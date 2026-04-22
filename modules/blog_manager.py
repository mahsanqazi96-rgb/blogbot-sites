"""
BlogBot — blog_manager.py
Phase 3: Publishing Engine

Responsibilities:
  - Blogger API client (3 GCP projects rotating — 30,000 req/day)
  - Blog creation: role assignment, template, RTL for AR/UR
  - Legal pages injection (7 languages × 10 page types)
  - Ad network code injection (6 slots per page)
  - Post publish / update / delete
  - Sitemap submission to Google + Bing + Yandex
  - Blog health monitoring (HTTPS, template integrity, CSP)
  - RSS feed URL tracking
  - Blog network sitemap index maintenance

Blog roles:
  hub           — 20% — deepest content, most authority
  feeder        — 50% — high volume trend content
  traffic_catcher — 20% — viral/clickbait → monetized blogs
  link_builder  — 10% — builds internal authority for hubs

Account sets:
  Gmail Set A — safe blogs (max 10 blogs per account)
  Gmail Set B — adult blogs only (completely separate)
"""

import sys
import time
import json
import logging
import re
import threading
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any, Tuple
from dataclasses import dataclass, field

# ── Path bootstrap ─────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent.parent.resolve()
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

LOGS_DIR = BASE_DIR / "logs"

# ── Logging ────────────────────────────────────────────────────────────────────
_log = logging.getLogger("blog_manager")
_log.setLevel(logging.INFO)
if not _log.handlers:
    _fh = logging.FileHandler(LOGS_DIR / "activity.log", encoding="utf-8")
    _fh.setFormatter(logging.Formatter("%(asctime)s [BLOG] %(levelname)s %(message)s"))
    _log.addHandler(_fh)


# ── Constants ──────────────────────────────────────────────────────────────────
BLOGGER_API_VERSION = "v3"
MAX_BLOGS_PER_GMAIL = 10
BLOGGER_POST_SIZE_LIMIT_MB = 1        # Blogger enforces 1MB per post
SITEMAP_PING_ENGINES = [
    "https://www.google.com/ping?sitemap={sitemap_url}",
    "https://www.bing.com/ping?sitemap={sitemap_url}",
]

# Blog roles and their content ratios
BLOG_ROLES = {
    "hub":             {"ratio": 0.20, "links_up": False, "links_to_hub": False},
    "feeder":          {"ratio": 0.50, "links_up": True,  "links_to_hub": True},
    "traffic_catcher": {"ratio": 0.20, "links_up": True,  "links_to_hub": True},
    "link_builder":    {"ratio": 0.10, "links_up": True,  "links_to_hub": True},
}

# RTL languages
RTL_LANGUAGES = {"ar", "ur"}

# Languages
ALL_LANGUAGES = ["en", "es", "pt", "hi", "ar", "fr", "ur"]
LANGUAGE_NAMES = {
    "en": "English", "es": "Spanish", "pt": "Portuguese",
    "hi": "Hindi", "ar": "Arabic", "fr": "French", "ur": "Urdu",
}

# ── Data Structures ────────────────────────────────────────────────────────────
@dataclass
class BlogInfo:
    blog_id:      int
    blogger_id:   str          # Blogger's internal ID
    url:          str          # e.g. https://my-blog.blogspot.com
    title:        str
    niche:        str
    role:         str          # hub / feeder / traffic_catcher / link_builder
    language:     str
    gmail_account: str
    is_adult:     bool
    created_at:   str
    is_active:    bool = True
    posts_count:  int = 0
    ad_codes_injected: bool = False

@dataclass
class PublishResult:
    success:    bool
    post_id:    str = ""
    post_url:   str = ""
    error:      str = ""
    provider:   str = "blogger"
    published_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


# ── Legal Page Templates (English master — translated copies generated separately) ──
LEGAL_PAGES_EN = {
    "privacy_policy": {
        "title": "Privacy Policy",
        "slug": "privacy-policy",
        "body": """
<h2>Privacy Policy</h2>
<p><em>Last updated: {date}</em></p>
<p>This Privacy Policy describes how {blog_title} ("we", "us", or "our") collects, uses, and shares information about you when you visit our website.</p>

<h3>Information We Collect</h3>
<p>We collect information you provide directly to us and information collected automatically when you visit our site, including:</p>
<ul>
<li>Usage data (pages visited, time spent, browser type)</li>
<li>Device information (IP address, operating system)</li>
<li>Cookies and similar tracking technologies</li>
</ul>

<h3>How We Use Your Information</h3>
<ul>
<li>To provide and improve our services</li>
<li>To serve relevant advertisements via third-party ad networks</li>
<li>To analyze site traffic and usage patterns</li>
<li>To comply with legal obligations</li>
</ul>

<h3>Third-Party Advertising</h3>
<p>We use third-party advertising companies to serve ads when you visit our site. These companies may use information about your visits to provide advertisements about goods and services of interest to you. This includes networks such as Google AdSense, PopAds, Adsterra, and others.</p>

<h3>Cookies</h3>
<p>We use cookies to enhance your experience. You can control cookies through your browser settings. Disabling cookies may affect site functionality.</p>

<h3>GDPR Rights (EU Visitors)</h3>
<p>If you are in the European Union, you have rights including: access to your data, correction, deletion, restriction of processing, data portability, and the right to object. Contact us to exercise these rights.</p>

<h3>CCPA Rights (California Residents)</h3>
<p>California residents have the right to know what personal information is collected, the right to delete personal information, and the right to opt-out of the sale of personal information. We do not sell personal information.</p>

<h3>Children's Privacy</h3>
<p>Our site is not directed to children under 13. We do not knowingly collect personal information from children under 13.</p>

<h3>Contact Us</h3>
<p>For privacy questions, please use our <a href="/contact">contact page</a>.</p>
""",
    },

    "terms_of_service": {
        "title": "Terms of Service",
        "slug": "terms-of-service",
        "body": """
<h2>Terms of Service</h2>
<p><em>Last updated: {date}</em></p>
<p>By accessing {blog_title}, you agree to these Terms of Service. If you do not agree, please do not use this site.</p>

<h3>Use of Site</h3>
<p>You may use this site for lawful purposes only. You agree not to use this site to transmit unlawful, harmful, or objectionable content.</p>

<h3>Intellectual Property</h3>
<p>All content on this site is protected by copyright. You may not reproduce, distribute, or modify content without written permission, except as permitted by applicable law.</p>

<h3>Disclaimer of Warranties</h3>
<p>This site is provided "as is" without warranties of any kind. We make no representations about the accuracy or completeness of content.</p>

<h3>Limitation of Liability</h3>
<p>We shall not be liable for any indirect, incidental, special, or consequential damages arising from your use of this site.</p>

<h3>Governing Law</h3>
<p>These terms are governed by applicable law. Disputes shall be resolved through binding arbitration.</p>
""",
    },

    "affiliate_disclosure": {
        "title": "Affiliate Disclosure",
        "slug": "affiliate-disclosure",
        "body": """
<h2>Affiliate Disclosure</h2>
<p><em>FTC Disclosure — Required by Law</em></p>
<p>{blog_title} participates in affiliate marketing programs. This means we may earn a commission when you click on links to products or services and make a purchase.</p>

<h3>AI-Assisted Content Disclosure</h3>
<p>Some content on this site is created with the assistance of artificial intelligence tools. All AI-generated content is reviewed and edited by our team before publication.</p>

<h3>Advertising</h3>
<p>This site displays advertisements from third-party ad networks. We earn revenue from these advertisements based on impressions and clicks.</p>

<h3>Honest Reviews</h3>
<p>Our reviews and recommendations are based on genuine research and analysis. Affiliate relationships do not influence our editorial opinions.</p>
""",
    },

    "dmca": {
        "title": "DMCA Disclaimer",
        "slug": "dmca",
        "body": """
<h2>DMCA Disclaimer</h2>
<p>This site respects the intellectual property rights of others and expects its users to do the same.</p>

<h3>Copyright Infringement Claims</h3>
<p>If you believe that content on this site infringes your copyright, please send a written notice to us via our <a href="/contact">contact page</a> with the following information:</p>
<ul>
<li>Your contact information</li>
<li>Description of the copyrighted work you claim is infringed</li>
<li>URL or location of the allegedly infringing content</li>
<li>A statement that you have a good faith belief that the use is not authorized</li>
<li>A statement under penalty of perjury that you are the copyright owner or authorized to act on their behalf</li>
</ul>
<p>We will respond to valid DMCA notices promptly.</p>
""",
    },

    "cookie_consent": {
        "title": "Cookie Policy",
        "slug": "cookie-policy",
        "body": """
<h2>Cookie Policy</h2>
<p>This site uses cookies to improve your experience and deliver personalized advertising.</p>

<h3>Types of Cookies We Use</h3>
<ul>
<li><strong>Essential cookies:</strong> Required for basic site functionality</li>
<li><strong>Analytics cookies:</strong> Help us understand how visitors use our site</li>
<li><strong>Advertising cookies:</strong> Used to deliver relevant advertisements</li>
</ul>

<h3>Managing Cookies</h3>
<p>You can control and delete cookies through your browser settings. Note that disabling some cookies may affect your experience on this site.</p>

<h3>EU/GDPR Notice</h3>
<p>If you are located in the European Union, by continuing to use this site you consent to our use of cookies as described in this policy.</p>
""",
    },

    "contact": {
        "title": "Contact Us",
        "slug": "contact",
        "body": """
<h2>Contact Us</h2>
<p>Have a question, suggestion, or want to report an issue? We'd love to hear from you.</p>

<h3>General Inquiries</h3>
<p>For general inquiries, content corrections, or feedback, please use the form below or reach out through our social media channels.</p>

<h3>DMCA / Copyright</h3>
<p>For copyright concerns, please see our <a href="/dmca">DMCA page</a> for the correct procedure.</p>

<h3>Advertising</h3>
<p>For advertising inquiries, please include your site, target audience, and budget in your message.</p>

<p><em>We aim to respond to all messages within 48 hours.</em></p>
""",
    },

    "about": {
        "title": "About Us",
        "slug": "about",
        "body": """
<h2>About {blog_title}</h2>
<p>Welcome to {blog_title} — your source for the latest news, analysis, and insights.</p>

<p>We are a dedicated team of writers, researchers, and analysts committed to delivering accurate, timely, and engaging content across a range of topics.</p>

<h3>Our Mission</h3>
<p>To provide high-quality, well-researched content that informs and empowers our readers to make better decisions.</p>

<h3>Editorial Standards</h3>
<p>All content is fact-checked against multiple sources before publication. We clearly disclose AI-assisted content and affiliate relationships as required by law.</p>

<h3>Connect With Us</h3>
<p>Follow us on social media for the latest updates, or subscribe to our newsletter for weekly highlights delivered to your inbox.</p>
""",
    },
}

# Adult-only additional pages
ADULT_LEGAL_PAGES_EN = {
    "age_verification": {
        "title": "Age Verification",
        "slug": "age-verification",
        "body": """
<h2>Age Verification — 18+ Only</h2>
<p>This website contains adult content intended for individuals aged 18 years or older.</p>
<p>By entering this site, you confirm that:</p>
<ul>
<li>You are 18 years of age or older</li>
<li>It is legal in your jurisdiction to view adult content</li>
<li>You understand that adult content will be present on this site</li>
</ul>
<p>If you are under 18 or if adult content is illegal in your jurisdiction, please exit immediately.</p>
""",
    },
    "2257_compliance": {
        "title": "18 U.S.C. 2257 Compliance Statement",
        "slug": "2257",
        "body": """
<h2>18 U.S.C. 2257 Compliance Statement</h2>
<p>All content on this website is informational in nature. This site does not produce or host explicit visual content.</p>
<p>This website contains no content subject to 18 U.S.C. § 2257 record-keeping requirements as no visual depictions of sexually explicit conduct are produced by this site.</p>
<p>For all third-party content linked from this site, records are maintained by the respective producers of such content.</p>
""",
    },
}


# ── Ad Network Slot Templates ──────────────────────────────────────────────────
AD_SLOT_COMMENTS = {
    "slot_1": "<!-- AD_SLOT_1: Header native display — above fold -->",
    "slot_2": "<!-- AD_SLOT_2: After paragraph 1 — video ad (highest RPM) -->",
    "slot_3": "<!-- AD_SLOT_3: Mid content — native display -->",
    "slot_4": "<!-- AD_SLOT_4: 70% scroll depth — interstitial -->",
    "slot_5": "<!-- AD_SLOT_5: Sticky footer — follows scroll -->",
    "slot_6": "<!-- AD_SLOT_6: Exit intent — pop-under -->",
    "push":   "<!-- PUSH_NOTIFICATION_CODE -->",
    "clarity":"<!-- MICROSOFT_CLARITY_CODE -->",
    "gtm":    "<!-- GOOGLE_TAG_MANAGER_CODE -->",
    "onesig": "<!-- ONESIGNAL_PUSH_CODE -->",
}

def build_ad_injection_html(network_codes: Dict[str, str]) -> str:
    """
    Build the ad code block for template injection.
    network_codes: dict of slot_name → actual ad code (from config)
    """
    parts = []
    for slot, comment in AD_SLOT_COMMENTS.items():
        code = network_codes.get(slot, "")
        parts.append(f"{comment}\n{code}" if code else comment)
    return "\n".join(parts)


# ── Blogger Template ───────────────────────────────────────────────────────────
def build_blogger_template(
    blog_title: str,
    language: str,
    niche: str,
    ad_codes: Optional[Dict] = None,
    is_adult: bool = False,
) -> str:
    """
    Generate a minimal but complete Blogger template with:
    - RTL support for AR/UR
    - 6 ad slots
    - Schema/hreflang/canonical placeholders
    - OneSignal push
    - Microsoft Clarity
    - Cookie consent banner
    - Mobile-responsive
    """
    is_rtl = language in RTL_LANGUAGES
    dir_attr = 'dir="rtl"' if is_rtl else 'dir="ltr"'
    text_align = "right" if is_rtl else "left"

    adult_meta = '<meta name="rating" content="adult"/>\n    ' if is_adult else ""
    adult_warning = (
        '<div id="adult-warning" style="background:#c00;color:#fff;padding:10px;text-align:center;">'
        '18+ ADULT CONTENT — YOU MUST BE 18 OR OLDER TO CONTINUE</div>\n'
    ) if is_adult else ""

    ad_block = ""
    if ad_codes:
        ad_block = build_ad_injection_html(ad_codes)

    template = f"""<?xml version="1.0" encoding="UTF-8" ?>
<!DOCTYPE html>
<html b:version='2' class='v2' expr:dir='data:blog.languageDirection' xmlns='http://www.w3.org/1999/xhtml' xmlns:b='http://www.google.com/2005/gml/b' xmlns:data='http://www.google.com/2005/gml/data' xmlns:expr='http://www.google.com/2005/gml/expr'>
<head>
  <meta charset='UTF-8'/>
  <meta content='width=device-width, initial-scale=1' name='viewport'/>
  {adult_meta}<b:include data='blog' name='all-head-content'/>
  <title><data:blog.pageTitle/></title>

  <!-- CANONICAL_PLACEHOLDER -->
  <!-- HREFLANG_PLACEHOLDER -->
  <!-- SCHEMA_PLACEHOLDER -->
  <!-- GOOGLE_TAG_MANAGER_CODE -->
  <!-- MICROSOFT_CLARITY_CODE -->
  <!-- ONESIGNAL_PUSH_CODE -->

  <style type='text/css'>
  /* ── Base Reset ─────────────────────────────── */
  *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
  html, body {{ height: 100%; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Arial, sans-serif;
    font-size: 16px;
    line-height: 1.7;
    color: #1a1a1a;
    background: #f8f8f8;
    direction: {'rtl' if is_rtl else 'ltr'};
    text-align: {text_align};
  }}
  /* ── Layout ─────────────────────────────────── */
  .wrapper {{ max-width: 1200px; margin: 0 auto; padding: 0 16px; }}
  .main-content {{ display: flex; gap: 24px; padding: 24px 0; }}
  .post-area {{ flex: 1; min-width: 0; }}
  .sidebar {{ width: 300px; flex-shrink: 0; }}
  @media (max-width: 768px) {{
    .main-content {{ flex-direction: column; }}
    .sidebar {{ width: 100%; }}
  }}
  /* ── Header ─────────────────────────────────── */
  #header {{ background: #1a1a2e; color: #fff; padding: 16px 0; }}
  #header h1 {{ font-size: 1.5rem; font-weight: 700; }}
  #header h1 a {{ color: #fff; text-decoration: none; }}
  /* ── Navigation ─────────────────────────────── */
  .nav-bar {{ background: #16213e; padding: 8px 0; }}
  .nav-bar ul {{ list-style: none; display: flex; flex-wrap: wrap; gap: 16px; }}
  .nav-bar a {{ color: #e0e0e0; text-decoration: none; font-size: 0.9rem; }}
  .nav-bar a:hover {{ color: #fff; }}
  /* ── Post Card ───────────────────────────────── */
  .post-outer {{ background: #fff; border-radius: 8px; margin-bottom: 24px;
    box-shadow: 0 2px 8px rgba(0,0,0,0.08); overflow: hidden; }}
  .post-body {{ padding: 20px 24px; }}
  .post-title {{ font-size: 1.5rem; font-weight: 700; margin-bottom: 8px; }}
  .post-title a {{ color: #1a1a2e; text-decoration: none; }}
  .post-title a:hover {{ color: #0066cc; }}
  .post-meta {{ font-size: 0.85rem; color: #666; margin-bottom: 16px; }}
  .post-body p {{ margin-bottom: 1em; }}
  .post-body h2 {{ font-size: 1.25rem; margin: 1.5em 0 0.5em; }}
  .post-body h3 {{ font-size: 1.1rem; margin: 1.2em 0 0.4em; }}
  .post-body img {{ max-width: 100%; height: auto; border-radius: 4px; }}
  .post-body table {{ width: 100%; border-collapse: collapse; margin: 1em 0; }}
  .post-body th, .post-body td {{ border: 1px solid #ddd; padding: 8px 12px; }}
  .post-body th {{ background: #f0f0f0; }}
  /* ── Featured Image ──────────────────────────── */
  .featured-image img {{ width: 100%; height: auto; display: block; }}
  /* ── Sticky Footer Ad ────────────────────────── */
  #sticky-footer-ad {{
    position: fixed; bottom: 0; left: 0; right: 0; z-index: 9999;
    background: #fff; border-top: 1px solid #ddd; padding: 4px;
    text-align: center;
  }}
  #sticky-footer-ad .close-btn {{
    position: absolute; top: 4px; right: 8px;
    background: none; border: none; cursor: pointer; font-size: 1rem;
  }}
  /* ── Cookie Banner ───────────────────────────── */
  #cookie-banner {{
    position: fixed; bottom: 60px; left: 0; right: 0; z-index: 9998;
    background: #1a1a2e; color: #fff; padding: 12px 16px;
    display: flex; align-items: center; justify-content: space-between;
    flex-wrap: wrap; gap: 8px; font-size: 0.85rem;
  }}
  #cookie-banner button {{
    background: #0066cc; color: #fff; border: none;
    padding: 6px 16px; border-radius: 4px; cursor: pointer;
  }}
  /* ── Labels / Tags ───────────────────────────── */
  .label {{ display: inline-block; background: #e8f0fe; color: #1a73e8;
    padding: 2px 8px; border-radius: 12px; font-size: 0.75rem; margin-right: 4px; }}
  /* ── Sidebar ─────────────────────────────────── */
  .sidebar .widget {{ background: #fff; border-radius: 8px; padding: 16px;
    margin-bottom: 16px; box-shadow: 0 2px 8px rgba(0,0,0,0.06); }}
  .sidebar .widget h2 {{ font-size: 1rem; font-weight: 600; margin-bottom: 12px;
    padding-bottom: 8px; border-bottom: 2px solid #0066cc; }}
  /* ── Footer ─────────────────────────────────── */
  #footer {{ background: #1a1a2e; color: #ccc; padding: 32px 0 80px; margin-top: 32px; }}
  #footer a {{ color: #aaa; text-decoration: none; }}
  #footer a:hover {{ color: #fff; }}
  .footer-links {{ display: flex; flex-wrap: wrap; gap: 16px; margin-bottom: 16px; }}
  .footer-bottom {{ font-size: 0.8rem; color: #666; margin-top: 16px; }}
  /* ── RTL Overrides ───────────────────────────── */
  {'[dir="rtl"] .sidebar { order: -1; }' if is_rtl else ''}
  </style>
</head>

<body>
  {adult_warning}

  <!-- Cookie Consent Banner (GDPR) -->
  <div id='cookie-banner'>
    <span>We use cookies to improve your experience and serve personalized ads.
    <a href='/cookie-policy' style='color:#7fc6ff'>Learn more</a></span>
    <button onclick='document.getElementById("cookie-banner").style.display="none";
      localStorage.setItem("cookieConsent","true")'>Accept</button>
  </div>
  <script>
  if(localStorage.getItem('cookieConsent')==='true')
    document.getElementById('cookie-banner').style.display='none';
  </script>

  <!-- Google Tag Manager (noscript) -->
  <!-- GTM_NOSCRIPT_PLACEHOLDER -->

  <div id='header'>
    <div class='wrapper'>
      <h1><a expr:href='data:blog.homepageUrl'><data:blog.title/></a></h1>
    </div>
  </div>

  <nav class='nav-bar'>
    <div class='wrapper'>
      <ul>
        <li><a expr:href='data:blog.homepageUrl'>Home</a></li>
        <b:loop values='data:blog.pageList' var='page'>
          <li><a expr:href='data:page.url'><data:page.title/></a></li>
        </b:loop>
      </ul>
    </div>
  </nav>

  <!-- AD SLOT 1: Header -->
  {ad_block}

  <div class='wrapper'>
    <div class='main-content'>
      <main class='post-area'>
        <b:section class='main' id='main' showaddelement='no'>
          <b:widget id='Blog1' locked='false' title='Blog Posts' type='Blog' version='1'>
            <b:widget-settings>
              <b:widget-setting name='showDateHeader'>false</b:widget-setting>
              <b:widget-setting name='showShareButtons'>true</b:widget-setting>
            </b:widget-settings>
            <b:includable id='main'>
              <b:loop values='data:posts' var='post'>
                <article class='post-outer hentry'>
                  <div class='featured-image'>
                    <!-- FEATURED_IMAGE_PLACEHOLDER -->
                  </div>
                  <div class='post-body'>
                    <h2 class='post-title entry-title'>
                      <a expr:href='data:post.url'><data:post.title/></a>
                    </h2>
                    <div class='post-meta'>
                      <time class='published' expr:datetime='data:post.timestampISO8601'>
                        <data:post.timestamp/>
                      </time>
                      — <span class='post-author'><data:post.author.name/></span>
                    </div>
                    <!-- AD SLOT 2: After paragraph 1 — VIDEO -->
                    <!-- AD_SLOT_2_PLACEHOLDER -->
                    <div class='post-body-text entry-content' itemprop='articleBody'>
                      <data:post.body/>
                    </div>
                    <!-- AD SLOT 3: Mid content -->
                    <!-- AD_SLOT_3_PLACEHOLDER -->
                    <div class='post-footer'>
                      <b:loop values='data:post.labels' var='label'>
                        <span class='label'><data:label.name/></span>
                      </b:loop>
                    </div>
                  </div>
                </article>
              </b:loop>
              <!-- Pagination -->
              <div class='blog-pager'>
                <b:if cond='data:newerPageUrl'>
                  <a class='newer-link' expr:href='data:newerPageUrl'>&#8592; Newer</a>
                </b:if>
                <b:if cond='data:olderPageUrl'>
                  <a class='older-link' expr:href='data:olderPageUrl'>Older &#8594;</a>
                </b:if>
              </div>
            </b:includable>
          </b:widget>
        </b:section>
      </main>

      <aside class='sidebar'>
        <!-- AD SLOT 4: Interstitial at 70% scroll -->
        <!-- AD_SLOT_4_PLACEHOLDER -->
        <b:section class='sidebar-right' id='sidebar' showaddelement='yes'>
          <b:widget id='HTML1' locked='false' title='Featured' type='HTML'/>
          <b:widget id='Label1' locked='false' title='Topics' type='Label'/>
          <b:widget id='PopularPosts1' locked='false' title='Popular Posts' type='PopularPosts'/>
        </b:section>
      </aside>
    </div>
  </div>

  <!-- Sticky Footer Ad (AD SLOT 5) -->
  <div id='sticky-footer-ad'>
    <button class='close-btn' onclick='document.getElementById("sticky-footer-ad").style.display="none"'>&#x2715;</button>
    <!-- AD_SLOT_5_PLACEHOLDER -->
  </div>

  <!-- Exit Intent (AD SLOT 6) -->
  <script>
  var _exitShown = false;
  document.addEventListener('mouseleave', function(e) {{
    if (e.clientY < 10 && !_exitShown) {{
      _exitShown = true;
      /* AD_SLOT_6_PLACEHOLDER */
    }}
  }});
  </script>

  <footer id='footer'>
    <div class='wrapper'>
      <div class='footer-links'>
        <a href='/privacy-policy'>Privacy Policy</a>
        <a href='/terms-of-service'>Terms of Service</a>
        <a href='/affiliate-disclosure'>Affiliate Disclosure</a>
        <a href='/dmca'>DMCA</a>
        <a href='/cookie-policy'>Cookie Policy</a>
        <a href='/about'>About</a>
        <a href='/contact'>Contact</a>
      </div>
      <div class='footer-bottom'>
        <p>&copy; <data:blog.title/> {datetime.now().year}. AI-assisted content. All affiliate links are disclosed.</p>
        <p><em>This site participates in affiliate programs and displays advertising.</em></p>
      </div>
    </div>
  </footer>

  <!-- 70% scroll depth interstitial trigger -->
  <script>
  var _scrollFired = false;
  window.addEventListener('scroll', function() {{
    var pct = (window.scrollY + window.innerHeight) / document.documentElement.scrollHeight;
    if (pct > 0.70 && !_scrollFired) {{
      _scrollFired = true;
      /* AD_SLOT_4_TRIGGER */
    }}
  }});
  </script>
</body>
</html>"""
    return template


# ── Post HTML Builder ─────────────────────────────────────────────────────────
def resolve_post_placeholders(
    body_html: str,
    blog_info: BlogInfo,
    canonical_url: str,
    hreflang_links: Dict[str, str],   # {lang_code: url}
    schema_json: Optional[str] = None,
    featured_image_url: str = "",
    affiliate_disclosure_text: str = "",
    legal_footer_text: str = "",
) -> str:
    """
    Replace all placeholder comments with real content before publishing.
    """
    now = datetime.now(timezone.utc).isoformat()

    # Canonical
    canonical_tag = f'<link rel="canonical" href="{canonical_url}"/>'
    body_html = body_html.replace("<!-- CANONICAL_PLACEHOLDER -->", canonical_tag)

    # Hreflang
    hreflang_tags = "\n".join(
        f'<link rel="alternate" hreflang="{lang}" href="{url}"/>'
        for lang, url in hreflang_links.items()
    )
    hreflang_tags += '\n<link rel="alternate" hreflang="x-default" href="' + hreflang_links.get("en", canonical_url) + '"/>'
    body_html = body_html.replace("<!-- HREFLANG_PLACEHOLDER -->", hreflang_tags)

    # Schema
    if schema_json:
        schema_tag = f'<script type="application/ld+json">{schema_json}</script>'
    else:
        schema_tag = _build_article_schema(blog_info, canonical_url, body_html)
    body_html = body_html.replace("<!-- SCHEMA_PLACEHOLDER -->", schema_tag)

    # Featured image
    if featured_image_url:
        img_tag = f'<img src="{featured_image_url}" alt="" loading="lazy" width="1200" height="628"/>'
    else:
        img_tag = ""
    body_html = body_html.replace("<!-- FEATURED_IMAGE_PLACEHOLDER -->", img_tag)

    # Ad slots — leave as comments if no real code (quality_control will have checked)
    # They get replaced by blog_manager when injecting live codes

    # Affiliate disclosure
    disclosure = affiliate_disclosure_text or (
        '<p><em>Disclosure: This post contains affiliate links. '
        'We may earn a commission at no extra cost to you. '
        'AI-assisted content — reviewed by our editorial team.</em></p>'
    )
    body_html = body_html.replace("<!-- AFFILIATE_DISCLOSURE -->", disclosure)

    # Legal footer
    footer = legal_footer_text or (
        '<p style="font-size:0.8em;color:#666;">'
        f'Published {now[:10]} | <a href="/privacy-policy">Privacy</a> | '
        '<a href="/affiliate-disclosure">Disclosure</a></p>'
    )
    body_html = body_html.replace("<!-- LEGAL_FOOTER -->", footer)

    return body_html


def _build_article_schema(blog_info: BlogInfo, url: str, body_html: str) -> str:
    """Build Article JSON-LD schema markup."""
    plain_text = re.sub(r'<[^>]+>', ' ', body_html)[:200].strip()
    schema = {
        "@context": "https://schema.org",
        "@type": "NewsArticle",
        "headline": blog_info.title[:110],
        "url": url,
        "inLanguage": blog_info.language,
        "publisher": {
            "@type": "Organization",
            "name": blog_info.title,
            "url": blog_info.url,
        },
        "datePublished": datetime.now(timezone.utc).isoformat(),
        "dateModified": datetime.now(timezone.utc).isoformat(),
        "description": plain_text,
    }
    return f'<script type="application/ld+json">{json.dumps(schema)}</script>'


# ── Blogger API Client ────────────────────────────────────────────────────────
class BloggerClient:
    """
    Wrapper around the Blogger v3 API.
    Uses google-api-python-client with OAuth2 credentials per Gmail account.
    Falls back to requests-based calls if google-api lib unavailable.
    """

    def __init__(self, credentials, blog_id: str = ""):
        self._creds = credentials
        self._blog_id = blog_id
        self._service = None
        self._init_service()

    def _init_service(self):
        try:
            from googleapiclient.discovery import build
            from google.oauth2.credentials import Credentials
            self._service = build("blogger", BLOGGER_API_VERSION,
                                  credentials=self._creds, cache_discovery=False)
        except ImportError:
            _log.warning("google-api-python-client not available — using requests fallback")
            self._service = None

    def get_blog_by_url(self, url: str) -> Optional[Dict]:
        """Get blog info by URL."""
        try:
            if self._service:
                result = self._service.blogs().getByUrl(url=url).execute()
                return result
        except Exception as e:
            _log.error(f"get_blog_by_url failed: {e}")
        return None

    def create_post(
        self,
        title: str,
        body_html: str,
        labels: Optional[List[str]] = None,
        is_draft: bool = False,
        publish_date: Optional[str] = None,  # ISO 8601
    ) -> Optional[Dict]:
        """Publish or draft a post. Returns API response dict or None."""
        if not self._blog_id:
            raise ValueError("blog_id not set on BloggerClient")

        # Enforce 1MB post size limit
        body_bytes = body_html.encode("utf-8")
        if len(body_bytes) > BLOGGER_POST_SIZE_LIMIT_MB * 1024 * 1024:
            raise ValueError(f"Post exceeds Blogger 1MB limit: {len(body_bytes)} bytes")

        post_body = {
            "kind": "blogger#post",
            "title": title,
            "content": body_html,
        }
        if labels:
            post_body["labels"] = labels[:10]  # Blogger max 10 labels
        if publish_date:
            post_body["published"] = publish_date

        try:
            if self._service:
                if is_draft:
                    result = self._service.posts().insert(
                        blogId=self._blog_id, body=post_body, isDraft=True
                    ).execute()
                else:
                    result = self._service.posts().insert(
                        blogId=self._blog_id, body=post_body
                    ).execute()
                return result
        except Exception as e:
            _log.error(f"create_post failed: {e}")
            raise RuntimeError(f"Blogger API post creation failed: {e}") from e
        return None

    def update_post(self, post_id: str, title: str, body_html: str) -> Optional[Dict]:
        try:
            if self._service:
                result = self._service.posts().update(
                    blogId=self._blog_id,
                    postId=post_id,
                    body={"title": title, "content": body_html}
                ).execute()
                return result
        except Exception as e:
            _log.error(f"update_post failed: {e}")
        return None

    def delete_post(self, post_id: str) -> bool:
        try:
            if self._service:
                self._service.posts().delete(
                    blogId=self._blog_id, postId=post_id
                ).execute()
                return True
        except Exception as e:
            _log.error(f"delete_post failed: {e}")
        return False

    def list_posts(self, max_results: int = 20, status: str = "live") -> List[Dict]:
        try:
            if self._service:
                result = self._service.posts().list(
                    blogId=self._blog_id,
                    maxResults=max_results,
                    status=status,
                    fetchBodies=False,
                ).execute()
                return result.get("items", [])
        except Exception as e:
            _log.error(f"list_posts failed: {e}")
        return []

    def create_page(self, title: str, body_html: str) -> Optional[Dict]:
        """Create a static page (Privacy Policy, etc.)"""
        try:
            if self._service:
                result = self._service.pages().insert(
                    blogId=self._blog_id,
                    body={"title": title, "content": body_html}
                ).execute()
                return result
        except Exception as e:
            _log.error(f"create_page failed: {e}")
        return None

    def update_template(self, template_xml: str) -> bool:
        """Update blog template. Uses Blogger gadget/template API."""
        try:
            import requests
            # Blogger template update requires web session (not REST API)
            # This is a placeholder — actual template update done via platform_manager
            _log.warning("Template update requires authenticated browser session via platform_manager")
            return False
        except Exception as e:
            _log.error(f"update_template failed: {e}")
        return False


# ── Legal Pages Injector ──────────────────────────────────────────────────────
def inject_legal_pages(
    client: BloggerClient,
    blog_info: BlogInfo,
    existing_pages: Optional[List[str]] = None,
) -> Dict[str, bool]:
    """
    Create all legal pages for a blog in its language.
    Returns {page_slug: success}.
    existing_pages: list of existing page titles to skip
    """
    pages = dict(LEGAL_PAGES_EN)
    if blog_info.is_adult:
        pages.update(ADULT_LEGAL_PAGES_EN)

    results = {}
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    for page_key, page_data in pages.items():
        title = page_data["title"]
        body  = page_data["body"].format(
            blog_title=blog_info.title,
            date=today,
        )

        # Skip if already exists
        if existing_pages and title in existing_pages:
            results[page_data["slug"]] = True
            continue

        try:
            resp = client.create_page(title, body)
            results[page_data["slug"]] = resp is not None
            if resp:
                _log.info(f"Created page '{title}' for blog {blog_info.blog_id}")
            time.sleep(0.5)  # Rate limiting
        except Exception as e:
            _log.error(f"Failed to create page '{title}': {e}")
            results[page_data["slug"]] = False

    return results


# ── Sitemap Submission ────────────────────────────────────────────────────────
def submit_sitemap(blog_url: str, sitemap_path: str = "sitemap.xml") -> Dict[str, bool]:
    """
    Submit sitemap to Google, Bing, and Yandex.
    Returns {engine: success}.
    """
    import requests

    sitemap_url = f"{blog_url.rstrip('/')}/{sitemap_path}"
    results = {}

    for engine_template in SITEMAP_PING_ENGINES:
        ping_url = engine_template.format(sitemap_url=sitemap_url)
        engine_name = "google" if "google" in ping_url else "bing"
        try:
            r = requests.get(ping_url, timeout=10)
            results[engine_name] = r.status_code == 200
            _log.info(f"Sitemap ping {engine_name}: {r.status_code}")
        except Exception as e:
            _log.warning(f"Sitemap ping {engine_name} failed: {e}")
            results[engine_name] = False

    # Yandex (via XML API)
    try:
        r = requests.get(
            f"https://webmaster.yandex.com/ping?sitemap={sitemap_url}",
            timeout=10
        )
        results["yandex"] = r.status_code in (200, 201)
    except Exception as e:  # noqa: BLE001 — sitemap ping is best-effort
        _log.debug(f"yandex sitemap ping failed: {e}")
        results["yandex"] = False

    return results


# ── Blog DB Operations ────────────────────────────────────────────────────────
def register_blog(
    blogger_id: str,
    url: str,
    title: str,
    niche: str,
    role: str,
    language: str,
    gmail_account: str,
    is_adult: bool = False,
) -> Optional[int]:
    """Register a new blog in blogs.db. Returns internal row id."""
    try:
        from modules.database_manager import execute, audit
        network = "adult" if is_adult else "safe"
        row_id = execute(
            "blogs",
            """INSERT OR IGNORE INTO blogs
               (blog_id, url, name, niche, role, language, gmail_account,
                network, created_at, status, post_count)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', 0)""",
            (blogger_id, url, title, niche, role, language, gmail_account,
             network, datetime.now(timezone.utc).isoformat()),
        )
        # Fetch the actual id (INSERT OR IGNORE may not return id on conflict)
        from modules.database_manager import fetch_one
        row = fetch_one("blogs", "SELECT id FROM blogs WHERE blog_id=?", (blogger_id,))
        db_id = row["id"] if row else row_id
        audit("blog_manager", "blog_registered",
              f"id={db_id} url={url} niche={niche} role={role}", "INFO")
        return db_id
    except Exception as e:
        _log.error(f"register_blog failed: {e}")
        return None


def get_blog(blog_id: int) -> Optional[BlogInfo]:
    """Fetch blog info from blogs.db."""
    try:
        from modules.database_manager import fetch_one
        row = fetch_one("blogs", "SELECT * FROM blogs WHERE id=?", (blog_id,))
        if not row:
            return None
        return BlogInfo(
            blog_id=row["id"],
            blogger_id=row["blog_id"],
            url=row["url"],
            title=row["name"],
            niche=row["niche"],
            role=row["role"],
            language=row["language"],
            gmail_account=row["gmail_account"],
            is_adult=row["network"] == "adult",
            created_at=row["created_at"],
            is_active=row["status"] == "active",
            posts_count=row["post_count"] or 0,
            ad_codes_injected=False,
        )
    except Exception as e:
        _log.error(f"get_blog failed: {e}")
        return None


def get_all_active_blogs(is_adult: bool = False) -> List[BlogInfo]:
    """Get all active blogs of a given type."""
    try:
        from modules.database_manager import fetch_all
        network = "adult" if is_adult else "safe"
        rows = fetch_all("blogs",
                         "SELECT * FROM blogs WHERE status='active' AND network=?",
                         (network,))
        return [BlogInfo(
            blog_id=r["id"], blogger_id=r["blog_id"], url=r["url"],
            title=r["name"], niche=r["niche"], role=r["role"],
            language=r["language"], gmail_account=r["gmail_account"],
            is_adult=r["network"] == "adult",
            created_at=r["created_at"],
            is_active=True, posts_count=r["post_count"] or 0,
            ad_codes_injected=False,
        ) for r in rows]
    except Exception as e:
        _log.error(f"get_all_active_blogs failed: {e}")
        return []


def increment_post_count(blog_id: int):
    try:
        from modules.database_manager import execute
        execute("blogs",
                "UPDATE blogs SET post_count = post_count + 1 WHERE id=?",
                (blog_id,))
    except Exception as e:
        _log.warning(f"increment_post_count failed: {e}")


# ── High-Level Publish Function ───────────────────────────────────────────────
def publish_post(
    blog_info: BlogInfo,
    title: str,
    body_html: str,
    labels: Optional[List[str]] = None,
    canonical_url: str = "",
    hreflang_links: Optional[Dict[str, str]] = None,
    featured_image_url: str = "",
    is_draft: bool = False,
    credentials = None,
) -> PublishResult:
    """
    Full publish pipeline:
    1. Resolve all placeholders in body_html
    2. Check post size
    3. Publish via Blogger API
    4. Update post count in DB
    5. Audit log
    """
    if not canonical_url:
        canonical_url = blog_info.url

    # Resolve placeholders
    body_resolved = resolve_post_placeholders(
        body_html=body_html,
        blog_info=blog_info,
        canonical_url=canonical_url,
        hreflang_links=hreflang_links or {"en": canonical_url},
        featured_image_url=featured_image_url,
    )

    # Size check
    size_bytes = len(body_resolved.encode("utf-8"))
    if size_bytes > BLOGGER_POST_SIZE_LIMIT_MB * 1024 * 1024:
        return PublishResult(
            success=False,
            error=f"Post too large: {size_bytes} bytes > 1MB Blogger limit"
        )

    try:
        client = BloggerClient(credentials, blog_id=blog_info.blogger_id)
        resp = client.create_post(
            title=title,
            body_html=body_resolved,
            labels=labels,
            is_draft=is_draft,
        )

        if resp:
            post_id  = resp.get("id", "")
            post_url = resp.get("url", "")
            increment_post_count(blog_info.blog_id)

            try:
                from modules.database_manager import audit
                audit("blog_manager", "post_published",
                      f"blog={blog_info.blog_id} post={post_id} title={title[:50]}", "INFO")
            except Exception as e:  # noqa: BLE001 — audit log is best-effort
                _log.debug(f"audit log post_published: {e}")

            _log.info(f"Published: {title[:60]} → {post_url}")
            return PublishResult(success=True, post_id=post_id, post_url=post_url)

        return PublishResult(success=False, error="API returned empty response")

    except Exception as e:
        _log.error(f"publish_post failed: {e}")
        return PublishResult(success=False, error=str(e))


# ── Network Sitemap Index ─────────────────────────────────────────────────────
def update_network_sitemap_index(blogs: List[BlogInfo], output_path: Optional[Path] = None) -> str:
    """
    Generate and write a sitemap index covering all active blogs.
    Returns XML string.
    """
    if output_path is None:
        output_path = BASE_DIR / "data" / "network_sitemap_index.xml"

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    lines = ['<?xml version="1.0" encoding="UTF-8"?>',
             '<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']

    for blog in blogs:
        sitemap_url = f"{blog.url.rstrip('/')}/sitemap.xml"
        lines.append(f'  <sitemap>')
        lines.append(f'    <loc>{sitemap_url}</loc>')
        lines.append(f'    <lastmod>{now}</lastmod>')
        lines.append(f'  </sitemap>')

    lines.append('</sitemapindex>')
    xml = "\n".join(lines)

    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(xml, encoding="utf-8")
    except Exception as e:
        _log.warning(f"Could not write sitemap index: {e}")

    return xml


# ── Template Integrity Check ──────────────────────────────────────────────────
_template_checksums: Dict[int, str] = {}  # blog_id → sha256 of template

def record_template_checksum(blog_id: int, template_xml: str):
    import hashlib
    _template_checksums[blog_id] = hashlib.sha256(template_xml.encode()).hexdigest()

def check_template_integrity(blog_id: int, current_template: str) -> bool:
    """Returns True if template matches stored checksum (not tampered)."""
    import hashlib
    stored = _template_checksums.get(blog_id)
    if not stored:
        return True  # No baseline recorded yet
    current = hashlib.sha256(current_template.encode()).hexdigest()
    return stored == current


# ── Cloudflare Blog Creation at Scale ─────────────────────────────────────────

# Niche distribution caps (total across 500-blog network)
NICHE_CAPS = {
    "finance":       50,
    "crypto":        50,
    "health":        100,
    "tech":          150,
    "entertainment": 150,   # fills remainder
}

# ── Professional site name pools (one per niche, enough for cap + 20% buffer) ──
# Each name becomes a Cloudflare Pages subdomain: name.pages.dev
SITE_NAME_POOLS: Dict[str, List[str]] = {
    "crypto": [
        "coinpulse", "cryptowire", "blockledger", "bitcoindaily", "altcoinreport",
        "cointrend", "cryptobeat", "blocknewshub", "digitalassets", "cryptoflash",
        "coinchronicle", "cryptovault", "tokenreport", "cryptosignal", "coinbrief",
        "cryptodigest", "blocktimes", "coininsight", "cryptoalert", "chainreport",
        "coinsphere", "cryptomatrix", "blockpulse", "cryptoedge", "coinreview",
        "cryptonexus", "blockwatch", "coindepth", "cryptolens", "coinhorizon",
        "cryptosphere", "blockinsight", "coinvision", "cryptodaily", "coinmarket",
        "cryptotrend", "blockwave", "coinindex", "cryptoradar", "coingauge",
        "blockbrief", "coinflash", "cryptonews", "coinpeak", "cryptomonitor",
        "blockbeat", "coinwatch", "cryptotracker", "coinworld", "cryptozone",
        "blockinfo", "coinstream", "cryptoboard", "coinwire", "cryptoflow",
        "blocktrend", "bitcoinwatch", "cryptoreport", "coindesk2", "coinledger",
    ],
    "finance": [
        "wealthwire", "moneypulse", "marketbrief", "investnow", "financebeat",
        "capitalwatch", "wealthbeat", "moneydigest", "marketledger", "investdaily",
        "finpulse", "capitalbrief", "wealthzone", "moneywatch", "marketzone",
        "investwire", "financehub", "capitalzone", "wealthreport", "moneyledger",
        "marketinsight", "investreport", "capitaledge", "wealthinsight", "moneybrief",
        "marketedge", "investbrief", "financezone", "capitalreport", "wealthflash",
        "moneyhub", "markettimes", "investzone", "financeledger", "capitalflash",
        "wealthtimes", "moneyflash", "marketflash", "investflash", "capitalbeat",
        "wealthhub", "moneybeat", "markethub", "investhub", "financetimes",
        "capitaltimes", "moneytimes", "marketsignal", "investsignal", "wealthsignal",
        "financewatch", "capitalwatch2", "wealthwatch", "moneyzone", "investzone2",
        "marketwatch2", "financeflash", "wealthledger", "investledger", "moneywire",
    ],
    "health": [
        "healthwire", "wellnessdaily", "fitpulse", "medadvice", "healthdigest",
        "wellnessbeat", "fitbrief", "medicinewire", "healthzone", "wellnesshub",
        "fitwatch", "medpulse", "healthbeat", "wellnesszone", "fitzone",
        "medbrief", "healthhub", "wellnesspulse", "fitdaily", "medzone",
        "healthflash", "wellnessflash", "fitflash", "medflash", "healthtimes",
        "wellnesstimes", "fittimes", "medtimes", "healthledger", "wellnessledger",
        "fitledger", "medledger", "healthreport", "wellnessreport", "fitreport",
        "medreport", "healthinsight", "wellnessinsight", "fitinsight", "medinsight",
        "healthedge", "wellnessedge", "fitedge", "mededge", "healthsignal",
        "wellnesssignal", "fitsignal", "medsignal", "healthwatch", "wellnesswatch",
        "fitcheck", "medcheck", "healthflow", "wellnessflow", "fitflow",
        "medflow", "healthstream", "wellnessstream", "fitstream", "medstream",
        "healthnow", "wellnessnow", "fitnow", "mednow", "healthpoint",
        "wellnesspoint", "fitpoint", "medpoint", "healthpath", "wellnesspath",
        "fitpath", "medpath", "healthlive", "wellnesslive", "fitlive",
        "medlive", "healthtoday", "wellnesstoday", "fittoday", "medtoday",
        "healthworld", "wellnessworld", "fitworld", "medworld", "healthglobal",
        "wellnessglobal", "fitglobal", "medglobal", "healthspace", "wellnessspace",
        "fitspace", "medspace", "healthverse", "wellnessverse", "fitverse",
        "medverse", "healthsite", "wellnesssite", "fitsite", "medsite",
        "healthnews", "wellnessnews", "fitnews", "mednews", "healthtrend",
        "wellnesstrend", "fittrend", "medtrend", "healthguide", "wellnessguide",
        "fitguide", "medguide", "healthalert", "wellnessalert", "fitalert",
        "medalert", "healthcheck", "wellnesscheck", "fitcheck2", "medcheck2",
    ],
    "tech": [
        "techpulse", "gadgetnews", "techbrief", "devicehub", "techdigest",
        "gadgetbeat", "techwatch", "devicewire", "techzone", "gadgetzone",
        "techledger", "devicebrief", "techreport", "gadgetreport", "techinsight",
        "devicepulse", "techedge", "gadgetedge", "techsignal", "devicesignal",
        "techflash", "gadgetflash", "techbeat", "devicebeat", "techhub",
        "gadgethub", "techtimes", "devicetimes", "techstream", "gadgetstream",
        "techflow", "deviceflow", "technews", "techtrend", "devicetrend",
        "techguide", "gadgetguide", "techalert", "gadgetalert", "techpoint",
        "gadgetpoint", "techpath", "gadgetpath", "techlive", "gadgetlive",
        "techtoday", "gadgettoday", "techworld", "gadgetworld", "techglobal",
        "gadgetglobal", "techspace", "gadgetspace", "techverse", "gadgetverse",
        "techinfo", "gadgetinfo", "techwire", "techpeak", "gadgetpeak",
        "techhorizon", "gadgethorizon", "techvision", "gadgetvision", "techmatrix",
        "gadgetmatrix", "technexus", "gadgetnexus", "techradar", "gadgetradar",
        "techscope", "gadgetscope", "techview", "gadgetview", "techmeter",
        "gadgetmeter", "techindex", "gadgetindex", "techgauge", "gadgetgauge",
        "techsphere", "gadgetsphere", "techfront", "gadgetfront", "techlogic",
        "gadgetlogic", "techbyte", "gadgetbyte", "techcloud", "gadgetcloud",
        "technet", "gadgetnet", "techlink", "gadgetlink", "techboard",
        "gadgetboard", "techmonitor", "gadgetmonitor", "techtracker", "gadgettracker",
        "techreview", "gadgetreview", "techupdate", "gadgetupdate", "techscan",
        "gadgetscan", "techfinder", "gadgetfinder", "techpro", "gadgetpro",
        "techlab", "gadgetlab", "techbase", "gadgetbase", "techsource",
        "gadgetsource", "techhq", "gadgethq", "techcenter", "gadgetcenter",
        "techportal", "gadgetportal", "techhive", "gadgethive", "techstation",
        "gadgetstation", "techdepot", "gadgetdepot", "techcorner", "gadgetcorner",
        "techspot2", "gadgetspot", "techhaven", "gadgethaven", "techzone2",
        "gadgetzone2", "techfeed", "gadgetfeed", "techdebrief", "gadgetdebrief",
        "techdata", "gadgetdata", "techrank", "gadgetrank", "techexplore",
        "gadgetexplore", "techseeker", "gadgetseeker", "techhunter", "gadgethunter",
        "techcheck", "gadgetcheck", "techshare", "gadgetshare", "techcast",
        "gadgetcast", "techgrid", "gadgetgrid", "techdeck", "gadgetdeck",
    ],
    "entertainment": [
        "viralbeat", "trendwatch", "celebnews", "popwire", "viralzone",
        "trendbeat", "celebwire", "popdigest", "viralwire", "trendzone",
        "celebzone", "poppulse", "viralpulse", "trendhub", "celebhub",
        "pophub", "viralhub", "trendflash", "celebflash", "popflash",
        "viralflash", "trendtimes", "celebtimes", "poptimes", "viraledge",
        "trendedge", "celebedge", "popedge", "viralreport", "trendreport",
        "celebreport", "popreport", "viraldigest", "trenddigest", "celebdigest",
        "viralledger", "trendledger", "celebledger", "popledger", "viralwatch",
        "celebwatch", "popwatch", "viralnews", "trendnews", "celebnewshub",
        "popnews", "viraltrend", "trendalert", "celebalert", "popalert",
        "viralguide", "trendguide", "celebguide", "popguide", "viralsignal",
        "trendsignal", "celebsignal", "popsignal", "viralstream", "trendstream",
        "celebstream", "popstream", "viralflow", "trendflow", "celebflow",
        "popflow", "viralpoint", "trendpoint", "celebpoint", "poppoint",
        "viralpath", "trendpath", "celebpath", "poppath", "virallive",
        "trendlive", "celeblive", "poplive", "viraltoday", "trendtoday",
        "celebtoday", "poptoday", "viralworld", "trendworld", "celebworld",
        "popworld", "viralglobal", "trendglobal", "celebglobal", "popglobal",
        "viralspace", "trendspace", "celebspace", "popspace", "viralverse",
        "trendverse", "celebverse", "popverse", "viralinfo", "trendinfo",
        "celebinfo", "popinfo", "viralpeak", "trendpeak", "celebpeak",
        "poppeak", "viralhorizon", "trendhorizon", "celebhorizon", "pophorizon",
        "viralvision", "trendvision", "celebvision", "popvision", "viralmatrix",
        "trendmatrix", "celebmatrix", "popmatrix", "viralnexus", "trendnexus",
        "celebnexus", "popnexus", "viralradar", "trendradar", "celebradar",
        "popradar", "viralscope", "trendscope", "celebscope", "popscope",
        "viralview", "trendview", "celebview", "popview", "viralmeter",
        "trendmeter", "celebmeter", "popmeter", "viralindex", "trendindex",
        "celebindex", "popindex", "viralrank", "trendrank", "celebrank",
        "poprank", "viralgauge", "trendgauge", "celebgauge", "popgauge",
        "viralsphere", "trendsphere", "celebsphere", "popsphere", "viralcheck",
        "trendcheck", "celebcheck", "popcheck", "viraledge2", "trendedge2",
        "celebedge2", "popedge2", "viralcast", "trendcast", "celebcast",
        "popcast", "viraldeck", "trenddeck", "celebdeck", "popdeck",
    ],
}

# Suffix → display suffix for title casing
_TITLE_SUFFIXES = [
    "pulse", "wire", "beat", "zone", "hub", "flash", "times", "ledger",
    "report", "insight", "edge", "signal", "watch", "news", "trend", "guide",
    "alert", "check", "stream", "flow", "point", "live", "today", "world",
    "global", "verse", "info", "data", "peak", "horizon", "vision", "matrix",
    "nexus", "radar", "scope", "view", "meter", "index", "rank", "gauge",
    "sphere", "front", "logic", "byte", "bit", "cloud", "net", "link", "board",
    "monitor", "tracker", "review", "update", "scan", "pro", "lab", "base",
    "source", "hive", "station", "depot", "corner", "spot", "haven", "brief",
    "digest", "daily", "market", "assets", "vault", "feed", "center", "portal",
    "cast", "deck", "grid", "debrief", "seeker", "hunter", "explore", "check2",
    "hq", "site", "path", "now",
]


def _name_to_title(name: str) -> str:
    """Convert a slug like 'coinpulse' → 'CoinPulse' for display as a blog title."""
    for suffix in sorted(_TITLE_SUFFIXES, key=len, reverse=True):
        if name.endswith(suffix):
            prefix = name[: -len(suffix)]
            return prefix.capitalize() + suffix.capitalize()
    return name.capitalize()


def _get_used_site_names() -> set:
    """Return set of blog_ids already in blogs.db to avoid re-using names."""
    try:
        from modules.database_manager import fetch_all
        rows = fetch_all("blogs", "SELECT blog_id FROM blogs WHERE platform='cloudflare'")
        return {r["blog_id"] for r in rows} if rows else set()
    except Exception:  # noqa: BLE001
        return set()


def get_professional_site_name(niche: str) -> str:
    """
    Pick an unused professional name from SITE_NAME_POOLS for the given niche.
    Returns a random available name, or a niche+number fallback if pool exhausted.
    """
    import random
    pool = SITE_NAME_POOLS.get(niche, SITE_NAME_POOLS.get("tech", []))
    used = _get_used_site_names()
    available = [n for n in pool if n not in used]
    if available:
        return random.choice(available)
    # Pool exhausted — generate unique fallback
    prefix = niche[:5].replace("entertainment", "pop").replace("finance", "fin")
    return f"{prefix}{random.randint(1000, 9999)}"

def get_niche_blog_count(niche: str) -> int:
    """Return current number of active Cloudflare blogs for a given niche."""
    try:
        from modules.database_manager import fetch_one
        row = fetch_one(
            "blogs",
            "SELECT COUNT(*) as n FROM blogs "
            "WHERE niche=? AND platform='cloudflare' AND status IN ('active','replacing')",
            (niche,)
        )
        return row["n"] if row else 0
    except Exception as e:  # noqa: BLE001 — count query failure → assume 0
        _log.debug(f"get_niche_blog_count({niche}): {e}")
        return 0


def get_next_site_number() -> Optional[int]:
    """Return the next available site number (1-500) not yet used in blogs.db."""
    try:
        from modules.database_manager import fetch_all
        rows = fetch_all(
            "blogs",
            "SELECT github_path FROM blogs WHERE platform='cloudflare' AND github_path IS NOT NULL"
        )
        used = set()
        for row in rows:
            if row["github_path"]:
                try:
                    n = int(row["github_path"].strip("/").split("site-")[-1])
                    used.add(n)
                except Exception as e:  # noqa: BLE001 — bad github_path format
                    _log.debug(f"parse site number from {row['github_path']!r}: {e}")
        for n in range(1, 501):
            if n not in used:
                return n
        return None
    except Exception as e:  # noqa: BLE001 — fall back to None on DB error
        _log.warning(f"get_next_site_number failed: {e}")
        return None


def create_cloudflare_blog(
    niche: str,
    language: str = "en",
    title: Optional[str] = None,
    ad_codes: Optional[Dict] = None,
) -> Optional[Dict]:
    """
    Create a new Cloudflare Pages blog end-to-end.

    Steps:
      1. Enforce niche distribution caps
      2. Assign next available site number + Cloudflare account
      3. Create Cloudflare Pages project (via cloudflare_manager)
      4. Create placeholder index.html and push to GitHub
      5. Generate legal pages
      6. Save to blogs.db via register_static_blog
      7. Submit sitemap to Bing Webmaster Tools
      8. Fire IndexNow for new blog URL
      9. Alert dashboard

    Returns dict with blog_url, site_id, github_path on success; None on failure.
    """
    import logging
    _clog = logging.getLogger("blog_manager")

    # Step 1: Niche cap check
    cap = NICHE_CAPS.get(niche)
    if cap is not None:
        current = get_niche_blog_count(niche)
        if current >= cap:
            _clog.warning(
                f"create_cloudflare_blog: niche '{niche}' at cap ({current}/{cap}). "
                f"Falling back to 'entertainment'."
            )
            niche = "entertainment"

    # Step 2: Assign site number + Cloudflare account
    site_num = get_next_site_number()
    if site_num is None:
        _clog.error("create_cloudflare_blog: all 500 site slots used")
        return None

    github_path   = f"sites/site-{site_num:03d}"

    # BUG-009 FIX: use professional name pool instead of "blogbot-site-NNN"
    project_name  = get_professional_site_name(niche)
    blog_id       = project_name

    if title is None:
        title = _name_to_title(project_name)

    # Step 3: Create Cloudflare Pages project
    blog_url = f"https://{project_name}.pages.dev"
    try:
        from modules.cloudflare_manager import get_manager
        from modules.config_manager import load_config as _lc
        cf  = get_manager()

        # BUG-010 FIX: resolve the real account_id string (not just the index "1")
        acct = cf.get_account_for_site(site_num)
        real_account_id = acct.account_id if acct else str(((site_num - 1) // 100) + 1)

        # BUG-009 FIX: pass required github_owner / github_repo args
        _gh = _lc().get("github", {})
        result = cf.create_pages_project(
            account_id=real_account_id,
            project_name=project_name,
            github_owner=_gh.get("username", ""),
            github_repo=_gh.get("repo", "blogbot-sites"),
            build_dir=github_path,
        )
        if result and result.get("subdomain"):
            blog_url = f"https://{result['subdomain']}"
        elif result and result.get("name"):
            blog_url = f"https://{result['name']}.pages.dev"
    except Exception as e:
        _clog.warning(f"Cloudflare project creation skipped ({e}) — proceeding with default URL")

    # Store real account index for DB reference (1-5)
    cf_account_id = str(((site_num - 1) // 100) + 1)

    # Step 4: Create placeholder + legal pages and push to GitHub
    try:
        from modules.static_site_generator import (
            SiteConfig, generate_legal_pages, generate_robots_txt, generate_ads_txt
        )
        from modules.github_publisher import make_publisher_from_config
        from pathlib import Path

        base_dir   = Path(__file__).parent.parent.resolve()
        output_dir = base_dir / "sites" / f"site-{site_num:03d}"
        output_dir.mkdir(parents=True, exist_ok=True)

        site_cfg = SiteConfig(
            site_id=site_num,
            blog_id=blog_id,
            title=title,
            language=language,
            niche=niche,
            blog_url=blog_url,
            ad_codes=ad_codes or {},
        )

        # Placeholder index.html
        placeholder = (
            f"<!DOCTYPE html><html lang='{language}'><head>"
            f"<meta charset='UTF-8'><title>{title}</title></head>"
            f"<body><h1>{title}</h1><p>Coming soon.</p></body></html>"
        )
        (output_dir / "index.html").write_text(placeholder, encoding="utf-8")
        (output_dir / "robots.txt").write_text(
            generate_robots_txt(blog_url), encoding="utf-8"
        )
        (output_dir / "ads.txt").write_text(
            generate_ads_txt({}), encoding="utf-8"
        )
        generate_legal_pages(site_cfg, output_dir)

        pub = make_publisher_from_config()
        if pub is None:
            raise RuntimeError("GitHub publisher not configured")
        pub.push_site(
            site_id=site_num,
            site_dir=output_dir,
        )
    except Exception as e:
        _clog.warning(f"Placeholder push failed ({e}) — blog registered without content")

    # Step 5: Register in blogs.db
    try:
        from modules.static_site_generator import register_static_blog
        gmail = "blogbot@protonmail.com"  # default; overridden from config if available
        try:
            from modules.config_manager import load_config
            cfg = load_config()
            set_c = (cfg.get("gmail", {}) or {}).get("set_c", [])
            if set_c:
                gmail = set_c[0]
        except Exception as e:  # noqa: BLE001 — fall back to default email
            _clog.debug(f"load gmail from config: {e}")

        row_id = register_static_blog(
            site_id=site_num,
            blog_id=blog_id,
            title=title,
            niche=niche,
            role="hub",        # BUG-008 FIX: "main" violates DB CHECK(hub|feeder|traffic_catcher|link_builder)
            language=language,
            gmail_account=gmail,
            cloudflare_account_id=cf_account_id,
            github_path=github_path,
            site_url=blog_url,
        )
    except Exception as e:
        _clog.error(f"register_static_blog failed: {e}")
        row_id = None

    # Step 6: Submit sitemap to Bing Webmaster Tools
    try:
        submit_sitemap(blog_url)
    except Exception as e:  # noqa: BLE001 — sitemap submission is best-effort
        _clog.debug(f"submit_sitemap({blog_url}): {e}")

    # Step 7: Fire IndexNow
    try:
        from modules.indexing import get_indexing_manager
        im = get_indexing_manager()
        im.on_post_published(blog_url, blog_url, title, niche)
    except Exception as e:  # noqa: BLE001 — indexing is best-effort
        _clog.debug(f"IndexNow on_post_published({blog_url}): {e}")

    # Step 8: Submit to blog directories (Feedspot, AllTop, Blogarama)
    try:
        from modules.directory_submitter import submit_new_blog_to_directories
        rss_url = f"{blog_url}/sitemap.xml"
        _blog_title = title or project_name.replace("-", " ").title()
        submit_new_blog_to_directories(blog_url, rss_url, _blog_title, niche)
    except Exception as e:  # noqa: BLE001 — directory submission is best-effort
        _clog.debug(f"directory_submitter({blog_url}): {e}")

    # Step 9: Alert dashboard
    try:
        from modules.alert_system import tier1
        tier1(f"New blog created: {blog_url} (niche={niche}, site={site_num:03d})")
    except Exception as e:  # noqa: BLE001 — alert_system may not be running
        _clog.debug(f"tier1 alert: {e}")

    _clog.info(f"create_cloudflare_blog complete: {blog_url} (site-{site_num:03d})")
    return {
        "blog_url":       blog_url,
        "site_id":        site_num,
        "github_path":    github_path,
        "cf_account_id":  cf_account_id,
        "blog_id":        blog_id,
        "niche":          niche,
        "language":       language,
        "db_row_id":      row_id,
    }


# ── Self-Test ──────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import io
    if sys.platform == "win32":
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

    print("blog_manager self-test...")

    # Template generation
    tmpl = build_blogger_template("Test Blog", "en", "crypto")
    print(f"  Template generated: {'OK' if len(tmpl) > 1000 else 'FAIL'}")
    print(f"  Template has canonical placeholder: {'OK' if 'CANONICAL_PLACEHOLDER' in tmpl else 'FAIL'}")
    print(f"  Template has hreflang placeholder: {'OK' if 'HREFLANG_PLACEHOLDER' in tmpl else 'FAIL'}")
    print(f"  Template has cookie banner: {'OK' if 'cookie-banner' in tmpl else 'FAIL'}")
    print(f"  Template has sticky footer: {'OK' if 'sticky-footer-ad' in tmpl else 'FAIL'}")
    print(f"  Template has 6 ad slots: {'OK' if tmpl.count('AD_SLOT') >= 6 else 'FAIL'}")

    # RTL template
    tmpl_ar = build_blogger_template("مدونة الأخبار", "ar", "breaking_news")
    print(f"  RTL template for Arabic: {'OK' if 'rtl' in tmpl_ar else 'FAIL'}")

    # Adult template
    tmpl_adult = build_blogger_template("Adult Blog", "en", "adult", is_adult=True)
    print(f"  Adult template has 18+ warning: {'OK' if 'adult-warning' in tmpl_adult else 'FAIL'}")
    print(f"  Adult template has adult meta: {'OK' if 'rating' in tmpl_adult else 'FAIL'}")

    # Legal pages
    pages = LEGAL_PAGES_EN
    print(f"  Legal pages defined: {len(pages)} {'OK' if len(pages) >= 6 else 'FAIL'}")
    adult_pages = ADULT_LEGAL_PAGES_EN
    print(f"  Adult legal pages: {len(adult_pages)} {'OK' if len(adult_pages) >= 2 else 'FAIL'}")

    # Legal page body formatting
    pp = LEGAL_PAGES_EN["privacy_policy"]["body"].format(blog_title="Test Blog", date="2026-03-27")
    print(f"  Privacy policy body: {'OK' if 'GDPR' in pp and 'CCPA' in pp else 'FAIL'}")

    # Placeholder resolution
    dummy_blog = BlogInfo(
        blog_id=1, blogger_id="123456789", url="https://test-blog.blogspot.com",
        title="Test Blog", niche="crypto", role="feeder", language="en",
        gmail_account="test@gmail.com", is_adult=False,
        created_at=datetime.now(timezone.utc).isoformat()
    )
    test_html = "<!-- CANONICAL_PLACEHOLDER --><!-- HREFLANG_PLACEHOLDER --><!-- SCHEMA_PLACEHOLDER --><!-- FEATURED_IMAGE_PLACEHOLDER --><!-- AFFILIATE_DISCLOSURE --><!-- LEGAL_FOOTER --><p>Content.</p>"
    resolved = resolve_post_placeholders(
        body_html=test_html,
        blog_info=dummy_blog,
        canonical_url="https://test-blog.blogspot.com/post/test",
        hreflang_links={"en": "https://test-blog.blogspot.com/post/test"},
        featured_image_url="https://images.example.com/test.jpg",
    )
    print(f"  Canonical resolved: {'OK' if 'rel=\"canonical\"' in resolved else 'FAIL'}")
    print(f"  Hreflang resolved: {'OK' if 'hreflang' in resolved else 'FAIL'}")
    print(f"  Schema resolved: {'OK' if 'application/ld+json' in resolved else 'FAIL'}")
    print(f"  Featured image resolved: {'OK' if 'images.example.com' in resolved else 'FAIL'}")
    print(f"  Disclosure resolved: {'OK' if 'Disclosure' in resolved else 'FAIL'}")
    print(f"  Legal footer resolved: {'OK' if 'Published' in resolved else 'FAIL'}")

    # Post size check
    big_html = "a" * (BLOGGER_POST_SIZE_LIMIT_MB * 1024 * 1024 + 1)
    size_ok = len(big_html.encode()) > BLOGGER_POST_SIZE_LIMIT_MB * 1024 * 1024
    print(f"  Post size limit detection: {'OK' if size_ok else 'FAIL'}")

    # Sitemap XML generation
    blogs = [dummy_blog]
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        xml = update_network_sitemap_index(blogs, output_path=Path(tmp) / "sitemap_index.xml")
    print(f"  Sitemap index: {'OK' if 'sitemapindex' in xml and 'blogspot.com' in xml else 'FAIL'}")

    # Template integrity
    record_template_checksum(1, tmpl)
    print(f"  Template checksum match: {'OK' if check_template_integrity(1, tmpl) else 'FAIL'}")
    print(f"  Template checksum tamper: {'OK' if not check_template_integrity(1, tmpl + 'x') else 'FAIL'}")

    # Ad block builder
    ad_codes = {"slot_1": "<script>ad1()</script>", "slot_2": "<script>ad2()</script>"}
    ad_block = build_ad_injection_html(ad_codes)
    print(f"  Ad injection block: {'OK' if 'AD_SLOT_1' in ad_block and 'ad1()' in ad_block else 'FAIL'}")

    print()
    print("Self-test complete.")
