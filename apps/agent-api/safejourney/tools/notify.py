"""Push notification via Firebase Cloud Messaging (FCM), with a log/store fallback.

The fallback still records the alert in the repo, so the web UI's alert feed works even
without FCM configured — only the OS-level push is skipped.
"""

from __future__ import annotations

from ..config import get_settings

_fcm_app = None


def _ensure_fcm():
    global _fcm_app
    if _fcm_app is not None:
        return _fcm_app
    try:
        import firebase_admin
        from firebase_admin import credentials  # noqa: F401

        _fcm_app = firebase_admin.initialize_app()
        return _fcm_app
    except Exception as e:  # pragma: no cover
        print(f"[notify] FCM init failed ({e}); using log fallback.")
        return None


def send_push(token: str, title: str, body: str, data: dict | None = None) -> bool:
    """Send a push to one device token. Returns True if actually delivered to FCM."""
    s = get_settings()
    if not s.fcm_enabled or not token:
        print(f"[notify:log] {title} — {body}")
        return False
    if _ensure_fcm() is None:
        print(f"[notify:log] {title} — {body}")
        return False
    try:
        from firebase_admin import messaging

        msg = messaging.Message(
            token=token,
            notification=messaging.Notification(title=title, body=body),
            data={k: str(v) for k, v in (data or {}).items()},
        )
        messaging.send(msg)
        return True
    except Exception as e:  # pragma: no cover
        print(f"[notify] send failed ({e}); logged instead: {title} — {body}")
        return False
