"""Webhook Notifications — Discord, Telegram, Slack, Email."""
import logging, asyncio
from typing import Optional
import httpx
log = logging.getLogger(__name__)

class WebhookManager:
    """Send real-time notifications to Discord, Telegram, Slack, or email."""
    def __init__(self, discord_url:str="", telegram_token:str="", telegram_chat_id:str="", slack_url:str="", smtp_host:str="", smtp_port:int=587, smtp_user:str="", smtp_pass:str="", smtp_to:str=""):
        self.discord_url      = discord_url
        self.telegram_token   = telegram_token
        self.telegram_chat_id = telegram_chat_id
        self.slack_url        = slack_url
        self.smtp_host        = smtp_host
        self.smtp_port        = smtp_port
        self.smtp_user        = smtp_user
        self.smtp_pass        = smtp_pass
        self.smtp_to          = smtp_to
        self._client          = httpx.Client(timeout=10)

    @property
    def configured_channels(self) -> list[str]:
        channels = []
        if self.discord_url:      channels.append("discord")
        if self.telegram_token:   channels.append("telegram")
        if self.slack_url:        channels.append("slack")
        if self.smtp_host:        channels.append("email")
        return channels

    def notify(self, title: str, message: str, level: str = "info", data: dict = None) -> dict:
        """Send notification to all configured channels. level: info|success|warning|error"""
        results = {"channels": self.configured_channels, "sent": [], "failed": [], "mode": "live" if self.configured_channels else "simulation"}
        if not self.configured_channels:
            log.debug(f"webhook.simulation: {title} — {message}")
            results["message"] = "No webhook channels configured — add credentials in Settings"
            return results
        emoji = {"info":"ℹ️","success":"✅","warning":"⚠️","error":"❌"}.get(level,"📢")
        full_msg = f"{emoji} **{title}**\n{message}"
        if data:
            full_msg += "\n```\n" + "\n".join(f"{k}: {v}" for k,v in data.items()) + "\n```"
        for channel in self.configured_channels:
            try:
                if channel == "discord":   self._send_discord(full_msg)
                elif channel == "telegram": self._send_telegram(full_msg)
                elif channel == "slack":    self._send_slack(full_msg)
                elif channel == "email":    self._send_email_sync(title, message, level)
                results["sent"].append(channel)
            except Exception as e:
                results["failed"].append({"channel": channel, "error": str(e)})
                log.error(f"webhook.{channel}.failed: {e}")
        return results

    def notify_milestone(self, platform: str, metric: str, value: int) -> dict:
        milestones = [100, 500, 1000, 5000, 10000, 50000, 100000]
        for m in milestones:
            if value >= m and (value - 10) < m:
                return self.notify(f"🎉 {platform.title()} Milestone!", f"You just hit **{m:,} {metric}** on {platform.title()}!", "success", {"platform": platform, "metric": metric, "value": value})
        return {"sent": [], "message": "No milestone triggered"}

    def notify_job_complete(self, job_id: str, results: dict) -> dict:
        summary = {k: v for k, v in results.items() if isinstance(v, (int, str, float))}
        return self.notify("Job Completed", f"Job `{job_id}` finished successfully", "success", summary)

    def notify_error(self, context: str, error: str) -> dict:
        return self.notify("Bot Error", f"Error in `{context}`:\n{error[:200]}", "error")

    def _send_discord(self, message: str) -> None:
        r = self._client.post(self.discord_url, json={"content": message[:2000]})
        r.raise_for_status()

    def _send_telegram(self, message: str) -> None:
        url = f"https://api.telegram.org/bot{self.telegram_token}/sendMessage"
        r = self._client.post(url, json={"chat_id": self.telegram_chat_id, "text": message[:4096], "parse_mode": "Markdown"})
        r.raise_for_status()

    def _send_slack(self, message: str) -> None:
        r = self._client.post(self.slack_url, json={"text": message})
        r.raise_for_status()

    def _send_email_sync(self, subject: str, body: str, level: str) -> None:
        import smtplib
        from email.mime.text import MIMEText
        msg = MIMEText(f"{body}\n\nLevel: {level}\nSent by BotPlatform", "plain")
        msg["Subject"] = f"[BotPlatform] {subject}"
        msg["From"]    = self.smtp_user
        msg["To"]      = self.smtp_to
        with smtplib.SMTP(self.smtp_host, self.smtp_port) as smtp:
            smtp.starttls()
            smtp.login(self.smtp_user, self.smtp_pass)
            smtp.send_message(msg)

    def test_channels(self) -> dict:
        return self.notify("Test Notification", "BotPlatform webhooks are working correctly!", "success")