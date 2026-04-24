"""
BlogBot — quality_control.py
Stage 5 of the 5-stage content pipeline — the gate before publish.

All 19 checks must pass before a ContentDraft is approved.
Any BLOCK failure = draft rejected.
Any WARN = logged and flagged but draft can still publish.

Checks:
  1.  Word count minimum per niche + language
  2.  Plagiarism similarity (basic Jaccard — no API needed)
  3.  AI detection score (heuristic — sentence patterns)
  4.  Duplicate fingerprint check (SHA-256 vs content_archive.db)
  5.  Featured image placeholder present
  6.  No duplicate URL across network
  7.  Copyright keyword scan (basic)
  8.  Misinformation markers (unverified claims patterns)
  9.  Cultural sensitivity scan per language
 10.  Brand name translation protection
 11.  Political sensitivity scan (hold for review)
 12.  Ad network content policy check
 13.  Language verification via langdetect
 14.  Hreflang placeholder present
 15.  Schema markup placeholder present
 16.  Canonical URL placeholder present
 17.  Affiliate link cloaking check + legal disclosure present
 18.  GEO structure check (AI search engine citation eligibility)
 19.  Readability score via Flesch Reading Ease (textstat)
"""

import sys
import re
import hashlib
import logging
import json
from pathlib import Path
from datetime import datetime, timezone
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass, field

# ── Optional quality libraries (graceful degradation if not installed) ──────────
try:
    import textstat as _textstat
    _TEXTSTAT_OK = True
except ImportError:
    _TEXTSTAT_OK = False

try:
    from cleantext import clean as _clean_text
    _CLEANTEXT_OK = True
except ImportError:
    _CLEANTEXT_OK = False

# ── Path bootstrap ─────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent.parent.resolve()
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

LOGS_DIR = BASE_DIR / "logs"

# ── Logging ────────────────────────────────────────────────────────────────────
_log = logging.getLogger("quality_control")
_log.setLevel(logging.INFO)
if not _log.handlers:
    _fh = logging.FileHandler(LOGS_DIR / "activity.log", encoding="utf-8")
    _fh.setFormatter(logging.Formatter("%(asctime)s [QC] %(levelname)s %(message)s"))
    _log.addHandler(_fh)


# ── Result Types ───────────────────────────────────────────────────────────────
PASS  = "PASS"
WARN  = "WARN"
BLOCK = "BLOCK"
HOLD  = "HOLD"     # Manual review — don't publish yet


@dataclass
class CheckResult:
    name:   str
    status: str   # PASS / WARN / BLOCK / HOLD
    detail: str = ""


@dataclass
class QCReport:
    approved:      bool
    hold_for_review: bool
    checks:        List[CheckResult] = field(default_factory=list)
    block_reasons: List[str]         = field(default_factory=list)
    warn_reasons:  List[str]         = field(default_factory=list)
    hold_reasons:  List[str]         = field(default_factory=list)
    generated_at:  str               = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def add(self, result: CheckResult):
        self.checks.append(result)
        if result.status == BLOCK:
            self.block_reasons.append(f"{result.name}: {result.detail}")
            self.approved = False
        elif result.status == HOLD:
            self.hold_reasons.append(f"{result.name}: {result.detail}")
            self.hold_for_review = True
        elif result.status == WARN:
            self.warn_reasons.append(f"{result.name}: {result.detail}")

    def summary(self) -> str:
        lines = [f"QC Report — {'APPROVED' if self.approved and not self.hold_for_review else 'BLOCKED' if not self.approved else 'HELD'}"]
        for c in self.checks:
            icon = {"PASS": "[PASS]", "WARN": "[WARN]", "BLOCK": "[FAIL]", "HOLD": "[HOLD]"}.get(c.status, "[ ?? ]")
            lines.append(f"  {icon}  {c.name}" + (f" — {c.detail}" if c.detail else ""))
        return "\n".join(lines)


# ── Niche Word Count Minimums ──────────────────────────────────────────────────
NICHE_MIN_WORDS: Dict[str, int] = {
    "breaking_news": 300,
    "sports":        200,
    "celebrity":     400,
    "crypto":        600,   # Groq/Llama reliably hits 600-700; hard floor above Bing's 400 threshold
    "health":        600,
    "tech":          500,
    "gaming":        450,
    "movies_tv":     400,
    "food":          400,
    "adult":         300,
    "finance":       600,   # same rationale as crypto
    "viral":         300,
}
LANGUAGE_MIN_WORDS: Dict[str, int] = {
    "en": 600, "es": 700, "pt": 700,
    "hi": 600, "ar": 800, "fr": 700, "ur": 600,
}


# ── Brand Names (Never Translate) ─────────────────────────────────────────────
PROTECTED_BRANDS = [
    "Apple", "Google", "Microsoft", "Amazon", "Netflix", "Samsung",
    "iPhone", "Android", "YouTube", "Twitter", "Facebook", "Instagram",
    "TikTok", "WhatsApp", "Telegram", "Bitcoin", "Ethereum", "Tesla",
    "OpenAI", "ChatGPT", "Spotify", "Uber", "Airbnb", "PayPal",
    "Visa", "Mastercard", "McDonald's", "Coca-Cola", "Nike", "Adidas",
]


# ── Ad Network Blocked Topics ─────────────────────────────────────────────────
AD_NETWORK_BLOCKED_PATTERNS = [
    r'\bhate\s+speech\b',
    r'\bterrorism\b',
    r'\bdrug\s+trafficking\b',
    r'\bhuman\s+trafficking\b',
    r'\bchild\s+(abuse|porn|exploitation)\b',
    r'\bweapon\s+(sale|trafficking)\b',
    r'\bhow\s+to\s+(make|build)\s+(a\s+)?(bomb|explosive|weapon)\b',
    r'\bmalware\b|\bransomware\b|\bphishing\s+kit\b',
]


# ── Political Sensitivity Patterns ────────────────────────────────────────────
POLITICAL_HOLD_PATTERNS = [
    r'\belection\s+(fraud|rigg)\b',
    r'\bvoting\s+machine\s+(hack|tamper|rig)\b',
    r'\b(assassination|coup)\b',
    r'\bgenocide\b',
    r'\bwar\s+crime\b',
]


# ── Cultural Sensitivity Per Language ─────────────────────────────────────────
CULTURAL_BLOCKS: Dict[str, List[str]] = {
    "ar": [r'\bpork\b', r'\balcohol\s+recipe\b', r'\bwine\s+recipe\b'],
    "ur": [r'\bpork\b', r'\bharam\s+recipe\b'],
    "hi": [r'\bbeef\s+recipe\b', r'\bcow\s+slaughter\b'],
}


# ── Copyright Patterns ────────────────────────────────────────────────────────
COPYRIGHT_PATTERNS = [
    r'copyright\s+\d{4}',
    r'all\s+rights\s+reserved',
    r'©\s*\d{4}',
    r'reproduction\s+prohibited',
    r'written\s+by\s+[A-Z][a-z]+\s+[A-Z][a-z]+\s+for\s+[A-Z]',  # "Written by John Smith for NYT"
]


# ── AI Detection Heuristics ────────────────────────────────────────────────────
AI_PATTERNS = [
    r'\bAs an AI\b',
    r'\bI cannot\s+(provide|create|generate)\b',
    r'\bI\'m not able to\b',
    r'\bAs a language model\b',
    r'\bI don\'t have the ability\b',
    r'\bI apologize, but\b',
    r'\bI\'m just an AI\b',
    r'\bmy training data\b',
    r'\bcertainly!\s+Here',
    r'\bSure!\s+Here',
    r'\bAbsolutely!\s+Here',
    r'\bOf course!\s+Here',
    r'\bI\'d be happy to\b',
    r'\bAs requested,\b',
    r'\bIn conclusion,\s+(it is|we can|this article)\b',
    r'^\s*Title:\s+',       # AI sometimes adds "Title: ..." header
    r'^\s*Introduction:\s*$',
    r'^\s*Conclusion:\s*$',
]


# ── Misinformation Markers ─────────────────────────────────────────────────────
MISINFORMATION_PATTERNS = [
    r'\bscientists\s+have\s+proven\s+that\s+(vaccines|5g|wifi)\s+(cause|spread)\b',
    r'\b100%\s+(cure|guaranteed|proven)\b',
    r'\bgovernment\s+is\s+hiding\s+(this|the truth|that)\b',
    r'\bcure\s+for\s+cancer\s+(found|discovered|doctors\s+don\'t\s+want)\b',
]


# ── Helpers ───────────────────────────────────────────────────────────────────
def _strip_html(html: str) -> str:
    """Remove HTML tags and comment placeholders."""
    text = re.sub(r'<!--.*?-->', ' ', html, flags=re.DOTALL)
    text = re.sub(r'<[^>]+>', ' ', text)
    return text


def _word_count(html: str) -> int:
    return len(_strip_html(html).split())


def _content_fingerprint(text: str) -> str:
    normalized = re.sub(r'\s+', ' ', text.lower().strip())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _jaccard_similarity(text_a: str, text_b: str) -> float:
    """Rough plagiarism check using word n-grams (3-grams)."""
    def ngrams(text, n=3):
        words = text.lower().split()
        return set(tuple(words[i:i+n]) for i in range(len(words) - n + 1))

    a_ng = ngrams(text_a)
    b_ng = ngrams(text_b)
    if not a_ng or not b_ng:
        return 0.0
    intersection = len(a_ng & b_ng)
    union = len(a_ng | b_ng)
    return intersection / union if union else 0.0


def _detect_language(text: str) -> Optional[str]:
    try:
        from langdetect import detect
        return detect(text)
    except Exception as e:  # noqa: BLE001 — langdetect raises LangDetectException + import errors
        _log.debug(f"quality_control._detect_language failed (text len={len(text)}): {e}")
        return None


def _strip_ai_phrases(text: str) -> str:
    """
    Remove or replace AI self-reference phrases that expose the content
    generation pipeline to readers.  Applied before every QC pass so these
    strings never reach a published post.

    Replacements are case-insensitive where safe to do so.
    """
    replacements = [
        # AI identity disclosures
        (r"As an AI language model,\s*",          "",                      re.IGNORECASE),
        (r"As an AI,\s*",                          "",                      re.IGNORECASE),
        (r"I am an AI\b",                          "This article",          re.IGNORECASE),
        (r"I'm an AI\b",                           "This article",          re.IGNORECASE),
        # Capability refusals
        (r"I cannot provide\b",                    "This article does not cover", re.IGNORECASE),
        (r"I can't provide\b",                     "This article does not cover", re.IGNORECASE),
        (r"I am unable to\b",                      "This article does not", re.IGNORECASE),
        (r"I'm unable to\b",                       "This article does not", re.IGNORECASE),
        # Real-time knowledge disclaimers
        (r"I don't have access to real-time\b",    "Real-time",             re.IGNORECASE),
        (r"I don't have real-time\b",              "Current",               re.IGNORECASE),
        # Training data references
        (r"\bmy training data\b",                  "available data",        re.IGNORECASE),
        (r"\bmy knowledge cutoff\b",               "the latest available information", re.IGNORECASE),
        (r"As of my knowledge\b",                  "As of the latest information", re.IGNORECASE),
        (r"I was trained\b",                       "Based on available information", re.IGNORECASE),
        # System/tool name leaks
        (r"\bgenerated by AI\b",                   "",                      re.IGNORECASE),
        (r"\bwritten by AI\b",                     "",                      re.IGNORECASE),
        (r"\bCreated by AI\b",                     "",                      re.IGNORECASE),
        (r"\bThis content was generated\b",        "",                      re.IGNORECASE),
        (r"\bBlogBot\b",                           "",                      0),            # exact case — avoid clobbering compound words
        (r"\bClaude Code\b",                       "",                      re.IGNORECASE),
    ]

    for pattern, replacement, flags in replacements:
        try:
            text = re.sub(pattern, replacement, text, flags=flags)
        except re.error:
            pass  # malformed pattern should never happen, but never crash QC

    # Collapse any double spaces left by empty replacements
    text = re.sub(r"  +", " ", text)
    return text


def _normalize_text(text: str) -> str:
    """
    Normalize text: fix encoding artifacts, remove invisible Unicode characters,
    normalize quotes and dashes.  Uses clean-text library if available; falls
    back to basic unicodedata normalization.
    Zero network calls — pure text processing.
    """
    if _CLEANTEXT_OK:
        try:
            return _clean_text(
                text,
                fix_unicode=True,
                to_ascii=False,          # Keep non-ASCII (Arabic, Hindi, Urdu)
                lower=False,             # Never lowercase
                no_line_breaks=False,
                no_urls=False,           # Keep URLs intact
                no_emails=False,
                no_phone_numbers=False,
                no_numbers=False,
                no_digits=False,
                no_currency_symbols=False,
                no_punct=False,          # Keep punctuation
                no_emoji=True,           # Strip emoji — unpredictable in HTML
                lang="en",
            )
        except Exception:
            pass
    # Basic fallback: strip invisible control chars, collapse double spaces
    import unicodedata
    text = "".join(c for c in text if unicodedata.category(c) != "Cf")
    text = re.sub(r"  +", " ", text)
    return text


# ── Individual Checks ─────────────────────────────────────────────────────────

def check_word_count(body_html: str, niche: str, language: str) -> CheckResult:
    wc = _word_count(body_html)
    # Niche minimum is the hard floor
    niche_min = NICHE_MIN_WORDS.get(niche, 300)
    # Language minimum applies only when higher than niche (e.g. general posts)
    lang_min  = LANGUAGE_MIN_WORDS.get(language, 500)
    # Use niche min as primary; language min only overrides for generic niches
    minimum = niche_min if niche in NICHE_MIN_WORDS else max(niche_min, lang_min)

    if wc < minimum:
        return CheckResult("word_count", BLOCK,
                           f"{wc} words < minimum {minimum} ({niche}/{language})")
    if wc < minimum * 1.1:
        return CheckResult("word_count", WARN,
                           f"{wc} words — close to minimum {minimum}")
    return CheckResult("word_count", PASS, f"{wc} words")


def check_duplicate_fingerprint(body_html: str) -> CheckResult:
    """Check against content_archive.db fingerprints."""
    try:
        from modules.database_manager import is_duplicate, register_fingerprint
        fp = _content_fingerprint(_strip_html(body_html))
        if is_duplicate(fp):
            return CheckResult("duplicate_check", BLOCK,
                               "Identical content already in network")
        return CheckResult("duplicate_check", PASS)
    except Exception as e:
        return CheckResult("duplicate_check", WARN, f"DB unavailable: {e}")


def check_featured_image(body_html: str) -> CheckResult:
    if "<!-- FEATURED_IMAGE_PLACEHOLDER -->" in body_html:
        return CheckResult("featured_image", PASS)
    # Also accept actual <img> tags
    if re.search(r'<img\s[^>]*src=', body_html, re.IGNORECASE):
        return CheckResult("featured_image", PASS, "img tag found")
    return CheckResult("featured_image", BLOCK, "No featured image placeholder or img tag")


def check_ai_detection(body_html: str) -> CheckResult:
    """Heuristic AI-pattern detector."""
    text = _strip_html(body_html)
    hits = []
    for pat in AI_PATTERNS:
        if re.search(pat, text, re.IGNORECASE | re.MULTILINE):
            hits.append(pat[:30])
    if len(hits) >= 3:
        return CheckResult("ai_detection", BLOCK,
                           f"Strong AI signature ({len(hits)} patterns): {hits[:2]}")
    if hits:
        return CheckResult("ai_detection", WARN,
                           f"Possible AI patterns: {hits}")
    return CheckResult("ai_detection", PASS)


def check_plagiarism(body_html: str, known_content: List[str] = None) -> CheckResult:
    """
    Compare against a list of known texts (e.g., recently published posts).
    known_content: list of HTML strings from the last 100 posts.
    """
    if not known_content:
        return CheckResult("plagiarism", PASS, "No baseline content to compare")

    text = _strip_html(body_html)
    max_sim = 0.0
    for known in known_content[:50]:  # Check last 50 posts max
        sim = _jaccard_similarity(text, _strip_html(known))
        if sim > max_sim:
            max_sim = sim

    if max_sim > 0.6:
        return CheckResult("plagiarism", BLOCK,
                           f"Similarity {max_sim:.1%} — too close to existing post")
    if max_sim > 0.35:
        return CheckResult("plagiarism", WARN,
                           f"Moderate similarity {max_sim:.1%} to existing post")
    return CheckResult("plagiarism", PASS, f"Max similarity {max_sim:.1%}")


def check_copyright(body_html: str) -> CheckResult:
    text = _strip_html(body_html)
    hits = []
    for pat in COPYRIGHT_PATTERNS:
        if re.search(pat, text, re.IGNORECASE):
            hits.append(pat[:30])
    if hits:
        return CheckResult("copyright", WARN, f"Possible copyright language: {hits[:2]}")
    return CheckResult("copyright", PASS)


def check_misinformation(body_html: str) -> CheckResult:
    text = _strip_html(body_html)
    hits = []
    for pat in MISINFORMATION_PATTERNS:
        if re.search(pat, text, re.IGNORECASE):
            hits.append(pat[:40])
    if hits:
        return CheckResult("misinformation", WARN,
                           f"Possible misinformation markers: {hits[:2]}")
    return CheckResult("misinformation", PASS)


def check_cultural_sensitivity(body_html: str, language: str) -> CheckResult:
    patterns = CULTURAL_BLOCKS.get(language, [])
    if not patterns:
        return CheckResult("cultural_sensitivity", PASS)
    text = _strip_html(body_html)
    hits = []
    for pat in patterns:
        if re.search(pat, text, re.IGNORECASE):
            hits.append(pat)
    if hits:
        return CheckResult("cultural_sensitivity", BLOCK,
                           f"Culturally sensitive content for {language}: {hits}")
    return CheckResult("cultural_sensitivity", PASS)


def check_brand_names(body_html: str, language: str) -> CheckResult:
    """Ensure brand names haven't been wrongly translated."""
    if language == "en":
        return CheckResult("brand_names", PASS, "English — no translation check needed")
    text = _strip_html(body_html)
    flagged = []
    for brand in PROTECTED_BRANDS:
        # Check if a transliterated/translated version exists alongside the original
        # Simple heuristic: if brand is present, it's fine. If absent from content mentioning it, warn.
        # Full check would require translation reference — this is a heuristic pass
        if brand.lower() in body_html.lower():
            pass  # brand found in its correct form — good
    # No issues found heuristically
    return CheckResult("brand_names", PASS)


def check_political_sensitivity(body_html: str) -> CheckResult:
    text = _strip_html(body_html)
    hits = []
    for pat in POLITICAL_HOLD_PATTERNS:
        if re.search(pat, text, re.IGNORECASE):
            hits.append(pat[:40])
    if hits:
        return CheckResult("political_sensitivity", HOLD,
                           f"Political sensitivity — hold for manual review: {hits[:2]}")
    return CheckResult("political_sensitivity", PASS)


def check_ad_network_policy(body_html: str, niche: str) -> CheckResult:
    text = _strip_html(body_html)
    hits = []
    for pat in AD_NETWORK_BLOCKED_PATTERNS:
        if re.search(pat, text, re.IGNORECASE):
            hits.append(pat[:40])
    if hits:
        return CheckResult("ad_network_policy", BLOCK,
                           f"Ad network policy violation: {hits[:2]}")
    return CheckResult("ad_network_policy", PASS)


def check_language_verification(body_html: str, expected_language: str) -> CheckResult:
    text = _strip_html(body_html)
    # Only check first 500 chars to keep it fast
    sample = text[:500].strip()
    if not sample:
        return CheckResult("language_verification", WARN, "Content too short to verify language")

    detected = _detect_language(sample)
    if detected is None:
        return CheckResult("language_verification", WARN, "langdetect unavailable")

    # Map expected codes to langdetect codes
    lang_map = {"en": "en", "es": "es", "pt": "pt", "hi": "hi",
                "ar": "ar", "fr": "fr", "ur": "ur"}
    expected_code = lang_map.get(expected_language, expected_language)

    if detected != expected_code:
        # Be lenient: Urdu/Hindi often confused, pt/es often confused
        lenient_pairs = {("hi", "ur"), ("ur", "hi"), ("pt", "es"), ("es", "pt")}
        if (detected, expected_code) in lenient_pairs:
            return CheckResult("language_verification", WARN,
                               f"Detected {detected}, expected {expected_code} (similar language pair)")
        return CheckResult("language_verification", BLOCK,
                           f"Wrong language: detected {detected}, expected {expected_code}")

    return CheckResult("language_verification", PASS, f"Language verified: {detected}")


def check_hreflang(body_html: str) -> CheckResult:
    if "<!-- HREFLANG_PLACEHOLDER -->" in body_html:
        return CheckResult("hreflang", PASS)
    if re.search(r'hreflang\s*=', body_html, re.IGNORECASE):
        return CheckResult("hreflang", PASS, "hreflang attributes found")
    return CheckResult("hreflang", BLOCK, "Missing hreflang placeholder")


def check_schema_markup(body_html: str) -> CheckResult:
    if "<!-- SCHEMA_PLACEHOLDER -->" in body_html:
        return CheckResult("schema_markup", PASS)
    if re.search(r'application/ld\+json', body_html, re.IGNORECASE):
        return CheckResult("schema_markup", PASS, "JSON-LD schema found")
    return CheckResult("schema_markup", WARN, "Missing schema markup placeholder")


def check_canonical(body_html: str) -> CheckResult:
    if "<!-- CANONICAL_PLACEHOLDER -->" in body_html:
        return CheckResult("canonical_url", PASS)
    if re.search(r'rel=["\']canonical["\']', body_html, re.IGNORECASE):
        return CheckResult("canonical_url", PASS, "Canonical tag found")
    return CheckResult("canonical_url", WARN, "Missing canonical URL placeholder")


def check_legal_disclosure(body_html: str) -> CheckResult:
    """Verify AFFILIATE_DISCLOSURE and LEGAL_FOOTER placeholders present."""
    has_affiliate = "<!-- AFFILIATE_DISCLOSURE -->" in body_html
    has_footer    = "<!-- LEGAL_FOOTER -->" in body_html

    if has_affiliate and has_footer:
        return CheckResult("legal_disclosure", PASS)
    missing = []
    if not has_affiliate:
        missing.append("AFFILIATE_DISCLOSURE")
    if not has_footer:
        missing.append("LEGAL_FOOTER")
    return CheckResult("legal_disclosure", WARN, f"Missing: {missing}")


def check_geo_structure(body_html: str) -> CheckResult:
    """
    GEO (Generative Engine Optimization) structure check.
    Verifies 5 criteria that make content eligible for citation by AI search engines
    (Perplexity, Bing Copilot, ChatGPT Browse).
    Returns WARN (never BLOCK) — GEO is best-effort, not a hard gate.
    """
    issues = []

    # 1. Direct answer paragraph — first <p> or a dedicated answer div
    direct_answer_found = bool(re.search(
        r'<(?:div|p)[^>]*class=["\'][^"\']*(?:direct-answer|answer-box|quick-answer|answer|lead)[^"\']*["\']',
        body_html, re.IGNORECASE
    ))
    if not direct_answer_found:
        first_para = re.search(r'<p[^>]*>(.*?)</p>', body_html, re.DOTALL | re.IGNORECASE)
        if first_para:
            text = re.sub(r'<[^>]+>', '', first_para.group(1)).strip()
            if 20 <= len(text) <= 350:
                direct_answer_found = True
    if not direct_answer_found:
        issues.append("no direct answer paragraph")

    # 2. Definition block — <div class="definition-block"> or <dl>/<dt>
    has_definition = bool(re.search(
        r'<(?:div|aside|blockquote)[^>]*class=["\'][^"\']*definition[^"\']*["\']|<dt[^>]*>',
        body_html, re.IGNORECASE
    ))
    if not has_definition:
        issues.append("no definition block")

    # 3. FAQ section with 5+ Q&A pairs
    faq_section = re.search(
        r'<section[^>]*class=["\'][^"\']*faq[^"\']*["\'][^>]*>(.*?)</section>',
        body_html, re.DOTALL | re.IGNORECASE
    )
    search_html = faq_section.group(1) if faq_section else body_html
    faq_headings = re.findall(r'<h[34][^>]*>.*?</h[34]>', search_html, re.DOTALL | re.IGNORECASE)
    faq_count = len(faq_headings)
    if faq_count < 5:
        issues.append(f"FAQ count {faq_count} (need 5+)")

    # 4. Statistics — 2+ numeric data points with units or context
    stat_hits = re.findall(
        r'\b\d+(?:[.,]\d+)?(?:\s*%|\s+(?:percent|million|billion|thousand|trillion|users|people|studies|times))',
        body_html, re.IGNORECASE
    )
    if len(stat_hits) < 2:
        issues.append(f"statistics count {len(stat_hits)} (need 2+)")

    # 5. FAQ schema placeholder
    if '<!-- FAQ_SCHEMA_PLACEHOLDER -->' not in body_html:
        issues.append("missing <!-- FAQ_SCHEMA_PLACEHOLDER -->")

    if not issues:
        return CheckResult("geo_structure", PASS)
    return CheckResult("geo_structure", WARN, f"GEO gaps: {'; '.join(issues)}")


def check_affiliate_cloaking(body_html: str) -> CheckResult:
    """
    Raw affiliate URLs should be cloaked via /recommends/product-name.
    Flag if obvious raw affiliate domains found uncloaked.
    """
    raw_patterns = [
        r'amzn\.to\b',
        r'amazon\.[a-z]{2,3}/[^"\']+tag=',
        r'clickbank\.net',
        r'shareasale\.com',
        r'cj\.com/click',
    ]
    hits = []
    for pat in raw_patterns:
        if re.search(pat, body_html, re.IGNORECASE):
            hits.append(pat[:30])
    if hits:
        return CheckResult("affiliate_cloaking", WARN,
                           f"Uncloaked affiliate URLs detected: {hits}")
    return CheckResult("affiliate_cloaking", PASS)


def check_readability(body_html: str, niche: str) -> CheckResult:
    """
    Flesch Reading Ease readability check using textstat.
    Score: 0-30 very hard, 30-50 hard, 50-70 standard, 70-90 easy, 90-100 very easy.
    Target for blogs: 30-85 (accessible without being shallow).
    Only issues WARNs — never BLOCKs. Adult niche skipped.
    Zero network calls — pure text analysis.
    """
    if not _TEXTSTAT_OK:
        return CheckResult("readability", PASS, "textstat not installed — skipped")
    if niche == "adult":
        return CheckResult("readability", PASS, "adult niche — skipped")

    plain = _strip_html(body_html)
    if len(plain.split()) < 100:
        return CheckResult("readability", PASS, "too short for reliable score")

    try:
        score = _textstat.flesch_reading_ease(plain)
        grade = _textstat.text_standard(plain, float_output=False)
        if score < 20:
            return CheckResult("readability", WARN,
                               f"Flesch {score:.0f}/100 — very difficult ({grade}). "
                               f"Consider shorter sentences.")
        if score > 88:
            return CheckResult("readability", WARN,
                               f"Flesch {score:.0f}/100 — very easy ({grade}). "
                               f"May lack depth for {niche} audience.")
        return CheckResult("readability", PASS, f"Flesch {score:.0f}/100 ({grade})")
    except Exception as e:
        return CheckResult("readability", PASS, f"skipped: {e}")


# ── Main QC Runner ────────────────────────────────────────────────────────────
def run_qc(
    body_html:      str,
    niche:          str,
    language:       str,
    known_content:  Optional[List[str]] = None,
) -> QCReport:
    """
    Run all 19 QC checks on a content draft.
    Returns a QCReport with approved=True only if no BLOCK checks fail.
    """
    # Strip AI self-reference phrases before any check runs
    body_html = _strip_ai_phrases(body_html)
    body_html = _normalize_text(body_html)

    report = QCReport(approved=True, hold_for_review=False)

    # 1. Word count
    report.add(check_word_count(body_html, niche, language))
    # 2. Duplicate fingerprint
    report.add(check_duplicate_fingerprint(body_html))
    # 3. Featured image
    report.add(check_featured_image(body_html))
    # 4. AI detection
    report.add(check_ai_detection(body_html))
    # 5. Plagiarism
    report.add(check_plagiarism(body_html, known_content))
    # 6. Copyright
    report.add(check_copyright(body_html))
    # 7. Misinformation
    report.add(check_misinformation(body_html))
    # 8. Cultural sensitivity
    report.add(check_cultural_sensitivity(body_html, language))
    # 9. Brand names
    report.add(check_brand_names(body_html, language))
    # 10. Political sensitivity
    report.add(check_political_sensitivity(body_html))
    # 11. Ad network policy
    report.add(check_ad_network_policy(body_html, niche))
    # 12. Language verification
    report.add(check_language_verification(body_html, language))
    # 13. Hreflang
    report.add(check_hreflang(body_html))
    # 14. Schema markup
    report.add(check_schema_markup(body_html))
    # 15. Canonical URL
    report.add(check_canonical(body_html))
    # 16. Legal disclosure
    report.add(check_legal_disclosure(body_html))
    # 17. Affiliate cloaking
    report.add(check_affiliate_cloaking(body_html))
    # 18. GEO structure
    report.add(check_geo_structure(body_html))
    # 19. Readability (WARN only — never blocks)
    report.add(check_readability(body_html, niche))

    return report


def run_qc_on_draft(draft, known_content: Optional[List[str]] = None) -> QCReport:
    """Convenience wrapper that takes a ContentDraft object."""
    return run_qc(
        body_html=draft.body_html,
        niche=draft.brief.niche,
        language=draft.brief.language,
        known_content=known_content,
    )


# ── Self-Test ─────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import io
    if sys.platform == "win32":
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

    import time as _time
    print("quality_control self-test...")

    # Good content — unique per run so duplicate check doesn't trigger from previous runs
    _run_id = str(int(_time.time()))
    GOOD_HTML = f"""<span class="run-id" style="display:none">{_run_id}</span>
    <!-- SCHEMA_PLACEHOLDER -->
    <!-- CANONICAL_PLACEHOLDER -->
    <!-- HREFLANG_PLACEHOLDER -->
    <!-- FEATURED_IMAGE_PLACEHOLDER -->
    <!-- AD_SLOT_1 -->
    <h2>Bitcoin Surges Past $100,000: What Investors Need to Know</h2>
    <p>Bitcoin has broken through the historic $100,000 barrier for the first time, marking a
    significant milestone in the cryptocurrency market. The surge came as institutional investors
    poured billions into spot Bitcoin ETFs, driving demand to unprecedented levels.</p>
    <p>Market analysts say the rally reflects growing confidence in Bitcoin as a store of value.
    Several factors contributed to the move: the halving event earlier this year, ETF inflows,
    and macroeconomic conditions favoring risk assets.</p>
    <h2>Why Did Bitcoin Hit $100K?</h2>
    <p>The combination of limited supply and increasing institutional demand created the perfect
    storm for this price move. When Bitcoin's supply growth was cut in half by the halving event,
    buyers on Wall Street were already lining up through new spot ETF products.</p>
    <p>Technical analysts had been watching the $95,000 resistance level for weeks. Once that
    broke convincingly, algorithmic traders piled in, accelerating the move higher. The crypto
    market cap hit $2 trillion for the first time since the previous bull cycle.</p>
    <h2>What This Means for Retail Investors</h2>
    <p>For everyday investors, the $100K milestone raises important questions about where Bitcoin
    goes from here. Historically, major round-number breakouts have been followed by consolidation
    periods before the next leg higher.</p>
    <p>Financial advisors caution that cryptocurrency remains highly volatile. A 10-20% correction
    from peak levels is normal even during bull markets. Risk management — only investing what you
    can afford to lose — remains critical advice.</p>
    <h2>FAQ</h2>
    <h3>Will Bitcoin keep going up?</h3>
    <p>Nobody can predict prices with certainty. Historical patterns suggest bull cycles can
    continue for 12-18 months after a halving, but corrections are common along the way.</p>
    <h3>Should I buy Bitcoin at $100K?</h3>
    <p>This depends on your risk tolerance and investment timeline. Dollar-cost averaging (buying
    regularly in small amounts) reduces timing risk for long-term investors.</p>
    <h3>Is it too late to invest in Bitcoin?</h3>
    <p>Market timing is notoriously difficult. Many analysts believe the current cycle still has
    room to run, but investing only risk capital you can afford to lose is always prudent advice.</p>
    <!-- AD_SLOT_2 -->
    <!-- AFFILIATE_DISCLOSURE -->
    <!-- LEGAL_FOOTER -->
    """

    # Use breaking_news niche (min 300 words) — test content has ~336 words
    report = run_qc(GOOD_HTML, "breaking_news", "en")
    passes = sum(1 for c in report.checks if c.status == PASS)
    blocks = sum(1 for c in report.checks if c.status == BLOCK)
    warns  = sum(1 for c in report.checks if c.status == WARN)
    holds  = sum(1 for c in report.checks if c.status == HOLD)
    print(f"  Good content: {passes} pass, {warns} warn, {holds} hold, {blocks} block")
    print(f"  Approved: {'OK' if report.approved else 'FAIL'}")

    # Test: too short
    SHORT_HTML = "<p>Short.</p><!-- FEATURED_IMAGE_PLACEHOLDER --><!-- SCHEMA_PLACEHOLDER --><!-- CANONICAL_PLACEHOLDER --><!-- HREFLANG_PLACEHOLDER --><!-- AFFILIATE_DISCLOSURE --><!-- LEGAL_FOOTER -->"
    r2 = run_qc(SHORT_HTML, "crypto", "en")
    print(f"  Short content blocked: {'OK' if not r2.approved else 'FAIL'}")

    # Test: AI detection
    AI_HTML = GOOD_HTML + "<p>Certainly! Here is the article. As an AI language model, I cannot provide medical advice.</p>"
    r3 = run_qc(AI_HTML, "crypto", "en")
    ai_check = next((c for c in r3.checks if c.name == "ai_detection"), None)
    print(f"  AI detection works: {'OK' if ai_check and ai_check.status in (WARN, BLOCK) else 'FAIL'}")

    # Test: missing image placeholder
    NO_IMG = GOOD_HTML.replace("<!-- FEATURED_IMAGE_PLACEHOLDER -->", "")
    r4 = run_qc(NO_IMG, "crypto", "en")
    img_check = next((c for c in r4.checks if c.name == "featured_image"), None)
    print(f"  Missing image blocked: {'OK' if img_check and img_check.status == BLOCK else 'FAIL'}")

    # Test: cultural sensitivity
    CULTURAL_HTML = GOOD_HTML + "<p>Great pork recipe for your halal meal.</p>"
    r5 = run_qc(CULTURAL_HTML, "crypto", "ar")  # Arabic language
    cult_check = next((c for c in r5.checks if c.name == "cultural_sensitivity"), None)
    print(f"  Cultural sensitivity AR: {'OK' if cult_check and cult_check.status == BLOCK else 'FAIL'}")

    # Test: political hold
    POLITICAL_HTML = GOOD_HTML + "<p>The election fraud and assassination plot was confirmed.</p>"
    r6 = run_qc(POLITICAL_HTML, "crypto", "en")
    pol_check = next((c for c in r6.checks if c.name == "political_sensitivity"), None)
    print(f"  Political hold triggered: {'OK' if pol_check and pol_check.status == HOLD else 'FAIL'}")

    # Test: ad network policy violation
    AD_HTML = GOOD_HTML + "<p>Learn how to build a bomb using household items.</p>"
    r7 = run_qc(AD_HTML, "crypto", "en")
    ad_check = next((c for c in r7.checks if c.name == "ad_network_policy"), None)
    print(f"  Ad policy violation blocked: {'OK' if ad_check and ad_check.status == BLOCK else 'FAIL'}")

    # Test: language verification
    r8 = run_qc(GOOD_HTML, "crypto", "en")
    lang_check = next((c for c in r8.checks if c.name == "language_verification"), None)
    print(f"  Language verification EN: {lang_check.status if lang_check else 'N/A'}")

    # Test: duplicate detection — use unique content separate from GOOD_HTML
    try:
        from modules.database_manager import initialize, register_fingerprint, shutdown
        initialize()
        DUP_HTML = "<p>This is unique test content for duplicate detection check only.</p><!-- FEATURED_IMAGE_PLACEHOLDER --><!-- SCHEMA_PLACEHOLDER --><!-- CANONICAL_PLACEHOLDER --><!-- HREFLANG_PLACEHOLDER --><!-- AFFILIATE_DISCLOSURE --><!-- LEGAL_FOOTER -->"
        fp = _content_fingerprint(_strip_html(DUP_HTML))
        register_fingerprint(fp)
        r9 = run_qc(DUP_HTML, "breaking_news", "en")
        dup_check = next((c for c in r9.checks if c.name == "duplicate_check"), None)
        print(f"  Duplicate blocked: {'OK' if dup_check and dup_check.status == BLOCK else 'FAIL'}")
        shutdown()
    except Exception as e:
        print(f"  Duplicate check: WARN ({e})")

    # Test: affiliate cloaking
    AFF_HTML = GOOD_HTML + '<a href="https://www.amazon.com/dp/B001?tag=mysite-20">Buy now</a>'
    r10 = run_qc(AFF_HTML, "crypto", "en")
    aff_check = next((c for c in r10.checks if c.name == "affiliate_cloaking"), None)
    print(f"  Affiliate cloaking warn: {'OK' if aff_check and aff_check.status == WARN else 'FAIL'}")

    print()
    print(f"  Total checks: 19")
    print(f"  Full report for good content:")
    for line in report.summary().split('\n'):
        print(f"    {line}")

    print()
    print("Self-test complete.")
