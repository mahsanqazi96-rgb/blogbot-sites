"""
BlogBot — static_site_generator.py
Phase 3B: Static Site Engine

Responsibilities:
  - Jinja2 HTML templates (5 niche styles: finance, crypto, health, tech, entertainment)
  - RTL variant templates for Arabic / Urdu
  - Static site generation: post pages, index, sitemap.xml, robots.txt, ads.txt
  - Full site build to /sites/site-NNN/ directory structure
  - DB migration: adds platform / cloudflare_account_id / github_path / site_url columns

Blog structure per site:
  /sites/site-NNN/
      index.html          homepage — latest 10 posts
      /posts/             individual post HTML files
      sitemap.xml         auto-generated
      robots.txt
      ads.txt
"""

import sys
import re
import json
import logging
import hashlib
import sqlite3
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, field

# ── Path bootstrap ──────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent.parent.resolve()
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

SITES_DIR = BASE_DIR / "sites"
LOGS_DIR  = BASE_DIR / "logs"

# ── Logging ─────────────────────────────────────────────────────────────────────
_log = logging.getLogger("static_site_generator")
_log.setLevel(logging.INFO)
if not _log.handlers:
    _fh = logging.FileHandler(LOGS_DIR / "activity.log", encoding="utf-8")
    _fh.setFormatter(logging.Formatter("%(asctime)s [SSG] %(levelname)s %(message)s"))
    _log.addHandler(_fh)

# ── RTL languages ───────────────────────────────────────────────────────────────
RTL_LANGUAGES = {"ar", "ur"}

# ── Niche → template group mapping ─────────────────────────────────────────────
NICHE_TEMPLATE_GROUP = {
    "finance":        "finance",
    "investing":      "finance",
    "crypto":         "crypto",
    "blockchain":     "crypto",
    "health":         "health",
    "weight_loss":    "health",
    "food":           "health",
    "tech":           "tech",
    "gaming":         "tech",
    "gadgets":        "tech",
    "entertainment":  "entertainment",
    "celebrity":      "entertainment",
    "sports":         "entertainment",
    "movies_tv":      "entertainment",
    "breaking_news":  "entertainment",
    "viral":          "entertainment",
    "adult":          "entertainment",
}

# ── Niche style sets ────────────────────────────────────────────────────────────
NICHE_STYLES = {
    "finance": {
        "primary":       "#1a3a5c",
        "secondary":     "#2c5f8a",
        "accent":        "#f0a500",
        "bg":            "#f8f9fa",
        "text":          "#1c1c1c",
        "font":          "'Inter', 'Segoe UI', sans-serif",
        "heading_font":  "'Merriweather', 'Georgia', serif",
        "card_bg":       "#ffffff",
        "border":        "#d0d7de",
        "cat_color":     "#1a3a5c",
        "hero_overlay":  "rgba(10,30,55,0.72)",
    },
    "crypto": {
        "primary":       "#0d1117",
        "secondary":     "#161b22",
        "accent":        "#00d4aa",
        "bg":            "#0d1117",
        "text":          "#e6edf3",
        "font":          "'Inter', 'Segoe UI', sans-serif",
        "heading_font":  "'Merriweather', 'Georgia', serif",
        "card_bg":       "#161b22",
        "border":        "#30363d",
        "cat_color":     "#00d4aa",
        "hero_overlay":  "rgba(0,0,0,0.78)",
    },
    "health": {
        "primary":       "#2d6a4f",
        "secondary":     "#40916c",
        "accent":        "#f4845f",
        "bg":            "#ffffff",
        "text":          "#2c3e50",
        "font":          "'Inter', 'Segoe UI', sans-serif",
        "heading_font":  "'Merriweather', 'Georgia', serif",
        "card_bg":       "#f8fffe",
        "border":        "#d8f3dc",
        "cat_color":     "#2d6a4f",
        "hero_overlay":  "rgba(20,65,45,0.70)",
    },
    "tech": {
        "primary":       "#0066cc",
        "secondary":     "#004a99",
        "accent":        "#ff6600",
        "bg":            "#ffffff",
        "text":          "#1a1a1a",
        "font":          "'Inter', 'Segoe UI', sans-serif",
        "heading_font":  "'Merriweather', 'Georgia', serif",
        "card_bg":       "#f5f8ff",
        "border":        "#dde8f5",
        "cat_color":     "#0066cc",
        "hero_overlay":  "rgba(0,50,110,0.70)",
    },
    "entertainment": {
        "primary":       "#c1121f",
        "secondary":     "#1d3557",
        "accent":        "#f4a261",
        "bg":            "#ffffff",
        "text":          "#1c1c1c",
        "font":          "'Inter', 'Segoe UI', sans-serif",
        "heading_font":  "'Merriweather', 'Georgia', serif",
        "card_bg":       "#fff8f8",
        "border":        "#ffddd9",
        "cat_color":     "#c1121f",
        "hero_overlay":  "rgba(80,10,15,0.72)",
    },
}

def get_niche_styles(niche: str) -> Dict[str, str]:
    group = NICHE_TEMPLATE_GROUP.get(niche, "entertainment")
    return NICHE_STYLES[group]


# ── Per-blog unique accent colors ───────────────────────────────────────────────
_NICHE_ACCENT_PALETTES: Dict[str, List[str]] = {
    "crypto":        ["#00ff88","#00e5ff","#b44aff","#ff6b35","#ffd700","#00ffcc","#ff3cac","#7b2fff"],
    "finance":       ["#c8000a","#1a6ba0","#e8a000","#2e7d32","#7b1fa2","#00695c","#c62828","#1565c0"],
    "health":        ["#38a169","#e53e3e","#d69e2e","#3182ce","#805ad5","#00b5d8","#ed8936","#48bb78"],
    "tech":          ["#ff4500","#0070f3","#7928ca","#00b4d8","#06d6a0","#ffd60a","#ef233c","#3a86ff"],
    "entertainment": ["#e31c5f","#ff6b6b","#feca57","#48dbfb","#ff9ff3","#54a0ff","#5f27cd","#00d2d3"],
}

def get_blog_accent_color(slug: str, niche_group: str) -> str:
    """Return a unique accent color for this blog, derived from its slug."""
    import hashlib as _hl
    seed = int(_hl.md5(slug.encode()).hexdigest(), 16)
    palette = _NICHE_ACCENT_PALETTES.get(niche_group, _NICHE_ACCENT_PALETTES["tech"])
    return palette[seed % len(palette)]

def get_blog_layout_variant(slug: str) -> int:
    """Return 0, 1, or 2 — layout variant for this blog, consistent per slug."""
    import hashlib as _hl
    seed = int(_hl.md5((slug + "_v").encode()).hexdigest(), 16)
    return seed % 3


def _get_onesignal_app_id() -> str:
    """Return OneSignal App ID from config, or '' if not configured yet."""
    try:
        from modules.config_manager import get as cfg_get
        return cfg_get("onesignal_app_id", "")
    except Exception:
        return ""


def extract_key_takeaways(body_html: str, n: int = 3) -> List[str]:
    """
    Extract n key takeaway sentences from post body HTML.
    Strips tags, splits into sentences, picks the clearest ones.
    Falls back to meaningful topic-neutral summaries if content is sparse.
    """
    import re as _re
    # Strip HTML tags and collapse whitespace
    text = _re.sub(r'<[^>]+>', ' ', body_html)
    text = _re.sub(r'\s+', ' ', text).strip()
    # Split on sentence-ending punctuation
    raw_sentences = _re.split(r'(?<=[.!?])\s+', text)
    # Filter: must start with capital, be > 60 chars, not be a question
    good = [
        s.strip() for s in raw_sentences
        if len(s.strip()) > 60
        and s.strip()[:1].isupper()
        and not s.strip().endswith('?')
        and not s.strip().startswith(('Note:', 'Source:', 'Disclaimer', 'FAQ'))
    ]
    # Prefer sentences from the first half (intro is most informative)
    half = max(n, len(good) // 2)
    candidates = good[:half] if len(good) > n else good
    # Truncate each to a readable length
    result = [s[:160].rstrip(',') + ('.' if not s[:160].endswith('.') else '') for s in candidates[:n]]
    # Pad with generic fallbacks if needed
    fallbacks = [
        "Verified data and expert analysis are included throughout this article.",
        "Practical tips and actionable insights are covered in detail.",
        "Key statistics and real-world examples support every point made.",
    ]
    while len(result) < n:
        result.append(fallbacks[len(result) % len(fallbacks)])
    return result


def get_article_image_url(slug: str, niche: str = "", width: int = 1200, height: int = 628) -> str:
    """
    Return a consistent, niche-relevant image URL for an article.
    Uses curated Unsplash photo IDs per niche — real photography, free CDN.
    The slug deterministically selects from the niche pool so the same
    article always gets the same image.
    """
    import hashlib

    # Curated Unsplash photo IDs per niche group (6 per group for variety)
    _NICHE_PHOTOS: Dict[str, List[str]] = {
        "crypto": [
            "photo-1639762681057-408e52192e55",  # Bitcoin coins
            "photo-1518546305927-5a555bb7020d",  # Single Bitcoin
            "photo-1622630998477-20aa696ecb05",  # Crypto charts
            "photo-1642790551116-04d12ee08ddb",  # Blockchain nodes
            "photo-1621504450181-5d356f61d307",  # Crypto trading
            "photo-1605792657660-596af9009e82",  # Ethereum coin
        ],
        "finance": [
            "photo-1579621970563-ebec7560ff3e",  # Dollar bills
            "photo-1611974789855-9c2a0a7236a3",  # Stock chart
            "photo-1563986768609-322da13575f3",  # Finance planning
            "photo-1554224155-6726b3ff858f",      # Savings coins
            "photo-1611532736597-de2d4265fba3",  # Investment portfolio
            "photo-1559526324-593bc073d938",      # Bank/finance
        ],
        "health": [
            "photo-1571019613454-1cb2f99b2d8b",  # Running/fitness
            "photo-1490645935967-10de6ba17061",  # Healthy food spread
            "photo-1512621776951-a57141f2eefd",  # Salad bowl
            "photo-1476480862126-209bfaa8edc8",  # Outdoor running
            "photo-1498837167922-ddd27525d352",  # Healthy meal
            "photo-1544367567-0f2fcb009e0b",      # Yoga/wellness
        ],
        "tech": [
            "photo-1518770660439-4636190af475",  # Circuit board
            "photo-1551650975-87deedd944c3",      # Smartphone setup
            "photo-1526374965328-7f61d4dc18c5",  # Code on screen
            "photo-1467232004584-a241de8bcf5d",  # Laptop workspace
            "photo-1488590528505-98d2b5aba04b",  # Tech laptop
            "photo-1550745165-9bc0b252726f",      # Gaming/tech
        ],
        "entertainment": [
            "photo-1603190287605-e6ade32fa852",  # Cinema seats
            "photo-1493711662062-fa541adb3fc8",  # Gaming setup
            "photo-1470229722913-7c0e2dbbafd3",  # Concert crowd
            "photo-1505236858219-8359eb29e329",  # Music headphones
            "photo-1540575467063-178a50c2df87",  # Stage lights
            "photo-1516035069371-29a1b244cc32",  # Camera/photography
        ],
    }

    niche_group = NICHE_TEMPLATE_GROUP.get(niche, "entertainment")
    photos = _NICHE_PHOTOS.get(niche_group, _NICHE_PHOTOS["tech"])
    seed_num = int(hashlib.md5(slug.encode()).hexdigest(), 16)
    photo_id = photos[seed_num % len(photos)]
    return f"https://images.unsplash.com/{photo_id}?w={width}&h={height}&fit=crop&auto=format&q=80"


# ── Common CSS (injected into every template) ───────────────────────────────────
_COMMON_CSS = """
/* ── Reset ─────────────────────────────────────────────────────────────────── */
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
html{scroll-behavior:smooth;-webkit-text-size-adjust:100%;font-size:16px}
body{font-family:var(--font);background:var(--bg);color:var(--text);line-height:1.75;-webkit-font-smoothing:antialiased}
img{max-width:100%;height:auto;display:block}
a{color:var(--accent);transition:color .18s}

/* ── Layout ─────────────────────────────────────────────────────────────────── */
.wrapper{max-width:1200px;margin:0 auto;padding:0 24px}
.wrapper-narrow{max-width:860px;margin:0 auto;padding:0 24px}

/* ── HEADER ─────────────────────────────────────────────────────────────────── */
.site-header{background:var(--primary);color:#fff;position:sticky;top:0;z-index:600;box-shadow:0 2px 12px rgba(0,0,0,.45)}
.header-accent-bar{height:3px;background:linear-gradient(90deg,var(--accent),var(--accent) 40%,rgba(255,255,255,.3))}
.header-inner{display:flex;align-items:center;justify-content:space-between;padding:12px 0;gap:16px;min-height:58px}
.site-brand{display:flex;align-items:center;gap:12px;text-decoration:none}
.site-brand-mark{width:34px;height:34px;background:var(--accent);border-radius:4px;display:flex;align-items:center;justify-content:center;font-family:var(--heading-font);font-weight:700;color:#000;font-size:.95rem;flex-shrink:0}
.site-title{color:#fff;font-family:var(--heading-font);font-size:1.35rem;font-weight:700;letter-spacing:-.3px;white-space:nowrap;line-height:1}
.site-title:hover{color:var(--accent)}
.header-right{display:flex;align-items:center;gap:8px}
.header-nav a{color:rgba(255,255,255,.75);text-decoration:none;font-size:.82rem;font-weight:500;padding:5px 11px;border-radius:3px;transition:background .18s,color .18s;white-space:nowrap}
.header-nav a:hover{background:rgba(255,255,255,.12);color:#fff}
.header-search-btn{background:rgba(255,255,255,.1);border:1px solid rgba(255,255,255,.2);color:#fff;padding:6px 10px;border-radius:4px;cursor:pointer;font-size:.85rem;transition:background .18s}
.header-search-btn:hover{background:rgba(255,255,255,.2)}

/* ── CATEGORY NAV BAR ───────────────────────────────────────────────────────── */
.cat-nav{background:rgba(0,0,0,.22);border-bottom:1px solid rgba(255,255,255,.07)}
.cat-nav-inner{display:flex;gap:0;overflow-x:auto;scrollbar-width:none;-ms-overflow-style:none}
.cat-nav-inner::-webkit-scrollbar{display:none}
.cat-nav-link{color:rgba(255,255,255,.72);text-decoration:none;font-size:.76rem;font-weight:600;padding:9px 15px;white-space:nowrap;text-transform:uppercase;letter-spacing:.07em;border-bottom:3px solid transparent;transition:all .18s;display:block}
.cat-nav-link:hover,.cat-nav-link.active{color:#fff;border-bottom-color:var(--accent)}

/* ── BREAKING NEWS TICKER ───────────────────────────────────────────────────── */
.ticker-bar{background:var(--accent);overflow:hidden;display:flex;align-items:center;height:36px}
.ticker-label{padding:0 16px;height:100%;display:flex;align-items:center;font-size:.72rem;font-weight:800;letter-spacing:.1em;text-transform:uppercase;flex-shrink:0;white-space:nowrap;background:rgba(0,0,0,.22);color:#fff}
.ticker-track-wrap{overflow:hidden;flex:1;cursor:pointer}
.ticker-track{display:flex;animation:tickerScroll 36s linear infinite;width:max-content}
.ticker-track:hover{animation-play-state:paused}
.ticker-sep{padding:0 18px;opacity:.45;color:currentColor;font-size:.85rem}
.ticker-item a{color:#000;font-weight:600;font-size:.82rem;text-decoration:none;white-space:nowrap;transition:opacity .18s}
.ticker-item a:hover{opacity:.75;text-decoration:underline}
@keyframes tickerScroll{from{transform:translateX(0)}to{transform:translateX(-50%)}}

/* ── HERO SECTION ───────────────────────────────────────────────────────────── */
.hero{position:relative;overflow:hidden;min-height:62vh;display:flex;align-items:flex-end;background:var(--secondary)}
.hero-bg{position:absolute;inset:0;width:100%;height:100%;object-fit:cover;z-index:0;transform:scale(1.03);transition:transform 8s ease}
.hero:hover .hero-bg{transform:scale(1)}
.hero-gradient{position:absolute;inset:0;background:linear-gradient(to top,rgba(0,0,0,.85) 0%,rgba(0,0,0,.5) 50%,rgba(0,0,0,.15) 100%);z-index:1}
.hero-content{position:relative;z-index:2;padding:48px 24px 52px;max-width:1200px;margin:0 auto;width:100%}
.hero-badge{display:inline-flex;align-items:center;background:var(--accent);color:#000;font-size:.68rem;font-weight:800;text-transform:uppercase;letter-spacing:.1em;padding:4px 12px;border-radius:20px;margin-bottom:16px;gap:6px}
.hero-badge-dot{width:5px;height:5px;background:#000;border-radius:50%;animation:pulse 1.5s infinite}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.35}}
.hero-title{font-family:var(--heading-font);font-size:clamp(1.8rem,4.5vw,3.2rem);line-height:1.15;color:#fff;margin-bottom:16px;max-width:820px;text-shadow:0 2px 8px rgba(0,0,0,.45);letter-spacing:-.02em}
.hero-excerpt{color:rgba(255,255,255,.85);font-size:1.05rem;line-height:1.65;max-width:640px;margin-bottom:24px;text-shadow:0 1px 3px rgba(0,0,0,.4)}
.hero-meta{font-size:.8rem;color:rgba(255,255,255,.65);margin-bottom:20px;display:flex;gap:12px;align-items:center;flex-wrap:wrap}
.hero-meta-sep{opacity:.4}
.hero-btn{display:inline-flex;align-items:center;gap:8px;background:var(--accent);color:#000;text-decoration:none;font-weight:700;font-size:.9rem;padding:11px 24px;border-radius:4px;transition:transform .2s,box-shadow .2s;box-shadow:0 4px 12px rgba(0,0,0,.35)}
.hero-btn:hover{transform:translateY(-2px);box-shadow:0 7px 20px rgba(0,0,0,.45);color:#000}
.hero-btn-arrow{font-size:1.1rem;transition:transform .2s}
.hero-btn:hover .hero-btn-arrow{transform:translateX(3px)}

/* ── FEATURED SPLIT (2 secondary cards) ────────────────────────────────────── */
.featured-split{display:grid;grid-template-columns:1fr 1fr;gap:3px;margin:3px 0;background:var(--border)}
.split-card{position:relative;overflow:hidden;aspect-ratio:16/9;background:var(--secondary)}
.split-card img{width:100%;height:100%;object-fit:cover;transition:transform .45s ease}
.split-card:hover img{transform:scale(1.06)}
.split-card-overlay{position:absolute;inset:0;background:linear-gradient(to top,rgba(0,0,0,.78) 0%,transparent 55%);transition:background .3s}
.split-card:hover .split-card-overlay{background:linear-gradient(to top,rgba(0,0,0,.88) 0%,rgba(0,0,0,.15) 70%)}
.split-card-body{position:absolute;bottom:0;left:0;right:0;padding:18px 16px}
.split-card-badge{display:inline-block;background:var(--accent);color:#000;font-size:.63rem;font-weight:800;text-transform:uppercase;letter-spacing:.08em;padding:2px 9px;border-radius:20px;margin-bottom:8px}
.split-card-title{font-family:var(--heading-font);font-size:1.02rem;line-height:1.3;color:#fff;text-decoration:none;display:block;text-shadow:0 1px 4px rgba(0,0,0,.5)}
.split-card-title:hover{color:var(--accent)}
.split-card-meta{font-size:.73rem;color:rgba(255,255,255,.6);margin-top:7px}

/* ── SECTION LABELS ─────────────────────────────────────────────────────────── */
.section-block{margin:40px 0}
.section-label{display:flex;align-items:center;gap:14px;margin-bottom:22px}
.section-label-text{font-family:var(--heading-font);font-size:1rem;font-weight:700;color:var(--primary);text-transform:uppercase;letter-spacing:.08em;white-space:nowrap}
.section-label-line{flex:1;height:1px;background:var(--border)}
.section-label-accent{width:32px;height:3px;background:var(--accent);border-radius:2px;flex-shrink:0}

/* ── POST CARDS ─────────────────────────────────────────────────────────────── */
.post-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:28px}
.post-card{background:var(--card-bg,#fff);border-radius:6px;overflow:hidden;display:flex;flex-direction:column;transition:box-shadow .22s,transform .22s;border:1px solid transparent}
.post-card:hover{box-shadow:0 8px 32px rgba(0,0,0,.13);transform:translateY(-4px);border-color:var(--border)}
.post-card-img-wrap{overflow:hidden;aspect-ratio:16/9;background:linear-gradient(135deg,var(--primary),var(--secondary));position:relative}
.post-card-img-wrap img{width:100%;height:100%;object-fit:cover;display:block;transition:transform .4s ease}
.post-card:hover .post-card-img-wrap img{transform:scale(1.07)}
.post-card-img-wrap .placeholder-overlay{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;color:rgba(255,255,255,.25);font-size:2.5rem}
.post-card-body{padding:18px;flex:1;display:flex;flex-direction:column;gap:9px}
.cat-badge{display:inline-block;background:var(--cat-color,var(--primary));color:#fff;font-size:.64rem;font-weight:800;text-transform:uppercase;letter-spacing:.09em;padding:3px 10px;border-radius:20px;width:fit-content;line-height:1.4}
.post-card-title{font-family:var(--heading-font);font-size:1.05rem;line-height:1.42;color:var(--text);margin:0}
.post-card-title a{color:inherit;text-decoration:none;transition:color .18s;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.post-card-title a:hover{color:var(--accent)}
.post-card-excerpt{font-size:.84rem;color:#777;line-height:1.55;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;flex:1}
.card-meta{font-size:.73rem;color:#aaa;margin-top:auto;display:flex;gap:8px;align-items:center;padding-top:10px;border-top:1px solid var(--border)}
.card-meta-dot{opacity:.4;font-size:.6rem}
.card-read-time{display:inline-flex;align-items:center;gap:4px}
.card-read-time::before{content:'';font-size:.7rem}

/* ── AD SLOTS ───────────────────────────────────────────────────────────────── */
.ad-unit{text-align:center;padding:12px 0;min-height:12px}
.ad-unit-label{font-size:.65rem;text-transform:uppercase;letter-spacing:.1em;color:#ccc;margin-bottom:4px}
.ad-sticky-footer{position:fixed;bottom:0;left:0;right:0;z-index:990;background:rgba(12,12,12,.95);text-align:center;padding:6px 48px;backdrop-filter:blur(8px)}
.close-sticky{position:absolute;right:14px;top:50%;transform:translateY(-50%);color:rgba(255,255,255,.6);background:none;border:1px solid rgba(255,255,255,.2);font-size:1rem;cursor:pointer;line-height:1;padding:3px 8px;border-radius:3px;transition:all .18s}
.close-sticky:hover{background:rgba(255,255,255,.1);color:#fff}

/* ── COOKIE BANNER ──────────────────────────────────────────────────────────── */
#cookie-banner{position:fixed;bottom:0;left:0;right:0;background:rgba(17,17,17,.97);color:#ccc;padding:14px 24px;display:none;align-items:center;justify-content:space-between;z-index:9998;font-size:.85rem;gap:14px;flex-wrap:wrap;backdrop-filter:blur(10px);border-top:1px solid rgba(255,255,255,.08)}
#cookie-banner a{color:var(--accent)}
#cookie-accept{background:var(--accent);color:#000;border:none;padding:8px 20px;border-radius:4px;cursor:pointer;font-weight:700;white-space:nowrap;font-size:.85rem;transition:opacity .18s}
#cookie-accept:hover{opacity:.85}

/* ── ADULT GATE ─────────────────────────────────────────────────────────────── */
.adult-gate{position:fixed;inset:0;background:rgba(0,0,0,.97);z-index:99999;display:flex;align-items:center;justify-content:center;flex-direction:column;color:#fff;text-align:center;padding:24px}
.adult-gate h2{font-size:1.8rem;margin-bottom:14px;font-family:var(--heading-font)}
.adult-gate p{margin-bottom:24px;opacity:.75;max-width:520px;line-height:1.65}
.adult-gate-btn{background:var(--accent);color:#000;border:none;padding:14px 32px;font-size:1rem;border-radius:5px;cursor:pointer;margin:5px;font-weight:700}

/* ── ARTICLE PAGE ───────────────────────────────────────────────────────────── */
.reading-progress{position:fixed;top:0;left:0;width:0%;height:3px;background:linear-gradient(90deg,var(--accent),rgba(255,255,255,.6));z-index:9999;transition:width .08s linear}
.breadcrumb{font-size:.78rem;color:#aaa;padding:14px 0;display:flex;gap:6px;align-items:center;flex-wrap:wrap}
.breadcrumb a{color:#aaa;text-decoration:none;transition:color .18s}
.breadcrumb a:hover{color:var(--accent)}
.breadcrumb-sep{opacity:.4}
.article-hero-img{width:100%;aspect-ratio:21/9;object-fit:cover;display:block;margin-bottom:6px}
.article-img-caption{font-size:.75rem;color:#aaa;text-align:center;padding:6px 0 20px;font-style:italic;border-bottom:1px solid var(--border);margin-bottom:24px}
.article-header{padding:20px 0 18px}
.article-header .cat-badge{margin-bottom:14px}
.article-title{font-family:var(--heading-font);font-size:clamp(1.7rem,4vw,2.8rem);line-height:1.18;color:var(--text);margin-bottom:18px;letter-spacing:-.025em}
.article-meta{font-size:.82rem;color:#999;display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin-bottom:20px;padding-bottom:18px;border-bottom:1px solid var(--border)}
.article-meta-sep{opacity:.4;font-size:.65rem}
.article-meta strong{color:var(--text);font-weight:600}
.article-layout{display:grid;grid-template-columns:minmax(0,1fr) 308px;gap:48px;align-items:start;margin-top:8px}
.article-body{min-width:0}
.article-body p{font-size:1.05rem;line-height:1.88;margin-bottom:1.4em;color:var(--text)}
.article-body h2{font-family:var(--heading-font);font-size:1.55rem;color:var(--primary);margin:2.2em 0 .75em;line-height:1.28;padding-bottom:10px;border-bottom:2px solid var(--border)}
.article-body h3{font-family:var(--heading-font);font-size:1.2rem;color:var(--secondary);margin:1.8em 0 .6em;line-height:1.3}
.article-body h4{font-family:var(--heading-font);font-size:1rem;margin:1.4em 0 .5em;font-weight:700}
.article-body ul,.article-body ol{margin:0 0 1.4em 1.65em}
.article-body li{margin-bottom:.55em;font-size:1.02rem;line-height:1.8}
.article-body strong{font-weight:700;color:var(--primary)}
.article-body em{font-style:italic;color:var(--secondary)}
.article-body a{color:var(--accent);text-decoration:underline;text-underline-offset:2px}
.article-body blockquote{border-left:5px solid var(--accent);padding:18px 22px;margin:28px 0;background:linear-gradient(135deg,rgba(0,0,0,.03),rgba(0,0,0,.01));font-style:italic;font-size:1.18rem;line-height:1.75;border-radius:0 6px 6px 0;position:relative}
.article-body blockquote::before{content:'\\201C';font-size:4rem;color:var(--accent);opacity:.2;position:absolute;top:-10px;left:12px;font-family:Georgia,serif;line-height:1}
.article-body blockquote p{margin:0;color:var(--secondary)}
.article-body img{border-radius:6px;margin:20px 0;box-shadow:0 4px 16px rgba(0,0,0,.1)}
.article-body hr{border:none;border-top:2px solid var(--border);margin:2em 0}
.article-body table{width:100%;border-collapse:collapse;margin-bottom:1.4em;font-size:.92rem}
.article-body th{background:var(--primary);color:#fff;padding:10px 14px;text-align:left;font-family:var(--heading-font);font-weight:600}
.article-body td{padding:9px 14px;border-bottom:1px solid var(--border)}
.article-body tr:nth-child(even) td{background:rgba(0,0,0,.02)}

/* ── ARTICLE SIDEBAR ────────────────────────────────────────────────────────── */
.article-sidebar{position:sticky;top:80px}
.sidebar-box{background:var(--card-bg,#fff);border:1px solid var(--border);border-radius:6px;padding:20px;margin-bottom:20px;overflow:hidden}
.sidebar-box-title{font-family:var(--heading-font);font-size:.85rem;font-weight:700;color:var(--primary);text-transform:uppercase;letter-spacing:.08em;margin-bottom:16px;padding-bottom:10px;border-bottom:3px solid var(--accent);display:flex;align-items:center;gap:8px}
.trending-list{list-style:none;padding:0;margin:0}
.trending-item{display:flex;gap:12px;align-items:flex-start;padding:10px 0;border-bottom:1px solid var(--border)}
.trending-item:last-child{border-bottom:none;padding-bottom:0}
.trending-num{font-family:var(--heading-font);font-size:1.65rem;font-weight:700;color:var(--accent);line-height:1;min-width:30px;opacity:.6;flex-shrink:0}
.trending-link{font-size:.85rem;color:var(--text);text-decoration:none;line-height:1.45;font-weight:500;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;transition:color .18s}
.trending-link:hover{color:var(--accent)}
.topics-cloud{display:flex;flex-wrap:wrap;gap:7px}
.topic-tag{background:var(--border);color:var(--text);font-size:.76rem;padding:5px 12px;border-radius:20px;text-decoration:none;transition:all .18s;font-weight:500}
.topic-tag:hover{background:var(--accent);color:#000}

/* ── SHARE BAR ──────────────────────────────────────────────────────────────── */
.share-bar{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin:32px 0 24px;padding:18px 0;border-top:2px solid var(--border);border-bottom:1px solid var(--border)}
.share-label{font-size:.82rem;font-weight:700;color:var(--text);letter-spacing:.03em;text-transform:uppercase;margin-right:4px}
.share-btn{display:inline-flex;align-items:center;gap:6px;padding:8px 16px;border-radius:20px;font-size:.8rem;font-weight:600;text-decoration:none;cursor:pointer;border:none;transition:all .18s;line-height:1;letter-spacing:.02em}
.share-btn:hover{transform:translateY(-2px);box-shadow:0 4px 12px rgba(0,0,0,.2)}
.share-btn-twitter{background:#000;color:#fff}
.share-btn-facebook{background:#1877f2;color:#fff}
.share-btn-copy{background:var(--border);color:var(--text);border:1px solid var(--border)}
.share-btn-copy:hover{background:var(--accent);color:#000;border-color:var(--accent)}

/* ── DISCLOSURE & LEGAL ─────────────────────────────────────────────────────── */
.disclosure{background:rgba(0,0,0,.03);border-left:4px solid var(--accent);padding:12px 16px;font-size:.82rem;color:#777;margin:20px 0;border-radius:0 4px 4px 0;line-height:1.55}
.legal-footer-text{font-size:.77rem;color:#bbb;margin-top:28px;padding-top:14px;border-top:1px solid var(--border);line-height:1.6}
.legal-footer-text a{color:#bbb}

/* ── TAGS ───────────────────────────────────────────────────────────────────── */
.article-tags{margin-top:22px;display:flex;flex-wrap:wrap;gap:8px;align-items:center}
.tags-label{font-size:.78rem;font-weight:700;color:#999;letter-spacing:.04em;text-transform:uppercase;margin-right:4px}
.tag-pill{background:var(--border);color:#666;font-size:.76rem;padding:5px 13px;border-radius:20px;text-decoration:none;transition:all .18s;font-weight:500}
.tag-pill:hover{background:var(--accent);color:#000}

/* ── FOOTER ─────────────────────────────────────────────────────────────────── */
.site-footer{background:var(--primary);color:rgba(255,255,255,.72);margin-top:60px}
.footer-top{padding:48px 0 36px}
.footer-grid{display:grid;grid-template-columns:2fr 1fr 1fr 1fr;gap:36px;margin-bottom:36px}
.footer-logo{display:flex;align-items:center;gap:10px;margin-bottom:14px;text-decoration:none}
.footer-logo-mark{width:30px;height:30px;background:var(--accent);border-radius:3px;display:flex;align-items:center;justify-content:center;font-family:var(--heading-font);font-weight:700;color:#000;font-size:.85rem;flex-shrink:0}
.footer-logo-name{color:#fff;font-family:var(--heading-font);font-weight:700;font-size:1.1rem}
.footer-tagline{font-size:.83rem;line-height:1.65;opacity:.65;max-width:240px}
.footer-col-title{font-family:var(--heading-font);font-size:.82rem;font-weight:700;color:#fff;margin-bottom:14px;text-transform:uppercase;letter-spacing:.08em}
.footer-col ul{list-style:none;padding:0;margin:0;display:flex;flex-direction:column;gap:8px}
.footer-col ul li a{color:rgba(255,255,255,.58);text-decoration:none;font-size:.83rem;transition:color .18s}
.footer-col ul li a:hover{color:#fff}
.footer-divider{border:none;border-top:1px solid rgba(255,255,255,.1);margin:0}
.footer-bottom{padding:16px 0 32px;display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:10px}
.footer-copy{font-size:.76rem;opacity:.45}
.footer-legal-links{display:flex;gap:16px;flex-wrap:wrap}
.footer-legal-links a{color:rgba(255,255,255,.42);text-decoration:none;font-size:.75rem;transition:color .18s}
.footer-legal-links a:hover{color:#fff}

/* ── MAIN ───────────────────────────────────────────────────────────────────── */
main{padding:0 0 80px}

/* ── RTL ────────────────────────────────────────────────────────────────────── */
[dir=rtl]{text-align:right}
[dir=rtl] .article-body ul,[dir=rtl] .article-body ol{margin:0 1.65em 1.4em 0}
[dir=rtl] .article-body blockquote{border-left:none;border-right:5px solid var(--accent);border-radius:6px 0 0 6px}
[dir=rtl] .article-body blockquote::before{left:auto;right:12px}
[dir=rtl] .disclosure{border-left:none;border-right:4px solid var(--accent);border-radius:4px 0 0 4px}
[dir=rtl] .breadcrumb,[dir=rtl] .header-inner,[dir=rtl] .cat-nav-inner,[dir=rtl] .share-bar,[dir=rtl] .footer-bottom{flex-direction:row-reverse}
[dir=rtl] .reading-progress{left:auto;right:0}

/* ── RESPONSIVE ─────────────────────────────────────────────────────────────── */
@media(max-width:1080px){.footer-grid{grid-template-columns:1fr 1fr;gap:28px}.post-grid{grid-template-columns:repeat(2,1fr)}.featured-split{grid-template-columns:1fr}}
@media(max-width:860px){.article-layout{grid-template-columns:1fr}.article-sidebar{display:none}.article-hero-img{aspect-ratio:16/9}.post-grid{grid-template-columns:repeat(2,1fr)}}
@media(max-width:640px){.post-grid{grid-template-columns:1fr}.hero{min-height:50vh}.hero-title{font-size:1.65rem}.article-title{font-size:1.55rem}.wrapper{padding:0 16px}.header-inner{padding:10px 0}.footer-grid{grid-template-columns:1fr}.footer-bottom{flex-direction:column;text-align:center}#cookie-banner{flex-direction:column}}
@media(max-width:400px){.hero-title{font-size:1.35rem}.article-title{font-size:1.3rem}.cat-nav-link{padding:8px 11px}}

/* ── PRINT ──────────────────────────────────────────────────────────────────── */
@media print{.site-header,.site-footer,.ad-unit,.ad-sticky-footer,.ticker-bar,.cat-nav,.share-bar,.article-sidebar,.reading-progress,#cookie-banner{display:none!important}.article-layout{display:block!important}}

/* ── POST HERO (cinematic full-width, headline overlaid on image) ─────────── */
.post-hero{position:relative;width:100%;min-height:68vh;display:flex;align-items:flex-end;overflow:hidden;background:var(--secondary)}
.post-hero-bg{position:absolute;inset:0;width:100%;height:100%;object-fit:cover;z-index:0;transform:scale(1.04);transition:transform 8s ease}
.post-hero:hover .post-hero-bg{transform:scale(1)}
.post-hero-gradient{position:absolute;inset:0;background:linear-gradient(to top,rgba(0,0,0,.92) 0%,rgba(0,0,0,.52) 45%,rgba(0,0,0,.1) 100%);z-index:1}
.post-hero-inner{position:relative;z-index:2;width:100%;max-width:1200px;margin:0 auto;padding:40px 24px 56px}
.post-hero-cat{display:inline-flex;align-items:center;background:var(--accent);color:#000;font-size:.68rem;font-weight:800;text-transform:uppercase;letter-spacing:.1em;padding:4px 13px;border-radius:20px;margin-bottom:18px}
.post-hero-title{font-family:var(--heading-font);font-size:clamp(1.85rem,4.5vw,3.1rem);line-height:1.14;color:#fff;margin-bottom:16px;text-shadow:0 2px 10px rgba(0,0,0,.55);letter-spacing:-.025em;max-width:880px}
.post-hero-meta{font-size:.83rem;color:rgba(255,255,255,.72);display:flex;gap:12px;align-items:center;flex-wrap:wrap}
.post-hero-meta-sep{opacity:.4}

/* ── KEY TAKEAWAYS ──────────────────────────────────────────────────────────── */
.key-takeaways{border:2px solid var(--accent);border-radius:8px;padding:20px 24px;margin:28px 0;background:rgba(0,0,0,.02)}
.key-takeaways-hd{font-family:var(--heading-font);font-size:.8rem;font-weight:700;text-transform:uppercase;letter-spacing:.1em;color:var(--accent);margin-bottom:14px;display:flex;align-items:center;gap:8px}
.key-takeaways ul{list-style:none;padding:0;margin:0;display:flex;flex-direction:column;gap:9px}
.key-takeaways li{padding-left:22px;position:relative;font-size:.94rem;line-height:1.65;color:var(--text)}
.key-takeaways li::before{content:'✓';position:absolute;left:0;color:var(--accent);font-weight:700}

/* ── NEWSLETTER BOX (sidebar) ───────────────────────────────────────────────── */
.newsletter-box{background:linear-gradient(145deg,var(--primary),var(--secondary));border-radius:8px;padding:22px;color:#fff;margin-bottom:20px}
.newsletter-hd{font-family:var(--heading-font);font-size:.95rem;font-weight:700;color:#fff;margin-bottom:8px;line-height:1.3}
.newsletter-sub{font-size:.8rem;opacity:.75;margin-bottom:14px;line-height:1.55}
.newsletter-input{width:100%;padding:9px 12px;border:none;border-radius:4px;font-size:.84rem;margin-bottom:8px;color:#1a1a1a;outline:none}
.newsletter-btn{width:100%;background:var(--accent);color:#000;border:none;padding:9px;border-radius:4px;font-weight:700;font-size:.84rem;cursor:pointer;letter-spacing:.02em;transition:opacity .18s}
.newsletter-btn:hover{opacity:.88}

/* ── RELATED POSTS ──────────────────────────────────────────────────────────── */
.related-posts{margin:48px 0 0;padding-top:36px;border-top:2px solid var(--border)}
.related-posts-hd{font-family:var(--heading-font);font-size:1.05rem;font-weight:700;color:var(--primary);margin-bottom:22px;display:flex;align-items:center;gap:10px}
.related-posts-hd::before{content:'';display:block;width:4px;height:1.1em;background:var(--accent);border-radius:2px;flex-shrink:0}
.related-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:20px}
.related-card{display:flex;flex-direction:column;gap:10px;text-decoration:none;color:var(--text)}
.related-card-img{width:100%;aspect-ratio:16/9;object-fit:cover;border-radius:5px;display:block;transition:opacity .22s}
.related-card:hover .related-card-img{opacity:.88}
.related-card-title{font-size:.88rem;font-weight:600;line-height:1.42;color:var(--text);transition:color .18s;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.related-card:hover .related-card-title{color:var(--accent)}
.related-card-meta{font-size:.72rem;color:#aaa}

/* ── EDITOR PICKS (index page) ──────────────────────────────────────────────── */
.editor-strip{display:flex;flex-direction:column;gap:0}
.editor-item{display:flex;gap:16px;align-items:flex-start;text-decoration:none;color:var(--text);padding:14px 0;border-bottom:1px solid var(--border)}
.editor-item:last-child{border-bottom:none;padding-bottom:0}
.editor-item-img{width:96px;height:64px;object-fit:cover;border-radius:5px;flex-shrink:0}
.editor-item-body{flex:1;min-width:0}
.editor-item-badge{display:inline-block;font-size:.62rem;font-weight:800;text-transform:uppercase;letter-spacing:.08em;color:var(--accent);margin-bottom:5px}
.editor-item-title{font-size:.88rem;font-weight:600;line-height:1.42;color:var(--text);transition:color .18s;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.editor-item:hover .editor-item-title{color:var(--accent)}
.editor-item-meta{font-size:.72rem;color:#aaa;margin-top:4px}

/* ── SUBSCRIBE STRIP (index page) ───────────────────────────────────────────── */
.subscribe-strip{background:linear-gradient(135deg,var(--primary),var(--secondary));padding:36px 32px;margin:40px 0;border-radius:8px;display:flex;align-items:center;justify-content:space-between;gap:24px;flex-wrap:wrap}
.subscribe-strip-text h3{font-family:var(--heading-font);font-size:1.25rem;color:#fff;margin-bottom:6px}
.subscribe-strip-text p{font-size:.86rem;color:rgba(255,255,255,.72)}
.subscribe-strip-form{display:flex;gap:10px;flex-wrap:wrap}
.subscribe-input{padding:10px 16px;border:none;border-radius:4px;font-size:.88rem;min-width:240px;color:#1a1a1a;outline:none}
.subscribe-btn{background:var(--accent);color:#000;border:none;padding:10px 22px;border-radius:4px;font-weight:700;font-size:.88rem;cursor:pointer;white-space:nowrap;transition:opacity .18s}
.subscribe-btn:hover{opacity:.88}

/* ── RESPONSIVE (new additions) ─────────────────────────────────────────────── */
@media(max-width:860px){.post-hero{min-height:52vh}.related-grid{grid-template-columns:repeat(2,1fr)}.subscribe-strip{flex-direction:column}.subscribe-input{min-width:0;width:100%}}
@media(max-width:640px){.related-grid{grid-template-columns:1fr}.post-hero-title{font-size:1.65rem}.post-hero-inner{padding:28px 16px 44px}.editor-item-img{width:72px;height:50px}}
"""

# ── Post page Jinja2 template ───────────────────────────────────────────────────
_POST_TEMPLATE = """\
<!DOCTYPE html>
<html lang="{{ language }}"{% if rtl %} dir="rtl"{% endif %}>
<head>
<base href="{{ blog_url }}/">
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="description" content="{{ meta_desc | e }}">
<meta property="og:title" content="{{ title | e }}">
<meta property="og:description" content="{{ meta_desc | e }}">
<meta property="og:image" content="{{ featured_image_url | e }}">
<meta property="og:type" content="article">
<meta name="twitter:card" content="summary_large_image">
{% if is_adult %}<meta name="rating" content="adult">{% endif %}
<title>{{ title | e }}{% if blog_title %} — {{ blog_title | e }}{% endif %}</title>
<link rel="canonical" href="{{ canonical_url | e }}">
{{ hreflang_tags | safe }}
{{ schema_tag | safe }}
{{ faq_schema_tag | safe }}
{{ ad_head_code | safe }}
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Merriweather:ital,wght@0,400;0,700;1,400&family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet">
<style>
:root{
  --primary:{{ styles.primary }};
  --secondary:{{ styles.secondary }};
  --accent:{{ styles.accent }};
  --bg:{{ styles.bg }};
  --text:{{ styles.text }};
  --font:'Inter','Segoe UI',system-ui,sans-serif;
  --heading-font:'Merriweather','Georgia',serif;
  --card-bg:{{ styles.card_bg }};
  --border:{{ styles.border }};
  --cat-color:{{ styles.cat_color }};
  --hero-overlay:{{ styles.hero_overlay }};
}
{{ common_css | safe }}
</style>
</head>
<body>

<div class="reading-progress" id="readingProgress"></div>

{% if is_adult %}
<div id="adult-gate" class="adult-gate">
  <h2>18+ Content — Age Verification Required</h2>
  <p>This site contains adult content intended for adults aged 18 and older.<br>By entering you confirm you are of legal age in your jurisdiction.</p>
  <button class="adult-gate-btn" onclick="verifyAge()">I am 18 or older — Enter</button>
  <button class="adult-gate-btn" style="background:rgba(255,255,255,.12);color:#fff" onclick="location='https://www.google.com'">Leave</button>
</div>
{% endif %}

<div id="cookie-banner">
  <span>We use cookies to improve your experience and show relevant content. <a href="cookie-policy.html">Learn more</a></span>
  <button id="cookie-accept">Accept All</button>
</div>

<header class="site-header">
  <div class="header-accent-bar"></div>
  <div class="wrapper">
    <div class="header-inner">
      <a href="./" class="site-brand">
        <div class="site-brand-mark">{% if blog_title %}{{ blog_title[0] | upper }}{% else %}B{% endif %}</div>
        <span class="site-title">{{ blog_title | e }}</span>
      </a>
      <div class="header-right">
        <nav class="header-nav" aria-label="Site navigation">
          <a href="./">Home</a>
          <a href="about.html">About</a>
          <a href="contact.html">Contact</a>
        </nav>
      </div>
    </div>
  </div>
  <nav class="cat-nav" aria-label="Category navigation">
    <div class="wrapper">
      <div class="cat-nav-inner" id="catNavInner"></div>
    </div>
  </nav>
</header>

<div class="ad-unit" aria-label="Advertisement">{{ ad_slot_1 | safe }}</div>

<main>
  <div class="wrapper">
    <nav class="breadcrumb" aria-label="Breadcrumb">
      <a href="./">Home</a>
      <span class="breadcrumb-sep">›</span>
      {% if keywords and keywords|length > 0 %}
      <a href="./">{{ keywords[0] | e | title }}</a>
      <span class="breadcrumb-sep">›</span>
      {% endif %}
      <span aria-current="page">{{ title | e | truncate(50) }}</span>
    </nav>

    <article itemscope itemtype="https://schema.org/NewsArticle">

      <div class="post-hero">
        {% if featured_image_url %}
        <img src="{{ featured_image_url | e }}" alt="{{ title | e }}" class="post-hero-bg" width="1200" height="628" loading="eager" itemprop="image">
        {% endif %}
        <div class="post-hero-gradient"></div>
        <div class="post-hero-inner">
          {% if keywords and keywords|length > 0 %}
          <span class="post-hero-cat">{{ keywords[0] | e | upper }}</span>
          {% endif %}
          <h1 class="post-hero-title" itemprop="headline">{{ title | e }}</h1>
          <div class="post-hero-meta">
            <time itemprop="datePublished" datetime="{{ published_at }}">{{ published_at[:10] }}</time>
            <span class="post-hero-meta-sep">·</span>
            <span id="readingTimeDisplay">5 min read</span>
            <span class="post-hero-meta-sep">·</span>
            <span itemprop="author" itemscope itemtype="https://schema.org/Organization">
              By <strong itemprop="name">Editorial Team</strong>
            </span>
          </div>
        </div>
      </div>

      <div class="disclosure">{{ disclosure | safe }}</div>

      <div class="key-takeaways">
        <div class="key-takeaways-hd">&#9632; Key Takeaways</div>
        <ul id="keyTakeaways">
          {% for kt in key_takeaways %}
          <li>{{ kt | e }}</li>
          {% endfor %}
        </ul>
      </div>

      <div class="article-layout">
        <div class="article-body" id="articleBody" itemprop="articleBody">
          {{ body_html | safe }}

          <div class="ad-unit" aria-label="Advertisement">{{ ad_slot_3 | safe }}</div>

          <div class="share-bar">
            <span class="share-label">Share</span>
            <a class="share-btn share-btn-twitter"
               href="https://twitter.com/intent/tweet?url={{ canonical_url | replace('&','%26') }}&text={{ title | replace(' ','+') }}"
               target="_blank" rel="noopener noreferrer" aria-label="Share on Twitter">
               Twitter
            </a>
            <a class="share-btn share-btn-facebook"
               href="https://www.facebook.com/sharer/sharer.php?u={{ canonical_url | replace('&','%26') }}"
               target="_blank" rel="noopener noreferrer" aria-label="Share on Facebook">
               Facebook
            </a>
            <button class="share-btn share-btn-copy" id="copyLinkBtn" aria-label="Copy link">
              Copy Link
            </button>
          </div>

          {% if keywords %}
          <div class="article-tags">
            <span class="tags-label">Tags</span>
            {% for kw in keywords %}
            <a href="./" class="tag-pill">{{ kw | e }}</a>
            {% endfor %}
          </div>
          {% endif %}

          {% if related_posts %}
          <div class="related-posts">
            <div class="related-posts-hd">More Stories</div>
            <div class="related-grid">
              {% for rp in related_posts %}
              <a href="{% if rp.slug %}posts/{{ rp.slug }}.html{% else %}./{% endif %}" class="related-card">
                <img src="{{ rp.featured_image_url | e }}" alt="{{ rp.title | e }}" class="related-card-img" loading="lazy">
                <div class="related-card-title">{{ rp.title | e | truncate(80) }}</div>
                <div class="related-card-meta">{{ rp.published_at }} · Editorial Team</div>
              </a>
              {% endfor %}
            </div>
          </div>
          {% endif %}

          <div class="legal-footer-text">{{ legal_footer | safe }}</div>
        </div>

        <aside class="article-sidebar" aria-label="Sidebar">
          <div class="sidebar-box">
            <div class="sidebar-box-title">Trending Now</div>
            <ul class="trending-list" id="trendingSidebar">
              <li class="trending-item">
                <span class="trending-num">01</span>
                <a href="posts/{{ slug | e }}.html" class="trending-link">{{ title | e | truncate(65) }}</a>
              </li>
              {% for rp in related_posts[:3] %}
              <li class="trending-item">
                <span class="trending-num">{{ '%02d' | format(loop.index + 1) }}</span>
                <a href="{% if rp.slug %}posts/{{ rp.slug }}.html{% else %}./{% endif %}" class="trending-link">{{ rp.title | e | truncate(65) }}</a>
              </li>
              {% endfor %}
            </ul>
          </div>
          {% if keywords %}
          <div class="sidebar-box">
            <div class="sidebar-box-title">Topics</div>
            <div class="topics-cloud">
              {% for kw in keywords %}
              <a href="./" class="topic-tag">{{ kw | e }}</a>
              {% endfor %}
            </div>
          </div>
          {% endif %}
          <div class="newsletter-box">
            <div class="newsletter-hd">Stay Informed</div>
            <p class="newsletter-sub">Get the latest stories delivered directly to your inbox — free.</p>
            <input type="email" class="newsletter-input" placeholder="Your email address" aria-label="Email address">
            <button class="newsletter-btn">Subscribe Free</button>
          </div>
          <div class="ad-unit" aria-label="Advertisement">{{ ad_slot_3 | safe }}</div>
        </aside>
      </div>
    </article>
  </div>
</main>

<div class="ad-sticky-footer" id="stickyAd">
  <button class="close-sticky" onclick="document.getElementById('stickyAd').remove()" aria-label="Close">&#x2715;</button>
  {{ ad_slot_5 | safe }}
</div>

<footer class="site-footer">
  <div class="footer-top">
    <div class="wrapper">
      <div class="footer-grid">
        <div class="footer-col">
          <a href="./" class="footer-logo">
            <div class="footer-logo-mark">{% if blog_title %}{{ blog_title[0] | upper }}{% else %}B{% endif %}</div>
            <span class="footer-logo-name">{{ blog_title | e }}</span>
          </a>
          <p class="footer-tagline">Delivering news, analysis and insights. AI-assisted editorial content reviewed for accuracy.</p>
        </div>
        <div class="footer-col">
          <div class="footer-col-title">Company</div>
          <ul>
            <li><a href="about.html">About Us</a></li>
            <li><a href="contact.html">Contact</a></li>
            <li><a href="affiliate-disclosure.html">Disclosure</a></li>
          </ul>
        </div>
        <div class="footer-col">
          <div class="footer-col-title">Legal</div>
          <ul>
            <li><a href="privacy-policy.html">Privacy Policy</a></li>
            <li><a href="terms-of-service.html">Terms of Service</a></li>
            <li><a href="cookie-policy.html">Cookie Policy</a></li>
            <li><a href="dmca.html">DMCA</a></li>
          </ul>
        </div>
        <div class="footer-col">
          <div class="footer-col-title">Follow</div>
          <ul>
            <li><a href="./" rel="noopener">Twitter / X</a></li>
            <li><a href="./" rel="noopener">Pinterest</a></li>
            <li><a href="./" rel="noopener">Telegram</a></li>
            <li><a href="./" rel="noopener">Tumblr</a></li>
          </ul>
        </div>
      </div>
    </div>
  </div>
  <hr class="footer-divider">
  <div class="wrapper">
    <div class="footer-bottom">
      <span class="footer-copy">&copy; {{ year }} {{ blog_title | e }}. AI-assisted content. All affiliate links disclosed.</span>
      <div class="footer-legal-links">
        <a href="privacy-policy.html">Privacy</a>
        <a href="terms-of-service.html">Terms</a>
        <a href="cookie-policy.html">Cookies</a>
        <a href="contact.html">Contact</a>
      </div>
    </div>
  </div>
</footer>

<script>
(function(){
  'use strict';

  // Cookie banner
  var ckBanner=document.getElementById('cookie-banner');
  if(ckBanner&&!localStorage.getItem('ck')){ckBanner.style.display='flex';}
  var ckBtn=document.getElementById('cookie-accept');
  if(ckBtn){ckBtn.onclick=function(){localStorage.setItem('ck','1');if(ckBanner)ckBanner.style.display='none';};}

  // Reading progress
  var prog=document.getElementById('readingProgress');
  if(prog){
    var _raf;
    window.addEventListener('scroll',function(){
      if(_raf)return;
      _raf=requestAnimationFrame(function(){
        _raf=null;
        var scrolled=window.scrollY;
        var total=Math.max(document.body.scrollHeight,document.documentElement.scrollHeight)-document.documentElement.clientHeight;
        prog.style.width=total>0?Math.min(100,(scrolled/total)*100)+'%':'0%';
      });
    },{passive:true});
  }

  // Reading time
  var body=document.getElementById('articleBody');
  var rtDisplay=document.getElementById('readingTimeDisplay');
  if(body&&rtDisplay){
    var words=body.innerText.trim().split(/\\s+/).filter(function(w){return w.length>0;}).length;
    var mins=Math.max(1,Math.round(words/220));
    rtDisplay.textContent=mins+' min read';
  }

  // Copy link
  var copyBtn=document.getElementById('copyLinkBtn');
  if(copyBtn){
    copyBtn.onclick=function(){
      if(navigator.clipboard&&navigator.clipboard.writeText){
        navigator.clipboard.writeText(window.location.href).then(function(){
          copyBtn.textContent='Copied!';
          setTimeout(function(){copyBtn.textContent='Copy Link';},2000);
        });
      } else {
        var ta=document.createElement('textarea');
        ta.value=window.location.href;
        document.body.appendChild(ta);ta.select();
        document.execCommand('copy');
        document.body.removeChild(ta);
        copyBtn.textContent='Copied!';
        setTimeout(function(){copyBtn.textContent='Copy Link';},2000);
      }
    };
  }

  // Category nav
  var CATS={finance:['Markets','Investing','Economy','Crypto','Personal Finance'],crypto:['Bitcoin','Ethereum','DeFi','NFTs','Markets','Web3'],health:['Nutrition','Fitness','Wellness','Medical','Mental Health'],tech:['AI','Gadgets','Software','Science','Cybersecurity'],entertainment:['Movies','Celebrity','Music','Sports','TV']};
  var cats=CATS['{{ niche }}']||CATS.tech;
  var nav=document.getElementById('catNavInner');
  if(nav){
    cats.forEach(function(c){
      var a=document.createElement('a');
      a.href='/';a.className='cat-nav-link';a.textContent=c;
      nav.appendChild(a);
    });
  }

  // Scroll-triggered ad
  var _scrollAd=false;
  window.addEventListener('scroll',function(){
    if(!_scrollAd&&(window.scrollY+window.innerHeight)/document.documentElement.scrollHeight>=0.70){
      _scrollAd=true;{{ ad_slot_4_js | safe }}
    }
  },{passive:true});

  // Exit intent
  var _exitAd=false;
  document.addEventListener('mouseleave',function(e){
    if(!_exitAd&&e.clientY<10){_exitAd=true;{{ ad_slot_6_js | safe }}}
  });

  {% if is_adult %}
  function verifyAge(){sessionStorage.setItem('av','1');var g=document.getElementById('adult-gate');if(g)g.style.display='none';}
  if(sessionStorage.getItem('av')){var g=document.getElementById('adult-gate');if(g)g.style.display='none';}
  window.verifyAge=verifyAge;
  {% endif %}
})();
</script>
{% if onesignal_app_id %}<script src="https://cdn.onesignal.com/sdks/web/v16/OneSignalSDK.page.js" defer></script><script>window.OneSignalDeferred=window.OneSignalDeferred||[];OneSignalDeferred.push(async function(OneSignal){await OneSignal.init({appId:"{{ onesignal_app_id }}",notifyButton:{enable:true}});});</script>{% endif %}
<!-- Cloudflare Web Analytics --><script defer src='https://static.cloudflareinsights.com/beacon.min.js' data-cf-beacon='{"token": "be17bfc005774526803b0ef32264a47e"}'></script><!-- End Cloudflare Web Analytics -->
</body>
</html>"""

# ── Index page Jinja2 template ──────────────────────────────────────────────────
_INDEX_TEMPLATE = """\
<!DOCTYPE html>
<html lang="{{ language }}"{% if rtl %} dir="rtl"{% endif %}>
<head>
<base href="{{ blog_url }}/">
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="description" content="{{ meta_desc | e }}">
<meta property="og:title" content="{{ blog_title | e }}">
<meta property="og:description" content="{{ meta_desc | e }}">
{% if posts %}<meta property="og:image" content="{{ posts[0].get('featured_image_url','') | e }}">{% endif %}
<meta property="og:type" content="website">
<meta name="twitter:card" content="summary_large_image">
{% if is_adult %}<meta name="rating" content="adult">{% endif %}
<title>{{ blog_title | e }}</title>
<link rel="canonical" href="{{ blog_url | e }}">
{{ ad_head_code | safe }}
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Merriweather:ital,wght@0,400;0,700;1,400&family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet">
<style>
:root{
  --primary:{{ styles.primary }};
  --secondary:{{ styles.secondary }};
  --accent:{{ styles.accent }};
  --bg:{{ styles.bg }};
  --text:{{ styles.text }};
  --font:'Inter','Segoe UI',system-ui,sans-serif;
  --heading-font:'Merriweather','Georgia',serif;
  --card-bg:{{ styles.card_bg }};
  --border:{{ styles.border }};
  --cat-color:{{ styles.cat_color }};
  --hero-overlay:{{ styles.hero_overlay }};
}
{{ common_css | safe }}
</style>
</head>
<body>

{% if is_adult %}
<div id="adult-gate" class="adult-gate">
  <h2>18+ Content — Age Verification Required</h2>
  <p>This site contains adult content for adults aged 18+. By entering you confirm you are of legal age.</p>
  <button class="adult-gate-btn" onclick="verifyAge()">I am 18 or older — Enter</button>
  <button class="adult-gate-btn" style="background:rgba(255,255,255,.12);color:#fff" onclick="location='https://www.google.com'">Leave</button>
</div>
{% endif %}

<div id="cookie-banner">
  <span>We use cookies for analytics and personalisation. <a href="cookie-policy.html">Learn more</a></span>
  <button id="cookie-accept">Accept All</button>
</div>

<header class="site-header">
  <div class="header-accent-bar"></div>
  <div class="wrapper">
    <div class="header-inner">
      <a href="./" class="site-brand">
        <div class="site-brand-mark">{% if blog_title %}{{ blog_title[0] | upper }}{% else %}B{% endif %}</div>
        <span class="site-title">{{ blog_title | e }}</span>
      </a>
      <div class="header-right">
        <nav class="header-nav">
          <a href="./">Home</a>
          <a href="about.html">About</a>
          <a href="contact.html">Contact</a>
        </nav>
      </div>
    </div>
  </div>
  <nav class="cat-nav" aria-label="Category navigation">
    <div class="wrapper">
      <div class="cat-nav-inner" id="catNavInner"></div>
    </div>
  </nav>
</header>

{% if posts|length > 0 %}
<div class="ticker-bar" role="marquee" aria-label="Breaking news">
  <span class="ticker-label">Latest</span>
  <div class="ticker-track-wrap">
    <div class="ticker-track" id="tickerTrack">
      {% for p in posts[:5] %}
      <span class="ticker-item"><a href="posts/{{ p.slug | e }}.html">{{ p.title | e }}</a></span>
      <span class="ticker-sep">&#9670;</span>
      {% endfor %}
      {% for p in posts[:5] %}
      <span class="ticker-item"><a href="posts/{{ p.slug | e }}.html">{{ p.title | e }}</a></span>
      <span class="ticker-sep">&#9670;</span>
      {% endfor %}
    </div>
  </div>
</div>
{% endif %}

<div class="ad-unit" aria-label="Advertisement">{{ ad_slot_1 | safe }}</div>

<main>
  {% if posts|length > 0 %}
  {%- set hero = posts[0] %}
  <section class="hero" aria-label="Featured story">
    <img src="{{ hero.get('featured_image_url','') | e }}" alt="{{ hero.title | e }}" class="hero-bg" loading="eager" width="1440" height="810">
    <div class="hero-gradient"></div>
    <div class="hero-content">
      <span class="hero-badge">
        <span class="hero-badge-dot"></span>
        Featured
      </span>
      <h1 class="hero-title">
        <a href="posts/{{ hero.slug | e }}.html" style="color:inherit;text-decoration:none;">{{ hero.title | e }}</a>
      </h1>
      {% if hero.get('meta_desc') %}
      <p class="hero-excerpt">{{ hero.meta_desc | e | truncate(160) }}</p>
      {% endif %}
      <div class="hero-meta">
        <span>{{ hero.get('published_at','')[:10] }}</span>
        <span class="hero-meta-sep">·</span>
        <span>Editorial Team</span>
      </div>
      <a href="posts/{{ hero.slug | e }}.html" class="hero-btn">
        Read Full Story <span class="hero-btn-arrow">&#8594;</span>
      </a>
    </div>
  </section>
  {% endif %}

  <div class="wrapper">
    {% if posts|length > 1 %}
    <section class="featured-split" aria-label="Top stories">
      {% for p in posts[1:3] %}
      <article class="split-card">
        <img src="{{ p.get('featured_image_url','') | e }}" alt="{{ p.title | e }}" loading="lazy" width="720" height="405">
        <div class="split-card-overlay"></div>
        <div class="split-card-body">
          <span class="split-card-badge">Top Story</span>
          <a href="posts/{{ p.slug | e }}.html" class="split-card-title">{{ p.title | e }}</a>
          <div class="split-card-meta">{{ p.get('published_at','')[:10] }}</div>
        </div>
      </article>
      {% endfor %}
    </section>
    {% endif %}

    <div class="subscribe-strip">
      <div class="subscribe-strip-text">
        <h3>Stay ahead of the story</h3>
        <p>Join thousands of readers getting the latest news delivered to their inbox.</p>
      </div>
      <div class="subscribe-strip-form">
        <input type="email" class="subscribe-input" placeholder="Enter your email address" aria-label="Email address">
        <button class="subscribe-btn">Subscribe Free</button>
      </div>
    </div>

    {% if posts|length > 3 %}
    <section class="section-block" aria-label="Latest stories">
      <div class="section-label">
        <span class="section-label-accent"></span>
        <span class="section-label-text">Latest Stories</span>
        <span class="section-label-line"></span>
      </div>
      <div class="post-grid">
        {% for p in posts[3:] %}
        <article class="post-card">
          <div class="post-card-img-wrap">
            <img src="{{ p.get('featured_image_url','') | e }}" alt="{{ p.title | e }}" loading="lazy" width="400" height="225">
          </div>
          <div class="post-card-body">
            <span class="cat-badge">{{ blog_title | e | truncate(12) }}</span>
            <h2 class="post-card-title">
              <a href="posts/{{ p.slug | e }}.html">{{ p.title | e }}</a>
            </h2>
            {% if p.get('meta_desc') %}
            <p class="post-card-excerpt">{{ p.meta_desc | e }}</p>
            {% endif %}
            <div class="card-meta">
              <span>{{ p.get('published_at','')[:10] }}</span>
              <span class="card-meta-dot">&#9679;</span>
              <span class="card-read-time">5 min</span>
            </div>
          </div>
        </article>
        {% endfor %}
      </div>
    </section>
    {% elif posts|length > 0 %}
    <section class="section-block" aria-label="All stories">
      <div class="section-label">
        <span class="section-label-accent"></span>
        <span class="section-label-text">All Stories</span>
        <span class="section-label-line"></span>
      </div>
      <div class="post-grid">
        {% for p in posts %}
        <article class="post-card">
          <div class="post-card-img-wrap">
            <img src="{{ p.get('featured_image_url','') | e }}" alt="{{ p.title | e }}" loading="lazy" width="400" height="225">
          </div>
          <div class="post-card-body">
            <span class="cat-badge">{{ blog_title | e | truncate(12) }}</span>
            <h2 class="post-card-title">
              <a href="posts/{{ p.slug | e }}.html">{{ p.title | e }}</a>
            </h2>
            {% if p.get('meta_desc') %}
            <p class="post-card-excerpt">{{ p.meta_desc | e }}</p>
            {% endif %}
            <div class="card-meta">
              <span>{{ p.get('published_at','')[:10] }}</span>
              <span class="card-meta-dot">&#9679;</span>
              <span class="card-read-time">5 min</span>
            </div>
          </div>
        </article>
        {% endfor %}
      </div>
    </section>
    {% endif %}

    {% if posts|length > 1 %}
    <section class="section-block" aria-label="Editor's picks">
      <div class="section-label">
        <span class="section-label-accent"></span>
        <span class="section-label-text">Editor's Picks</span>
        <span class="section-label-line"></span>
      </div>
      <div style="display:grid;grid-template-columns:1fr 300px;gap:36px;align-items:start">
        <div class="editor-strip">
          {% for p in posts[1:5] %}
          <a href="posts/{{ p.slug | e }}.html" class="editor-item">
            <img src="{{ p.get('featured_image_url','') | e }}" alt="{{ p.title | e }}" class="editor-item-img" loading="lazy">
            <div class="editor-item-body">
              <span class="editor-item-badge">Must Read</span>
              <div class="editor-item-title">{{ p.title | e }}</div>
              <div class="editor-item-meta">{{ p.get('published_at','')[:10] }} &middot; 4 min read</div>
            </div>
          </a>
          {% endfor %}
        </div>
        <div class="sidebar-box" style="position:sticky;top:80px">
          <div class="sidebar-box-title">Most Popular</div>
          <ul class="trending-list">
            {% for p in posts[:4] %}
            <li class="trending-item">
              <span class="trending-num">0{{ loop.index }}</span>
              <a href="posts/{{ p.slug | e }}.html" class="trending-link">{{ p.title | e | truncate(60) }}</a>
            </li>
            {% endfor %}
          </ul>
        </div>
      </div>
    </section>
    {% endif %}

    <div class="ad-unit" aria-label="Advertisement">{{ ad_slot_3 | safe }}</div>
  </div>
</main>

<footer class="site-footer">
  <div class="footer-top">
    <div class="wrapper">
      <div class="footer-grid">
        <div class="footer-col">
          <a href="./" class="footer-logo">
            <div class="footer-logo-mark">{% if blog_title %}{{ blog_title[0] | upper }}{% else %}B{% endif %}</div>
            <span class="footer-logo-name">{{ blog_title | e }}</span>
          </a>
          <p class="footer-tagline">Delivering news, analysis and insights. AI-assisted editorial content reviewed for accuracy.</p>
        </div>
        <div class="footer-col">
          <div class="footer-col-title">Company</div>
          <ul>
            <li><a href="about.html">About Us</a></li>
            <li><a href="contact.html">Contact</a></li>
            <li><a href="affiliate-disclosure.html">Disclosure</a></li>
          </ul>
        </div>
        <div class="footer-col">
          <div class="footer-col-title">Legal</div>
          <ul>
            <li><a href="privacy-policy.html">Privacy Policy</a></li>
            <li><a href="terms-of-service.html">Terms of Service</a></li>
            <li><a href="cookie-policy.html">Cookie Policy</a></li>
            <li><a href="dmca.html">DMCA</a></li>
          </ul>
        </div>
        <div class="footer-col">
          <div class="footer-col-title">Follow Us</div>
          <ul>
            <li><a href="./" rel="noopener">Twitter / X</a></li>
            <li><a href="./" rel="noopener">Pinterest</a></li>
            <li><a href="./" rel="noopener">Telegram</a></li>
            <li><a href="./" rel="noopener">Tumblr</a></li>
          </ul>
        </div>
      </div>
    </div>
  </div>
  <hr class="footer-divider">
  <div class="wrapper">
    <div class="footer-bottom">
      <span class="footer-copy">&copy; {{ year }} {{ blog_title | e }}. AI-assisted content. All rights reserved.</span>
      <div class="footer-legal-links">
        <a href="privacy-policy.html">Privacy</a>
        <a href="terms-of-service.html">Terms</a>
        <a href="cookie-policy.html">Cookies</a>
        <a href="contact.html">Contact</a>
      </div>
    </div>
  </div>
</footer>

<script>
(function(){
  'use strict';

  // Cookie banner
  var ckBanner=document.getElementById('cookie-banner');
  if(ckBanner&&!localStorage.getItem('ck')){ckBanner.style.display='flex';}
  var ckBtn=document.getElementById('cookie-accept');
  if(ckBtn){ckBtn.onclick=function(){localStorage.setItem('ck','1');if(ckBanner)ckBanner.style.display='none';};}

  // Category nav
  var CATS={finance:['Markets','Investing','Economy','Crypto','Personal Finance'],crypto:['Bitcoin','Ethereum','DeFi','NFTs','Markets'],health:['Nutrition','Fitness','Wellness','Medical','Mental Health'],tech:['AI & Machine Learning','Gadgets','Software','Science','Cybersecurity'],entertainment:['Movies','Celebrity','Music','Sports','TV']};
  var niche='{{ niche }}';
  var navEl=document.getElementById('catNavInner');
  if(navEl){
    var catList=CATS[niche]||CATS.tech;
    catList.forEach(function(c,i){
      var a=document.createElement('a');a.href='/';a.className='cat-nav-link';
      if(i===0)a.classList.add('active');
      a.textContent=c;navEl.appendChild(a);
    });
  }

  {% if is_adult %}
  function verifyAge(){sessionStorage.setItem('av','1');var g=document.getElementById('adult-gate');if(g)g.style.display='none';}
  if(sessionStorage.getItem('av')){var g=document.getElementById('adult-gate');if(g)g.style.display='none';}
  window.verifyAge=verifyAge;
  {% endif %}
})();
</script>
</body>
</html>"""

# ── Niche-specific index page templates ─────────────────────────────────────────

_CRYPTO_TEMPLATE = """<!DOCTYPE html>
<html lang="{{ language }}" {% if rtl %}dir="rtl"{% endif %}>
<head>
<base href="{{ blog_url }}/">
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{{ blog_title }}</title>
<meta name="description" content="{{ meta_desc }}">
<link rel="canonical" href="{{ blog_url }}">
<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;700&family=Inter:wght@300;400;600&display=swap" rel="stylesheet">
{{ ad_head_code }}
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{background:#0d1117;color:#e6edf3;font-family:'Inter',sans-serif;line-height:1.7}
a{color:{{ accent_color }};text-decoration:none}
.hdr{background:#010409;border-bottom:1px solid {{ accent_color }};padding:0 24px;position:sticky;top:0;z-index:100}
.hdr-inner{max-width:1200px;margin:0 auto;display:flex;align-items:center;justify-content:space-between;height:56px}
.logo{font-family:'JetBrains Mono',monospace;font-size:1.4rem;font-weight:700;color:{{ accent_color }};text-shadow:0 0 12px rgba(0,255,136,.5);letter-spacing:2px}
.logo span{color:#ffffff}
.nav a{color:#8b949e;font-size:.8rem;font-family:'JetBrains Mono',monospace;margin-left:20px;letter-spacing:.05em;text-transform:uppercase}
.nav a:hover{color:{{ accent_color }}}
.ticker{background:{{ accent_color }};color:#000;padding:6px 0;overflow:hidden;font-family:'JetBrains Mono',monospace;font-size:.72rem;font-weight:700}
.ticker-inner{white-space:nowrap;animation:scroll 30s linear infinite;display:inline-block}
@keyframes scroll{from{transform:translateX(100vw)}to{transform:translateX(-100%)}}
.wrap{max-width:1200px;margin:0 auto;padding:32px 24px}
.section-title{font-family:'JetBrains Mono',monospace;color:{{ accent_color }};font-size:.85rem;letter-spacing:.15em;text-transform:uppercase;margin-bottom:20px;padding-bottom:8px;border-bottom:1px solid #21262d}
.section-title::before{content:"▸ "}
.hero-grid{display:grid;grid-template-columns:1fr 1fr;gap:20px;margin-bottom:40px}
@media(max-width:700px){.hero-grid{grid-template-columns:1fr}}
.card{background:#161b22;border:1px solid #21262d;border-radius:6px;overflow:hidden;transition:border-color .2s,transform .2s}
.card:hover{border-color:{{ accent_color }};transform:translateY(-2px)}
.card img{width:100%;height:200px;object-fit:cover;opacity:.85}
.card-body{padding:16px}
.card-tag{font-family:'JetBrains Mono',monospace;font-size:.65rem;color:{{ accent_color }};text-transform:uppercase;letter-spacing:.1em;margin-bottom:8px}
.card h2{font-size:1.05rem;font-weight:700;line-height:1.35;color:#e6edf3;margin-bottom:8px}
.card h2 a{color:#e6edf3}.card h2 a:hover{color:{{ accent_color }}}
.card-meta{font-size:.72rem;color:#8b949e;font-family:'JetBrains Mono',monospace}
.side-stack{display:flex;flex-direction:column;gap:16px}
.mini-card{display:flex;gap:12px;background:#161b22;border:1px solid #21262d;border-left:3px solid {{ accent_color }};padding:12px;border-radius:4px}
.mini-card img{width:80px;height:60px;object-fit:cover;border-radius:3px;flex-shrink:0}
.mini-card h3{font-size:.88rem;line-height:1.3;color:#e6edf3}.mini-card h3 a{color:#e6edf3}.mini-card h3 a:hover{color:{{ accent_color }}}
.mini-card-meta{font-size:.68rem;color:#8b949e;font-family:'JetBrains Mono',monospace;margin-top:4px}
.empty{text-align:center;padding:80px 20px;color:#8b949e}
.empty h2{font-family:'JetBrains Mono',monospace;color:{{ accent_color }};font-size:1.1rem;margin-bottom:12px}
footer{border-top:1px solid #21262d;margin-top:60px;padding:24px;text-align:center;color:#8b949e;font-family:'JetBrains Mono',monospace;font-size:.72rem}
</style></head>
<body>
<header class="hdr"><div class="hdr-inner">
<div class="logo">{{ blog_title[:2].upper() }}<span>{{ blog_title[2:] }}</span></div>
<nav class="nav"><a href="{{ blog_url }}/">Home</a><a href="{{ blog_url }}/sitemap.xml">Sitemap</a></nav>
</div></header>
<div class="ticker"><span class="ticker-inner">&#x2B1B; LATEST: {{ blog_title }} — Updated Daily &nbsp;&nbsp;&nbsp;&#x2B1B; CRYPTO NEWS &nbsp;&nbsp;&nbsp;&#x2B1B; BLOCKCHAIN INSIGHTS &nbsp;&nbsp;&nbsp;&#x2B1B; MARKET SIGNALS &nbsp;&nbsp;&nbsp;&#x2B1B; DEFI UPDATES &nbsp;&nbsp;&nbsp;&#x2B1B; NFT TRENDS &nbsp;&nbsp;&nbsp;</span></div>
{{ ad_slot_1 }}
<main class="wrap">
{% if posts %}
<p class="section-title">Latest Signals</p>
<div class="hero-grid">
<div>
{% set p = posts[0] %}
<div class="card">
{% if p.featured_image_url %}<img src="{{ p.featured_image_url }}" alt="{{ p.title }}" loading="lazy">{% endif %}
<div class="card-body">
<div class="card-tag">{{ p.get('category','Crypto') }}</div>
<h2><a href="{{ blog_url }}/posts/{{ p.slug }}.html">{{ p.title }}</a></h2>
<div class="card-meta">{{ p.get('published_at','')[:10] }}</div>
</div></div>
</div>
<div class="side-stack">
{% for p in posts[1:4] %}
<div class="mini-card">
{% if p.featured_image_url %}<img src="{{ p.featured_image_url }}" alt="{{ p.title }}" loading="lazy">{% endif %}
<div><h3><a href="{{ blog_url }}/posts/{{ p.slug }}.html">{{ p.title }}</a></h3>
<div class="mini-card-meta">{{ p.get('published_at','')[:10] }}</div></div>
</div>{% endfor %}
</div></div>
{% if posts|length > 4 %}
<p class="section-title" style="margin-top:40px">More Signals</p>
<div class="hero-grid">
{% for p in posts[4:] %}
<div class="card">
{% if p.featured_image_url %}<img src="{{ p.featured_image_url }}" alt="{{ p.title }}" loading="lazy">{% endif %}
<div class="card-body">
<div class="card-tag">{{ p.get('category','Crypto') }}</div>
<h2><a href="{{ blog_url }}/posts/{{ p.slug }}.html">{{ p.title }}</a></h2>
<div class="card-meta">{{ p.get('published_at','')[:10] }}</div>
</div></div>{% endfor %}
</div>{% endif %}
{% else %}
<div class="empty"><h2>// SIGNAL INCOMING</h2><p>First articles deploying soon. Check back in 24 hours.</p></div>
{% endif %}
{{ ad_slot_3 }}
</main>
<footer>&copy; {{ year }} {{ blog_title }} &mdash; All rights reserved</footer>
{% if onesignal_app_id %}<script src="https://cdn.onesignal.com/sdks/web/v16/OneSignalSDK.page.js" defer></script><script>window.OneSignalDeferred=window.OneSignalDeferred||[];OneSignalDeferred.push(async function(OneSignal){await OneSignal.init({appId:"{{ onesignal_app_id }}",notifyButton:{enable:true}});});</script>{% endif %}
<!-- Cloudflare Web Analytics --><script defer src='https://static.cloudflareinsights.com/beacon.min.js' data-cf-beacon='{"token": "be17bfc005774526803b0ef32264a47e"}'></script><!-- End Cloudflare Web Analytics -->
</body></html>"""

_FINANCE_TEMPLATE = """<!DOCTYPE html>
<html lang="{{ language }}" {% if rtl %}dir="rtl"{% endif %}>
<head>
<base href="{{ blog_url }}/">
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{{ blog_title }}</title>
<meta name="description" content="{{ meta_desc }}">
<link rel="canonical" href="{{ blog_url }}">
<link href="https://fonts.googleapis.com/css2?family=Playfair+Display:wght@700;800&family=Source+Sans+3:wght@400;600&display=swap" rel="stylesheet">
{{ ad_head_code }}
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{background:#f5f5f0;color:#1a1a1a;font-family:'Source Sans 3','Segoe UI',sans-serif;line-height:1.65}
a{color:{{ accent_color }};text-decoration:none}
.market-bar{background:#1a1a2e;color:#e0e0e0;font-size:.72rem;padding:5px 24px;text-align:center;letter-spacing:.05em}
.market-bar span{margin:0 16px;color:#4ade80}
.hdr{background:#fff;border-bottom:3px solid {{ accent_color }};padding:16px 24px 12px}
.hdr-inner{max-width:1200px;margin:0 auto;text-align:center}
.logo{font-family:'Playfair Display',serif;font-size:2.2rem;font-weight:800;color:#1a1a2e;letter-spacing:-1px;line-height:1}
.logo-sub{font-size:.72rem;letter-spacing:.3em;text-transform:uppercase;color:#888;margin-top:4px;font-family:'Source Sans 3',sans-serif}
.nav{display:flex;justify-content:center;gap:0;margin-top:10px;border-top:1px solid #e0e0e0;padding-top:8px}
.nav a{color:#1a1a1a;font-size:.78rem;font-weight:600;padding:4px 14px;text-transform:uppercase;letter-spacing:.07em;border-right:1px solid #e0e0e0}
.nav a:last-child{border-right:none}
.nav a:hover{color:{{ accent_color }}}
.wrap{max-width:1200px;margin:0 auto;padding:28px 24px}
.section-divider{display:flex;align-items:center;margin:28px 0 18px;gap:12px}
.section-divider::before{content:"";flex:0 0 40px;height:3px;background:{{ accent_color }}}
.section-divider h2{font-family:'Playfair Display',serif;font-size:1rem;font-weight:700;text-transform:uppercase;letter-spacing:.08em;color:#1a1a2e}
.section-divider::after{content:"";flex:1;height:1px;background:#d0d0d0}
.featured{display:grid;grid-template-columns:2fr 1fr;gap:24px;margin-bottom:8px}
@media(max-width:700px){.featured{grid-template-columns:1fr}}
.feat-card img{width:100%;height:320px;object-fit:cover}
.feat-card .cat{font-size:.68rem;font-weight:700;color:{{ accent_color }};text-transform:uppercase;letter-spacing:.1em;margin-bottom:6px}
.feat-card h2{font-family:'Playfair Display',serif;font-size:1.6rem;line-height:1.25;margin-bottom:8px}
.feat-card h2 a{color:#1a1a1a}.feat-card h2 a:hover{color:{{ accent_color }}}
.feat-card .excerpt{font-size:.9rem;color:#444;margin-bottom:10px;line-height:1.55}
.feat-card .byline{font-size:.72rem;color:#888;border-top:1px solid #e0e0e0;padding-top:8px}
.news-list{display:flex;flex-direction:column;gap:0}
.news-item{display:flex;gap:12px;padding:12px 0;border-bottom:1px solid #e8e8e8}
.news-item img{width:90px;height:65px;object-fit:cover;flex-shrink:0}
.news-item .cat{font-size:.62rem;font-weight:700;color:{{ accent_color }};text-transform:uppercase;letter-spacing:.08em}
.news-item h3{font-family:'Playfair Display',serif;font-size:.92rem;line-height:1.3;margin:3px 0}
.news-item h3 a{color:#1a1a1a}.news-item h3 a:hover{color:{{ accent_color }}}
.news-item .date{font-size:.68rem;color:#aaa}
.news-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:20px;margin-top:8px}
@media(max-width:700px){.news-grid{grid-template-columns:1fr}}
.grid-card{border-top:2px solid #e0e0e0;padding-top:12px}
.grid-card img{width:100%;height:150px;object-fit:cover;margin-bottom:10px}
.grid-card .cat{font-size:.62rem;font-weight:700;color:{{ accent_color }};text-transform:uppercase;letter-spacing:.08em}
.grid-card h3{font-family:'Playfair Display',serif;font-size:.98rem;line-height:1.3;margin:4px 0 6px}
.grid-card h3 a{color:#1a1a1a}.grid-card h3 a:hover{color:{{ accent_color }}}
.grid-card .date{font-size:.68rem;color:#aaa}
.empty{text-align:center;padding:80px 20px;color:#888}
.empty h2{font-family:'Playfair Display',serif;font-size:1.4rem;color:#1a1a2e;margin-bottom:8px}
footer{background:#1a1a2e;color:#aaa;text-align:center;padding:20px;font-size:.75rem;margin-top:50px}
footer a{color:#aaa}
</style></head>
<body>
<div class="market-bar">MARKETS: <span>STOCKS &#x25B2; 0.34%</span><span>BONDS &#x25BC; 0.12%</span><span>GOLD &#x25B2; 0.67%</span><span>OIL &#x25BC; 0.45%</span></div>
<header class="hdr"><div class="hdr-inner">
<div class="logo">{{ blog_title }}</div>
<div class="logo-sub">Financial Intelligence</div>
<nav class="nav"><a href="{{ blog_url }}/">Home</a><a href="#">Markets</a><a href="#">Investing</a><a href="#">Economy</a><a href="{{ blog_url }}/sitemap.xml">Sitemap</a></nav>
</div></header>
{{ ad_slot_1 }}
<main class="wrap">
{% if posts %}
{% set p = posts[0] %}
<div class="section-divider"><h2>Top Story</h2></div>
<div class="featured">
<div class="feat-card">
{% if p.featured_image_url %}<img src="{{ p.featured_image_url }}" alt="{{ p.title }}">{% endif %}
<div style="padding-top:14px">
<div class="cat">{{ p.get('category','Finance') }}</div>
<h2><a href="{{ blog_url }}/posts/{{ p.slug }}.html">{{ p.title }}</a></h2>
{% if p.get('meta_desc') %}<p class="excerpt">{{ p.meta_desc[:160] }}...</p>{% endif %}
<div class="byline">{{ p.get('published_at','')[:10] }}</div>
</div></div>
{% if posts|length > 1 %}
<div class="news-list">
{% for p in posts[1:5] %}
<div class="news-item">
{% if p.featured_image_url %}<img src="{{ p.featured_image_url }}" alt="{{ p.title }}">{% endif %}
<div class="news-item-body">
<div class="cat">{{ p.get('category','Finance') }}</div>
<h3><a href="{{ blog_url }}/posts/{{ p.slug }}.html">{{ p.title }}</a></h3>
<div class="date">{{ p.get('published_at','')[:10] }}</div>
</div></div>{% endfor %}
</div>{% endif %}
</div>
{% if posts|length > 5 %}
<div class="section-divider" style="margin-top:32px"><h2>More Analysis</h2></div>
<div class="news-grid">
{% for p in posts[5:] %}
<div class="grid-card">
{% if p.featured_image_url %}<img src="{{ p.featured_image_url }}" alt="{{ p.title }}">{% endif %}
<div class="cat">{{ p.get('category','Finance') }}</div>
<h3><a href="{{ blog_url }}/posts/{{ p.slug }}.html">{{ p.title }}</a></h3>
<div class="date">{{ p.get('published_at','')[:10] }}</div>
</div>{% endfor %}
</div>{% endif %}
{% else %}
<div class="empty"><h2>Analysis Coming Soon</h2><p>Premium financial content launches shortly. Bookmark this page.</p></div>
{% endif %}
{{ ad_slot_3 }}
</main>
<footer>&copy; {{ year }} {{ blog_title }}. All rights reserved. | <a href="{{ blog_url }}/sitemap.xml">Sitemap</a></footer>
{% if onesignal_app_id %}<script src="https://cdn.onesignal.com/sdks/web/v16/OneSignalSDK.page.js" defer></script><script>window.OneSignalDeferred=window.OneSignalDeferred||[];OneSignalDeferred.push(async function(OneSignal){await OneSignal.init({appId:"{{ onesignal_app_id }}",notifyButton:{enable:true}});});</script>{% endif %}
<!-- Cloudflare Web Analytics --><script defer src='https://static.cloudflareinsights.com/beacon.min.js' data-cf-beacon='{"token": "be17bfc005774526803b0ef32264a47e"}'></script><!-- End Cloudflare Web Analytics -->
</body></html>"""

_HEALTH_TEMPLATE = """<!DOCTYPE html>
<html lang="{{ language }}" {% if rtl %}dir="rtl"{% endif %}>
<head>
<base href="{{ blog_url }}/">
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{{ blog_title }}</title>
<meta name="description" content="{{ meta_desc }}">
<link rel="canonical" href="{{ blog_url }}">
<link href="https://fonts.googleapis.com/css2?family=Nunito:wght@600;700;800&family=Lato:wght@400;700&display=swap" rel="stylesheet">
{{ ad_head_code }}
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{background:#fafef7;color:#2c3e50;font-family:'Lato',sans-serif;line-height:1.7}
a{color:{{ accent_color }};text-decoration:none}
.hdr{background:#fff;box-shadow:0 2px 20px rgba(0,0,0,.06);padding:0 24px;position:sticky;top:0;z-index:100}
.hdr-inner{max-width:1100px;margin:0 auto;display:flex;align-items:center;justify-content:space-between;height:64px}
.logo{font-family:'Nunito',sans-serif;font-size:1.5rem;font-weight:800;color:#2d6a4f;display:flex;align-items:center;gap:8px}
.logo-leaf{font-size:1.3rem}
.nav a{color:#555;font-size:.82rem;font-weight:700;margin-left:20px;padding:6px 14px;border-radius:20px;transition:background .2s}
.nav a:hover{background:#d8f3dc;color:#2d6a4f}
.filters{max-width:1100px;margin:20px auto 0;padding:0 24px;display:flex;gap:8px;flex-wrap:wrap}
.pill{padding:6px 16px;border-radius:999px;font-size:.78rem;font-weight:700;border:2px solid #d8f3dc;color:#2d6a4f;cursor:pointer;transition:.2s}
.pill.active,.pill:hover{background:{{ accent_color }};color:#fff;border-color:{{ accent_color }}}
.wrap{max-width:1100px;margin:0 auto;padding:28px 24px}
.section-label{font-family:'Nunito',sans-serif;font-size:.75rem;font-weight:800;color:{{ accent_color }};text-transform:uppercase;letter-spacing:.1em;margin-bottom:16px;display:flex;align-items:center;gap:8px}
.section-label::after{content:"";flex:1;height:2px;background:#d8f3dc;border-radius:1px}
.hero-card{border-radius:20px;overflow:hidden;background:#fff;box-shadow:0 4px 24px rgba(45,106,79,.08);margin-bottom:28px;display:grid;grid-template-columns:1.4fr 1fr}
@media(max-width:700px){.hero-card{grid-template-columns:1fr}}
.hero-card img{width:100%;height:100%;min-height:280px;object-fit:cover}
.hero-card-body{padding:28px}
.tag-pill{display:inline-block;background:#d8f3dc;color:#2d6a4f;font-size:.68rem;font-weight:700;padding:3px 10px;border-radius:999px;text-transform:uppercase;letter-spacing:.07em;margin-bottom:10px}
.hero-card h2{font-family:'Nunito',sans-serif;font-size:1.5rem;font-weight:800;line-height:1.28;margin-bottom:10px;color:#1a2e1f}
.hero-card h2 a{color:#1a2e1f}.hero-card h2 a:hover{color:{{ accent_color }}}
.hero-card .excerpt{font-size:.88rem;color:#555;line-height:1.6;margin-bottom:14px}
.read-more{display:inline-flex;align-items:center;gap:6px;background:{{ accent_color }};color:#fff;font-size:.8rem;font-weight:700;padding:8px 18px;border-radius:999px;transition:.2s}
.read-more:hover{background:#2d6a4f;color:#fff}
.card-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:20px}
@media(max-width:800px){.card-grid{grid-template-columns:repeat(2,1fr)}}
@media(max-width:500px){.card-grid{grid-template-columns:1fr}}
.card{background:#fff;border-radius:16px;overflow:hidden;box-shadow:0 2px 16px rgba(0,0,0,.06);transition:transform .2s,box-shadow .2s}
.card:hover{transform:translateY(-4px);box-shadow:0 8px 30px rgba(0,0,0,.1)}
.card img{width:100%;height:180px;object-fit:cover}
.card-body{padding:16px}
.card .tag-pill{margin-bottom:8px}
.card h3{font-family:'Nunito',sans-serif;font-size:1rem;font-weight:700;line-height:1.3;color:#1a2e1f;margin-bottom:6px}
.card h3 a{color:#1a2e1f}.card h3 a:hover{color:{{ accent_color }}}
.card .date{font-size:.72rem;color:#aaa}
.empty{text-align:center;padding:80px 20px}
.empty-icon{font-size:3rem;margin-bottom:12px}
.empty h2{font-family:'Nunito',sans-serif;font-size:1.4rem;color:#2d6a4f;margin-bottom:8px}
.empty p{color:#888;font-size:.9rem}
footer{background:#1a2e1f;color:#b7e4c7;text-align:center;padding:24px;font-size:.78rem;margin-top:60px;border-radius:20px 20px 0 0}
</style></head>
<body>
<header class="hdr"><div class="hdr-inner">
<div class="logo"><span class="logo-leaf">&#x1F33F;</span>{{ blog_title }}</div>
<nav class="nav"><a href="{{ blog_url }}/">Home</a><a href="#">Nutrition</a><a href="#">Fitness</a><a href="#">Wellness</a></nav>
</div></header>
<div class="filters">
<span class="pill active">All</span><span class="pill">Nutrition</span><span class="pill">Fitness</span><span class="pill">Mental Health</span><span class="pill">Recipes</span>
</div>
{{ ad_slot_1 }}
<main class="wrap">
{% if posts %}
{% set p = posts[0] %}
<div class="section-label">Wellness Picks</div>
<div class="hero-card">
{% if p.featured_image_url %}<img src="{{ p.featured_image_url }}" alt="{{ p.title }}">{% endif %}
<div class="hero-card-body">
<span class="tag-pill">{{ p.get('category','Health') }}</span>
<h2><a href="{{ blog_url }}/posts/{{ p.slug }}.html">{{ p.title }}</a></h2>
{% if p.get('meta_desc') %}<p class="excerpt">{{ p.meta_desc[:150] }}</p>{% endif %}
<a href="{{ blog_url }}/posts/{{ p.slug }}.html" class="read-more">Read Article &#x2192;</a>
</div></div>
{% if posts|length > 1 %}
<div class="section-label" style="margin-top:32px">More Articles</div>
<div class="card-grid">
{% for p in posts[1:] %}
<div class="card">
{% if p.featured_image_url %}<img src="{{ p.featured_image_url }}" alt="{{ p.title }}">{% endif %}
<div class="card-body">
<span class="tag-pill">{{ p.get('category','Health') }}</span>
<h3><a href="{{ blog_url }}/posts/{{ p.slug }}.html">{{ p.title }}</a></h3>
<div class="date">{{ p.get('published_at','')[:10] }}</div>
</div></div>{% endfor %}
</div>{% endif %}
{% else %}
<div class="empty"><div class="empty-icon">&#x1F331;</div><h2>Growing Something Good</h2><p>Fresh wellness content coming soon. Check back tomorrow!</p></div>
{% endif %}
{{ ad_slot_3 }}
</main>
<footer>&copy; {{ year }} {{ blog_title }} &mdash; Your Wellness Journey Starts Here | <a href="{{ blog_url }}/sitemap.xml" style="color:#b7e4c7">Sitemap</a></footer>
{% if onesignal_app_id %}<script src="https://cdn.onesignal.com/sdks/web/v16/OneSignalSDK.page.js" defer></script><script>window.OneSignalDeferred=window.OneSignalDeferred||[];OneSignalDeferred.push(async function(OneSignal){await OneSignal.init({appId:"{{ onesignal_app_id }}",notifyButton:{enable:true}});});</script>{% endif %}
<!-- Cloudflare Web Analytics --><script defer src='https://static.cloudflareinsights.com/beacon.min.js' data-cf-beacon='{"token": "be17bfc005774526803b0ef32264a47e"}'></script><!-- End Cloudflare Web Analytics -->
</body></html>"""

_TECH_TEMPLATE = """<!DOCTYPE html>
<html lang="{{ language }}" {% if rtl %}dir="rtl"{% endif %}>
<head>
<base href="{{ blog_url }}/">
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{{ blog_title }}</title>
<meta name="description" content="{{ meta_desc }}">
<link rel="canonical" href="{{ blog_url }}">
<link href="https://fonts.googleapis.com/css2?family=Barlow+Condensed:wght@600;700;800&family=Inter:wght@400;500;600&display=swap" rel="stylesheet">
{{ ad_head_code }}
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{background:#fff;color:#1a1a1a;font-family:'Inter',sans-serif;line-height:1.65}
a{color:{{ accent_color }};text-decoration:none}
.hdr{background:#000;padding:0 24px;position:sticky;top:0;z-index:100}
.hdr-inner{max-width:1200px;margin:0 auto;display:flex;align-items:center;justify-content:space-between;height:56px}
.logo{font-family:'Barlow Condensed',sans-serif;font-size:1.8rem;font-weight:800;color:#fff;letter-spacing:-1px;text-transform:uppercase}
.logo em{color:{{ accent_color }};font-style:normal}
.nav a{color:rgba(255,255,255,.7);font-size:.8rem;font-weight:600;margin-left:20px;text-transform:uppercase;letter-spacing:.05em;transition:.2s}
.nav a:hover{color:{{ accent_color }}}
.accent-line{height:4px;background:linear-gradient(90deg,{{ accent_color }},#ff8c00,#ffd700)}
.cat-tabs{background:#f5f5f5;border-bottom:1px solid #e5e5e5;padding:0 24px}
.cat-tabs-inner{max-width:1200px;margin:0 auto;display:flex;gap:0;overflow-x:auto}
.cat-tab{padding:10px 18px;font-size:.78rem;font-weight:700;color:#666;text-transform:uppercase;letter-spacing:.07em;border-bottom:3px solid transparent;white-space:nowrap;cursor:pointer;transition:.2s}
.cat-tab:hover,.cat-tab.active{color:{{ accent_color }};border-bottom-color:{{ accent_color }}}
.wrap{max-width:1200px;margin:0 auto;padding:28px 24px}
.hero-full{display:grid;grid-template-columns:1.6fr 1fr;gap:0;margin-bottom:32px;background:#000;min-height:380px}
@media(max-width:700px){.hero-full{grid-template-columns:1fr}}
.hero-full img{width:100%;height:100%;min-height:300px;object-fit:cover;opacity:.9}
.hero-full-body{padding:28px;display:flex;flex-direction:column;justify-content:flex-end}
.hero-cat{font-family:'Barlow Condensed',sans-serif;font-size:.78rem;font-weight:700;color:{{ accent_color }};text-transform:uppercase;letter-spacing:.15em;margin-bottom:8px}
.hero-full h2{font-family:'Barlow Condensed',sans-serif;font-size:2rem;font-weight:800;line-height:1.1;color:#fff;margin-bottom:10px;text-transform:uppercase}
.hero-full h2 a{color:#fff}.hero-full h2 a:hover{color:{{ accent_color }}}
.hero-date{font-size:.72rem;color:#aaa}
.tech-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:20px}
@media(max-width:900px){.tech-grid{grid-template-columns:repeat(2,1fr)}}
@media(max-width:500px){.tech-grid{grid-template-columns:1fr}}
.tech-card{transition:transform .2s}
.tech-card:hover{transform:translateY(-4px)}
.tech-card img{width:100%;height:160px;object-fit:cover;margin-bottom:10px}
.tech-card .cat{font-family:'Barlow Condensed',sans-serif;font-size:.7rem;font-weight:700;color:{{ accent_color }};text-transform:uppercase;letter-spacing:.1em;margin-bottom:4px}
.tech-card h3{font-family:'Barlow Condensed',sans-serif;font-size:1.1rem;font-weight:700;line-height:1.2;text-transform:uppercase;color:#1a1a1a}
.tech-card h3 a{color:#1a1a1a}.tech-card h3 a:hover{color:{{ accent_color }}}
.tech-card .date{font-size:.68rem;color:#aaa;margin-top:6px}
.sec-title{font-family:'Barlow Condensed',sans-serif;font-size:1.1rem;font-weight:800;text-transform:uppercase;letter-spacing:.1em;margin-bottom:16px;padding-left:12px;border-left:4px solid {{ accent_color }};color:#1a1a1a}
.empty{text-align:center;padding:80px 20px}
.empty h2{font-family:'Barlow Condensed',sans-serif;font-size:1.8rem;font-weight:800;text-transform:uppercase;color:#1a1a1a;margin-bottom:8px}
.empty p{color:#888}
footer{background:#000;color:#666;text-align:center;padding:20px;font-size:.75rem;margin-top:50px}
footer a{color:{{ accent_color }}}
</style></head>
<body>
<header class="hdr"><div class="hdr-inner">
<div class="logo">{{ blog_title[:4].upper() }}<em>{{ blog_title[4:].upper() }}</em></div>
<nav class="nav"><a href="{{ blog_url }}/">Home</a><a href="#">Reviews</a><a href="#">AI</a><a href="#">Gadgets</a></nav>
</div></header>
<div class="accent-line"></div>
<div class="cat-tabs"><div class="cat-tabs-inner">
<div class="cat-tab active">All</div><div class="cat-tab">AI</div><div class="cat-tab">Gadgets</div><div class="cat-tab">Apps</div><div class="cat-tab">Science</div><div class="cat-tab">Reviews</div>
</div></div>
{{ ad_slot_1 }}
<main class="wrap">
{% if posts %}
{% set p = posts[0] %}
<div class="hero-full">
{% if p.featured_image_url %}<img src="{{ p.featured_image_url }}" alt="{{ p.title }}">{% endif %}
<div class="hero-full-body">
<div class="hero-cat">{{ p.get('category','Tech') }}</div>
<h2><a href="{{ blog_url }}/posts/{{ p.slug }}.html">{{ p.title }}</a></h2>
<div class="hero-date">{{ p.get('published_at','')[:10] }}</div>
</div></div>
{% if posts|length > 1 %}
<div class="sec-title" style="margin-top:32px">Latest Coverage</div>
<div class="tech-grid">
{% for p in posts[1:] %}
<div class="tech-card">
{% if p.featured_image_url %}<img src="{{ p.featured_image_url }}" alt="{{ p.title }}">{% endif %}
<div class="cat">{{ p.get('category','Tech') }}</div>
<h3><a href="{{ blog_url }}/posts/{{ p.slug }}.html">{{ p.title }}</a></h3>
<div class="date">{{ p.get('published_at','')[:10] }}</div>
</div>{% endfor %}
</div>{% endif %}
{% else %}
<div class="empty"><h2>Content Loading</h2><p>First tech articles arriving soon. Stay tuned.</p></div>
{% endif %}
{{ ad_slot_3 }}
</main>
<footer>&copy; {{ year }} {{ blog_title }} | <a href="{{ blog_url }}/sitemap.xml">Sitemap</a></footer>
{% if onesignal_app_id %}<script src="https://cdn.onesignal.com/sdks/web/v16/OneSignalSDK.page.js" defer></script><script>window.OneSignalDeferred=window.OneSignalDeferred||[];OneSignalDeferred.push(async function(OneSignal){await OneSignal.init({appId:"{{ onesignal_app_id }}",notifyButton:{enable:true}});});</script>{% endif %}
<!-- Cloudflare Web Analytics --><script defer src='https://static.cloudflareinsights.com/beacon.min.js' data-cf-beacon='{"token": "be17bfc005774526803b0ef32264a47e"}'></script><!-- End Cloudflare Web Analytics -->
</body></html>"""

_ENTERTAINMENT_TEMPLATE = """<!DOCTYPE html>
<html lang="{{ language }}" {% if rtl %}dir="rtl"{% endif %}>
<head>
<base href="{{ blog_url }}/">
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{{ blog_title }}</title>
<meta name="description" content="{{ meta_desc }}">
<link rel="canonical" href="{{ blog_url }}">
<link href="https://fonts.googleapis.com/css2?family=Oswald:wght@400;500;600;700&family=Open+Sans:wght@400;600&display=swap" rel="stylesheet">
{{ ad_head_code }}
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{background:#f7f7f7;color:#1a1a1a;font-family:'Open Sans',sans-serif;line-height:1.65}
a{color:{{ accent_color }};text-decoration:none}
.hdr{background:{{ accent_color }};padding:0 24px;position:sticky;top:0;z-index:100}
.hdr-inner{max-width:1200px;margin:0 auto;display:flex;align-items:center;justify-content:space-between;height:60px}
.logo{font-family:'Oswald',sans-serif;font-size:1.9rem;font-weight:700;color:#fff;text-transform:uppercase;letter-spacing:-1px}
.nav a{color:rgba(255,255,255,.85);font-size:.82rem;font-weight:600;margin-left:18px;text-transform:uppercase;transition:.2s}
.nav a:hover{color:#fff}
.trending-bar{background:#1a1a1a;color:#fff;padding:8px 24px;display:flex;align-items:center;gap:12px}
.trending-label{background:{{ accent_color }};color:#fff;font-family:'Oswald',sans-serif;font-size:.72rem;font-weight:700;padding:2px 10px;border-radius:3px;text-transform:uppercase;white-space:nowrap}
.trending-items{display:flex;gap:16px;overflow:hidden;font-size:.78rem;color:#ccc}
.wrap{max-width:1200px;margin:0 auto;padding:24px}
.sec-hdr{font-family:'Oswald',sans-serif;font-size:1.1rem;font-weight:700;text-transform:uppercase;letter-spacing:.05em;color:#fff;background:#1a1a1a;padding:8px 14px;margin-bottom:16px;display:flex;align-items:center;gap:8px}
.sec-hdr::before{content:"&#x25CF;";color:{{ accent_color }}}
.big-card{background:#fff;border-radius:8px;overflow:hidden;margin-bottom:24px;box-shadow:0 2px 12px rgba(0,0,0,.08)}
.big-card img{width:100%;height:360px;object-fit:cover}
.big-card-body{padding:20px}
.badge{display:inline-block;background:{{ accent_color }};color:#fff;font-family:'Oswald',sans-serif;font-size:.65rem;font-weight:700;padding:2px 8px;border-radius:3px;text-transform:uppercase;letter-spacing:.05em;margin-bottom:8px}
.big-card h2{font-family:'Oswald',sans-serif;font-size:1.7rem;font-weight:700;line-height:1.2;text-transform:uppercase;color:#1a1a1a;margin-bottom:6px}
.big-card h2 a{color:#1a1a1a}.big-card h2 a:hover{color:{{ accent_color }}}
.big-card .meta{font-size:.72rem;color:#888}
.img-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:16px}
@media(max-width:700px){.img-grid{grid-template-columns:1fr}}
.img-card{background:#fff;border-radius:8px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,.06);transition:transform .2s}
.img-card:hover{transform:translateY(-3px)}
.img-card-thumb{position:relative;overflow:hidden}
.img-card img{width:100%;height:200px;object-fit:cover;transition:transform .3s}
.img-card:hover img{transform:scale(1.04)}
.hot-badge{position:absolute;top:8px;left:8px;background:{{ accent_color }};color:#fff;font-family:'Oswald',sans-serif;font-size:.62rem;font-weight:700;padding:2px 8px;border-radius:3px;text-transform:uppercase}
.img-card-body{padding:12px}
.img-card h3{font-family:'Oswald',sans-serif;font-size:1.05rem;font-weight:600;line-height:1.25;text-transform:uppercase;color:#1a1a1a;margin-bottom:4px}
.img-card h3 a{color:#1a1a1a}.img-card h3 a:hover{color:{{ accent_color }}}
.img-card .date{font-size:.68rem;color:#aaa}
.empty{text-align:center;padding:80px 20px;background:#fff;border-radius:12px}
.empty h2{font-family:'Oswald',sans-serif;font-size:1.6rem;font-weight:700;text-transform:uppercase;color:{{ accent_color }};margin-bottom:8px}
footer{background:#1a1a1a;color:#888;text-align:center;padding:20px;font-size:.75rem;margin-top:40px}
footer a{color:{{ accent_color }}}
</style></head>
<body>
<header class="hdr"><div class="hdr-inner">
<div class="logo">{{ blog_title }}</div>
<nav class="nav"><a href="{{ blog_url }}/">Home</a><a href="#">Celebs</a><a href="#">Viral</a><a href="#">Trending</a></nav>
</div></header>
<div class="trending-bar">
<span class="trending-label">&#x1F525; Trending</span>
<div class="trending-items">
<span>{{ blog_title }} goes viral</span><span>Hot takes daily</span><span>Celebrity news 24/7</span>
</div></div>
{{ ad_slot_1 }}
<main class="wrap">
{% if posts %}
{% set p = posts[0] %}
<div class="sec-hdr">Breaking Now</div>
<div class="big-card">
{% if p.featured_image_url %}<img src="{{ p.featured_image_url }}" alt="{{ p.title }}">{% endif %}
<div class="big-card-body">
<span class="badge">Hot</span>
<h2><a href="{{ blog_url }}/posts/{{ p.slug }}.html">{{ p.title }}</a></h2>
<div class="meta">{{ p.get('published_at','')[:10] }}</div>
</div></div>
{% if posts|length > 1 %}
<div class="sec-hdr">More Stories</div>
<div class="img-grid">
{% for p in posts[1:] %}
<div class="img-card">
<div class="img-card-thumb">
{% if p.featured_image_url %}<img src="{{ p.featured_image_url }}" alt="{{ p.title }}">{% endif %}
<span class="hot-badge">&#x1F525;</span>
</div>
<div class="img-card-body">
<h3><a href="{{ blog_url }}/posts/{{ p.slug }}.html">{{ p.title }}</a></h3>
<div class="date">{{ p.get('published_at','')[:10] }}</div>
</div></div>{% endfor %}
</div>{% endif %}
{% else %}
<div class="empty"><h2>&#x1F3AC; Show Starting Soon</h2><p>The hottest content is loading. Check back soon!</p></div>
{% endif %}
{{ ad_slot_3 }}
</main>
<footer>&copy; {{ year }} {{ blog_title }} | <a href="{{ blog_url }}/sitemap.xml">Sitemap</a></footer>
{% if onesignal_app_id %}<script src="https://cdn.onesignal.com/sdks/web/v16/OneSignalSDK.page.js" defer></script><script>window.OneSignalDeferred=window.OneSignalDeferred||[];OneSignalDeferred.push(async function(OneSignal){await OneSignal.init({appId:"{{ onesignal_app_id }}",notifyButton:{enable:true}});});</script>{% endif %}
<!-- Cloudflare Web Analytics --><script defer src='https://static.cloudflareinsights.com/beacon.min.js' data-cf-beacon='{"token": "be17bfc005774526803b0ef32264a47e"}'></script><!-- End Cloudflare Web Analytics -->
</body></html>"""

# ── Variant B / C templates ─────────────────────────────────────────────────────

_CRYPTO_TEMPLATE_B = """\
<!DOCTYPE html>
<html lang="{{ language }}" {% if rtl %}dir="rtl"{% endif %}>
<head>
<base href="{{ blog_url }}/">
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{{ blog_title }}</title>
<meta name="description" content="{{ meta_desc }}">
<link rel="canonical" href="{{ blog_url }}">
<link href="https://fonts.googleapis.com/css2?family=Exo+2:wght@400;600;700;800&family=Inter:wght@300;400;500&display=swap" rel="stylesheet">
{{ ad_head_code }}
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{background:#0a0a1a;color:#c9d1d9;font-family:'Inter',sans-serif;line-height:1.7}
a{color:{{ accent_color }};text-decoration:none}
.hdr{background:linear-gradient(135deg,#0d0d2b 0%,#1a0a2e 100%);padding:0 24px;border-bottom:1px solid rgba(100,100,200,0.3)}
.hdr-inner{max-width:1200px;margin:0 auto;display:flex;align-items:center;justify-content:space-between;height:60px}
.logo{font-family:'Exo 2',sans-serif;font-size:1.5rem;font-weight:800;color:#fff;letter-spacing:-0.5px}
.logo-dot{color:{{ accent_color }}}
.nav a{color:rgba(255,255,255,.65);font-size:.8rem;font-weight:600;margin-left:20px;text-transform:uppercase;letter-spacing:.06em;transition:.2s}
.nav a:hover{color:{{ accent_color }}}
.hero-band{background:rgba(255,255,255,.04);border-bottom:1px solid rgba(255,255,255,.06);padding:10px 24px}
.hero-band-inner{max-width:1200px;margin:0 auto;font-family:'Exo 2',sans-serif;font-size:.75rem;font-weight:700;color:{{ accent_color }};text-transform:uppercase;letter-spacing:.15em}
.wrap{max-width:1200px;margin:0 auto;padding:32px 24px}
.sec-label{font-family:'Exo 2',sans-serif;font-size:.7rem;font-weight:800;color:{{ accent_color }};text-transform:uppercase;letter-spacing:.2em;margin-bottom:20px;display:flex;align-items:center;gap:10px}
.sec-label::after{content:"";flex:1;height:1px;background:linear-gradient(90deg,{{ accent_color }},transparent)}
.grid{display:grid;grid-template-columns:repeat(3,1fr);gap:20px}
@media(max-width:800px){.grid{grid-template-columns:1fr}}
.card{background:#0f0f24;border:1px solid rgba(255,255,255,.07);border-radius:8px;overflow:hidden;transition:transform .2s,border-color .2s}
.card:hover{transform:translateY(-4px);border-color:{{ accent_color }}}
.card img{width:100%;height:190px;object-fit:cover;opacity:.85}
.card-body{padding:16px}
.card-cat{font-family:'Exo 2',sans-serif;font-size:.62rem;font-weight:700;color:{{ accent_color }};text-transform:uppercase;letter-spacing:.12em;margin-bottom:6px}
.card h3{font-family:'Exo 2',sans-serif;font-size:1rem;font-weight:700;line-height:1.3;color:#e6edf3;margin-bottom:8px}
.card h3 a{color:#e6edf3}.card h3 a:hover{color:{{ accent_color }}}
.card-date{font-size:.68rem;color:#8b949e}
.empty{text-align:center;padding:80px 20px;color:#8b949e}
.empty h2{font-family:'Exo 2',sans-serif;font-size:1.3rem;color:{{ accent_color }};margin-bottom:8px}
footer{border-top:1px solid rgba(255,255,255,.06);margin-top:60px;padding:20px 24px;text-align:center;color:#8b949e;font-size:.75rem}
</style></head>
<body>
<header class="hdr"><div class="hdr-inner">
<div class="logo">{{ blog_title[:3] }}<span class="logo-dot">.</span>{{ blog_title[3:] }}</div>
<nav class="nav"><a href="{{ blog_url }}/">Home</a><a href="#">Markets</a><a href="#">DeFi</a><a href="{{ blog_url }}/sitemap.xml">Sitemap</a></nav>
</div></header>
<div class="hero-band"><div class="hero-band-inner">◆ {{ blog_title }} — Crypto Intelligence Network ◆</div></div>
{{ ad_slot_1 }}
<main class="wrap">
{% if posts %}
<div class="sec-label">Latest Coverage</div>
<div class="grid">
{% for p in posts %}
<div class="card">
{% if p.featured_image_url %}<img src="{{ p.featured_image_url }}" alt="{{ p.title }}" loading="lazy">{% endif %}
<div class="card-body">
<div class="card-cat">{{ p.get('category','Crypto') }}</div>
<h3><a href="{{ blog_url }}/posts/{{ p.slug }}.html">{{ p.title }}</a></h3>
<div class="card-date">{{ p.get('published_at','')[:10] }}</div>
</div></div>{% endfor %}
</div>
{% else %}
<div class="empty"><h2>Intelligence Loading</h2><p>Crypto market analysis arriving soon.</p></div>
{% endif %}
{{ ad_slot_3 }}
</main>
<footer>© {{ year }} {{ blog_title }} — Crypto Intelligence | <a href="{{ blog_url }}/sitemap.xml">Sitemap</a></footer>
{% if onesignal_app_id %}<script src="https://cdn.onesignal.com/sdks/web/v16/OneSignalSDK.page.js" defer></script><script>window.OneSignalDeferred=window.OneSignalDeferred||[];OneSignalDeferred.push(async function(OneSignal){await OneSignal.init({appId:"{{ onesignal_app_id }}",notifyButton:{enable:true}});});</script>{% endif %}
<!-- Cloudflare Web Analytics --><script defer src='https://static.cloudflareinsights.com/beacon.min.js' data-cf-beacon='{"token": "be17bfc005774526803b0ef32264a47e"}'></script><!-- End Cloudflare Web Analytics -->
</body></html>"""

_CRYPTO_TEMPLATE_C = """\
<!DOCTYPE html>
<html lang="{{ language }}" {% if rtl %}dir="rtl"{% endif %}>
<head>
<base href="{{ blog_url }}/">
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{{ blog_title }}</title>
<meta name="description" content="{{ meta_desc }}">
<link rel="canonical" href="{{ blog_url }}">
<link href="https://fonts.googleapis.com/css2?family=DM+Serif+Display&family=DM+Sans:wght@300;400;500;700&display=swap" rel="stylesheet">
{{ ad_head_code }}
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{background:#111827;color:#d1d5db;font-family:'DM Sans',sans-serif;line-height:1.7}
a{color:{{ accent_color }};text-decoration:none}
.hdr{padding:16px 24px;border-bottom:1px solid #1f2937}
.hdr-inner{max-width:1100px;margin:0 auto;display:flex;align-items:center;justify-content:space-between}
.logo{font-family:'DM Serif Display',serif;font-size:1.7rem;color:#f9fafb;letter-spacing:-0.5px}
.logo span{color:{{ accent_color }}}
.nav a{color:#6b7280;font-size:.82rem;margin-left:18px;transition:.2s}
.nav a:hover{color:{{ accent_color }}}
.accent-strip{height:3px;background:linear-gradient(90deg,{{ accent_color }},transparent)}
.wrap{max-width:1100px;margin:0 auto;padding:36px 24px;display:grid;grid-template-columns:1fr 280px;gap:40px}
@media(max-width:800px){.wrap{grid-template-columns:1fr}}
.side-col{border-left:1px solid #1f2937;padding-left:28px}
@media(max-width:800px){.side-col{border-left:none;padding-left:0;border-top:1px solid #1f2937;padding-top:24px}}
.sec-title{font-family:'DM Serif Display',serif;font-size:1.1rem;color:#f9fafb;margin-bottom:18px;padding-bottom:8px;border-bottom:2px solid {{ accent_color }};display:inline-block}
.post-row{display:flex;gap:14px;padding:14px 0;border-bottom:1px solid #1f2937}
.post-row:last-child{border-bottom:none}
.post-row img{width:80px;height:60px;object-fit:cover;border-radius:4px;flex-shrink:0}
.post-row h3{font-family:'DM Serif Display',serif;font-size:.95rem;line-height:1.3;color:#f9fafb;margin-bottom:4px}
.post-row h3 a{color:#f9fafb}.post-row h3 a:hover{color:{{ accent_color }}}
.post-row .date{font-size:.68rem;color:#6b7280}
.side-item{padding:10px 0;border-bottom:1px solid #1f2937}
.side-item:last-child{border-bottom:none}
.side-item h4{font-family:'DM Serif Display',serif;font-size:.88rem;color:#f9fafb;line-height:1.3}
.side-item h4 a{color:#f9fafb}.side-item h4 a:hover{color:{{ accent_color }}}
.side-item .date{font-size:.65rem;color:#6b7280;margin-top:3px}
.empty{text-align:center;padding:60px 20px;color:#6b7280}
.empty h2{font-family:'DM Serif Display',serif;font-size:1.4rem;color:#f9fafb;margin-bottom:8px}
footer{margin-top:48px;padding:20px 24px;text-align:center;color:#6b7280;font-size:.75rem;border-top:1px solid #1f2937}
</style></head>
<body>
<header class="hdr"><div class="hdr-inner">
<div class="logo">{{ blog_title[:2] }}<span>{{ blog_title[2:] }}</span></div>
<nav class="nav"><a href="{{ blog_url }}/">Home</a><a href="#">Analysis</a><a href="#">Charts</a><a href="{{ blog_url }}/sitemap.xml">Sitemap</a></nav>
</div></header>
<div class="accent-strip"></div>
{{ ad_slot_1 }}
<div class="wrap">
<main class="main-col">
{% if posts %}
<div class="sec-title">Latest Analysis</div>
{% for p in posts[:6] %}
<div class="post-row">
{% if p.featured_image_url %}<img src="{{ p.featured_image_url }}" alt="{{ p.title }}" loading="lazy">{% endif %}
<div><h3><a href="{{ blog_url }}/posts/{{ p.slug }}.html">{{ p.title }}</a></h3>
<div class="date">{{ p.get('published_at','')[:10] }}</div></div>
</div>{% endfor %}
{% else %}
<div class="empty"><h2>Analysis Incoming</h2><p>Deep-dive crypto content arriving soon.</p></div>
{% endif %}
</main>
<aside class="side-col">
<div class="sec-title">Quick Reads</div>
{% if posts %}{% for p in posts[6:] %}<div class="side-item">
<h4><a href="{{ blog_url }}/posts/{{ p.slug }}.html">{{ p.title }}</a></h4>
<div class="date">{{ p.get('published_at','')[:10] }}</div>
</div>{% endfor %}{% endif %}
{{ ad_slot_3 }}
</aside>
</div>
<footer>© {{ year }} {{ blog_title }} | <a href="{{ blog_url }}/sitemap.xml">Sitemap</a></footer>
{% if onesignal_app_id %}<script src="https://cdn.onesignal.com/sdks/web/v16/OneSignalSDK.page.js" defer></script><script>window.OneSignalDeferred=window.OneSignalDeferred||[];OneSignalDeferred.push(async function(OneSignal){await OneSignal.init({appId:"{{ onesignal_app_id }}",notifyButton:{enable:true}});});</script>{% endif %}
<!-- Cloudflare Web Analytics --><script defer src='https://static.cloudflareinsights.com/beacon.min.js' data-cf-beacon='{"token": "be17bfc005774526803b0ef32264a47e"}'></script><!-- End Cloudflare Web Analytics -->
</body></html>"""

_FINANCE_TEMPLATE_B = """\
<!DOCTYPE html>
<html lang="{{ language }}" {% if rtl %}dir="rtl"{% endif %}>
<head>
<base href="{{ blog_url }}/">
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{{ blog_title }}</title>
<meta name="description" content="{{ meta_desc }}">
<link rel="canonical" href="{{ blog_url }}">
<link href="https://fonts.googleapis.com/css2?family=Cormorant+Garamond:wght@400;600;700&family=Inter:wght@300;400;500&display=swap" rel="stylesheet">
{{ ad_head_code }}
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{background:#0f1117;color:#c9b99a;font-family:'Inter',sans-serif;line-height:1.75}
a{color:{{ accent_color }};text-decoration:none}
.hdr{background:#0a0c12;border-bottom:1px solid rgba(255,255,255,.06);padding:0 24px}
.hdr-inner{max-width:1200px;margin:0 auto;display:flex;align-items:center;justify-content:space-between;height:64px}
.logo{font-family:'Cormorant Garamond',serif;font-size:1.9rem;font-weight:700;color:#f0e6d3;letter-spacing:.5px}
.logo-accent{color:{{ accent_color }}}
.nav a{color:#8b7e6a;font-size:.78rem;font-weight:500;margin-left:22px;text-transform:uppercase;letter-spacing:.1em;transition:.2s}
.nav a:hover{color:{{ accent_color }}}
.mkt-bar{background:#070a10;border-bottom:1px solid rgba(255,255,255,.04);padding:7px 24px;text-align:center;font-size:.72rem;color:#8b7e6a;letter-spacing:.05em}
.mkt-bar span{color:{{ accent_color }};margin:0 14px}
.wrap{max-width:1200px;margin:0 auto;padding:36px 24px}
.rule{display:flex;align-items:center;gap:12px;margin:0 0 20px}
.rule h2{font-family:'Cormorant Garamond',serif;font-size:1.1rem;font-weight:600;color:#f0e6d3;white-space:nowrap;text-transform:uppercase;letter-spacing:.12em}
.rule::after{content:"";flex:1;height:1px;background:linear-gradient(90deg,{{ accent_color }},transparent)}
.featured{display:grid;grid-template-columns:1.5fr 1fr;gap:28px;margin-bottom:36px}
@media(max-width:700px){.featured{grid-template-columns:1fr}}
.feat-img{width:100%;height:300px;object-fit:cover;opacity:.88}
.feat-body{padding:4px 0}
.feat-cat{font-size:.65rem;font-weight:600;color:{{ accent_color }};text-transform:uppercase;letter-spacing:.12em;margin-bottom:8px}
.feat-title{font-family:'Cormorant Garamond',serif;font-size:1.7rem;font-weight:700;line-height:1.2;color:#f0e6d3;margin-bottom:10px}
.feat-title a{color:#f0e6d3}.feat-title a:hover{color:{{ accent_color }}}
.feat-meta{font-size:.72rem;color:#8b7e6a;border-top:1px solid rgba(255,255,255,.06);padding-top:10px;margin-top:10px}
.list-row{display:flex;gap:14px;padding:12px 0;border-bottom:1px solid rgba(255,255,255,.05)}
.list-row:last-child{border-bottom:none}
.list-row img{width:75px;height:55px;object-fit:cover;flex-shrink:0;opacity:.85}
.list-title{font-family:'Cormorant Garamond',serif;font-size:.98rem;font-weight:600;color:#d4c4a8;line-height:1.3}
.list-title a{color:#d4c4a8}.list-title a:hover{color:{{ accent_color }}}
.list-meta{font-size:.65rem;color:#8b7e6a;margin-top:4px}
.empty{text-align:center;padding:80px 20px;color:#8b7e6a}
.empty h2{font-family:'Cormorant Garamond',serif;font-size:1.6rem;color:#f0e6d3;margin-bottom:8px}
footer{background:#070a10;border-top:1px solid rgba(255,255,255,.04);padding:20px;text-align:center;color:#8b7e6a;font-size:.72rem;margin-top:60px}
</style></head>
<body>
<header class="hdr"><div class="hdr-inner">
<div class="logo">{{ blog_title[:5] }}<span class="logo-accent">{{ blog_title[5:] }}</span></div>
<nav class="nav"><a href="{{ blog_url }}/">Home</a><a href="#">Portfolio</a><a href="#">Macro</a><a href="{{ blog_url }}/sitemap.xml">Sitemap</a></nav>
</div></header>
<div class="mkt-bar">INDICES:<span>S&amp;P 500 ▲</span><span>NASDAQ ▲</span><span>GOLD ▲</span><span>YIELDS ▼</span></div>
{{ ad_slot_1 }}
<main class="wrap">
{% if posts %}
{% set p = posts[0] %}
<div class="rule"><h2>Top Story</h2></div>
<div class="featured">
<div>{% if p.featured_image_url %}<img class="feat-img" src="{{ p.featured_image_url }}" alt="{{ p.title }}">{% endif %}</div>
<div class="feat-body">
<div class="feat-cat">{{ p.get('category','Finance') }}</div>
<div class="feat-title"><a href="{{ blog_url }}/posts/{{ p.slug }}.html">{{ p.title }}</a></div>
<div class="feat-meta">{{ p.get('published_at','')[:10] }}</div>
</div></div>
{% if posts|length > 1 %}
<div class="rule"><h2>More</h2></div>
{% for p in posts[1:] %}<div class="list-row">
{% if p.featured_image_url %}<img src="{{ p.featured_image_url }}" alt="{{ p.title }}">{% endif %}
<div><div class="list-title"><a href="{{ blog_url }}/posts/{{ p.slug }}.html">{{ p.title }}</a></div>
<div class="list-meta">{{ p.get('published_at','')[:10] }}</div></div>
</div>{% endfor %}{% endif %}
{% else %}
<div class="empty"><h2>Markets Opening Soon</h2><p>Premium financial intelligence loading.</p></div>
{% endif %}
{{ ad_slot_3 }}
</main>
<footer>© {{ year }} {{ blog_title }} — Premium Financial Intelligence</footer>
{% if onesignal_app_id %}<script src="https://cdn.onesignal.com/sdks/web/v16/OneSignalSDK.page.js" defer></script><script>window.OneSignalDeferred=window.OneSignalDeferred||[];OneSignalDeferred.push(async function(OneSignal){await OneSignal.init({appId:"{{ onesignal_app_id }}",notifyButton:{enable:true}});});</script>{% endif %}
<!-- Cloudflare Web Analytics --><script defer src='https://static.cloudflareinsights.com/beacon.min.js' data-cf-beacon='{"token": "be17bfc005774526803b0ef32264a47e"}'></script><!-- End Cloudflare Web Analytics -->
</body></html>"""

_FINANCE_TEMPLATE_C = """\
<!DOCTYPE html>
<html lang="{{ language }}" {% if rtl %}dir="rtl"{% endif %}>
<head>
<base href="{{ blog_url }}/">
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{{ blog_title }}</title>
<meta name="description" content="{{ meta_desc }}">
<link rel="canonical" href="{{ blog_url }}">
<link href="https://fonts.googleapis.com/css2?family=Libre+Baskerville:wght@400;700&family=Source+Sans+3:wght@400;600;700&display=swap" rel="stylesheet">
{{ ad_head_code }}
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{background:#fff;color:#1a1a1a;font-family:'Source Sans 3',sans-serif;line-height:1.65}
a{color:{{ accent_color }};text-decoration:none}
.top-bar{height:4px;background:{{ accent_color }}}
.hdr{padding:18px 24px;border-bottom:1px solid #e8e8e8}
.hdr-inner{max-width:1100px;margin:0 auto;display:flex;align-items:center;justify-content:space-between}
.logo{font-family:'Libre Baskerville',serif;font-size:1.6rem;font-weight:700;color:#1a1a1a}
.nav a{color:#555;font-size:.82rem;font-weight:600;margin-left:18px;padding-bottom:2px;border-bottom:2px solid transparent;transition:.2s}
.nav a:hover{color:{{ accent_color }};border-bottom-color:{{ accent_color }}}
.wrap{max-width:1100px;margin:0 auto;padding:32px 24px}
.lead-grid{display:grid;grid-template-columns:1.8fr 1fr;gap:32px;margin-bottom:40px;padding-bottom:40px;border-bottom:2px solid #f0f0f0}
@media(max-width:700px){.lead-grid{grid-template-columns:1fr}}
.lead-img{width:100%;height:280px;object-fit:cover;margin-bottom:14px}
.tag{display:inline-block;background:{{ accent_color }};color:#fff;font-size:.62rem;font-weight:700;padding:2px 8px;border-radius:2px;text-transform:uppercase;letter-spacing:.08em;margin-bottom:8px}
.lead-h{font-family:'Libre Baskerville',serif;font-size:1.5rem;font-weight:700;line-height:1.25;color:#1a1a1a;margin-bottom:8px}
.lead-h a{color:#1a1a1a}.lead-h a:hover{color:{{ accent_color }}}
.lead-date{font-size:.72rem;color:#aaa}
.side-list{display:flex;flex-direction:column;gap:0}
.side-item{padding:10px 0;border-bottom:1px solid #f0f0f0}
.side-item:first-child{padding-top:0}
.side-item h4{font-family:'Libre Baskerville',serif;font-size:.92rem;font-weight:700;line-height:1.3;color:#1a1a1a}
.side-item h4 a{color:#1a1a1a}.side-item h4 a:hover{color:{{ accent_color }}}
.side-item .date{font-size:.65rem;color:#aaa;margin-top:3px}
.card-row{display:grid;grid-template-columns:repeat(3,1fr);gap:24px}
@media(max-width:700px){.card-row{grid-template-columns:1fr}}
.mini-card img{width:100%;height:140px;object-fit:cover;margin-bottom:10px}
.mini-card .tag{margin-bottom:6px}
.mini-card h3{font-family:'Libre Baskerville',serif;font-size:.92rem;font-weight:700;line-height:1.3;color:#1a1a1a}
.mini-card h3 a{color:#1a1a1a}.mini-card h3 a:hover{color:{{ accent_color }}}
.mini-card .date{font-size:.65rem;color:#aaa;margin-top:4px}
.sec-head{font-family:'Libre Baskerville',serif;font-size:.9rem;font-weight:700;text-transform:uppercase;letter-spacing:.1em;color:#1a1a1a;margin:0 0 16px;padding-bottom:8px;border-bottom:2px solid {{ accent_color }};display:inline-block}
.empty{text-align:center;padding:70px 20px;color:#aaa}
.empty h2{font-family:'Libre Baskerville',serif;font-size:1.4rem;color:#1a1a1a;margin-bottom:8px}
footer{background:#1a1a1a;color:#888;text-align:center;padding:18px;font-size:.72rem;margin-top:50px}
footer a{color:{{ accent_color }}}
</style></head>
<body>
<div class="top-bar"></div>
<header class="hdr"><div class="hdr-inner">
<div class="logo">{{ blog_title }}</div>
<nav class="nav"><a href="{{ blog_url }}/">Home</a><a href="#">Economy</a><a href="#">Markets</a><a href="{{ blog_url }}/sitemap.xml">Sitemap</a></nav>
</div></header>
{{ ad_slot_1 }}
<main class="wrap">
{% if posts %}
{% set p = posts[0] %}
<div class="lead-grid">
<div>{% if p.featured_image_url %}<img class="lead-img" src="{{ p.featured_image_url }}" alt="{{ p.title }}">{% endif %}
<span class="tag">{{ p.get('category','Finance') }}</span>
<div class="lead-h"><a href="{{ blog_url }}/posts/{{ p.slug }}.html">{{ p.title }}</a></div>
<div class="lead-date">{{ p.get('published_at','')[:10] }}</div>
</div>
<div class="side-list">{% for p in posts[1:5] %}<div class="side-item">
<h4><a href="{{ blog_url }}/posts/{{ p.slug }}.html">{{ p.title }}</a></h4>
<div class="date">{{ p.get('published_at','')[:10] }}</div>
</div>{% endfor %}</div>
</div>
{% if posts|length > 5 %}
<div class="sec-head">More Articles</div>
<div class="card-row">
{% for p in posts[5:] %}<div class="mini-card">
{% if p.featured_image_url %}<img src="{{ p.featured_image_url }}" alt="{{ p.title }}">{% endif %}
<span class="tag">{{ p.get('category','Finance') }}</span>
<h3><a href="{{ blog_url }}/posts/{{ p.slug }}.html">{{ p.title }}</a></h3>
<div class="date">{{ p.get('published_at','')[:10] }}</div>
</div>{% endfor %}</div>{% endif %}
{% else %}
<div class="empty"><h2>Content Coming Soon</h2><p>Financial analysis launching shortly.</p></div>
{% endif %}
{{ ad_slot_3 }}
</main>
<footer>© {{ year }} {{ blog_title }} | <a href="{{ blog_url }}/sitemap.xml">Sitemap</a></footer>
{% if onesignal_app_id %}<script src="https://cdn.onesignal.com/sdks/web/v16/OneSignalSDK.page.js" defer></script><script>window.OneSignalDeferred=window.OneSignalDeferred||[];OneSignalDeferred.push(async function(OneSignal){await OneSignal.init({appId:"{{ onesignal_app_id }}",notifyButton:{enable:true}});});</script>{% endif %}
<!-- Cloudflare Web Analytics --><script defer src='https://static.cloudflareinsights.com/beacon.min.js' data-cf-beacon='{"token": "be17bfc005774526803b0ef32264a47e"}'></script><!-- End Cloudflare Web Analytics -->
</body></html>"""

_HEALTH_TEMPLATE_B = """\
<!DOCTYPE html>
<html lang="{{ language }}" {% if rtl %}dir="rtl"{% endif %}>
<head>
<base href="{{ blog_url }}/">
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{{ blog_title }}</title>
<meta name="description" content="{{ meta_desc }}">
<link rel="canonical" href="{{ blog_url }}">
<link href="https://fonts.googleapis.com/css2?family=Montserrat:wght@400;600;700;800;900&display=swap" rel="stylesheet">
{{ ad_head_code }}
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{background:#fff;color:#1a1a1a;font-family:'Montserrat',sans-serif;line-height:1.6}
a{color:{{ accent_color }};text-decoration:none}
.hdr{background:#fff;border-bottom:3px solid {{ accent_color }};padding:0 24px;position:sticky;top:0;z-index:100}
.hdr-inner{max-width:1200px;margin:0 auto;display:flex;align-items:center;justify-content:space-between;height:58px}
.logo{font-size:1.35rem;font-weight:900;color:#1a1a1a;text-transform:uppercase;letter-spacing:-0.5px}
.logo span{color:{{ accent_color }}}
.nav a{color:#444;font-size:.75rem;font-weight:700;margin-left:16px;text-transform:uppercase;letter-spacing:.06em;transition:.2s}
.nav a:hover{color:{{ accent_color }}}
.hero-strip{background:{{ accent_color }};padding:10px 24px}
.hero-strip-inner{max-width:1200px;margin:0 auto;display:flex;gap:24px;overflow-x:auto}
.strip-tag{background:rgba(255,255,255,.25);color:#fff;font-size:.68rem;font-weight:700;padding:3px 12px;border-radius:2px;text-transform:uppercase;letter-spacing:.06em;white-space:nowrap}
.wrap{max-width:1200px;margin:0 auto;padding:28px 24px}
.sec-bar{display:flex;align-items:center;gap:0;margin-bottom:20px}
.sec-bar-label{background:{{ accent_color }};color:#fff;font-size:.7rem;font-weight:700;padding:5px 14px;text-transform:uppercase;letter-spacing:.1em}
.sec-bar-line{flex:1;height:2px;background:#f0f0f0}
.hero-card{display:grid;grid-template-columns:1.4fr 1fr;gap:0;margin-bottom:28px;border:2px solid #f0f0f0;border-radius:4px;overflow:hidden}
@media(max-width:700px){.hero-card{grid-template-columns:1fr}}
.hero-card img{width:100%;height:100%;min-height:260px;object-fit:cover}
.hero-body{padding:24px}
.cat-tag{display:inline-block;background:{{ accent_color }};color:#fff;font-size:.62rem;font-weight:700;padding:2px 8px;text-transform:uppercase;letter-spacing:.08em;margin-bottom:10px}
.hero-body h2{font-size:1.4rem;font-weight:800;line-height:1.2;color:#1a1a1a;margin-bottom:8px}
.hero-body h2 a{color:#1a1a1a}.hero-body h2 a:hover{color:{{ accent_color }}}
.hero-body .meta{font-size:.72rem;color:#aaa;margin-top:10px}
.grid{display:grid;grid-template-columns:repeat(3,1fr);gap:16px}
@media(max-width:700px){.grid{grid-template-columns:1fr}}
.card{border:2px solid #f0f0f0;border-radius:4px;overflow:hidden;transition:border-color .2s}
.card:hover{border-color:{{ accent_color }}}
.card img{width:100%;height:160px;object-fit:cover}
.card-body{padding:12px}
.card h3{font-size:.9rem;font-weight:700;line-height:1.3;color:#1a1a1a}
.card h3 a{color:#1a1a1a}.card h3 a:hover{color:{{ accent_color }}}
.card .meta{font-size:.65rem;color:#aaa;margin-top:6px}
.empty{text-align:center;padding:70px 20px;color:#aaa}
.empty h2{font-size:1.3rem;font-weight:800;text-transform:uppercase;color:{{ accent_color }};margin-bottom:8px}
footer{background:#1a1a1a;color:#888;text-align:center;padding:18px;font-size:.72rem;margin-top:48px}
footer a{color:{{ accent_color }}}
</style></head>
<body>
<header class="hdr"><div class="hdr-inner">
<div class="logo"><span>{{ blog_title[:3] }}</span>{{ blog_title[3:] }}</div>
<nav class="nav"><a href="{{ blog_url }}/">Home</a><a href="#">Workouts</a><a href="#">Nutrition</a><a href="#">Goals</a></nav>
</div></header>
<div class="hero-strip"><div class="hero-strip-inner">
<span class="strip-tag">Fitness</span><span class="strip-tag">Strength</span><span class="strip-tag">Nutrition</span><span class="strip-tag">Recovery</span><span class="strip-tag">HIIT</span>
</div></div>
{{ ad_slot_1 }}
<main class="wrap">
{% if posts %}
{% set p = posts[0] %}
<div class="sec-bar"><span class="sec-bar-label">Featured</span><div class="sec-bar-line"></div></div>
<div class="hero-card">
{% if p.featured_image_url %}<img src="{{ p.featured_image_url }}" alt="{{ p.title }}">{% endif %}
<div class="hero-body">
<span class="cat-tag">{{ p.get('category','Health') }}</span>
<h2><a href="{{ blog_url }}/posts/{{ p.slug }}.html">{{ p.title }}</a></h2>
<div class="meta">{{ p.get('published_at','')[:10] }}</div>
</div></div>
{% if posts|length > 1 %}
<div class="sec-bar" style="margin-top:28px"><span class="sec-bar-label">More Articles</span><div class="sec-bar-line"></div></div>
<div class="grid">
{% for p in posts[1:] %}<div class="card">
{% if p.featured_image_url %}<img src="{{ p.featured_image_url }}" alt="{{ p.title }}">{% endif %}
<div class="card-body">
<span class="cat-tag">{{ p.get('category','Health') }}</span>
<h3><a href="{{ blog_url }}/posts/{{ p.slug }}.html">{{ p.title }}</a></h3>
<div class="meta">{{ p.get('published_at','')[:10] }}</div>
</div></div>{% endfor %}
</div>{% endif %}
{% else %}
<div class="empty"><h2>Train. Eat. Recover.</h2><p>Your fitness content is loading. Check back soon!</p></div>
{% endif %}
{{ ad_slot_3 }}
</main>
<footer>© {{ year }} {{ blog_title }} | <a href="{{ blog_url }}/sitemap.xml">Sitemap</a></footer>
{% if onesignal_app_id %}<script src="https://cdn.onesignal.com/sdks/web/v16/OneSignalSDK.page.js" defer></script><script>window.OneSignalDeferred=window.OneSignalDeferred||[];OneSignalDeferred.push(async function(OneSignal){await OneSignal.init({appId:"{{ onesignal_app_id }}",notifyButton:{enable:true}});});</script>{% endif %}
<!-- Cloudflare Web Analytics --><script defer src='https://static.cloudflareinsights.com/beacon.min.js' data-cf-beacon='{"token": "be17bfc005774526803b0ef32264a47e"}'></script><!-- End Cloudflare Web Analytics -->
</body></html>"""

_HEALTH_TEMPLATE_C = """\
<!DOCTYPE html>
<html lang="{{ language }}" {% if rtl %}dir="rtl"{% endif %}>
<head>
<base href="{{ blog_url }}/">
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{{ blog_title }}</title>
<meta name="description" content="{{ meta_desc }}">
<link rel="canonical" href="{{ blog_url }}">
<link href="https://fonts.googleapis.com/css2?family=Raleway:wght@400;500;600;700;800&family=Open+Sans:wght@400;600&display=swap" rel="stylesheet">
{{ ad_head_code }}
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{background:#f0f4f8;color:#2d3748;font-family:'Open Sans',sans-serif;line-height:1.7}
a{color:{{ accent_color }};text-decoration:none}
.hdr{background:#fff;border-bottom:1px solid #e2e8f0;padding:0 24px}
.hdr-inner{max-width:1100px;margin:0 auto;display:flex;align-items:center;justify-content:space-between;height:60px}
.logo{font-family:'Raleway',sans-serif;font-size:1.4rem;font-weight:800;color:#1a202c;letter-spacing:-0.3px}
.logo-plus{color:{{ accent_color }};font-size:1.6rem;vertical-align:-2px;margin-right:2px}
.nav a{color:#718096;font-size:.8rem;font-weight:600;margin-left:16px;transition:.2s}
.nav a:hover{color:{{ accent_color }}}
.wrap{max-width:1100px;margin:0 auto;padding:28px 24px}
.info-bar{background:#fff;border:1px solid #e2e8f0;border-left:4px solid {{ accent_color }};padding:12px 18px;margin-bottom:28px;border-radius:0 6px 6px 0;font-size:.82rem;color:#718096}
.info-bar strong{color:{{ accent_color }};font-weight:700}
.two-col{display:grid;grid-template-columns:1.4fr 1fr;gap:24px;margin-bottom:28px}
@media(max-width:700px){.two-col{grid-template-columns:1fr}}
.card{background:#fff;border:1px solid #e2e8f0;border-radius:8px;overflow:hidden}
.card img{width:100%;height:200px;object-fit:cover}
.card-body{padding:16px}
.badge{display:inline-flex;align-items:center;gap:4px;background:#ebf8f4;color:{{ accent_color }};font-size:.62rem;font-weight:700;padding:3px 8px;border-radius:4px;text-transform:uppercase;letter-spacing:.06em;margin-bottom:8px}
.card h3{font-family:'Raleway',sans-serif;font-size:1rem;font-weight:700;line-height:1.3;color:#1a202c;margin-bottom:6px}
.card h3 a{color:#1a202c}.card h3 a:hover{color:{{ accent_color }}}
.card .date{font-size:.68rem;color:#a0aec0}
.side-list{display:flex;flex-direction:column;gap:12px}
.side-card{background:#fff;border:1px solid #e2e8f0;border-radius:8px;padding:14px;display:flex;gap:12px}
.side-card img{width:70px;height:52px;object-fit:cover;border-radius:4px;flex-shrink:0}
.side-card h4{font-family:'Raleway',sans-serif;font-size:.88rem;font-weight:700;line-height:1.3;color:#1a202c}
.side-card h4 a{color:#1a202c}.side-card h4 a:hover{color:{{ accent_color }}}
.side-card .date{font-size:.65rem;color:#a0aec0;margin-top:3px}
.three-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:16px;margin-top:8px}
@media(max-width:700px){.three-grid{grid-template-columns:1fr}}
.sec-h{font-family:'Raleway',sans-serif;font-size:.8rem;font-weight:800;color:#1a202c;text-transform:uppercase;letter-spacing:.1em;margin:24px 0 14px;padding-left:10px;border-left:3px solid {{ accent_color }}}
.empty{text-align:center;padding:70px 20px;background:#fff;border-radius:12px;border:1px solid #e2e8f0}
.empty h2{font-family:'Raleway',sans-serif;font-size:1.3rem;color:#1a202c;margin-bottom:8px}
.empty p{color:#a0aec0;font-size:.88rem}
footer{background:#2d3748;color:#a0aec0;text-align:center;padding:18px;font-size:.72rem;margin-top:48px}
footer a{color:{{ accent_color }}}
</style></head>
<body>
<header class="hdr"><div class="hdr-inner">
<div class="logo"><span class="logo-plus">+</span>{{ blog_title }}</div>
<nav class="nav"><a href="{{ blog_url }}/">Home</a><a href="#">Wellness</a><a href="#">Research</a><a href="{{ blog_url }}/sitemap.xml">Sitemap</a></nav>
</div></header>
{{ ad_slot_1 }}
<main class="wrap">
<div class="info-bar"><strong>Evidence-based</strong> — All content reviewed for accuracy and medical relevance.</div>
{% if posts %}
{% set p = posts[0] %}
<div class="two-col">
<div class="card">
{% if p.featured_image_url %}<img src="{{ p.featured_image_url }}" alt="{{ p.title }}">{% endif %}
<div class="card-body">
<span class="badge">{{ p.get('category','Health') }}</span>
<h3><a href="{{ blog_url }}/posts/{{ p.slug }}.html">{{ p.title }}</a></h3>
<div class="date">{{ p.get('published_at','')[:10] }}</div>
</div></div>
<div class="side-list">
{% for p in posts[1:5] %}<div class="side-card">
{% if p.featured_image_url %}<img src="{{ p.featured_image_url }}" alt="{{ p.title }}">{% endif %}
<div><h4><a href="{{ blog_url }}/posts/{{ p.slug }}.html">{{ p.title }}</a></h4>
<div class="date">{{ p.get('published_at','')[:10] }}</div></div>
</div>{% endfor %}
</div></div>
{% if posts|length > 5 %}
<div class="sec-h">All Articles</div>
<div class="three-grid">
{% for p in posts[5:] %}<div class="card">
{% if p.featured_image_url %}<img src="{{ p.featured_image_url }}" alt="{{ p.title }}">{% endif %}
<div class="card-body">
<span class="badge">{{ p.get('category','Health') }}</span>
<h3><a href="{{ blog_url }}/posts/{{ p.slug }}.html">{{ p.title }}</a></h3>
<div class="date">{{ p.get('published_at','')[:10] }}</div>
</div></div>{% endfor %}
</div>{% endif %}
{% else %}
<div class="empty"><h2>Content Loading</h2><p>Evidence-based health content launching soon.</p></div>
{% endif %}
{{ ad_slot_3 }}
</main>
<footer>© {{ year }} {{ blog_title }} | <a href="{{ blog_url }}/sitemap.xml">Sitemap</a></footer>
{% if onesignal_app_id %}<script src="https://cdn.onesignal.com/sdks/web/v16/OneSignalSDK.page.js" defer></script><script>window.OneSignalDeferred=window.OneSignalDeferred||[];OneSignalDeferred.push(async function(OneSignal){await OneSignal.init({appId:"{{ onesignal_app_id }}",notifyButton:{enable:true}});});</script>{% endif %}
<!-- Cloudflare Web Analytics --><script defer src='https://static.cloudflareinsights.com/beacon.min.js' data-cf-beacon='{"token": "be17bfc005774526803b0ef32264a47e"}'></script><!-- End Cloudflare Web Analytics -->
</body></html>"""

_TECH_TEMPLATE_B = """\
<!DOCTYPE html>
<html lang="{{ language }}" {% if rtl %}dir="rtl"{% endif %}>
<head>
<base href="{{ blog_url }}/">
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{{ blog_title }}</title>
<meta name="description" content="{{ meta_desc }}">
<link rel="canonical" href="{{ blog_url }}">
<link href="https://fonts.googleapis.com/css2?family=Fira+Code:wght@400;500;600&family=Inter:wght@400;500;600&display=swap" rel="stylesheet">
{{ ad_head_code }}
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{background:#0a0e1a;color:#8892a4;font-family:'Inter',sans-serif;line-height:1.7}
a{color:{{ accent_color }};text-decoration:none}
.hdr{background:#060810;border-bottom:1px solid #1c2333;padding:0 24px}
.hdr-inner{max-width:1200px;margin:0 auto;display:flex;align-items:center;justify-content:space-between;height:54px}
.logo{font-family:'Fira Code',monospace;font-size:1.2rem;font-weight:600;color:{{ accent_color }}}
.logo-bracket{color:#4a5568}
.nav a{color:#4a5568;font-family:'Fira Code',monospace;font-size:.72rem;margin-left:18px;transition:.2s}
.nav a:hover{color:{{ accent_color }}}
.term-bar{background:#060810;border-bottom:1px solid #1c2333;padding:6px 24px;font-family:'Fira Code',monospace;font-size:.68rem;color:#3d4f6b}
.term-bar span{color:{{ accent_color }}}
.wrap{max-width:1200px;margin:0 auto;padding:28px 24px}
.file-header{font-family:'Fira Code',monospace;font-size:.7rem;color:#3d4f6b;margin-bottom:16px;padding:6px 10px;background:#0d1220;border-left:2px solid {{ accent_color }}}
.file-header span{color:{{ accent_color }}}
.post-grid{display:grid;grid-template-columns:repeat(2,1fr);gap:16px}
@media(max-width:700px){.post-grid{grid-template-columns:1fr}}
.post-card{background:#0d1220;border:1px solid #1c2333;border-radius:4px;overflow:hidden;transition:border-color .2s}
.post-card:hover{border-color:{{ accent_color }}}
.post-card img{width:100%;height:170px;object-fit:cover;opacity:.8}
.post-card-body{padding:14px}
.func-name{font-family:'Fira Code',monospace;font-size:.65rem;color:{{ accent_color }};margin-bottom:6px}
.post-card h3{font-size:.95rem;font-weight:600;line-height:1.35;color:#c9d1d9;margin-bottom:6px}
.post-card h3 a{color:#c9d1d9}.post-card h3 a:hover{color:{{ accent_color }}}
.post-card .meta{font-family:'Fira Code',monospace;font-size:.62rem;color:#3d4f6b}
.empty{text-align:center;padding:70px 20px;color:#3d4f6b}
.empty pre{font-family:'Fira Code',monospace;font-size:.88rem;color:{{ accent_color }};margin-bottom:12px}
footer{border-top:1px solid #1c2333;margin-top:50px;padding:18px 24px;text-align:center;font-family:'Fira Code',monospace;font-size:.68rem;color:#3d4f6b}
</style></head>
<body>
<header class="hdr"><div class="hdr-inner">
<div class="logo"><span class="logo-bracket">{"</span>{{ blog_title }}<span class="logo-bracket">"}</span></div>
<nav class="nav"><a href="{{ blog_url }}/">~/home</a><a href="#">/posts</a><a href="{{ blog_url }}/sitemap.xml">/sitemap</a></nav>
</div></header>
<div class="term-bar">$ <span>fetch</span> --latest --source {{ blog_title|lower }} --format json | render</div>
{{ ad_slot_1 }}
<main class="wrap">
{% if posts %}
<div class="file-header">// <span>{{ posts|length }} articles</span> loaded from {{ blog_title }}</div>
<div class="post-grid">
{% for p in posts %}<div class="post-card">
{% if p.featured_image_url %}<img src="{{ p.featured_image_url }}" alt="{{ p.title }}" loading="lazy">{% endif %}
<div class="post-card-body">
<div class="func-name">{{ p.get('category','tech') }}::article()</div>
<h3><a href="{{ blog_url }}/posts/{{ p.slug }}.html">{{ p.title }}</a></h3>
<div class="meta">// {{ p.get('published_at','')[:10] }}</div>
</div></div>{% endfor %}
</div>
{% else %}
<div class="empty"><pre>$ loading articles...\n→ no results yet</pre><p>First articles deploying. Run again soon.</p></div>
{% endif %}
{{ ad_slot_3 }}
</main>
<footer>// © {{ year }} {{ blog_title }} — all rights reserved</footer>
{% if onesignal_app_id %}<script src="https://cdn.onesignal.com/sdks/web/v16/OneSignalSDK.page.js" defer></script><script>window.OneSignalDeferred=window.OneSignalDeferred||[];OneSignalDeferred.push(async function(OneSignal){await OneSignal.init({appId:"{{ onesignal_app_id }}",notifyButton:{enable:true}});});</script>{% endif %}
<!-- Cloudflare Web Analytics --><script defer src='https://static.cloudflareinsights.com/beacon.min.js' data-cf-beacon='{"token": "be17bfc005774526803b0ef32264a47e"}'></script><!-- End Cloudflare Web Analytics -->
</body></html>"""

_TECH_TEMPLATE_C = """\
<!DOCTYPE html>
<html lang="{{ language }}" {% if rtl %}dir="rtl"{% endif %}>
<head>
<base href="{{ blog_url }}/">
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{{ blog_title }}</title>
<meta name="description" content="{{ meta_desc }}">
<link rel="canonical" href="{{ blog_url }}">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap" rel="stylesheet">
{{ ad_head_code }}
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{background:#fbfbfd;color:#1d1d1f;font-family:'Inter',sans-serif;line-height:1.65;-webkit-font-smoothing:antialiased}
a{color:{{ accent_color }};text-decoration:none}
.hdr{background:rgba(251,251,253,.85);backdrop-filter:saturate(180%) blur(20px);border-bottom:1px solid rgba(0,0,0,.08);padding:0 24px;position:sticky;top:0;z-index:100}
.hdr-inner{max-width:1060px;margin:0 auto;display:flex;align-items:center;justify-content:space-between;height:52px}
.logo{font-size:1.2rem;font-weight:700;color:#1d1d1f;letter-spacing:-0.4px}
.logo span{color:{{ accent_color }}}
.nav a{color:#6e6e73;font-size:.82rem;font-weight:500;margin-left:22px;transition:color .2s}
.nav a:hover{color:{{ accent_color }}}
.hero-section{background:#fff;border-bottom:1px solid #f0f0f0;padding:48px 24px 36px}
.hero-inner{max-width:1060px;margin:0 auto;display:grid;grid-template-columns:1.2fr 1fr;gap:40px;align-items:center}
@media(max-width:700px){.hero-inner{grid-template-columns:1fr}}
.hero-label{font-size:.7rem;font-weight:600;color:{{ accent_color }};text-transform:uppercase;letter-spacing:.12em;margin-bottom:10px}
.hero-title{font-size:2rem;font-weight:800;line-height:1.1;letter-spacing:-1px;color:#1d1d1f;margin-bottom:12px}
.hero-title a{color:#1d1d1f}.hero-title a:hover{color:{{ accent_color }}}
.hero-sub{font-size:.9rem;color:#6e6e73;line-height:1.55;margin-bottom:16px}
.read-btn{display:inline-flex;align-items:center;gap:6px;background:{{ accent_color }};color:#fff;font-size:.82rem;font-weight:600;padding:9px 20px;border-radius:100px;transition:.2s}
.read-btn:hover{opacity:.85;color:#fff}
.hero-img{width:100%;border-radius:16px;box-shadow:0 20px 60px rgba(0,0,0,.1)}
.wrap{max-width:1060px;margin:0 auto;padding:32px 24px}
.grid-4{display:grid;grid-template-columns:repeat(4,1fr);gap:20px}
@media(max-width:900px){.grid-4{grid-template-columns:repeat(2,1fr)}}
@media(max-width:500px){.grid-4{grid-template-columns:1fr}}
.card{background:#fff;border-radius:12px;overflow:hidden;box-shadow:0 2px 12px rgba(0,0,0,.06);transition:transform .2s,box-shadow .2s}
.card:hover{transform:translateY(-4px);box-shadow:0 8px 28px rgba(0,0,0,.1)}
.card img{width:100%;height:150px;object-fit:cover}
.card-body{padding:14px}
.card-cat{font-size:.62rem;font-weight:600;color:{{ accent_color }};text-transform:uppercase;letter-spacing:.08em;margin-bottom:5px}
.card h3{font-size:.88rem;font-weight:600;line-height:1.3;color:#1d1d1f}
.card h3 a{color:#1d1d1f}.card h3 a:hover{color:{{ accent_color }}}
.card .date{font-size:.65rem;color:#a1a1a6;margin-top:6px}
.sec-title{font-size:.8rem;font-weight:700;color:#1d1d1f;text-transform:uppercase;letter-spacing:.1em;margin-bottom:18px;padding-bottom:10px;border-bottom:1px solid #f0f0f0}
.empty{text-align:center;padding:80px 20px;background:#fff;border-radius:16px}
.empty h2{font-size:1.4rem;font-weight:700;color:#1d1d1f;margin-bottom:8px}
.empty p{color:#6e6e73;font-size:.9rem}
footer{background:#1d1d1f;color:#6e6e73;text-align:center;padding:18px;font-size:.72rem;margin-top:50px}
footer a{color:{{ accent_color }}}
</style></head>
<body>
<header class="hdr"><div class="hdr-inner">
<div class="logo">{{ blog_title[:4] }}<span>{{ blog_title[4:] }}</span></div>
<nav class="nav"><a href="{{ blog_url }}/">Home</a><a href="#">Reviews</a><a href="#">News</a><a href="{{ blog_url }}/sitemap.xml">Sitemap</a></nav>
</div></header>
{{ ad_slot_1 }}
{% if posts %}{% set p = posts[0] %}
<section class="hero-section"><div class="hero-inner">
<div>
<div class="hero-label">{{ p.get('category','Technology') }}</div>
<h2 class="hero-title"><a href="{{ blog_url }}/posts/{{ p.slug }}.html">{{ p.title }}</a></h2>
{% if p.get('meta_desc') %}<p class="hero-sub">{{ p.meta_desc[:120] }}</p>{% endif %}
<a href="{{ blog_url }}/posts/{{ p.slug }}.html" class="read-btn">Read Article →</a>
</div>
{% if p.featured_image_url %}<img class="hero-img" src="{{ p.featured_image_url }}" alt="{{ p.title }}">{% endif %}
</div></section>
<main class="wrap">
{% if posts|length > 1 %}
<div class="sec-title">Latest</div>
<div class="grid-4">
{% for p in posts[1:] %}<div class="card">
{% if p.featured_image_url %}<img src="{{ p.featured_image_url }}" alt="{{ p.title }}">{% endif %}
<div class="card-body">
<div class="card-cat">{{ p.get('category','Tech') }}</div>
<h3><a href="{{ blog_url }}/posts/{{ p.slug }}.html">{{ p.title }}</a></h3>
<div class="date">{{ p.get('published_at','')[:10] }}</div>
</div></div>{% endfor %}
</div>{% endif %}
{% else %}
<main class="wrap"><div class="empty"><h2>Coming Soon</h2><p>The latest in tech, launching shortly.</p></div>
{% endif %}
{{ ad_slot_3 }}
</main>
<footer>© {{ year }} {{ blog_title }} | <a href="{{ blog_url }}/sitemap.xml">Sitemap</a></footer>
{% if onesignal_app_id %}<script src="https://cdn.onesignal.com/sdks/web/v16/OneSignalSDK.page.js" defer></script><script>window.OneSignalDeferred=window.OneSignalDeferred||[];OneSignalDeferred.push(async function(OneSignal){await OneSignal.init({appId:"{{ onesignal_app_id }}",notifyButton:{enable:true}});});</script>{% endif %}
<!-- Cloudflare Web Analytics --><script defer src='https://static.cloudflareinsights.com/beacon.min.js' data-cf-beacon='{"token": "be17bfc005774526803b0ef32264a47e"}'></script><!-- End Cloudflare Web Analytics -->
</body></html>"""

_ENTERTAINMENT_TEMPLATE_B = """\
<!DOCTYPE html>
<html lang="{{ language }}" {% if rtl %}dir="rtl"{% endif %}>
<head>
<base href="{{ blog_url }}/">
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{{ blog_title }}</title>
<meta name="description" content="{{ meta_desc }}">
<link rel="canonical" href="{{ blog_url }}">
<link href="https://fonts.googleapis.com/css2?family=Cinzel:wght@400;600;700&family=Raleway:wght@300;400;500;600&display=swap" rel="stylesheet">
{{ ad_head_code }}
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{background:#0d0d14;color:#bfb9ae;font-family:'Raleway',sans-serif;line-height:1.7}
a{color:{{ accent_color }};text-decoration:none}
.hdr{background:#07070e;border-bottom:1px solid rgba(255,215,0,.12);padding:0 24px}
.hdr-inner{max-width:1200px;margin:0 auto;display:flex;align-items:center;justify-content:space-between;height:64px}
.logo{font-family:'Cinzel',serif;font-size:1.5rem;font-weight:700;color:#f5e6c8;letter-spacing:2px;text-transform:uppercase}
.logo em{color:{{ accent_color }};font-style:normal}
.nav a{color:#7a7265;font-size:.75rem;font-weight:600;margin-left:20px;text-transform:uppercase;letter-spacing:.12em;transition:.2s}
.nav a:hover{color:{{ accent_color }}}
.gold-line{height:1px;background:linear-gradient(90deg,transparent,{{ accent_color }},transparent)}
.wrap{max-width:1200px;margin:0 auto;padding:32px 24px}
.mag-grid{display:grid;grid-template-columns:1.6fr 1fr;gap:0;margin-bottom:36px}
@media(max-width:700px){.mag-grid{grid-template-columns:1fr}}
.mag-main{padding-right:28px;border-right:1px solid #1e1e2e}
@media(max-width:700px){.mag-main{padding-right:0;border-right:none;border-bottom:1px solid #1e1e2e;padding-bottom:24px;margin-bottom:24px}}
.mag-side{padding-left:24px}
@media(max-width:700px){.mag-side{padding-left:0}}
.mag-main img{width:100%;height:320px;object-fit:cover;margin-bottom:14px;filter:brightness(.9)}
.excl{font-family:'Cinzel',serif;font-size:.6rem;font-weight:700;color:{{ accent_color }};text-transform:uppercase;letter-spacing:.2em;margin-bottom:8px}
.mag-main h2{font-family:'Cinzel',serif;font-size:1.5rem;font-weight:700;line-height:1.2;color:#f5e6c8;margin-bottom:10px}
.mag-main h2 a{color:#f5e6c8}.mag-main h2 a:hover{color:{{ accent_color }}}
.mag-date{font-size:.7rem;color:#7a7265;font-family:'Cinzel',serif;letter-spacing:.08em}
.side-title{font-family:'Cinzel',serif;font-size:.7rem;font-weight:700;color:{{ accent_color }};text-transform:uppercase;letter-spacing:.2em;margin-bottom:12px}
.side-item{padding:12px 0;border-bottom:1px solid #1e1e2e;display:flex;gap:12px}
.side-item:last-child{border-bottom:none}
.side-item img{width:70px;height:52px;object-fit:cover;flex-shrink:0;filter:brightness(.85)}
.side-item h3{font-family:'Cinzel',serif;font-size:.82rem;font-weight:600;line-height:1.3;color:#d4c9b8}
.side-item h3 a{color:#d4c9b8}.side-item h3 a:hover{color:{{ accent_color }}}
.side-item .date{font-size:.62rem;color:#7a7265;margin-top:4px}
.more-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:20px;margin-top:8px}
@media(max-width:700px){.more-grid{grid-template-columns:1fr}}
.more-card img{width:100%;height:170px;object-fit:cover;margin-bottom:10px;filter:brightness(.88)}
.more-card h4{font-family:'Cinzel',serif;font-size:.85rem;font-weight:600;color:#d4c9b8;line-height:1.3}
.more-card h4 a{color:#d4c9b8}.more-card h4 a:hover{color:{{ accent_color }}}
.more-card .date{font-size:.62rem;color:#7a7265;margin-top:5px}
.sec-title{font-family:'Cinzel',serif;font-size:.72rem;font-weight:700;color:#f5e6c8;text-transform:uppercase;letter-spacing:.2em;margin:28px 0 16px;display:flex;align-items:center;gap:12px}
.sec-title::after{content:"";flex:1;height:1px;background:linear-gradient(90deg,{{ accent_color }},transparent)}
.empty{text-align:center;padding:80px 20px;color:#7a7265}
.empty h2{font-family:'Cinzel',serif;font-size:1.4rem;color:#f5e6c8;margin-bottom:8px}
footer{background:#07070e;border-top:1px solid rgba(255,215,0,.1);padding:20px;text-align:center;color:#7a7265;font-size:.7rem;font-family:'Cinzel',serif;letter-spacing:.1em;margin-top:50px}
</style></head>
<body>
<header class="hdr"><div class="hdr-inner">
<div class="logo">{{ blog_title[:4] }}<em>{{ blog_title[4:] }}</em></div>
<nav class="nav"><a href="{{ blog_url }}/">Home</a><a href="#">Stars</a><a href="#">Red Carpet</a><a href="{{ blog_url }}/sitemap.xml">Sitemap</a></nav>
</div></header>
<div class="gold-line"></div>
{{ ad_slot_1 }}
<main class="wrap">
{% if posts %}{% set p = posts[0] %}
<div class="mag-grid">
<div class="mag-main">
{% if p.featured_image_url %}<img src="{{ p.featured_image_url }}" alt="{{ p.title }}">{% endif %}
<div class="excl">Exclusive</div>
<h2><a href="{{ blog_url }}/posts/{{ p.slug }}.html">{{ p.title }}</a></h2>
<div class="mag-date">{{ p.get('published_at','')[:10] }}</div>
</div>
<div class="mag-side">
<div class="side-title">Also Trending</div>
{% for p in posts[1:6] %}<div class="side-item">
{% if p.featured_image_url %}<img src="{{ p.featured_image_url }}" alt="{{ p.title }}">{% endif %}
<div><h3><a href="{{ blog_url }}/posts/{{ p.slug }}.html">{{ p.title }}</a></h3>
<div class="date">{{ p.get('published_at','')[:10] }}</div></div>
</div>{% endfor %}
</div></div>
{% if posts|length > 6 %}
<div class="sec-title">More Stories</div>
<div class="more-grid">
{% for p in posts[6:] %}<div class="more-card">
{% if p.featured_image_url %}<img src="{{ p.featured_image_url }}" alt="{{ p.title }}">{% endif %}
<h4><a href="{{ blog_url }}/posts/{{ p.slug }}.html">{{ p.title }}</a></h4>
<div class="date">{{ p.get('published_at','')[:10] }}</div>
</div>{% endfor %}</div>{% endif %}
{% else %}
<div class="empty"><h2>Curtain Rising</h2><p>Celebrity exclusives loading now. Check back soon.</p></div>
{% endif %}
{{ ad_slot_3 }}
</main>
<footer>© {{ year }} {{ blog_title }} — All Rights Reserved</footer>
{% if onesignal_app_id %}<script src="https://cdn.onesignal.com/sdks/web/v16/OneSignalSDK.page.js" defer></script><script>window.OneSignalDeferred=window.OneSignalDeferred||[];OneSignalDeferred.push(async function(OneSignal){await OneSignal.init({appId:"{{ onesignal_app_id }}",notifyButton:{enable:true}});});</script>{% endif %}
<!-- Cloudflare Web Analytics --><script defer src='https://static.cloudflareinsights.com/beacon.min.js' data-cf-beacon='{"token": "be17bfc005774526803b0ef32264a47e"}'></script><!-- End Cloudflare Web Analytics -->
</body></html>"""

_ENTERTAINMENT_TEMPLATE_C = """\
<!DOCTYPE html>
<html lang="{{ language }}" {% if rtl %}dir="rtl"{% endif %}>
<head>
<base href="{{ blog_url }}/">
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{{ blog_title }}</title>
<meta name="description" content="{{ meta_desc }}">
<link rel="canonical" href="{{ blog_url }}">
<link href="https://fonts.googleapis.com/css2?family=Anton&family=Open+Sans:wght@400;600;700&display=swap" rel="stylesheet">
{{ ad_head_code }}
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{background:#fffde7;color:#111;font-family:'Open Sans',sans-serif;line-height:1.6}
a{color:{{ accent_color }};text-decoration:none}
.hdr{background:#111;padding:0 16px}
.hdr-inner{max-width:1200px;margin:0 auto;display:flex;align-items:center;justify-content:space-between;min-height:60px;padding:8px 0}
.logo{font-family:'Anton',sans-serif;font-size:2rem;color:{{ accent_color }};letter-spacing:1px;text-transform:uppercase;line-height:1}
.logo-sub{font-size:.55rem;color:#999;letter-spacing:.2em;text-transform:uppercase;margin-top:2px}
.nav a{color:#888;font-size:.78rem;font-weight:700;margin-left:16px;text-transform:uppercase;letter-spacing:.06em}
.nav a:hover{color:{{ accent_color }}}
.flash-bar{background:{{ accent_color }};padding:7px 16px;display:flex;align-items:center;gap:12px;overflow:hidden}
.flash-label{background:#111;color:{{ accent_color }};font-family:'Anton',sans-serif;font-size:.7rem;padding:2px 8px;text-transform:uppercase;letter-spacing:.1em;white-space:nowrap}
.flash-text{font-size:.75rem;font-weight:700;color:#111}
.wrap{max-width:1200px;margin:0 auto;padding:20px 16px}
.big-story{background:#111;color:#fff;border-radius:4px;overflow:hidden;display:grid;grid-template-columns:1.4fr 1fr;margin-bottom:20px}
@media(max-width:700px){.big-story{grid-template-columns:1fr}}
.big-story img{width:100%;height:100%;min-height:280px;object-fit:cover}
.big-body{padding:20px}
.scream{font-family:'Anton',sans-serif;font-size:1.8rem;line-height:1.05;text-transform:uppercase;letter-spacing:-0.5px;margin-bottom:10px}
.scream a{color:#fff}.scream a:hover{color:{{ accent_color }}}
.kicker{background:{{ accent_color }};color:#111;font-family:'Anton',sans-serif;font-size:.65rem;padding:2px 8px;display:inline-block;text-transform:uppercase;letter-spacing:.1em;margin-bottom:8px}
.big-meta{font-size:.7rem;color:#888;margin-top:10px}
.story-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:12px}
@media(max-width:700px){.story-grid{grid-template-columns:1fr}}
.story{background:#fff;border:2px solid #111;border-radius:2px;overflow:hidden;transition:border-color .2s}
.story:hover{border-color:{{ accent_color }}}
.story img{width:100%;height:170px;object-fit:cover}
.story-body{padding:10px}
.story h3{font-family:'Anton',sans-serif;font-size:1.05rem;text-transform:uppercase;letter-spacing:-0.3px;line-height:1.15;color:#111}
.story h3 a{color:#111}.story h3 a:hover{color:{{ accent_color }}}
.story .meta{font-size:.65rem;color:#888;margin-top:6px}
.empty{text-align:center;padding:70px 20px;background:#fff;border:2px solid #111}
.empty h2{font-family:'Anton',sans-serif;font-size:1.8rem;text-transform:uppercase;color:#111;margin-bottom:8px}
footer{background:#111;color:#555;text-align:center;padding:16px;font-size:.72rem;margin-top:24px}
footer a{color:{{ accent_color }}}
</style></head>
<body>
<header class="hdr"><div class="hdr-inner">
<div><div class="logo">{{ blog_title }}</div><div class="logo-sub">Breaking Every Day</div></div>
<nav class="nav"><a href="{{ blog_url }}/">Home</a><a href="#">Gossip</a><a href="#">Scandals</a></nav>
</div></header>
<div class="flash-bar"><span class="flash-label">Breaking</span><span class="flash-text">{{ blog_title }} — The hottest stories updated daily</span></div>
{{ ad_slot_1 }}
<main class="wrap">
{% if posts %}{% set p = posts[0] %}
<div class="big-story">
{% if p.featured_image_url %}<img src="{{ p.featured_image_url }}" alt="{{ p.title }}">{% endif %}
<div class="big-body">
<span class="kicker">{{ p.get('category','Entertainment') }}</span>
<div class="scream"><a href="{{ blog_url }}/posts/{{ p.slug }}.html">{{ p.title }}</a></div>
<div class="big-meta">{{ p.get('published_at','')[:10] }}</div>
</div></div>
{% if posts|length > 1 %}
<div class="story-grid">
{% for p in posts[1:] %}<div class="story">
{% if p.featured_image_url %}<img src="{{ p.featured_image_url }}" alt="{{ p.title }}">{% endif %}
<div class="story-body">
<span class="kicker">{{ p.get('category','Entertainment') }}</span>
<h3><a href="{{ blog_url }}/posts/{{ p.slug }}.html">{{ p.title }}</a></h3>
<div class="meta">{{ p.get('published_at','')[:10] }}</div>
</div></div>{% endfor %}
</div>{% endif %}
{% else %}
<div class="empty"><h2>Breaking Soon!</h2><p>Hot stories loading. Reload in a few hours.</p></div>
{% endif %}
{{ ad_slot_3 }}
</main>
<footer>© {{ year }} {{ blog_title }} | <a href="{{ blog_url }}/sitemap.xml">Sitemap</a></footer>
{% if onesignal_app_id %}<script src="https://cdn.onesignal.com/sdks/web/v16/OneSignalSDK.page.js" defer></script><script>window.OneSignalDeferred=window.OneSignalDeferred||[];OneSignalDeferred.push(async function(OneSignal){await OneSignal.init({appId:"{{ onesignal_app_id }}",notifyButton:{enable:true}});});</script>{% endif %}
<!-- Cloudflare Web Analytics --><script defer src='https://static.cloudflareinsights.com/beacon.min.js' data-cf-beacon='{"token": "be17bfc005774526803b0ef32264a47e"}'></script><!-- End Cloudflare Web Analytics -->
</body></html>"""


_NICHE_TEMPLATE_VARIANTS: Dict[str, list] = {}  # populated lazily on first call


def _get_index_template(niche_group: str, variant: int = 0) -> str:
    """Return the HTML template for the given niche group and variant (0, 1, or 2)."""
    if not _NICHE_TEMPLATE_VARIANTS:
        _NICHE_TEMPLATE_VARIANTS.update({
            "crypto":        [_CRYPTO_TEMPLATE, _CRYPTO_TEMPLATE_B, _CRYPTO_TEMPLATE_C],
            "finance":       [_FINANCE_TEMPLATE, _FINANCE_TEMPLATE_B, _FINANCE_TEMPLATE_C],
            "health":        [_HEALTH_TEMPLATE, _HEALTH_TEMPLATE_B, _HEALTH_TEMPLATE_C],
            "tech":          [_TECH_TEMPLATE, _TECH_TEMPLATE_B, _TECH_TEMPLATE_C],
            "entertainment": [_ENTERTAINMENT_TEMPLATE, _ENTERTAINMENT_TEMPLATE_B, _ENTERTAINMENT_TEMPLATE_C],
        })
    variants = _NICHE_TEMPLATE_VARIANTS.get(niche_group, _NICHE_TEMPLATE_VARIANTS["entertainment"])
    return variants[variant % len(variants)]


# ── Data classes ────────────────────────────────────────────────────────────────
@dataclass
class SiteConfig:
    site_id:               int
    blog_id:               str        # Cloudflare project name / GitHub subdir identifier
    title:                 str        # blog display title
    language:              str        # en, es, pt, hi, ar, fr, ur
    niche:                 str
    blog_url:              str        # https://site-NNN.pages.dev or custom domain
    ad_codes:              Dict[str, str] = field(default_factory=dict)
    cloudflare_account_id: str = ""
    github_path:           str = ""   # sites/site-NNN
    is_adult:              bool = False
    meta_desc:             str = ""


@dataclass
class PostMeta:
    slug:              str
    title:             str
    meta_desc:         str
    language:          str
    published_at:      str       # ISO-8601
    niche:             str
    keywords:          List[str] = field(default_factory=list)
    featured_image_url: str = ""


# ── Helpers ─────────────────────────────────────────────────────────────────────
def _jinja_env():
    """Return a Jinja2 Environment. Lazy import so missing jinja2 fails at call time."""
    from jinja2 import Environment, Undefined
    env = Environment(
        autoescape=True,
        undefined=Undefined,
        keep_trailing_newline=True,
    )
    return env


def _build_hreflang_tags(hreflang_links: Dict[str, str]) -> str:
    if not hreflang_links:
        return ""
    tags = [
        f'<link rel="alternate" hreflang="{lang}" href="{url}">'
        for lang, url in hreflang_links.items()
    ]
    default_url = hreflang_links.get("en", next(iter(hreflang_links.values()), ""))
    tags.append(f'<link rel="alternate" hreflang="x-default" href="{default_url}">')
    return "\n".join(tags)


def _build_article_schema(
    title: str,
    blog_title: str,
    blog_url: str,
    canonical_url: str,
    language: str,
    published_at: str,
    meta_desc: str,
    featured_image_url: str = "",
) -> str:
    schema = {
        "@context": "https://schema.org",
        "@type": "NewsArticle",
        "headline": title[:110],
        "description": meta_desc[:200],
        "url": canonical_url,
        "inLanguage": language,
        "datePublished": published_at,
        "dateModified": published_at,
        "publisher": {
            "@type": "Organization",
            "name": blog_title,
            "url": blog_url,
        },
        "author": {"@type": "Organization", "name": blog_title},
    }
    if featured_image_url:
        schema["image"] = {"@type": "ImageObject", "url": featured_image_url}
    return f'<script type="application/ld+json">{json.dumps(schema, ensure_ascii=False)}</script>'


def _extract_faqs_from_html(body_html: str) -> list:
    """
    Extract FAQ Q&A pairs from body HTML.
    Looks for <section class="faq"> first, falls back to scanning all h3/h4 + p pairs.
    Returns list of (question_text, answer_text) tuples, max 10.
    """
    faqs = []
    faq_section = re.search(
        r'<section[^>]*class=["\'][^"\']*faq[^"\']*["\'][^>]*>(.*?)</section>',
        body_html, re.DOTALL | re.IGNORECASE
    )
    search_html = faq_section.group(1) if faq_section else body_html
    pairs = re.finditer(
        r'<h[34][^>]*>(.*?)</h[34]>\s*(?:<[^>]+>\s*)*<p[^>]*>(.*?)</p>',
        search_html, re.DOTALL | re.IGNORECASE
    )
    for m in pairs:
        question = re.sub(r'<[^>]+>', '', m.group(1)).strip()
        answer   = re.sub(r'<[^>]+>', '', m.group(2)).strip()
        if question and answer and len(question) > 8:
            faqs.append((question, answer))
        if len(faqs) >= 10:
            break
    return faqs


def _build_faq_schema(body_html: str) -> str:
    """
    Build FAQPage JSON-LD schema tag from FAQ section in body HTML.
    Returns empty string if no FAQs found.
    """
    faqs = _extract_faqs_from_html(body_html)
    if not faqs:
        return ""
    schema = {
        "@context": "https://schema.org",
        "@type": "FAQPage",
        "mainEntity": [
            {
                "@type": "Question",
                "name": q,
                "acceptedAnswer": {"@type": "Answer", "text": a},
            }
            for q, a in faqs
        ],
    }
    return f'<script type="application/ld+json">{json.dumps(schema, ensure_ascii=False)}</script>'


def _inject_ad_after_first_para(body_html: str, ad_html: str) -> str:
    """Insert ad_html after the first </p> in body_html."""
    if not ad_html:
        return body_html
    idx = body_html.find("</p>")
    if idx == -1:
        return body_html
    insert_at = idx + 4
    ad_block = f'\n<div class="ad-inline" aria-label="Advertisement">{ad_html}</div>\n'
    return body_html[:insert_at] + ad_block + body_html[insert_at:]


def make_slug(title: str) -> str:
    """Convert title to URL slug."""
    slug = title.lower()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s_-]+", "-", slug)
    slug = slug.strip("-")
    return slug[:80]


# ── Core generation functions ───────────────────────────────────────────────────
def generate_post_html(
    post_meta: PostMeta,
    body_html: str,
    site_config: SiteConfig,
    canonical_url: str = "",
    hreflang_links: Optional[Dict[str, str]] = None,
    disclosure_text: str = "",
    legal_footer_text: str = "",
    related_posts: Optional[List[Dict]] = None,
) -> str:
    """
    Generate a full HTML page for a single blog post.
    Returns complete HTML string ready to write to disk.
    """
    try:
        from jinja2 import Environment
        env = _jinja_env()
    except ImportError:
        raise RuntimeError("jinja2 not installed — run: pip install jinja2")

    rtl = post_meta.language in RTL_LANGUAGES
    styles = dict(get_niche_styles(post_meta.niche))  # copy so we can override
    # Apply per-blog unique accent so post header matches the index page color
    _blog_slug = site_config.blog_url.rstrip("/").split("/")[-1]
    _niche_group = NICHE_TEMPLATE_GROUP.get(post_meta.niche, "entertainment")
    _blog_accent = get_blog_accent_color(_blog_slug, _niche_group)
    styles["primary"] = _blog_accent   # header background matches index accent
    styles["accent"]  = _blog_accent   # links, highlights, brand mark

    if not canonical_url:
        canonical_url = f"{site_config.blog_url}/posts/{post_meta.slug}.html"

    if not post_meta.featured_image_url:
        post_meta = PostMeta(
            slug=post_meta.slug,
            title=post_meta.title,
            meta_desc=post_meta.meta_desc,
            language=post_meta.language,
            published_at=post_meta.published_at,
            niche=post_meta.niche,
            keywords=post_meta.keywords,
            featured_image_url=get_article_image_url(post_meta.slug, post_meta.niche),
        )

    # Extract real key takeaways from post body
    key_takeaways = extract_key_takeaways(body_html, n=3)

    # Build related_posts list — ensure each card has a niche-relevant image
    _related: List[Dict] = []
    for rp in (related_posts or [])[:3]:
        rp_slug = rp.get("slug", "")
        rp_img  = rp.get("featured_image_url") or get_article_image_url(rp_slug, post_meta.niche, 400, 225)
        _related.append({
            "slug":              rp_slug,
            "title":             rp.get("title", "More stories"),
            "published_at":      rp.get("published_at", post_meta.published_at)[:10],
            "featured_image_url": rp_img,
        })

    hreflang_tags = _build_hreflang_tags(hreflang_links or {})
    schema_tag    = _build_article_schema(
        title=post_meta.title,
        blog_title=site_config.title,
        blog_url=site_config.blog_url,
        canonical_url=canonical_url,
        language=post_meta.language,
        published_at=post_meta.published_at,
        meta_desc=post_meta.meta_desc,
        featured_image_url=post_meta.featured_image_url,
    )
    faq_schema_tag = _build_faq_schema(body_html)

    ad = site_config.ad_codes
    # Inject ad_slot_2 inline after first paragraph
    processed_body = _inject_ad_after_first_para(
        body_html,
        ad.get("slot_2", ad.get("slot_3", ad.get("ad_slot_2", ad.get("ad_slot_3", "")))),
    )

    disclosure = disclosure_text or (
        "Disclosure: This post contains affiliate links. "
        "We may earn a commission at no extra cost to you. "
        "AI-assisted content — reviewed editorially."
    )
    legal_footer = legal_footer_text or (
        f'Published {post_meta.published_at[:10]} | '
        f'<a href="privacy-policy">Privacy</a> | '
        f'<a href="affiliate-disclosure">Disclosure</a>'
    )

    tmpl = env.from_string(_POST_TEMPLATE)
    return tmpl.render(
        title=post_meta.title,
        slug=post_meta.slug,
        meta_desc=post_meta.meta_desc,
        language=post_meta.language,
        rtl=rtl,
        is_adult=site_config.is_adult,
        blog_title=site_config.title,
        blog_url=site_config.blog_url,
        canonical_url=canonical_url,
        hreflang_tags=hreflang_tags,
        schema_tag=schema_tag,
        faq_schema_tag=faq_schema_tag,
        ad_head_code=ad.get("head", ad.get("ad_head", "")),
        ad_slot_1=ad.get("slot_1", ad.get("ad_slot_1", "")),
        ad_slot_3=ad.get("slot_3", ad.get("ad_slot_3", "")),
        ad_slot_4_js=ad.get("slot_4_js", ad.get("ad_slot_4_js", "/* slot 4 */")),
        ad_slot_5=ad.get("slot_5", ad.get("ad_slot_5", "")),
        ad_slot_6_js=ad.get("slot_6_js", ad.get("ad_slot_6_js", "/* slot 6 */")),
        body_html=processed_body,
        featured_image_url=post_meta.featured_image_url,
        published_at=post_meta.published_at,
        keywords=post_meta.keywords[:6],
        key_takeaways=key_takeaways,
        related_posts=_related,
        styles=styles,
        common_css=_COMMON_CSS,
        disclosure=disclosure,
        legal_footer=legal_footer,
        year=datetime.now().year,
        onesignal_app_id=_get_onesignal_app_id(),
    )


def generate_index_html(
    posts: List[Dict],           # list of post info dicts (slug, title, meta_desc, published_at, featured_image_url)
    site_config: SiteConfig,
    max_posts: int = 10,
) -> str:
    """
    Generate the homepage index.html for a blog site.
    Shows the latest max_posts posts.
    """
    try:
        env = _jinja_env()
    except ImportError:
        raise RuntimeError("jinja2 not installed — run: pip install jinja2")

    rtl    = site_config.language in RTL_LANGUAGES
    styles = get_niche_styles(site_config.niche)
    ad     = site_config.ad_codes

    # Most recent first, cap at max_posts
    sorted_posts = sorted(
        posts,
        key=lambda p: p.get("published_at", ""),
        reverse=True,
    )[:max_posts]

    meta_desc = site_config.meta_desc or f"Latest news and articles from {site_config.title}."

    for p in sorted_posts:
        if not p.get("featured_image_url"):
            p["featured_image_url"] = get_article_image_url(
                p.get("slug", "post"), site_config.niche, 800, 450
            )

    niche_group = NICHE_TEMPLATE_GROUP.get(site_config.niche, "entertainment")
    _slug = site_config.blog_url.rstrip("/").split("/")[-1]
    accent_color = get_blog_accent_color(_slug, niche_group)
    variant = get_blog_layout_variant(_slug)
    tmpl = env.from_string(_get_index_template(niche_group, variant))
    return tmpl.render(
        blog_title=site_config.title,
        blog_url=site_config.blog_url,
        meta_desc=meta_desc,
        language=site_config.language,
        rtl=rtl,
        is_adult=site_config.is_adult,
        posts=sorted_posts,
        ad_head_code=ad.get("head", ad.get("ad_head", "")),
        ad_slot_1=ad.get("slot_1", ad.get("ad_slot_1", "")),
        ad_slot_3=ad.get("slot_3", ad.get("ad_slot_3", "")),
        styles=styles,
        common_css=_COMMON_CSS,
        accent_color=accent_color,
        year=datetime.now().year,
        niche=site_config.niche,
        onesignal_app_id=_get_onesignal_app_id(),
    )


def generate_sitemap_xml(posts: List[Dict], site_config: SiteConfig) -> str:
    """
    Generate sitemap.xml for a site.
    Includes index URL + all post URLs.
    """
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    lines = ['<?xml version="1.0" encoding="UTF-8"?>']
    lines.append('<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"')
    lines.append('        xmlns:xhtml="http://www.w3.org/1999/xhtml">')

    # Homepage
    lines.append(f"  <url>")
    lines.append(f"    <loc>{site_config.blog_url}/</loc>")
    lines.append(f"    <lastmod>{now}</lastmod>")
    lines.append(f"    <changefreq>hourly</changefreq>")
    lines.append(f"    <priority>1.0</priority>")
    lines.append(f"  </url>")

    for post in posts:
        slug = post.get("slug", "")
        if not slug:
            continue
        pub = post.get("published_at", now)[:10]
        url = f"{site_config.blog_url}/posts/{slug}.html"
        lines.append(f"  <url>")
        lines.append(f"    <loc>{url}</loc>")
        lines.append(f"    <lastmod>{pub}</lastmod>")
        lines.append(f"    <changefreq>weekly</changefreq>")
        lines.append(f"    <priority>0.8</priority>")
        lines.append(f"  </url>")

    lines.append("</urlset>")
    return "\n".join(lines)


def generate_robots_txt(blog_url: str) -> str:
    return (
        "User-agent: *\n"
        "Allow: /\n"
        f"Sitemap: {blog_url}/sitemap.xml\n"
        "\n"
        "# BlogBot — auto-generated\n"
    )


def generate_ads_txt(network_ids: Dict[str, str]) -> str:
    """
    Generate ads.txt content.
    network_ids: {publisher_id: 'popads.net, PUBID, DIRECT, ...'}
    """
    lines = ["# BlogBot ads.txt — auto-generated"]
    lines.append(f"# Updated: {datetime.now(timezone.utc).strftime('%Y-%m-%d')}")
    lines.append("")
    for domain_entry in network_ids.values():
        lines.append(domain_entry)
    if not network_ids:
        # Default entries for the three primary networks
        lines.append("popads.net, PLACEHOLDER_ID, DIRECT")
        lines.append("adsterra.com, PLACEHOLDER_ID, DIRECT")
        lines.append("monetag.com, PLACEHOLDER_ID, DIRECT")
    return "\n".join(lines)


# ── Full site builder ───────────────────────────────────────────────────────────
def build_full_site(
    site_config: SiteConfig,
    posts_data: List[Dict],   # each dict: {meta: PostMeta, body_html: str, hreflang_links: dict}
    output_dir: Optional[Path] = None,
    ads_txt_entries: Optional[Dict[str, str]] = None,
) -> Dict:
    """
    Build the complete static site to output_dir.
    Returns {files_written: int, paths: List[str], site_id: int}.

    output_dir defaults to SITES_DIR / f"site-{site_id:03d}"
    """
    if output_dir is None:
        output_dir = SITES_DIR / f"site-{site_config.site_id:03d}"

    output_dir = Path(output_dir)
    posts_dir  = output_dir / "posts"
    posts_dir.mkdir(parents=True, exist_ok=True)

    written: List[str] = []

    # Build post list for index + sitemap
    post_index: List[Dict] = []

    for item in posts_data:
        meta: PostMeta = item["meta"]
        body_html: str = item["body_html"]
        hreflang_links = item.get("hreflang_links", {})

        # Generate post HTML
        post_html = generate_post_html(
            post_meta=meta,
            body_html=body_html,
            site_config=site_config,
            hreflang_links=hreflang_links,
        )

        # Write post file
        post_file = posts_dir / f"{meta.slug}.html"
        post_file.write_text(post_html, encoding="utf-8")
        written.append(str(post_file.relative_to(output_dir)))

        post_index.append({
            "slug":              meta.slug,
            "title":             meta.title,
            "meta_desc":         meta.meta_desc,
            "published_at":      meta.published_at,
            "featured_image_url": meta.featured_image_url,
        })

    # Generate + write index.html
    index_html = generate_index_html(post_index, site_config)
    (output_dir / "index.html").write_text(index_html, encoding="utf-8")
    written.append("index.html")

    # Generate + write sitemap.xml
    sitemap = generate_sitemap_xml(post_index, site_config)
    (output_dir / "sitemap.xml").write_text(sitemap, encoding="utf-8")
    written.append("sitemap.xml")

    # robots.txt
    robots = generate_robots_txt(site_config.blog_url)
    (output_dir / "robots.txt").write_text(robots, encoding="utf-8")
    written.append("robots.txt")

    # ads.txt
    ads_txt = generate_ads_txt(ads_txt_entries or {})
    (output_dir / "ads.txt").write_text(ads_txt, encoding="utf-8")
    written.append("ads.txt")

    # Legal pages (privacy, terms, dmca, affiliate disclosure, contact)
    legal_files = generate_legal_pages(site_config, output_dir)
    written.extend(legal_files)

    _log.info(f"Built site-{site_config.site_id:03d} — {len(written)} files in {output_dir}")
    return {
        "files_written": len(written),
        "paths": written,
        "site_id": site_config.site_id,
        "output_dir": str(output_dir),
    }


# ── Legal Pages ────────────────────────────────────────────────────────────────

_LEGAL_TEMPLATE = """\
<!DOCTYPE html>
<html lang="{lang}" {dir_attr}>
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{page_title} — {blog_title}</title>
<meta name="robots" content="noindex, follow">
<link rel="canonical" href="{canonical}">
<style>
:root{{--primary:{primary};--accent:{accent};--bg:{bg};--text:{text};--font:{font};}}
*{{box-sizing:border-box;margin:0;padding:0}}
body{{background:var(--bg);color:var(--text);font-family:var(--font);line-height:1.7;padding:20px 16px;}}
.wrap{{max-width:800px;margin:0 auto}}
header{{border-bottom:2px solid var(--primary);padding-bottom:14px;margin-bottom:28px}}
header a{{color:var(--primary);text-decoration:none;font-size:1.4rem;font-weight:700}}
h1{{font-size:1.8rem;color:var(--primary);margin-bottom:20px}}
h2{{font-size:1.2rem;color:var(--primary);margin:24px 0 10px}}
p{{margin-bottom:14px}}
ul{{margin:0 0 14px 20px}}
li{{margin-bottom:6px}}
footer{{margin-top:40px;padding-top:18px;border-top:1px solid #ddd;font-size:.82rem;color:#888;text-align:center}}
footer a{{color:var(--accent);text-decoration:none;margin:0 6px}}
</style>
</head>
<body>
<div class="wrap">
<header><a href="./">{blog_title}</a></header>
<h1>{page_title}</h1>
{body_content}
<footer>
  <p>&copy; {year} {blog_title} |
  <a href="privacy-policy.html">Privacy</a>
  <a href="terms-of-service.html">Terms</a>
  <a href="dmca.html">DMCA</a>
  <a href="contact.html">Contact</a></p>
  <p>This site uses AI-assisted content generation. Content is for informational purposes only.</p>
</footer>
</div>
</body>
</html>
"""

def _render_legal_page(
    page_title: str,
    body_content: str,
    site_config: "SiteConfig",
    slug: str,
) -> str:
    st = get_niche_styles(site_config.niche)
    lang = site_config.language
    dir_attr = 'dir="rtl"' if lang in RTL_LANGUAGES else ""
    canonical = f"{site_config.blog_url.rstrip('/')}/{slug}.html"
    return _LEGAL_TEMPLATE.format(
        lang=lang,
        dir_attr=dir_attr,
        page_title=page_title,
        blog_title=site_config.title,
        canonical=canonical,
        primary=st["primary"],
        accent=st["accent"],
        bg=st["bg"],
        text=st["text"],
        font=st["font"],
        body_content=body_content,
        year=datetime.now(timezone.utc).year,
    )


def generate_legal_pages(
    site_config: "SiteConfig",
    output_dir: Path,
) -> List[str]:
    """
    Generate all 5 legal HTML pages for a site:
      privacy-policy.html, terms-of-service.html, dmca.html,
      affiliate-disclosure.html, contact.html

    Returns list of filenames written.
    Arabic/Urdu blogs get RTL layout automatically via _render_legal_page().
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    blog_url   = site_config.blog_url.rstrip("/")
    blog_title = site_config.title
    year       = datetime.now(timezone.utc).year

    pages = [

        ("privacy-policy.html", "Privacy Policy", f"""\
<p><strong>Last updated: {year}</strong></p>
<p>This Privacy Policy describes how {blog_title} ("we", "us", or "our") collects,
uses, and shares information when you visit our website.</p>
<h2>Information We Collect</h2>
<ul>
  <li>Usage data via cookies and analytics (IP address, browser type, pages visited)</li>
  <li>Information you voluntarily provide (contact forms, newsletter signup)</li>
</ul>
<h2>How We Use Information</h2>
<ul>
  <li>To operate and improve the site</li>
  <li>To serve relevant advertisements via third-party ad networks (PopAds, Adsterra, Monetag)</li>
  <li>To send newsletters if you have subscribed</li>
</ul>
<h2>Third-Party Advertising</h2>
<p>We use third-party ad networks that may use cookies to serve ads based on your visits
to this and other websites. You may opt out of personalised advertising by visiting
<a href="https://www.aboutads.info/choices/" target="_blank">aboutads.info</a>.</p>
<h2>Cookies</h2>
<p>We use cookies to remember your preferences and for analytics. You may disable cookies
in your browser settings; some site features may not function correctly without them.</p>
<h2>GDPR Rights</h2>
<p>If you are in the European Economic Area you have the right to access, correct, or delete
your personal data. Contact us at the address below to exercise these rights.</p>
<h2>Contact</h2>
<p>For privacy inquiries please use our <a href="{blog_url}/contact.html">contact page</a>.</p>
<p><em>Note: Content on this site is AI-assisted. We disclose this in compliance with FTC guidelines.</em></p>
"""),

        ("terms-of-service.html", "Terms of Service", f"""\
<p><strong>Last updated: {year}</strong></p>
<p>By accessing {blog_title} you agree to the following terms. If you do not agree,
please do not use this site.</p>
<h2>Use of Content</h2>
<ul>
  <li>Content is provided for informational purposes only and does not constitute
      professional financial, medical, or legal advice.</li>
  <li>You may share individual articles with attribution and a link back to the original.</li>
  <li>Reproduction of the full site or systematic scraping is prohibited.</li>
</ul>
<h2>AI-Generated Content Disclosure</h2>
<p>In compliance with FTC guidelines, we disclose that some content on this site is
created or assisted by artificial intelligence. All content is reviewed for accuracy
before publication.</p>
<h2>Affiliate Disclosure</h2>
<p>This site may contain affiliate links. We may earn a commission if you click a link
and make a purchase, at no additional cost to you. See our
<a href="{blog_url}/affiliate-disclosure.html">full affiliate disclosure</a>.</p>
<h2>Limitation of Liability</h2>
<p>We make no warranties about the accuracy or completeness of content. We are not liable
for any damages arising from your use of this site.</p>
<h2>Changes to These Terms</h2>
<p>We may update these terms at any time. Continued use of the site constitutes
acceptance of the updated terms.</p>
"""),

        ("dmca.html", "DMCA Policy", f"""\
<p><strong>Last updated: {year}</strong></p>
<p>{blog_title} respects intellectual property rights and expects users to do the same.
We respond to notices of alleged copyright infringement that comply with the Digital
Millennium Copyright Act (DMCA).</p>
<h2>Reporting Infringement</h2>
<p>If you believe that content on this site infringes your copyright, please send a
written notice containing:</p>
<ul>
  <li>Your contact information (name, address, email, phone)</li>
  <li>A description of the copyrighted work you claim has been infringed</li>
  <li>The URL of the allegedly infringing content on our site</li>
  <li>A statement that you have a good faith belief the use is not authorised</li>
  <li>A statement that the information in the notice is accurate</li>
  <li>Your electronic or physical signature</li>
</ul>
<p>Send DMCA notices to our <a href="{blog_url}/contact.html">contact page</a>.</p>
<h2>Counter-Notice</h2>
<p>If you believe your content was removed in error, you may submit a counter-notice
with the required DMCA information. Repeat infringers will have their access terminated.</p>
"""),

        ("affiliate-disclosure.html", "Affiliate Disclosure", f"""\
<p><strong>Last updated: {year}</strong></p>
<p>In accordance with FTC guidelines, {blog_title} discloses the following:</p>
<h2>Affiliate Links</h2>
<p>Some links on this site are affiliate links. If you click an affiliate link and make
a purchase, we may receive a commission from the merchant at no additional cost to you.</p>
<h2>Advertisers</h2>
<p>This site also displays paid advertisements from third-party ad networks including
PopAds, Adsterra, and Monetag. The presence of these advertisements does not constitute
an endorsement of any products or services advertised.</p>
<h2>AI Content</h2>
<p>Some articles on this site are generated or assisted by artificial intelligence.
All content is reviewed for accuracy and relevance before publication. AI-assisted
articles are fact-checked where possible.</p>
<h2>Opinions</h2>
<p>All opinions expressed on this site are our own and are not influenced by advertisers
or affiliate partners.</p>
"""),

        ("contact.html", "Contact Us", f"""\
<p>Thank you for visiting {blog_title}. We welcome feedback, corrections, and partnership enquiries.</p>
<h2>General Enquiries</h2>
<p>For general questions about content, please use the form below or reach out via our
social media channels.</p>
<h2>DMCA / Copyright Notices</h2>
<p>For copyright concerns please refer to our <a href="{blog_url}/dmca.html">DMCA policy</a>
and include all required information in your message.</p>
<h2>Privacy Requests</h2>
<p>For data access or deletion requests under GDPR, please mention "Privacy Request"
in your subject line.</p>
<h2>Business &amp; Advertising</h2>
<p>For advertising inquiries, sponsored content, or partnership proposals, please include
your website URL, target audience, and budget range.</p>
<p style="margin-top:24px;padding:16px;background:#f5f5f5;border-radius:6px;">
  <em>Response time: typically 2–5 business days.</em><br>
  Please do not submit SPAM, link exchange requests, or unsolicited SEO proposals.
</p>
"""),
    ]

    written = []
    for filename, title, body_html in pages:
        slug = filename.replace(".html", "")
        html = _render_legal_page(title, body_html, site_config, slug)
        (output_dir / filename).write_text(html, encoding="utf-8")
        written.append(filename)

    _log.info(f"Generated {len(written)} legal pages for site {site_config.site_id}")
    return written


def update_index_only(
    site_config: SiteConfig,
    post_index: List[Dict],
    output_dir: Optional[Path] = None,
) -> str:
    """Regenerate only index.html and sitemap.xml (faster than full rebuild)."""
    if output_dir is None:
        output_dir = SITES_DIR / f"site-{site_config.site_id:03d}"
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    html = generate_index_html(post_index, site_config)
    (output_dir / "index.html").write_text(html, encoding="utf-8")

    sitemap = generate_sitemap_xml(post_index, site_config)
    (output_dir / "sitemap.xml").write_text(sitemap, encoding="utf-8")

    return str(output_dir / "index.html")


# ── DB migration — Phase 3B columns ────────────────────────────────────────────
def ensure_phase3b_columns() -> bool:
    """
    Add Phase 3B columns to blogs.db if they don't exist.
    Idempotent — safe to call on every startup.
    """
    try:
        from modules.database_manager import DATABASES
        db_path = DATABASES["blogs"]
        conn = sqlite3.connect(str(db_path))
        existing = {r[1] for r in conn.execute("PRAGMA table_info(blogs)").fetchall()}
        migrations = [
            ("platform",              "TEXT DEFAULT 'blogger'"),
            ("cloudflare_account_id", "TEXT"),
            ("github_path",           "TEXT"),
            ("site_url",              "TEXT"),
        ]
        for col, col_def in migrations:
            if col not in existing:
                conn.execute(f"ALTER TABLE blogs ADD COLUMN {col} {col_def}")
                _log.info(f"blogs.db: added column '{col}'")
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        _log.error(f"ensure_phase3b_columns failed: {e}")
        return False


def register_static_blog(
    site_id: int,
    blog_id: str,
    title: str,
    niche: str,
    role: str,
    language: str,
    gmail_account: str,
    cloudflare_account_id: str,
    github_path: str,
    site_url: str,
    is_adult: bool = False,
) -> Optional[int]:
    """
    Register a Phase 3B (Cloudflare Pages) blog in blogs.db.
    Returns internal row id.
    """
    try:
        from modules.database_manager import execute, fetch_one
        network = "adult" if is_adult else "safe"
        row_id = execute(
            "blogs",
            """INSERT OR IGNORE INTO blogs
               (blog_id, url, name, niche, role, language, gmail_account,
                network, created_at, status, post_count,
                platform, cloudflare_account_id, github_path, site_url)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', 0, 'cloudflare', ?, ?, ?)""",
            (blog_id, site_url, title, niche, role, language, gmail_account,
             network, datetime.now(timezone.utc).isoformat(),
             cloudflare_account_id, github_path, site_url),
        )
        row = fetch_one("blogs", "SELECT id FROM blogs WHERE blog_id=?", (blog_id,))
        db_id = row["id"] if row else row_id
        _log.info(f"Registered Cloudflare blog: id={db_id} url={site_url}")
        return db_id
    except Exception as e:
        _log.error(f"register_static_blog failed: {e}")
        return None


# ── Module self-test ────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import tempfile
    print("static_site_generator self-test...")

    cfg = SiteConfig(
        site_id=1, blog_id="site-001", title="Test Crypto Blog",
        language="en", niche="crypto",
        blog_url="https://site-001.pages.dev",
        ad_codes={"slot_1": "<!-- AD1 -->", "slot_3": "<!-- AD3 -->"},
    )
    meta = PostMeta(
        slug="bitcoin-test", title="Bitcoin Hits New High",
        meta_desc="A test post about Bitcoin.", language="en",
        published_at="2026-03-27T12:00:00Z", niche="crypto",
        keywords=["bitcoin", "crypto"], featured_image_url="",
    )
    body = "<p>This is a test paragraph about Bitcoin and crypto markets.</p>"

    with tempfile.TemporaryDirectory() as tmp:
        result = build_full_site(
            cfg,
            [{"meta": meta, "body_html": body, "hreflang_links": {}}],
            output_dir=Path(tmp),
        )
        print(f"  Files written: {result['files_written']}")
        for p in result["paths"]:
            print(f"  - {p}")
    print("  [OK] self-test passed")
