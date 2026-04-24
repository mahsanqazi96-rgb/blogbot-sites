"""
BlogBot — competitor_intelligence.py
Phase 2+ Deferred Feature

Weekly competitor monitoring for top 10 sites per niche:
- New blog / new competitor detection
- Content gap analysis (topics they cover that we don't)
- Competitive threat scoring
- Keyword and ranking tracking
- Auto-response: queue gap-filling content immediately

Uses only free, public signals:
- Bing/Yandex SERP scraping (no API key required)
- RSS feed monitoring for new competitor posts
- Sitemap.xml diffing (public sitemaps)

Results stored in system.db (competitor_sites, competitor_posts, content_gaps).
Weekly report sent via alert_system.
"""

import sys
import re
import json
import time
import logging
import hashlib
import threading
import urllib.request
import urllib.error
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, List, Any
from dataclasses import dataclass, field
from xml.etree import ElementTree as ET

# ── feedparser — reliable RSS/Atom parser ────────────────────────────────────────
try:
    import feedparser as _feedparser
    _FEEDPARSER_OK = True
except ImportError:
    _FEEDPARSER_OK = False

# ── Path bootstrap ────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent.parent.resolve()
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

LOGS_DIR = BASE_DIR / "logs"

# ── Logging ───────────────────────────────────────────────────────────────────
_log = logging.getLogger("competitor_intelligence")
_log.setLevel(logging.INFO)
if not _log.handlers:
    _fh = logging.FileHandler(LOGS_DIR / "activity.log", encoding="utf-8")
    _fh.setFormatter(logging.Formatter("%(asctime)s [CI] %(levelname)s %(message)s"))
    _log.addHandler(_fh)

# ── Default competitor sets per niche ─────────────────────────────────────────
DEFAULT_COMPETITORS: Dict[str, List[str]] = {
    "finance":       [],
    "crypto":        [],
    "health":        [],
    "tech":          [],
    "entertainment": [],
}

# Scoring thresholds
THREAT_SCORE_HIGH    = 70    # Immediate gap-fill response
THREAT_SCORE_MEDIUM  = 40    # Queue content within 48h
THREAT_SCORE_LOW     = 0     # Monitor only


@dataclass
class CompetitorSite:
    url: str
    niche: str
    rss_url: Optional[str] = None
    sitemap_url: Optional[str] = None
    threat_score: int = 0
    last_checked: Optional[str] = None
    post_count_last: int = 0
    active: bool = True


@dataclass
class ContentGap:
    topic: str
    niche: str
    keywords: List[str]
    found_on: str           # competitor URL that covers this topic
    gap_score: int = 50     # 0-100, higher = bigger opportunity
    queued: bool = False
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


# ── DB ────────────────────────────────────────────────────────────────────────
def ensure_ci_tables():
    try:
        from modules.database_manager import execute_raw
        execute_raw("system", """
            CREATE TABLE IF NOT EXISTS competitor_sites (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                url             TEXT UNIQUE NOT NULL,
                niche           TEXT,
                rss_url         TEXT,
                sitemap_url     TEXT,
                threat_score    INTEGER DEFAULT 0,
                last_checked    TEXT,
                post_count_last INTEGER DEFAULT 0,
                active          INTEGER DEFAULT 1,
                added_at        TEXT
            )
        """)
        execute_raw("system", """
            CREATE TABLE IF NOT EXISTS competitor_posts (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                site_url    TEXT,
                post_url    TEXT UNIQUE,
                title       TEXT,
                niche       TEXT,
                discovered  TEXT,
                keywords_json TEXT
            )
        """)
        execute_raw("system", """
            CREATE TABLE IF NOT EXISTS content_gaps (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                topic       TEXT,
                niche       TEXT,
                keywords_json TEXT,
                found_on    TEXT,
                gap_score   INTEGER DEFAULT 50,
                queued      INTEGER DEFAULT 0,
                created_at  TEXT,
                UNIQUE(topic, niche)
            )
        """)
    except Exception as e:
        _log.error(f"ensure_ci_tables: {e}")


# ── Competitor Management ─────────────────────────────────────────────────────
def add_competitor(url: str, niche: str) -> bool:
    """Register a competitor site for monitoring."""
    ensure_ci_tables()
    url = url.strip().rstrip("/")
    try:
        from modules.database_manager import execute
        rss_url     = _discover_rss(url)
        sitemap_url = _discover_sitemap(url)
        execute("system",
            """INSERT OR IGNORE INTO competitor_sites
               (url, niche, rss_url, sitemap_url, active, added_at)
               VALUES (?, ?, ?, ?, 1, ?)""",
            (url, niche, rss_url, sitemap_url,
             datetime.now(timezone.utc).isoformat()))
        _log.info(f"Competitor added: {url} ({niche})")
        return True
    except Exception as e:
        _log.error(f"add_competitor: {e}")
        return False


def get_competitors(niche: Optional[str] = None) -> List[Dict]:
    try:
        from modules.database_manager import fetch_all
        where  = "WHERE active=1"
        params: tuple = ()
        if niche:
            where  += " AND niche=?"
            params  = (niche,)
        rows = fetch_all("system",
            f"SELECT * FROM competitor_sites {where} ORDER BY threat_score DESC",
            params)
        return [dict(r) for r in rows]
    except Exception as e:  # noqa: BLE001 — competitor_sites table may not exist yet
        _log.debug(f"get_competitors(niche={niche}): {e}")
        return []


# ── Monitoring ────────────────────────────────────────────────────────────────
def monitor_all_competitors() -> Dict:
    """
    Full monitoring run. Called weekly by scheduler.
    1. Fetch each competitor's RSS/sitemap for new posts
    2. Extract topics/keywords from new posts
    3. Compare against our own content_archive
    4. Record gaps
    5. Auto-queue gap-filling content for high-score gaps
    6. Update threat scores
    7. Send weekly report
    """
    ensure_ci_tables()
    competitors = get_competitors()
    if not competitors:
        _log.info("No competitors registered — skipping monitor run")
        return {"monitored": 0, "new_posts": 0, "gaps_found": 0}

    total_new_posts = 0
    total_gaps      = 0

    for comp in competitors:
        url   = comp["url"]
        niche = comp["niche"]
        _log.info(f"Monitoring competitor: {url}")

        new_posts = _fetch_new_posts(comp)
        total_new_posts += len(new_posts)

        for post in new_posts:
            _store_competitor_post(url, niche, post)
            gaps = _find_gaps(post, niche)
            for gap in gaps:
                _store_gap(gap)
                total_gaps += 1

        score = _calculate_threat_score(comp, len(new_posts))
        _update_threat_score(url, score, len(new_posts))

        # Auto-respond to high-threat competitors
        if score >= THREAT_SCORE_HIGH:
            _queue_gap_filling_content(niche, limit=5)
            _log.warning(f"HIGH THREAT competitor: {url} (score={score}) — queued gap-fill content")

        time.sleep(2)   # be polite between requests

    _send_weekly_report(competitors, total_new_posts, total_gaps)

    return {
        "monitored":   len(competitors),
        "new_posts":   total_new_posts,
        "gaps_found":  total_gaps,
    }


def _fetch_new_posts(comp: Dict) -> List[Dict]:
    """Return list of new posts from competitor's RSS or sitemap."""
    posts = []

    # Try RSS first
    if comp.get("rss_url"):
        try:
            posts = _parse_rss(comp["rss_url"])
        except Exception as e:
            _log.debug(f"RSS failed for {comp['url']}: {e}")

    # Fall back to sitemap
    if not posts and comp.get("sitemap_url"):
        try:
            posts = _parse_sitemap_new(comp["sitemap_url"], comp["url"])
        except Exception as e:
            _log.debug(f"Sitemap failed for {comp['url']}: {e}")

    # Filter posts we haven't seen before
    new_posts = []
    try:
        from modules.database_manager import fetch_one
        for p in posts:
            exists = fetch_one("system",
                "SELECT id FROM competitor_posts WHERE post_url=?",
                (p.get("url", ""),))
            if not exists:
                new_posts.append(p)
    except Exception as e:  # noqa: BLE001 — DB lookup failure → assume all new
        _log.debug(f"_fetch_new_posts dedup: {e}")
        new_posts = posts

    return new_posts[:20]   # max 20 new posts per competitor per run


def _parse_feed_with_feedparser(url: str, timeout: int = 15) -> List[Dict]:
    """
    Parse an RSS/Atom feed with feedparser. Handles RSS 0.9x/1.0/2.0 and Atom.
    Makes a single HTTP GET to `url`. No credentials needed.
    Returns [{title, url, published, summary}, ...] or [] on error.
    """
    if not _FEEDPARSER_OK:
        _log.debug("feedparser not installed — using stdlib XML parser fallback")
        return []
    try:
        import socket
        old = socket.getdefaulttimeout()
        socket.setdefaulttimeout(timeout)
        try:
            feed = _feedparser.parse(url)
        finally:
            socket.setdefaulttimeout(old)
        if feed.bozo and not feed.entries:
            _log.warning(f"feedparser: malformed feed {url}: {feed.bozo_exception}")
            return []
        entries = []
        for entry in feed.entries[:50]:
            title = getattr(entry, "title", "").strip()
            link  = getattr(entry, "link",  "").strip()
            if not title or not link:
                continue
            published = getattr(entry, "published", None) or getattr(entry, "updated", None) or ""
            summary   = re.sub(r"<[^>]+>", " ",
                               getattr(entry, "summary", getattr(entry, "description", ""))).strip()[:300]
            entries.append({"title": title, "url": link, "published": published, "summary": summary})
        _log.debug(f"feedparser: {len(entries)} entries from {url}")
        return entries
    except Exception as e:
        _log.warning(f"feedparser error for {url}: {e}")
        return []


def _parse_rss(rss_url: str) -> List[Dict]:
    """Parse RSS feed and return list of {url, title, keywords} dicts."""
    # Try feedparser first (more reliable), fall back to manual XML parsing
    fp_entries = _parse_feed_with_feedparser(rss_url)
    if fp_entries:
        posts = []
        for e in fp_entries:
            text = e.get("title", "") + " " + e.get("summary", "")
            keywords = _extract_keywords(text)
            posts.append({"url": e["url"], "title": e["title"], "keywords": keywords})
        return posts

    # Fallback: manual urllib + ElementTree XML parsing
    headers = {"User-Agent": "Mozilla/5.0 (compatible; BlogBot/1.0)"}
    req = urllib.request.Request(rss_url, headers=headers)
    resp = urllib.request.urlopen(req, timeout=10)
    xml  = resp.read()
    root = ET.fromstring(xml)
    ns   = {"atom": "http://www.w3.org/2005/Atom"}
    posts = []

    # RSS 2.0
    for item in root.findall(".//item"):
        title = item.findtext("title", "")
        link  = item.findtext("link", "")
        desc  = item.findtext("description", "")
        if title and link:
            keywords = _extract_keywords(title + " " + desc)
            posts.append({"url": link, "title": title, "keywords": keywords})

    # Atom
    if not posts:
        for entry in root.findall(".//atom:entry", ns):
            title = entry.findtext("atom:title", "", ns)
            link_el = entry.find("atom:link", ns)
            link  = link_el.get("href", "") if link_el is not None else ""
            if title and link:
                keywords = _extract_keywords(title)
                posts.append({"url": link, "title": title, "keywords": keywords})

    return posts


def _parse_sitemap_new(sitemap_url: str, base_url: str) -> List[Dict]:
    """Parse sitemap.xml and return URLs that match post patterns."""
    headers = {"User-Agent": "Mozilla/5.0 (compatible; BlogBot/1.0)"}
    req  = urllib.request.Request(sitemap_url, headers=headers)
    resp = urllib.request.urlopen(req, timeout=10)
    xml  = resp.read()
    root = ET.fromstring(xml)
    ns   = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    posts = []
    for url_el in root.findall("sm:url", ns):
        loc = url_el.findtext("sm:loc", "", ns)
        if loc and _looks_like_post(loc, base_url):
            slug    = loc.rstrip("/").split("/")[-1]
            title   = slug.replace("-", " ").replace("_", " ").title()
            keywords = _extract_keywords(title)
            posts.append({"url": loc, "title": title, "keywords": keywords})
    return posts


def _looks_like_post(url: str, base_url: str) -> bool:
    """Heuristic: is this URL likely a blog post (not a category/tag/page)?"""
    path = url.replace(base_url, "").strip("/")
    # Reject short paths (homepage, categories)
    if len(path) < 10:
        return False
    # Reject obvious non-post paths
    skip_patterns = ["category", "tag", "author", "page", "search", "wp-"]
    return not any(p in path for p in skip_patterns)


def _discover_rss(base_url: str) -> Optional[str]:
    """Try common RSS paths on a domain."""
    candidates = [
        f"{base_url}/feed",
        f"{base_url}/rss",
        f"{base_url}/feed.xml",
        f"{base_url}/atom.xml",
        f"{base_url}/rss.xml",
    ]
    for url in candidates:
        try:
            req  = urllib.request.Request(
                url, headers={"User-Agent": "Mozilla/5.0 (compatible; BlogBot/1.0)"}
            )
            resp = urllib.request.urlopen(req, timeout=5)
            ct   = resp.headers.get("Content-Type", "")
            if "xml" in ct or "rss" in ct or "atom" in ct:
                return url
        except Exception as e:  # noqa: BLE001 — RSS path probe; try next
            _log.debug(f"_discover_rss probe {url}: {e}")
    return None


def _discover_sitemap(base_url: str) -> Optional[str]:
    """Try common sitemap paths on a domain."""
    candidates = [
        f"{base_url}/sitemap.xml",
        f"{base_url}/sitemap_index.xml",
        f"{base_url}/post-sitemap.xml",
    ]
    for url in candidates:
        try:
            req  = urllib.request.Request(
                url, headers={"User-Agent": "Mozilla/5.0 (compatible; BlogBot/1.0)"}
            )
            resp = urllib.request.urlopen(req, timeout=5)
            if resp.status == 200:
                return url
        except Exception as e:  # noqa: BLE001 — sitemap path probe; try next
            _log.debug(f"_discover_sitemap probe {url}: {e}")
    return None


def _extract_keywords(text: str) -> List[str]:
    """Extract potential keywords from title/description text."""
    # Remove HTML tags
    text = re.sub(r"<[^>]+>", " ", text)
    # Tokenise and deduplicate (2+ word tokens only)
    words = re.findall(r"\b[a-zA-Z]{3,}\b", text.lower())
    stop  = {
        "the", "and", "for", "with", "this", "that", "from", "have",
        "are", "was", "been", "will", "what", "how", "why", "all",
        "can", "not", "but", "its", "you", "your", "our",
    }
    keywords = [w for w in words if w not in stop]
    # Return unique, max 10
    seen = set()
    result = []
    for k in keywords:
        if k not in seen:
            seen.add(k)
            result.append(k)
        if len(result) >= 10:
            break
    return result


def _find_gaps(post: Dict, niche: str) -> List[ContentGap]:
    """
    Check if this competitor post topic is already covered in our content archive.
    Returns ContentGap entries for uncovered topics.
    """
    gaps = []
    title    = post.get("title", "")
    keywords = post.get("keywords", [])
    if not title:
        return gaps

    try:
        from modules.database_manager import fetch_one
        # Check if we have a post with similar keywords
        covered = False
        for kw in keywords[:3]:
            row = fetch_one("content_archive",
                "SELECT id FROM posts WHERE title LIKE ? AND niche=?",
                (f"%{kw}%", niche))
            if row:
                covered = True
                break

        if not covered:
            score = min(100, 50 + len(keywords) * 5)
            gaps.append(ContentGap(
                topic=title,
                niche=niche,
                keywords=keywords,
                found_on=post.get("url", ""),
                gap_score=score,
            ))
    except Exception as e:  # noqa: BLE001 — content_archive may not exist yet
        _log.debug(f"_find_gaps lookup: {e}")

    return gaps


def _store_competitor_post(site_url: str, niche: str, post: Dict):
    try:
        from modules.database_manager import execute
        execute("system",
            "INSERT OR IGNORE INTO competitor_posts "
            "(site_url, post_url, title, niche, discovered, keywords_json) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (site_url, post.get("url", ""), post.get("title", ""),
             niche, datetime.now(timezone.utc).isoformat(),
             json.dumps(post.get("keywords", []))))
    except Exception as e:  # noqa: BLE001 — competitor_posts may not exist yet
        _log.debug(f"_store_competitor_post({site_url}): {e}")


def _store_gap(gap: ContentGap):
    try:
        from modules.database_manager import execute
        execute("system",
            "INSERT OR IGNORE INTO content_gaps "
            "(topic, niche, keywords_json, found_on, gap_score, queued, created_at) "
            "VALUES (?, ?, ?, ?, ?, 0, ?)",
            (gap.topic, gap.niche, json.dumps(gap.keywords),
             gap.found_on, gap.gap_score,
             datetime.now(timezone.utc).isoformat()))
    except Exception as e:  # noqa: BLE001 — content_gaps may not exist yet
        _log.debug(f"_store_gap({gap.topic[:40]}): {e}")


def _calculate_threat_score(comp: Dict, new_post_count: int) -> int:
    """
    Simple heuristic threat score (0-100).
    High post velocity = higher threat.
    """
    base = min(60, new_post_count * 5)    # up to 60 points from velocity
    # Previous score carries 40%
    prev = comp.get("threat_score", 0) or 0
    return int(base * 0.6 + prev * 0.4)


def _update_threat_score(url: str, score: int, new_posts: int):
    try:
        from modules.database_manager import execute
        execute("system",
            "UPDATE competitor_sites SET threat_score=?, last_checked=?, "
            "post_count_last=? WHERE url=?",
            (score, datetime.now(timezone.utc).isoformat(), new_posts, url))
    except Exception as e:  # noqa: BLE001 — competitor_sites may not exist yet
        _log.debug(f"_update_threat_score({url}): {e}")


def _queue_gap_filling_content(niche: str, limit: int = 5):
    """
    Take the top unqueued content gaps and add generate_content tasks to task_queue.
    """
    try:
        from modules.database_manager import fetch_all, execute
        gaps = fetch_all("system",
            "SELECT * FROM content_gaps WHERE niche=? AND queued=0 "
            "ORDER BY gap_score DESC LIMIT ?",
            (niche, limit))

        for gap in gaps:
            payload = json.dumps({
                "niche":    niche,
                "language": "en",
                "topic":    gap["topic"],
                "keywords": json.loads(gap["keywords_json"] or "[]"),
                "reason":   "competitor_gap",
                "priority": 2,
            })
            execute("system",
                "INSERT INTO task_queue (task_type, payload, status) VALUES (?, ?, ?)",
                ("generate_content", payload, "pending"))
            execute("system",
                "UPDATE content_gaps SET queued=1 WHERE id=?",
                (gap["id"],))
            _log.info(f"Gap-fill queued: '{gap['topic']}' ({niche})")
    except Exception as e:
        _log.error(f"_queue_gap_filling_content: {e}")


def _send_weekly_report(competitors: List[Dict], new_posts: int, gaps: int):
    """Send weekly competitor intelligence summary via alert_system."""
    try:
        from modules.alert_system import tier1
        high_threat = [c for c in competitors if (c.get("threat_score") or 0) >= THREAT_SCORE_HIGH]
        msg = (
            f"Weekly Competitor Report\n"
            f"Competitors monitored: {len(competitors)}\n"
            f"New competitor posts: {new_posts}\n"
            f"Content gaps found: {gaps}\n"
            f"High-threat competitors: {len(high_threat)}"
        )
        if high_threat:
            msg += "\nHIGH THREAT: " + ", ".join(c["url"] for c in high_threat)
        tier1(msg)
    except Exception as e:  # noqa: BLE001 — alert_system may not be running
        _log.debug(f"_send_weekly_report: {e}")


# ── Gap report ────────────────────────────────────────────────────────────────
def get_content_gaps(
    niche: Optional[str] = None,
    queued: Optional[bool] = None,
    limit: int = 50,
) -> List[Dict]:
    """Return content gaps from DB."""
    try:
        from modules.database_manager import fetch_all
        where  = "WHERE 1=1"
        params: list = []
        if niche:
            where  += " AND niche=?"
            params.append(niche)
        if queued is not None:
            where  += " AND queued=?"
            params.append(1 if queued else 0)
        rows = fetch_all("system",
            f"SELECT * FROM content_gaps {where} ORDER BY gap_score DESC LIMIT ?",
            tuple(params) + (limit,))
        return [dict(r) for r in rows]
    except Exception as e:  # noqa: BLE001 — content_gaps may not exist yet
        _log.debug(f"get_content_gaps: {e}")
        return []


def get_threat_report() -> List[Dict]:
    """Return all competitors sorted by threat score descending."""
    return sorted(get_competitors(), key=lambda x: x.get("threat_score", 0), reverse=True)


# ── Self-Test ─────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("competitor_intelligence self-test...")
    ensure_ci_tables()

    # Add a fake competitor
    ok = add_competitor("https://example-crypto-blog.com", "crypto")
    print(f"  add_competitor: {'OK' if ok else 'FAIL'}")

    competitors = get_competitors("crypto")
    print(f"  get_competitors: {len(competitors)} ({'OK' if len(competitors) >= 1 else 'FAIL'})")

    # Simulate gap detection
    fake_post = {
        "url":      "https://example-crypto-blog.com/bitcoin-etf-guide",
        "title":    "Complete Bitcoin ETF Investment Guide 2026",
        "keywords": ["bitcoin", "etf", "investment", "guide"],
    }
    _store_competitor_post("https://example-crypto-blog.com", "crypto", fake_post)

    gap = ContentGap(
        topic="Complete Bitcoin ETF Investment Guide",
        niche="crypto",
        keywords=["bitcoin", "etf"],
        found_on="https://example-crypto-blog.com/bitcoin-etf-guide",
        gap_score=75,
    )
    _store_gap(gap)

    gaps = get_content_gaps(niche="crypto")
    print(f"  content_gaps stored: {len(gaps)} ({'OK' if len(gaps) >= 1 else 'FAIL'})")
    print(f"  gap_score: {gaps[0]['gap_score']} ({'OK' if gaps[0]['gap_score'] >= 70 else 'FAIL'})")

    print("Self-test complete.")
