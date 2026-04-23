"""
BlogBot — setup_traffic_keys.py
One-time setup for all automated traffic sources.
Run this ONCE to enter API keys, then the bot handles everything automatically.

Usage:
    py setup_traffic_keys.py
"""

import sys
import json
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
        from modules.config_manager import set_value as cfg_set
        cfg_set(key_name, value)
    except Exception as e:
        print(f"  [WARN] config_manager.set_value failed ({e}) — saving to plain fallback")
        fallback = BASE_DIR / "data" / "traffic_keys.json"
        fallback.parent.mkdir(parents=True, exist_ok=True)
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


def ask(prompt: str, current: str = "", secret: bool = False) -> str:
    display = (current[:6] + "..." if len(current) > 8 else current) if (current and secret) else current
    if current:
        print(f"  Current: {display}  (press Enter to keep)")
    val = input(f"  {prompt}: ").strip()
    return val if val else current


def section(n: int, title: str, subtitle: str = "") -> None:
    print()
    print("━" * 60)
    print(f"{n}. {title}")
    if subtitle:
        print(f"   {subtitle}")
    print("━" * 60)
    print()


# ═══════════════════════════════════════════════════════════════
# 1. OneSignal Web Push
# ═══════════════════════════════════════════════════════════════
section(1, "OneSignal Web Push", "Push notifications to blog subscribers")
print("  HOW TO GET KEYS:")
print("  a) https://app.onesignal.com/signup")
print("  b) Create Web Push app → site URL: https://topicpulse.pages.dev")
print("  c) Copy App ID + REST API Key from Settings → Keys & IDs")
print()

app_id  = ask("OneSignal App ID",      _get_key("onesignal_app_id"),  secret=True)
api_key = ask("OneSignal REST API Key", _get_key("onesignal_api_key"), secret=True)
if app_id:
    _save_key("onesignal_app_id",  app_id)
    _save_key("onesignal_api_key", api_key)
    print("  ✅ OneSignal saved")
else:
    print("  ⏭  Skipped")


# ═══════════════════════════════════════════════════════════════
# 2. Medium Syndication
# ═══════════════════════════════════════════════════════════════
section(2, "Medium Syndication", "Auto-publish posts to Medium")
print("  a) https://medium.com/me/settings/security")
print("  b) Integration tokens → Generate → name: BlogBot")
print()

token = ask("Medium Integration Token", _get_key("medium_integration_token"), secret=True)
if token:
    _save_key("medium_integration_token", token)
    print("  ✅ Medium saved")
else:
    print("  ⏭  Skipped")


# ═══════════════════════════════════════════════════════════════
# 3. CryptoPanic (paid plan only — skip if not available)
# ═══════════════════════════════════════════════════════════════
section(3, "CryptoPanic", "Crypto news aggregator — paid plan only, skip if unavailable")
cp_token = ask("CryptoPanic Auth Token", _get_key("cryptopanic_auth_token"), secret=True)
if cp_token:
    _save_key("cryptopanic_auth_token", cp_token)
    print("  ✅ CryptoPanic saved")
else:
    print("  ⏭  Skipped")


# ═══════════════════════════════════════════════════════════════
# 4. Telegram Bot + 5 Channels
# ═══════════════════════════════════════════════════════════════
section(4, "Telegram Bot + Channels", "Posts new articles to 5 niche Telegram channels")
print("  SETUP (see SETUP_ACCOUNTS.md Step 2 for full instructions):")
print("  a) Message @BotFather → /newbot → copy the token")
print("  b) Create 5 channels and add your bot as admin")
print()

tg_token = ask("Telegram Bot Token", _get_key("telegram_bot_token"), secret=True)
if tg_token:
    _save_key("telegram_bot_token", tg_token)

    niches = ["tech", "crypto", "finance", "health", "entertainment"]
    for n in niches:
        key = f"telegram_channel_{n}"
        val = ask(f"  Telegram channel for {n} (e.g. @topicpulse_{n})", _get_key(key))
        if val:
            _save_key(key, val)

    print("  ✅ Telegram saved")
else:
    print("  ⏭  Skipped")


# ═══════════════════════════════════════════════════════════════
# 5. Bluesky
# ═══════════════════════════════════════════════════════════════
section(5, "Bluesky", "Posts new articles to Bluesky with link cards")
print("  a) https://bsky.app → sign up")
print("  b) Settings → App Passwords → Add App Password → name: BlogBot")
print()

bsky_handle = ask("Bluesky handle (e.g. topicpulse.bsky.social)", _get_key("bluesky_handle"))
bsky_pass   = ask("Bluesky App Password (xxxx-xxxx-xxxx-xxxx)",   _get_key("bluesky_app_password"), secret=True)
if bsky_handle:
    _save_key("bluesky_handle",       bsky_handle)
    _save_key("bluesky_app_password", bsky_pass)
    print("  ✅ Bluesky saved")
else:
    print("  ⏭  Skipped")


# ═══════════════════════════════════════════════════════════════
# 6. Mastodon
# ═══════════════════════════════════════════════════════════════
section(6, "Mastodon", "Posts new articles to Mastodon federated network")
print("  a) https://mastodon.social/auth/sign_up")
print("  b) Settings → Development → New Application → copy access token")
print()

mast_url   = ask("Mastodon instance URL (e.g. https://mastodon.social)", _get_key("mastodon_instance_url"))
mast_token = ask("Mastodon Access Token", _get_key("mastodon_access_token"), secret=True)
if mast_url:
    _save_key("mastodon_instance_url",  mast_url)
    _save_key("mastodon_access_token",  mast_token)
    print("  ✅ Mastodon saved")
else:
    print("  ⏭  Skipped")


# ═══════════════════════════════════════════════════════════════
# 7. Reddit
# ═══════════════════════════════════════════════════════════════
section(7, "Reddit", "Submits posts to relevant subreddits (needs 30-day-aged accounts)")
print("  NOTE: Create Reddit accounts today — they need karma before link posting works.")
print("  a) https://www.reddit.com/prefs/apps → Create App (script type)")
print("  b) Copy client_id (under app name) + client_secret")
print()

reddit_id     = ask("Reddit Client ID",     _get_key("reddit_client_id"),     secret=True)
reddit_secret = ask("Reddit Client Secret", _get_key("reddit_client_secret"), secret=True)
reddit_user   = ask("Reddit Username",      _get_key("reddit_username"))
reddit_pass   = ask("Reddit Password",      _get_key("reddit_password"),      secret=True)
if reddit_id:
    _save_key("reddit_client_id",     reddit_id)
    _save_key("reddit_client_secret", reddit_secret)
    _save_key("reddit_username",      reddit_user)
    _save_key("reddit_password",      reddit_pass)
    print("  ✅ Reddit saved")
else:
    print("  ⏭  Skipped")


# ═══════════════════════════════════════════════════════════════
# 8. Discord Webhook (for FeedCord — easiest option)
# ═══════════════════════════════════════════════════════════════
section(8, "Discord Webhook (FeedCord)", "Posts new articles to Discord channels via webhook")
print("  a) Open any Discord channel → Edit Channel → Integrations → Webhooks")
print("  b) New Webhook → copy URL (https://discord.com/api/webhooks/...)")
print()

discord_webhook = ask("Discord Webhook URL", _get_key("discord_webhook_url"), secret=True)
if discord_webhook:
    _save_key("discord_webhook_url", discord_webhook)
    print("  ✅ Discord webhook saved")
else:
    print("  ⏭  Skipped")


# ═══════════════════════════════════════════════════════════════
# 9. Brevo SMTP (for listmonk newsletter)
# ═══════════════════════════════════════════════════════════════
section(9, "Brevo SMTP", "Free SMTP for listmonk newsletter — 300 emails/day free")
print("  a) https://www.brevo.com → Sign up free")
print("  b) Transactional → Settings → SMTP & API → SMTP tab")
print("  c) Copy: SMTP login (your email) + SMTP key (the long password)")
print()

brevo_host = "smtp-relay.brevo.com"
brevo_port = "587"
brevo_login = ask("Brevo SMTP login (your email)", _get_key("brevo_smtp_login"))
brevo_pass  = ask("Brevo SMTP password (the key)", _get_key("brevo_smtp_password"), secret=True)
if brevo_login:
    _save_key("brevo_smtp_host",     brevo_host)
    _save_key("brevo_smtp_port",     brevo_port)
    _save_key("brevo_smtp_login",    brevo_login)
    _save_key("brevo_smtp_password", brevo_pass)
    print("  ✅ Brevo SMTP saved")
else:
    print("  ⏭  Skipped")


# ═══════════════════════════════════════════════════════════════
# 10. Pinterest (for pinterest-bot bulk CSV generator)
# ═══════════════════════════════════════════════════════════════
section(10, "Pinterest", "Bulk pin generator — reads posts and creates pins.csv for upload")
print("  a) https://pinterest.com/business/convert/ → convert to business")
print("  b) Create 5 boards: Tech, Crypto, Finance, Health, Entertainment")
print("  c) Enter credentials below (used only for CSV generation, not automated login)")
print()

pin_email = ask("Pinterest email", _get_key("pinterest_email"))
if pin_email:
    _save_key("pinterest_email", pin_email)
    print("  ✅ Pinterest email saved (use third_party/pinterest-bot/generate_csv.py to create pins)")
else:
    print("  ⏭  Skipped")


# ═══════════════════════════════════════════════════════════════
# 11. Directory submission (runs immediately)
# ═══════════════════════════════════════════════════════════════
section(11, "Feedspot / AllTop / Blogarama Directory Submission", "Permanent backlinks — no key needed")
print("  Submits all live blog RSS feeds to 200+ directories.")
print()

if input("  Submit all blogs to directories now? (y/n): ").strip().lower() == 'y':
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
else:
    print("  ⏭  Skipped")


# ═══════════════════════════════════════════════════════════════
# Final summary
# ═══════════════════════════════════════════════════════════════
print()
print("=" * 60)
print("  Setup complete!")
print()
print("  Sources that activate with ZERO credentials:")
print("    ✅ Nostr publisher    — broadcasts immediately")
print("    ✅ IndexNow (Python)  — fires on every post publish")
print("    ✅ RSS pings          — 500+ ping services notified")
print("    ✅ Flipboard ping     — URL ping on every post")
print("    ✅ Directory listing  — if submitted above")
print()
print("  Sources activated by credentials you just entered:")
print("    Telegram, Bluesky, Mastodon, Reddit, Discord,")
print("    OneSignal push, Medium, listmonk newsletter")
print()
print("  GitHub Actions (activate after first git push):")
print("    IndexNow workflow, Bluesky RSS bot, Multi-social poster")
print()
print("  To change any key later, run this script again.")
print("=" * 60)
