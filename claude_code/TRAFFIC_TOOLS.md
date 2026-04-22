# BlogBot — TRAFFIC_TOOLS.md
## Master Reference: All Traffic Tools (Libraries + Ready-Made)
*Created SESSION-038 — 2026-04-23*

---

## OVERVIEW

16 tools total across two categories:
- **Python modules** (built into bot, fire on every post publish automatically)
- **Ready-made tools** (standalone services/actions, run separately)

RSS feed URL format per blog: `https://<blog>.pages.dev/feed.xml`
IndexNow key: `f00a67501cd09f1f9f3977cbcad94c53`

---

## COMPLETE TOOL LIST

| # | Tool | Type | Impact | Account Needed | Status |
|---|------|------|--------|---------------|--------|
| 1 | Telegram (python-telegram-bot) | Python module | 🔥🔥🔥🔥 | Bot token | Waiting |
| 2 | Bluesky (atproto) | Python module | 🔥🔥🔥 | Free account | Waiting |
| 3 | Mastodon (Mastodon.py) | Python module | 🔥🔥 | Free account | Waiting |
| 4 | Reddit (PRAW) | Python module | 🔥🔥🔥🔥 | Aged accounts | Waiting |
| 5 | Nostr (nostr-sdk) | Python module | 🔥 | None ✅ | Ready to build |
| 6 | pywebpush (self-hosted push) | Python module | 🔥🔥🔥 | None ✅ | Ready to build |
| 7 | Postiz (28-platform dashboard) | Docker service | 🔥🔥🔥🔥🔥 | Per platform | Waiting Docker |
| 8 | BoKKeR RSS-to-Telegram | Python script | 🔥🔥🔥🔥 | Bot token | Waiting |
| 9 | blueskyfeedbot | GitHub Action | 🔥🔥🔥 | Bluesky | Waiting |
| 10 | MonitoRSS (Discord) | Docker service | 🔥🔥 | Discord bot | Waiting |
| 11 | FeedCord (Discord webhook) | Docker service | 🔥🔥 | Webhook URL | Waiting |
| 12 | listmonk (newsletter) | Docker service | 🔥🔥🔥🔥 | SMTP | Waiting Docker |
| 13 | Skywrite (Bluesky RSS) | Python script | 🔥🔥🔥 | Bluesky | Waiting |
| 14 | PinterestBulkPostBot | Python/Selenium | 🔥🔥🔥 | Pinterest | Ready to build |
| 15 | indexnow-action | GitHub Action | 🔥🔥🔥 | None ✅ | Ready to build |
| 16 | feed-to-social-media | GitHub Action | 🔥🔥 | Multi-platform | Waiting |

---

## SECTION A: PYTHON MODULES (built into bot_loop.py)

These fire inside `_fire_traffic_signals()` after every single post publish.

---

### MODULE 1: Telegram Publisher
**Library:** python-telegram-bot ★29,000 — https://github.com/python-telegram-bot/python-telegram-bot
**File:** `modules/telegram_publisher.py`
**Impact:** 🔥🔥🔥🔥 Very High
**What it does:** Posts every new article to 5 niche Telegram channels instantly. 900M users, zero algorithm — every subscriber sees every post.

### Setup:
1. Open Telegram → search @BotFather → `/newbot`
2. Copy bot token
3. Create 5 channels (tech/crypto/finance/health/entertainment)
4. Add bot as admin to each channel
5. Tell Claude the token + channel usernames → activates immediately

---

### MODULE 2: Bluesky Publisher
**Library:** atproto ★646 — https://github.com/MarshalX/atproto
**File:** `modules/bluesky_publisher.py`
**Impact:** 🔥🔥🔥 High
**What it does:** Posts every new article to Bluesky. 35M users, no link suppression, no shadow-banning. App password auth — no OAuth.

### Setup:
1. Create account at bsky.app
2. Settings → App Passwords → create one named "BlogBot"
3. Tell Claude handle + password → activates immediately

---

### MODULE 3: Mastodon Publisher
**Library:** Mastodon.py ★946 — https://github.com/halcy/Mastodon.py
**File:** `modules/mastodon_publisher.py`
**Impact:** 🔥🔥 Medium
**What it does:** Posts to Mastodon, federating across thousands of Fediverse instances. One post reaches Mastodon, Misskey, Pleroma, Pixelfed audiences simultaneously.

### Setup:
1. Create account at mastodon.social
2. Settings → Development → New Application → copy access token
3. Tell Claude instance URL + token → activates immediately

---

### MODULE 4: Reddit Submitter
**Library:** PRAW ★4,100 — https://github.com/praw-dev/praw
**File:** `modules/reddit_publisher.py`
**Impact:** 🔥🔥🔥🔥 Very High (highest RPM referral source)
**What it does:** Submits posts to relevant subreddits. Finance posts → r/personalfinance, r/investing. Crypto → r/CryptoCurrency. Tech → r/technology. Health → r/loseit, r/fitness.

### Setup:
1. Create Reddit account NOW (needs 30 days + karma before link posting works)
2. reddit.com/prefs/apps → create app (script type) → copy client_id + client_secret
3. Tell Claude credentials → bot waits until accounts are aged enough

---

### MODULE 5: Nostr Publisher
**Library:** nostr-sdk — https://github.com/rust-nostr/nostr (`pip install nostr-sdk`)
**File:** `modules/nostr_publisher.py`
**Impact:** 🔥 Low-Medium (growing, good for crypto/finance)
**What it does:** Publishes to the decentralised Nostr protocol. No account, no bans, no algorithm. Broadcasts to 20 public relays simultaneously. Content appears in Damus, Primal, Snort.
**STATUS: ✅ READY TO BUILD — generates keypair automatically, zero setup**

---

### MODULE 6: Self-Hosted Web Push (pywebpush)
**Library:** pywebpush ★366 — https://github.com/web-push-libs/pywebpush
**File:** `modules/webpush_publisher.py`
**Impact:** 🔥🔥🔥 High (long-term — builds subscriber list you own permanently)
**What it does:** Replaces OneSignal with a self-hosted push system. VAPID keys auto-generated. Subscribe button added to blog templates. Subscriber endpoints stored in analytics.db. No platform dependency, free forever.
**STATUS: ✅ READY TO BUILD — no accounts needed**

---

---

## TOOL 1: Postiz (Self-Hosted Social Dashboard)
**GitHub:** https://github.com/gitroomhq/postiz-app ★28,400
**Type:** Docker service (runs 24/7 on your machine)
**Platforms:** Twitter/X, Bluesky, Mastodon, Reddit, Pinterest, Instagram, TikTok, LinkedIn, Discord, Telegram, YouTube + 17 more
**Location:** `third_party/postiz/`

### How it works:
- Postiz runs as a web dashboard at http://localhost:3000
- BlogBot calls the Postiz REST API after every post publish
- Postiz schedules and distributes the post to all connected platforms
- You connect platforms once via the web UI — bot handles the rest forever

### Setup steps:
1. Install Docker Desktop (https://www.docker.com/products/docker-desktop/)
2. Run: `cd third_party/postiz && docker-compose up -d`
3. Open http://localhost:3000
4. Connect your accounts (Twitter, Bluesky, Reddit, Pinterest, etc.)
5. Copy your Postiz API key from Settings → API
6. Run: `py setup_traffic_keys.py` → enter Postiz API key + channel IDs
7. Bot calls Postiz automatically from next cycle

### Config files:
- `third_party/postiz/docker-compose.yml`
- `third_party/postiz/.env` (copy from .env.example, fill in values)

### Status: ⏳ WAITING FOR DOCKER DESKTOP

---

## TOOL 2: BoKKeR RSS-to-Telegram-Bot
**GitHub:** https://github.com/BoKKeR/RSS-to-Telegram-Bot ★500
**Type:** Python script (runs as background process)
**Platform:** Telegram (900M users)
**Location:** `third_party/rss-to-telegram/`

### How it works:
- One Telegram channel per niche (5 channels total)
- Bot checks all 100 blog RSS feeds every 10 minutes
- New posts auto-posted to the matching niche channel
- Channel members get instant notification with title + link

### Niche → Channel mapping:
- tech blogs → @blogbot_tech (or your channel name)
- crypto blogs → @blogbot_crypto
- finance blogs → @blogbot_finance
- health blogs → @blogbot_health
- entertainment blogs → @blogbot_entertainment

### Setup steps:
1. Open Telegram → search @BotFather → type /newbot
2. Name it "TopicPulse Bot" → username "topicpulse_bot"
3. Copy the token (looks like: 1234567890:ABCdef...)
4. Create 5 Telegram channels (one per niche)
5. Add your bot as admin to all 5 channels
6. Copy each channel's username or ID
7. Edit `third_party/rss-to-telegram/config.ini` with your token + channel IDs
8. Run `START_TELEGRAM_BOT.bat` to start (runs in background)

### Config files:
- `third_party/rss-to-telegram/config.ini` (copy from config.ini.example)
- `third_party/rss-to-telegram/START_TELEGRAM_BOT.bat`

### Status: ⏳ WAITING FOR TELEGRAM BOT TOKEN + CHANNEL IDs

---

## TOOL 3: blueskyfeedbot (GitHub Action)
**GitHub:** https://github.com/joschi/blueskyfeedbot ★200
**Type:** GitHub Action (runs free in GitHub, no server needed)
**Platform:** Bluesky (35M users, no algorithm suppression)
**Location:** `.github/workflows/bluesky-rss.yml`

### How it works:
- GitHub Action runs on a cron schedule (every 30 minutes)
- Checks all blog RSS feeds for new items
- Posts each new item to your Bluesky account automatically
- Zero server cost — GitHub runs it free

### Setup steps:
1. Create Bluesky account at https://bsky.app
2. Go to Settings → Privacy and Security → App Passwords
3. Create app password named "BlogBot"
4. Go to your GitHub repo → Settings → Secrets → Actions
5. Add secret: `BLUESKY_IDENTIFIER` = your handle (e.g. yourname.bsky.social)
6. Add secret: `BLUESKY_PASSWORD` = the app password
7. Workflow file is already in repo — activates automatically

### Config files:
- `.github/workflows/bluesky-rss.yml` (already created)

### Status: ⏳ WAITING FOR BLUESKY ACCOUNT + GITHUB SECRETS

---

## TOOL 4: MonitoRSS (Discord RSS Bot)
**GitHub:** https://github.com/synzen/MonitoRSS ★1,200
**Type:** Docker service
**Platform:** Discord (servers in crypto/tech/finance niches)
**Location:** `third_party/monitorrss/`

### How it works:
- MonitoRSS monitors all 100 blog RSS feeds
- New posts appear as rich embeds in your Discord channels
- Join niche Discord servers, add your bot, and feed those communities
- Has a web control panel at http://localhost:8081

### Setup steps:
1. Go to https://discord.com/developers/applications
2. Create new application → "TopicPulse Bot"
3. Bot tab → Add Bot → copy token
4. Generate invite URL with bot permissions → add to your servers
5. Install Docker Desktop
6. Run: `cd third_party/monitorrss && docker-compose up -d`
7. Open http://localhost:8081
8. Add your bot token + channel IDs + RSS feed URLs via web UI

### Config files:
- `third_party/monitorrss/docker-compose.yml`
- `third_party/monitorrss/config.json` (copy from .example)

### Status: ⏳ WAITING FOR DISCORD BOT TOKEN + DOCKER DESKTOP

---

## TOOL 5: listmonk (Self-Hosted Email Newsletter)
**GitHub:** https://github.com/knadh/listmonk ★19,500
**Type:** Docker service + BlogBot API integration
**Platform:** Email (subscribers from your blogs)
**Location:** `third_party/listmonk/`

### How it works:
- listmonk runs at http://localhost:9000
- A subscribe form is embedded in your blog templates
- New subscribers are stored in listmonk's database
- BlogBot calls listmonk API every Sunday to send weekly digest
- Digest = top 10 posts from that week across all 100 blogs

### Setup steps:
1. Create free Brevo account at https://brevo.com
2. Brevo → SMTP & API → SMTP tab → copy host/port/login/password
3. Install Docker Desktop
4. Edit `third_party/listmonk/config.toml` with your SMTP credentials
5. Run: `cd third_party/listmonk && docker-compose up -d`
6. Open http://localhost:9000 → admin / admin (change password)
7. Settings → SMTP → test connection
8. Run: `py setup_traffic_keys.py` → enter listmonk admin credentials
9. Bot sends weekly digest automatically every Sunday

### Config files:
- `third_party/listmonk/docker-compose.yml`
- `third_party/listmonk/config.toml` (copy from .example)

### Status: ⏳ WAITING FOR DOCKER DESKTOP + BREVO SMTP

---

## TOOL 6: github-action-feed-to-social-media (Multi-Platform)
**GitHub:** https://github.com/lwojcik/github-action-feed-to-social-media ★150
**Type:** GitHub Action (free)
**Platforms:** Mastodon + Bluesky + Discord + Slack simultaneously
**Location:** `.github/workflows/multi-social.yml`

### How it works:
- Runs on every git push (which happens on every bot cycle)
- Reads latest RSS item from the hub feed
- Posts to all configured platforms in one action

### Setup steps:
1. Add platform credentials as GitHub secrets (see setup guide)
2. Workflow already created in repo — auto-activates when secrets are added

### Status: ⏳ WAITING FOR PLATFORM ACCOUNTS + GITHUB SECRETS

---

## TOOL 7: Skywrite (Bluesky RSS Bot — backup)
**GitHub:** https://github.com/Blooym/skywrite
**Type:** Python binary (runs as background process)
**Platform:** Bluesky
**Location:** `third_party/skywrite/`

### How it works:
- Backup to blueskyfeedbot GitHub Action
- Runs locally, checks RSS feeds every 15 minutes
- Posts new items to Bluesky with deduplication

### Setup steps:
1. Same Bluesky account as Tool 3
2. Edit `third_party/skywrite/config.toml` with handle + app password + RSS URLs
3. Run `START_SKYWRITE.bat` — runs in background

### Status: ⏳ WAITING FOR BLUESKY ACCOUNT (same as Tool 3)

---

## TOOL 8: PinterestBulkPostBot
**GitHub:** https://github.com/SoCloseSociety/PinterestBulkPostBot
**Type:** Python + Selenium (runs on schedule)
**Platform:** Pinterest (traffic compounds for months)
**Location:** `third_party/pinterest-bot/`

### How it works:
- `generate_csv.py` reads your RSS feeds and creates a pin CSV automatically
- CSV has: image URL, title, description, link, board name per post
- PinterestBulkPostBot reads the CSV and creates all pins via Selenium
- Run weekly — each week's posts become pins that drive traffic for months

### Setup steps:
1. Create Pinterest business account
2. Create 5 boards (one per niche)
3. Install Chrome + ChromeDriver (already needed for Selenium)
4. Edit `third_party/pinterest-bot/credentials.json` with Pinterest login
5. Run: `py third_party/pinterest-bot/generate_csv.py` → creates pins.csv
6. Run: `py third_party/pinterest-bot/run.py` → pins all posts

### Status: ✅ CAN RUN NOW (generate_csv.py ready — just needs Pinterest login)

---

## INDEXNOW GITHUB ACTION (Bonus layer)
**GitHub:** https://github.com/bojieyang/indexnow-action ★200
**Type:** GitHub Action (free)
**Platforms:** Bing + Yandex + DuckDuckGo
**Location:** `.github/workflows/indexnow.yml`

### How it works:
- Fires on every git push to main branch (every bot cycle)
- Submits all new/changed URLs to IndexNow automatically
- Adds a second indexing layer on top of the existing Python IndexNow module

### Setup steps:
- None — IndexNow key already exists in repo
- Workflow already created — active immediately

### Status: ✅ ACTIVE (no accounts needed)

---

## QUICK REFERENCE — What You Need to Create

| What | Where | Time | Blocks |
|------|--------|------|--------|
| Docker Desktop | docker.com/products/docker-desktop/ | 10 min install | Postiz, MonitoRSS, listmonk |
| Telegram bot token + 5 channels | Telegram → @BotFather | 10 min | Tool 2 |
| Bluesky account + app password | bsky.app | 2 min | Tools 3, 7 |
| Discord bot token + channels | discord.com/developers | 10 min | Tool 4 |
| Brevo SMTP (free) | brevo.com | 5 min | Tool 5 |
| Pinterest business account | pinterest.com | 5 min | Tool 8 |
| Mastodon account + token | mastodon.social | 5 min | Tool 6 |

**Total setup time once you have accounts: ~1 hour**
**Total new daily traffic when fully running: +500-2,000 visits/day**

---

## FILE STRUCTURE

```
BlogBot/
├── third_party/
│   ├── postiz/
│   │   ├── docker-compose.yml
│   │   ├── .env.example
│   │   └── README.md
│   ├── rss-to-telegram/
│   │   ├── (cloned BoKKeR repo files)
│   │   ├── config.ini.example
│   │   └── START_TELEGRAM_BOT.bat
│   ├── monitorrss/
│   │   ├── docker-compose.yml
│   │   ├── config.json.example
│   │   └── README.md
│   ├── listmonk/
│   │   ├── docker-compose.yml
│   │   ├── config.toml.example
│   │   └── README.md
│   ├── skywrite/
│   │   ├── config.toml.example
│   │   └── START_SKYWRITE.bat
│   └── pinterest-bot/
│       ├── (cloned PinterestBulkPostBot files)
│       ├── generate_csv.py  ← our addition
│       ├── credentials.json.example
│       └── README.md
├── .github/
│   └── workflows/
│       ├── indexnow.yml        ← ✅ active now
│       ├── bluesky-rss.yml     ← waits for secrets
│       └── multi-social.yml    ← waits for secrets
├── modules/
│   └── rss_generator.py        ← new module
└── claude_code/
    ├── TRAFFIC_TOOLS.md        ← this file
    └── SETUP_ACCOUNTS.md       ← step-by-step account guide
```

---
*Updated: SESSION-038 — 2026-04-23*
*Next update: after user provides account credentials*
