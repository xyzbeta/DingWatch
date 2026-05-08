from fastapi import APIRouter, Depends, HTTPException, Body
from sqlalchemy.orm import Session
from .. import database, crud, schemas, models
from ..services.dingtalk import dingtalk_client
from ..logger import logger
import json
import secrets
from typing import List
from ..config import settings as env_settings
from datetime import datetime


def _is_dingtalk_success(errcode) -> bool:
    """Check if a DingTalk errcode indicates success, handling both string and int."""
    if errcode is None:
        return False
    try:
        return int(errcode) == 0
    except (ValueError, TypeError):
        return False


router = APIRouter(
    prefix="/api/v1/settings",
    tags=["settings"]
)

@router.get("/export")
def export_config(db: Session = Depends(database.get_db)):
    """
    Export all configurations: Rules, Channels, Users, Teams, Tags, SystemSettings
    """
    data = {
        "version": "1.4",
        "exported_at": datetime.now().isoformat(),
        "channels": [schemas.NotificationChannel.from_orm(c).dict() for c in crud.get_notification_channels(db, limit=1000)],
        "rules": [schemas.Rule.from_orm(r).dict() for r in crud.get_rules(db, limit=1000)],
        "users": [schemas.User.from_orm(u).dict() for u in crud.get_users(db, limit=1000)],
        "teams": [schemas.Team.from_orm(t).dict() for t in crud.get_teams(db, limit=1000)],
        "tags": [schemas.Tag.from_orm(t).dict() for t in crud.get_tags(db)],
        # Export system settings except maybe sensitive ones? No, export all for migration.
        # "settings": ... (Need a crud for getting all settings)
    }
    return data

@router.post("/import")
def import_config(config_data: dict = Body(...), db: Session = Depends(database.get_db)):
    """
    Import configuration. Strategy: Skip existing (by name/id) or Overwrite?
    Simple strategy: Create if not exists by Name.
    """
    try:
        # Import Channels
        for c in config_data.get("channels", []):
            # Check if exists by name
            existing = db.query(models.NotificationChannel).filter(models.NotificationChannel.name == c["name"]).first()
            if not existing:
                crud.create_notification_channel(db, schemas.NotificationChannelCreate(**c))
        
        # Import Users
        for u in config_data.get("users", []):
            existing = db.query(models.User).filter(models.User.phone_number == u["phone_number"]).first()
            if not existing:
                crud.create_user(db, schemas.UserCreate(**u))
                
        # Import Teams (Complex due to relationships)
        # ... Simplification for MVP: Just basic imports
        
        # Import Rules (Complex)
        # ...
        
        return {"status": "success", "message": "Import completed (Partial support)"}
        
    except Exception as e:
        logger.error(f"Import failed: {e}", exc_info=True)
        raise HTTPException(status_code=400, detail="Import failed due to invalid configuration data")

@router.post("/announcement")
def send_announcement(announcement: schemas.AnnouncementCreate, db: Session = Depends(database.get_db)):
    # 1. Determine targets
    target_phones = set()
    is_at_all = False
    
    if announcement.target_type == "all":
        # Target type "all" now means @All in DingTalk group
        is_at_all = True
            
    elif announcement.target_type == "team":
        if announcement.target_ids:
            teams = db.query(models.Team).filter(models.Team.id.in_(announcement.target_ids)).all()
            for team in teams:
                for u in team.users:
                    if u.is_active and u.phone_number: target_phones.add(u.phone_number)
                    
    elif announcement.target_type == "user":
        if announcement.target_ids:
            users = db.query(models.User).filter(models.User.id.in_(announcement.target_ids)).all()
            for u in users:
                if u.is_active and u.phone_number: target_phones.add(u.phone_number)
                
    if not is_at_all and not target_phones:
        raise HTTPException(status_code=400, detail="No valid recipients found")
        
    # 2. Determine Channel
    channel = None
    if announcement.channel_id:
        channel = crud.get_notification_channel(db, announcement.channel_id)
    
    if not channel:
        # Try default
        def_id = crud.get_system_setting(db, "default_channel_id")
        if def_id:
            channel = crud.get_notification_channel(db, int(def_id))
        else:
            # Fallback: Pick the first enabled channel
            channels = crud.get_notification_channels(db)
            for c in channels:
                if c.is_enabled:
                    channel = c
                    # Optionally set it as default for future
                    crud.set_system_setting(db, "default_channel_id", str(c.id))
                    break

    if not channel:
        raise HTTPException(status_code=400, detail="No valid notification channel available (Please configure at least one enabled channel)")
        
    if not channel.is_enabled:
        raise HTTPException(status_code=400, detail="Selected channel is disabled")

    # 3. Send DingTalk message
    text_content = f"### 📢 系统公告\n\n**{announcement.title}**\n\n{announcement.content}"
    
    # Append @mentions to text for visual highlighting in Markdown
    if is_at_all:
        text_content += "\n\n@所有人"
    elif target_phones:
        # DingTalk Markdown supports @phone for highlighting
        mention_text = " ".join([f"@{p}" for p in target_phones])
        text_content += f"\n\n{mention_text}"
    
    try:
        config = json.loads(channel.config)
        result_wrapper = dingtalk_client.send_markdown(
            title=f"公告: {announcement.title}",
            text=text_content,
            webhook_url=config.get("webhook_url"),
            secret=config.get("secret"),
            access_token=config.get("access_token"),
            at_mobiles=list(target_phones),
            at_all=is_at_all
        )
        
        # 4. Log to RequestLog
        # Log the *result* too.
        log_entry = crud.create_request_log(
            db,
            headers=json.dumps({"source": "system_announcement", "type": "manual_push", "at_all": is_at_all}),
            body=json.dumps(announcement.dict()),
            channel_name=channel.name
        )
        
        result = result_wrapper.get("response", {}) if "response" in result_wrapper else result_wrapper
        
        crud.update_request_log_status(
            db,
            log_entry.id,
            "success" if _is_dingtalk_success(result.get("errcode")) else "failed",
            response=json.dumps(result),
            dingtalk_request_body=json.dumps(result_wrapper.get("request_payload", {})),
            matched_rule="SYSTEM_ANNOUNCEMENT",
            channel_name=channel.name
        )
        
        return {"status": "success", "count": "ALL" if is_at_all else len(target_phones)}
        
    except Exception as e:
        logger.error(f"Announcement failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to send announcement")

# Channel Management APIs

@router.get("/channels", response_model=List[schemas.NotificationChannel])
def get_channels(db: Session = Depends(database.get_db)):
    return crud.get_notification_channels(db)

@router.post("/channels", response_model=schemas.NotificationChannel)
def create_channel(channel: schemas.NotificationChannelCreate, db: Session = Depends(database.get_db)):
    return crud.create_notification_channel(db, channel)

@router.put("/channels/{channel_id}", response_model=schemas.NotificationChannel)
def update_channel(channel_id: int, channel: schemas.NotificationChannelCreate, db: Session = Depends(database.get_db)):
    updated = crud.update_notification_channel(db, channel_id, channel)
    if not updated:
        raise HTTPException(status_code=404, detail="Channel not found")
    return updated

@router.delete("/channels/{channel_id}")
def delete_channel(channel_id: int, db: Session = Depends(database.get_db)):
    success = crud.delete_notification_channel(db, channel_id)
    if not success:
        raise HTTPException(status_code=404, detail="Channel not found")
    return {"ok": True}

@router.post("/channels/default")
def set_default_channel(body: dict = Body(...), db: Session = Depends(database.get_db)):
    channel_id = body.get("id")
    if not channel_id:
        raise HTTPException(status_code=400, detail="Missing channel id")
    
    channel = crud.get_notification_channel(db, channel_id)
    if not channel:
         raise HTTPException(status_code=404, detail="Channel not found")
         
    crud.set_system_setting(db, "default_channel_id", str(channel_id))
    return {"status": "success"}

@router.get("/channels/default")
def get_default_channel(db: Session = Depends(database.get_db)):
    val = crud.get_system_setting(db, "default_channel_id")
    return {"id": int(val) if val else None}

@router.post("/channels/test")
def test_channel_config(channel: schemas.NotificationChannelCreate, db: Session = Depends(database.get_db)):
    try:
        config = json.loads(channel.config)
        # Assuming DingTalk for now
        result_wrapper = dingtalk_client.send_markdown(
            title="DingWatch 测试",
            text="### 通道配置测试\n\n您的配置已生效！",
            webhook_url=config.get("webhook_url"),
            secret=config.get("secret"),
            access_token=config.get("access_token")
        )

        # Log to RequestLog
        log_entry = crud.create_request_log(
            db,
            headers=json.dumps({"source": "system_test", "type": "test_push"}),
            body=json.dumps(channel.dict()),
            channel_name=channel.name
        )

        result = result_wrapper.get("response", {}) if "response" in result_wrapper else result_wrapper
        
        crud.update_request_log_status(
            db,
            log_entry.id,
            "success" if _is_dingtalk_success(result.get("errcode")) else "failed",
            response=json.dumps(result),
            dingtalk_request_body=json.dumps(result_wrapper.get("request_payload", {})),
            matched_rule="SYSTEM_TEST",
            channel_name=channel.name
        )

        # Check for errors: either top-level (network error) or inner response (DingTalk API error)
        top_errcode = result_wrapper.get("errcode")
        inner_errcode = result.get("errcode")
        actual_errcode = top_errcode if top_errcode is not None else inner_errcode

        if actual_errcode is not None and not _is_dingtalk_success(actual_errcode):
            err_msg = result_wrapper.get("errmsg") or result.get("errmsg", "Unknown error")
            raise HTTPException(status_code=400, detail=f"Error: {err_msg}")
             
        return {"status": "success", "response": result_wrapper}
    except Exception as e:
        logger.error(f"Channel test failed: {e}", exc_info=True)
        raise HTTPException(status_code=400, detail="Channel test failed")

# API Tokens
@router.get("/tokens", response_model=List[schemas.ApiToken])
def get_tokens(db: Session = Depends(database.get_db)):
    return crud.get_api_tokens(db)

@router.post("/tokens", response_model=schemas.ApiToken)
def create_token(token_in: schemas.ApiTokenCreate, db: Session = Depends(database.get_db)):
    # Generate random token
    token_str = secrets.token_hex(32)
    return crud.create_api_token(db, name=token_in.name, token=token_str)

@router.delete("/tokens/{token_id}")
def delete_token(token_id: int, db: Session = Depends(database.get_db)):
    success = crud.delete_api_token(db, token_id)
    if not success:
        raise HTTPException(status_code=404, detail="Token not found")
    return {"ok": True}

# System Config (Auth Switch)
@router.get("/system", response_model=schemas.SystemSettings)
def get_system_config(db: Session = Depends(database.get_db)):
    auth_enabled = crud.get_system_setting(db, "webhook_auth_enabled")
    retention = crud.get_system_setting(db, "log_retention_days")
    silence_retention = crud.get_system_setting(db, "silence_retention_days")
    return schemas.SystemSettings(
        webhook_auth_enabled=(auth_enabled == "true"),
        log_retention_days=int(retention) if retention else 30,
        silence_retention_days=int(silence_retention) if silence_retention else 7,
    )

@router.post("/system")
def save_system_config(settings: schemas.SystemSettings, db: Session = Depends(database.get_db)):
    crud.set_system_setting(db, "webhook_auth_enabled", "true" if settings.webhook_auth_enabled else "false")
    crud.set_system_setting(db, "log_retention_days", str(settings.log_retention_days))
    crud.set_system_setting(db, "silence_retention_days", str(settings.silence_retention_days))
    return {"status": "success"}

# Silence Management (v1.4)
@router.get("/silences", response_model=List[schemas.Silence])
def get_silences(include_expired: bool = True, db: Session = Depends(database.get_db)):
    return crud.get_silences(db, include_expired=include_expired)


def _bj_time(dt) -> str:
    """Convert UTC datetime to Beijing time string."""
    from datetime import timedelta, timezone
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    bj = dt.astimezone(timezone(timedelta(hours=8)))
    return bj.strftime("%Y-%m-%d %H:%M")


def _notify_silence(db: Session, silence, action: str):
    """Send a DingTalk notification about a silence event (best-effort)."""
    try:
        def_id = crud.get_system_setting(db, "default_channel_id")
        if not def_id:
            return
        channel = crud.get_notification_channel(db, int(def_id))
        if not channel or not channel.is_enabled:
            return

        cond_lines = "\n".join(f"- {c.key} = {c.value}" for c in silence.conditions)
        mode_label = "全部满足" if silence.match_mode == "AND" else "任一满足"

        if action == "create":
            title = "告警屏蔽已启用"
            content = (
                f"**告警屏蔽已启用**\n\n"
                f"名称：{silence.name}\n\n"
                f"原因：{silence.reason or '-'}\n\n"
                f"生效时间：{_bj_time(silence.starts_at)}\n\n"
                f"截止时间：{_bj_time(silence.ends_at)}\n\n"
                f"匹配模式：{mode_label}\n\n"
                f"匹配条件：\n{cond_lines}\n\n"
                f"> 匹配此条件的告警将被静默，不会推送到钉钉。"
            )
        else:  # cancel
            title = "告警屏蔽已取消"
            content = (
                f"**告警屏蔽已取消**\n\n"
                f"名称：{silence.name}\n\n"
                f"原因：{silence.reason or '-'}\n\n"
                f"生效时间：{_bj_time(silence.starts_at)}\n\n"
                f"截止时间：{_bj_time(silence.ends_at)}（提前取消）\n\n"
                f"匹配模式：{mode_label}\n\n"
                f"匹配条件：\n{cond_lines}\n\n"
                f"> 告警推送已恢复正常。"
            )

        config = json.loads(channel.config)
        dingtalk_client.send_markdown(
            title=title,
            text=content,
            webhook_url=config.get("webhook_url"),
            secret=config.get("secret"),
            access_token=config.get("access_token"),
        )
    except Exception:
        pass


@router.post("/silences", response_model=schemas.Silence)
def create_silence(silence: schemas.SilenceCreate, db: Session = Depends(database.get_db)):
    s = crud.create_silence(db=db, silence=silence)
    _notify_silence(db, s, "create")
    return s


@router.put("/silences/{silence_id}", response_model=schemas.Silence)
def update_silence_endpoint(silence_id: int, silence: schemas.SilenceCreate, db: Session = Depends(database.get_db)):
    s = crud.update_silence(db, silence_id, silence)
    if not s:
        raise HTTPException(status_code=404, detail="Silence not found")
    return s


@router.delete("/silences/{silence_id}")
def cancel_or_delete_silence(silence_id: int, permanent: bool = False, db: Session = Depends(database.get_db)):
    if permanent:
        ok = crud.delete_silence(db, silence_id)
        if not ok:
            raise HTTPException(status_code=404, detail="Silence not found")
        return {"ok": True}
    s = crud.cancel_silence(db, silence_id)
    if not s:
        raise HTTPException(status_code=404, detail="Silence not found")
    _notify_silence(db, s, "cancel")
    return {"ok": True}


# Deprecated / Backward Compatibility Endpoints
