"""Auth dependencies used by the API routes."""
import jwt
from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from .db import get_db
from .models import User
from .security import decode_token


def current_user(authorization: str = Header(default=""),
                 db: Session = Depends(get_db)) -> User:
    if not authorization.startswith("Bearer "):
        raise HTTPException(401, "missing token")
    try:
        payload = decode_token(authorization[7:])
    except jwt.PyJWTError:
        raise HTTPException(401, "invalid token")
    if payload.get("type") != "access":
        raise HTTPException(401, "wrong token type")
    user = db.get(User, payload.get("sub"))
    if not user or user.status != "active":
        raise HTTPException(401, "no such user")
    return user


def require_admin(user: User = Depends(current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(403, "admin only")
    return user
