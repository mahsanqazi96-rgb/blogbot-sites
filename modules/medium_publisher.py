"""
BlogBot — medium_publisher.py
Medium syndication: publishes every post to Medium with canonical URL.
Builds passive referral traffic from Medium's 100M+ readers.
Zero SEO impact — canonical tag credits original blog, not Medium.
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
_log = logging.getLogger("medium_publisher")
_log.setLevel(logging.INFO)
if not _log.handlers:
    _fh = logging.FileHandler(LOGS_DIR / "activity.log", encoding="utf-8")
    _fh.setFormatter(logging.Formatter("%(asctime)s [MEDIUM] %(levelname)s %(message)s"))
    _log.addHandler(_fh)

# ── Niche → Medium tag mapping ────────────────────────────────────────────────
NICHE_TAGS: dict = {
    "health":        ["health", "wellness", "fitness"],
    "weight_loss":   ["health", "wellness", "fitness"],
    "crypto":        ["cryptocurrency", "bitcoin", "blockchain"],
    "finance":       ["finance", "investing", "money"],
    "tech":          ["technology", "gadgets", "software"],
    "technology":    ["technology", "gadgets", "software"],
    "entertainment": ["entertainment", "celebrity", "culture"],
    "viral":         ["entertainment", "celebrity", "culture"],
    "celebrity":     ["entertainment", "celebrity", "culture"],
}

_DEFAULT_TAGS = ["blogging", "news", "lifestyle"]


# ── MediumPublisher ───────────────────────────────────────────────────────────
class MediumPublisher:
    """
    Publishes posts to Medium via the official Integration Token API.

    Parameters
    ----------
    integration_token : Medium integration token obtained from
                        medium.com/me/settings → Integration tokens
    """

    _ME_URL    = "https://api.medium.com/v1/me"
    _POSTS_URL = "https://api.medium.com/v1/users/{author_id}/posts"
    _TIMEOUT   = 30  # seconds

    def __init__(self, integration_token: str) -> None:
        self.integration_token = integration_token.strip()
        self._author_id: Optional[str] = None  # cached after first _get_author_id()

    # ── Internal helpers ──────────────────────────────────────────────────────
    def _auth_headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.integration_token}",
            "Content-Type":  "application/json",
            "Accept":        "application/json",
        }

    def _get_author_id(self) -> str:
        """
        Fetch and cache the authenticated user's Medium author ID.

        Returns the author ID string on success.
        Raises RuntimeError if the API call fails so publish() can catch it.
        """
        if self._author_id:
            return self._author_id

        try:
            response = requests.get(
                self._ME_URL,
                headers=self._auth_headers(),
                timeout=self._TIMEOUT,
            )
            data = response.json()

            if not response.ok:
                raise RuntimeError(
                    f"Medium /me returned HTTP {response.status_code}: "
                    f"{data.get('errors', data)}"
                )

            author_id = data.get("data", {}).get("id", "")
            if not author_id:
                raise RuntimeError(f"Medium /me response missing data.id: {data}")

            self._author_id = author_id
            _log.info(f"Medium author ID fetched and cached: {author_id}")
            return author_id

        except RuntimeError:
            raise
        except requests.exceptions.Timeout:
            raise RuntimeError("Medium /me timed out after 30 s")
        except requests.exceptions.ConnectionError as exc:
            raise RuntimeError(f"Medium /me connection error: {exc}")
        except Exception as exc:
            raise RuntimeError(f"Medium /me unexpected error: {exc}")

    # ── Public API ────────────────────────────────────────────────────────────
    def publish(
        self,
        title:        str,
        content_html: str,
        canonical_url: str,
        tags:         list,
        status:       str = "public",
    ) -> dict:
        """
        Publish an HTML post to Medium with a canonical URL pointing back to
        the original blog. Medium will display "Originally published at <url>"
        and Google honours the canonical — no duplicate-content penalty.

        Parameters
        ----------
        title         : Post headline
        content_html  : Full post body as HTML string
        canonical_url : Permanent URL on the original Cloudflare Pages blog
        tags          : List of topic tags (first 5 are used — Medium's limit)
        status        : "public" | "draft" | "unlisted"  (default: "public")

        Returns
        -------
        dict  Response JSON from Medium, or {"error": "<reason>"} on failure.
        """
        try:
            author_id = self._get_author_id()
        except RuntimeError as exc:
            _log.error(f"publish: could not fetch author ID — {exc}")
            return {"error": str(exc)}

        url     = self._POSTS_URL.format(author_id=author_id)
        payload = {
            "title":         title,
            "contentFormat": "html",
            "content":       content_html,
            "canonicalUrl":  canonical_url,
            "tags":          tags[:5],          # Medium enforces max 5 tags
            "publishStatus": status,
        }

        try:
            response = requests.post(
                url,
                headers=self._auth_headers(),
                json=payload,
                timeout=self._TIMEOUT,
            )
            data = response.json()

            if response.ok and data.get("data", {}).get("id"):
                post_data = data["data"]
                post_url  = post_data.get("url", "")
                _log.info(
                    f"Medium publish OK — "
                    f"medium_url={post_url!r} "
                    f"canonical={canonical_url!r} "
                    f"title={title!r}"
                )
            else:
                _log.warning(
                    f"Medium publish failed — HTTP {response.status_code} "
                    f"errors={data.get('errors', data)}"
                )

            return data

        except requests.exceptions.Timeout:
            _log.error(f"Medium publish timed out after 30 s — title={title!r}")
            return {"error": "timeout"}
        except requests.exceptions.ConnectionError as exc:
            _log.error(f"Medium publish connection error: {exc}")
            return {"error": "connection_error"}
        except Exception as exc:
            _log.error(f"Medium publish unexpected error: {exc}")
            return {"error": str(exc)}


# ── Factory ───────────────────────────────────────────────────────────────────
def make_medium_publisher_from_config() -> Optional[MediumPublisher]:
    """
    Build a MediumPublisher from encrypted config.json.

    Reads:
        medium_integration_token — Medium Integration Token

    Returns None (silently) if the token is not set, so callers degrade
    gracefully without crashing bot_loop.py.
    """
    try:
        from modules.config_manager import get as cfg_get
        token = cfg_get("medium_integration_token", "")
    except Exception as exc:
        _log.warning(f"make_medium_publisher_from_config: config read error — {exc}")
        return None

    if not token:
        _log.debug(
            "Medium syndication disabled — set medium_integration_token "
            "in config.json to enable"
        )
        return None

    return MediumPublisher(integration_token=token)


# ── Convenience entry point ───────────────────────────────────────────────────
def syndicate_post(
    title:        str,
    content_html: str,
    canonical_url: str,
    niche:        str,
    keywords:     list,
) -> bool:
    """
    Syndicate a published blog post to Medium with the canonical URL intact.

    Called by bot_loop.py after a post is successfully published to
    Cloudflare Pages.  Never raises — any failure returns False so the bot
    continues without interruption.

    Parameters
    ----------
    title         : Post headline
    content_html  : Full HTML content of the post
    canonical_url : Permanent URL on the original Cloudflare Pages blog
    niche         : Blog niche — maps to Medium topic tags automatically
    keywords      : List of post keywords (appended to niche tags, up to 5 total)

    Returns
    -------
    True  if Medium accepted the post.
    False if Medium is not configured, the post was rejected, or any error occurs.
    """
    publisher = make_medium_publisher_from_config()
    if publisher is None:
        # Medium not configured — silent skip
        return False

    # Build tag list: niche base tags + keyword tags, deduped, max 5
    niche_key  = niche.lower().replace("-", "_").replace(" ", "_")
    base_tags  = NICHE_TAGS.get(niche_key, _DEFAULT_TAGS)

    combined: list = []
    seen: set      = set()
    for tag in base_tags + [k.lower() for k in keywords]:
        clean = tag.strip()
        if clean and clean not in seen:
            combined.append(clean)
            seen.add(clean)
        if len(combined) == 5:
            break

    if not combined:
        combined = _DEFAULT_TAGS[:5]

    try:
        result = publisher.publish(
            title=title,
            content_html=content_html,
            canonical_url=canonical_url,
            tags=combined,
        )
    except Exception as exc:
        # Belt-and-suspenders: publish() already handles all exceptions
        # internally, but guard here too so bot_loop.py is never at risk.
        _log.error(f"syndicate_post unhandled exception: {exc}")
        return False

    # Success = response contains data.id with no errors key
    if result.get("data", {}).get("id") and not result.get("errors"):
        _log.info(
            f"syndicate_post OK — niche={niche!r} "
            f"canonical={canonical_url!r} tags={combined}"
        )
        return True

    _log.warning(
        f"syndicate_post failed — niche={niche!r} "
        f"canonical={canonical_url!r} result={result}"
    )
    return False


# ── Self-Test ─────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("medium_publisher self-test...")

    # Factory with missing config
    publisher = make_medium_publisher_from_config()
    print(f"  make_medium_publisher_from_config (unconfigured): "
          f"{'None as expected' if publisher is None else 'UNEXPECTED PUBLISHER'}")

    # syndicate_post short-circuits gracefully
    result = syndicate_post(
        title="Test Post",
        content_html="<p>Test content</p>",
        canonical_url="https://example.pages.dev/posts/test-post.html",
        niche="crypto",
        keywords=["bitcoin", "defi"],
    )
    print(f"  syndicate_post (unconfigured): "
          f"{'False as expected' if result is False else 'UNEXPECTED TRUE'}")

    # Tag mapping test
    from modules.medium_publisher import NICHE_TAGS
    for niche, expected_first in [
        ("health",        "health"),
        ("crypto",        "cryptocurrency"),
        ("finance",       "finance"),
        ("tech",          "technology"),
        ("entertainment", "entertainment"),
    ]:
        tags = NICHE_TAGS.get(niche, [])
        ok   = tags and tags[0] == expected_first
        print(f"  NICHE_TAGS[{niche!r}]: {tags} — {'OK' if ok else 'FAIL'}")

    print("Self-test complete.")
