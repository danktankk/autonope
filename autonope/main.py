"""AutoNope core scheduler with global‑default merging logic."""
from __future__ import annotations

import logging
import os
import pathlib
import sqlite3
import time
from typing import Dict, List

import requests
import schedule
import yaml

DB_PATH = os.getenv("AUTONOPE_DB", "db/autonope.db")
CONFIG_PATH = os.getenv("AUTONOPE_CONFIG", "config/config.yml")


# ---------------------------------------------------------------------------
# Configuration helpers
# ---------------------------------------------------------------------------

def load_config() -> dict:
    with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def merge_repo_cfg(repo_cfg: Dict, global_cfg: Dict) -> Dict:
    """Merge per‑repo overrides with global defaults."""
    return {
        "name": repo_cfg["name"],
        "repo": repo_cfg["repo"],
        "interval": repo_cfg.get("interval", global_cfg.get("check_interval", "24h")),
        "break_keywords": [k.lower() for k in repo_cfg.get("break_keywords", global_cfg.get("break_keywords", []))],
    }


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

def init_db() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH)
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS checks (
            repo TEXT PRIMARY KEY,
            last_release_id INTEGER
        )
        """
    )
    con.commit()
    return con


# ---------------------------------------------------------------------------
# GitHub helpers
# ---------------------------------------------------------------------------

def fetch_releases(repo: str) -> List[dict]:
    resp = requests.get(
        f"https://api.github.com/repos/{repo}/releases",
        headers={"Accept": "application/vnd.github+json"},
        timeout=20,
    )
    resp.raise_for_status()
    return resp.json()


# ---------------------------------------------------------------------------
# Compose helpers (label check)
# ---------------------------------------------------------------------------

def compose_has_autonope() -> bool:
    for fname in ("docker-compose.yml", "docker-compose.yaml"):
        path = pathlib.Path(fname)
        if not path.exists():
            continue
        data = yaml.safe_load(path.read_text())
        for svc in data.get("services", {}).values():
            labels = svc.get("labels", [])
            if isinstance(labels, dict):
                labels = labels.values()
            if any(str(lbl).strip() == "autonope" for lbl in labels):
                return True
    return False


# ---------------------------------------------------------------------------
# Notification plumbing (minimal)
# ---------------------------------------------------------------------------

def send_notification(title: str, body: str) -> None:  # stub for brevity
    logging.warning("%s — %s", title, body)


# ---------------------------------------------------------------------------
# Core check
# ---------------------------------------------------------------------------

def check_repo(repo: Dict, con: sqlite3.Connection) -> None:
    cur = con.cursor()
    cur.execute("SELECT last_release_id FROM checks WHERE repo=?", (repo["repo"],))
    row = cur.fetchone()
    last_seen = row[0] if row else 0

    for rel in fetch_releases(repo["repo"]):
        rid = rel.get("id", 0)
        if rid <= last_seen:
            break
        blob = f"{rel.get('name')}\n{rel.get('body', '')}".lower()
        if any(kw in blob for kw in repo["break_keywords"]):
            if compose_has_autonope():
                send_notification(
                    f"AutoNope: breaking in {repo['name']}", rel.get("html_url", "")
                )
            break

    newest = fetch_releases(repo["repo"])[0].get("id", last_seen)
    cur.execute(
        "INSERT OR REPLACE INTO checks(repo,last_release_id) VALUES (?,?)",
        (repo["repo"], newest),
    )
    con.commit()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    cfg = load_config()
    con = init_db()

    for repo in cfg.get("repos", []):
        effective = merge_repo_cfg(repo, cfg)
        hours = int(effective["interval"].rstrip("hdw")) * {"h": 1, "d": 24, "w": 168}[effective["interval"][-1]]
        schedule.every(hours).hours.do(check_repo, effective, con)
        logging.info("Scheduled %s every %s", effective["name"], effective["interval"])

    while True:
        schedule.run_pending()
        time.sleep(30)


if __name__ == "__main__":
    main()
