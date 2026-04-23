"""
install_popads.py
=================
Injects the PopAds popunder script into every HTML file across all blog sites,
then pushes the changes to GitHub in a single Trees-API commit and triggers
a Cloudflare Pages deployment.

Injection:  PopAds script tag → just before </head> on every page (posts + index)
Idempotent: files already containing <!-- POPADS_INJECTED --> are skipped.

Usage:
    python install_popads.py
"""

import sys, requests, logging
from pathlib import Path
from datetime import datetime, timezone

BASE_DIR  = Path(__file__).parent.resolve()
SITES_DIR = BASE_DIR / "sites"
LOGS_DIR  = BASE_DIR / "logs"
sys.path.insert(0, str(BASE_DIR))

MARKER = "<!-- POPADS_INJECTED -->"

POPADS_CODE = """\
<script type="text/javascript" data-cfasync="false">
/*<![CDATA[/* */
(function(){var y=window,l="a5a68e18cd631c06ce8d904524095128",c=[["siteId",240+797*960+807+4527548],["minBid",0],["popundersPerIP","0"],["delayBetween",0],["default",false],["defaultPerDay",0],["topmostLayer","auto"]],i=["d3d3LmJsb2NrYWRzbm90LmNvbS9lZGpwL2pqc3RzLm1pbi5qcw==","ZG5oZmk1bm4yZHQ2Ny5jbG91ZGZyb250Lm5ldC90c3VwR2kvd3duYnVtL2VjbGFtcC5taW4uY3Nz"],f=-1,o,p,q=function(){clearTimeout(p);f++;if(i[f]&&!(1802901518000<(new Date).getTime()&&1<f)){o=y.document.createElement("script");o.type="text/javascript";o.async=!0;var r=y.document.getElementsByTagName("script")[0];o.src="https://"+atob(i[f]);o.crossOrigin="anonymous";o.onerror=q;o.onload=function(){clearTimeout(p);y[l.slice(0,16)+l.slice(0,16)]||q()};p=setTimeout(q,5E3);r.parentNode.insertBefore(o,r)}};if(!y[l]){try{Object.freeze(y[l]=c)}catch(e){}q()}})();
/*]]>/* */
</script>
<!-- POPADS_INJECTED -->"""

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [POPADS] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOGS_DIR / "install_ads.log", encoding="utf-8"),
    ],
)
log = logging.getLogger("install_popads")


def inject_file(fpath: Path) -> bool:
    """Inject PopAds code just before </head>. Returns True if file was changed."""
    html = fpath.read_text(encoding="utf-8", errors="replace")
    if MARKER in html:
        return False  # already done
    if "</head>" not in html:
        return False  # malformed file, skip
    html = html.replace("</head>", f"{POPADS_CODE}\n</head>", 1)
    fpath.write_text(html, encoding="utf-8")
    return True


def push_to_github(modified_files, gh_token, gh_owner, gh_repo, gh_branch):
    api     = "https://api.github.com"
    headers = {"Authorization": f"Bearer {gh_token}", "Accept": "application/vnd.github.v3+json"}

    # HEAD commit sha
    r = requests.get(f"{api}/repos/{gh_owner}/{gh_repo}/git/ref/heads/{gh_branch}",
                     headers=headers, timeout=30)
    if r.status_code != 200:
        log.error(f"Failed to get HEAD: {r.status_code}")
        return ""
    base_sha = r.json()["object"]["sha"]

    # Base tree sha
    r = requests.get(f"{api}/repos/{gh_owner}/{gh_repo}/git/commits/{base_sha}",
                     headers=headers, timeout=30)
    base_tree_sha = r.json()["tree"]["sha"]

    # Build tree entries (paths relative to repo root, stripping leading sites/)
    tree_entries = []
    for fpath in modified_files:
        try:
            rel = fpath.relative_to(SITES_DIR).as_posix()
        except ValueError:
            continue
        try:
            content = fpath.read_text(encoding="utf-8")
        except Exception as e:
            log.warning(f"Skipped {rel}: {e}")
            continue
        tree_entries.append({"path": rel, "mode": "100644", "type": "blob", "content": content})

    if not tree_entries:
        log.warning("No tree entries — nothing to commit.")
        return ""

    log.info(f"  Building GitHub tree for {len(tree_entries)} files…")
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

    # Create commit
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    r = requests.post(
        f"{api}/repos/{gh_owner}/{gh_repo}/git/commits",
        headers=headers,
        json={
            "message": f"BlogBot: inject PopAds into {len(tree_entries)} files ({now})",
            "tree":    new_tree_sha,
            "parents": [base_sha],
        },
        timeout=60,
    )
    if r.status_code not in (200, 201):
        log.error(f"Create commit failed: {r.status_code}")
        return ""
    new_commit_sha = r.json()["sha"]

    # Update branch ref
    r = requests.patch(
        f"{api}/repos/{gh_owner}/{gh_repo}/git/refs/heads/{gh_branch}",
        headers=headers,
        json={"sha": new_commit_sha, "force": False},
        timeout=30,
    )
    if r.status_code not in (200, 201):
        log.error(f"Update ref failed: {r.status_code}")
        return ""

    log.info(f"  GitHub commit OK: {new_commit_sha[:12]} ({len(tree_entries)} files)")
    return new_commit_sha


def trigger_cf(cf_token, cf_account_id, cf_project):
    url     = (f"https://api.cloudflare.com/client/v4/accounts/{cf_account_id}"
               f"/pages/projects/{cf_project}/deployments")
    headers = {"Authorization": f"Bearer {cf_token}", "Content-Type": "application/json"}
    r = requests.post(url, headers=headers, json={}, timeout=30)
    if r.status_code in (200, 201):
        dep_id = r.json().get("result", {}).get("id", "?")
        log.info(f"  CF deployment triggered: {dep_id}")
        return dep_id
    log.error(f"  CF trigger failed: {r.status_code} {r.text[:200]}")
    return ""


def main():
    log.info("=" * 60)
    log.info("install_popads.py — PopAds injection")
    log.info("=" * 60)

    # Load config
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

    if "github.com" in gh_repo:
        gh_repo = gh_repo.rstrip("/").split("github.com/")[-1]

    # Collect all HTML files under sites/
    post_files  = list(SITES_DIR.rglob("posts/*.html"))
    index_files = [f for f in SITES_DIR.rglob("index.html")
                   if f.parent.name != "posts"]

    log.info(f"Found {len(post_files)} post files + {len(index_files)} index files")

    modified = []
    skipped  = 0

    for fpath in sorted(post_files) + sorted(index_files):
        if inject_file(fpath):
            modified.append(fpath)
        else:
            skipped += 1

    log.info(f"Modified: {len(modified)} | Already done / skipped: {skipped}")

    if not modified:
        log.info("Nothing to push — all files already have PopAds injected.")
        return

    # Push to GitHub
    log.info(f"Pushing {len(modified)} files to GitHub…")
    commit_sha = push_to_github(modified, gh_token, gh_owner, gh_repo, gh_branch)
    if not commit_sha:
        log.error("GitHub push failed — files updated on disk but not live yet.")
        return

    # Trigger Cloudflare deployment
    log.info("Triggering Cloudflare deployment…")
    trigger_cf(cf_token, cf_acct, cf_proj)

    log.info("")
    log.info("=" * 60)
    log.info(f"OK PopAds injected into {len(modified)} files")
    log.info(f"   GitHub commit: {commit_sha[:12]}")
    log.info(f"   Cloudflare build will go live in ~30 seconds")
    log.info("=" * 60)


if __name__ == "__main__":
    main()
