"""
BlogBot — bot_loop.py
Autonomous Publish Loop

Runs the full pipeline end-to-end for every active Cloudflare blog:
  Topic → ContentBrief → generate() → QC → HTML → disk → GitHub → Cloudflare

Usage:
  python bot_loop.py                    # run forever (default 30-min cycles)
  python bot_loop.py --once             # run one cycle and exit
  python bot_loop.py --blog site-001    # publish one specific blog and exit
  python bot_loop.py --dry-run          # generate + QC only, no write/push

Called by scheduler.py every cycle (or run standalone).
"""

import sys
import os
import re
import glob
import time
import json
import atexit
import logging
import random
import argparse
from pathlib import Path
from datetime import datetime, timezone, timedelta
from urllib.parse import urlparse as _urlparse
from dataclasses import dataclass, field
from typing import Optional, List, Dict

# ── Path bootstrap ──────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent.resolve()
SITES_DIR = BASE_DIR / "sites"
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

# ── Bot status files (read by dashboard) ────────────────────────────────────────
_PID_FILE    = BASE_DIR / "data" / "bot.pid"
_STATUS_FILE = BASE_DIR / "data" / "bot_status.json"

def _write_pid() -> None:
    try:
        _PID_FILE.parent.mkdir(exist_ok=True)
        _PID_FILE.write_text(str(os.getpid()), encoding="utf-8")
    except Exception:
        pass

def _remove_pid() -> None:
    try:
        _PID_FILE.unlink(missing_ok=True)
    except Exception:
        pass

def _write_status(state: str, cycle_num: int = 0, summary: str = "",
                  current_blog: str = "") -> None:
    """Write JSON status file so the dashboard can show bot progress."""
    try:
        _STATUS_FILE.parent.mkdir(exist_ok=True)
        _STATUS_FILE.write_text(
            json.dumps({
                "state":        state,          # running | idle | stopped
                "pid":          os.getpid(),
                "cycle_num":    cycle_num,
                "summary":      summary,
                "current_blog": current_blog,
                "updated_at":   datetime.now(timezone.utc).isoformat(),
            }, indent=2),
            encoding="utf-8",
        )
    except Exception:
        pass

# Force UTF-8 on Windows
if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# ── Logging ─────────────────────────────────────────────────────────────────────
_log = logging.getLogger("bot_loop")
_log.setLevel(logging.INFO)
if not _log.handlers:
    _fh = logging.FileHandler(BASE_DIR / "logs" / "activity.log", encoding="utf-8")
    _fh.setFormatter(logging.Formatter("%(asctime)s [LOOP] %(levelname)s %(message)s"))
    _log.addHandler(_fh)
    _ch = logging.StreamHandler(sys.stdout)
    _ch.setFormatter(logging.Formatter("%(asctime)s [LOOP] %(message)s"))
    _log.addHandler(_ch)


# ── Constants ───────────────────────────────────────────────────────────────────
PUBLISH_GAP_HOURS   = 4     # Minimum hours between posts on the same blog
MAX_BLOGS_PER_CYCLE = 10    # Blogs processed per cycle
CYCLE_INTERVAL_MINS = 30    # Sleep between cycles (minutes)
MAX_QC_RETRIES      = 2     # Re-generate if QC blocks (different angle)
MIN_CYCLE_SLEEP_SEC = 60    # Never sleep less than this between cycles


# ── Topic pools (fallback when trend_detector has nothing) ──────────────────────
# {year} and {month} are substituted at runtime to keep content timely.

_Y = datetime.now().year
_M = datetime.now().strftime("%B")

NICHE_TOPICS: Dict[str, List[str]] = {
    "crypto": [
        f"Bitcoin price prediction {_M} {_Y}: what analysts expect",
        f"Best crypto exchanges for beginners in {_Y}",
        "How to buy Bitcoin in Pakistan: step-by-step guide",
        "Ethereum vs Bitcoin: which should you invest in?",
        f"Top 5 altcoins to watch in {_M} {_Y}",
        "What is DeFi and how does it work? Beginner guide",
        "How to store crypto safely: hardware wallet guide",
        f"Crypto market analysis: weekly recap {_M} {_Y}",
        "Bitcoin halving explained: what it means for price",
        "Is cryptocurrency halal? Islamic finance perspective",
        "How to avoid crypto scams: red flags and warning signs",
        "What is staking and how to earn passive income with crypto",
        f"Ethereum price analysis {_M} {_Y}: bull or bear?",
        "How blockchain technology works: simple explanation",
        "Best crypto wallets compared: hot vs cold storage",
        "How to read crypto charts for beginners",
        "Top crypto mistakes beginners make and how to avoid them",
        "What is a crypto bull run and when is the next one?",
        "How to pay taxes on crypto gains: complete guide",
        "NFTs explained: are they still worth investing in?",
        f"Solana vs Ethereum: which is better in {_Y}?",
        "What is Bitcoin dominance and why does it matter?",
        "How to dollar cost average into crypto",
        "Crypto FOMO: how emotions destroy your portfolio",
        "Best strategies for crypto bear market survival",
        f"Cardano ADA price forecast {_M} {_Y}",
        "What is a crypto airdrop and how to qualify",
        "Binance vs Coinbase: which exchange to choose",
        "How to earn from crypto without trading",
        "Ripple XRP lawsuit: what investors need to know",
    ],
    "finance": [
        f"Best investment options in Pakistan for {_Y}",
        "How to start investing with 10,000 PKR",
        f"Pakistan stock market PSX analysis {_M} {_Y}",
        "How to build an emergency fund from scratch",
        "Best savings accounts with highest interest rates",
        "How inflation affects your savings and what to do",
        "Passive income ideas that actually work",
        "How to get out of debt: practical step-by-step plan",
        f"Gold price forecast {_M} {_Y}: buy or sell?",
        "Mutual funds vs stocks: which is better for beginners",
        "How to create a personal budget that sticks",
        f"Dollar to PKR forecast {_M} {_Y}",
        "What is compound interest and why it matters",
        "Best apps for tracking personal finances",
        "How to invest in US stocks from Pakistan",
        "Real estate vs stocks: which gives better returns",
        "How to negotiate a higher salary: proven tactics",
        "What is the 50/30/20 budget rule and how to use it",
        "How to retire early: FIRE strategy explained",
        "Best ways to send money internationally from Pakistan",
        "Fixed vs variable expenses: how to cut costs",
        "What is a P/E ratio and how to use it when investing",
        "How to build wealth on a low income",
        "National Savings Pakistan: best schemes ranked",
        "How to protect your money from currency devaluation",
        f"Inflation rate Pakistan {_Y}: impact on your wallet",
        "Best freelancing platforms to earn dollars in Pakistan",
        "How to open a bank account in Pakistan online",
        "What is Roshan Digital Account and how to open one",
        "Insurance in Pakistan: what you actually need",
    ],
    "health": [
        f"Best weight loss diet plan for {_Y}: what works",
        "How to lose 10kg in 3 months without crash dieting",
        "Intermittent fasting 16:8: complete beginner guide",
        "Best exercises to do at home without equipment",
        "How much water should you drink daily? The truth",
        "Pakistani foods that are secretly unhealthy",
        "Best healthy Pakistani meals under 500 calories",
        "How to improve sleep quality: 10 science-backed tips",
        "Signs of vitamin D deficiency and how to fix it",
        "Best vitamins and supplements for daily health",
        "How stress affects your body and how to manage it",
        "Sugar addiction: signs you eat too much sugar",
        "How to build muscle at home: beginner workout plan",
        "PCOS diet plan: what to eat and avoid",
        "Best exercises for back pain relief",
        f"Ramadan health tips: eat healthy during fasting {_Y}",
        "How to lower blood pressure naturally",
        "Diabetes prevention: lifestyle changes that work",
        "Best mental health apps for anxiety and depression",
        "How to boost your immune system naturally",
        "Protein intake guide: how much do you really need?",
        "Benefits of walking 30 minutes daily",
        "How to fix bad posture: simple daily exercises",
        "Best foods to eat for glowing skin",
        "How to quit sugar in 30 days: step-by-step plan",
        "Thyroid problems: signs, symptoms, and treatment",
        "Best yoga poses for stress relief and flexibility",
        "How to improve digestion naturally",
        "High blood pressure foods to avoid completely",
        "Signs you need to see a doctor immediately",
        "Best diet plan for diabetics in Pakistan",
        f"Summer health tips for {_Y}: staying cool and safe",
        "How to lose belly fat: what actually works",
        "Benefits of green tea: what science actually says",
        "How to deal with depression without medication",
    ],
    "tech": [
        f"Best smartphones under 50,000 PKR in {_Y}",
        f"Top 10 tech gadgets worth buying in {_M} {_Y}",
        "How to speed up your slow Android phone",
        "Best free AI tools that replace paid software",
        f"iPhone vs Samsung: which is better value in {_Y}?",
        f"Best laptops for students in Pakistan {_Y}",
        "How to protect your phone from hackers",
        "Best VPN services: which actually keeps you private",
        "How to earn online in Pakistan: 10 proven methods",
        "ChatGPT vs Google Gemini: which AI is smarter?",
        f"Best budget Android phones under 30,000 PKR {_Y}",
        "How to free up storage space on your phone",
        "5G in Pakistan: which cities have it and what to expect",
        "Best free video editing apps for Android",
        "How to set up parental controls on any device",
        f"Best gaming phones in Pakistan {_Y}: ranked",
        "How to recover deleted photos from your phone",
        "Best broadband internet plans in Pakistan compared",
        "How to make money with freelancing as a student",
        "WhatsApp tips and tricks most people don't know",
        f"Best smart TVs under 100,000 PKR in {_Y}",
        "How to spot a fake online shop in Pakistan",
        "Best antivirus for Windows: free vs paid compared",
        "How to use AI to write better in 2024",
        "YouTube monetization: how much do Pakistani creators earn",
        "How to build a PC in Pakistan on a budget",
        "Best earbuds under 5,000 PKR: honest reviews",
        "Google Pixel vs iPhone: camera comparison",
        "How to set up a home WiFi network properly",
        "Best productivity apps for students and freelancers",
        f"Top AI image generators compared in {_Y}",
        "How to increase internet speed at home: 10 tips",
        "Best apps for online earning in Pakistan",
        "How to use Google Maps offline: complete guide",
        "Cybersecurity basics everyone should know",
    ],
    "entertainment": [
        f"Best Pakistani dramas to watch in {_M} {_Y}",
        f"Top trending songs on YouTube Pakistan {_M} {_Y}",
        "Best Bollywood movies to stream right now",
        f"Most popular TikTok trends this week {_M} {_Y}",
        "Best Netflix shows everyone is watching",
        "Pakistani cricketers and their net worth revealed",
        f"PSL {_Y} highlights: best moments of the season",
        "Most followed Pakistani celebrities on Instagram",
        f"Top viral moments from social media {_M} {_Y}",
        "Best comedy shows on YouTube Pakistan right now",
        "Biggest celebrity breakups and relationships of the year",
        "Best action movies releasing this month",
        f"Pakistan entertainment news weekly recap {_M} {_Y}",
        "Famous Pakistani YouTubers and how much they earn",
        "Best Urdu books everyone should read",
        "Top wedding song trends in Pakistan right now",
        "Most controversial celebrity interviews this year",
        "Best Pakistani food vlogs on YouTube",
        "Upcoming Pakistani movies you should be excited about",
        "Best gaming YouTube channels in Pakistan",
        f"Sports news Pakistan: weekly wrap-up {_M} {_Y}",
        "Most popular Pakistani memes explained",
        "Best travel destinations in Pakistan for weekend trips",
        "Funniest Pakistani TV moments that went viral",
        "Most anticipated movie sequels coming this year",
        "Top fashion trends from Pakistani celebrities",
        "Best motivational Pakistani speakers on YouTube",
        "Most streamed Pakistani songs of all time",
        "Celebrities who started from nothing: inspiring stories",
        "Best reality shows currently airing in Pakistan",
    ],
}


# ── Result types ────────────────────────────────────────────────────────────────

@dataclass
class PublishResult:
    success: bool
    blog_id: str
    niche: str
    language: str
    title: str = ""
    slug: str = ""
    word_count: int = 0
    qc_passed: bool = False
    github_pushed: bool = False
    error: str = ""
    duration_sec: float = 0.0


@dataclass
class CycleStats:
    started_at: str
    blogs_attempted: int = 0
    blogs_succeeded: int = 0
    blogs_failed: int = 0
    total_words: int = 0
    results: List[PublishResult] = field(default_factory=list)

    def summary(self) -> str:
        elapsed = (
            datetime.now(timezone.utc)
            - datetime.fromisoformat(self.started_at)
        ).total_seconds()
        return (
            f"{self.blogs_succeeded}/{self.blogs_attempted} published | "
            f"{self.total_words:,} words | "
            f"{elapsed:.0f}s"
        )


# ── DB helpers ──────────────────────────────────────────────────────────────────

def get_due_blogs(max_count: int = MAX_BLOGS_PER_CYCLE) -> List[Dict]:
    """
    Return active Cloudflare blogs that are due for a new post.
    A blog is 'due' if last_post_at is NULL or older than PUBLISH_GAP_HOURS.
    """
    try:
        from modules.database_manager import fetch_all
        cutoff = (
            datetime.now(timezone.utc) - timedelta(hours=PUBLISH_GAP_HOURS)
        ).isoformat()
        rows = fetch_all(
            "blogs",
            """SELECT id, blog_id, name, niche, language,
                      site_url, github_path, cloudflare_account_id,
                      last_post_at, post_count
               FROM blogs
               WHERE platform = 'cloudflare'
                 AND status   = 'active'
                 AND (last_post_at IS NULL OR last_post_at < ?)
               ORDER BY COALESCE(last_post_at, '1970-01-01') ASC
               LIMIT ?""",
            (cutoff, max_count),
        )
        return [dict(r) for r in rows] if rows else []
    except Exception as e:
        _log.error(f"get_due_blogs failed: {e}")
        return []


def mark_published(blog_id: str, title: str, slug: str) -> None:
    """Update blog stats after a successful publish."""
    try:
        from modules.database_manager import execute
        now = datetime.now(timezone.utc).isoformat()
        execute(
            "blogs",
            """UPDATE blogs
               SET last_post_at = ?,
                   post_count   = COALESCE(post_count, 0) + 1
               WHERE blog_id = ?""",
            (now, blog_id),
        )
        _log.debug(f"Marked published: {blog_id} — {title}")
    except Exception as e:
        _log.warning(f"mark_published failed ({blog_id}): {e}")


def get_used_topics(blog_id: str, limit: int = 50) -> List[str]:
    """Return recently used topic titles for a blog (to avoid repeats)."""
    try:
        from modules.database_manager import fetch_all
        rows = fetch_all(
            "content_archive",
            """SELECT title FROM content_archive
               WHERE blog_id = ?
               ORDER BY created_at DESC
               LIMIT ?""",
            (blog_id, limit),
        )
        return [r["title"].lower() for r in rows] if rows else []
    except Exception as e:
        _log.debug(f"get_used_topics fallback: {e}")
        # Fallback: read from published HTML files on disk
        try:
            import re as _re
            post_dir = SITES_DIR / blog_id.split("-")[0] / "posts" \
                if "-" not in blog_id else SITES_DIR / blog_id / "posts"
            # Try by DB site_url slug
            slugs = [p.stem for p in post_dir.glob("*.html")] if post_dir.exists() else []
            return [s.replace("-", " ") for s in slugs[:limit]]
        except Exception:
            return []


def save_to_archive(blog_id: str, draft) -> None:
    """Persist generated content to content_archive.db for deduplication."""
    try:
        from modules.database_manager import execute
        now = datetime.now(timezone.utc).isoformat()
        # Schema: id, blog_id, title, slug, body_html, meta_desc, language,
        #         niche, keywords, featured_image_url, status, published_url,
        #         created_at, published_at   (no word_count column)
        execute(
            "content_archive",
            """INSERT OR IGNORE INTO content_archive
               (blog_id, title, slug, niche, language, status, created_at, published_at)
               VALUES (?, ?, ?, ?, ?, 'published', ?, ?)""",
            (
                blog_id,
                draft.title,
                draft.slug,
                getattr(draft.brief, "niche", ""),
                getattr(draft.brief, "language", "en"),
                now,
                now,
            ),
        )
    except Exception as e:
        _log.warning(f"save_to_archive failed ({blog_id}): {e}")  # promoted to warning


# ── Topic selection ─────────────────────────────────────────────────────────────

def pick_topic(niche: str, language: str, used_titles: List[str]) -> str:
    """
    Pick a topic for the given niche.
    Priority:
      1. Live trend from trend_detector (if running and niche matches)
      2. Random item from NICHE_TOPICS pool (avoiding recent repeats)
      3. Generic fallback with timestamp
    """
    # 1. Try trend_detector
    try:
        from modules.trend_detector import is_running_status
        if is_running_status():
            # trend_detector fires callbacks — we can't pull synchronously,
            # so fall through to pool
            pass
    except Exception:
        pass

    # 2. Pool selection
    pool = NICHE_TOPICS.get(niche, NICHE_TOPICS.get("tech", []))
    used_lower = {t.lower() for t in used_titles}
    available = [t for t in pool if t.lower() not in used_lower]

    if not available:
        # All pool topics used — reset and reuse (fresh with current month/year)
        available = pool[:]

    if available:
        return random.choice(available)

    # 3. Fallback
    return f"Latest {niche} news and analysis — {datetime.now().strftime('%B %Y')}"


# ── HTML helpers ────────────────────────────────────────────────────────────────

def _get_existing_posts(site_dir: Path) -> List[Dict]:
    """Read all existing post HTML files and extract metadata."""
    posts = []
    for pfile in sorted(site_dir.glob("posts/*.html")):
        try:
            content = pfile.read_text(encoding="utf-8")
            slug = pfile.stem
            m = re.search(r"<h1[^>]*>(.*?)</h1>", content, re.DOTALL | re.IGNORECASE)
            title = re.sub(r"<[^>]+>", "", m.group(1)).strip() if m else slug
            m_date = re.search(
                r'<time[^>]*datetime="([^"]+)"', content, re.IGNORECASE
            )
            pub_date = m_date.group(1)[:10] if m_date else "2026-01-01"
            m_img = re.search(r'src="(https://[^"]+picsum[^"]+)"', content)
            img_url = m_img.group(1) if m_img else ""
            posts.append(
                {
                    "slug": slug,
                    "title": title,
                    "meta_desc": "",
                    "published_at": pub_date,
                    "featured_image_url": img_url,
                }
            )
        except Exception:
            continue
    return posts


# ── Extended PublishResult (carries internal state for batched push) ─────────────

class _ExtPublishResult(PublishResult):
    """Internal: carries site_dir + draft so run_cycle can batch the push."""
    _site_dir: Optional[Path] = None
    _draft: object = None


# ── Core publish pipeline ────────────────────────────────────────────────────────

def _generate_and_write(blog: Dict, dry_run: bool = False) -> "_ExtPublishResult":
    """
    Steps 1-5 of the pipeline: generate content, run QC, write HTML to disk.
    Does NOT push to GitHub — that is done in a single batched commit by run_cycle().

    Returns an _ExtPublishResult with _site_dir and _draft set so the caller
    can push all updated dirs in one commit.
    """
    t_start  = time.monotonic()
    blog_id  = blog["blog_id"]
    niche    = blog.get("niche", "tech")
    language = blog.get("language", "en")
    blog_url = (blog.get("site_url") or "").rstrip("/")
    gh_path  = blog.get("github_path") or f"sites/{blog_id}"
    # Parse site number from blog_id ("site-001" → 1, "site-042" → 42)
    # Never use the DB row id — that's an auto-increment unrelated to site path
    _site_num_match = re.search(r"(\d+)$", blog_id)
    site_num = int(_site_num_match.group(1)) if _site_num_match else blog.get("id", 1)

    _log.info(f"[{blog_id}] Generating — niche={niche} lang={language}")

    # 1. Topic
    used_titles = get_used_topics(blog_id)
    topic = pick_topic(niche, language, used_titles)
    _log.info(f"[{blog_id}] Topic: {topic}")

    # 2. Content generation
    from modules.content_generator import ContentBrief, generate, get_target_words
    from modules.quality_control   import run_qc

    draft  = None
    angles = ["in-depth guide", "analysis", "how-to", "expert review", "beginner guide"]

    for attempt in range(MAX_QC_RETRIES + 1):
        angle = random.choice(angles)
        brief = ContentBrief(
            niche=niche, language=language, topic=topic,
            keyword=topic.split(":")[0].strip().lower(),
            blog_role="hub", angle=angle,
            target_words=get_target_words(niche, language),
            voice_profile={},
        )
        draft = generate(brief)
        if draft is None:
            _log.warning(f"[{blog_id}] generate() returned None (attempt {attempt+1})")
            continue

        # 3. QC
        qc = run_qc(draft.body_html, niche, language)
        if qc.approved:
            _log.info(f"[{blog_id}] QC PASS — {draft.word_count}w via {draft.ai_provider}")
            break
        else:
            blocks = list(qc.block_reasons)
            _log.warning(f"[{blog_id}] QC BLOCK (attempt {attempt+1}): {'; '.join(blocks)}")
            if attempt < MAX_QC_RETRIES:
                topic = pick_topic(niche, language, used_titles + [topic])
            else:
                duration = time.monotonic() - t_start
                r = _ExtPublishResult(
                    success=False, blog_id=blog_id, niche=niche, language=language,
                    title=draft.title if draft else "",
                    error=f"QC blocked after {MAX_QC_RETRIES+1} attempts: {blocks[0] if blocks else 'unknown'}",
                    duration_sec=duration,
                )
                return r

    if draft is None:
        duration = time.monotonic() - t_start
        r = _ExtPublishResult(
            success=False, blog_id=blog_id, niche=niche, language=language,
            error="All AI providers failed", duration_sec=duration,
        )
        return r

    if dry_run:
        duration = time.monotonic() - t_start
        _log.info(f"[{blog_id}] DRY RUN — skipping write/push")
        r = _ExtPublishResult(
            success=True, blog_id=blog_id, niche=niche, language=language,
            title=draft.title, slug=draft.slug,
            word_count=draft.word_count, qc_passed=True,
            github_pushed=False, duration_sec=duration,
        )
        return r

    # 4. HTML generation
    from modules.static_site_generator import (
        SiteConfig, PostMeta, generate_post_html, generate_index_html,
    )

    # ── Active ad codes — injected into every page the bot generates ───────────
    # Monetag Multitag + Adsterra Popunder go in <head>
    # Adsterra Social Bar goes before </body> (slot_1)
    # Adsterra Native Banner (728x90) goes mid-content (slot_3)
    _AD_CODES = {
        "head": (
            '<script src="https://quge5.com/88/tag.min.js"'
            ' data-zone="231924" async data-cfasync="false"></script>\n'
            '<script src="https://pl29187206.profitablecpmratenetwork.com'
            '/16/cc/bf/16ccbffc155b8b226ff5a4a3cee1b3f7.js"></script>'
        ),
        "slot_1": (
            '<script async="async" data-cfasync="false"'
            ' src="https://pl29187207.profitablecpmratenetwork.com'
            '/b8e877d8b944bec7a11a9b6416c4b5f8/invoke.js"></script>'
        ),
        "slot_3": (
            "<script>\n  atOptions = {\n    'key' : 'dbadba18c43e9301d4313b491638f571',\n"
            "    'format' : 'iframe',\n    'height' : 90,\n    'width' : 728,\n"
            "    'params' : {}\n  };\n</script>\n"
            '<script src="https://www.highperformanceformat.com'
            '/dbadba18c43e9301d4313b491638f571/invoke.js"></script>'
        ),
    }

    cfg = SiteConfig(
        site_id=site_num, blog_id=blog_id,
        title=blog.get("name") or blog_id,
        language=language, niche=niche, blog_url=blog_url, ad_codes=_AD_CODES,
    )
    post_meta = PostMeta(
        slug=draft.slug, title=draft.title, meta_desc=draft.meta_desc,
        language=language,
        published_at=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        niche=niche, keywords=draft.keywords or [],
    )

    # Resolve site_dir from github_path
    parts = gh_path.strip("/").split("/")
    site_dir = SITES_DIR / (parts[1] if len(parts) >= 2 and parts[0] == "sites" else gh_path.strip("/"))
    site_dir.mkdir(parents=True, exist_ok=True)
    (site_dir / "posts").mkdir(exist_ok=True)

    existing_posts = _get_existing_posts(site_dir)
    post_html  = generate_post_html(
        post_meta, draft.body_html, cfg,
        related_posts=existing_posts[:3],
    )
    all_posts  = [{"slug": draft.slug, "title": draft.title, "meta_desc": draft.meta_desc,
                   "published_at": post_meta.published_at,
                   "featured_image_url": post_meta.featured_image_url}] + existing_posts
    index_html = generate_index_html(all_posts, cfg)

    # 5. Write to disk
    post_path = site_dir / "posts" / f"{draft.slug}.html"
    post_path.write_text(post_html, encoding="utf-8")
    (site_dir / "index.html").write_text(index_html, encoding="utf-8")

    # 5b. Regenerate sitemap.xml with correct URLs ──────────────────────────────
    try:
        from modules.static_site_generator import generate_sitemap_xml
        sitemap = generate_sitemap_xml(all_posts, cfg)
        (site_dir / "sitemap.xml").write_text(sitemap, encoding="utf-8")
    except Exception as _se:
        _log.warning(f"[{blog_id}] sitemap.xml update failed: {_se}")

    _log.info(f"[{blog_id}] Written: posts/{draft.slug}.html ({len(post_html):,} bytes)")

    duration = time.monotonic() - t_start
    r = _ExtPublishResult(
        success=True, blog_id=blog_id, niche=niche, language=language,
        title=draft.title, slug=draft.slug,
        word_count=draft.word_count, qc_passed=True,
        github_pushed=False,   # not pushed yet — batched later
        duration_sec=duration,
    )
    r._site_dir = site_dir
    r._draft    = draft
    return r


def publish_one(
    blog: Dict,
    dry_run: bool = False,
) -> PublishResult:
    """
    Run the full publish pipeline for one blog (generate + QC + write + push).
    Used by publish_blog() (single-blog CLI mode).

    blog dict keys: blog_id, niche, language, site_url, github_path, id (db row id)
    dry_run=True: generate + QC only — no file writes, no GitHub push.
    """
    t_start = time.monotonic()
    blog_id  = blog["blog_id"]
    niche    = blog.get("niche", "tech")
    language = blog.get("language", "en")
    blog_url = (blog.get("site_url") or "").rstrip("/")
    gh_path  = blog.get("github_path") or f"sites/{blog_id}"
    # Parse site number from blog_id ("site-001" → 1, "site-042" → 42)
    _site_num_match = re.search(r"(\d+)$", blog_id)
    site_num = int(_site_num_match.group(1)) if _site_num_match else blog.get("id", 1)

    _log.info(f"[{blog_id}] Starting publish — niche={niche} lang={language}")

    # Steps 1-5: generate + QC + write HTML to disk
    wr = _generate_and_write(blog, dry_run=dry_run)
    if not wr.success or dry_run:
        return wr

    # Step 6: GitHub push (immediate — single-blog mode)
    pushed = False
    try:
        from modules.github_publisher import make_publisher_from_config
        pub = make_publisher_from_config()
        if pub is None:
            raise RuntimeError("GitHub publisher not configured")
        pr = pub.push_site(site_num, wr._site_dir, github_path=gh_path)
        pushed = pr.success
        if pushed:
            _log.info(
                f"[{blog_id}] Pushed {len(pr.pushed)} files "
                f"sha={pr.commit_sha[:8] if pr.commit_sha else 'n/a'}"
            )
        else:
            _log.warning(f"[{blog_id}] GitHub push failed: {pr.message}")
    except Exception as e:
        _log.error(f"[{blog_id}] GitHub push error: {e}")

    # Steps 7-8: archive + traffic signals
    draft = wr._draft
    save_to_archive(blog_id, draft)
    if pushed:
        mark_published(blog_id, draft.title, draft.slug)
    if pushed and blog_url:
        _fire_traffic_signals(blog_url, draft.slug, draft.title, niche)

    wr.github_pushed = pushed
    wr.success       = pushed
    t_elapsed = time.monotonic() - t_start
    wr.duration_sec  = t_elapsed
    _log.info(
        f"[{blog_id}] Done in {t_elapsed:.1f}s — "
        f"'{draft.title[:55]}' ({draft.word_count}w) pushed={pushed}"
    )
    return wr


def _fire_traffic_signals(blog_url: str, slug: str, title: str, niche: str) -> None:
    """Fire IndexNow + social pings after a successful push (best-effort, non-blocking)."""
    # ── SAFETY GUARD: never submit the root hub page as a traffic target ─────────
    # The root topicpulse.pages.dev/ lists ALL 100 blogs — never promote it.
    # Only individual blog homepages (.../cryptoinsiderdaily/) or post URLs are OK.
    _parsed = _urlparse(blog_url)
    _path   = _parsed.path.strip("/")
    if not _path:
        _log.warning(
            f"BLOCKED: blog_url has no sub-path (root hub page) — "
            f"will NOT fire traffic signals for: {blog_url}"
        )
        return
    # ─────────────────────────────────────────────────────────────────────────────

    post_url = f"{blog_url}/posts/{slug}.html"

    # ── IndexNow: submit sitemap so Bing/Yandex crawl within minutes ────────────
    try:
        from modules.indexing import get_manager
        im = get_manager()
        result = im.on_post_published(blog_url)
        _log.info(f"IndexNow submitted {len(result)} sitemaps for {blog_url.split('/')[-1]}")
    except Exception as e:
        _log.warning(f"IndexNow ping failed: {e}")

    # ── Traffic engine: RSS pings, Twitter, Pinterest, Tumblr ───────────────────
    try:
        from modules.traffic_engine import get_dispatcher, PostSignal
        te = get_dispatcher()
        signal = PostSignal(
            url=post_url,
            title=title,
            meta_desc=f"{title} — read more on {blog_url}",
            language="en",
            niche=niche,
            blog_url=blog_url,
            slug=slug,
            keywords=[niche, "blog", title.split()[0] if title else ""],
            published_at=datetime.now(timezone.utc).isoformat(),
        )
        report = te.dispatch(signal)
        rss_list = getattr(report, 'rss_pings', [])
        rss_ok   = sum(1 for p in rss_list if getattr(p, 'success', False)) if isinstance(rss_list, list) else 0
        rss_tot  = len(rss_list) if isinstance(rss_list, list) else 0
        _log.info(
            f"Traffic [{slug}]: rss={rss_ok}/{rss_tot} "
            f"twitter={getattr(report,'twitter_posted',False)} "
            f"pinterest={getattr(report,'pinterest_posted',False)} "
            f"tumblr={getattr(report,'tumblr_posted',False)}"
        )
    except Exception as e:
        _log.warning(f"Traffic engine signal failed: {e}")

    # ── OneSignal web push notification ─────────────────────────────────────────
    try:
        from modules.push_notifications import notify_new_post
        blog_title = blog_url.rstrip("/").split("/")[-1].replace("-", " ").title()
        pushed = notify_new_post(
            blog_title=blog_title,
            post_title=title,
            post_url=post_url,
            niche=niche,
        )
        if pushed:
            _log.info(f"OneSignal push sent [{slug}]")
    except Exception as e:
        _log.warning(f"OneSignal push failed: {e}")

    # ── Medium syndication ───────────────────────────────────────────────────────
    try:
        from modules.medium_publisher import syndicate_post
        # Pass a short plain-text excerpt as content (Medium renders HTML)
        syndicated = syndicate_post(
            title=title,
            content_html=f"<p>Originally published at <a href='{post_url}'>{post_url}</a></p>",
            canonical_url=post_url,
            niche=niche,
            keywords=[niche, slug.replace("-", " ")],
        )
        if syndicated:
            _log.info(f"Medium syndicated [{slug}]")
    except Exception as e:
        _log.warning(f"Medium syndication failed: {e}")

    # ── CryptoPanic (crypto/finance niches only) ─────────────────────────────────
    try:
        from modules.cryptopanic_publisher import submit_crypto_post
        cp_ok = submit_crypto_post(title=title, url=post_url, niche=niche)
        if cp_ok:
            _log.info(f"CryptoPanic submitted [{slug}]")
    except Exception as e:
        _log.warning(f"CryptoPanic submit failed: {e}")

    # ── Flipboard ping ───────────────────────────────────────────────────────────
    try:
        from modules.flipboard_publisher import submit_post_to_flipboard
        rss_url = f"{blog_url}/sitemap.xml"
        fp_ok = submit_post_to_flipboard(title=title, url=post_url, rss_url=rss_url)
        if fp_ok:
            _log.info(f"Flipboard ping sent [{slug}]")
    except Exception as e:
        _log.warning(f"Flipboard ping failed: {e}")


# ── Cycle runner ─────────────────────────────────────────────────────────────────

def run_cycle(max_blogs: int = MAX_BLOGS_PER_CYCLE, dry_run: bool = False) -> CycleStats:
    """
    Publish one post to each due blog (up to max_blogs), then push ALL
    updated site dirs in a SINGLE GitHub commit at the end of the cycle.

    Batching writes → 1 Cloudflare build per cycle instead of 1 per blog.
    Free tier: 500 builds/month → handles ~16 cycles/day × 30 days easily.
    """
    stats = CycleStats(started_at=datetime.now(timezone.utc).isoformat())
    blogs = get_due_blogs(max_blogs)

    if not blogs:
        _log.info("No blogs due for publishing this cycle.")
        return stats

    _log.info(f"Cycle start — {len(blogs)} blogs due (max={max_blogs})")

    # Phase 1: Generate + write HTML for all blogs (no push yet)
    pending_push: List[Dict] = []   # [{blog, site_num, site_dir, draft}]

    for blog in blogs:
        stats.blogs_attempted += 1
        try:
            result = _generate_and_write(blog, dry_run=dry_run)
            stats.results.append(result)
            if result.success:
                if dry_run:
                    stats.blogs_succeeded += 1
                    stats.total_words += result.word_count
                else:
                    # Queue for batched push
                    # Parse site number from blog_id ("site-001" → 1)
                    _snm = re.search(r"(\d+)$", blog["blog_id"])
                    _sn  = int(_snm.group(1)) if _snm else blog.get("id", 1)
                    pending_push.append({
                        "blog":     blog,
                        "site_num": _sn,
                        "site_dir": result._site_dir,
                        "draft":    result._draft,
                        "result":   result,
                    })
            else:
                stats.blogs_failed += 1
                _log.warning(f"Blog {blog['blog_id']} write failed: {result.error}")
        except Exception as e:
            stats.blogs_failed += 1
            _log.error(f"Blog {blog['blog_id']} unexpected error: {e}", exc_info=True)
            stats.results.append(PublishResult(
                success=False, blog_id=blog["blog_id"],
                niche=blog.get("niche", "?"), language=blog.get("language", "?"),
                error=str(e),
            ))

    if dry_run or not pending_push:
        _log.info(f"Cycle complete — {stats.summary()}")
        return stats

    # Phase 2: Single batched GitHub push for all updated sites
    _log.info(f"Batched push — {len(pending_push)} sites in one commit")
    pushed_ids: set = set()
    try:
        from modules.github_publisher import make_publisher_from_config
        pub = make_publisher_from_config()
        if pub is None:
            raise RuntimeError("GitHub publisher not configured")

        # Push all updated dirs as one commit using push_multiple_sites if available,
        # otherwise fall back to sequential pushes (still one commit per site)
        if hasattr(pub, "push_multiple_sites"):
            dirs = [(p["site_num"], p["site_dir"]) for p in pending_push]
            push_result = pub.push_multiple_sites(dirs)
            if push_result.success:
                pushed_ids = {p["blog"]["blog_id"] for p in pending_push}
                _log.info(f"Batch push OK — sha={push_result.commit_sha[:8] if push_result.commit_sha else 'n/a'}")
            else:
                _log.warning(f"Batch push failed: {push_result.message}")
        else:
            # Fallback: push each site dir individually, using github_path from DB
            for item in pending_push:
                gh_p = item["blog"].get("github_path") or item["blog"]["blog_id"].lower()
                push_r = pub.push_site(item["site_num"], item["site_dir"], github_path=gh_p)
                if push_r.success:
                    pushed_ids.add(item["blog"]["blog_id"])
                else:
                    _log.warning(f"Push failed for {item['blog']['blog_id']}: {push_r.message}")
    except Exception as e:
        _log.error(f"Batched push error: {e}", exc_info=True)

    # Phase 3: Update DB + fire traffic signals for successfully pushed blogs
    for item in pending_push:
        b_id  = item["blog"]["blog_id"]
        draft = item["draft"]
        pushed = b_id in pushed_ids

        # Mark the result object as pushed/failed
        item["result"].github_pushed = pushed
        item["result"].success       = pushed

        if pushed:
            stats.blogs_succeeded += 1
            stats.total_words     += item["result"].word_count
            save_to_archive(b_id, draft)
            mark_published(b_id, draft.title, draft.slug)
            blog_url = (item["blog"].get("site_url") or "").rstrip("/")
            if blog_url:
                _fire_traffic_signals(blog_url, draft.slug, draft.title,
                                      item["blog"].get("niche", "tech"))
        else:
            stats.blogs_failed += 1
            item["result"].error = "GitHub push failed"

    _log.info(f"Cycle complete — {stats.summary()}")
    return stats


# ── Single-blog shortcut ─────────────────────────────────────────────────────────

def publish_blog(blog_id: str, dry_run: bool = False) -> PublishResult:
    """Publish one specific blog by blog_id. Used for testing and manual triggers."""
    try:
        from modules.database_manager import fetch_one
        row = fetch_one(
            "blogs",
            "SELECT * FROM blogs WHERE blog_id = ? AND platform = 'cloudflare'",
            (blog_id,),
        )
        if not row:
            return PublishResult(
                success=False, blog_id=blog_id, niche="?", language="?",
                error=f"Blog '{blog_id}' not found in DB",
            )
        return publish_one(dict(row), dry_run=dry_run)
    except Exception as e:
        return PublishResult(
            success=False, blog_id=blog_id, niche="?", language="?",
            error=str(e),
        )


# ── Forever loop ─────────────────────────────────────────────────────────────────

def run_forever(interval_minutes: int = CYCLE_INTERVAL_MINS) -> None:
    """
    Run publish cycles indefinitely.
    interval_minutes: sleep between cycles.
    """
    _log.info(
        f"Bot loop starting — cycle every {interval_minutes}min, "
        f"max {MAX_BLOGS_PER_CYCLE} blogs/cycle, "
        f"gap {PUBLISH_GAP_HOURS}h/blog"
    )
    cycle_num = 0
    while True:
        cycle_num += 1
        _log.info(f"──── Cycle #{cycle_num} ────")
        _write_status("running", cycle_num=cycle_num, summary=f"Cycle #{cycle_num} in progress…")
        try:
            stats = run_cycle()
            _write_status(
                "idle",
                cycle_num=cycle_num,
                summary=f"Cycle #{cycle_num} done — {stats.summary()}",
            )
        except KeyboardInterrupt:
            _write_status("stopped", cycle_num=cycle_num, summary="Stopped by user")
            _log.info("Bot loop stopped by user.")
            break
        except Exception as e:
            _write_status("idle", cycle_num=cycle_num, summary=f"Cycle #{cycle_num} error: {e}")
            _log.error(f"Cycle #{cycle_num} crashed: {e}", exc_info=True)

        sleep_sec = max(MIN_CYCLE_SLEEP_SEC, interval_minutes * 60)
        _log.info(f"Sleeping {sleep_sec // 60}m until next cycle…")
        _write_status(
            "sleeping",
            cycle_num=cycle_num,
            summary=f"Sleeping {sleep_sec // 60}m before cycle #{cycle_num + 1}",
        )
        try:
            time.sleep(sleep_sec)
        except KeyboardInterrupt:
            _write_status("stopped", cycle_num=cycle_num, summary="Stopped by user")
            _log.info("Bot loop stopped by user.")
            break


# ── CLI entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="BlogBot autonomous publish loop",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python bot_loop.py                    # run forever (30-min cycles)
  python bot_loop.py --once             # run one cycle and exit
  python bot_loop.py --blog site-001    # publish one specific blog and exit
  python bot_loop.py --dry-run          # test without writing or pushing
  python bot_loop.py --interval 60      # run forever with 60-min cycles
        """,
    )
    parser.add_argument("--once",     action="store_true", help="Run one cycle and exit")
    parser.add_argument("--blog",     type=str,            help="Publish one specific blog_id")
    parser.add_argument("--dry-run",  action="store_true", help="Generate + QC only — no write/push")
    parser.add_argument("--interval", type=int, default=CYCLE_INTERVAL_MINS,
                        help=f"Cycle interval in minutes (default: {CYCLE_INTERVAL_MINS})")
    parser.add_argument("--max-blogs",type=int, default=MAX_BLOGS_PER_CYCLE,
                        help=f"Max blogs per cycle (default: {MAX_BLOGS_PER_CYCLE})")
    args = parser.parse_args()

    # ── Write PID file so the dashboard can detect the bot is running ────────────
    _write_pid()
    atexit.register(_remove_pid)
    _write_status("starting", summary="Bot initialising…")

    if args.blog:
        # Single blog mode
        result = publish_blog(args.blog, dry_run=args.dry_run)
        print(
            f"\n{'OK' if result.success else 'FAIL'} — {result.blog_id} "
            f"| {result.title[:60]} "
            f"| {result.word_count}w "
            f"| pushed={result.github_pushed} "
            f"| {result.duration_sec:.1f}s"
        )
        if not result.success:
            print(f"Error: {result.error}")
        sys.exit(0 if result.success else 1)

    if args.once:
        # One cycle mode
        _write_status("running", cycle_num=1, summary="Running single cycle…")
        stats = run_cycle(max_blogs=args.max_blogs, dry_run=args.dry_run)
        _write_status("stopped", cycle_num=1, summary=f"--once done: {stats.summary()}")
        print(f"\nCycle complete: {stats.summary()}")
        for r in stats.results:
            status = "OK  " if r.success else "FAIL"
            print(
                f"  [{status}] {r.blog_id:15} | {r.title[:50]:50} "
                f"| {r.word_count:4}w | {r.duration_sec:.1f}s"
            )
        sys.exit(0 if stats.blogs_failed == 0 else 1)

    # Forever mode
    run_forever(interval_minutes=args.interval)


if __name__ == "__main__":
    main()
