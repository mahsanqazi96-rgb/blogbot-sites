"""
BlogBot — nostr_publisher.py
Publishes blog post announcements to the Nostr decentralised protocol.
Broadcasts kind-1 text notes to 10 public relays on every post publish.
Especially effective for crypto/finance/tech content.

nostr_sdk version: 0.44.x (Rust-backed via uniffi)
Key pattern: uniffi_set_event_loop() MUST be called before any async nostr_sdk
             operations when running from a synchronous context.
"""

import asyncio
import logging
from pathlib import Path
from typing import List

# ── BASE_DIR bootstrap ────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent.parent.resolve()
LOGS_DIR = BASE_DIR / "logs"
LOGS_DIR.mkdir(parents=True, exist_ok=True)

# ── Logging ───────────────────────────────────────────────────────────────────
_log = logging.getLogger("nostr_publisher")
_log.setLevel(logging.INFO)
if not _log.handlers:
    _fh = logging.FileHandler(LOGS_DIR / "activity.log", encoding="utf-8")
    _fh.setFormatter(
        logging.Formatter("%(asctime)s [NOSTR] %(levelname)s %(message)s")
    )
    _log.addHandler(_fh)

# ── Constants ─────────────────────────────────────────────────────────────────

# Niches that benefit from Nostr distribution (crypto-native community)
_NOSTR_NICHES = {"crypto", "blockchain", "finance", "investing", "tech"}

# 10 well-connected public relays (no auth required)
_RELAYS: List[str] = [
    "wss://relay.damus.io",
    "wss://relay.nostr.band",
    "wss://nos.lol",
    "wss://relay.snort.social",
    "wss://nostr.wine",
    "wss://relay.primal.net",
    "wss://purplepag.es",
    "wss://relay.nostr.bg",
    "wss://nostr.oxtr.dev",
    "wss://relay.current.fyi",
]

# Seconds to wait for relay connections before sending
_CONNECT_WAIT = 2

# Seconds for the overall publish coroutine (connect + send + disconnect)
_PUBLISH_TIMEOUT = 30


# ── Class ─────────────────────────────────────────────────────────────────────

class NostrPublisher:
    """
    Publishes blog post announcements to the Nostr decentralised network.

    Uses a persistent keypair stored in config so every post is attributed
    to the same Nostr identity. Keypair is auto-generated on first use.
    """

    def __init__(self, private_key_hex: str = "") -> None:
        """
        Initialise with an optional private key hex string.

        If private_key_hex is empty, _get_or_create_keys() will load one
        from config or generate and save a fresh one.
        """
        self._private_key_hex = private_key_hex
        self._keys = None  # nostr_sdk Keys object, loaded lazily
        self._get_or_create_keys()

    # ── Key management ────────────────────────────────────────────────────────

    def _get_or_create_keys(self) -> None:
        """
        Load an existing keypair from config, or generate a new one and save it.

        Priority:
          1. private_key_hex passed to __init__
          2. 'nostr_private_key_hex' in config
          3. Freshly generated keypair (saved to config for future runs)
        """
        try:
            from nostr_sdk import Keys, SecretKey
        except ImportError:
            _log.error("nostr_sdk not installed — run: pip install nostr-sdk")
            return

        # 1. Use the key passed in directly
        if self._private_key_hex:
            try:
                sk = SecretKey.parse(self._private_key_hex)
                self._keys = Keys(sk)
                _log.debug("Nostr: loaded keypair from constructor argument")
                return
            except Exception as exc:
                _log.warning(f"Nostr: provided private_key_hex invalid ({exc}), will load/generate")

        # 2. Try loading from config
        cfg_hex = self._cfg_get("nostr_private_key_hex")
        if cfg_hex:
            try:
                sk = SecretKey.parse(cfg_hex)
                self._keys = Keys(sk)
                self._private_key_hex = cfg_hex
                _log.debug("Nostr: loaded keypair from config")
                return
            except Exception as exc:
                _log.warning(f"Nostr: config key invalid ({exc}), generating new keypair")

        # 3. Generate a fresh keypair and persist it
        try:
            self._keys = Keys.generate()
            new_hex = self._keys.secret_key().to_hex()
            self._private_key_hex = new_hex
            self._cfg_set("nostr_private_key_hex", new_hex)
            pubkey = self._keys.public_key().to_hex()
            _log.info(f"Nostr: generated new keypair. pubkey={pubkey}")
        except Exception as exc:
            _log.error(f"Nostr: keypair generation failed: {exc}")
            self._keys = None

    # ── Config helpers (handle missing config_manager gracefully) ─────────────

    @staticmethod
    def _cfg_get(key: str) -> str:
        try:
            try:
                from modules.config_manager import get as cfg_get
            except ImportError:
                from config_manager import get as cfg_get
            return cfg_get(key) or ""
        except Exception:
            return ""

    @staticmethod
    def _cfg_set(key: str, value: str) -> None:
        try:
            try:
                from modules.config_manager import set_value
            except ImportError:
                from config_manager import set_value
            set_value(key, value)
        except Exception as exc:
            _log.warning(f"Nostr: could not persist key to config: {exc}")

    # ── Publish ───────────────────────────────────────────────────────────────

    def publish(
        self,
        title: str,
        url: str,
        niche: str,
        tags: List[str] = [],
    ) -> bool:
        """
        Broadcast a kind-1 text note to all configured relays.

        Note format:
            {title}

            {url}

            #{tag1} #{tag2} #{niche}

        Returns True if at least one relay accepted the event.
        Never raises — all exceptions are caught and logged.
        """
        if self._keys is None:
            _log.error("Nostr: no valid keypair — cannot publish")
            return False

        # Build the hashtag block (niche always included)
        all_tags: List[str] = list(tags)
        if niche and niche not in all_tags:
            all_tags.append(niche)

        hashtags = " ".join(f"#{t.strip().replace(' ', '_')}" for t in all_tags if t.strip())
        content_parts = [title.strip(), url.strip()]
        if hashtags:
            content_parts.append(hashtags)
        content = "\n\n".join(content_parts)

        try:
            return self._run_publish(content)
        except Exception as exc:
            _log.error(f"Nostr: unexpected error in publish(): {exc}")
            return False

    def _run_publish(self, content: str) -> bool:
        """
        Sync wrapper: creates a fresh event loop, sets it for uniffi, runs the
        async coroutine, then closes the loop.

        uniffi_set_event_loop() is REQUIRED when nostr_sdk async callbacks
        need to interact with a Python event loop created outside asyncio.run().
        """
        from nostr_sdk import uniffi_set_event_loop

        loop = asyncio.new_event_loop()
        # Tell nostr_sdk's Rust callbacks which loop to use for Python futures
        uniffi_set_event_loop(loop)
        try:
            return loop.run_until_complete(
                asyncio.wait_for(self._async_publish(content), timeout=_PUBLISH_TIMEOUT)
            )
        except asyncio.TimeoutError:
            _log.warning(f"Nostr: publish timed out after {_PUBLISH_TIMEOUT}s")
            return False
        except Exception as exc:
            _log.error(f"Nostr: _run_publish error: {exc}")
            return False
        finally:
            try:
                loop.close()
            except Exception:
                pass

    async def _async_publish(self, content: str) -> bool:
        """
        Core async publish: adds all relays, connects, sends the note,
        disconnects, and returns True if at least one relay accepted.
        """
        from nostr_sdk import Client, EventBuilder, NostrSigner, RelayUrl

        signer = NostrSigner.keys(self._keys)
        client = Client(signer)

        # Register all relays (skip any with invalid URLs)
        added = 0
        for relay_str in _RELAYS:
            try:
                relay_url = RelayUrl.parse(relay_str)
                ok = await client.add_relay(relay_url)
                if ok:
                    added += 1
            except Exception as exc:
                _log.debug(f"Nostr: could not add relay {relay_str}: {exc}")

        if added == 0:
            _log.error("Nostr: no relays could be added — aborting")
            return False

        # Connect to all registered relays
        await client.connect()

        # Brief pause to allow WebSocket handshakes to complete
        await asyncio.sleep(_CONNECT_WAIT)

        # Build and send the kind-1 text note
        builder = EventBuilder.text_note(content)
        try:
            output = await client.send_event_builder(builder)
            success_count = len(output.success)
            failed_count = len(output.failed)
            event_id = output.id.to_hex() if output.id else "unknown"

            if success_count > 0:
                _log.info(
                    f"Nostr: event published id={event_id[:16]}... "
                    f"accepted={success_count}/{added} relays "
                    f"failed={failed_count}"
                )
            else:
                _log.warning(
                    f"Nostr: event id={event_id[:16]}... rejected by all "
                    f"{added} relays. failures={dict(output.failed)}"
                )

            return success_count > 0

        except Exception as exc:
            _log.error(f"Nostr: send_event_builder error: {exc}")
            return False

        finally:
            try:
                await client.disconnect()
            except Exception:
                pass


# ── Top-level helper ──────────────────────────────────────────────────────────

def publish_to_nostr(
    title: str,
    url: str,
    niche: str,
    keywords: List[str] = [],
) -> bool:
    """
    Publish a blog post announcement to Nostr if the niche is relevant.

    Skips silently for health/entertainment niches — their audiences are not
    on Nostr in meaningful numbers.

    Returns True if at least one relay accepted the note.
    Returns False (without error) for non-Nostr niches.
    """
    niche_lower = niche.lower().strip()

    if niche_lower not in _NOSTR_NICHES:
        _log.debug(f"Nostr: skipping niche '{niche}' — not in Nostr target set")
        return False

    try:
        publisher = NostrPublisher()  # loads/generates key from config
        return publisher.publish(
            title=title,
            url=url,
            niche=niche_lower,
            tags=keywords,
        )
    except Exception as exc:
        _log.error(f"publish_to_nostr: unexpected error: {exc}")
        return False


# ── Self-test ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(BASE_DIR))

    print("nostr_publisher self-test")
    print("=" * 40)

    # 1. Verify import
    try:
        from nostr_sdk import Keys, Client, EventBuilder, NostrSigner, Kind  # noqa: F401
        print("[OK] nostr_sdk imports correctly")
        print(f"     Keys, Client, EventBuilder, NostrSigner, Kind all available")
    except ImportError as e:
        print(f"[FAIL] nostr_sdk import error: {e}")
        print("       Run: pip install nostr-sdk")
        sys.exit(1)

    # 2. Key generation
    try:
        publisher = NostrPublisher()
        if publisher._keys is not None:
            pubkey_hex = publisher._keys.public_key().to_hex()
            sk_hex = publisher._keys.secret_key().to_hex()
            print(f"[OK] Keypair ready")
            print(f"     pubkey : {pubkey_hex}")
            print(f"     seckey : {sk_hex[:8]}...{sk_hex[-8:]} (truncated)")
        else:
            print("[FAIL] NostrPublisher created but _keys is None")
            sys.exit(1)
    except Exception as e:
        print(f"[FAIL] NostrPublisher init error: {e}")
        sys.exit(1)

    # 3. Niche filter check
    skip_result = publish_to_nostr("Test", "https://example.com", "health")
    print(f"[OK] Niche filter works — health niche skipped: {skip_result is False}")

    # 4. Live publish test (optional — requires network)
    run_live = "--live" in sys.argv
    if run_live:
        print("\n[LIVE] Publishing test note to Nostr relays...")
        ok = publisher.publish(
            title="BlogBot Nostr Test",
            url="https://blogbot.example.com/test",
            niche="tech",
            tags=["blogbot", "test", "automation"],
        )
        print(f"[{'OK' if ok else 'FAIL'}] Live publish result: {ok}")
    else:
        print("\n[SKIP] Live relay test — pass --live to run it")
        print("       Example: python nostr_publisher.py --live")

    print("=" * 40)
    print("Self-test complete.")
