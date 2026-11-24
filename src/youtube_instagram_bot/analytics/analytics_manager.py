"""Analytics — historical metrics stored in SQLite, served as time-series."""
import logging
from datetime import datetime, timedelta, timezone
from sqlalchemy import create_engine, Column, String, Integer, Float, DateTime
from sqlalchemy.orm import declarative_base, sessionmaker
log = logging.getLogger(__name__)
AnalyticsBase = declarative_base()

class MetricRow(AnalyticsBase):
    __tablename__ = "analytics_metrics"
    id          = Column(Integer, primary_key=True, autoincrement=True)
    platform    = Column(String(32),  nullable=False)
    account_id  = Column(String(128), nullable=False)
    metric_name = Column(String(64),  nullable=False)   # followers, views, likes, watch_hours
    value       = Column(Float,       nullable=False)
    recorded_at = Column(DateTime,    default=datetime.utcnow)

class AnalyticsManager:
    def __init__(self, database_url: str):
        self.engine       = create_engine(database_url, echo=False, connect_args={"check_same_thread": False})
        self.SessionLocal = sessionmaker(bind=self.engine, autocommit=False, autoflush=False)
        AnalyticsBase.metadata.create_all(bind=self.engine)

    def record(self, platform: str, account_id: str, metric_name: str, value: float) -> None:
        with self.SessionLocal() as s:
            s.add(MetricRow(platform=platform, account_id=account_id, metric_name=metric_name, value=value))
            s.commit()

    def get_series(self, platform: str, account_id: str, metric_name: str, days: int = 30) -> list[dict]:
        since = datetime.utcnow() - timedelta(days=days)
        with self.SessionLocal() as s:
            rows = (s.query(MetricRow)
                    .filter(MetricRow.platform==platform, MetricRow.account_id==account_id, MetricRow.metric_name==metric_name, MetricRow.recorded_at>=since)
                    .order_by(MetricRow.recorded_at.asc()).all())
            return [{"date": r.recorded_at.strftime("%Y-%m-%d %H:%M"), "value": r.value} for r in rows]

    def get_summary(self, platform: str, account_id: str) -> dict:
        with self.SessionLocal() as s:
            rows = s.query(MetricRow).filter(MetricRow.platform==platform, MetricRow.account_id==account_id).all()
            summary = {}
            for r in rows:
                if r.metric_name not in summary:
                    summary[r.metric_name] = {"latest": r.value, "first": r.value, "count": 0}
                summary[r.metric_name]["latest"] = r.value
                summary[r.metric_name]["count"] += 1
            for k in summary:
                summary[k]["growth"] = round(summary[k]["latest"] - summary[k]["first"], 2)
            return summary

    def snapshot_instagram(self, account_id: str, ig_client) -> dict:
        """Pull live Instagram stats and record them."""
        try:
            info = ig_client.get_user_info(account_id)
            metrics = {"followers": info.get("followers_count",0), "following": info.get("follows_count",0), "posts": info.get("media_count",0)}
            for name, val in metrics.items():
                self.record("instagram", account_id, name, val)
            return {"recorded": metrics, "mode": "live"}
        except Exception as e:
            return {"error": str(e), "mode": "live"}

    def snapshot_youtube(self, channel_id: str, yt_client) -> dict:
        """Pull live YouTube channel stats and record them."""
        try:
            info = yt_client.get_channel_info()
            metrics = {"subscribers": info.get("subscriber_count",0), "total_views": info.get("view_count",0), "videos": info.get("video_count",0)}
            for name, val in metrics.items():
                self.record("youtube", channel_id, name, val)
            return {"recorded": metrics, "mode": "live"}
        except Exception as e:
            return {"error": str(e), "mode": "live"}

    def seed_demo_data(self) -> None:
        """Seed realistic demo data for the charts."""
        import random
        base_ig = {"followers": 1200, "likes": 450, "posts": 24}
        base_yt = {"subscribers": 350, "total_views": 8900, "watch_hours": 420}
        for days_ago in range(30, 0, -1):
            dt = datetime.utcnow() - timedelta(days=days_ago)
            with self.SessionLocal() as s:
                for metric, start in base_ig.items():
                    growth = start + (30 - days_ago) * random.uniform(5, 20)
                    s.add(MetricRow(platform="instagram", account_id="demo", metric_name=metric, value=round(growth,0), recorded_at=dt))
                for metric, start in base_yt.items():
                    growth = start + (30 - days_ago) * random.uniform(3, 15)
                    s.add(MetricRow(platform="youtube", account_id="demo", metric_name=metric, value=round(growth,0), recorded_at=dt))
                s.commit()