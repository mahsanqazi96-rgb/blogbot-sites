"""
BlogBot — alert_system.py
Tier 1/2/3 alert routing. Email + WhatsApp + SMS.
Daily report (7am UTC), Weekly report (Monday 7am UTC).

Tier 1: Dashboard only — auto-fixed silently
Tier 2: Email only — fix within 24 hours
Tier 3: WhatsApp + Email simultaneously — respond within 1 hour
"""

import smtplib
import logging
import json
import threading
import sys
from pathlib import Path
from datetime import datetime, timezone, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional
import requests

# ── Optional: apprise unified notifications ─────────────────────────────────────
try:
    import apprise as _apprise_lib
    _APPRISE_OK = True
except ImportError:
    _APPRISE_OK = False

_apprise_instance = None
_apprise_lock = threading.Lock()

# ── Path bootstrap ────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent.parent.resolve()
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

LOGS_DIR = BASE_DIR / "logs"

# ── Logging ───────────────────────────────────────────────────────────────────
_log = logging.getLogger("alert_system")
_log.setLevel(logging.INFO)
if not _log.handlers:
    _fh = logging.FileHandler(LOGS_DIR / "activity.log", encoding="utf-8")
    _fh.setFormatter(logging.Formatter("%(asctime)s [ALERT] %(levelname)s %(message)s"))
    _log.addHandler(_fh)

# ── Alert Queue (in-memory for dashboard) ─────────────────────────────────────
_dashboard_queue: list = []
_queue_lock = threading.Lock()

TIER_LABELS = {1: "INFO", 2: "WARNING", 3: "CRITICAL"}

# ── Core Alert Dispatcher ─────────────────────────────────────────────────────
def alert(tier: int, title: str, message: str, module: str = "system"):
    """
    Send an alert at the appropriate tier.
    tier 1 = dashboard only
    tier 2 = email
    tier 3 = email + WhatsApp
    """
    from modules.database_manager import audit
    now = datetime.now(timezone.utc).isoformat()
    severity = TIER_LABELS.get(tier, "INFO")

    # Always log to file
    _log.log(
        logging.CRITICAL if tier == 3 else (logging.WARNING if tier == 2 else logging.INFO),
        f"[T{tier}] {module} | {title} | {message}"
    )

    # Always add to dashboard queue
    _add_to_dashboard(tier, title, message, module, now)

    # Audit log (non-blocking)
    try:
        audit(module, title, message[:200], severity)
    except Exception as e:  # noqa: BLE001 — audit log is best-effort
        _log.debug(f"alert_system._audit({module}/{title}) audit log failed: {e}")

    # Tier 2+: Email
    if tier >= 2:
        _send_email_alert(tier, title, message, module)
        _send_apprise_alert(tier, title, message)

    # Tier 3: WhatsApp
    if tier >= 3:
        _send_whatsapp_alert(title, message, module)

# Convenience functions
def tier1(title: str, message: str, module: str = "system"):
    alert(1, title, message, module)

def tier2(title: str, message: str, module: str = "system"):
    alert(2, title, message, module)

def tier3(title: str, message: str, module: str = "system"):
    alert(3, title, message, module)

def critical(title: str, message: str, module: str = "system"):
    """Alias for tier3."""
    alert(3, title, message, module)

def warning(title: str, message: str, module: str = "system"):
    """Alias for tier2."""
    alert(2, title, message, module)

def info(title: str, message: str, module: str = "system"):
    """Alias for tier1."""
    alert(1, title, message, module)

# ── Apprise (optional unified notifications) ──────────────────────────────────
def _get_apprise():
    """Return configured apprise.Apprise instance or None. Lazy-loaded.
    Security: URLs loaded from encrypted config.json. Scheme-only logging (never full URL)."""
    global _apprise_instance
    if not _APPRISE_OK:
        return None
    with _apprise_lock:
        if _apprise_instance is not None:
            return _apprise_instance
        try:
            from modules.config_manager import get
            urls = get("apprise_urls", [])
            if not urls:
                return None
            ap = _apprise_lib.Apprise()
            loaded = 0
            for url in (urls if isinstance(urls, list) else []):
                if not isinstance(url, str) or "://" not in url:
                    continue
                scheme = url.split("://")[0]
                try:
                    if ap.add(url):
                        loaded += 1
                        _log.debug(f"apprise: loaded {scheme}:// target")
                except Exception as e:
                    _log.warning(f"apprise: failed to load {scheme}:// target: {e}")
            if loaded == 0:
                return None
            _apprise_instance = ap
            _log.info(f"apprise: {loaded} notification target(s) configured")
            return _apprise_instance
        except Exception as e:
            _log.error(f"apprise._get_apprise error: {e}")
            return None


def _send_apprise_alert(tier: int, title: str, message: str):
    """Send alert via apprise in background thread. Never raises."""
    threading.Thread(target=_apprise_worker, args=(tier, title, message), daemon=True).start()


def _apprise_worker(tier: int, title: str, message: str):
    try:
        ap = _get_apprise()
        if ap is None:
            return
        if not _APPRISE_OK:
            return
        notify_type = (
            _apprise_lib.NotifyType.FAILURE if tier >= 3
            else _apprise_lib.NotifyType.WARNING if tier == 2
            else _apprise_lib.NotifyType.INFO
        )
        ap.notify(
            title=f"[BlogBot T{tier}] {title}",
            body=message[:500],
            notify_type=notify_type,
        )
        _log.debug(f"apprise: T{tier} notification sent")
    except Exception as e:
        _log.error(f"apprise._apprise_worker error: {e}")


# ── Dashboard Queue ───────────────────────────────────────────────────────────
def _add_to_dashboard(tier: int, title: str, message: str, module: str, timestamp: str):
    with _queue_lock:
        _dashboard_queue.append({
            "tier": tier,
            "title": title,
            "message": message,
            "module": module,
            "timestamp": timestamp,
            "read": False,
        })
        # Cap at 500 entries
        if len(_dashboard_queue) > 500:
            _dashboard_queue.pop(0)

def get_dashboard_alerts(unread_only: bool = False, limit: int = 50) -> list:
    """Called by dashboard to show alert panel."""
    with _queue_lock:
        alerts = _dashboard_queue[-limit:]
        if unread_only:
            alerts = [a for a in alerts if not a["read"]]
        return list(reversed(alerts))

def mark_all_read():
    with _queue_lock:
        for a in _dashboard_queue:
            a["read"] = True

def get_unread_count() -> int:
    with _queue_lock:
        return sum(1 for a in _dashboard_queue if not a["read"])

# ── Email ─────────────────────────────────────────────────────────────────────
def _send_email_alert(tier: int, title: str, message: str, module: str):
    """Send email alert. Non-blocking (runs in thread)."""
    threading.Thread(
        target=_email_worker,
        args=(tier, title, message, module),
        daemon=True
    ).start()

def _email_worker(tier: int, title: str, message: str, module: str):
    try:
        from modules.config_manager import get_alert_email, get
        email = get_alert_email()
        if not email:
            _log.warning("No alert email configured — skipping email alert")
            return

        smtp_host = get("alerts.smtp_host", "smtp.gmail.com")
        smtp_port = int(get("alerts.smtp_port", 587))
        smtp_user = get("alerts.smtp_user", "")
        smtp_pass = get("alerts.smtp_pass", "")

        if not smtp_user or not smtp_pass:
            # Fallback: use Gmail app password from alert email if it's Gmail
            _log.warning("SMTP credentials not configured — email alert skipped")
            return

        subject = f"[BlogBot T{tier}] {title}"
        body = _format_email_body(tier, title, message, module)

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = smtp_user
        msg["To"] = email
        msg.attach(MIMEText(body, "plain", "utf-8"))

        with smtplib.SMTP(smtp_host, smtp_port, timeout=15) as server:
            server.ehlo()
            server.starttls()
            server.login(smtp_user, smtp_pass)
            server.sendmail(smtp_user, email, msg.as_string())

        _log.info(f"Email alert sent: {subject}")
    except Exception as e:
        _log.error(f"Email alert failed: {e}")

def _format_email_body(tier: int, title: str, message: str, module: str) -> str:
    label = TIER_LABELS.get(tier, "ALERT")
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    return (
        f"BlogBot Alert\n"
        f"{'=' * 40}\n"
        f"Severity:  {label} (Tier {tier})\n"
        f"Module:    {module}\n"
        f"Time:      {now}\n"
        f"{'=' * 40}\n\n"
        f"{title}\n\n"
        f"{message}\n\n"
        f"{'=' * 40}\n"
        f"Response required: {'Within 1 hour' if tier == 3 else 'Within 24 hours'}\n"
    )

# ── WhatsApp (CallMeBot — free, no app needed) ────────────────────────────────
CALLMEBOT_API = "https://api.callmebot.com/whatsapp.php"

def _send_whatsapp_alert(title: str, message: str, module: str):
    """Send WhatsApp via CallMeBot. Non-blocking."""
    threading.Thread(
        target=_whatsapp_worker,
        args=(title, message, module),
        daemon=True
    ).start()

def _whatsapp_worker(title: str, message: str, module: str):
    try:
        from modules.config_manager import get_whatsapp_number, get
        number = get_whatsapp_number()
        api_key = get("alerts.callmebot_key", "")

        if not number or not api_key:
            _log.warning("WhatsApp not configured (need number + CallMeBot key)")
            return

        text = f"[BlogBot CRITICAL] {title}\n{message[:200]}"
        params = {"phone": number, "text": text, "apikey": api_key}
        resp = requests.get(CALLMEBOT_API, params=params, timeout=15)

        if resp.status_code == 200:
            _log.info(f"WhatsApp alert sent to {number}")
        else:
            _log.error(f"WhatsApp alert failed: {resp.status_code} {resp.text[:100]}")
    except Exception as e:
        _log.error(f"WhatsApp alert error: {e}")

# ── Daily Report (7am UTC) ────────────────────────────────────────────────────
def generate_daily_report() -> str:
    """Generate the 7am daily report. Called by scheduler."""
    try:
        from modules.database_manager import get_daily_revenue, fetch_one, fetch_all

        today = datetime.now(timezone.utc).date().isoformat()
        yesterday = (datetime.now(timezone.utc).date() - timedelta(days=1)).isoformat()

        # Revenue
        today_rev = get_daily_revenue(today)
        yesterday_rev = get_daily_revenue(yesterday)
        rev_change = ((today_rev - yesterday_rev) / yesterday_rev * 100
                      if yesterday_rev > 0 else 0)

        # Traffic (from analytics.db)
        traffic_row = fetch_one("analytics",
                                "SELECT SUM(pageviews) as total FROM traffic WHERE date=?",
                                (today,))
        today_traffic = traffic_row["total"] or 0 if traffic_row else 0

        # Queue depth
        queue = fetch_one("system",
                          "SELECT COUNT(*) as n FROM task_queue WHERE status='pending'")
        queue_depth = queue["n"] if queue else 0

        # Recent errors
        recent_errors = fetch_all("system", """
            SELECT module, action, result FROM audit_log
            WHERE severity IN ('CRITICAL','WARNING')
            AND timestamp > datetime('now', '-24 hours')
            ORDER BY timestamp DESC LIMIT 10
        """)

        # Active modules
        active_modules = fetch_all("system",
                                   "SELECT module_name FROM module_health WHERE status='running'")

        lines = [
            f"BlogBot Daily Report — {today}",
            "=" * 40,
            f"Revenue today:    ${today_rev:.2f}",
            f"Revenue yesterday:${yesterday_rev:.2f}  ({rev_change:+.1f}%)",
            f"Traffic today:    {today_traffic:,} pageviews",
            f"Queue depth:      {queue_depth} pending tasks",
            f"Active modules:   {len(active_modules)}",
            "",
        ]

        if recent_errors:
            lines.append("Recent Errors/Warnings:")
            for e in recent_errors[:5]:
                lines.append(f"  [{e['module']}] {e['action']}: {e['result'][:80]}")
        else:
            lines.append("No errors in last 24 hours.")

        lines.append("=" * 40)
        return "\n".join(lines)

    except Exception as e:
        return f"Daily report generation failed: {e}"

def generate_weekly_report() -> str:
    """Generate Monday weekly report."""
    try:
        from modules.database_manager import fetch_one, fetch_all

        now = datetime.now(timezone.utc)
        week_ago = (now - timedelta(days=7)).isoformat()

        # 7-day revenue
        rev_row = fetch_one("monetization",
                            "SELECT SUM(earnings) as total FROM revenue WHERE date >= ?",
                            (week_ago[:10],))
        week_rev = float(rev_row["total"] or 0) if rev_row else 0.0

        # 7-day traffic
        traffic_row = fetch_one("analytics",
                                "SELECT SUM(pageviews) as total FROM traffic WHERE date >= ?",
                                (week_ago[:10],))
        week_traffic = int(traffic_row["total"] or 0) if traffic_row else 0

        # Blog count
        blog_row = fetch_one("blogs",
                             "SELECT COUNT(*) as n FROM blogs WHERE status='active' AND network='safe'")
        blog_count = blog_row["n"] if blog_row else 0

        # Post count
        post_row = fetch_one("content_archive",
                             "SELECT COUNT(*) as n FROM posts WHERE published_at >= ?",
                             (week_ago,))
        post_count = post_row["n"] if post_row else 0

        lines = [
            f"BlogBot Weekly Report — Week ending {now.date().isoformat()}",
            "=" * 40,
            f"7-day revenue:    ${week_rev:.2f}",
            f"7-day traffic:    {week_traffic:,} pageviews",
            f"Active blogs:     {blog_count}",
            f"Posts published:  {post_count}",
            f"Avg daily rev:    ${week_rev/7:.2f}",
            "=" * 40,
        ]
        return "\n".join(lines)

    except Exception as e:
        return f"Weekly report generation failed: {e}"

def send_daily_report():
    """Called by scheduler at 7am UTC."""
    report = generate_daily_report()
    _log.info("Daily report generated")
    tier2("Daily Report", report, "alert_system")

def send_weekly_report():
    """Called by scheduler on Monday at 7am UTC."""
    report = generate_weekly_report()
    _log.info("Weekly report generated")
    tier2("Weekly Report", report, "alert_system")

# ── Revenue Drop Monitor ──────────────────────────────────────────────────────
def check_revenue_drop():
    """
    Alert if today's revenue is 50%+ below yesterday's.
    Called hourly by scheduler.
    """
    try:
        from modules.database_manager import get_daily_revenue
        today = datetime.now(timezone.utc).date().isoformat()
        yesterday = (datetime.now(timezone.utc).date() - timedelta(days=1)).isoformat()

        today_rev = get_daily_revenue(today)
        yesterday_rev = get_daily_revenue(yesterday)

        if yesterday_rev > 0 and today_rev < (yesterday_rev * 0.5):
            drop_pct = (1 - today_rev / yesterday_rev) * 100
            tier3(
                "Revenue Drop Alert",
                f"Today: ${today_rev:.2f} | Yesterday: ${yesterday_rev:.2f} | Drop: {drop_pct:.0f}%",
                "alert_system"
            )
    except Exception as e:
        _log.error(f"Revenue drop check failed: {e}")

# ── Apprise URL Configuration ─────────────────────────────────────────────────
def configure_apprise_urls(urls: list) -> int:
    """Save apprise notification URLs to config.json. Returns count saved.
    Example: configure_apprise_urls(['tgram://TOKEN/CHATID', 'discord://ID/TOKEN'])
    Security: stored in AES-256 encrypted config.json. URLs never logged in full."""
    global _apprise_instance
    try:
        from modules.config_manager import set as _cfg_set
        valid = [u for u in urls if isinstance(u, str) and "://" in u]
        _cfg_set("apprise_urls", valid)
        with _apprise_lock:
            _apprise_instance = None   # force reload on next call
        _log.info(f"apprise: {len(valid)} URL(s) saved to config")
        return len(valid)
    except Exception as e:
        _log.error(f"configure_apprise_urls failed: {e}")
        return 0


# ── Self-Test ─────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("alert_system self-test...")

    # Tier 1 alert
    tier1("Test Info", "This is a tier 1 test alert", "self_test")
    print("  Tier 1 alert: queued to dashboard")

    # Dashboard queue
    alerts = get_dashboard_alerts()
    print(f"  Dashboard queue: {len(alerts)} alert(s)")
    print(f"  Unread count: {get_unread_count()}")

    # Daily report (no DB errors expected)
    report = generate_daily_report()
    print(f"  Daily report: {len(report)} chars")
    print()
    print(report[:300])

    print("\nSelf-test complete.")
