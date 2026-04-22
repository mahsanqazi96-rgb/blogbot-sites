# BlogBot — SETUP_ACCOUNTS.md
## Step-by-Step: Create All Required Accounts
*For SESSION-038 Traffic Tools Integration*

---

Complete these in order. Each one takes 2-10 minutes.
When done, tell Claude the credentials and the tool activates automatically.

---

## STEP 1: Docker Desktop (Required for 3 tools)
**Time:** 10 minutes (download + install)
**Blocks:** Postiz, MonitoRSS, listmonk

1. Go to: https://www.docker.com/products/docker-desktop/
2. Click "Download for Windows"
3. Run the installer (default settings)
4. Restart your computer when prompted
5. Open Docker Desktop — wait for it to say "Docker Desktop is running"
6. Tell Claude: "Docker is installed and running"

---

## STEP 2: Telegram Bot + 5 Channels (RSS-to-Telegram)
**Time:** 10 minutes
**Blocks:** Tool 2

### Create the bot:
1. Open Telegram app on your phone or PC
2. Search for: **@BotFather**
3. Type: `/newbot`
4. Name: `TopicPulse Bot`
5. Username: `topicpulse_updates_bot` (or any available name ending in _bot)
6. BotFather sends you a token like: `7123456789:AAF...long string...`
7. **Copy this token** — this is your BOT TOKEN

### Create 5 channels:
1. In Telegram: tap the pencil icon → "New Channel"
2. Create these 5 channels:
   - Name: `TopicPulse Tech` → username: `@topicpulse_tech`
   - Name: `TopicPulse Crypto` → username: `@topicpulse_crypto`
   - Name: `TopicPulse Finance` → username: `@topicpulse_finance`
   - Name: `TopicPulse Health` → username: `@topicpulse_health`
   - Name: `TopicPulse Viral` → username: `@topicpulse_viral`
3. For each channel: Settings → Administrators → Add your bot as admin

### Tell Claude:
```
Telegram bot token: [your token]
Tech channel: @topicpulse_tech
Crypto channel: @topicpulse_crypto
Finance channel: @topicpulse_finance
Health channel: @topicpulse_health
Entertainment channel: @topicpulse_viral
```

---

## STEP 3: Bluesky Account (blueskyfeedbot + Skywrite)
**Time:** 2 minutes
**Blocks:** Tools 3, 7

1. Go to: https://bsky.app
2. Click "Sign up"
3. Use any email + choose a handle like `topicpulse.bsky.social`
4. After signing in: Settings → Privacy and Security → App Passwords
5. Click "Add App Password" → name it `BlogBot`
6. Copy the generated password (looks like: `xxxx-xxxx-xxxx-xxxx`)

### Tell Claude:
```
Bluesky handle: topicpulse.bsky.social
Bluesky app password: xxxx-xxxx-xxxx-xxxx
```

---

## STEP 4: Discord Bot + Server (MonitoRSS)
**Time:** 10 minutes
**Blocks:** Tool 4

### Create the bot:
1. Go to: https://discord.com/developers/applications
2. Click "New Application" → name: `TopicPulse`
3. Left sidebar → "Bot" → "Add Bot" → confirm
4. Under Token: click "Reset Token" → copy the token
5. Under Privileged Gateway Intents: turn ON "Message Content Intent"

### Add bot to a server:
1. Left sidebar → "OAuth2" → "URL Generator"
2. Scopes: check "bot"
3. Bot permissions: check "Send Messages", "Embed Links", "Read Message History"
4. Copy the generated URL → open in browser → select your server → Authorize

### Create Discord server (if you don't have one):
1. Open Discord → click + icon → "Create My Own" → "For me and my friends"
2. Name it "TopicPulse Network"
3. Create channels: #tech-news, #crypto-news, #finance-news, #health-news, #viral-news
4. Right-click each channel → "Copy Channel ID" (enable Developer Mode in User Settings first)

### Tell Claude:
```
Discord bot token: [your token]
Discord server: TopicPulse Network
tech channel ID: [ID]
crypto channel ID: [ID]
finance channel ID: [ID]
health channel ID: [ID]
entertainment channel ID: [ID]
```

### EASIER OPTION — Discord Webhook (for FeedCord, no bot needed):
If you just want RSS posts in a Discord channel without a full bot:
1. Open any Discord channel → Edit Channel → Integrations → Webhooks
2. New Webhook → copy the URL (looks like: https://discord.com/api/webhooks/...)
3. Tell Claude: `Discord webhook URL: [URL]`

---

## STEP 4b: Reddit Accounts (start aging NOW)
**Time:** 5 minutes to create, 30 days to age
**Blocks:** Reddit publisher (Tool 4)
**Note:** Create these accounts TODAY even if you don't use them yet — they need karma before Reddit allows link posting

1. Create 2-3 Reddit accounts with different emails
2. On each account: browse Reddit daily, upvote/comment on posts in your niches
3. After 30 days with some karma → tell Claude the API credentials
4. Go to https://www.reddit.com/prefs/apps → Create App (script type)
5. Copy client_id + client_secret + username + password

---

## STEP 5: Brevo SMTP (Free email for listmonk)
**Time:** 5 minutes
**Blocks:** Tool 5

1. Go to: https://www.brevo.com
2. Click "Sign up free"
3. Use any email → verify it
4. Once in: go to the top menu → "Transactional" → "Settings" → "SMTP & API"
5. Click the "SMTP" tab
6. You'll see:
   - SMTP server: `smtp-relay.brevo.com`
   - Port: `587`
   - Login: your email address
   - Password: a long generated SMTP key

### Tell Claude:
```
Brevo SMTP host: smtp-relay.brevo.com
Brevo SMTP port: 587
Brevo SMTP login: [your email]
Brevo SMTP password: [the SMTP key]
```

---

## STEP 6: Mastodon Account (Multi-platform poster)
**Time:** 3 minutes
**Blocks:** Tool 6

1. Go to: https://mastodon.social/auth/sign_up
2. Sign up with any email + choose username like `topicpulse`
3. Verify your email
4. Once logged in: Settings → Development → "New application"
5. Name: `BlogBot` → keep default scopes → Submit
6. Click on your new app → copy "Your access token"

### Tell Claude:
```
Mastodon instance: https://mastodon.social
Mastodon access token: [your token]
```

---

## STEP 7: Pinterest Business Account (PinterestBulkPostBot)
**Time:** 5 minutes
**Blocks:** Tool 8

1. Go to: https://pinterest.com → sign up or log in
2. Convert to business: pinterest.com/business/convert/
3. Create 5 boards:
   - "Tech & Gadgets News"
   - "Crypto & Blockchain"
   - "Finance & Investing"
   - "Health & Wellness"
   - "Entertainment & Viral"
4. Go to pinterest.com/settings → Security → note your email + password

### Tell Claude:
```
Pinterest email: [your email]
Pinterest password: [your password]
Pinterest boards: Tech=Tech & Gadgets News, Crypto=Crypto & Blockchain, Finance=Finance & Investing, Health=Health & Wellness, Entertainment=Entertainment & Viral
```

---

## AFTER ALL ACCOUNTS ARE CREATED

Run `py setup_traffic_keys.py` to enter all credentials at once.
Everything activates automatically from the next bot cycle.

---

## QUICK STATUS TRACKER

| Account | Blocks | Done? | Claude notified? |
|---------|--------|-------|-----------------|
| Docker Desktop | Postiz, MonitoRSS, FeedCord, listmonk | [ ] | [ ] |
| Telegram bot token + 5 channels | Telegram publisher, RSS-to-Telegram | [ ] | [ ] |
| Bluesky handle + app password | Bluesky publisher, blueskyfeedbot, Skywrite | [ ] | [ ] |
| Discord bot token + server | MonitoRSS | [ ] | [ ] |
| Discord webhook URL | FeedCord (easier option) | [ ] | [ ] |
| Brevo SMTP credentials | listmonk | [ ] | [ ] |
| Mastodon instance + token | Mastodon publisher, multi-social action | [ ] | [ ] |
| Pinterest login + 5 boards | PinterestBulkPostBot | [ ] | [ ] |
| Reddit accounts (aged 30 days) | Reddit publisher | [ ] | [ ] |
| — NO ACCOUNT NEEDED — | Nostr publisher ✅ | auto | auto |
| — NO ACCOUNT NEEDED — | pywebpush ✅ | auto | auto |
| — NO ACCOUNT NEEDED — | indexnow-action ✅ | auto | auto |

**Tools that activate with zero setup (being built now):**
- Nostr publisher → fires on crypto/finance posts immediately
- pywebpush → subscribe button added to all blog templates immediately
- indexnow GitHub Action → fires on every git push immediately

---
*Created: SESSION-038 — 2026-04-23*
