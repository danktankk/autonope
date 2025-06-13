"""AutoNope core scheduler."""
from __future__ import annotations

import logging
import os
import pathlib
import sqlite3
import time
from typing import List

import requests
import schedule
import yaml

from autonope.config import Config, load as load_config
from autonope.notify import Notifier

DB_PATH = os.getenv("AUTONOPE_DB", "db/autonope.db")


# --------------------------------------------------------------------- #
# Database helpers
# --------------------------------------------------------------------- #

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


# --------------------------------------------------------------------- #
# GitHub helpers
# --------------------------------------------------------------------- #

def fetch_releases(repo: str) -> List[dict]:
    resp = requests.get(
        f"https://api.github.com/repos/{repo}/releases",
        headers={"Accept": "application/vnd.github+json"},
        timeout=20,
    )
    resp.raise_for_status()
    return resp.json()


# --------------------------------------------------------------------- #
# docker-compose helpers
# --------------------------------------------------------------------- #

def compose_has_autonope() -> bool:
    """Return True if any compose service is labelled with 'autonope'."""
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


# --------------------------------------------------------------------- #
# Core check
# --------------------------------------------------------------------- #

def check_repo(repo_cfg, con: sqlite3.Connection, notifier: Notifier) -> None:
    repo_name = repo_cfg.repo
    keywords = [k.lower() for k in repo_cfg.break_keywords]

    cur = con.cursor()
    cur.execute("SELECT last_release_id FROM checks WHERE repo=?", (repo_name,))
    row = cur.fetchone()
    last_seen = row[0] if row else 0

    releases = fetch_releases(repo_name)
    for rel in releases:
        rid = rel.get("id", 0)
        if rid <= last_seen:
            break

        blob = f"{rel.get('name')}\n{rel.get('body', '')}".lower()
        if any(k in blob for k in keywords) and compose_has_autonope():
            notifier.send(
                f"AutoNope: breaking change in {repo_name}",
                rel.get("html_url", ""),
            )
            logging.warning("Breaking change detected for %s", repo_name)
            break

    newest = releases[0].get("id", last_seen) if releases else last_seen
    cur.execute(
        "INSERT OR REPLACE INTO checks (repo, last_release_id) VALUES (?, ?)",
        (repo_name, newest),
    )
    con.commit()


# --------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------- #

def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s"
    )

    cfg: Config = load_config()
    notifier = Notifier(cfg.notify_channels)
    con = init_db()

    default_hours = Config.parse_interval(cfg.check_interval)
    for repo_cfg in cfg.repos:
        hours = (
            Config.parse_interval(repo_cfg.interval)
            if repo_cfg.interval
            else default_hours
        )
        schedule.every(hours).hours.do(check_repo, repo_cfg, con, notifier)

    logging.info("AutoNope started; tasks scheduled.")
    while True:
        schedule.run_pending()
        time.sleep(30)


if __name__ == "__main__":
    main()
