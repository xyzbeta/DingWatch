from fastapi import FastAPI, Request, Depends, Header, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from .database import engine, Base, get_db
from .routers import debug, config, webhook, settings, auth, stats, docs
from . import crud, models, database, schemas
from .config import settings as app_config
from .logger import logger
from fastapi.responses import RedirectResponse
from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime, timedelta
import json

# Create tables
Base.metadata.create_all(bind=engine)

# Init Admin
def init_admin():
    db = next(get_db())
    try:
        if not crud.get_admin_by_username(db, app_config.ADMIN_USERNAME):
            logger.info("Initializing default admin user...")
            crud.create_admin(db, schemas.AdminCreate(
                username=app_config.ADMIN_USERNAME, 
                password=app_config.ADMIN_PASSWORD,
                nickname="Administrator",
                description="Default System Administrator"
            ))
    finally:
        db.close()

def init_migration():
    db = next(get_db())
    try:
        # Add message_template column if missing (v1.3 upgrade)
        import sqlalchemy as sa
        inspector = sa.inspect(engine)
        columns = [c["name"] for c in inspector.get_columns("notification_channels")]
        if "message_template" not in columns:
            with engine.connect() as conn:
                conn.execute(sa.text("ALTER TABLE notification_channels ADD COLUMN message_template TEXT"))
                conn.commit()
            logger.info("Added message_template column to notification_channels")

        # Create silences tables if missing (v1.4 upgrade)
        existing_tables = inspector.get_table_names()
        if "silences" not in existing_tables:
            models.Silence.__table__.create(bind=engine)
            models.SilenceCondition.__table__.create(bind=engine)
            logger.info("Created silences and silence_conditions tables")

        # Check if any channel exists
        if db.query(models.NotificationChannel).first():
            return
            
        logger.info("Migrating legacy DingTalk settings to NotificationChannel...")
        
        # Get old settings
        url = crud.get_system_setting(db, "dingtalk_webhook_url")
        secret = crud.get_system_setting(db, "dingtalk_secret")
        token = crud.get_system_setting(db, "dingtalk_access_token")
        
        # Even if some are missing, if we have URL, we might want to migrate? 
        # But old logic required all three. Let's stick to that.
        # Fallback to env if not in DB? No, migration is about DB state.
        
        if url and secret and token:
            # Create channel
            config = {
                "webhook_url": url,
                "secret": secret,
                "access_token": token
            }
            channel = models.NotificationChannel(
                name="默认钉钉机器人",
                type="dingtalk",
                config=json.dumps(config),
                is_enabled=True
            )
            db.add(channel)
            db.commit()
            db.refresh(channel)
            
            # Set default
            crud.set_system_setting(db, "default_channel_id", str(channel.id))
            logger.info(f"Migrated DingTalk settings to channel {channel.id}")
            
    except Exception as e:
        logger.error(f"Migration failed: {e}")
    finally:
        db.close()

init_admin()
init_migration()

app = FastAPI(
    title="DingWatch",
    version="1.4.3",
    docs_url="/api/docs",
    redoc_url=None,
    openapi_url="/api/openapi.json"
)

app.mount("/static", StaticFiles(directory="static"), name="static")

@app.middleware("http")
async def cache_control_middleware(request: Request, call_next):
    response = await call_next(request)
    if request.url.path.startswith("/static"):
        response.headers["Cache-Control"] = "public, max-age=604800"
    return response

# Scheduler for Auto-Pruning
scheduler = BackgroundScheduler()

def prune_logs():
    db = next(get_db())
    try:
        # Prune old request logs
        retention = crud.get_system_setting(db, "log_retention_days")
        days = int(retention) if retention else 30
        cutoff = datetime.now() - timedelta(days=days)
        deleted = db.query(models.RequestLog).filter(models.RequestLog.timestamp < cutoff).delete()
        if deleted > 0:
            logger.info(f"Auto-pruned {deleted} old request logs (older than {days} days).")

        # Prune expired/inactive silences (keep for 7 days after expiry/cancel)
        silence_retention = crud.get_system_setting(db, "silence_retention_days")
        silence_days = int(silence_retention) if silence_retention else 7
        silence_cutoff = datetime.now() - timedelta(days=silence_days)
        old_silences = db.query(models.Silence).filter(
            models.Silence.ends_at < silence_cutoff
        ).delete()
        if old_silences > 0:
            logger.info(f"Auto-pruned {old_silences} expired silence rules.")

        db.commit()
    except Exception as e:
        logger.error(f"Auto-prune failed: {e}")
    finally:
        db.close()

scheduler.add_job(prune_logs, 'cron', hour=3, minute=0)
scheduler.start()

@app.on_event("shutdown")
def shutdown_scheduler():
    scheduler.shutdown()

# API Token Dependency
async def verify_api_token(request: Request, x_api_token: str = Header(None), db: Session = Depends(get_db)):
    # Skip for webhook (if using separate auth), login, static, and UI pages
    path = request.url.path
    if path.startswith("/static") or path in ["/login", "/docs", "/openapi.json", "/"]:
        return
    
    # Internal UI requests use Cookies. External use Token.
    # If cookie exists, we MUST validate it. Just existence is not enough.
    token_cookie = request.cookies.get("access_token")
    if token_cookie:
        from .routers.auth import get_current_admin
        try:
            # Re-use auth logic to validate cookie
            # When calling manually, we must match the signature: get_current_admin(request=None, token_str=..., db=...)
            await get_current_admin(token_str=token_cookie, db=db)
            return
        except HTTPException:
            # If cookie is invalid, fall through to check API Token
            pass

    # If no cookie or invalid cookie, and path is API, require X-API-Token
    if path.startswith("/api/v1"):
        # Exception for login API
        if path == "/api/v1/auth/login":
            return
        
        if not x_api_token:
             # If it's webhook, check system setting
             # Replay endpoint should be protected always, so we exclude it from bypass if possible
             # But replay is under /api/v1/webhook... let's check exact path
             if path.startswith("/api/v1/webhook") and not path.endswith("/replay"):
                 webhook_auth_enabled = crud.get_system_setting(db, "webhook_auth_enabled")
                 if webhook_auth_enabled == "true":
                     raise HTTPException(status_code=401, detail="Missing X-API-Token header")
                 return

             raise HTTPException(status_code=401, detail="Missing X-API-Token header")
        
        # Verify token
        token_record = db.query(models.ApiToken).filter(
            models.ApiToken.token == x_api_token,
            models.ApiToken.is_active == True
        ).first()
        
        if not token_record:
            raise HTTPException(status_code=403, detail="Invalid API Token")


templates = Jinja2Templates(directory="app/templates")
app.state.templates = templates

# Middleware to check auth for pages
@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    # Force HTTPS behind proxy
    if "x-forwarded-proto" in request.headers and request.headers["x-forwarded-proto"] == "https":
        request.scope["scheme"] = "https"
        
    if request.url.path in ["/login", "/docs", "/openapi.json"]:
        return await call_next(request)
    if request.url.path.startswith("/static") or request.url.path.startswith("/api/v1/webhook"):
        return await call_next(request)
        
    token = request.cookies.get("access_token")
    if not token and not request.url.path.startswith("/api"):
        return RedirectResponse(url="/login")
        
    response = await call_next(request)
    return response

@app.get("/api/health")
def health_check():
    import os
    db_size = 0
    db_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "dingwatch.db")
    if os.path.exists(db_path):
        db_size = os.path.getsize(db_path)
    
    return {
        "status": "ok",
        "version": "1.4.3",
        "db_size_bytes": db_size,
        "db_wal_enabled": True 
    }

app.include_router(auth.router)
app.include_router(debug.router, dependencies=[Depends(verify_api_token)])
app.include_router(config.router, dependencies=[Depends(verify_api_token)])
app.include_router(webhook.router, dependencies=[Depends(verify_api_token)]) # Auth check logic inside verify_api_token handles conditional bypass
app.include_router(settings.router, dependencies=[Depends(verify_api_token)])
app.include_router(stats.router, dependencies=[Depends(verify_api_token)])
app.include_router(docs.router) # No auth required for docs, or maybe yes? Let's require login via middleware

@app.get("/login")
def login_page(request: Request):
    return templates.TemplateResponse(request, "login.html")

@app.get("/profile")
def profile_page(request: Request):
    return templates.TemplateResponse(request, "profile.html")

@app.get("/")
def read_root(request: Request):
    return templates.TemplateResponse(request, "index.html")

@app.get("/logs")
def view_logs(request: Request, page: int = 1, q: str = None, db: Session = Depends(get_db)):
    limit = 50
    skip = (page - 1) * limit
    logs = crud.get_request_logs(db, skip=skip, limit=limit, query=q)
    total = crud.count_request_logs(db, query=q)
    total_pages = (total + limit - 1) // limit
    
    return templates.TemplateResponse(request, "debug.html", {
        "logs": logs,
        "page": page,
        "total_pages": total_pages,
        "query": q,
        "total": total
    })

@app.get("/users")
def view_users(request: Request):
    return templates.TemplateResponse(request, "users.html")

@app.get("/rules")
def view_rules(request: Request):
    return templates.TemplateResponse(request, "rules.html")

@app.get("/silences")
def view_silences(request: Request):
    return templates.TemplateResponse(request, "silences.html")

@app.get("/system")
def view_system(request: Request):
    return templates.TemplateResponse(request, "system.html")

@app.get("/health")
def view_health(request: Request):
    return templates.TemplateResponse(request, "health.html")
