#!/usr/bin/env python3
"""
BlogBot — scripts/bluesky_rss_poster.py
========================================
Reads all feed.xml files found under sites/, posts any new items to Bluesky,
and persists the set of posted URLs in .github/bluesky_posted.json so the
workflow never double-posts.

Credentials are read ONLY from environment variables injected by GitHub Secrets —
nothing is ever hard-coded or logged.

Environment variables (both required):
  BLUESKY_IDENTIFIER  — Bluesky handle, e.g. "topicpulse.bsky.social"
  BLUESKY_PASSWORD    — Bluesky App Password (not your login password)

Safety limits:
  MAX_POSTS_PER_RUN = 5  — never flood Bluesky even if the feed has many new items
  State file keeps growing indefinitely (one URL per line in JSON) — never resets
"""

import json
import logging
import os
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, List, Set

# ── Logging — stdout only, no file writes (GitHub Actions shows stdout in UI) ──
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [BLUESKY-RSS] %(levelname)s %(message)s",
    stream=sys.stdout,
)
_log = logging.getLogger("bluesky_rss_poster")

# ── Paths ──────────────────────────────────────────────────────────────────────
BASE_DIR   = Path(__file__).parent.parent.resolve()
STATE_FILE = BASE_DIR / ".github" / "bluesky_posted.json"
SITES_DIR  = BASE_DIR / "sites"

# ── Tunables ───────────────────────────────────────────────────────────────────
MAX_POSTS_PER_RUN = 5    # max new Bluesky posts per workflow run
EXCERPT_LIMIT     = 200  # chars kept from RSS description


# ─────────────────────────────────────────────────────────────────────────────
# State helpers
# ─────────────────────────────────────────────────────────────────────────────

def _load_state() -> Set[str]:
    """Return the set of already-posted item URLs from the state file."""
    if not STATE_FILE.exists():
        _log.info("State file not found — starting fresh (first run)")
        return set()
    try:
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        posted = set(data.get("posted", []))
        _log.info(f"Loaded state: {len(posted)} previously-posted URL(s)")
        return posted
    except Exception as exc:
        _log.warning(f"State file unreadable ({exc}) — starting fresh")
        return set()


def _save_state(posted: Set[str]) -> None:
    """Persist the set of posted URLs back to the state file."""
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(
        {"posted": sorted(posted)},
        indent=2,
        ensure_ascii=False,
    )
    STATE_FILE.write_text(payload, encoding="utf-8")
    _log.info(f"State saved: {len(posted)} total posted URL(s)")


# ─────────────────────────────────────────────────────────────────────────────
# RSS parsing
# ─────────────────────────────────────────────────────────────────────────────

def _strip_html(text: str) -> str:
    """Very lightweight HTML tag stripper — no external deps needed."""
    import re
    return re.sub(r"<[^>]+>", "", text).strip()


def _parse_feeds() -> List[Dict]:
    """
    Walk sites/ and parse every feed.xml found.
    Returns a list of dicts: {title, link, desc, pub}.
    Items with no title or no link are silently skipped.
    """
    feed_files = sorted(SITES_DIR.rglob("feed.xml"))
    _log.info(f"Found {len(feed_files)} feed.xml file(s) under sites/")

    items: List[Dict] = []
    for feed_path in feed_files:
        try:
            tree = ET.parse(str(feed_path))
            root = tree.getroot()
            channel = root.find("channel")
            if channel is None:
                continue

            for item_el in channel.findall("item"):
                title = (item_el.findtext("title") or "").strip()
                link  = (item_el.findtext("link")  or "").strip()
                desc  = _strip_html(item_el.findtext("description") or "")
                pub   = (item_el.findtext("pubDate") or "").strip()

                if not title or not link:
                    continue

                items.append({
                    "title": title,
                    "link":  link,
                    "desc":  desc[:EXCERPT_LIMIT],
                    "pub":   pub,
                })
        except Exception as exc:
            _log.warning(f"Skipping {feed_path.name}: {exc}")

    _log.info(f"Total feed items across all feeds: {len(items)}")
    return items


# ─────────────────────────────────────────────────────────────────────────────
# Bluesky posting
# ─────────────────────────────────────────────────────────────────────────────

def _post_to_bluesky(
    handle:   str,
    password: str,
    title:    str,
    url:      str,
    excerpt:  str,
) -> bool:
    """
    Post a single item to Bluesky with an external link card embed.
    Returns True on success, False on any failure.
    Credentials are NEVER logged — handle is logged at INFO, password never.
    """
    try:
        from atproto import Client
        from atproto import models as atproto_models
    except ImportError:
        _log.error("atproto is not installed — run: pip install atproto")
        return False

    # Build post text — Bluesky limit is 300 graphemes
    parts = [title]
    if excerpt:
        parts.append(excerpt.rstrip())
    parts.append(url)
    post_text = "\n\n".join(parts)

    # Hard truncate to 298 chars + ellipsis if needed
    if len(post_text) > 300:
        post_text = post_text[:297] + "..."

    try:
        client = Client()
        client.login(handle, password)
        # Password used here — never stored in any variable that might leak to logs
    except Exception as exc:
        _log.error(f"Bluesky login failed for handle {handle!r}: {exc}")
        return False

    try:
        embed = atproto_models.AppBskyEmbedExternal.Main(
            external=atproto_models.AppBskyEmbedExternal.External(
                uri=url,
                title=title,
                description=excerpt or title,
            )
        )
        client.send_post(text=post_text, embed=embed)
        _log.info(f"Posted to Bluesky: {title!r}")
        return True
    except Exception as exc:
        _log.error(f"send_post failed for {url!r}: {exc}")
        return False


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    # ── Credentials from environment only — never hard-coded ──────────────────
    handle   = os.environ.get("BLUESKY_IDENTIFIER", "").strip()
    password = os.environ.get("BLUESKY_PASSWORD", "").strip()

    if not handle or not password:
        _log.error(
            "Missing credentials: BLUESKY_IDENTIFIER and BLUESKY_PASSWORD "
            "must be set as GitHub Secrets / environment variables."
        )
        sys.exit(1)

    # Log handle only — never log password or any part of it
    _log.info(f"Starting Bluesky RSS Poster — handle: {handle}")

    # ── Load state ─────────────────────────────────────────────────────────────
    posted = _load_state()

    # ── Parse feeds ────────────────────────────────────────────────────────────
    items = _parse_feeds()

    # ── Find new items (not yet posted) ────────────────────────────────────────
    new_items = [i for i in items if i["link"] not in posted]
    _log.info(f"New (unposted) items: {len(new_items)}")

    if not new_items:
        _log.info("Nothing new to post — exiting cleanly.")
        _save_state(posted)  # still write state so git diff is stable
        return

    # ── Post up to MAX_POSTS_PER_RUN items ─────────────────────────────────────
    posted_count = 0
    for item in new_items[:MAX_POSTS_PER_RUN]:
        ok = _post_to_bluesky(
            handle   = handle,
            password = password,
            title    = item["title"],
            url      = item["link"],
            excerpt  = item["desc"],
        )
        if ok:
            posted.add(item["link"])
            posted_count += 1

    # ── Persist state ──────────────────────────────────────────────────────────
    _save_state(posted)

    _log.info(
        f"Run complete — posted {posted_count} new item(s) "
        f"({len(new_items) - posted_count} skipped due to errors or per-run cap)."
    )


if __name__ == "__main__":
    main()
