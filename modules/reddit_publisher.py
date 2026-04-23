"""
BlogBot — reddit_publisher.py
Submits blog posts as link posts to Reddit, targeting the most appropriate
subreddit for each niche.
Uses praw (already installed).
Rate limits and whitelist blocks are caught and skipped gracefully.
"""

import logging
import sys
from pathlib import Path
from typing import Dict, List, Optional

# ── BASE_DIR bootstrap ────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent.parent.resolve()
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

LOGS_DIR = BASE_DIR / "logs"
LOGS_DIR.mkdir(parents=True, exist_ok=True)

# ── Logging ───────────────────────────────────────────────────────────────────
_log = logging.getLogger("reddit_publisher")
_log.setLevel(logging.INFO)
if not _log.handlers:
    _fh = logging.FileHandler(LOGS_DIR / "activity.log", encoding="utf-8")
    _fh.setFormatter(
        logging.Formatter("%(asctime)s [REDDIT] %(levelname)s %(message)s")
    )
    _log.addHandler(_fh)

# ── Niche → subreddit mapping ─────────────────────────────────────────────────
NICHE_SUBREDDITS: Dict[str, List[str]] = {
    "tech":          ["technology", "gadgets"],
    "technology":    ["technology", "gadgets"],
    "gadgets":       ["gadgets", "technology"],
    "gaming":        ["gaming", "pcgaming"],
    "crypto":        ["CryptoCurrency", "Bitcoin"],
    "blockchain":    ["CryptoCurrency", "ethereum"],
    "finance":       ["personalfinance", "investing"],
    "investing":     ["investing", "stocks"],
    "health":        ["loseit", "Health"],
    "weight_loss":   ["loseit", "Fitness"],
    "fitness":       ["Fitness", "loseit"],
    "entertainment": ["entertainment", "movies"],
    "celebrity":     ["entertainment", "popculturechat"],
    "viral":         ["entertainment", "movies"],
}

_FALLBACK_SUBREDDITS = ["self", "blog"]

# Error substrings that mean "skip gracefully" rather than "retry"
_SKIP_ERROR_CODES = {"RATELIMIT", "NOT_WHITELISTED", "BANNED_FROM_SUBREDDIT",
                     "SUBREDDIT_NOTALLOWED", "DOMAIN_BANNED", "KARMA_REQUIRED"}


# ── RedditPublisher ───────────────────────────────────────────────────────────
class RedditPublisher:
    """
    Submits blog post URLs as Reddit link posts.

    Parameters
    ----------
    client_id     : Reddit app client ID
    client_secret : Reddit app client secret
    username      : Reddit account username
    password      : Reddit account password
    """

    def __init__(
        self,
        client_id:     str,
        client_secret: str,
        username:      str,
        password:      str,
    ) -> None:
        self.client_id     = client_id.strip()
        self.client_secret = client_secret.strip()
        self.username      = username.strip()
        self.password      = password.strip()

    def _get_reddit(self):
        """Initialise and return an authenticated praw.Reddit instance."""
        try:
            import praw
        except ImportError:
            raise ImportError("praw not installed — run: pip install praw")

        return praw.Reddit(
            client_id=self.client_id,
            client_secret=self.client_secret,
            username=self.username,
            password=self.password,
            user_agent="BlogBot/1.0",
        )

    def submit(self, title: str, url: str, subreddit: str) -> bool:
        """
        Submit a link post to the given subreddit.

        Catches praw.exceptions.RedditAPIException and returns False gracefully
        for rate limits, whitelist requirements, domain bans, and similar
        permanent or temporary blocks.

        Returns True if the submission was accepted, False otherwise.
        """
        try:
            import praw
            import praw.exceptions
        except ImportError:
            _log.error("praw not installed — run: pip install praw")
            return False

        try:
            reddit = self._get_reddit()
            sub    = reddit.subreddit(subreddit)
            submission = sub.submit(title=title, url=url)
            _log.info(
                f"Reddit: submitted to r/{subreddit} — "
                f"id={submission.id} title={title!r}"
            )
            return True

        except praw.exceptions.RedditAPIException as exc:
            # Check each error item for known skip codes
            for item in exc.items:
                if any(code in item.error_type.upper() for code in _SKIP_ERROR_CODES):
                    _log.warning(
                        f"Reddit: r/{subreddit} skipped — "
                        f"error_type={item.error_type!r} message={item.message!r}"
                    )
                    return False
            # Unknown API exception — log at warning and skip
            _log.warning(
                f"Reddit: RedditAPIException for r/{subreddit}: {exc}"
            )
            return False

        except praw.exceptions.PRAWException as exc:
            _log.warning(f"Reddit: PRAW error for r/{subreddit}: {exc}")
            return False

        except Exception as exc:
            _log.warning(f"Reddit: unexpected error for r/{subreddit}: {exc}")
            return False


# ── Config helper ─────────────────────────────────────────────────────────────
def _cfg_get(key: str) -> str:
    try:
        from modules.config_manager import get as cfg_get
        return cfg_get(key) or ""
    except Exception:
        try:
            from config_manager import get as cfg_get
            return cfg_get(key) or ""
        except Exception:
            return ""


# ── Factory ───────────────────────────────────────────────────────────────────
def make_reddit_from_config() -> Optional[RedditPublisher]:
    """
    Build a RedditPublisher from config.

    Reads:
        reddit_client_id     — Reddit app client ID
        reddit_client_secret — Reddit app client secret
        reddit_username      — Reddit account username
        reddit_password      — Reddit account password

    Returns None silently if any credential is missing.
    """
    client_id     = _cfg_get("reddit_client_id")
    client_secret = _cfg_get("reddit_client_secret")
    username      = _cfg_get("reddit_username")
    password      = _cfg_get("reddit_password")

    if not all([client_id, client_secret, username, password]):
        _log.debug(
            "Reddit: one or more credentials not configured "
            "(reddit_client_id / reddit_client_secret / "
            "reddit_username / reddit_password) — skipping"
        )
        return None

    return RedditPublisher(
        client_id=client_id,
        client_secret=client_secret,
        username=username,
        password=password,
    )


# ── Top-level entry point ─────────────────────────────────────────────────────
def publish_to_reddit(title: str, url: str, niche: str) -> bool:
    """
    Submit a blog post URL to the primary subreddit for the given niche.

    Uses the FIRST subreddit in NICHE_SUBREDDITS for the niche. Falls back to
    the fallback list if the niche is not mapped.

    Called by bot_loop.py after a post is successfully published to
    Cloudflare Pages.  Never raises — any failure returns False so the
    bot continues without interruption.

    Parameters
    ----------
    title : Post headline
    url   : Canonical URL on Cloudflare Pages
    niche : Blog niche — determines target subreddit

    Returns True if the post was submitted, False otherwise.
    """
    publisher = make_reddit_from_config()
    if publisher is None:
        return False

    niche_key   = niche.lower().replace("-", "_").replace(" ", "_")
    subreddits  = NICHE_SUBREDDITS.get(niche_key, _FALLBACK_SUBREDDITS)
    target_sub  = subreddits[0]  # submit to the primary subreddit for the niche

    _log.info(
        f"Reddit: attempting submission to r/{target_sub} "
        f"for niche={niche!r} title={title!r}"
    )

    try:
        return publisher.submit(title=title, url=url, subreddit=target_sub)
    except Exception as exc:
        _log.error(f"publish_to_reddit: unexpected error: {exc}")
        return False


# ── Self-test ─────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("reddit_publisher self-test")
    print("=" * 40)

    try:
        import praw  # noqa: F401
        import praw.exceptions  # noqa: F401
        print("[OK] praw imports correctly")
    except ImportError as exc:
        print(f"[FAIL] praw import error: {exc}")
        print("       Run: pip install praw")
        sys.exit(1)

    # Unconfigured — should return False silently
    result = publish_to_reddit(
        title="Test Post",
        url="https://example.pages.dev/posts/test.html",
        niche="tech",
    )
    print(
        f"[{'OK' if result is False else 'FAIL'}] "
        f"publish_to_reddit (unconfigured) returned False: {result is False}"
    )

    # Factory returns None when unconfigured
    pub = make_reddit_from_config()
    print(f"[OK] make_reddit_from_config (unconfigured) returns None: {pub is None}")

    # Niche mapping checks
    test_cases = [
        ("tech",          "technology"),
        ("crypto",        "CryptoCurrency"),
        ("finance",       "personalfinance"),
        ("health",        "loseit"),
        ("entertainment", "entertainment"),
        ("celebrity",     "entertainment"),
        ("unknown_niche", _FALLBACK_SUBREDDITS[0]),
    ]
    for niche, expected_sub in test_cases:
        niche_key = niche.lower().replace("-", "_").replace(" ", "_")
        subs      = NICHE_SUBREDDITS.get(niche_key, _FALLBACK_SUBREDDITS)
        ok        = subs[0] == expected_sub
        print(
            f"  [{'OK' if ok else 'FAIL'}] niche={niche!r} → "
            f"r/{subs[0]} (expected r/{expected_sub})"
        )

    print("=" * 40)
    print("Self-test complete.")
