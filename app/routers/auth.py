from fastapi import APIRouter, Depends, HTTPException, status, Request, Response
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from fastapi.responses import RedirectResponse, HTMLResponse
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
from typing import Optional
from jose import JWTError, jwt
import bcrypt
import os
import secrets
from .. import database, models, schemas, crud

# Configuration
SECRET_KEY = os.environ.get("DINGWATCH_JWT_SECRET") or os.environ.get("SECRET_KEY", "")
if not SECRET_KEY:
    SECRET_KEY = secrets.token_hex(32)
    logger = __import__('logging').getLogger('dingwatch')
    logger.warning("JWT SECRET_KEY not configured, using random key (sessions reset on restart)")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7  # 7 days

router = APIRouter(tags=["auth"])

def verify_password(plain_password, hashed_password):
    if not hashed_password:
        return False
    return bcrypt.checkpw(plain_password.encode('utf-8'), hashed_password.encode('utf-8'))

def get_password_hash(password):
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=15)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

# Dependency for API endpoints
async def get_current_admin(
    request: Request = None, 
    token_str: str = None,
    db: Session = Depends(database.get_db)
):
    # This dependency is tricky because we want to support both direct calling with a string token
    # AND dependency injection via Request.
    # FastAPI dependency injection matches parameters by name/type.
    
    # When used as Depends(get_current_admin), FastAPI injects 'request'. 'token_str' will be None.
    # When called manually like await get_current_admin(token_str=cookie_val, db=db), 'request' is None.
    
    token = None
    if token_str:
        token = token_str
    elif request:
        token = request.cookies.get("access_token")
        if not token:
            # Check Authorization header as fallback
            auth_header = request.headers.get("Authorization")
            if auth_header and auth_header.startswith("Bearer "):
                token = auth_header.split(" ")[1]
            
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
        
    admin = crud.get_admin_by_username(db, username=username)
    if admin is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    return admin

# Login Endpoint
@router.post("/login")
async def login(response: Response, form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(database.get_db)):
    admin = crud.get_admin_by_username(db, form_data.username)
    if not admin or not verify_password(form_data.password, admin.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": admin.username}, expires_delta=access_token_expires
    )
    
    response.set_cookie(
        key="access_token",
        value=access_token,
        httponly=True,
        samesite="lax",
        max_age=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        expires=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )
    return {"access_token": access_token, "token_type": "bearer"}

@router.post("/logout")
async def logout(response: Response):
    response.delete_cookie("access_token")
    return {"msg": "Logged out"}

# Profile API
@router.get("/api/v1/profile", response_model=schemas.Admin)
async def read_users_me(current_admin: models.Admin = Depends(get_current_admin)):
    return current_admin

@router.put("/api/v1/profile", response_model=schemas.Admin)
async def update_profile(
    profile: schemas.AdminUpdate, 
    current_admin: models.Admin = Depends(get_current_admin),
    db: Session = Depends(database.get_db)
):
    return crud.update_admin(db, current_admin.id, profile)
