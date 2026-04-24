"""
BlogBot — tumblr_publisher.py
Republishes blog content to Tumblr using pytumblr (official Tumblr Python client).

Why Tumblr:
  - Tumblr posts independently index in Google and Bing (free backlinks)
  - Tumblr has its own recommendation engine (organic discovery)
  - Link posts drive traffic directly to source URL
  - Tumblr allows automated posting via OAuth

Credentials required (set via setup_traffic_keys.py):
  tumblr_consumer_key    — OAuth Consumer Key (from apps.tumblr.com)
  tumblr_consumer_secret — OAuth Consumer Secret
  tumblr_oauth_token     — OAuth Access Token
  tumblr_oauth_secret    — OAuth Access Token Secret
  tumblr_blog_name       — Blog identifier (e.g. 'myblog' from myblog.tumblr.com)

Security:
  - All credentials from AES-256 encrypted config.json via config_manager
  - Only connects to api.tumblr.com (pytumblr default)
  - Circuit breaker: opens after 5 failures, 5-min cooldown
  - Credentials logged masked (first 8 chars + '...' only)
  - No eval/exec anywhere in this module
"""

import sys
import re
import logging
from pathlib import Path
from typing import Optional, List

BASE_DIR = Path(__file__).parent.parent.resolve()
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

LOGS_DIR = BASE_DIR / "logs"

# ── Optional: pytumblr ─────────────────────────────────────────────────────────
try:
    import pytumblr
    _PYTUMBLR_OK = True
except ImportError:
    _PYTUMBLR_OK = False

from modules.circuit_breaker import get_breaker, ServiceUnavailableError

_log = logging.getLogger("tumblr_publisher")
_log.setLevel(logging.INFO)
if not _log.handlers:
    _fh = logging.FileHandler(LOGS_DIR / "activity.log", encoding="utf-8")
    _fh.setFormatter(logging.Formatter("%(asctime)s [TUMBLR] %(levelname)s %(message)s"))
    _log.addHandler(_fh)

_tumblr_breaker = get_breaker("tumblr", failure_threshold=5, timeout_sec=300)

# ── Niche tag mapping ──────────────────────────────────────────────────────────
NICHE_TAGS: dict = {
    "crypto":        ["crypto", "bitcoin", "cryptocurrency", "blockchain", "defi"],
    "finance":       ["finance", "investing", "money", "stocks", "personalfinance"],
    "health":        ["health", "wellness", "fitness", "nutrition", "healthyliving"],
    "tech":          ["technology", "tech", "gadgets", "ai", "innovation"],
    "entertainment": ["entertainment", "celebrity", "viral", "trending", "movies"],
}


def _strip_html_tags(html: str) -> str:
    """Remove HTML tags for excerpt generation."""
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"\s+", " ", text).strip()
    return text


class TumblrPublisher:
    """
    Wraps pytumblr.TumblrRestClient for publishing link posts to Tumblr.
    Credentials loaded from encrypted config.json — never hardcoded.
    """

    def __init__(self):
        self._client = None
        self._blog_name: str = ""
        self._configured = False
        self._load_credentials()

    def _load_credentials(self):
        """Load Tumblr credentials from config_manager. Log masked values."""
        if not _PYTUMBLR_OK:
            _log.debug("pytumblr not installed — Tumblr publisher disabled")
            return
        try:
            from modules.config_manager import get
            consumer_key    = get("tumblr_consumer_key",    "")
            consumer_secret = get("tumblr_consumer_secret", "")
            oauth_token     = get("tumblr_oauth_token",     "")
            oauth_secret    = get("tumblr_oauth_secret",    "")
            blog_name       = get("tumblr_blog_name",       "")

            if not all([consumer_key, consumer_secret, oauth_token, oauth_secret, blog_name]):
                _log.debug(
                    "Tumblr credentials not configured — skipping "
                    "(run setup_traffic_keys.py to configure)"
                )
                return

            _log.debug(
                f"Tumblr credentials loaded — "
                f"consumer_key={consumer_key[:8]}... "
                f"blog={blog_name}"
            )

            self._client = pytumblr.TumblrRestClient(
                consumer_key,
                consumer_secret,
                oauth_token,
                oauth_secret,
            )
            self._blog_name = blog_name
            self._configured = True
        except Exception as e:
            _log.error(f"TumblrPublisher._load_credentials failed: {e}")

    def _is_configured(self) -> bool:
        return self._configured and self._client is not None and bool(self._blog_name)

    def publish(self, title: str, url: str, body: str = "",
                niche: str = "", tags: Optional[List[str]] = None) -> bool:
        """
        Create a Tumblr link post for a new blog entry.
        Link posts get the best organic reach on Tumblr.
        Target: api.tumblr.com (pytumblr default — never changes)
        Returns True on success.
        """
        if not self._is_configured():
            return False

        try:
            # Build excerpt from body HTML
            excerpt = _strip_html_tags(body)[:250].strip() if body else ""
            if excerpt and not excerpt.endswith("."):
                excerpt += "..."

            # Combine niche tags + custom tags (max 10 total, Tumblr limit)
            all_tags = list(dict.fromkeys(
                NICHE_TAGS.get(niche, []) + (tags or [])
            ))[:10]

            # Truncate title to 100 chars (Tumblr limit)
            safe_title = title[:100]

            def _do():
                _log.info(
                    f"Tumblr: creating link post → api.tumblr.com "
                    f"(blog={self._blog_name}, title={safe_title[:40]}...)"
                )
                return self._client.create_link(
                    self._blog_name,
                    title=safe_title,
                    url=url,
                    description=excerpt,
                    tags=all_tags,
                    state="published",
                    native_inline_images=False,
                )

            result = _tumblr_breaker.call(_do)

            # pytumblr returns dict with 'id' on success, or 'meta'/'errors' on failure
            if isinstance(result, dict):
                if "id" in result:
                    _log.info(f"Tumblr: link post published — id={result['id']} blog={self._blog_name}")
                    return True
                meta_status = result.get("meta", {}).get("status", 0)
                if meta_status in (200, 201):
                    _log.info(f"Tumblr: link post published — blog={self._blog_name}")
                    return True
                errors = result.get("errors", result.get("meta", {}))
                _log.warning(f"Tumblr: post failed — {errors}")
                return False

            _log.warning(f"Tumblr: unexpected response type: {type(result)}")
            return False

        except ServiceUnavailableError:
            _log.warning("Tumblr: circuit breaker open — skipping")
            return False
        except Exception as e:
            _log.error(f"TumblrPublisher.publish error: {e}")
            return False


# ── Module-level convenience functions ────────────────────────────────────────

_publisher_instance: Optional[TumblrPublisher] = None


def make_tumblr_from_config() -> Optional[TumblrPublisher]:
    """Factory: build TumblrPublisher from config. Returns None if not configured."""
    global _publisher_instance
    if _publisher_instance is None:
        _publisher_instance = TumblrPublisher()
    return _publisher_instance if _publisher_instance._is_configured() else None


def publish_to_tumblr(title: str, url: str, body: str = "",
                      niche: str = "", tags: Optional[List[str]] = None) -> bool:
    """
    Publish a new blog post as a Tumblr link post.
    Returns False silently if credentials not configured — never raises.
    """
    try:
        pub = make_tumblr_from_config()
        if pub is None:
            return False
        return pub.publish(title=title, url=url, body=body, niche=niche, tags=tags)
    except Exception as e:
        _log.error(f"publish_to_tumblr error: {e}")
        return False


# ── Self-test ─────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print(f"pytumblr available: {_PYTUMBLR_OK}")
    pub = TumblrPublisher()
    print(f"Configured: {pub._is_configured()}")
    tags = NICHE_TAGS.get("crypto", [])
    print(f"Crypto tags: {tags}")
    excerpt = _strip_html_tags("<p>Bitcoin breaks $100k milestone as ETF inflows surge.</p>")
    print(f"Excerpt: {excerpt}")
    print("Self-test passed.")
