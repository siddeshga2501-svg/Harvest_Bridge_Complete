import os
from datetime import datetime, timedelta, timezone
from jose import jwt, JWTError
from passlib.context import CryptContext
from fastapi import Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
from .database import get_db
from .models import User

SECRET = os.getenv("SECRET_KEY", "local-only-change-me")
ALGORITHM = "HS256"
pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")
oauth2 = OAuth2PasswordBearer(tokenUrl="/api/auth/login")

def hash_password(password: str) -> str:
    return pwd_context.hash(password)

def verify_password(password: str, hashed: str) -> bool:
    return pwd_context.verify(password, hashed)

def make_token(user: User) -> str:
    expires = datetime.now(timezone.utc) + timedelta(minutes=int(os.getenv("ACCESS_TOKEN_MINUTES", "60")))
    return jwt.encode({"sub": str(user.id), "role": user.role, "type":"access", "exp": expires}, SECRET, algorithm=ALGORITHM)

def make_refresh_token(user: User) -> str:
    expires = datetime.now(timezone.utc) + timedelta(days=14)
    return jwt.encode({"sub": str(user.id), "role": user.role, "type":"refresh", "exp": expires}, SECRET, algorithm=ALGORITHM)

def user_from_refresh(token: str, db: Session) -> User:
    try:
        payload=jwt.decode(token,SECRET,algorithms=[ALGORITHM])
        if payload.get("type")!="refresh": raise ValueError("wrong token type")
        user=db.get(User,int(payload.get("sub","0")))
    except (JWTError,ValueError):
        raise HTTPException(401,"Refresh session expired. Please sign in again.")
    if not user or not user.is_active: raise HTTPException(401,"Account is unavailable")
    return user

def current_user(token: str = Depends(oauth2), db: Session = Depends(get_db)) -> User:
    try:
        payload = jwt.decode(token, SECRET, algorithms=[ALGORITHM])
        if payload.get("type") != "access": raise ValueError("wrong token type")
        user_id = int(payload.get("sub", "0"))
    except (JWTError, ValueError):
        raise HTTPException(401, "Invalid or expired sign-in. Please log in again.", headers={"WWW-Authenticate": "Bearer"})
    user = db.get(User, user_id)
    if not user or not user.is_active:
        raise HTTPException(401, "Account is unavailable")
    return user

def allow_roles(*roles):
    def dependency(user: User = Depends(current_user)):
        if user.role not in roles:
            raise HTTPException(403, "This account does not have access to this feature")
        return user
    return dependency
