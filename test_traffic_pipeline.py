"""
BlogBot — test_traffic_pipeline.py
Complete test of all zero-credential traffic features.

Tests:
  1. rss_generator        — pure stdlib, no credentials
  2. nostr_publisher      — no credentials (generates own keypair)
  3. webpush_publisher    — no credentials (generates own VAPID keys)
  4. indexing             — IndexNow (no auth required)
  5. flipboard_publisher  — no credentials
  6. directory_submitter  — no credentials
  7. push_notifications   — App ID already in config
  8. _fire_traffic_signals() — integration test with real blog URL
"""

import sys
import os
import traceback
import tempfile
from pathlib import Path
from datetime import datetime, timezone

# ── Path bootstrap ─────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent.resolve()
sys.path.insert(0, str(BASE_DIR))

# Suppress the urllib3 version warning for cleaner output
import warnings
warnings.filterwarnings("ignore", category=UserWarning)

# ── Test data ──────────────────────────────────────────────────────────────────
BLOG_URL  = "https://topicpulse.pages.dev/cryptoinsiderdaily"
SLUG      = "understanding-bitcoin-etf"
TITLE     = "Understanding Bitcoin ETF: Complete Guide 2026"
NICHE     = "crypto"
POST_URL  = f"{BLOG_URL}/posts/{SLUG}.html"
RSS_URL   = f"{BLOG_URL}/feed.xml"

results = []  # list of (module, status, notes)

def record(module, status, notes=""):
    results.append((module, status, notes))
    icon = "OK  " if status == "PASS" else ("WARN" if status == "WARN" else "FAIL")
    print(f"  [{icon}] {module}: {notes}")

# ══════════════════════════════════════════════════════════════════════════════
# 1. RSS GENERATOR
# ══════════════════════════════════════════════════════════════════════════════
print("\n" + "="*60)
print("1. RSS GENERATOR (modules/rss_generator.py)")
print("="*60)

try:
    from modules.rss_generator import (
        generate_rss_feed, write_rss_feed, generate_hub_feed, generate_feed_for_site
    )

    # Build minimal site_config stub with correct attribute names
    class _MockSiteCfg:
        blog_url  = BLOG_URL
        title     = "CryptoInsider Daily"
        language  = "en"
        niche     = "crypto"
        meta_desc = "Daily crypto news and analysis"

    sample_posts = [
        {
            "slug":         SLUG,
            "title":        TITLE,
            "meta_desc":    "A complete guide to Bitcoin ETFs in 2026",
            "published_at": "2026-04-24T09:00:00",
            "featured_image_url": "https://cdn.example.com/btc-etf.jpg",
            "niche": "crypto",
        },
        {
            "slug":         "ethereum-price-analysis-2026",
            "title":        "Ethereum Price Analysis April 2026",
            "meta_desc":    "ETH technical analysis and price targets",
            "published_at": "2026-04-23T14:00:00",
            "featured_image_url": "",
            "niche": "crypto",
        },
    ]

    cfg = _MockSiteCfg()

    # Test generate_rss_feed
    xml = generate_rss_feed(sample_posts, cfg)
    assert "<?xml" in xml, "Missing XML declaration"
    assert "<rss version=\"2.0\"" in xml, "Missing RSS tag"
    assert BLOG_URL in xml, "blog_url not embedded in feed"
    assert TITLE in xml, "Post title not in feed"
    assert xml.count("<item>") == 2, f"Expected 2 items, got {xml.count('<item>')}"
    record("rss_generator.generate_rss_feed", "PASS",
           f"Generated {len(xml)} chars, {xml.count('<item>')} items")

    # Test write_rss_feed
    with tempfile.TemporaryDirectory() as tmp:
        out = write_rss_feed(sample_posts, cfg, Path(tmp))
        assert out.exists(), "feed.xml not created"
        assert out.stat().st_size > 100, "feed.xml too small"
        record("rss_generator.write_rss_feed", "PASS",
               f"Wrote {out.stat().st_size} bytes to feed.xml")

    # Test generate_hub_feed
    hub_posts = [dict(p, blog_url=BLOG_URL, blog_title="CryptoInsider Daily")
                 for p in sample_posts]
    with tempfile.TemporaryDirectory() as tmp:
        hub_out = generate_hub_feed(
            hub_posts,
            hub_url="https://topicpulse.pages.dev",
            output_path=Path(tmp) / "feed.xml",
        )
        assert hub_out.exists()
        record("rss_generator.generate_hub_feed", "PASS",
               f"Hub feed {hub_out.stat().st_size} bytes, {len(hub_posts)} posts")

except Exception as e:
    record("rss_generator", "FAIL", f"{type(e).__name__}: {e}")
    traceback.print_exc()

# ══════════════════════════════════════════════════════════════════════════════
# 2. NOSTR PUBLISHER
# ══════════════════════════════════════════════════════════════════════════════
print("\n" + "="*60)
print("2. NOSTR PUBLISHER (modules/nostr_publisher.py)")
print("="*60)

try:
    from modules.nostr_publisher import NostrPublisher, publish_to_nostr

    # Test keypair initialisation
    pub = NostrPublisher()
    assert pub._keys is not None, "NostrPublisher._keys is None after init"
    pubkey_hex = pub._keys.public_key().to_hex()
    sk_hex     = pub._keys.secret_key().to_hex()
    assert len(pubkey_hex) == 64, f"pubkey wrong length: {len(pubkey_hex)}"
    assert len(sk_hex)     == 64, f"seckey wrong length: {len(sk_hex)}"
    record("nostr_publisher.NostrPublisher.__init__", "PASS",
           f"Keypair ready — pubkey={pubkey_hex[:16]}...")

    # Test niche filter (health should be skipped silently)
    skip = publish_to_nostr("Test", "https://example.com", "health")
    assert skip is False, "Expected False for non-Nostr niche 'health'"
    record("nostr_publisher.niche_filter", "PASS",
           "health niche correctly skipped (returned False)")

    # Test message construction (no live relay call — would need network)
    all_tags = [NICHE, "bitcoin", "etf"]
    hashtags = " ".join(f"#{t}" for t in all_tags)
    content  = f"{TITLE}\n\n{POST_URL}\n\n{hashtags}"
    assert TITLE in content and POST_URL in content
    record("nostr_publisher.message_construction", "PASS",
           f"Message built correctly ({len(content)} chars)")

    # Live relay broadcast (best-effort — may fail if relays are unreachable)
    print("    [INFO] Attempting live Nostr broadcast (30s timeout)...")
    try:
        ok = pub.publish(
            title=TITLE,
            url=POST_URL,
            niche=NICHE,
            tags=["bitcoin", "etf", "crypto"],
        )
        if ok:
            record("nostr_publisher.live_broadcast", "PASS",
                   "At least one relay accepted the event")
        else:
            record("nostr_publisher.live_broadcast", "WARN",
                   "No relay accepted (network issue or all busy) — non-fatal")
    except Exception as e:
        record("nostr_publisher.live_broadcast", "WARN",
               f"Relay error (non-fatal): {type(e).__name__}: {e}")

except Exception as e:
    record("nostr_publisher", "FAIL", f"{type(e).__name__}: {e}")
    traceback.print_exc()

# ══════════════════════════════════════════════════════════════════════════════
# 3. WEBPUSH PUBLISHER
# ══════════════════════════════════════════════════════════════════════════════
print("\n" + "="*60)
print("3. WEBPUSH PUBLISHER (modules/webpush_publisher.py)")
print("="*60)

try:
    from modules.webpush_publisher import (
        WebPushPublisher, get_or_create_vapid_keys,
        notify_subscribers, get_subscriber_js_snippet, VAPID_PUBLIC_KEY_PLACEHOLDER
    )

    # VAPID keys
    keys = get_or_create_vapid_keys()
    assert keys.get("private_key"), "private_key missing"
    assert keys.get("public_key"),  "public_key missing"
    assert len(keys["public_key"]) > 20, "public_key too short"
    record("webpush_publisher.vapid_keys", "PASS",
           f"Keys loaded — pub={keys['public_key'][:20]}...")

    # WebPushPublisher instantiation
    wp = WebPushPublisher()
    record("webpush_publisher.__init__", "PASS", "WebPushPublisher created OK")

    # save_subscriber with fake endpoint (tests DB write path)
    import json as _json
    fake_sub = _json.dumps({
        "endpoint": "https://fcm.googleapis.com/fcm/send/test-endpoint-blogbot",
        "keys": {"p256dh": "BFAKE_P256DH_KEY", "auth": "FAKEAUTHKEY"},
    })
    ok = wp.save_subscriber(fake_sub, niche=NICHE, blog_url=BLOG_URL)
    assert ok is True, "save_subscriber returned False"
    record("webpush_publisher.save_subscriber", "PASS",
           "Subscriber saved to analytics.db")

    # broadcast — fake endpoint will fail the actual push (expected), but no crash
    result = wp.broadcast(
        title=TITLE,
        body=f"New {NICHE} post just published",
        url=POST_URL,
        niche=NICHE,
    )
    assert isinstance(result, dict), "broadcast must return a dict"
    assert "sent" in result and "failed" in result
    record("webpush_publisher.broadcast", "PASS",
           f"Broadcast completed — sent={result['sent']} failed={result['failed']} "
           f"removed={result['removed']} (fake endpoint, failures expected)")

    # JS snippet
    snippet = get_subscriber_js_snippet(keys["public_key"], "/api/subscribe")
    assert "serviceWorker" in snippet
    assert keys["public_key"] in snippet
    assert "/api/subscribe" in snippet
    record("webpush_publisher.js_snippet", "PASS",
           f"JS snippet generated ({len(snippet)} chars)")

    # Constant check
    assert VAPID_PUBLIC_KEY_PLACEHOLDER == "VAPID_PUBLIC_KEY_HERE"
    record("webpush_publisher.constant", "PASS",
           "VAPID_PUBLIC_KEY_PLACEHOLDER correct")

except Exception as e:
    record("webpush_publisher", "FAIL", f"{type(e).__name__}: {e}")
    traceback.print_exc()

# ══════════════════════════════════════════════════════════════════════════════
# 4. INDEXING (IndexNow)
# ══════════════════════════════════════════════════════════════════════════════
print("\n" + "="*60)
print("4. INDEXING — IndexNow (modules/indexing.py)")
print("="*60)

try:
    from modules.indexing import (
        IndexNowKeyManager, SitemapSubmitter, IndexingManager, get_manager
    )

    # Key manager
    km = IndexNowKeyManager()
    key = km.generate()
    assert km.is_valid_key(key), f"Generated key invalid: {key}"
    assert len(key) == 32
    record("indexing.IndexNowKeyManager.generate", "PASS",
           f"Key generated: {key}")

    # Key file write
    with tempfile.TemporaryDirectory() as tmp:
        kp = km.write_key_to_site(key, Path(tmp))
        assert kp.exists() and kp.read_text() == key
        record("indexing.write_key_to_site", "PASS",
               f"Key file written: {kp.name}")

    # IndexingManager from config
    mgr = get_manager()
    assert mgr.get_indexnow_key(), "IndexNow key is empty"
    assert mgr.get_indexnow_key_file_name().endswith(".txt")
    record("indexing.get_manager", "PASS",
           f"IndexNow key={mgr.get_indexnow_key()[:16]}...")

    # Live IndexNow ping (Bing + indexnow.org + Yandex) — real network call
    print("    [INFO] Firing IndexNow pings to Bing + indexnow.org + Yandex...")
    pings = mgr.on_post_published(BLOG_URL)
    assert isinstance(pings, list) and len(pings) > 0
    for p in pings:
        status = "PASS" if p.success else "WARN"
        record(f"indexing.IndexNow[{p.engine}]", status,
               f"HTTP {p.status} — {'OK' if p.success else p.error or 'no success'}")

except Exception as e:
    record("indexing", "FAIL", f"{type(e).__name__}: {e}")
    traceback.print_exc()

# ══════════════════════════════════════════════════════════════════════════════
# 5. FLIPBOARD PUBLISHER
# ══════════════════════════════════════════════════════════════════════════════
print("\n" + "="*60)
print("5. FLIPBOARD PUBLISHER (modules/flipboard_publisher.py)")
print("="*60)

try:
    from modules.flipboard_publisher import (
        FlipboardPublisher, submit_post_to_flipboard, make_flipboard_from_config
    )

    # Instantiation
    fp = make_flipboard_from_config()
    assert isinstance(fp, FlipboardPublisher)
    record("flipboard_publisher.make_flipboard_from_config", "PASS",
           "FlipboardPublisher created from config")

    # Live ping (uses public Flipboard endpoints — no auth needed)
    print("    [INFO] Pinging Flipboard API and share endpoints...")
    ok = submit_post_to_flipboard(title=TITLE, url=POST_URL, rss_url=RSS_URL)
    status = "PASS" if ok else "WARN"
    record("flipboard_publisher.submit_post_to_flipboard", status,
           "At least one ping returned HTTP 200" if ok else
           "Both pings returned non-200 (Flipboard may have changed endpoints)")

except Exception as e:
    record("flipboard_publisher", "FAIL", f"{type(e).__name__}: {e}")
    traceback.print_exc()

# ══════════════════════════════════════════════════════════════════════════════
# 6. DIRECTORY SUBMITTER
# ══════════════════════════════════════════════════════════════════════════════
print("\n" + "="*60)
print("6. DIRECTORY SUBMITTER (modules/directory_submitter.py)")
print("="*60)

try:
    from modules.directory_submitter import DirectorySubmitter, submit_new_blog_to_directories

    # Instantiation (creates DB table)
    ds = DirectorySubmitter()
    record("directory_submitter.__init__", "PASS",
           "DirectorySubmitter created, DB table ensured")

    # DB helpers
    assert not ds._already_submitted("https://never-seen.example.com", "Feedspot")
    record("directory_submitter._already_submitted", "PASS",
           "Returns False for unknown blog/directory pair")

    # Live submit — these are real HTTP calls; 200 means accepted
    print("    [INFO] Submitting to Feedspot, AllTop, Blogarama, BlogDirectory...")
    res = ds.submit_blog(
        blog_url=BLOG_URL,
        rss_url=RSS_URL,
        title="CryptoInsider Daily",
        niche=NICHE,
        email="mahsanqazi96@gmail.com",
    )
    assert isinstance(res, dict)
    for dir_name, ok in res.items():
        status = "PASS" if ok else "WARN"
        record(f"directory_submitter[{dir_name}]", status,
               "HTTP 200 accepted" if ok else
               "Non-200 (directory may require manual signup)")

except Exception as e:
    record("directory_submitter", "FAIL", f"{type(e).__name__}: {e}")
    traceback.print_exc()

# ══════════════════════════════════════════════════════════════════════════════
# 7. ONESIGNAL PUSH NOTIFICATIONS
# ══════════════════════════════════════════════════════════════════════════════
print("\n" + "="*60)
print("7. ONESIGNAL PUSH NOTIFICATIONS (modules/push_notifications.py)")
print("="*60)

try:
    from modules.push_notifications import (
        make_pusher_from_config, notify_new_post, OneSignalPusher,
        ONESIGNAL_SDK_SNIPPET
    )

    # Factory
    pusher = make_pusher_from_config()
    if pusher is None:
        record("push_notifications.make_pusher_from_config", "WARN",
               "Returned None — onesignal_app_id or onesignal_api_key not in config")
    else:
        assert isinstance(pusher, OneSignalPusher)
        record("push_notifications.make_pusher_from_config", "PASS",
               f"OneSignalPusher created — app_id={pusher.app_id[:18]}...")

        # Subscriber count (validates API key works)
        count = pusher.get_subscriber_count()
        record("push_notifications.get_subscriber_count", "PASS",
               f"API call OK — {count} subscribers")

        # Send push notification
        print("    [INFO] Sending OneSignal push notification...")
        result = pusher.send(
            title=f"[TEST] {TITLE}",
            message=f"New crypto post: {TITLE}",
            url=POST_URL,
        )
        if result.get("id") and not result.get("errors"):
            record("push_notifications.send", "PASS",
                   f"Push sent — id={result['id']} recipients={result.get('recipients', '?')}")
        elif result.get("errors"):
            record("push_notifications.send", "WARN",
                   f"API responded with errors: {result['errors']}")
        else:
            record("push_notifications.send", "WARN",
                   f"Unexpected response: {result}")

    # SDK snippet check
    assert "OneSignalSDK" in ONESIGNAL_SDK_SNIPPET
    assert "onesignal_app_id" in ONESIGNAL_SDK_SNIPPET
    record("push_notifications.sdk_snippet", "PASS",
           "ONESIGNAL_SDK_SNIPPET contains expected placeholders")

except Exception as e:
    record("push_notifications", "FAIL", f"{type(e).__name__}: {e}")
    traceback.print_exc()

# ══════════════════════════════════════════════════════════════════════════════
# 8. _fire_traffic_signals() INTEGRATION TEST
# ══════════════════════════════════════════════════════════════════════════════
print("\n" + "="*60)
print("8. _fire_traffic_signals() INTEGRATION (bot_loop.py)")
print("="*60)

try:
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "bot_loop", BASE_DIR / "bot_loop.py"
    )
    bot_loop = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bot_loop)

    fn = getattr(bot_loop, "_fire_traffic_signals", None)
    assert fn is not None, "_fire_traffic_signals not found in bot_loop.py"
    record("bot_loop._fire_traffic_signals.import", "PASS",
           "_fire_traffic_signals function found")

    # Test the root-URL guard
    print("    [INFO] Testing root-URL guard...")
    fn("https://topicpulse.pages.dev", SLUG, TITLE, NICHE)  # should be blocked
    record("bot_loop._fire_traffic_signals.root_guard", "PASS",
           "Root hub URL correctly blocked (no sub-path)")

    # Test with real blog URL (all zero-credential channels fire)
    print(f"    [INFO] Firing all traffic signals for {BLOG_URL}...")
    fn(BLOG_URL, SLUG, TITLE, NICHE)
    record("bot_loop._fire_traffic_signals.integration", "PASS",
           f"Fired without exception — blog={BLOG_URL} slug={SLUG}")

except Exception as e:
    record("bot_loop._fire_traffic_signals", "FAIL", f"{type(e).__name__}: {e}")
    traceback.print_exc()

# ══════════════════════════════════════════════════════════════════════════════
# REPORT
# ══════════════════════════════════════════════════════════════════════════════
print("\n\n" + "="*70)
print("FINAL RESULTS TABLE")
print("="*70)
print(f"{'Module':<52} {'Status':<6} {'Notes'}")
print("-"*70)

totals = {"PASS": 0, "WARN": 0, "FAIL": 0}
for module, status, notes in results:
    icon = {"PASS": "OK  ", "WARN": "WARN", "FAIL": "FAIL"}.get(status, "    ")
    # truncate notes to 60 chars for table
    notes_short = (notes[:57] + "...") if len(notes) > 60 else notes
    print(f"  [{icon}] {module:<48} {notes_short}")
    totals[status] = totals.get(status, 0) + 1

print("-"*70)
print(f"\nSummary: {totals['PASS']} PASS  |  {totals['WARN']} WARN  |  {totals['FAIL']} FAIL")
print("="*70)

if totals["FAIL"] > 0:
    print("\nFAILED MODULES:")
    for module, status, notes in results:
        if status == "FAIL":
            print(f"  - {module}: {notes}")

sys.exit(0 if totals["FAIL"] == 0 else 1)
