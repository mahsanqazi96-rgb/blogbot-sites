"""
BlogBot — twitter_publisher.py
Posts new blog content to Twitter/X using tweepy (Twitter API v2).

Credentials required (set via setup_traffic_keys.py):
  twitter_api_key        — Consumer API Key
  twitter_api_secret     — Consumer API Secret
  twitter_access_token   — Access Token
  twitter_access_secret  — Access Token Secret

Security:
  - All credentials from AES-256 encrypted config.json via config_manager
  - Only connects to api.twitter.com (tweepy default endpoint)
  - Circuit breaker: opens after 5 failures, 5-min cooldown
  - Credentials logged masked (first 8 chars + '...' only)
  - wait_on_rate_limit=True — never hammers API on rate-limit errors
  - No eval/exec anywhere in this module

Twitter API v2 free tier:
  - 500 tweets/month (Essential access)
  - Bot uses ~1-2 tweets per post cycle
"""

import sys
import logging
from pathlib import Path
from typing import Optional, List

BASE_DIR = Path(__file__).parent.parent.resolve()
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

LOGS_DIR = BASE_DIR / "logs"

# ── Optional: tweepy ───────────────────────────────────────────────────────────
try:
    import tweepy
    _TWEEPY_OK = True
except ImportError:
    _TWEEPY_OK = False

from modules.circuit_breaker import get_breaker, ServiceUnavailableError

_log = logging.getLogger("twitter_publisher")
_log.setLevel(logging.INFO)
if not _log.handlers:
    _fh = logging.FileHandler(LOGS_DIR / "activity.log", encoding="utf-8")
    _fh.setFormatter(logging.Formatter("%(asctime)s [TWITTER] %(levelname)s %(message)s"))
    _log.addHandler(_fh)

_twitter_breaker = get_breaker("twitter", failure_threshold=5, timeout_sec=300)

# ── Niche hashtag mapping ──────────────────────────────────────────────────────
NICHE_HASHTAGS: dict = {
    "crypto":        ["crypto", "bitcoin", "blockchain", "defi"],
    "finance":       ["finance", "investing", "stocks", "money"],
    "health":        ["health", "wellness", "fitness", "nutrition"],
    "tech":          ["technology", "tech", "ai", "innovation"],
    "entertainment": ["entertainment", "trending", "viral", "news"],
}

# Twitter URL always counts as 23 chars in tweet length calculation
_URL_CHAR_COUNT = 23


class TwitterPublisher:
    """
    Wraps tweepy.Client (API v2) for posting blog content to Twitter/X.
    Credentials loaded from encrypted config.json — never hardcoded.
    """

    def __init__(self):
        self._client: Optional[object] = None
        self._configured = False
        self._load_credentials()

    def _load_credentials(self):
        """Load Twitter credentials from config_manager. Log masked values."""
        if not _TWEEPY_OK:
            _log.debug("tweepy not installed — Twitter publisher disabled")
            return
        try:
            from modules.config_manager import get
            api_key       = get("twitter_api_key",       "")
            api_secret    = get("twitter_api_secret",    "")
            access_token  = get("twitter_access_token",  "")
            access_secret = get("twitter_access_secret", "")

            if not all([api_key, api_secret, access_token, access_secret]):
                _log.debug(
                    "Twitter credentials not configured — skipping "
                    "(run setup_traffic_keys.py to configure)"
                )
                return

            # Log masked credentials (first 8 chars only — never full value)
            _log.debug(
                f"Twitter credentials loaded — "
                f"api_key={api_key[:8]}... "
                f"access_token={access_token[:8]}..."
            )

            self._client = tweepy.Client(
                consumer_key=api_key,
                consumer_secret=api_secret,
                access_token=access_token,
                access_token_secret=access_secret,
                wait_on_rate_limit=True,   # Never hammer API on rate limits
            )
            self._configured = True
        except Exception as e:
            _log.error(f"TwitterPublisher._load_credentials failed: {e}")

    def _is_configured(self) -> bool:
        return self._configured and self._client is not None

    def _build_tweet(self, title: str, url: str, niche: str,
                     tags: Optional[List[str]] = None) -> str:
        """
        Build tweet text: title + URL + hashtags.
        Total length capped at 280 chars. URL always counts as 23 chars.
        """
        hashtags = list(dict.fromkeys(
            (NICHE_HASHTAGS.get(niche, []) + (tags or []))[:4]
        ))
        hashtag_str = " ".join(f"#{t.replace(' ', '')}" for t in hashtags)

        # Budget: 280 - 23 (url) - 2 (newlines) - len(hashtag_str) - 1 (space)
        title_budget = 280 - _URL_CHAR_COUNT - 2 - len(hashtag_str) - 1
        if len(title) > title_budget:
            title = title[:title_budget - 3] + "..."

        return f"{title}\n\n{url}\n\n{hashtag_str}".strip()

    def post_tweet(self, text: str) -> bool:
        """
        Post a single tweet. Circuit-breaker protected. Returns True on success.
        Target: api.twitter.com (tweepy default — never changes)
        """
        if not self._is_configured():
            return False

        def _do():
            _log.info("Twitter: posting tweet → api.twitter.com/2/tweets")
            response = self._client.create_tweet(text=text)
            return response

        try:
            response = _twitter_breaker.call(_do)
            if response and response.data:
                tweet_id = response.data.get("id", "?")
                _log.info(f"Twitter: tweet posted — id={tweet_id}")
                return True
            _log.warning("Twitter: create_tweet returned empty response")
            return False
        except ServiceUnavailableError:
            _log.warning("Twitter: circuit breaker open — skipping")
            return False
        except Exception as e:
            _log.error(f"Twitter: post_tweet error: {e}")
            return False

    def publish(self, title: str, url: str, niche: str,
                tags: Optional[List[str]] = None) -> bool:
        """
        Build and post a tweet for a new blog post.
        Returns True if tweet was successfully posted.
        """
        if not self._is_configured():
            return False
        try:
            tweet_text = self._build_tweet(title, url, niche, tags)
            return self.post_tweet(tweet_text)
        except Exception as e:
            _log.error(f"TwitterPublisher.publish error: {e}")
            return False


# ── Module-level convenience functions ────────────────────────────────────────

_publisher_instance: Optional[TwitterPublisher] = None


def make_twitter_from_config() -> Optional[TwitterPublisher]:
    """Factory: build TwitterPublisher from config. Returns None if not configured."""
    global _publisher_instance
    if _publisher_instance is None:
        _publisher_instance = TwitterPublisher()
    return _publisher_instance if _publisher_instance._is_configured() else None


def publish_to_twitter(title: str, url: str, niche: str,
                       tags: Optional[List[str]] = None) -> bool:
    """
    Post a new blog entry to Twitter/X.
    Returns False silently if credentials not configured — never raises.
    """
    try:
        pub = make_twitter_from_config()
        if pub is None:
            return False
        return pub.publish(title=title, url=url, niche=niche, tags=tags)
    except Exception as e:
        _log.error(f"publish_to_twitter error: {e}")
        return False


# ── Self-test ─────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    pub = TwitterPublisher()
    print(f"Configured: {pub._is_configured()}")
    tweet = pub._build_tweet(
        "Bitcoin Hits $100K: What Investors Need to Know Now",
        "https://topicpulse.pages.dev/cryptoinsiderdaily/posts/btc-100k.html",
        "crypto",
    )
    print(f"Tweet ({len(tweet)} chars):\n{tweet}")
    assert len(tweet) <= 280, f"Tweet too long: {len(tweet)}"
    print("Self-test passed.")
