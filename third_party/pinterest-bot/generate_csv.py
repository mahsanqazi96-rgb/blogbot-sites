"""
BlogBot — Pinterest Bulk Pin Generator
======================================
Reads the latest posts from each niche's RSS feed (or content_archive.db)
and produces a pins.csv file compatible with Pinterest's bulk uploader:
  https://help.pinterest.com/en/business/article/bulk-create-pins

Usage:
    python generate_csv.py [--days N]

Output:
    pins.csv — ready to upload at pinterest.com/pin-builder/bulk-create

Columns: Title, Description, Link, Image URL, Board
"""

import argparse
import csv
import sqlite3
import pathlib
import sys

# ── Paths ─────────────────────────────────────────────────────────────────────
BASE_DIR   = pathlib.Path(__file__).parent.parent.parent.resolve()
DB_PATH    = BASE_DIR / "content_archive.db"
CREDS_FILE = pathlib.Path(__file__).parent / "credentials.json"
OUT_CSV    = pathlib.Path(__file__).parent / "pins.csv"

# ── Board mapping ─────────────────────────────────────────────────────────────
DEFAULT_BOARDS = {
    "tech":          "Tech & Gadgets News",
    "crypto":        "Crypto & Blockchain",
    "finance":       "Finance & Investing",
    "health":        "Health & Wellness",
    "entertainment": "Entertainment & Viral",
}


def load_board_map():
    """Load board mapping from credentials.json if available."""
    try:
        import json
        with open(CREDS_FILE) as f:
            creds = json.load(f)
        return creds.get("boards", DEFAULT_BOARDS)
    except Exception:
        return DEFAULT_BOARDS


def fetch_recent_posts(days: int = 7):
    """Fetch posts published in the last N days from content_archive.db."""
    if not DB_PATH.exists():
        print(f"ERROR: content_archive.db not found at {DB_PATH}")
        sys.exit(1)

    conn = sqlite3.connect(DB_PATH)
    cur  = conn.cursor()

    # Try standard column names — adjust if your schema differs
    try:
        cur.execute("""
            SELECT title, slug, niche, site_url, image_url, meta_description
            FROM   published_posts
            WHERE  published_at >= datetime('now', ?)
            ORDER  BY published_at DESC
            LIMIT  500
        """, (f"-{days} days",))
        rows = cur.fetchall()
    except sqlite3.OperationalError:
        # Fallback column names
        cur.execute("""
            SELECT title, slug, niche, site_url, '' as image_url, '' as meta_description
            FROM   posts
            WHERE  created_at >= datetime('now', ?)
            ORDER  BY created_at DESC
            LIMIT  500
        """, (f"-{days} days",))
        rows = cur.fetchall()

    conn.close()
    return rows


def generate_csv(days: int = 7):
    """Main entry point."""
    boards   = load_board_map()
    posts    = fetch_recent_posts(days)

    if not posts:
        print(f"No posts found in the last {days} days.")
        return

    with open(OUT_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        # Pinterest bulk upload header
        writer.writerow(["Title", "Description", "Link", "Image URL", "Board"])

        for title, slug, niche, site_url, image_url, meta_desc in posts:
            niche_lower = (niche or "tech").lower()
            board = boards.get(niche_lower, boards.get("tech", "Tech & Gadgets News"))
            post_url = f"{site_url.rstrip('/')}/posts/{slug}.html"
            description = (meta_desc or f"Read about {title}") + f" #{niche_lower} #blogging"
            writer.writerow([title, description[:500], post_url, image_url or "", board])

    print(f"Generated {len(posts)} pins → {OUT_CSV}")
    print("Upload at: https://www.pinterest.com/pin-builder/bulk-create/")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate Pinterest bulk pins CSV")
    parser.add_argument("--days", type=int, default=7, help="Look back N days (default: 7)")
    args = parser.parse_args()
    generate_csv(args.days)
