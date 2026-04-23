"""
fix_canonical_urls.py
=====================
Patches every HTML file under sites/ that still references the old
  https://blogbot-sites.pages.dev/sites/site-NNN/
URL scheme, replacing it with the correct
  https://topicpulse.pages.dev/<blogname>/
URL read from blogs.db.

Idempotent: files already containing <!-- CANONICAL_FIXED --> are skipped.

After patching it pushes ALL modified files to GitHub in a single Trees-API
batch commit (same pattern as install_popads.py) and triggers a Cloudflare
Pages deployment.

Usage:
    python fix_canonical_urls.py
"""

import re
import sys
import sqlite3
import logging
import requests
from pathlib import Path
from datetime import datetime, timezone

# ── Paths ─────────────────────────────────────────────────────────────────────
BASE_DIR  = Path(__file__).parent.resolve()
SITES_DIR = BASE_DIR / "sites"
LOGS_DIR  = BASE_DIR / "logs"
DB_PATH   = BASE_DIR / "data" / "blogs.db"
sys.path.insert(0, str(BASE_DIR))

MARKER    = "<!-- CANONICAL_FIXED -->"

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [FIX-CANONICAL] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOGS_DIR / "fix_canonical.log", encoding="utf-8"),
    ],
)
log = logging.getLogger("fix_canonical")


# ── DB helpers ────────────────────────────────────────────────────────────────

def _build_url_mapping() -> dict:
    """
    Returns two dicts merged into one:
      dirname -> correct_site_url

    For named dirs (e.g. 'bitsignal'): keyed by github_path.
    For legacy site-NNN dirs:          keyed by blog_id (e.g. 'site-001').

    Both are stored in the same returned dict — callers just look up by
    the directory name found in the filesystem.
    """
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    cur  = conn.cursor()
    cur.execute(
        "SELECT blog_id, github_path, site_url "
        "FROM blogs "
        "WHERE platform='cloudflare' "
        "  AND github_path IS NOT NULL "
        "  AND site_url    IS NOT NULL"
    )
    rows = cur.fetchall()
    conn.close()

    mapping = {}
    for r in rows:
        site_url    = r["site_url"].rstrip("/")
        github_path = r["github_path"]
        blog_id     = r["blog_id"]
        # Named dir (e.g. 'bitsignal') → site_url
        mapping[github_path] = site_url
        # Legacy dir (e.g. 'site-002') → same site_url
        mapping[blog_id]     = site_url

    return mapping


# ── Per-file patching ─────────────────────────────────────────────────────────

def _fix_file(fpath: Path, correct_site_url: str) -> bool:
    """
    Replace every occurrence of the old blogbot-sites.pages.dev URL in fpath
    with the correct topicpulse URL.  Injects CANONICAL_FIXED marker just
    before </head>.

    Returns True if the file was changed.
    """
    try:
        html = fpath.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        log.warning(f"Cannot read {fpath}: {e}")
        return False

    if MARKER in html:
        return False  # already fixed, idempotent

    # ── Replace all old URL occurrences ───────────────────────────────────────
    # The old pattern is: https://blogbot-sites.pages.dev/sites/site-NNN/...
    # We want:            https://topicpulse.pages.dev/<blogname>/...
    #
    # Strategy: replace the OLD base (everything up to and including the
    # site-NNN segment) with the correct base, preserving the remainder of the
    # path (e.g. posts/slug.html, privacy-policy.html etc.).
    #
    # Pattern captures:  blogbot-sites.pages.dev/sites/site-NNN
    # Replaced with:     topicpulse.pages.dev/<blogname>

    OLD_BASE_RE = re.compile(
        r"https://blogbot-sites\.pages\.dev/sites/site-\d+",
        re.IGNORECASE,
    )

    if not OLD_BASE_RE.search(html):
        return False  # nothing to fix in this file

    new_html = OLD_BASE_RE.sub(correct_site_url, html)

    # ── Inject marker just before </head> ─────────────────────────────────────
    if "</head>" in new_html:
        new_html = new_html.replace("</head>", f"{MARKER}\n</head>", 1)
    else:
        new_html += f"\n{MARKER}"

    if new_html == html:
        return False  # paranoia: no real change

    try:
        fpath.write_text(new_html, encoding="utf-8")
    except Exception as e:
        log.warning(f"Cannot write {fpath}: {e}")
        return False

    return True


# ── GitHub push (Trees API batch) ─────────────────────────────────────────────

def push_to_github(modified_files: list, gh_token: str, gh_owner: str,
                   gh_repo: str, gh_branch: str) -> str:
    """
    Push all modified files in a single commit via GitHub Trees API.
    File paths are made relative to the repo root by stripping the
    leading sites/ prefix (matching how install_popads.py works).

    Returns the new commit SHA on success, empty string on failure.
    """
    api     = "https://api.github.com"
    headers = {
        "Authorization": f"Bearer {gh_token}",
        "Accept":        "application/vnd.github.v3+json",
    }

    # 1. HEAD commit SHA
    r = requests.get(
        f"{api}/repos/{gh_owner}/{gh_repo}/git/ref/heads/{gh_branch}",
        headers=headers, timeout=30,
    )
    if r.status_code != 200:
        log.error(f"Failed to get HEAD ref: {r.status_code} {r.text[:200]}")
        return ""
    base_sha = r.json()["object"]["sha"]

    # 2. Base tree SHA (from the HEAD commit)
    r = requests.get(
        f"{api}/repos/{gh_owner}/{gh_repo}/git/commits/{base_sha}",
        headers=headers, timeout=30,
    )
    if r.status_code != 200:
        log.error(f"Failed to get HEAD commit: {r.status_code}")
        return ""
    base_tree_sha = r.json()["tree"]["sha"]

    # 3. Build tree entries — paths relative to repo root
    tree_entries = []
    for fpath in modified_files:
        # Strip the leading SITES_DIR to get repo-relative path
        try:
            rel = fpath.relative_to(SITES_DIR).as_posix()
        except ValueError:
            # File is not under SITES_DIR — use path relative to BASE_DIR
            try:
                rel = fpath.relative_to(BASE_DIR).as_posix()
            except ValueError:
                log.warning(f"Cannot make {fpath} relative — skipping")
                continue
        try:
            content = fpath.read_text(encoding="utf-8")
        except Exception as e:
            log.warning(f"Skipping {rel}: {e}")
            continue
        tree_entries.append({
            "path":    rel,
            "mode":    "100644",
            "type":    "blob",
            "content": content,
        })

    if not tree_entries:
        log.warning("No tree entries — nothing to commit.")
        return ""

    log.info(f"  Building GitHub tree for {len(tree_entries)} files…")

    # Build in batches of 500 to stay under GitHub's body size limit
    BATCH = 500
    if len(tree_entries) > BATCH:
        log.info(f"  Large payload — splitting into batches of {BATCH}")
        current_tree_sha = base_tree_sha
        current_sha = base_sha
        for start in range(0, len(tree_entries), BATCH):
            batch = tree_entries[start:start + BATCH]
            r = requests.post(
                f"{api}/repos/{gh_owner}/{gh_repo}/git/trees",
                headers=headers,
                json={"base_tree": current_tree_sha, "tree": batch},
                timeout=300,
            )
            if r.status_code not in (200, 201):
                log.error(f"Create tree batch failed: {r.status_code} {r.text[:200]}")
                return ""
            current_tree_sha = r.json()["sha"]
            log.info(f"  Batch {start//BATCH + 1} tree SHA: {current_tree_sha[:12]}")
        new_tree_sha = current_tree_sha
    else:
        r = requests.post(
            f"{api}/repos/{gh_owner}/{gh_repo}/git/trees",
            headers=headers,
            json={"base_tree": base_tree_sha, "tree": tree_entries},
            timeout=300,
        )
        if r.status_code not in (200, 201):
            log.error(f"Create tree failed: {r.status_code} {r.text[:200]}")
            return ""
        new_tree_sha = r.json()["sha"]

    # 4. Create commit
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    r = requests.post(
        f"{api}/repos/{gh_owner}/{gh_repo}/git/commits",
        headers=headers,
        json={
            "message": (
                f"BlogBot: fix canonical URLs in {len(tree_entries)} files ({now})\n\n"
                "Replaced all blogbot-sites.pages.dev/sites/site-NNN/ references\n"
                "with correct topicpulse.pages.dev/<blogname>/ URLs."
            ),
            "tree":    new_tree_sha,
            "parents": [base_sha],
        },
        timeout=60,
    )
    if r.status_code not in (200, 201):
        log.error(f"Create commit failed: {r.status_code} {r.text[:200]}")
        return ""
    new_commit_sha = r.json()["sha"]

    # 5. Update branch ref
    r = requests.patch(
        f"{api}/repos/{gh_owner}/{gh_repo}/git/refs/heads/{gh_branch}",
        headers=headers,
        json={"sha": new_commit_sha, "force": False},
        timeout=30,
    )
    if r.status_code not in (200, 201):
        log.error(f"Update ref failed: {r.status_code} {r.text[:200]}")
        return ""

    log.info(f"  GitHub commit OK: {new_commit_sha[:12]} ({len(tree_entries)} files)")
    return new_commit_sha


# ── Cloudflare trigger ────────────────────────────────────────────────────────

def trigger_cf(cf_token: str, cf_account_id: str, cf_project: str) -> str:
    url     = (
        f"https://api.cloudflare.com/client/v4/accounts/{cf_account_id}"
        f"/pages/projects/{cf_project}/deployments"
    )
    headers = {
        "Authorization": f"Bearer {cf_token}",
        "Content-Type":  "application/json",
    }
    r = requests.post(url, headers=headers, json={}, timeout=30)
    if r.status_code in (200, 201):
        dep_id = r.json().get("result", {}).get("id", "?")
        log.info(f"  CF deployment triggered: {dep_id}")
        return dep_id
    log.error(f"  CF trigger failed: {r.status_code} {r.text[:200]}")
    return ""


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    log.info("=" * 65)
    log.info("fix_canonical_urls.py — patching old blogbot-sites.pages.dev URLs")
    log.info("=" * 65)

    # ── 1. Build DB mapping ───────────────────────────────────────────────────
    log.info("Loading URL mapping from blogs.db…")
    url_mapping = _build_url_mapping()
    log.info(f"  {len(url_mapping)} entries (named + site-NNN forms)")

    # ── 2. Scan all HTML files under sites/ ───────────────────────────────────
    log.info(f"Scanning {SITES_DIR}…")
    all_html = list(SITES_DIR.rglob("*.html"))
    log.info(f"  {len(all_html)} HTML files found")

    modified    = []
    skipped_ok  = 0   # already fixed
    skipped_map = 0   # no DB mapping
    skipped_clean = 0 # no old URL present

    for fpath in sorted(all_html):
        # Determine which blog dir this file lives in
        try:
            rel_parts = fpath.relative_to(SITES_DIR).parts
        except ValueError:
            skipped_map += 1
            continue

        blog_dir = rel_parts[0]  # e.g. 'activebrief' or 'site-001'

        # Quick idempotency check before DB lookup
        try:
            html_raw = fpath.read_text(encoding="utf-8", errors="replace")
        except Exception:
            skipped_map += 1
            continue

        if MARKER in html_raw:
            skipped_ok += 1
            continue

        if "blogbot-sites.pages.dev" not in html_raw:
            skipped_clean += 1
            continue

        # Look up the correct URL
        correct_url = url_mapping.get(blog_dir)
        if not correct_url:
            log.warning(f"  No URL mapping for dir '{blog_dir}' — skipping {fpath.name}")
            skipped_map += 1
            continue

        # Patch the file
        if _fix_file(fpath, correct_url):
            modified.append(fpath)
            log.debug(f"  Fixed: {fpath.relative_to(BASE_DIR)}")

    log.info(f"Fixed:         {len(modified)}")
    log.info(f"Already fixed: {skipped_ok}")
    log.info(f"No old URL:    {skipped_clean}")
    log.info(f"No DB mapping: {skipped_map}")

    if not modified:
        log.info("Nothing to push — all files already have correct URLs.")
        return

    # ── 3. Push to GitHub ─────────────────────────────────────────────────────
    log.info(f"Loading config for GitHub credentials…")
    from modules.config_manager import load_config
    cfg       = load_config()
    gh_token  = cfg.get("github_token", "")
    gh_owner  = cfg.get("github_owner", "")
    gh_repo   = cfg.get("github_repo", "")
    gh_branch = cfg.get("github_branch") or "main"
    cf_acc    = cfg["cloudflare_accounts"][0]
    cf_token  = cf_acc["api_token"]
    cf_acct   = cf_acc["account_id"]
    cf_proj   = cf_acc.get("pages_project", "topicpulse")

    # Normalise GitHub repo to owner/repo format
    if "github.com" in gh_repo:
        gh_repo = gh_repo.rstrip("/").split("github.com/")[-1]

    log.info(f"Pushing {len(modified)} files to GitHub ({gh_owner}/{gh_repo})…")
    commit_sha = push_to_github(modified, gh_token, gh_owner, gh_repo, gh_branch)

    if not commit_sha:
        log.error("GitHub push FAILED — files patched on disk but NOT live yet.")
        log.error("Re-run this script once the GitHub connection is restored.")
        return

    # ── 4. Trigger Cloudflare deployment ──────────────────────────────────────
    log.info("Triggering Cloudflare Pages deployment…")
    dep_id = trigger_cf(cf_token, cf_acct, cf_proj)

    log.info("")
    log.info("=" * 65)
    log.info(f"DONE — {len(modified)} files patched with correct canonical URLs")
    log.info(f"  GitHub commit : {commit_sha[:12]}")
    log.info(f"  CF deployment : {dep_id or 'trigger failed — check CF dashboard'}")
    log.info(f"  Live in       : ~30-60 seconds")
    log.info("=" * 65)


if __name__ == "__main__":
    main()
