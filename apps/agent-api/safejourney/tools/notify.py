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
    """Send a push to one device token. Returns True if actually delivered to FCM.

    A WebpushConfig is attached so the alert renders as a real OS notification on the web
    even when the tab/app is closed — the flagship 'app-closed push' behaviour — and clicking
    it deep-links back into the app at the alerting trip.
    """
    s = get_settings()
    if not s.fcm_enabled or not token:
        print(f"[notify:log] {title} — {body}")
        return False
    if _ensure_fcm() is None:
        print(f"[notify:log] {title} — {body}")
        return False
    try:
        from firebase_admin import messaging

        data_str = {k: str(v) for k, v in (data or {}).items()}
        link = s.web_app_url.rstrip("/") + "/" if s.web_app_url else "/"
        trip_id = data_str.get("tripId")
        if trip_id and s.web_app_url:
            link = f"{s.web_app_url.rstrip('/')}/?trip={trip_id}"

        # Top-level notification + data; the web SW's onBackgroundMessage renders exactly one
        # OS notification (avoiding the classic FCM web duplicate). fcm_options.link deep-links
        # the click back into the app at the alerting trip.
        msg = messaging.Message(
            token=token,
            notification=messaging.Notification(title=title, body=body),
            data={**data_str, "title": title, "body": body},
            webpush=messaging.WebpushConfig(
                fcm_options=messaging.WebpushFCMOptions(link=link),
            ),
        )
        messaging.send(msg)
        return True
    except Exception as e:  # pragma: no cover
        print(f"[notify] send failed ({e}); logged instead: {title} — {body}")
        return False
