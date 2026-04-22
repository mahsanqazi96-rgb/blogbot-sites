"""
BlogBot — cryptopanic_publisher.py
CryptoPanic news submission: posts crypto content to CryptoPanic's news feed.
CryptoPanic has 500k+ active users who browse crypto news daily.
Posts appear in their feed within minutes of submission.
"""

import logging
from pathlib import Path
from typing import Optional
from urllib.parse import urlencode

import requests

# ── Logging ───────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent.parent.resolve()
LOGS_DIR = BASE_DIR / "logs"
LOGS_DIR.mkdir(parents=True, exist_ok=True)

_log = logging.getLogger("cryptopanic_publisher")
_log.setLevel(logging.INFO)
if not _log.handlers:
    _fh = logging.FileHandler(LOGS_DIR / "activity.log", encoding="utf-8")
    _fh.setFormatter(logging.Formatter("%(asctime)s [CRYPTOPANIC] %(levelname)s %(message)s"))
    _log.addHandler(_fh)

# ── Constants ─────────────────────────────────────────────────────────────────
_API_BASE = "https://cryptopanic.com/api/free/v1/posts/"
_TIMEOUT = 20
_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; BlogBot/1.0)"}


# ── Class ─────────────────────────────────────────────────────────────────────
class CryptoPanicPublisher:
    """Submits crypto/finance post URLs and RSS feeds to CryptoPanic."""

    def __init__(self, auth_token: str) -> None:
        self.auth_token = auth_token

    # ── Public methods ────────────────────────────────────────────────────────

    def submit_post(self, title: str, url: str) -> bool:
        """
        Submit a single post URL to CryptoPanic's news feed.

        POST to https://cryptopanic.com/api/free/v1/posts/
        Params: auth_token, title, url, kind=news
        Returns True on HTTP 200 or 201, False otherwise.
        """
        payload = {
            "auth_token": self.auth_token,
            "title": title,
            "url": url,
            "kind": "news",
        }
        try:
            resp = requests.post(
                _API_BASE,
                data=payload,
                headers=_HEADERS,
                timeout=_TIMEOUT,
            )
            if resp.status_code in (200, 201):
                _log.info(f"CryptoPanic post accepted: {url}")
                return True
            _log.warning(
                f"CryptoPanic post rejected (HTTP {resp.status_code}): {url} — {resp.text[:200]}"
            )
            return False
        except requests.RequestException as exc:
            _log.error(f"CryptoPanic submit_post error for {url}: {exc}")
            return False

    def submit_rss_feed(self, feed_url: str) -> bool:
        """
        Register an RSS feed as a CryptoPanic news source.

        GET https://cryptopanic.com/api/free/v1/posts/?auth_token={token}&rss={feed_url}
        Returns True on HTTP 200.
        """
        params = urlencode({"auth_token": self.auth_token, "rss": feed_url})
        request_url = f"{_API_BASE}?{params}"
        try:
            resp = requests.get(request_url, headers=_HEADERS, timeout=_TIMEOUT)
            if resp.status_code == 200:
                _log.info(f"CryptoPanic RSS feed registered: {feed_url}")
                return True
            _log.warning(
                f"CryptoPanic RSS registration failed (HTTP {resp.status_code}): "
                f"{feed_url} — {resp.text[:200]}"
            )
            return False
        except requests.RequestException as exc:
            _log.error(f"CryptoPanic submit_rss_feed error for {feed_url}: {exc}")
            return False


# ── Factory ───────────────────────────────────────────────────────────────────
def make_cryptopanic_from_config() -> Optional[CryptoPanicPublisher]:
    """
    Build a CryptoPanicPublisher from the encrypted config.
    Reads 'cryptopanic_auth_token'. Returns None if not set.
    """
    try:
        from modules.config_manager import get as cfg_get
    except ImportError:
        try:
            from config_manager import get as cfg_get
        except ImportError:
            _log.error("config_manager not available — cannot build CryptoPanicPublisher")
            return None

    token = cfg_get("cryptopanic_auth_token")
    if not token:
        _log.debug("cryptopanic_auth_token not set in config — skipping CryptoPanic")
        return None
    return CryptoPanicPublisher(auth_token=token)


# ── Top-level helper ──────────────────────────────────────────────────────────
def submit_crypto_post(title: str, url: str, niche: str) -> bool:
    """
    Submit a post to CryptoPanic if the niche is 'crypto' or 'finance'.

    Returns False silently for other niches.
    Returns False if no auth token is configured.
    """
    if niche not in ("crypto", "finance"):
        return False

    publisher = make_cryptopanic_from_config()
    if publisher is None:
        return False

    return publisher.submit_post(title=title, url=url)
