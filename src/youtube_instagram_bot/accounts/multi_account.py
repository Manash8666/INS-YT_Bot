"""Multi-Account Manager — manage multiple IG + YT accounts."""
import logging
from datetime import datetime
from sqlalchemy import create_engine, Column, String, Boolean, DateTime, Enum as SAEnum
from sqlalchemy.orm import declarative_base, sessionmaker
import enum
log = logging.getLogger(__name__)
AccountBase = declarative_base()

class AccountPlatform(str, enum.Enum):
    INSTAGRAM = "instagram"
    YOUTUBE   = "youtube"
    RUMBLE    = "rumble"

class AccountRow(AccountBase):
    __tablename__ = "managed_accounts"
    id              = Column(String(64),  primary_key=True)
    platform        = Column(String(32),  nullable=False)
    display_name    = Column(String(128), nullable=False)
    username        = Column(String(128), nullable=True)
    access_token    = Column(String(2048), nullable=True)   # encrypted at rest
    refresh_token   = Column(String(2048), nullable=True)
    client_id       = Column(String(512), nullable=True)
    client_secret   = Column(String(512), nullable=True)
    user_id         = Column(String(128), nullable=True)
    is_active       = Column(Boolean,     default=True)
    is_default      = Column(Boolean,     default=False)
    followers_count = Column(String(32),  nullable=True)
    created_at      = Column(DateTime,    default=datetime.utcnow)
    last_used       = Column(DateTime,    nullable=True)
    tags            = Column(String(512), nullable=True)   # e.g. "personal,main"
    notes           = Column(String(1024), nullable=True)

class MultiAccountManager:
    """Manage multiple Instagram and YouTube accounts in one place."""
    def __init__(self, database_url: str):
        self.engine       = create_engine(database_url, echo=False, connect_args={"check_same_thread": False})
        self.SessionLocal = sessionmaker(bind=self.engine, autocommit=False, autoflush=False)
        AccountBase.metadata.create_all(bind=self.engine)

    def add_account(self, platform: str, display_name: str, **kwargs) -> dict:
        import uuid
        account_id = str(uuid.uuid4())[:12]
        with self.SessionLocal() as s:
            # If this is the first account for the platform, make it default
            existing = s.query(AccountRow).filter(AccountRow.platform==platform).count()
            acc = AccountRow(id=account_id, platform=platform, display_name=display_name, is_default=(existing==0), **{k:v for k,v in kwargs.items() if hasattr(AccountRow, k)})
            s.add(acc); s.commit()
        return self.get_account(account_id)

    def get_account(self, account_id: str) -> dict | None:
        with self.SessionLocal() as s:
            r = s.get(AccountRow, account_id)
            return self._row_to_dict(r) if r else None

    def list_accounts(self, platform: str = None) -> list[dict]:
        with self.SessionLocal() as s:
            q = s.query(AccountRow)
            if platform:
                q = q.filter(AccountRow.platform==platform)
            return [self._row_to_dict(r) for r in q.order_by(AccountRow.is_default.desc(), AccountRow.display_name).all()]

    def update_account(self, account_id: str, **kwargs) -> dict:
        with self.SessionLocal() as s:
            r = s.get(AccountRow, account_id)
            if not r:
                raise ValueError(f"Account {account_id} not found")
            for k, v in kwargs.items():
                if hasattr(r, k):
                    setattr(r, k, v)
            s.commit()
        return self.get_account(account_id)

    def set_default(self, account_id: str, platform: str) -> None:
        with self.SessionLocal() as s:
            s.query(AccountRow).filter(AccountRow.platform==platform).update({"is_default": False})
            r = s.get(AccountRow, account_id)
            if r:
                r.is_default = True
            s.commit()

    def delete_account(self, account_id: str) -> bool:
        with self.SessionLocal() as s:
            r = s.get(AccountRow, account_id)
            if r:
                s.delete(r); s.commit(); return True
        return False

    def get_default(self, platform: str) -> dict | None:
        with self.SessionLocal() as s:
            r = s.query(AccountRow).filter(AccountRow.platform==platform, AccountRow.is_default==True).first()
            return self._row_to_dict(r) if r else None

    def mark_used(self, account_id: str) -> None:
        with self.SessionLocal() as s:
            r = s.get(AccountRow, account_id)
            if r:
                r.last_used = datetime.utcnow(); s.commit()

    def stats(self) -> dict:
        with self.SessionLocal() as s:
            total = s.query(AccountRow).count()
            by_platform = {}
            for p in ["instagram","youtube","rumble"]:
                by_platform[p] = s.query(AccountRow).filter(AccountRow.platform==p).count()
            return {"total": total, "by_platform": by_platform}

    def _row_to_dict(self, r: AccountRow) -> dict:
        return {"id": r.id, "platform": r.platform, "display_name": r.display_name, "username": r.username, "user_id": r.user_id, "is_active": r.is_active, "is_default": r.is_default, "followers_count": r.followers_count, "created_at": r.created_at.isoformat() if r.created_at else "", "last_used": r.last_used.isoformat() if r.last_used else None, "tags": r.tags or "", "notes": r.notes or ""}