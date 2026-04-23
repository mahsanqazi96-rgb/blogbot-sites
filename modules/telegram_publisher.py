"""
BlogBot — telegram_publisher.py
Publishes blog post announcements to Telegram channels, one channel per niche.
Uses python-telegram-bot v20+ (async), wrapped with asyncio.run() for sync callers.
"""

import asyncio
import logging
import sys
from pathlib import Path
from typing import Optional

# ── BASE_DIR bootstrap ────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent.parent.resolve()
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

LOGS_DIR = BASE_DIR / "logs"
LOGS_DIR.mkdir(parents=True, exist_ok=True)

# ── Logging ───────────────────────────────────────────────────────────────────
_log = logging.getLogger("telegram_publisher")
_log.setLevel(logging.INFO)
if not _log.handlers:
    _fh = logging.FileHandler(LOGS_DIR / "activity.log", encoding="utf-8")
    _fh.setFormatter(
        logging.Formatter("%(asctime)s [TELEGRAM] %(levelname)s %(message)s")
    )
    _log.addHandler(_fh)

# ── Niche → config key mapping ────────────────────────────────────────────────
_NICHE_CONFIG_KEYS = {
    "tech":          "telegram_channel_tech",
    "technology":    "telegram_channel_tech",
    "gadgets":       "telegram_channel_tech",
    "crypto":        "telegram_channel_crypto",
    "blockchain":    "telegram_channel_crypto",
    "finance":       "telegram_channel_finance",
    "investing":     "telegram_channel_finance",
    "health":        "telegram_channel_health",
    "weight_loss":   "telegram_channel_health",
    "fitness":       "telegram_channel_health",
    "entertainment": "telegram_channel_entertainment",
    "celebrity":     "telegram_channel_entertainment",
    "viral":         "telegram_channel_entertainment",
}

_FALLBACK_CONFIG_KEY = "telegram_channel_entertainment"


# ── TelegramPublisher ─────────────────────────────────────────────────────────
class TelegramPublisher:
    """
    Sends formatted post announcements to a Telegram channel.

    Parameters
    ----------
    token   : Bot token from @BotFather
    channel : Channel username (e.g. "@myblogchannel") or numeric chat_id
    """

    def __init__(self, token: str, channel: str) -> None:
        self.token   = token.strip()
        self.channel = channel.strip()

    def publish(self, title: str, url: str, excerpt: str = "") -> bool:
        """
        Send a post announcement message to the configured Telegram channel.

        Message format:
            📰 {title}

            {excerpt}          ← only included when non-empty

            🔗 {url}

        Returns True on success, False on any failure.
        """
        try:
            return asyncio.run(self._async_send(title, url, excerpt))
        except RuntimeError:
            # asyncio.run() raises RuntimeError if there's already a running loop
            # (e.g. inside Jupyter or certain frameworks). Fall back to get_event_loop.
            try:
                loop = asyncio.get_event_loop()
                return loop.run_until_complete(self._async_send(title, url, excerpt))
            except Exception as exc:
                _log.error(f"Telegram: event loop fallback failed: {exc}")
                return False
        except Exception as exc:
            _log.error(f"Telegram: unexpected error in publish(): {exc}")
            return False

    async def _async_send(self, title: str, url: str, excerpt: str) -> bool:
        """Async implementation — builds the message and calls the Bot API."""
        try:
            from telegram import Bot
        except ImportError:
            _log.error("python-telegram-bot not installed — run: pip install python-telegram-bot")
            return False

        parts = [f"📰 <b>{title.strip()}</b>"]
        if excerpt and excerpt.strip():
            parts.append(excerpt.strip())
        parts.append(f"🔗 {url.strip()}")

        msg = "\n\n".join(parts)

        try:
            bot = Bot(token=self.token)
            await bot.send_message(
                chat_id=self.channel,
                text=msg,
                parse_mode="HTML",
                disable_web_page_preview=False,
            )
            _log.info(
                f"Telegram: sent to {self.channel!r} — title={title!r}"
            )
            return True
        except Exception as exc:
            _log.warning(f"Telegram: send_message failed for {self.channel!r}: {exc}")
            return False


# ── Config helper ─────────────────────────────────────────────────────────────
def _cfg_get(key: str) -> str:
    try:
        from modules.config_manager import get as cfg_get
        return cfg_get(key) or ""
    except Exception:
        try:
            from config_manager import get as cfg_get
            return cfg_get(key) or ""
        except Exception:
            return ""


# ── Factory ───────────────────────────────────────────────────────────────────
def make_telegram_from_config(niche: str) -> Optional[TelegramPublisher]:
    """
    Build a TelegramPublisher for the given niche from config.

    Reads:
        telegram_bot_token          — Bot token from @BotFather
        telegram_channel_tech       — @channel or chat_id for tech posts
        telegram_channel_crypto     — @channel for crypto/blockchain
        telegram_channel_finance    — @channel for finance/investing
        telegram_channel_health     — @channel for health/weight_loss
        telegram_channel_entertainment — @channel for entertainment/celebrity

    Returns None silently if token or the niche channel is not configured.
    """
    token = _cfg_get("telegram_bot_token")
    if not token:
        _log.debug("Telegram: telegram_bot_token not configured — skipping")
        return None

    niche_key  = niche.lower().replace("-", "_").replace(" ", "_")
    config_key = _NICHE_CONFIG_KEYS.get(niche_key, _FALLBACK_CONFIG_KEY)
    channel    = _cfg_get(config_key)

    if not channel:
        _log.debug(
            f"Telegram: no channel configured for niche={niche!r} "
            f"(config key: {config_key!r}) — skipping"
        )
        return None

    return TelegramPublisher(token=token, channel=channel)


# ── Top-level entry point ─────────────────────────────────────────────────────
def publish_to_telegram(
    title:   str,
    url:     str,
    niche:   str,
    excerpt: str = "",
) -> bool:
    """
    Publish a blog post announcement to the Telegram channel for the given niche.

    Called by bot_loop.py after a post is successfully published to
    Cloudflare Pages.  Never raises — any failure returns False so the
    bot continues without interruption.

    Returns True if the message was sent, False otherwise.
    """
    publisher = make_telegram_from_config(niche)
    if publisher is None:
        return False

    try:
        return publisher.publish(title=title, url=url, excerpt=excerpt)
    except Exception as exc:
        _log.error(f"publish_to_telegram: unexpected error: {exc}")
        return False


# ── Self-test ─────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("telegram_publisher self-test")
    print("=" * 40)

    try:
        from telegram import Bot  # noqa: F401
        print("[OK] python-telegram-bot imports correctly")
    except ImportError as exc:
        print(f"[FAIL] python-telegram-bot import error: {exc}")
        print("       Run: pip install python-telegram-bot")
        sys.exit(1)

    # Unconfigured — should return False silently
    result = publish_to_telegram(
        title="Test Post",
        url="https://example.pages.dev/posts/test.html",
        niche="tech",
        excerpt="A short excerpt about the test post.",
    )
    print(
        f"[{'OK' if result is False else 'FAIL'}] "
        f"publish_to_telegram (unconfigured) returned False: {result is False}"
    )

    # Niche fallback check
    pub = make_telegram_from_config("unknown_niche")
    print(
        f"[OK] Unknown niche returns None from factory: {pub is None}"
    )

    print("=" * 40)
    print("Self-test complete.")
