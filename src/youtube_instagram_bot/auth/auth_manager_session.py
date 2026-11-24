"""
Production authentication module — direct bcrypt (no passlib).
"""

import logging
import bcrypt
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import create_engine, Column, String, Boolean, DateTime, Text
from sqlalchemy.orm import declarative_base, sessionmaker
from jose import jwt, JWTError

log = logging.getLogger(__name__)

# ── Password hashing ──────────────────────────────────────────────────────────

def hash_password(plain: str) -> str:
    pw = plain.encode("utf-8")[:72]
    return bcrypt.hashpw(pw, bcrypt.gensalt(rounds=12)).decode("utf-8")

def verify_password(plain: str, hashed: str) -> bool:
    try:
        pw = plain.encode("utf-8")[:72]
        hb = hashed.encode("utf-8") if isinstance(hashed, str) else hashed
        return bcrypt.checkpw(pw, hb)
    except Exception:
        return False

# ── SQLAlchemy models ──────────────────────────────────────────────────────────

AuthBase = declarative_base()

class UserRow(AuthBase):
    __tablename__ = "users"
    username       = Column(String(64),  primary_key=True)
    password_hash  = Column(String(256), nullable=False)
    email          = Column(String(256), nullable=True)
    full_name      = Column(String(128), nullable=True)
    is_active      = Column(Boolean,     default=True)
    is_admin       = Column(Boolean,     default=False)
    created_at     = Column(DateTime,    default=datetime.utcnow)
    last_login     = Column(DateTime,    nullable=True)

class TokenRow(AuthBase):
    __tablename__ = "refresh_tokens"
    token      = Column(String(512), primary_key=True)
    username   = Column(String(64),  nullable=False)
    expires_at = Column(DateTime,    nullable=False)
    revoked    = Column(Boolean,     default=False)

# ── AuthManager ───────────────────────────────────────────────────────────────

class AuthManager:
    def __init__(self, database_url: str, secret_key: str,
                 algorithm: str = "HS256",
                 access_expire_minutes: int = 1440,
                 refresh_expire_days: int = 30):
        self.secret_key            = secret_key
        self.algorithm             = algorithm
        self.access_expire_minutes = access_expire_minutes
        self.refresh_expire_days   = refresh_expire_days
        self.engine       = create_engine(database_url, echo=False, connect_args={"check_same_thread": False})
        self.SessionLocal = sessionmaker(bind=self.engine, autocommit=False, autoflush=False)
        AuthBase.metadata.create_all(bind=self.engine)
        log.info("auth.manager.ready")

    def seed_admin(self, username: str, password: str) -> None:
        with self.SessionLocal() as s:
            if s.get(UserRow, username):
                return
            s.add(UserRow(username=username, password_hash=hash_password(password),
                          is_active=True, is_admin=True, full_name="Administrator"))
            s.commit()
            log.info("auth.admin.seeded", extra={"username": username})

    def register(self, username: str, password: str,
                 email: str = "", full_name: str = "") -> dict:
        with self.SessionLocal() as s:
            if s.get(UserRow, username):
                raise ValueError(f"Username '{username}' is already taken")
            s.add(UserRow(username=username, password_hash=hash_password(password),
                          email=email, full_name=full_name, is_active=True, is_admin=False))
            s.commit()
        return self.get_user(username)

    def get_user(self, username: str) -> Optional[dict]:
        with self.SessionLocal() as s:
            u = s.get(UserRow, username)
            if not u:
                return None
            return {
                "username":   u.username,
                "email":      u.email or "",
                "full_name":  u.full_name or "",
                "is_active":  u.is_active,
                "is_admin":   u.is_admin,
                "created_at": u.created_at.isoformat() if u.created_at else "",
                "last_login": u.last_login.isoformat() if u.last_login else None,
            }

    def authenticate(self, username: str, password: str) -> Optional[dict]:
        with self.SessionLocal() as s:
            u = s.get(UserRow, username)
            if not u or not u.is_active:
                return None
            if not verify_password(password, u.password_hash):
                return None
            u.last_login = datetime.utcnow()
            s.commit()
        return self.get_user(username)

    def change_password(self, username: str, old_password: str, new_password: str) -> bool:
        with self.SessionLocal() as s:
            u = s.get(UserRow, username)
            if not u or not verify_password(old_password, u.password_hash):
                return False
            u.password_hash = hash_password(new_password)
            s.commit()
        return True

    # ── JWT ───────────────────────────────────────────────────────────────────

    def create_access_token(self, username: str) -> str:
        expire = datetime.now(timezone.utc) + timedelta(minutes=self.access_expire_minutes)
        return jwt.encode({"sub": username, "exp": expire, "type": "access"},
                          self.secret_key, algorithm=self.algorithm)

    def create_refresh_token(self, username: str) -> str:
        expire = datetime.now(timezone.utc) + timedelta(days=self.refresh_expire_days)
        token  = jwt.encode({"sub": username, "exp": expire, "type": "refresh"},
                            self.secret_key, algorithm=self.algorithm)
        with self.SessionLocal() as s:
            s.query(TokenRow).filter(
                TokenRow.username == username,
                TokenRow.expires_at < datetime.utcnow(),
            ).delete()
            s.add(TokenRow(token=token, username=username,
                           expires_at=expire.replace(tzinfo=None)))
            s.commit()
        return token

    def decode_access_token(self, token: str) -> Optional[str]:
        try:
            payload = jwt.decode(token, self.secret_key, algorithms=[self.algorithm])
            if payload.get("type") != "access":
                return None
            return payload.get("sub")
        except JWTError:
            return None

    def refresh_access_token(self, refresh_token: str) -> Optional[str]:
        try:
            payload = jwt.decode(refresh_token, self.secret_key, algorithms=[self.algorithm])
            if payload.get("type") != "refresh":
                return None
            username = payload.get("sub")
        except JWTError:
            return None
        with self.SessionLocal() as s:
            row = s.get(TokenRow, refresh_token)
            if not row or row.revoked or row.expires_at < datetime.utcnow():
                return None
        return self.create_access_token(username)

    def revoke_refresh_token(self, refresh_token: str) -> bool:
        with self.SessionLocal() as s:
            row = s.get(TokenRow, refresh_token)
            if row:
                row.revoked = True
                s.commit()
                return True
        return False

    def revoke_all_tokens(self, username: str) -> int:
        with self.SessionLocal() as s:
            count = s.query(TokenRow).filter(
                TokenRow.username == username,
                TokenRow.revoked  == False,
            ).update({"revoked": True})
            s.commit()
        return count