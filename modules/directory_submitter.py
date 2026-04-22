"""
BlogBot — directory_submitter.py
Blog directory submission: submits blog RSS feeds to Feedspot, AllTop, and other directories.
Generates permanent backlinks and passive referral traffic.
Runs once per new blog — submissions are remembered in the DB.
"""

import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict
from urllib.parse import quote_plus

import requests

# ── Logging ───────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent.parent.resolve()
LOGS_DIR  = BASE_DIR / "logs"
DATA_DIR  = BASE_DIR / "data"
LOGS_DIR.mkdir(parents=True, exist_ok=True)
DATA_DIR.mkdir(parents=True, exist_ok=True)

_log = logging.getLogger("directory_submitter")
_log.setLevel(logging.INFO)
if not _log.handlers:
    _fh = logging.FileHandler(LOGS_DIR / "activity.log", encoding="utf-8")
    _fh.setFormatter(logging.Formatter("%(asctime)s [DIRECTORY] %(levelname)s %(message)s"))
    _log.addHandler(_fh)

# ── Constants ─────────────────────────────────────────────────────────────────
_SYSTEM_DB = DATA_DIR / "system.db"
_TIMEOUT   = 20
_HEADERS   = {"User-Agent": "Mozilla/5.0 (compatible; BlogBot/1.0)"}


# ── Class ─────────────────────────────────────────────────────────────────────
class DirectorySubmitter:
    """
    Submits a blog's RSS feed and URL to popular blog directories.
    Each successful submission is recorded in system.db to prevent duplicates.
    """

    # Directories we submit to. Each entry describes how to call the endpoint.
    DIRECTORIES = [
        {
            "name": "Feedspot",
            "method": "GET",
            "url_template": "https://www.feedspot.com/fs/feedsubmit?feed_url={rss_url}",
        },
        {
            "name": "AllTop",
            "method": "GET",
            "url_template": "https://alltop.com/submit?url={blog_url}",
        },
        {
            "name": "Blogarama",
            "method": "POST",
            "url_template": "https://www.blogarama.com/registerBlog",
        },
        {
            "name": "BlogDirectory",
            "method": "GET",
            "url_template": "https://www.blog-directory.org/AddBlog?blogurl={blog_url}",
        },
    ]

    def __init__(self) -> None:
        self._ensure_table()

    # ── DB helpers ────────────────────────────────────────────────────────────

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(_SYSTEM_DB), timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_table(self) -> None:
        """Create the directory_submissions tracking table if it does not exist."""
        try:
            with self._get_conn() as conn:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS directory_submissions (
                        id          INTEGER PRIMARY KEY AUTOINCREMENT,
                        blog_url    TEXT    NOT NULL,
                        directory   TEXT    NOT NULL,
                        submitted_at TEXT   NOT NULL,
                        UNIQUE(blog_url, directory)
                    )
                    """
                )
                conn.commit()
        except sqlite3.Error as exc:
            _log.error(f"Failed to create directory_submissions table: {exc}")

    def _already_submitted(self, blog_url: str, directory: str) -> bool:
        """Return True if this blog/directory pair has already been submitted."""
        try:
            with self._get_conn() as conn:
                row = conn.execute(
                    "SELECT 1 FROM directory_submissions WHERE blog_url=? AND directory=?",
                    (blog_url, directory),
                ).fetchone()
                return row is not None
        except sqlite3.Error as exc:
            _log.error(f"DB read error (_already_submitted): {exc}")
            return False

    def _mark_submitted(self, blog_url: str, directory: str) -> None:
        """Record a successful submission so it is never repeated."""
        try:
            with self._get_conn() as conn:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO directory_submissions (blog_url, directory, submitted_at)
                    VALUES (?, ?, ?)
                    """,
                    (blog_url, directory, datetime.now(timezone.utc).isoformat()),
                )
                conn.commit()
        except sqlite3.Error as exc:
            _log.error(f"DB write error (_mark_submitted): {exc}")

    # ── Submission helpers ────────────────────────────────────────────────────

    def _submit_feedspot(self, rss_url: str) -> bool:
        url = f"https://www.feedspot.com/fs/feedsubmit?feed_url={quote_plus(rss_url)}"
        try:
            resp = requests.get(url, headers=_HEADERS, timeout=_TIMEOUT)
            return resp.status_code == 200
        except requests.RequestException as exc:
            _log.warning(f"Feedspot request error: {exc}")
            return False

    def _submit_alltop(self, blog_url: str) -> bool:
        url = f"https://alltop.com/submit?url={quote_plus(blog_url)}"
        try:
            resp = requests.get(url, headers=_HEADERS, timeout=_TIMEOUT)
            return resp.status_code == 200
        except requests.RequestException as exc:
            _log.warning(f"AllTop request error: {exc}")
            return False

    def _submit_blogarama(self, blog_url: str, rss_url: str, email: str) -> bool:
        data = {
            "blog_url": blog_url,
            "rss_url":  rss_url,
            "email":    email,
        }
        try:
            resp = requests.post(
                "https://www.blogarama.com/registerBlog",
                data=data,
                headers=_HEADERS,
                timeout=_TIMEOUT,
            )
            return resp.status_code == 200
        except requests.RequestException as exc:
            _log.warning(f"Blogarama request error: {exc}")
            return False

    def _submit_blog_directory(self, blog_url: str) -> bool:
        url = f"https://www.blog-directory.org/AddBlog?blogurl={quote_plus(blog_url)}"
        try:
            resp = requests.get(url, headers=_HEADERS, timeout=_TIMEOUT)
            return resp.status_code == 200
        except requests.RequestException as exc:
            _log.warning(f"BlogDirectory request error: {exc}")
            return False

    # ── Main submission method ────────────────────────────────────────────────

    def submit_blog(
        self,
        blog_url: str,
        rss_url: str,
        title: str,
        niche: str,
        email: str = "",
    ) -> Dict[str, bool]:
        """
        Submit this blog to all directories.

        Skips any directory that already has a record in system.db.
        Returns a dict mapping directory name → True/False result.
        """
        results: Dict[str, bool] = {}

        # ── Feedspot ──────────────────────────────────────────────────────────
        name = "Feedspot"
        if self._already_submitted(blog_url, name):
            _log.debug(f"{name}: already submitted {blog_url} — skipping")
            results[name] = True
        else:
            try:
                ok = self._submit_feedspot(rss_url=rss_url)
                results[name] = ok
                if ok:
                    self._mark_submitted(blog_url, name)
                    _log.info(f"{name}: submitted {blog_url}")
                else:
                    _log.warning(f"{name}: submission failed for {blog_url}")
            except Exception as exc:
                _log.error(f"{name}: unexpected error for {blog_url}: {exc}")
                results[name] = False

        # ── AllTop ────────────────────────────────────────────────────────────
        name = "AllTop"
        if self._already_submitted(blog_url, name):
            _log.debug(f"{name}: already submitted {blog_url} — skipping")
            results[name] = True
        else:
            try:
                ok = self._submit_alltop(blog_url=blog_url)
                results[name] = ok
                if ok:
                    self._mark_submitted(blog_url, name)
                    _log.info(f"{name}: submitted {blog_url}")
                else:
                    _log.warning(f"{name}: submission failed for {blog_url}")
            except Exception as exc:
                _log.error(f"{name}: unexpected error for {blog_url}: {exc}")
                results[name] = False

        # ── Blogarama ─────────────────────────────────────────────────────────
        name = "Blogarama"
        if self._already_submitted(blog_url, name):
            _log.debug(f"{name}: already submitted {blog_url} — skipping")
            results[name] = True
        else:
            try:
                ok = self._submit_blogarama(
                    blog_url=blog_url, rss_url=rss_url, email=email
                )
                results[name] = ok
                if ok:
                    self._mark_submitted(blog_url, name)
                    _log.info(f"{name}: submitted {blog_url}")
                else:
                    _log.warning(f"{name}: submission failed for {blog_url}")
            except Exception as exc:
                _log.error(f"{name}: unexpected error for {blog_url}: {exc}")
                results[name] = False

        # ── BlogDirectory ─────────────────────────────────────────────────────
        name = "BlogDirectory"
        if self._already_submitted(blog_url, name):
            _log.debug(f"{name}: already submitted {blog_url} — skipping")
            results[name] = True
        else:
            try:
                ok = self._submit_blog_directory(blog_url=blog_url)
                results[name] = ok
                if ok:
                    self._mark_submitted(blog_url, name)
                    _log.info(f"{name}: submitted {blog_url}")
                else:
                    _log.warning(f"{name}: submission failed for {blog_url}")
            except Exception as exc:
                _log.error(f"{name}: unexpected error for {blog_url}: {exc}")
                results[name] = False

        _log.info(
            f"Directory submission complete for {blog_url} — "
            f"results: {results}"
        )
        return results


# ── Top-level helper ──────────────────────────────────────────────────────────
def submit_new_blog_to_directories(
    blog_url: str,
    rss_url: str,
    title: str,
    niche: str,
) -> Dict[str, bool]:
    """
    Called when a new blog is created.
    Looks up the contact email from config and submits to all directories.
    Returns the results dict from DirectorySubmitter.submit_blog().
    """
    email = ""
    try:
        try:
            from modules.config_manager import get as cfg_get
        except ImportError:
            from config_manager import get as cfg_get
        email = cfg_get("contact_email") or ""
    except Exception as exc:
        _log.debug(f"Could not read contact_email from config: {exc}")

    submitter = DirectorySubmitter()
    return submitter.submit_blog(
        blog_url=blog_url,
        rss_url=rss_url,
        title=title,
        niche=niche,
        email=email,
    )
