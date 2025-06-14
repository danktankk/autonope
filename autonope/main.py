"""AutoNope core scheduler with immediate run, global defaults, 404-auto-resolve, and
GitHub-search fallback so you don’t have to hand-label slugs."""

from __future__ import annotations

import json
import logging
import os
import pathlib
import re
import sqlite3
import subprocess
import time
from typing import Dict, List, Optional

import requests
import schedule
import yaml

DB_PATH     = os.getenv("AUTONOPE_DB", "db/autonope.db")
CONFIG_PATH = os.getenv("AUTONOPE_CONFIG", "config/config.yml")

# ---------------------------------------------------------------------------
# Common helpers
# ---------------------------------------------------------------------------
def gh_headers() -> dict:
    tok = (
        os.getenv("GITHUB_TOKEN")
        or os.getenv("GH_PAT")
        or os.getenv("GH_TOKEN")
    )
    h = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "autonope",
    }
    if tok:
        h["Authorization"] = f"token {tok}"
    return h


# ---------------------------------------------------------------------------
# Resolver helpers
# ---------------------------------------------------------------------------
LABEL_KEYS = [
    "org.opencontainers.image.source",
    "org.label-schema.vcs-url",
    "org.opencontainers.image.url",
]
GITHUB_RE = re.compile(r"github.com[:/](?P<owner>[^/]+)/(?P<repo>[^/.]+)")


def resolve_repo(image: str) -> Optional[str]:
    """Return <owner>/<repo> via labels, Hub API, or GitHub search."""
    if "/" not in image:
        return None
    owner, img = image.split("/", 1)

    # 1) OCI labels from local image
    try:
        inspect = subprocess.check_output(
            ["docker", "image", "inspect", image], text=True
        )
        labels = json.loads(inspect)[0]["Config"].get("Labels", {}) or {}
        for key in LABEL_KEYS:
            val = labels.get(key, "")
            m = GITHUB_RE.search(val)
            if m:
                return f"{m['owner']}/{m['repo']}"
    except Exception:
        pass

    # 2) Docker Hub API “source_repository” pointer
    try:
        data = requests.get(
            f"https://hub.docker.com/v2/repositories/{owner}/{img}/",
            timeout=10,
        ).json()
        src = (data or {}).get("source_repository", {})
        if src and src.get("provider") == "github":
            return src.get("full_name")
    except Exception:
        pass

    # 3) Heuristics + GitHub search: try common naming quirks
    candidates = {
        f"{owner}/{img}",
        f"{owner}/docker-{img}",
        f"{owner}/{img.replace('-', '_')}",
        f"{owner}/{img.replace('_', '-')}",
    }
    for cand in candidates:
        r = requests.get(
            f"https://api.github.com/repos/{cand}",
            headers=gh_headers(),
            timeout=10,
        )
        if r.status_code == 200:
            return cand

    # 4) Last-ditch: GitHub search inside the owner’s namespace
    try:
        r = requests.get(
            "https://api.github.com/search/repositories",
            headers=gh_headers(),
            params={"q": f"{img} in:name user:{owner}", "per_page": 1},
            timeout=20,
        )
        if r.status_code == 200 and r.json().get("items"):
            repo_name = r.json()["items"][0]["full_name"]
            return repo_name
    except Exception:
        pass

    return None


# ---------------------------------------------------------------------------
# Configuration helpers
# ---------------------------------------------------------------------------
def load_config() -> dict:
    with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def merge_repo_cfg(repo_cfg: Dict, global_cfg: Dict) -> Dict:
    return {
        "name": repo_cfg["name"],
        "repo": repo_cfg["repo"],
        "interval": repo_cfg.get("interval", global_cfg.get("check_interval", "24h")),
        "break_keywords": [
            k.lower()
            for k in repo_cfg.get("break_keywords", global_cfg.get("break_keywords", []))
        ],
    }


# ---------------------------------------------------------------------------
# DB helpers
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
    r = requests.get(
        f"https://api.github.com/repos/{repo}/releases",
        headers=gh_headers(),
        timeout=20,
    )
    r.raise_for_status()
    return r.json()


# ---------------------------------------------------------------------------
# Compose label helper
# ---------------------------------------------------------------------------
def compose_has_autonope() -> bool:
    for fname in ("docker-compose.yml", "docker-compose.yaml"):
        p = pathlib.Path(fname)
        if not p.exists():
            continue
        data = yaml.safe_load(p.read_text()) or {}
        for svc in data.get("services", {}).values():
            labels = svc.get("labels", {})
            if isinstance(labels, dict):
                labels = labels.values()
            if any(str(lbl).strip() == "autonope" for lbl in labels):
                return True
    return False


# ---------------------------------------------------------------------------
# Notify (stub)
# ---------------------------------------------------------------------------
def send_notification(title: str, body: str) -> None:
    logging.warning("%s — %s", title, body)


# ---------------------------------------------------------------------------
# Core check
# ---------------------------------------------------------------------------
def check_repo(repo: Dict, con: sqlite3.Connection) -> None:
    cur = con.cursor()
    cur.execute("SELECT last_release_id FROM checks WHERE repo=?", (repo["repo"],))
    row = cur.fetchone()
    last_seen = row[0] if row else 0

    try:
        releases = fetch_releases(repo["repo"])
    except requests.HTTPError as err:
        if err.response.status_code in (403, 404):
            corrected = resolve_repo(repo["repo"])
            if corrected:
                logging.warning("Resolved %s -> %s", repo["repo"], corrected)
                repo["repo"] = corrected
                releases = fetch_releases(corrected)
            else:
                logging.error("Unresolved repo for %s", repo["name"])
                return
        else:
            raise

    for rel in releases:
        rid = rel.get("id", 0)
        if rid <= last_seen:
            break
        blob = f"{rel.get('name')}\n{rel.get('body', '')}".lower()
        if any(k in blob for k in repo["break_keywords"]):
            if compose_has_autonope():
                send_notification(
                    f"AutoNope: breaking in {repo['name']}", rel.get("html_url", "")
                )
            break

    newest = releases[0].get("id", last_seen) if releases else last_seen
    cur.execute(
        "INSERT OR REPLACE INTO checks(repo,last_release_id) VALUES (?,?)",
        (repo["repo"], newest),
    )
    con.commit()


# ---------------------------------------------------------------------------
# Entry
# ---------------------------------------------------------------------------
def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    cfg = load_config()
    con = init_db()

    for repo_cfg in cfg.get("repos", []):
        eff = merge_repo_cfg(repo_cfg, cfg)
        hrs = int(eff["interval"].rstrip("hdw")) * {"h": 1, "d": 24, "w": 168}[
            eff["interval"][-1]
        ]
        schedule.every(hrs).hours.do(check_repo, eff, con)
        logging.info("Scheduled %s every %s", eff["name"], eff["interval"])
        check_repo(eff, con)  # immediate run

    logging.info("Initial scan complete; entering loop.")
    while True:
        schedule.run_pending()
        time.sleep(30)


if __name__ == "__main__":
    main()
