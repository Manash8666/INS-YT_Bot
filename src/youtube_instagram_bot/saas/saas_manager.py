"""SaaS — Subscription tiers, usage limits, Stripe payments."""
import logging
from datetime import datetime, timedelta
from sqlalchemy import create_engine, Column, String, Boolean, Integer, DateTime, Float
from sqlalchemy.orm import declarative_base, sessionmaker
log = logging.getLogger(__name__)
SaaSBase = declarative_base()

TIERS = {
    "free":   {"price": 0,   "accounts": 1, "follows_per_day": 50,  "ai_requests": 10, "analytics_days": 7,  "webhooks": False, "proxy": False},
    "pro":    {"price": 29,  "accounts": 3, "follows_per_day": 150, "ai_requests": 100,"analytics_days": 30, "webhooks": True,  "proxy": True},
    "agency": {"price": 99,  "accounts": 10,"follows_per_day": 500, "ai_requests": 500,"analytics_days": 90, "webhooks": True,  "proxy": True},
}

class SubscriptionRow(SaaSBase):
    __tablename__ = "subscriptions"
    username       = Column(String(64),  primary_key=True)
    tier           = Column(String(32),  default="free")
    stripe_customer_id    = Column(String(128), nullable=True)
    stripe_subscription_id = Column(String(128), nullable=True)
    current_period_end    = Column(DateTime,     nullable=True)
    is_active      = Column(Boolean,     default=True)
    created_at     = Column(DateTime,    default=datetime.utcnow)
    ai_requests_used = Column(Integer,   default=0)
    ai_requests_reset = Column(DateTime, nullable=True)

class SaaSManager:
    def __init__(self, database_url: str, stripe_secret_key: str = ""):
        self.engine       = create_engine(database_url, echo=False, connect_args={"check_same_thread": False})
        self.SessionLocal = sessionmaker(bind=self.engine, autocommit=False, autoflush=False)
        SaaSBase.metadata.create_all(bind=self.engine)
        self._stripe_key = stripe_secret_key
        if stripe_secret_key:
            try:
                import stripe; stripe.api_key = stripe_secret_key
                self._stripe = stripe
            except ImportError:
                self._stripe = None
        else:
            self._stripe = None

    def get_subscription(self, username: str) -> dict:
        with self.SessionLocal() as s:
            r = s.get(SubscriptionRow, username)
            if not r:
                r = SubscriptionRow(username=username, tier="free", is_active=True)
                s.add(r); s.commit()
            tier_info = TIERS.get(r.tier, TIERS["free"])
            period_end = r.current_period_end.isoformat() if r.current_period_end else None
            is_expired = r.current_period_end and r.current_period_end < datetime.utcnow() and r.tier != "free"
            return {"username": username, "tier": r.tier, "is_active": r.is_active and not is_expired, "period_end": period_end, "limits": tier_info, "ai_requests_used": r.ai_requests_used or 0, "stripe_customer_id": r.stripe_customer_id}

    def set_tier(self, username: str, tier: str, days: int = 30, stripe_customer_id: str = None, stripe_subscription_id: str = None) -> dict:
        if tier not in TIERS:
            raise ValueError(f"Unknown tier: {tier}")
        with self.SessionLocal() as s:
            r = s.get(SubscriptionRow, username) or SubscriptionRow(username=username)
            r.tier = tier
            r.is_active = True
            r.current_period_end = datetime.utcnow() + timedelta(days=days) if tier != "free" else None
            if stripe_customer_id: r.stripe_customer_id = stripe_customer_id
            if stripe_subscription_id: r.stripe_subscription_id = stripe_subscription_id
            s.merge(r); s.commit()
        return self.get_subscription(username)

    def check_limit(self, username: str, limit_name: str) -> dict:
        sub = self.get_subscription(username)
        limit = sub["limits"].get(limit_name)
        return {"username": username, "limit_name": limit_name, "limit": limit, "allowed": limit is not False and limit is not None}

    def use_ai_request(self, username: str) -> bool:
        sub = self.get_subscription(username)
        max_ai = sub["limits"].get("ai_requests", 0)
        used   = sub["ai_requests_used"]
        if used >= max_ai:
            return False
        with self.SessionLocal() as s:
            r = s.get(SubscriptionRow, username)
            if r:
                r.ai_requests_used = (r.ai_requests_used or 0) + 1
                s.commit()
        return True

    def create_stripe_checkout(self, username: str, tier: str, success_url: str, cancel_url: str) -> dict:
        price_map = {"pro": "price_pro_monthly_placeholder", "agency": "price_agency_monthly_placeholder"}
        if not self._stripe:
            return {"mode": "simulation", "url": f"#stripe-not-configured-{tier}", "message": "Add STRIPE_SECRET_KEY to .env to enable payments"}
        try:
            session = self._stripe.checkout.Session.create(
                payment_method_types=["card"],
                line_items=[{"price": price_map.get(tier), "quantity": 1}],
                mode="subscription",
                success_url=success_url + "?session_id={CHECKOUT_SESSION_ID}",
                cancel_url=cancel_url,
                metadata={"username": username, "tier": tier},
            )
            return {"mode": "live", "url": session.url, "session_id": session.id}
        except Exception as e:
            return {"mode": "live", "error": str(e)}

    @staticmethod
    def get_tier_info() -> dict:
        return TIERS