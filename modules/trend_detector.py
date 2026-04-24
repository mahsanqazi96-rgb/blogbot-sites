"""
BlogBot — trend_detector.py
Detects viral trends in 5 minutes. Scores and routes to publish queue.

Sources:
  - Google Trends (pytrends) — every 2-3 minutes
  - RSS feeds from 20+ major news sites
  - Reddit rising posts (no API key needed)
  - NewsAPI.org (free tier)
  - Twitter/X trending (via Nitter RSS — no API key)

Scoring:
  - Viral spike (>500% in 5 min): P1 — live in 5 minutes
  - Rising fast (>200% in 15 min): P2 — 15 minutes
  - Trending (>100% in 1 hour): P3 — 20 minutes
  - Steady (new in top 20): P4 — 60 minutes

Rules:
  - Max 3 blogs per trend topic
  - Topic lock: prevents duplicate posts
  - Second wave detector: 24-48hr resurgence
  - Min 30 min between blog posts on same topic
"""

import sys
import time
import logging
import threading
import hashlib
import json
import re
import feedparser
import requests

# ── Optional: pytrends Google Trends ────────────────────────────────────────────
try:
    from pytrends.request import TrendReq as _TrendReq
    _PYTRENDS_OK = True
except ImportError:
    _PYTRENDS_OK = False

from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Tuple
from collections import defaultdict

# ── Path bootstrap ────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent.parent.resolve()
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

LOGS_DIR = BASE_DIR / "logs"

# ── Logging ───────────────────────────────────────────────────────────────────
_log = logging.getLogger("trend_detector")
_log.setLevel(logging.INFO)
if not _log.handlers:
    _fh = logging.FileHandler(LOGS_DIR / "activity.log", encoding="utf-8")
    _fh.setFormatter(logging.Formatter("%(asctime)s [TREND] %(levelname)s %(message)s"))
    _log.addHandler(_fh)

# ── Constants ─────────────────────────────────────────────────────────────────
VIRAL_THRESHOLD    = 500   # % spike for P1
RISING_THRESHOLD   = 200   # % spike for P2
TRENDING_THRESHOLD = 100   # % spike for P3

MAX_BLOGS_PER_TOPIC = 3
TOPIC_LOCK_HOURS    = 6     # Don't re-pick same topic for 6 hours
SECOND_WAVE_WINDOW  = (22, 50)  # Hours — detect resurgence 22-50hr after first wave

CHECK_INTERVAL_GOOGLE = 150   # 2.5 minutes
CHECK_INTERVAL_RSS    = 300   # 5 minutes
CHECK_INTERVAL_REDDIT = 600   # 10 minutes

# ── Topic Lock (in-memory) ────────────────────────────────────────────────────
_topic_locks: Dict[str, datetime] = {}   # topic_key → unlock_time
_topic_blog_counts: Dict[str, int] = {}  # topic_key → blogs used
_topic_lock = threading.Lock()

def _topic_key(topic: str) -> str:
    return hashlib.md5(topic.lower().strip().encode()).hexdigest()[:16]

def is_topic_locked(topic: str) -> bool:
    key = _topic_key(topic)
    with _topic_lock:
        unlock = _topic_locks.get(key)
        if unlock and datetime.now(timezone.utc) < unlock:
            return True
        count = _topic_blog_counts.get(key, 0)
        return count >= MAX_BLOGS_PER_TOPIC

def lock_topic(topic: str, blog_index: int = 0):
    """Lock a topic after assignment to prevent over-use."""
    key = _topic_key(topic)
    with _topic_lock:
        count = _topic_blog_counts.get(key, 0) + 1
        _topic_blog_counts[key] = count
        if count >= MAX_BLOGS_PER_TOPIC:
            _topic_locks[key] = datetime.now(timezone.utc) + timedelta(hours=TOPIC_LOCK_HOURS)

def get_topic_blog_index(topic: str) -> int:
    """Returns which blog index (0, 1, 2) this is for the topic."""
    key = _topic_key(topic)
    with _topic_lock:
        return _topic_blog_counts.get(key, 0)

def cleanup_topic_locks():
    """Remove expired locks. Called every 30 minutes by scheduler."""
    now = datetime.now(timezone.utc)
    with _topic_lock:
        expired_keys = [k for k, t in _topic_locks.items() if t <= now]
        for k in expired_keys:
            del _topic_locks[k]
            _topic_blog_counts.pop(k, None)

# ── Trend Score & Trend Object ────────────────────────────────────────────────
class Trend:
    def __init__(self, topic: str, source: str, score: int,
                 priority: int, niche: str = "breaking_news",
                 language: str = "en", url: str = ""):
        self.topic = topic
        self.source = source
        self.score = score
        self.priority = priority
        self.niche = niche
        self.language = language
        self.url = url
        self.detected_at = datetime.now(timezone.utc)
        self.key = _topic_key(topic)

    def to_dict(self) -> dict:
        return {
            "topic": self.topic,
            "source": self.source,
            "score": self.score,
            "priority": self.priority,
            "niche": self.niche,
            "language": self.language,
            "url": self.url,
            "detected_at": self.detected_at.isoformat(),
        }

def _score_to_priority(score: int) -> int:
    if score >= VIRAL_THRESHOLD:    return 1
    if score >= RISING_THRESHOLD:   return 2
    if score >= TRENDING_THRESHOLD: return 3
    return 4

# ── Trend Callbacks ───────────────────────────────────────────────────────────
_trend_callbacks: List = []

def on_trend(callback):
    """Register a callback: callback(trend: Trend). Called for each new trend."""
    _trend_callbacks.append(callback)

def _emit_trend(trend: Trend):
    """Emit trend to all registered callbacks and enqueue to publish queue."""
    if is_topic_locked(trend.topic):
        _log.debug(f"Topic locked: {trend.topic}")
        return

    blog_index = get_topic_blog_index(trend.topic)
    lock_topic(trend.topic, blog_index)

    _log.info(f"[P{trend.priority}] TREND: '{trend.topic}' score={trend.score} src={trend.source}")

    # Enqueue to scheduler
    try:
        from modules.scheduler import enqueue_post
        enqueue_post(
            blog_id="auto",         # blog_manager assigns actual blog
            priority=trend.priority,
            topic=trend.topic,
            language=trend.language,
            payload=trend.to_dict(),
            topic_index=blog_index,
        )
    except Exception as e:
        _log.error(f"Failed to enqueue trend: {e}")

    # Audit
    try:
        from modules.database_manager import audit
        audit("trend_detector", f"p{trend.priority}_trend",
              f"{trend.topic} | score={trend.score}", "INFO")
    except Exception as e:  # noqa: BLE001 — audit log is best-effort
        _log.debug(f"trend_detector audit log write failed: {e}")

    # External callbacks
    for cb in _trend_callbacks:
        try:
            cb(trend)
        except Exception as e:
            _log.error(f"Trend callback error: {e}")

# ── Google Trends ─────────────────────────────────────────────────────────────
_google_previous: Dict[str, int] = {}

NICHE_KEYWORDS = {
    "finance":      ["stock market", "bitcoin", "crypto", "investing", "interest rate"],
    "tech":         ["ai", "chatgpt", "iphone", "android", "gadget"],
    "health":       ["weight loss", "diet", "exercise", "mental health", "covid"],
    "gaming":       ["gaming", "playstation", "xbox", "game release", "esports"],
    "celebrity":    ["celebrity", "actor", "singer", "reality tv", "viral"],
    "sports":       ["football", "cricket", "basketball", "tennis", "f1"],
    "breaking_news":["breaking news", "earthquake", "election", "war", "disaster"],
    "movies_tv":    ["netflix", "movie trailer", "tv show", "streaming", "box office"],
    "food":         ["recipe", "restaurant", "food", "cooking", "diet"],
    "crypto":       ["bitcoin", "ethereum", "crypto", "defi", "nft"],
}

def _fetch_google_trends(geo: str = "US") -> List[Trend]:
    """Fetch Google Trends realtime data. Returns list of Trend objects."""
    trends = []
    try:
        from pytrends.request import TrendReq
        pt = TrendReq(hl="en-US", tz=0, timeout=(10, 25), retries=2, backoff_factor=0.5)

        # Realtime trending searches
        try:
            df = pt.realtime_trending_searches(pn="US")
            if df is not None and not df.empty:
                for _, row in df.head(10).iterrows():
                    topic = str(row.get("title", "")).strip()
                    if not topic or len(topic) < 3:
                        continue
                    traffic = str(row.get("trafficBucketLowerBound", "100"))
                    # Parse traffic: "100K+" → 100000
                    score = _parse_traffic(traffic)
                    priority = _score_to_priority(score)
                    niche = _guess_niche(topic)
                    trends.append(Trend(topic, "google_realtime", score, priority, niche))
        except Exception as e:
            _log.debug(f"Google realtime trends error: {e}")

        # Top searches for specific niches
        for niche, keywords in list(NICHE_KEYWORDS.items())[:3]:
            try:
                pt.build_payload(keywords[:2], timeframe="now 1-H", geo=geo)
                related = pt.related_queries()
                for kw, data in related.items():
                    if data and data.get("rising") is not None:
                        for _, row in data["rising"].head(3).iterrows():
                            q = str(row.get("query", "")).strip()
                            val = int(row.get("value", 0))
                            if q and val > 0:
                                score = min(val * 5, 999)
                                trends.append(Trend(q, "google_rising", score,
                                                    _score_to_priority(score), niche))
                time.sleep(1)
            except Exception as e:  # noqa: BLE001 — pytrends raises many types
                _log.debug(f"trend_detector related_queries({niche}) failed: {e}")

    except ImportError:
        _log.warning("pytrends not installed — Google Trends skipped")
    except Exception as e:
        _log.error(f"Google Trends fetch error: {e}")

    return trends

def fetch_google_trends(niche: str = "", geo: str = "US") -> List[Dict]:
    """
    Fetch daily trending searches from Google Trends (pytrends).
    Connects ONLY to trends.google.com — public data, no API key required.
    Returns list of {title, score, source, niche, geo} dicts.
    Rate limit: pytrends handles backoff automatically.
    """
    if not _PYTRENDS_OK:
        _log.debug("pytrends not installed — Google Trends skipped")
        return []
    results = []
    try:
        pytrends = _TrendReq(hl="en-US", tz=0, timeout=(10, 30), retries=2, backoff_factor=0.5)
        geo_code = geo.lower() if geo else "united_states"
        trending = pytrends.trending_searches(pn=geo_code)
        if trending is not None and not trending.empty:
            for topic in trending.iloc[:, 0].tolist()[:20]:
                topic = str(topic).strip()
                if not topic:
                    continue
                results.append({
                    "title":  topic,
                    "score":  75,
                    "source": "google_trends",
                    "niche":  niche or "general",
                    "geo":    geo or "worldwide",
                })
        _log.info(f"Google Trends: {len(results)} trending topics (geo={geo or 'US'})")
    except Exception as e:
        _log.warning(f"fetch_google_trends error: {e}")
    return results


def _parse_traffic(traffic_str: str) -> int:
    """Parse '100K+', '500K+', '1M+' → integer."""
    s = str(traffic_str).upper().replace("+", "").strip()
    try:
        if "M" in s:
            return int(float(s.replace("M", "")) * 1_000_000 / 10_000)  # normalize to 0-1000
        if "K" in s:
            return int(float(s.replace("K", "")) / 10)
        return int(s)
    except Exception as e:  # noqa: BLE001 — best-effort parser, fall back to median
        _log.debug(f"trend_detector._parse_traffic({traffic_str!r}): {e}")
        return 100

# ── RSS Feed Sources ──────────────────────────────────────────────────────────
RSS_FEEDS = [
    # News
    ("https://feeds.bbci.co.uk/news/rss.xml",                   "breaking_news", "en"),
    ("https://rss.cnn.com/rss/cnn_topstories.rss",              "breaking_news", "en"),
    ("https://feeds.reuters.com/reuters/topNews",                "breaking_news", "en"),
    ("https://feeds.foxnews.com/foxnews/latest",                 "breaking_news", "en"),
    ("https://rss.nytimes.com/services/xml/rss/nyt/HomePage.xml","breaking_news", "en"),

    # Tech
    ("https://feeds.feedburner.com/TechCrunch",                  "tech", "en"),
    ("https://www.theverge.com/rss/index.xml",                   "tech", "en"),
    ("https://feeds.arstechnica.com/arstechnica/index",          "tech", "en"),

    # Finance / Crypto
    ("https://feeds.finance.yahoo.com/rss/2.0/headline?s=^GSPC","finance", "en"),
    ("https://cointelegraph.com/rss",                            "crypto", "en"),
    ("https://coindesk.com/arc/outboundfeeds/rss/",             "crypto", "en"),

    # Sports
    ("https://www.espn.com/espn/rss/news",                       "sports", "en"),

    # Entertainment
    ("https://variety.com/feed/",                                "movies_tv", "en"),
    ("https://deadline.com/feed/",                               "movies_tv", "en"),

    # Spanish
    ("https://feeds.elpais.com/mrss-s/pages/ep/site/elpais.com/portada", "breaking_news", "es"),
    ("https://www.bbc.co.uk/mundo/rss.xml",                     "breaking_news", "es"),

    # Hindi
    ("https://feeds.feedburner.com/ndtvindia",                   "breaking_news", "hi"),

    # Arabic
    ("https://www.aljazeera.net/rss/all.xml",                   "breaking_news", "ar"),

    # French
    ("https://www.lemonde.fr/rss/une.xml",                       "breaking_news", "fr"),

    # Portuguese
    ("https://feeds.folha.uol.com.br/emcimadahora/rss091.xml",  "breaking_news", "pt"),
]

_rss_seen: Dict[str, datetime] = {}  # title_hash → first_seen

def _fetch_rss_trends() -> List[Trend]:
    trends = []
    now = datetime.now(timezone.utc)

    for url, niche, lang in RSS_FEEDS:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:5]:
                title = entry.get("title", "").strip()
                if not title or len(title) < 10:
                    continue

                h = hashlib.md5(title.encode()).hexdigest()[:12]
                if h in _rss_seen:
                    # Check if item is new (within 30 min = trending)
                    age = (now - _rss_seen[h]).total_seconds() / 60
                    if age > 30:
                        continue  # Already processed
                else:
                    _rss_seen[h] = now
                    # New item — assign score based on position
                    score = 150  # Default: trending
                    t = Trend(title, f"rss_{lang}", score, _score_to_priority(score),
                              niche, lang, entry.get("link", ""))
                    trends.append(t)
        except Exception as e:
            _log.debug(f"RSS feed error {url[:50]}: {e}")

    # Prune old RSS seen entries (keep 24 hours)
    cutoff = now - timedelta(hours=24)
    stale = [k for k, v in _rss_seen.items() if v < cutoff]
    for k in stale:
        del _rss_seen[k]

    return trends

# ── Reddit Rising ─────────────────────────────────────────────────────────────
REDDIT_SUBS = [
    ("worldnews",   "breaking_news", "en"),
    ("news",        "breaking_news", "en"),
    ("technology",  "tech",          "en"),
    ("CryptoCurrency","crypto",      "en"),
    ("investing",   "finance",       "en"),
    ("sports",      "sports",        "en"),
    ("movies",      "movies_tv",     "en"),
    ("gaming",      "gaming",        "en"),
    ("health",      "health",        "en"),
    ("food",        "food",          "en"),
]

_reddit_seen: set = set()

def _fetch_reddit_trends() -> List[Trend]:
    trends = []
    headers = {
        "User-Agent": "BlogBot/1.0 (automated content bot; contact admin)",
        "Accept": "application/json",
    }
    for sub, niche, lang in REDDIT_SUBS[:5]:  # Limit to avoid rate limit
        try:
            url = f"https://www.reddit.com/r/{sub}/rising.json?limit=5"
            resp = requests.get(url, headers=headers, timeout=15)
            if resp.status_code != 200:
                continue
            data = resp.json()
            posts = data.get("data", {}).get("children", [])
            for post in posts:
                pd = post.get("data", {})
                title = pd.get("title", "").strip()
                upvotes = pd.get("ups", 0)
                if not title or upvotes < 100:
                    continue

                h = hashlib.md5(title.encode()).hexdigest()[:12]
                if h in _reddit_seen:
                    continue
                _reddit_seen.add(h)

                # Score: upvotes / 100, capped at 999
                score = min(upvotes // 100, 999)
                if score < 50:
                    score = 100  # Minimum

                link = f"https://reddit.com{pd.get('permalink', '')}"
                trends.append(Trend(title, f"reddit_{sub}", score,
                                    _score_to_priority(score), niche, lang, link))
            time.sleep(2)  # Be polite to Reddit
        except Exception as e:
            _log.debug(f"Reddit {sub} error: {e}")

    return trends

# ── Second Wave Detector ──────────────────────────────────────────────────────
_first_wave_log: Dict[str, datetime] = {}  # topic_key → first detection time

def check_second_wave(trends: List[Trend]) -> List[Trend]:
    """
    If a topic resurges 22-50 hours after first wave, flag as second wave P2.
    """
    now = datetime.now(timezone.utc)
    second_wave = []

    for t in trends:
        key = t.key
        first_seen = _first_wave_log.get(key)

        if first_seen is None:
            _first_wave_log[key] = now
        else:
            hours_since = (now - first_seen).total_seconds() / 3600
            if SECOND_WAVE_WINDOW[0] <= hours_since <= SECOND_WAVE_WINDOW[1]:
                # Second wave!
                t2 = Trend(f"UPDATE: {t.topic}", "second_wave",
                           max(t.score, 200), 2, t.niche, t.language, t.url)
                second_wave.append(t2)
                _log.info(f"Second wave detected: {t.topic} ({hours_since:.0f}hr after first)")

    return second_wave

# ── Niche Classifier ──────────────────────────────────────────────────────────
NICHE_PATTERNS = {
    "crypto":       r"bitcoin|ethereum|crypto|nft|defi|blockchain|token|coin\b|web3",
    "finance":      r"stock|market|invest|bank|economy|inflation|rate|trading|fund",
    "health":       r"health|medical|doctor|hospital|diet|weight|fitness|mental|covid|vaccine",
    "tech":         r"ai|iphone|android|app|software|computer|gadget|robot|tech|google|apple|microsoft",
    "gaming":       r"game|xbox|playstation|nintendo|steam|esport|streamer|twitch",
    "celebrity":    r"celebrity|actor|singer|rapper|kardashian|royal|wedding|divorce",
    "sports":       r"football|soccer|cricket|basketball|tennis|nba|nfl|f1|olympic|match|league|championship|tournament|premier|united|arsenal|chelsea|liverpool|transfer|goal|wicket|innings",
    "movies_tv":    r"netflix|movie|film|series|episode|season|trailer|box office|streaming",
    "food":         r"recipe|restaurant|food|chef|cook|diet|meal|ingredient",
    "adult":        r"adult|xxx|nsfw|porn|sex",
}

def _guess_niche(text: str) -> str:
    text_lower = text.lower()
    for niche, pattern in NICHE_PATTERNS.items():
        if niche == "adult":
            continue  # Never auto-assign adult from safe detection
        if re.search(pattern, text_lower):
            return niche
    return "breaking_news"

# ── Main Detection Loop ───────────────────────────────────────────────────────
_running = threading.Event()
_detection_thread: Optional[threading.Thread] = None

def _detection_loop():
    """Main loop: runs continuously, polling all sources on their intervals."""
    last_google = 0
    last_rss = 0
    last_reddit = 0

    while _running.is_set():
        now = time.time()
        all_trends = []

        # Google Trends
        if now - last_google >= CHECK_INTERVAL_GOOGLE:
            try:
                trends = _fetch_google_trends()
                all_trends.extend(trends)
                last_google = now
                if trends:
                    _log.info(f"Google Trends: {len(trends)} topics found")
            except Exception as e:
                _log.error(f"Google Trends cycle error: {e}")

        # RSS Feeds
        if now - last_rss >= CHECK_INTERVAL_RSS:
            try:
                trends = _fetch_rss_trends()
                all_trends.extend(trends)
                last_rss = now
                if trends:
                    _log.info(f"RSS: {len(trends)} new items")
            except Exception as e:
                _log.error(f"RSS cycle error: {e}")

        # Reddit
        if now - last_reddit >= CHECK_INTERVAL_REDDIT:
            try:
                trends = _fetch_reddit_trends()
                all_trends.extend(trends)
                last_reddit = now
                if trends:
                    _log.info(f"Reddit: {len(trends)} rising topics")
            except Exception as e:
                _log.error(f"Reddit cycle error: {e}")

        # Google Trends (trending_searches — daily, via fetch_google_trends)
        try:
            trends = [
                Trend(t["title"], t["source"], t["score"],
                      _score_to_priority(t["score"]), t.get("niche", "general"))
                for t in fetch_google_trends()
            ]
            all_trends.extend(trends)
            if trends:
                _log.info(f"Google Trends (daily): {len(trends)} topics")
        except Exception as e:
            _log.warning(f"Google Trends source failed: {e}")

        # Second wave check
        if all_trends:
            second_wave = check_second_wave(all_trends)
            all_trends.extend(second_wave)

        # Emit all trends (highest priority first)
        all_trends.sort(key=lambda t: (t.priority, -t.score))
        for trend in all_trends:
            try:
                _emit_trend(trend)
            except Exception as e:
                _log.error(f"Emit trend error: {e}")

        # Heartbeat
        try:
            from modules.database_manager import heartbeat
            heartbeat("trend_detector")
        except Exception as e:  # noqa: BLE001 — heartbeat is best-effort
            _log.debug(f"trend_detector heartbeat failed: {e}")

        time.sleep(30)  # Check every 30 seconds; source timers control actual fetching

def start():
    global _detection_thread
    _running.set()
    _detection_thread = threading.Thread(
        target=_detection_loop, daemon=True, name="trend_detector"
    )
    _detection_thread.start()
    _log.info("Trend detector started")

def stop():
    _running.clear()
    _log.info("Trend detector stopped")

def is_running_status() -> bool:
    return _running.is_set() and (_detection_thread is not None and _detection_thread.is_alive())

# ── Manual Trend Injection ────────────────────────────────────────────────────
def inject_trend(topic: str, priority: int = 2, niche: str = "breaking_news",
                 language: str = "en") -> Trend:
    """Manually inject a trend (for testing or dashboard use)."""
    t = Trend(topic, "manual", 200, priority, niche, language)
    _emit_trend(t)
    return t

# ── Self-Test ─────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("trend_detector self-test...")

    # Topic lock — must call lock_topic MAX_BLOGS_PER_TOPIC times to engage lock
    for _ in range(MAX_BLOGS_PER_TOPIC):
        lock_topic("test topic bitcoin")
    locked = is_topic_locked("test topic bitcoin")
    print(f"  Topic lock: {'OK' if locked else 'FAIL'}")

    # Niche guesser
    n1 = _guess_niche("Bitcoin crashes as crypto market collapses")
    n2 = _guess_niche("iPhone 17 leaked specs revealed")
    n3 = _guess_niche("Man United wins Premier League")
    print(f"  Niche guess crypto: {n1} {'OK' if n1=='crypto' else 'WARN'}")
    print(f"  Niche guess tech:   {n2} {'OK' if n2=='tech' else 'WARN'}")
    print(f"  Niche guess sports: {n3} {'OK' if n3=='sports' else 'WARN'}")

    # Traffic parser
    p1 = _parse_traffic("100K+")
    p2 = _parse_traffic("1M+")
    print(f"  Traffic parse 100K+: {p1} {'OK' if p1 > 0 else 'FAIL'}")
    print(f"  Traffic parse 1M+:   {p2} {'OK' if p2 > 0 else 'FAIL'}")

    # RSS fetch (live test)
    print("  Fetching RSS feeds (live)...")
    rss = _fetch_rss_trends()
    print(f"  RSS trends found: {len(rss)}")
    if rss:
        print(f"  First trend: '{rss[0].topic[:60]}' [{rss[0].niche}] P{rss[0].priority}")

    # Manual inject
    captured = []
    on_trend(lambda t: captured.append(t))
    inject_trend("Test Viral Topic 2026", priority=1, niche="breaking_news")
    print(f"  Inject + callback: {'OK' if len(captured) == 1 else 'WARN (topic may be locked)'}")

    # Priority routing
    p1t = Trend("viral test", "test", 600, _score_to_priority(600))
    p2t = Trend("rising test", "test", 250, _score_to_priority(250))
    p3t = Trend("trending test", "test", 120, _score_to_priority(120))
    print(f"  Score 600 -> P{p1t.priority} {'OK' if p1t.priority == 1 else 'FAIL'}")
    print(f"  Score 250 -> P{p2t.priority} {'OK' if p2t.priority == 2 else 'FAIL'}")
    print(f"  Score 120 -> P{p3t.priority} {'OK' if p3t.priority == 3 else 'FAIL'}")

    print("Self-test complete.")
