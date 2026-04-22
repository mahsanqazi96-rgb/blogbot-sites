"""
BlogBot — setup_traffic_keys.py
One-time setup for new automated traffic sources.
Run this ONCE to enter API keys, then the bot handles everything automatically.

Usage:
    py setup_traffic_keys.py
"""

import sys
import json
import base64
from pathlib import Path

BASE_DIR = Path(__file__).parent.resolve()
sys.path.insert(0, str(BASE_DIR))

print("=" * 60)
print("  BlogBot — Traffic Sources Setup")
print("  Run once, automated forever after")
print("=" * 60)
print()

def _save_key(key_name: str, value: str) -> None:
    """Save a key to config.json via config_manager."""
    try:
        from modules.config_manager import set as cfg_set
        cfg_set(key_name, value)
    except Exception as e:
        print(f"  [WARN] config_manager.set failed ({e}) — saving to plain fallback")
        fallback = BASE_DIR / "data" / "traffic_keys.json"
        existing = json.loads(fallback.read_text()) if fallback.exists() else {}
        existing[key_name] = value
        fallback.write_text(json.dumps(existing, indent=2))


def _get_key(key_name: str, default: str = "") -> str:
    try:
        from modules.config_manager import get as cfg_get
        return cfg_get(key_name, default)
    except Exception:
        fallback = BASE_DIR / "data" / "traffic_keys.json"
        if fallback.exists():
            return json.loads(fallback.read_text()).get(key_name, default)
        return default


def ask(prompt: str, current: str = "") -> str:
    if current:
        print(f"  Current value: {current[:8]}... (press Enter to keep)")
    val = input(f"  {prompt}: ").strip()
    return val if val else current


# ── 1. OneSignal Web Push ─────────────────────────────────────────────────────

print("━" * 60)
print("1. OneSignal Web Push (push notifications to subscribers)")
print("━" * 60)
print()
print("  HOW TO GET KEYS (5 minutes):")
print("  a) Go to: https://app.onesignal.com/signup")
print("  b) Sign up with your email")
print("  c) Create new app → choose 'Web Push' → enter your site URL")
print("     Site URL: https://topicpulse.pages.dev")
print("  d) Copy 'App ID' from Settings → Keys & IDs")
print("  e) Copy 'REST API Key' from Settings → Keys & IDs")
print()

cur_app_id  = _get_key("onesignal_app_id")
cur_api_key = _get_key("onesignal_api_key")

app_id  = ask("OneSignal App ID (32-char UUID)", cur_app_id)
api_key = ask("OneSignal REST API Key", cur_api_key)

if app_id:
    _save_key("onesignal_app_id", app_id)
    _save_key("onesignal_api_key", api_key)
    print("  ✅ OneSignal keys saved")
else:
    print("  ⏭  Skipped (enter later)")


# ── 2. Medium Integration ─────────────────────────────────────────────────────

print()
print("━" * 60)
print("2. Medium Syndication (auto-publish posts to Medium)")
print("━" * 60)
print()
print("  HOW TO GET TOKEN (2 minutes):")
print("  a) Go to: https://medium.com/me/settings/security")
print("  b) Sign in → scroll to 'Integration tokens'")
print("  c) Generate token with description: BlogBot")
print("  d) Copy the token (starts with a long alphanumeric string)")
print()

cur_token = _get_key("medium_integration_token")
token = ask("Medium Integration Token", cur_token)

if token:
    _save_key("medium_integration_token", token)
    print("  ✅ Medium token saved")
else:
    print("  ⏭  Skipped (enter later)")


# ── 3. CryptoPanic ───────────────────────────────────────────────────────────

print()
print("━" * 60)
print("3. CryptoPanic News Source (500k+ crypto readers)")
print("━" * 60)
print()
print("  HOW TO GET TOKEN (3 minutes):")
print("  a) Go to: https://cryptopanic.com/developers/api/")
print("  b) Click 'Get Free API Access'")
print("  c) Register with email")
print("  d) Copy your auth_token from your developer dashboard")
print()

cur_cp = _get_key("cryptopanic_auth_token")
cp_token = ask("CryptoPanic Auth Token", cur_cp)

if cp_token:
    _save_key("cryptopanic_auth_token", cp_token)
    print("  ✅ CryptoPanic token saved")
else:
    print("  ⏭  Skipped (enter later)")


# ── 4. Flipboard ─────────────────────────────────────────────────────────────

print()
print("━" * 60)
print("4. Flipboard Magazines (100M+ readers, RSS auto-feed)")
print("━" * 60)
print()
print("  NOTE: Flipboard URL pinging works WITHOUT an account.")
print("  For full magazine creation (optional, higher traffic):")
print("  a) Go to: https://flipboard.com/register")
print("  b) Create account → create 5 magazines (one per niche)")
print("  c) Each magazine: Settings → RSS → add all your blog RSS feeds")
print("  The bot will ping Flipboard URLs automatically regardless.")
print()
print("  ✅ Flipboard URL pinging: ENABLED (no key needed)")


# ── 5. Feedspot / AllTop ─────────────────────────────────────────────────────

print()
print("━" * 60)
print("5. Feedspot & AllTop Directory (permanent backlinks)")
print("━" * 60)
print()
print("  Submitting all 100 blog RSS feeds to directories now...")
print("  This runs automatically — no API key needed.")
print()

if input("  Submit all blogs to directories now? (y/n): ").lower() == 'y':
    try:
        import sqlite3
        db = BASE_DIR / "data" / "blogs.db"
        conn = sqlite3.connect(str(db))
        cur  = conn.cursor()
        cur.execute("""SELECT blog_id, github_path, niche
                       FROM blogs WHERE platform='cloudflare'
                       AND github_path IS NOT NULL""")
        rows = cur.fetchall()
        conn.close()

        from modules.directory_submitter import submit_new_blog_to_directories
        submitted = 0
        for blog_id, github_path, niche in rows:
            blog_url = f"https://topicpulse.pages.dev/{github_path}"
            rss_url  = f"{blog_url}/sitemap.xml"
            title    = github_path.replace("-", " ").title()
            result   = submit_new_blog_to_directories(blog_url, rss_url, title, niche)
            ok_count = sum(1 for v in result.values() if v)
            submitted += ok_count
        print(f"  ✅ Directory submissions: {submitted} successful")
    except Exception as e:
        print(f"  [WARN] Directory submission: {e}")
        print("  Will retry automatically when bot runs next cycle.")


# ── Summary ───────────────────────────────────────────────────────────────────

print()
print("=" * 60)
print("  Setup complete!")
print("  The bot will now use all configured traffic sources")
print("  on every new post publish — fully automatic.")
print()
print("  To add/change a key later, run this script again.")
print("=" * 60)
