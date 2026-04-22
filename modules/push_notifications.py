"""
BlogBot — push_notifications.py
OneSignal Web Push: sends a push notification to all subscribers on every new post.
Free tier: 10,000 subscribers per app. No traffic required to start.
"""

import sys
import logging
import requests
from pathlib import Path
from typing import Optional

# ── Path bootstrap ────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent.parent.resolve()
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

LOGS_DIR = BASE_DIR / "logs"

# ── Logging ───────────────────────────────────────────────────────────────────
_log = logging.getLogger("push_notifications")
_log.setLevel(logging.INFO)
if not _log.handlers:
    _fh = logging.FileHandler(LOGS_DIR / "activity.log", encoding="utf-8")
    _fh.setFormatter(logging.Formatter("%(asctime)s [PUSH] %(levelname)s %(message)s"))
    _log.addHandler(_fh)

# ── OneSignal JS SDK snippet (injected into Jinja2 templates) ─────────────────
ONESIGNAL_SDK_SNIPPET = """<!-- OneSignal Web Push -->
<script src="https://cdn.onesignal.com/sdks/web/v16/OneSignalSDK.page.js" defer></script>
<script>
  window.OneSignalDeferred = window.OneSignalDeferred || [];
  OneSignalDeferred.push(async function(OneSignal) {
    await OneSignal.init({
      appId: "{{ onesignal_app_id }}",
      notifyButton: { enable: true },
      allowLocalhostAsSecureOrigin: true,
    });
  });
</script>
<!-- End OneSignal -->"""

# ── OneSignalPusher ───────────────────────────────────────────────────────────
class OneSignalPusher:
    """
    Sends web push notifications via the OneSignal REST API.

    Parameters
    ----------
    app_id  : OneSignal Application ID (found in Settings > Keys & IDs)
    api_key : OneSignal REST API Key (same page, "REST API Key")
    """

    _NOTIFICATIONS_URL = "https://api.onesignal.com/notifications"
    _APPS_URL          = "https://api.onesignal.com/apps/{app_id}"
    _TIMEOUT           = 30  # seconds

    def __init__(self, app_id: str, api_key: str) -> None:
        self.app_id  = app_id.strip()
        self.api_key = api_key.strip()

    # ── Internal helpers ──────────────────────────────────────────────────────
    def _auth_headers(self) -> dict:
        return {
            "Authorization": f"Basic {self.api_key}",
            "Content-Type":  "application/json",
        }

    # ── Public API ────────────────────────────────────────────────────────────
    def send(
        self,
        title:    str,
        message:  str,
        url:      str,
        icon_url: str = "",
    ) -> dict:
        """
        Broadcast a push notification to all subscribers.

        Parameters
        ----------
        title    : Notification title (shown in bold)
        message  : Notification body text
        url      : URL to open when notification is tapped
        icon_url : Optional icon image URL

        Returns
        -------
        dict  Response JSON from OneSignal, or {"error": "<reason>"} on failure.
        """
        payload: dict = {
            "app_id":            self.app_id,
            "included_segments": ["All"],
            "headings":          {"en": title},
            "contents":          {"en": message},
            "url":               url,
        }
        if icon_url:
            payload["chrome_web_icon"] = icon_url

        try:
            response = requests.post(
                self._NOTIFICATIONS_URL,
                headers=self._auth_headers(),
                json=payload,
                timeout=self._TIMEOUT,
            )
            data = response.json()

            if response.ok and data.get("id"):
                _log.info(
                    f"Push sent OK — id={data['id']} "
                    f"recipients={data.get('recipients', '?')} "
                    f"title={title!r}"
                )
            else:
                _log.warning(
                    f"Push send failed — HTTP {response.status_code} "
                    f"errors={data.get('errors', data)}"
                )
            return data

        except requests.exceptions.Timeout:
            _log.error("Push send timed out after 30 s")
            return {"error": "timeout"}
        except requests.exceptions.ConnectionError as exc:
            _log.error(f"Push send connection error: {exc}")
            return {"error": "connection_error"}
        except Exception as exc:
            _log.error(f"Push send unexpected error: {exc}")
            return {"error": str(exc)}

    def get_subscriber_count(self) -> int:
        """
        Return the total subscriber (player) count for this OneSignal app.

        Returns 0 on any error so callers never crash.
        """
        url = self._APPS_URL.format(app_id=self.app_id)
        try:
            response = requests.get(
                url,
                headers=self._auth_headers(),
                timeout=self._TIMEOUT,
            )
            data = response.json()

            if response.ok:
                count = int(data.get("players", 0))
                _log.info(f"Subscriber count fetched: {count} (app_id={self.app_id})")
                return count
            else:
                _log.warning(
                    f"get_subscriber_count failed — HTTP {response.status_code} "
                    f"body={data}"
                )
                return 0

        except requests.exceptions.Timeout:
            _log.error("get_subscriber_count timed out after 30 s")
            return 0
        except requests.exceptions.ConnectionError as exc:
            _log.error(f"get_subscriber_count connection error: {exc}")
            return 0
        except Exception as exc:
            _log.error(f"get_subscriber_count unexpected error: {exc}")
            return 0


# ── Factory ───────────────────────────────────────────────────────────────────
def make_pusher_from_config() -> Optional[OneSignalPusher]:
    """
    Build a OneSignalPusher from encrypted config.json.

    Reads:
        onesignal_app_id   — OneSignal Application ID
        onesignal_api_key  — OneSignal REST API Key

    Returns None (with a warning log) if either value is missing/empty.
    """
    try:
        from modules.config_manager import get as cfg_get
        app_id  = cfg_get("onesignal_app_id",  "")
        api_key = cfg_get("onesignal_api_key", "")
    except Exception as exc:
        _log.warning(f"make_pusher_from_config: config read error — {exc}")
        return None

    if not app_id or not api_key:
        _log.warning(
            "OneSignal not configured — set onesignal_app_id and "
            "onesignal_api_key in config.json to enable push notifications"
        )
        return None

    return OneSignalPusher(app_id=app_id, api_key=api_key)


# ── Convenience entry point ───────────────────────────────────────────────────
def notify_new_post(
    blog_title: str,
    post_title: str,
    post_url:   str,
    niche:      str,
) -> bool:
    """
    Send a web push notification announcing a new blog post.

    Called by bot_loop.py immediately after a post is published.

    Parameters
    ----------
    blog_title : Display name of the blog (e.g. "CryptoInsider Daily")
    post_title : Title of the newly published post
    post_url   : Full URL of the post on Cloudflare Pages
    niche      : Blog niche (used for log context only)

    Returns
    -------
    True  if the notification was sent successfully.
    False if OneSignal is not configured or the send failed.
    """
    pusher = make_pusher_from_config()
    if pusher is None:
        # Not configured — silent skip, bot_loop.py continues normally
        return False

    title   = f"📢 {blog_title}"
    result  = pusher.send(title=title, message=post_title, url=post_url)

    # OneSignal returns {"id": "...", "recipients": N} on success
    if result.get("id") and not result.get("errors"):
        _log.info(
            f"notify_new_post OK — niche={niche!r} "
            f"blog={blog_title!r} post={post_title!r}"
        )
        return True

    _log.warning(
        f"notify_new_post failed — niche={niche!r} "
        f"blog={blog_title!r} result={result}"
    )
    return False


# ── Self-Test ─────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("push_notifications self-test...")

    # Factory with missing config
    pusher = make_pusher_from_config()
    print(f"  make_pusher_from_config (unconfigured): {'None as expected' if pusher is None else 'UNEXPECTED PUSHER'}")

    # notify_new_post short-circuits gracefully
    result = notify_new_post(
        blog_title="Test Blog",
        post_title="Test Post Title",
        post_url="https://example.pages.dev/posts/test-post.html",
        niche="tech",
    )
    print(f"  notify_new_post (unconfigured): {'False as expected' if result is False else 'UNEXPECTED TRUE'}")

    # SDK snippet present
    print(f"  ONESIGNAL_SDK_SNIPPET present: {'OK' if 'OneSignalSDK' in ONESIGNAL_SDK_SNIPPET else 'FAIL'}")

    print("Self-test complete.")
