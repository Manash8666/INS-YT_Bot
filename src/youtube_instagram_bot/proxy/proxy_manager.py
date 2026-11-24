"""Proxy Manager — rotate residential/datacenter proxies for anti-ban protection."""
import logging, random, time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional
log = logging.getLogger(__name__)

@dataclass
class Proxy:
    host: str; port: int; username: str = ""; password: str = ""
    proxy_type: str = "http"   # http, socks5
    tags: list = field(default_factory=list)
    success_count: int = 0; fail_count: int = 0
    last_used: Optional[datetime] = None; banned_until: Optional[datetime] = None

    @property
    def url(self) -> str:
        auth = f"{self.username}:{self.password}@" if self.username else ""
        return f"{self.proxy_type}://{auth}{self.host}:{self.port}"

    @property
    def is_available(self) -> bool:
        if self.banned_until and datetime.utcnow() < self.banned_until:
            return False
        return True

    @property
    def success_rate(self) -> float:
        total = self.success_count + self.fail_count
        return self.success_count / total if total > 0 else 1.0

    def to_dict(self) -> dict:
        return {"host": self.host, "port": self.port, "type": self.proxy_type, "tags": self.tags, "success_count": self.success_count, "fail_count": self.fail_count, "success_rate": round(self.success_rate*100,1), "is_available": self.is_available, "last_used": self.last_used.isoformat() if self.last_used else None, "banned_until": self.banned_until.isoformat() if self.banned_until else None}

class ProxyManager:
    """Rotate proxies for Instagram and YouTube requests to reduce ban risk."""
    def __init__(self):
        self._proxies: list[Proxy] = []
        self._platform_index: dict[str, int] = {}

    @property
    def has_proxies(self) -> bool:
        return bool(self._proxies)

    def add_proxy(self, host: str, port: int, username: str = "", password: str = "", proxy_type: str = "http", tags: list = None) -> None:
        p = Proxy(host=host, port=port, username=username, password=password, proxy_type=proxy_type, tags=tags or [])
        self._proxies.append(p)
        log.info(f"proxy.added {host}:{port}")

    def add_from_list(self, proxy_strings: list[str]) -> int:
        """Parse and add proxies in format host:port or user:pass@host:port"""
        added = 0
        for s in proxy_strings:
            s = s.strip()
            if not s or s.startswith("#"):
                continue
            try:
                if "@" in s:
                    auth, hostport = s.rsplit("@", 1)
                    user, pw = auth.split(":", 1)
                else:
                    user, pw = "", ""
                    hostport = s
                host, port = hostport.rsplit(":", 1)
                self.add_proxy(host.strip(), int(port.strip()), user, pw)
                added += 1
            except Exception as e:
                log.warning(f"proxy.parse_error '{s}': {e}")
        return added

    def get_proxy(self, platform: str = None, strategy: str = "round_robin") -> Optional[Proxy]:
        available = [p for p in self._proxies if p.is_available]
        if not available:
            return None
        if strategy == "round_robin":
            idx = self._platform_index.get(platform or "default", 0)
            proxy = available[idx % len(available)]
            self._platform_index[platform or "default"] = (idx + 1) % len(available)
        elif strategy == "random":
            proxy = random.choice(available)
        elif strategy == "best":
            proxy = max(available, key=lambda p: p.success_rate)
        else:
            proxy = available[0]
        proxy.last_used = datetime.utcnow()
        return proxy

    def mark_success(self, proxy: Proxy) -> None:
        proxy.success_count += 1

    def mark_failure(self, proxy: Proxy, ban_minutes: int = 60) -> None:
        proxy.fail_count += 1
        if proxy.fail_count > 3 and proxy.success_rate < 0.3:
            proxy.banned_until = datetime.utcnow() + timedelta(minutes=ban_minutes)
            log.warning(f"proxy.banned {proxy.host} for {ban_minutes}min")

    def remove_bad_proxies(self, min_success_rate: float = 0.5) -> int:
        before = len(self._proxies)
        self._proxies = [p for p in self._proxies if p.success_count + p.fail_count < 5 or p.success_rate >= min_success_rate]
        removed = before - len(self._proxies)
        log.info(f"proxy.cleanup removed={removed}")
        return removed

    def stats(self) -> dict:
        total = len(self._proxies)
        available = sum(1 for p in self._proxies if p.is_available)
        return {"total": total, "available": available, "banned": total - available, "configured": total > 0, "proxies": [p.to_dict() for p in self._proxies]}

    def get_httpx_proxies(self, platform: str = None) -> dict | None:
        proxy = self.get_proxy(platform)
        if not proxy:
            return None
        return {"http://": proxy.url, "https://": proxy.url}