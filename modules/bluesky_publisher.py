"""
BlogBot — bluesky_publisher.py
Publishes blog post announcements to Bluesky (AT Protocol) with a link card embed.
Uses the atproto library (already installed).
Link cards give rich previews in the Bluesky feed, driving higher click-through.
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
_log = logging.getLogger("bluesky_publisher")
_log.setLevel(logging.INFO)
if not _log.handlers:
    _fh = logging.FileHandler(LOGS_DIR / "activity.log", encoding="utf-8")
    _fh.setFormatter(
        logging.Formatter("%(asctime)s [BLUESKY] %(levelname)s %(message)s")
    )
    _log.addHandler(_fh)

# ── Constants ─────────────────────────────────────────────────────────────────
_EXCERPT_LIMIT = 200   # chars for excerpt truncation in post text and link card


# ── BlueSkyPublisher ──────────────────────────────────────────────────────────
class BlueSkyPublisher:
    """
    Posts blog announcements to Bluesky with an external link card (embed).

    Parameters
    ----------
    handle   : Bluesky handle, e.g. "myblog.bsky.social"
    password : App password generated at bsky.app → Settings → App Passwords
    """

    def __init__(self, handle: str, password: str) -> None:
        self.handle   = handle.strip()
        self.password = password.strip()

    def publish(self, title: str, url: str, excerpt: str = "") -> bool:
        """
        Create a Bluesky post with an external link card embed.

        Post text format:
            {title}

            {excerpt trimmed to 200 chars}   ← omitted when empty

            {url}

        Returns True on success, False on any failure.
        """
        try:
            from atproto import Client
            from atproto import models as atproto_models
        except ImportError:
            _log.error("atproto not installed — run: pip install atproto")
            return False

        # Build post text
        excerpt_trimmed = (excerpt.strip()[:_EXCERPT_LIMIT].rstrip() if excerpt and excerpt.strip() else "")
        parts = [title.strip()]
        if excerpt_trimmed:
            parts.append(excerpt_trimmed)
        parts.append(url.strip())
        post_text = "\n\n".join(parts)

        try:
            client = Client()
            client.login(self.handle, self.password)
        except Exception as exc:
            _log.warning(f"Bluesky: login failed for {self.handle!r}: {exc}")
            return False

        # Build the external link card embed
        try:
            embed = atproto_models.AppBskyEmbedExternal.Main(
                external=atproto_models.AppBskyEmbedExternal.External(
                    uri=url.strip(),
                    title=title.strip(),
                    description=excerpt_trimmed or title.strip(),
                )
            )

            client.send_post(text=post_text, embed=embed)
            _log.info(
                f"Bluesky: posted as {self.handle!r} — title={title!r} url={url!r}"
            )
            return True

        except Exception as exc:
            _log.warning(f"Bluesky: send_post failed: {exc}")
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
def make_bluesky_from_config() -> Optional[BlueSkyPublisher]:
    """
    Build a BlueSkyPublisher from config.

    Reads:
        bluesky_handle       — Bluesky handle, e.g. "yourblog.bsky.social"
        bluesky_app_password — App password from bsky.app settings

    Returns None silently if either credential is not configured.
    """
    handle   = _cfg_get("bluesky_handle")
    password = _cfg_get("bluesky_app_password")

    if not handle or not password:
        _log.debug(
            "Bluesky: bluesky_handle or bluesky_app_password not configured — skipping"
        )
        return None

    return BlueSkyPublisher(handle=handle, password=password)


# ── Top-level entry point ─────────────────────────────────────────────────────
def publish_to_bluesky(
    title:   str,
    url:     str,
    niche:   str,
    excerpt: str = "",
) -> bool:
    """
    Publish a blog post announcement to Bluesky with a link card embed.

    Called by bot_loop.py after a post is successfully published to
    Cloudflare Pages.  Never raises — any failure returns False so the
    bot continues without interruption.

    Parameters
    ----------
    title   : Post headline
    url     : Canonical URL on Cloudflare Pages
    niche   : Blog niche (informational; not used to gate posting)
    excerpt : Optional post excerpt — trimmed to 200 chars in post + link card

    Returns True if the post was created, False otherwise.
    """
    publisher = make_bluesky_from_config()
    if publisher is None:
        return False

    try:
        return publisher.publish(title=title, url=url, excerpt=excerpt)
    except Exception as exc:
        _log.error(f"publish_to_bluesky: unexpected error: {exc}")
        return False


# ── Self-test ─────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("bluesky_publisher self-test")
    print("=" * 40)

    try:
        from atproto import Client  # noqa: F401
        from atproto import models as _m  # noqa: F401
        print("[OK] atproto imports correctly")
    except ImportError as exc:
        print(f"[FAIL] atproto import error: {exc}")
        print("       Run: pip install atproto")
        sys.exit(1)

    # Unconfigured — should return False silently
    result = publish_to_bluesky(
        title="Test Post",
        url="https://example.pages.dev/posts/test.html",
        niche="tech",
        excerpt="A short excerpt about the test post.",
    )
    print(
        f"[{'OK' if result is False else 'FAIL'}] "
        f"publish_to_bluesky (unconfigured) returned False: {result is False}"
    )

    # Factory returns None when unconfigured
    pub = make_bluesky_from_config()
    print(f"[OK] make_bluesky_from_config (unconfigured) returns None: {pub is None}")

    # Excerpt truncation check
    long_excerpt = "x" * 300
    pub_dummy = BlueSkyPublisher(handle="test.bsky.social", password="dummy")
    trimmed = long_excerpt[:_EXCERPT_LIMIT].rstrip()
    print(
        f"[{'OK' if len(trimmed) == _EXCERPT_LIMIT else 'FAIL'}] "
        f"Excerpt trimmed to {_EXCERPT_LIMIT} chars: len={len(trimmed)}"
    )

    print("=" * 40)
    print("Self-test complete.")
