"""Webhook alerts for new drift events (Slack, Discord, Teams-compatible or any JSON endpoint)."""
import logging
import threading
from typing import Optional

import httpx

from app.config import settings
from app.services.drift_detection_service import SEVERITY_RANK

logger = logging.getLogger(__name__)

SEVERITY_EMOJI = {"high": "🔴", "medium": "🟠", "low": "🟡"}


class AlertService:
    last_status: Optional[dict] = None

    @staticmethod
    def enabled() -> bool:
        return bool(settings.ALERT_WEBHOOK_URL)

    @staticmethod
    def should_alert(severity: Optional[str]) -> bool:
        threshold = SEVERITY_RANK.get(settings.ALERT_MIN_SEVERITY, 3)
        return AlertService.enabled() and SEVERITY_RANK.get(severity or "", 0) >= threshold

    @staticmethod
    def build_payload(event: dict) -> dict:
        link = f"{settings.PUBLIC_BASE_URL}/ui/drift/{event['id']}" if settings.PUBLIC_BASE_URL else None
        emoji = SEVERITY_EMOJI.get(event.get("severity"), "⚠️")
        issues = (event.get("drift_detail") or {}).get("issues", [])
        lines = [
            f"{emoji} *{(event.get('severity') or 'unknown').upper()} schema drift* on "
            f"`{event['method']} {event['endpoint']}` — {len(issues)} issue(s)"
        ]
        for issue in issues[:5]:
            lines.append(f"• {issue['message']}")
        if len(issues) > 5:
            lines.append(f"• …and {len(issues) - 5} more")
        if link:
            lines.append(f"Details: {link}")
        text = "\n".join(lines)
        # `text` is used by Slack/Teams/Mattermost, `content` by Discord, `event` by generic receivers.
        return {
            "text": text,
            "content": text[:1900],
            "event": {
                "id": event["id"],
                "endpoint": event["endpoint"],
                "method": event["method"],
                "severity": event.get("severity"),
                "issue_count": len(issues),
                "url": link,
            },
        }

    @staticmethod
    def send(payload: dict) -> dict:
        try:
            response = httpx.post(settings.ALERT_WEBHOOK_URL, json=payload, timeout=8)
            status = {"ok": response.status_code < 400, "status_code": response.status_code}
            if not status["ok"]:
                status["error"] = response.text[:300]
        except httpx.HTTPError as exc:
            status = {"ok": False, "error": str(exc)}
        AlertService.last_status = status
        if not status["ok"]:
            logger.warning("Alert webhook failed: %s", status)
        return status

    @staticmethod
    def notify_new_event(event: dict) -> bool:
        """Fire-and-forget alert for a freshly created drift event."""
        if not AlertService.should_alert(event.get("severity")):
            return False
        payload = AlertService.build_payload(event)
        threading.Thread(target=AlertService.send, args=(payload,), daemon=True).start()
        return True

    @staticmethod
    def send_test() -> dict:
        if not AlertService.enabled():
            return {"ok": False, "error": "ALERT_WEBHOOK_URL is not configured"}
        text = "✅ API Contract Validator test alert — webhook is configured correctly."
        return AlertService.send({"text": text, "content": text, "event": {"test": True}})
