"""
BlogBot — webpush_publisher.py
Self-hosted browser push notifications via pywebpush (VAPID).

Replaces / supplements OneSignal with a platform-independent system where
subscriber push subscription objects (endpoint + keys) are stored in our own
SQLite database.  No third-party push service required.

Flow:
  1. Blog template embeds get_subscriber_js_snippet() output.
  2. Visitor's browser calls the /api/subscribe endpoint → bot calls
     WebPushPublisher.save_subscriber() to persist the subscription JSON.
  3. On every new post, notify_subscribers() → WebPushPublisher.broadcast()
     sends the push to every stored subscriber endpoint.
"""

import sys
import json
import sqlite3
import logging
import base64
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Optional

from pywebpush import webpush, WebPushException

# ── Path bootstrap ─────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent.parent.resolve()
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

DATA_DIR = BASE_DIR / "data"
LOGS_DIR = BASE_DIR / "logs"
ANALYTICS_DB = DATA_DIR / "analytics.db"

# ── Logging ───────────────────────────────────────────────────────────────────
_log = logging.getLogger("webpush_publisher")
_log.setLevel(logging.INFO)
if not _log.handlers:
    _fh = logging.FileHandler(LOGS_DIR / "activity.log", encoding="utf-8")
    _fh.setFormatter(
        logging.Formatter("%(asctime)s [WEBPUSH] %(levelname)s %(message)s")
    )
    _log.addHandler(_fh)

# ── Constant ──────────────────────────────────────────────────────────────────
VAPID_PUBLIC_KEY_PLACEHOLDER = "VAPID_PUBLIC_KEY_HERE"

# ── VAPID key management ───────────────────────────────────────────────────────

def get_or_create_vapid_keys() -> dict:
    """
    Return VAPID key pair from config, generating and persisting new keys if
    they are not yet present.

    The public key is returned as a URL-safe base64 string (no padding) — the
    format browsers expect in ``applicationServerKey``.
    The private key is returned as a PEM string so pywebpush can use it
    directly as ``vapid_private_key``.

    Returns
    -------
    dict with keys ``private_key`` (PEM string) and ``public_key`` (base64url
    string, no padding).
    """
    from modules.config_manager import get, set_value

    private_key = get("vapid_private_key", "")
    public_key  = get("vapid_public_key",  "")

    if private_key and public_key:
        _log.debug("VAPID keys loaded from config")
        return {"private_key": private_key, "public_key": public_key}

    # ── Generate fresh VAPID key pair ─────────────────────────────────────────
    _log.info("Generating new VAPID key pair…")
    try:
        from pywebpush import Vapid
        from cryptography.hazmat.primitives.serialization import (
            Encoding, PublicFormat,
        )

        vapid = Vapid()
        vapid.generate_keys()

        # Private key: PEM string — used by webpush() as vapid_private_key
        private_key = vapid.private_pem().decode("utf-8")

        # Public key: uncompressed EC point encoded as base64url (no padding)
        # This is the format browsers need for applicationServerKey.
        raw_pub = vapid.public_key.public_bytes(
            encoding=Encoding.X962,
            format=PublicFormat.UncompressedPoint,
        )
        public_key = base64.urlsafe_b64encode(raw_pub).rstrip(b"=").decode("utf-8")

        set_value("vapid_private_key", private_key)
        set_value("vapid_public_key",  public_key)
        _log.info("New VAPID keys generated and saved to config")

    except Exception as exc:
        _log.error(f"VAPID key generation failed: {exc}")
        raise

    return {"private_key": private_key, "public_key": public_key}


# ── Database helpers ───────────────────────────────────────────────────────────

def _get_analytics_conn() -> sqlite3.Connection:
    """Return a WAL-mode connection to analytics.db."""
    conn = sqlite3.connect(str(ANALYTICS_DB), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def _ensure_subscribers_table(conn: sqlite3.Connection) -> None:
    """Create webpush_subscribers table if it does not exist."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS webpush_subscribers (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            endpoint         TEXT    UNIQUE NOT NULL,
            subscription_json TEXT   NOT NULL,
            created_at       TEXT    NOT NULL,
            niche            TEXT    DEFAULT '',
            blog_url         TEXT    DEFAULT ''
        )
    """)
    conn.commit()


# ── WebPushPublisher ───────────────────────────────────────────────────────────

class WebPushPublisher:
    """
    Manages browser push subscriptions and sends VAPID-signed Web Push
    notifications without any third-party service.
    """

    # Default icon served from all Cloudflare Pages sites
    _DEFAULT_ICON = "/favicon.ico"
    # VAPID sub claim — must be a mailto: or https: URI
    _VAPID_SUB    = "mailto:blogbot@localhost"
    # Push TTL: 24 hours (browsers will re-attempt delivery for this long)
    _TTL          = 86_400
    # HTTP request timeout per push
    _TIMEOUT      = 15.0

    def __init__(self) -> None:
        keys = get_or_create_vapid_keys()
        self._private_key: str = keys["private_key"]
        self._public_key:  str = keys["public_key"]
        _log.debug("WebPushPublisher initialised")

    # ── Subscriber persistence ─────────────────────────────────────────────────

    def save_subscriber(
        self,
        subscription_json: str,
        niche: str    = "",
        blog_url: str = "",
    ) -> bool:
        """
        Persist a push subscription JSON string (from the browser's
        ``pushManager.subscribe()`` response) into ``analytics.db``.

        Parameters
        ----------
        subscription_json : Raw JSON string as sent by the browser.
        niche             : Optional niche tag (e.g. "tech", "crypto").
        blog_url          : Optional origin URL of the subscribing blog.

        Returns
        -------
        True on success, False on any error.
        """
        try:
            parsed = json.loads(subscription_json)
            endpoint = parsed.get("endpoint", "").strip()
            if not endpoint:
                _log.warning("save_subscriber: subscription_json has no endpoint")
                return False
        except (json.JSONDecodeError, AttributeError) as exc:
            _log.warning(f"save_subscriber: invalid JSON — {exc}")
            return False

        try:
            conn = _get_analytics_conn()
            try:
                _ensure_subscribers_table(conn)
                conn.execute(
                    """
                    INSERT INTO webpush_subscribers
                        (endpoint, subscription_json, created_at, niche, blog_url)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(endpoint) DO UPDATE SET
                        subscription_json = excluded.subscription_json,
                        niche             = excluded.niche,
                        blog_url          = excluded.blog_url
                    """,
                    (
                        endpoint,
                        subscription_json,
                        datetime.now(timezone.utc).isoformat(),
                        niche,
                        blog_url,
                    ),
                )
                conn.commit()
                _log.info(
                    f"Subscriber saved — niche={niche!r} blog={blog_url!r} "
                    f"endpoint={endpoint[:40]}…"
                )
                return True
            finally:
                conn.close()

        except Exception as exc:
            _log.error(f"save_subscriber DB error: {exc}")
            return False

    # ── Single notification ────────────────────────────────────────────────────

    def send_notification(
        self,
        subscription_json: str,
        title: str,
        body:  str,
        url:   str,
    ) -> bool:
        """
        Send a single Web Push notification to one subscriber.

        Parameters
        ----------
        subscription_json : Raw subscription JSON string from the database.
        title             : Notification title.
        body              : Notification body text.
        url               : URL to open when the user taps the notification.

        Returns
        -------
        True on success.  False on any error.
        If the endpoint returns HTTP 410 (Gone / subscription expired) the
        subscriber is automatically removed from the database.
        """
        try:
            subscription_info = json.loads(subscription_json)
        except (json.JSONDecodeError, TypeError) as exc:
            _log.warning(f"send_notification: bad subscription JSON — {exc}")
            return False

        payload = json.dumps({
            "title": title,
            "body":  body,
            "icon":  self._DEFAULT_ICON,
            "url":   url,
        })

        # VAPID claims: aud is derived from the endpoint; we set sub and exp.
        now_ts  = int(datetime.now(timezone.utc).timestamp())
        claims  = {
            "sub": self._VAPID_SUB,
            "exp": now_ts + 86_400,   # 24 h from now
        }

        try:
            webpush(
                subscription_info=subscription_info,
                data=payload,
                vapid_private_key=self._private_key,
                vapid_claims=claims,
                ttl=self._TTL,
                timeout=self._TIMEOUT,
            )
            return True

        except WebPushException as exc:
            status = getattr(exc.response, "status_code", None) if exc.response is not None else None
            endpoint = subscription_info.get("endpoint", "?")[:50]

            if status == 410:
                # Subscription expired or explicitly unsubscribed
                _log.info(
                    f"Subscriber gone (410) — removing endpoint={endpoint}…"
                )
                self._remove_subscriber(subscription_info.get("endpoint", ""))
            else:
                _log.warning(
                    f"WebPushException HTTP {status} — endpoint={endpoint}… : {exc}"
                )
            return False

        except Exception as exc:
            endpoint = subscription_info.get("endpoint", "?")[:50]
            _log.error(f"send_notification unexpected error (endpoint={endpoint}…): {exc}")
            return False

    # ── Broadcast ─────────────────────────────────────────────────────────────

    def broadcast(
        self,
        title: str,
        body:  str,
        url:   str,
        niche: str = "",
    ) -> dict:
        """
        Send a push notification to all stored subscribers, optionally
        filtered to a single niche.

        Parameters
        ----------
        title : Notification title.
        body  : Notification body text.
        url   : URL to open when tapped.
        niche : If non-empty, only subscribers with this niche tag receive
                the push.

        Returns
        -------
        dict  ``{"sent": N, "failed": N, "removed": N}``
        """
        sent = failed = 0

        try:
            conn = _get_analytics_conn()
            try:
                _ensure_subscribers_table(conn)
                if niche:
                    rows = conn.execute(
                        "SELECT subscription_json FROM webpush_subscribers WHERE niche = ?",
                        (niche,),
                    ).fetchall()
                else:
                    rows = conn.execute(
                        "SELECT subscription_json FROM webpush_subscribers"
                    ).fetchall()
            finally:
                conn.close()
        except Exception as exc:
            _log.error(f"broadcast: DB read error — {exc}")
            return {"sent": 0, "failed": 0, "removed": 0}

        total = len(rows)
        _log.info(
            f"broadcast start — total={total} niche={niche!r} title={title!r}"
        )

        removed_before = self._count_subscribers()

        for row in rows:
            ok = self.send_notification(
                subscription_json=row["subscription_json"],
                title=title,
                body=body,
                url=url,
            )
            if ok:
                sent += 1
            else:
                failed += 1

        removed_after  = self._count_subscribers()
        removed        = max(0, removed_before - removed_after)

        _log.info(
            f"broadcast done — sent={sent} failed={failed} removed={removed}"
        )
        return {"sent": sent, "failed": failed, "removed": removed}

    # ── Internal helpers ───────────────────────────────────────────────────────

    def _remove_subscriber(self, endpoint: str) -> None:
        """Delete a subscriber record by endpoint URL."""
        if not endpoint:
            return
        try:
            conn = _get_analytics_conn()
            try:
                conn.execute(
                    "DELETE FROM webpush_subscribers WHERE endpoint = ?",
                    (endpoint,),
                )
                conn.commit()
            finally:
                conn.close()
        except Exception as exc:
            _log.error(f"_remove_subscriber error: {exc}")

    def _count_subscribers(self) -> int:
        """Return total subscriber row count (used for removed-delta calculation)."""
        try:
            conn = _get_analytics_conn()
            try:
                _ensure_subscribers_table(conn)
                row = conn.execute(
                    "SELECT COUNT(*) AS n FROM webpush_subscribers"
                ).fetchone()
                return row["n"] if row else 0
            finally:
                conn.close()
        except Exception:
            return 0


# ── JS snippet for blog templates ──────────────────────────────────────────────

def get_subscriber_js_snippet(
    vapid_public_key: str,
    api_endpoint: str = "/api/subscribe",
) -> str:
    """
    Return a JavaScript snippet that:
    1. Registers a service worker (``/sw.js``).
    2. Requests notification permission from the visitor.
    3. Subscribes the browser to Web Push using the supplied VAPID public key.
    4. POSTs the resulting subscription object to ``api_endpoint``.

    Parameters
    ----------
    vapid_public_key : URL-safe base64 public key string (no padding).
    api_endpoint     : Server endpoint that accepts the POST, defaults to
                       ``/api/subscribe``.

    Returns
    -------
    str — ready to embed inside a ``<script>`` tag in the Jinja2 template.
    """
    return f"""<!-- BlogBot Self-Hosted Web Push -->
<script>
(function () {{
  'use strict';

  // Only run in secure contexts with SW + Push API support
  if (!('serviceWorker' in navigator) || !('PushManager' in window)) {{
    return;
  }}

  var VAPID_PUBLIC_KEY = '{vapid_public_key}';
  var SUBSCRIBE_ENDPOINT = '{api_endpoint}';

  // Convert URL-safe base64 string to Uint8Array (required by subscribe())
  function urlBase64ToUint8Array(base64String) {{
    var padding = '='.repeat((4 - base64String.length % 4) % 4);
    var base64 = (base64String + padding).replace(/-/g, '+').replace(/_/g, '/');
    var rawData = window.atob(base64);
    var outputArray = new Uint8Array(rawData.length);
    for (var i = 0; i < rawData.length; ++i) {{
      outputArray[i] = rawData.charCodeAt(i);
    }}
    return outputArray;
  }}

  // POST subscription to server
  function sendSubscriptionToServer(subscription) {{
    return fetch(SUBSCRIBE_ENDPOINT, {{
      method: 'POST',
      headers: {{ 'Content-Type': 'application/json' }},
      body: JSON.stringify(subscription),
    }}).catch(function (err) {{
      console.warn('[BlogBot Push] Failed to send subscription:', err);
    }});
  }}

  navigator.serviceWorker
    .register('/sw.js')
    .then(function (registration) {{
      // Ask permission only on a user gesture or after a short delay
      return Notification.requestPermission().then(function (permission) {{
        if (permission !== 'granted') {{
          return;
        }}
        return registration.pushManager
          .subscribe({{
            userVisibleOnly: true,
            applicationServerKey: urlBase64ToUint8Array(VAPID_PUBLIC_KEY),
          }})
          .then(sendSubscriptionToServer);
      }});
    }})
    .catch(function (err) {{
      console.warn('[BlogBot Push] Service worker registration failed:', err);
    }});
}})();
</script>
<!-- End BlogBot Web Push -->"""


# ── Top-level convenience entry point ─────────────────────────────────────────

def notify_subscribers(
    title: str,
    body:  str,
    url:   str,
    niche: str = "",
) -> bool:
    """
    High-level function called by ``bot_loop.py`` (or any module) after a new
    post is published.  Handles VAPID key bootstrapping, publisher creation, and
    broadcast in a single call.

    Parameters
    ----------
    title : Notification title.
    body  : Notification body text.
    url   : Full URL of the new post.
    niche : Optional niche filter — only subscribers tagged with this niche
            receive the push.  Pass ``""`` to send to everyone.

    Returns
    -------
    True if at least one notification was sent successfully, False otherwise.
    """
    try:
        get_or_create_vapid_keys()
        publisher = WebPushPublisher()
        result    = publisher.broadcast(title=title, body=body, url=url, niche=niche)
        _log.info(
            f"notify_subscribers — sent={result['sent']} "
            f"failed={result['failed']} removed={result['removed']} "
            f"niche={niche!r}"
        )
        return result["sent"] > 0
    except Exception as exc:
        _log.error(f"notify_subscribers unhandled error: {exc}")
        return False


# ── Self-test ─────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("webpush_publisher self-test…")

    # 1. VAPID key generation / retrieval
    try:
        keys = get_or_create_vapid_keys()
        assert keys.get("private_key"), "private_key missing"
        assert keys.get("public_key"),  "public_key missing"
        assert len(keys["public_key"]) > 20, "public_key too short"
        print(f"  VAPID keys: OK (pub_key={keys['public_key'][:20]}…)")
    except Exception as e:
        print(f"  VAPID keys: FAIL — {e}")

    # 2. WebPushPublisher instantiation
    try:
        pub = WebPushPublisher()
        print(f"  WebPushPublisher.__init__: OK")
    except Exception as e:
        print(f"  WebPushPublisher.__init__: FAIL — {e}")
        pub = None

    # 3. save_subscriber — valid JSON
    if pub:
        import json as _json
        fake_sub = _json.dumps({
            "endpoint": "https://fcm.googleapis.com/fcm/send/test-endpoint-001",
            "keys": {"p256dh": "BFAKE_P256DH_KEY", "auth": "FAKEAUTHKEY"},
        })
        ok = pub.save_subscriber(fake_sub, niche="tech", blog_url="https://test.pages.dev")
        print(f"  save_subscriber (valid): {'OK' if ok else 'FAIL'}")

        # Duplicate insert should succeed (upsert)
        ok2 = pub.save_subscriber(fake_sub, niche="tech", blog_url="https://test.pages.dev")
        print(f"  save_subscriber (duplicate upsert): {'OK' if ok2 else 'FAIL'}")

        # Invalid JSON
        ok3 = pub.save_subscriber("not-json")
        print(f"  save_subscriber (invalid JSON): {'False as expected' if not ok3 else 'UNEXPECTED TRUE'}")

    # 4. broadcast with no real subscribers (send_notification will fail for
    #    the fake endpoint — that is expected; important is no exception bubbles)
    if pub:
        result = pub.broadcast(
            title="Test Notification",
            body="This is a self-test broadcast.",
            url="https://test.pages.dev/posts/test.html",
        )
        print(
            f"  broadcast (fake endpoint): "
            f"sent={result['sent']} failed={result['failed']} removed={result['removed']} — OK (no crash)"
        )

    # 5. JS snippet
    snippet = get_subscriber_js_snippet(
        vapid_public_key="BFAKEKEY1234567890ABCDEF",
        api_endpoint="/api/subscribe",
    )
    assert "serviceWorker" in snippet
    assert "BFAKEKEY1234567890ABCDEF" in snippet
    assert "/api/subscribe" in snippet
    print(f"  get_subscriber_js_snippet: OK ({len(snippet)} chars)")

    # 6. VAPID_PUBLIC_KEY_PLACEHOLDER constant
    assert VAPID_PUBLIC_KEY_PLACEHOLDER == "VAPID_PUBLIC_KEY_HERE"
    print(f"  VAPID_PUBLIC_KEY_PLACEHOLDER: OK")

    # 7. notify_subscribers top-level (unconfigured DB / fake endpoint)
    r = notify_subscribers(
        title="Self-test push",
        body="Hello from BlogBot",
        url="https://test.pages.dev/posts/test.html",
    )
    print(f"  notify_subscribers: {'True' if r else 'False'} (False expected — fake endpoint)")

    print("Self-test complete.")
