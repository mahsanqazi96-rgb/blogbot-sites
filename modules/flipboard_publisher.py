"""
BlogBot — flipboard_publisher.py
Flipboard syndication: submits posts to Flipboard magazines via RSS.
Flipboard has 100M+ users browsing topic magazines.
One magazine per niche, RSS-fed automatically.
"""

import logging
from pathlib import Path
from urllib.parse import quote_plus

import requests

# ── Logging ───────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent.parent.resolve()
LOGS_DIR = BASE_DIR / "logs"
LOGS_DIR.mkdir(parents=True, exist_ok=True)

_log = logging.getLogger("flipboard_publisher")
_log.setLevel(logging.INFO)
if not _log.handlers:
    _fh = logging.FileHandler(LOGS_DIR / "activity.log", encoding="utf-8")
    _fh.setFormatter(logging.Formatter("%(asctime)s [FLIPBOARD] %(levelname)s %(message)s"))
    _log.addHandler(_fh)

# ── Constants ─────────────────────────────────────────────────────────────────
_API_PING    = "https://api.flipboard.com/flipboard.php"
_SHARE_PING  = "https://share.flipboard.com/bookmarklet/popout"
_TIMEOUT     = 20
_HEADERS     = {"User-Agent": "Mozilla/5.0 (compatible; BlogBot/1.0)"}


# ── Class ─────────────────────────────────────────────────────────────────────
class FlipboardPublisher:
    """Pings Flipboard's indexing endpoints to get posts discovered and curated."""

    def __init__(self, email: str = "", token: str = "") -> None:
        self.email = email
        self.token = token

    # ── Public methods ────────────────────────────────────────────────────────

    def submit_url(self, url: str, title: str) -> bool:
        """
        Ping Flipboard with a post URL so they can index it.

        Two pings:
          1. GET https://api.flipboard.com/flipboard.php?url={encoded_url}
          2. GET https://share.flipboard.com/bookmarklet/popout?v=2&title={encoded_title}&url={encoded_url}

        Returns True if either ping returns HTTP 200.
        """
        success = False

        # Ping 1 — API discovery endpoint
        api_url = f"{_API_PING}?url={quote_plus(url)}"
        try:
            resp = requests.get(api_url, headers=_HEADERS, timeout=_TIMEOUT)
            if resp.status_code == 200:
                _log.info(f"Flipboard API ping accepted: {url}")
                success = True
            else:
                _log.debug(
                    f"Flipboard API ping returned HTTP {resp.status_code} for {url}"
                )
        except requests.RequestException as exc:
            _log.warning(f"Flipboard API ping error for {url}: {exc}")

        # Ping 2 — Share/bookmarklet endpoint (also triggers discovery)
        share_url = (
            f"{_SHARE_PING}"
            f"?v=2"
            f"&title={quote_plus(title)}"
            f"&url={quote_plus(url)}"
        )
        try:
            resp = requests.get(share_url, headers=_HEADERS, timeout=_TIMEOUT)
            if resp.status_code == 200:
                _log.info(f"Flipboard share ping accepted: {url}")
                success = True
            else:
                _log.debug(
                    f"Flipboard share ping returned HTTP {resp.status_code} for {url}"
                )
        except requests.RequestException as exc:
            _log.warning(f"Flipboard share ping error for {url}: {exc}")

        return success

    def bulk_submit_rss(self, rss_url: str) -> bool:
        """
        Ping Flipboard with an RSS feed URL so they can auto-index all its items.

        GET https://api.flipboard.com/flipboard.php?url={encoded_rss_url}
        Returns True on HTTP 200.
        """
        api_url = f"{_API_PING}?url={quote_plus(rss_url)}"
        try:
            resp = requests.get(api_url, headers=_HEADERS, timeout=_TIMEOUT)
            if resp.status_code == 200:
                _log.info(f"Flipboard RSS ping accepted: {rss_url}")
                return True
            _log.debug(
                f"Flipboard RSS ping returned HTTP {resp.status_code} for {rss_url}"
            )
            return False
        except requests.RequestException as exc:
            _log.warning(f"Flipboard RSS ping error for {rss_url}: {exc}")
            return False


# ── Factory ───────────────────────────────────────────────────────────────────
def make_flipboard_from_config() -> FlipboardPublisher:
    """
    Build a FlipboardPublisher from the encrypted config.
    Reads optional 'flipboard_token'. No auth required for basic pinging —
    always returns a usable publisher.
    """
    token = ""
    try:
        try:
            from modules.config_manager import get as cfg_get
        except ImportError:
            from config_manager import get as cfg_get
        token = cfg_get("flipboard_token") or ""
    except Exception as exc:
        _log.debug(f"Could not read flipboard_token from config: {exc}")

    return FlipboardPublisher(token=token)


# ── Top-level helper ──────────────────────────────────────────────────────────
def submit_post_to_flipboard(title: str, url: str, rss_url: str) -> bool:
    """
    Ping Flipboard with a post URL and its blog RSS feed.

    Returns True if either the URL ping or the RSS ping succeeds.
    """
    publisher = make_flipboard_from_config()

    url_ok  = publisher.submit_url(url=url, title=title)
    rss_ok  = publisher.bulk_submit_rss(rss_url=rss_url)

    return url_ok or rss_ok
