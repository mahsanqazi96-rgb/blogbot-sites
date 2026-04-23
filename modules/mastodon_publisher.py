"""
BlogBot — mastodon_publisher.py
Publishes blog post announcements to a Mastodon instance.
Uses Mastodon.py (already installed).
Posts are public and include niche hashtags for discoverability in the
Fediverse federated timeline.
"""

import logging
import sys
from pathlib import Path
from typing import Optional

# ── BASE_DIR bootstrap ────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent.parent.resolve()
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

LOGS_DIR = BASE_DIR / "logs"
LOGS_DIR.mkdir(parents=True, exist_ok=True)

# ── Logging ───────────────────────────────────────────────────────────────────
_log = logging.getLogger("mastodon_publisher")
_log.setLevel(logging.INFO)
if not _log.handlers:
    _fh = logging.FileHandler(LOGS_DIR / "activity.log", encoding="utf-8")
    _fh.setFormatter(
        logging.Formatter("%(asctime)s [MASTODON] %(levelname)s %(message)s")
    )
    _log.addHandler(_fh)

# ── Constants ─────────────────────────────────────────────────────────────────
_MASTODON_CHAR_LIMIT = 500   # Mastodon's default status character limit
_EXCERPT_LIMIT       = 200   # initial excerpt trim before fitting into 500 chars


# ── MastodonPublisher ─────────────────────────────────────────────────────────
class MastodonPublisher:
    """
    Posts blog announcements to a Mastodon instance as public statuses.

    Parameters
    ----------
    instance_url   : Base URL of the Mastodon instance, e.g. "https://mastodon.social"
    access_token   : OAuth access token from instance → Settings → Development
    """

    def __init__(self, instance_url: str, access_token: str) -> None:
        self.instance_url = instance_url.rstrip("/").strip()
        self.access_token = access_token.strip()

    def publish(self, title: str, url: str, niche: str, excerpt: str = "") -> bool:
        """
        Post a public status to Mastodon with hashtags for the given niche.

        Post format (trimmed to fit 500 chars):
            {title}

            {excerpt trimmed to 200 chars}   ← omitted when empty

            {url}

            #{niche} #news #blogging

        Returns True on success, False on any failure.
        """
        try:
            from mastodon import Mastodon
        except ImportError:
            _log.error("Mastodon.py not installed — run: pip install Mastodon.py")
            return False

        # Build hashtag suffix
        niche_tag  = niche.strip().replace(" ", "_").replace("-", "_").lower()
        hashtags   = f"#{niche_tag} #news #blogging" if niche_tag else "#news #blogging"

        # Build status text, trim excerpt if necessary to stay under 500 chars
        excerpt_trimmed = (excerpt.strip()[:_EXCERPT_LIMIT].rstrip() if excerpt and excerpt.strip() else "")
        status_text     = self._fit_to_limit(
            title=title.strip(),
            url=url.strip(),
            excerpt=excerpt_trimmed,
            hashtags=hashtags,
        )

        try:
            mastodon = Mastodon(
                access_token=self.access_token,
                api_base_url=self.instance_url,
            )
            mastodon.status_post(status=status_text, visibility="public")
            _log.info(
                f"Mastodon: posted to {self.instance_url!r} — "
                f"niche={niche!r} title={title!r}"
            )
            return True

        except Exception as exc:
            _log.warning(f"Mastodon: status_post failed: {exc}")
            return False

    # ── Internal helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _fit_to_limit(
        title:    str,
        url:      str,
        excerpt:  str,
        hashtags: str,
    ) -> str:
        """
        Assemble the status text and shorten the excerpt if needed to stay
        within _MASTODON_CHAR_LIMIT characters.

        Structure (each section separated by double newline):
            {title}
            {excerpt}   ← dropped entirely if even empty excerpt doesn't fit
            {url}
            {hashtags}
        """
        # Skeleton without excerpt
        skeleton = "\n\n".join(filter(None, [title, url, hashtags]))
        available_for_excerpt = _MASTODON_CHAR_LIMIT - len(skeleton) - 2  # 2 for "\n\n"

        if excerpt and available_for_excerpt > 10:
            excerpt = excerpt[:available_for_excerpt].rstrip()
        else:
            excerpt = ""

        parts = [title]
        if excerpt:
            parts.append(excerpt)
        parts.append(url)
        parts.append(hashtags)

        status = "\n\n".join(parts)

        # Hard safety cut (shouldn't trigger, but just in case)
        if len(status) > _MASTODON_CHAR_LIMIT:
            status = status[:_MASTODON_CHAR_LIMIT]

        return status


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
def make_mastodon_from_config() -> Optional[MastodonPublisher]:
    """
    Build a MastodonPublisher from config.

    Reads:
        mastodon_instance_url  — e.g. "https://mastodon.social"
        mastodon_access_token  — OAuth token from instance developer settings

    Returns None silently if either value is not configured.
    """
    instance_url = _cfg_get("mastodon_instance_url")
    access_token = _cfg_get("mastodon_access_token")

    if not instance_url or not access_token:
        _log.debug(
            "Mastodon: mastodon_instance_url or mastodon_access_token not configured — skipping"
        )
        return None

    return MastodonPublisher(instance_url=instance_url, access_token=access_token)


# ── Top-level entry point ─────────────────────────────────────────────────────
def publish_to_mastodon(
    title:   str,
    url:     str,
    niche:   str,
    excerpt: str = "",
) -> bool:
    """
    Publish a blog post announcement to Mastodon as a public status.

    Called by bot_loop.py after a post is successfully published to
    Cloudflare Pages.  Never raises — any failure returns False so the
    bot continues without interruption.

    Parameters
    ----------
    title   : Post headline
    url     : Canonical URL on Cloudflare Pages
    niche   : Blog niche — used as the primary hashtag
    excerpt : Optional post excerpt — trimmed to fit within 500 char limit

    Returns True if the status was posted, False otherwise.
    """
    publisher = make_mastodon_from_config()
    if publisher is None:
        return False

    try:
        return publisher.publish(title=title, url=url, niche=niche, excerpt=excerpt)
    except Exception as exc:
        _log.error(f"publish_to_mastodon: unexpected error: {exc}")
        return False


# ── Self-test ─────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("mastodon_publisher self-test")
    print("=" * 40)

    try:
        from mastodon import Mastodon  # noqa: F401
        print("[OK] Mastodon.py imports correctly")
    except ImportError as exc:
        print(f"[FAIL] Mastodon.py import error: {exc}")
        print("       Run: pip install Mastodon.py")
        sys.exit(1)

    # Unconfigured — should return False silently
    result = publish_to_mastodon(
        title="Test Post",
        url="https://example.pages.dev/posts/test.html",
        niche="tech",
        excerpt="A short excerpt about the test post.",
    )
    print(
        f"[{'OK' if result is False else 'FAIL'}] "
        f"publish_to_mastodon (unconfigured) returned False: {result is False}"
    )

    # Factory returns None when unconfigured
    pub = make_mastodon_from_config()
    print(f"[OK] make_mastodon_from_config (unconfigured) returns None: {pub is None}")

    # Char-limit fitting test
    dummy = MastodonPublisher(instance_url="https://mastodon.social", access_token="x")
    long_excerpt = "word " * 200
    fitted = dummy._fit_to_limit(
        title="Test Title",
        url="https://example.com/post",
        excerpt=long_excerpt,
        hashtags="#tech #news #blogging",
    )
    under_limit = len(fitted) <= _MASTODON_CHAR_LIMIT
    print(
        f"[{'OK' if under_limit else 'FAIL'}] "
        f"_fit_to_limit respects {_MASTODON_CHAR_LIMIT} char limit: "
        f"len={len(fitted)}"
    )

    print("=" * 40)
    print("Self-test complete.")
