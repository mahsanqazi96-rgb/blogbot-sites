"""
BlogBot — rss_generator.py
RSS 2.0 Feed Generation

Responsibilities:
  - Generate valid RSS 2.0 feed.xml per static blog site
  - Generate a combined hub feed for topicpulse.pages.dev
  - Filesystem-based: reads from sites/site-NNN/posts/
  - No external dependencies beyond the standard library
  - Max 20 items per site feed, max 50 items for the hub feed
  - Sorted newest-first
  - Enclosure elements for featured images
  - RFC 2822 pubDate formatting
"""

import sys
import html
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Dict, Optional, Any
from dataclasses import dataclass, field

# ── Path bootstrap ──────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent.parent.resolve()
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

SITES_DIR = BASE_DIR / "sites"
DATA_DIR  = BASE_DIR / "data"
LOGS_DIR  = BASE_DIR / "logs"

# ── Logging ─────────────────────────────────────────────────────────────────────
_log = logging.getLogger("rss_generator")
_log.setLevel(logging.INFO)
if not _log.handlers:
    _fh = logging.FileHandler(LOGS_DIR / "activity.log", encoding="utf-8")
    _fh.setFormatter(
        logging.Formatter("%(asctime)s [RSS] %(levelname)s %(message)s")
    )
    _log.addHandler(_fh)

# ── Constants ───────────────────────────────────────────────────────────────────
MAX_FEED_ITEMS    = 20
MAX_HUB_ITEMS     = 50
FEED_TTL          = 60          # minutes
RSS_DATE_FORMAT   = "%a, %d %b %Y %H:%M:%S +0000"   # RFC 2822

# Common MIME types for image enclosures
_IMAGE_MIME: Dict[str, str] = {
    ".jpg":  "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png":  "image/png",
    ".webp": "image/webp",
    ".gif":  "image/gif",
    ".svg":  "image/svg+xml",
}


# ── Helpers ─────────────────────────────────────────────────────────────────────

def _to_rfc2822(date_value: Any) -> str:
    """
    Convert various date representations to an RFC 2822 string.

    Accepts:
      - datetime object (naive treated as UTC)
      - ISO-8601 string  (e.g. "2026-04-23T10:00:00", "2026-04-23 10:00:00",
                          "2026-04-23T10:00:00+00:00", "2026-04-23")
      - int / float  (Unix timestamp)
      - Already-formatted RFC 2822 string (returned as-is after normalisation)

    Falls back to current UTC time on parse failure.
    """
    if isinstance(date_value, datetime):
        dt = date_value
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.strftime(RSS_DATE_FORMAT)

    if isinstance(date_value, (int, float)):
        return datetime.fromtimestamp(float(date_value), tz=timezone.utc).strftime(
            RSS_DATE_FORMAT
        )

    if isinstance(date_value, str):
        s = date_value.strip()
        # Already RFC 2822?
        try:
            from email.utils import parsedate_to_datetime
            dt = parsedate_to_datetime(s)
            return dt.astimezone(timezone.utc).strftime(RSS_DATE_FORMAT)
        except Exception:
            pass

        # ISO-8601 variants
        for fmt in (
            "%Y-%m-%dT%H:%M:%S%z",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%dT%H:%M",
            "%Y-%m-%d",
        ):
            try:
                dt = datetime.strptime(s, fmt)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt.strftime(RSS_DATE_FORMAT)
            except ValueError:
                continue

    _log.warning("Could not parse date %r — using current UTC time", date_value)
    return datetime.now(tz=timezone.utc).strftime(RSS_DATE_FORMAT)


def _image_mime(url: str) -> str:
    """Return a MIME type for the image URL; defaults to image/jpeg."""
    if not url:
        return "image/jpeg"
    ext = Path(url.split("?")[0]).suffix.lower()
    return _IMAGE_MIME.get(ext, "image/jpeg")


def _esc(text: str) -> str:
    """HTML-escape a string for safe embedding in XML CDATA text content."""
    return html.escape(str(text) if text is not None else "", quote=False)


def _cdata(text: str) -> str:
    """Wrap text in a CDATA section, escaping any ]]> sequences inside."""
    safe = str(text).replace("]]>", "]]]]><![CDATA[>")
    return f"<![CDATA[{safe}]]>"


def _sort_posts(posts: List[Dict]) -> List[Dict]:
    """
    Return posts sorted newest-first.  Falls back to list order if date
    parsing fails for a particular item.
    """
    def _sort_key(p: Dict):
        raw = p.get("published_at") or p.get("pub_date") or ""
        try:
            date_str = _to_rfc2822(raw)
            from email.utils import parsedate_to_datetime
            return parsedate_to_datetime(date_str)
        except Exception:
            return datetime.min.replace(tzinfo=timezone.utc)

    return sorted(posts, key=_sort_key, reverse=True)


# ── Core generator ───────────────────────────────────────────────────────────────

def generate_rss_feed(posts: List[Dict], site_config) -> str:
    """
    Generate a valid RSS 2.0 XML string for a single blog.

    Parameters
    ----------
    posts : list of dicts
        Each dict should contain:
          slug              str   — URL slug, e.g. "my-post"
          title             str
          meta_desc         str
          published_at      str   — ISO-8601 or RFC 2822 date
          featured_image_url str  — optional; empty string if absent
          niche             str   — optional metadata
    site_config : object
        Must expose:
          .blog_url  str  — e.g. "https://codewire.pages.dev"
          .title     str  — blog display title
          .language  str  — BCP 47 language tag, e.g. "en"
          .niche     str
          .meta_desc str

    Returns
    -------
    str
        Well-formed RSS 2.0 XML string, UTF-8 encoded in declaration.
    """
    if not posts:
        _log.warning("generate_rss_feed called with empty post list for %s",
                     getattr(site_config, "blog_url", "unknown"))

    blog_url  = (getattr(site_config, "blog_url",  "") or "").rstrip("/")
    title     = getattr(site_config, "title",     "Blog Feed")
    language  = getattr(site_config, "language",  "en")
    meta_desc = getattr(site_config, "meta_desc", "")

    sorted_posts = _sort_posts(posts)[:MAX_FEED_ITEMS]
    last_build   = (
        _to_rfc2822(sorted_posts[0].get("published_at") or sorted_posts[0].get("pub_date"))
        if sorted_posts
        else datetime.now(tz=timezone.utc).strftime(RSS_DATE_FORMAT)
    )

    # ── Channel header ──────────────────────────────────────────────────────────
    lines: List[str] = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom"'
        '     xmlns:content="http://purl.org/rss/1.0/modules/content/"'
        '     xmlns:dc="http://purl.org/dc/elements/1.1/">',
        "  <channel>",
        f"    <title>{_esc(title)}</title>",
        f"    <link>{_esc(blog_url)}/</link>",
        f"    <description>{_esc(meta_desc or title)}</description>",
        f"    <language>{_esc(language)}</language>",
        f"    <lastBuildDate>{last_build}</lastBuildDate>",
        f"    <ttl>{FEED_TTL}</ttl>",
        f'    <atom:link href="{_esc(blog_url)}/feed.xml"'
        f' rel="self" type="application/rss+xml"/>',
    ]

    # ── Items ───────────────────────────────────────────────────────────────────
    for post in sorted_posts:
        slug      = (post.get("slug") or "").strip("/")
        post_url  = f"{blog_url}/posts/{slug}.html"
        item_title    = post.get("title")    or slug
        item_desc     = post.get("meta_desc") or ""
        pub_date_raw  = post.get("published_at") or post.get("pub_date") or ""
        pub_date      = _to_rfc2822(pub_date_raw)
        image_url     = (post.get("featured_image_url") or "").strip()

        lines.append("    <item>")
        lines.append(f"      <title>{_esc(item_title)}</title>")
        lines.append(f"      <link>{_esc(post_url)}</link>")
        lines.append(f"      <description>{_cdata(item_desc)}</description>")
        lines.append(f"      <pubDate>{pub_date}</pubDate>")
        lines.append(f"      <guid isPermaLink=\"true\">{_esc(post_url)}</guid>")

        if image_url:
            mime = _image_mime(image_url)
            lines.append(
                f'      <enclosure url="{_esc(image_url)}"'
                f' type="{mime}" length="0"/>'
            )

        lines.append("    </item>")

    lines.append("  </channel>")
    lines.append("</rss>")

    return "\n".join(lines)


# ── File writer ─────────────────────────────────────────────────────────────────

def write_rss_feed(
    posts: List[Dict],
    site_config,
    output_dir: Path,
) -> Path:
    """
    Generate and write feed.xml to *output_dir*.

    Parameters
    ----------
    posts       : same as generate_rss_feed
    site_config : same as generate_rss_feed
    output_dir  : Path  — directory in which to write feed.xml

    Returns
    -------
    Path  — absolute path of the written feed.xml
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "feed.xml"

    blog_url = getattr(site_config, "blog_url", str(output_dir))
    _log.info("Generating RSS feed for %s → %s", blog_url, output_path)

    try:
        xml_str = generate_rss_feed(posts, site_config)
        output_path.write_text(xml_str, encoding="utf-8")
        _log.info("Wrote %d items to %s", min(len(posts), MAX_FEED_ITEMS), output_path)
        return output_path
    except Exception:
        _log.exception("Failed to write RSS feed to %s", output_path)
        raise


# ── Hub feed ────────────────────────────────────────────────────────────────────

def generate_hub_feed(
    all_posts: List[Dict],
    hub_url: str,
    output_path: Path,
) -> Path:
    """
    Generate a combined RSS 2.0 feed aggregating posts from the entire network.

    Intended for the hub site at topicpulse.pages.dev.

    Parameters
    ----------
    all_posts   : list of post dicts (same schema as generate_rss_feed).
                  Each dict may also include:
                    blog_url   str  — source blog URL (used for constructing item links)
                    blog_title str  — source blog display name (added to item description)
    hub_url     : str  — canonical URL of the hub, e.g. "https://topicpulse.pages.dev"
    output_path : Path — full destination path, e.g. .../sites/hub/feed.xml

    Returns
    -------
    Path  — absolute path of the written file
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    hub_url = hub_url.rstrip("/")
    _log.info("Generating hub feed (%d source posts) → %s", len(all_posts), output_path)

    sorted_posts = _sort_posts(all_posts)[:MAX_HUB_ITEMS]
    last_build = (
        _to_rfc2822(
            sorted_posts[0].get("published_at") or sorted_posts[0].get("pub_date")
        )
        if sorted_posts
        else datetime.now(tz=timezone.utc).strftime(RSS_DATE_FORMAT)
    )

    lines: List[str] = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom"'
        '     xmlns:content="http://purl.org/rss/1.0/modules/content/"'
        '     xmlns:dc="http://purl.org/dc/elements/1.1/">',
        "  <channel>",
        f"    <title>{_esc('TopicPulse — Latest from the Network')}</title>",
        f"    <link>{_esc(hub_url)}/</link>",
        "    <description>"
        + _esc(
            "Aggregated feed from the TopicPulse network — "
            "crypto, finance, health, tech and entertainment."
        )
        + "</description>",
        "    <language>en</language>",
        f"    <lastBuildDate>{last_build}</lastBuildDate>",
        f"    <ttl>{FEED_TTL}</ttl>",
        f'    <atom:link href="{_esc(hub_url)}/feed.xml"'
        f' rel="self" type="application/rss+xml"/>',
    ]

    for post in sorted_posts:
        slug        = (post.get("slug") or "").strip("/")
        source_url  = (post.get("blog_url") or hub_url).rstrip("/")
        post_url    = f"{source_url}/posts/{slug}.html"
        item_title  = post.get("title")    or slug
        item_desc   = post.get("meta_desc") or ""
        blog_name   = post.get("blog_title") or ""
        pub_date    = _to_rfc2822(
            post.get("published_at") or post.get("pub_date") or ""
        )
        image_url   = (post.get("featured_image_url") or "").strip()
        niche       = post.get("niche", "")

        # Prepend source blog name to description if available
        if blog_name:
            full_desc = f"[{blog_name}] {item_desc}".strip()
        else:
            full_desc = item_desc

        lines.append("    <item>")
        lines.append(f"      <title>{_esc(item_title)}</title>")
        lines.append(f"      <link>{_esc(post_url)}</link>")
        lines.append(f"      <description>{_cdata(full_desc)}</description>")
        lines.append(f"      <pubDate>{pub_date}</pubDate>")
        lines.append(f"      <guid isPermaLink=\"true\">{_esc(post_url)}</guid>")

        if niche:
            lines.append(f"      <dc:subject>{_esc(niche)}</dc:subject>")

        if image_url:
            mime = _image_mime(image_url)
            lines.append(
                f'      <enclosure url="{_esc(image_url)}"'
                f' type="{mime}" length="0"/>'
            )

        lines.append("    </item>")

    lines.append("  </channel>")
    lines.append("</rss>")

    xml_str = "\n".join(lines)

    try:
        output_path.write_text(xml_str, encoding="utf-8")
        _log.info(
            "Wrote hub feed with %d items to %s",
            len(sorted_posts),
            output_path,
        )
        return output_path
    except Exception:
        _log.exception("Failed to write hub feed to %s", output_path)
        raise


# ── Filesystem helpers (optional convenience) ────────────────────────────────────

def _scrape_posts_from_db(blog_id: str, limit: int = MAX_FEED_ITEMS) -> List[Dict]:
    """
    Pull post metadata from content_archive.db for a given blog_id.
    Returns an empty list if the DB does not exist or the query fails.
    """
    db_path = DATA_DIR / "content_archive.db"
    if not db_path.exists():
        _log.debug("content_archive.db not found at %s", db_path)
        return []
    try:
        con = sqlite3.connect(str(db_path))
        con.row_factory = sqlite3.Row
        cur = con.execute(
            """
            SELECT slug, title, meta_desc, published_at,
                   featured_image_url, niche, language
            FROM   content_archive
            WHERE  blog_id = ?
            ORDER  BY published_at DESC
            LIMIT  ?
            """,
            (blog_id, limit),
        )
        rows = [dict(r) for r in cur.fetchall()]
        con.close()
        return rows
    except Exception:
        _log.exception("DB query failed for blog_id=%s", blog_id)
        return []


def generate_feed_for_site(site_dir: Path, site_config) -> Optional[Path]:
    """
    Convenience wrapper: load posts from the database for *site_config.blog_id*
    and write feed.xml into *site_dir*.

    Falls back to an empty-but-valid feed if no posts are found.

    Returns the written Path or None on error.
    """
    blog_id = getattr(site_config, "blog_id", "") or ""
    posts   = _scrape_posts_from_db(blog_id, limit=MAX_FEED_ITEMS)

    if not posts:
        _log.warning(
            "No posts found for blog_id=%s — writing empty feed", blog_id
        )

    try:
        return write_rss_feed(posts, site_config, site_dir)
    except Exception:
        _log.exception(
            "generate_feed_for_site failed for blog_id=%s", blog_id
        )
        return None


# ── Self-test ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import textwrap

    # --- Minimal site_config stand-in ---
    @dataclass
    class _MockSiteConfig:
        blog_url:  str = "https://codewire.pages.dev"
        title:     str = "CodeWire — Daily Tech News"
        language:  str = "en"
        niche:     str = "tech"
        meta_desc: str = "The latest in software, hardware, and developer tools."

    sample_posts = [
        {
            "slug":               "top-10-python-tips-2026",
            "title":              "Top 10 Python Tips You Need in 2026",
            "meta_desc":          "Boost your Python productivity with these expert tips.",
            "published_at":       "2026-04-24T09:00:00",
            "featured_image_url": "https://cdn.example.com/python-tips.jpg",
            "niche":              "tech",
        },
        {
            "slug":               "what-is-webassembly",
            "title":              "What Is WebAssembly & Why It Matters",
            "meta_desc":          "WebAssembly is changing how we run code in the browser.",
            "published_at":       "2026-04-23T14:30:00",
            "featured_image_url": "",
            "niche":              "tech",
        },
        {
            "slug":               "rust-vs-go-2026",
            "title":              "Rust vs Go in 2026: Which Should You Learn?",
            "meta_desc":          "A practical comparison of Rust and Go for backend development.",
            "published_at":       "2026-04-22T08:00:00",
            "featured_image_url": "https://cdn.example.com/rust-go.png",
            "niche":              "tech",
        },
    ]

    cfg = _MockSiteConfig()

    # ── Test 1: generate_rss_feed ────────────────────────────────────────────
    print("=" * 60)
    print("TEST 1 -- generate_rss_feed()")
    print("=" * 60)
    xml = generate_rss_feed(sample_posts, cfg)
    print(xml[:500])
    print("...")
    print(f"\nTotal XML length: {len(xml)} chars, {xml.count('<item>')} items")

    # ── Test 2: write_rss_feed ───────────────────────────────────────────────
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        out = write_rss_feed(sample_posts, cfg, Path(tmp))
        print(f"\nTEST 2 -- write_rss_feed() -> {out}")
        print(f"File exists: {out.exists()}, size: {out.stat().st_size} bytes")

    # ── Test 3: generate_hub_feed ────────────────────────────────────────────
    hub_posts = [
        dict(
            p,
            blog_url="https://codewire.pages.dev",
            blog_title="CodeWire",
        )
        for p in sample_posts
    ]
    hub_posts += [
        {
            "slug":               "bitcoin-hits-200k",
            "title":              "Bitcoin Hits $200k for the First Time",
            "meta_desc":          "BTC breaks all-time record as institutional demand surges.",
            "published_at":       "2026-04-24T11:00:00",
            "featured_image_url": "https://cdn.example.com/btc.jpg",
            "niche":              "crypto",
            "blog_url":           "https://bitsignal.pages.dev",
            "blog_title":         "BitSignal",
        }
    ]

    with tempfile.TemporaryDirectory() as tmp:
        hub_out = generate_hub_feed(
            hub_posts,
            hub_url="https://topicpulse.pages.dev",
            output_path=Path(tmp) / "feed.xml",
        )
        print(f"\nTEST 3 -- generate_hub_feed() -> {hub_out}")
        print(f"File exists: {hub_out.exists()}, size: {hub_out.stat().st_size} bytes")
        content = hub_out.read_text(encoding="utf-8")
        print("\nHub feed first 500 chars:")
        print(content[:500])
