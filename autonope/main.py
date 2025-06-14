"""AutoNope core scheduler – selectable log levels (OFF, ERROR, INFO, DEBUG, TRACE)
plus an aggressive GitHub-repo auto-resolver so you rarely have to label images.

Save as /app/autonope/main.py, rebuild your image with --no-cache, and run.
"""
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

###############################################################################
# Config paths
###############################################################################
DB_PATH: str = os.getenv("AUTONOPE_DB", "db/autonope.db")
CONFIG_PATH: str = os.getenv("AUTONOPE_CONFIG", "config/config.yml")

###############################################################################
# Logging helpers – adds TRACE level + module-level logging.trace()
###############################################################################
TRACE = 5
logging.addLevelName(TRACE, "TRACE")


def _trace(self: logging.Logger, msg: str, *args, **kwargs) -> None:  # noqa: D401
    if self.isEnabledFor(TRACE):
        self._log(TRACE, msg, args, **kwargs)


def _root_trace(msg: str, *args, **kwargs) -> None:
    logging.log(TRACE, msg, *args, **kwargs)


logging.Logger.trace = _trace  # type: ignore[attr-defined]
logging.trace = _root_trace    # type: ignore[attr-defined]

_LEVEL_MAP = {
    "OFF": logging.CRITICAL + 1,
    "ERROR": logging.ERROR,
    "INFO": logging.INFO,
    "DEBUG": logging.DEBUG,
    "TRACE": TRACE,
}


def configure_logging(cfg: dict) -> None:
    lvl_str = (os.getenv("AUTONOPE_LOG_LEVEL") or cfg.get("log_level", "INFO")).upper()
    lvl = _LEVEL_MAP.get(lvl_str, logging.INFO)
    logging.basicConfig(level=lvl, format="%(asctime)s %(levelname)s %(message)s")
    logging.debug("Log level set to %s (%s)", lvl_str, lvl)

###############################################################################
# GitHub helpers
###############################################################################

def gh_headers() -> dict:
    token = os.getenv("GITHUB_TOKEN") or os.getenv("GH_PAT") or os.getenv("GH_TOKEN")
    hdr = {"Accept": "application/vnd.github+json", "User-Agent": "autonope"}
    if token:
        hdr["Authorization"] = f"token {token}"
    return hdr


def fetch_releases(repo: str) -> List[dict]:
    logging.trace("Fetching releases for %s", repo)
    r = requests.get(f"https://api.github.com/repos/{repo}/releases", headers=gh_headers(), timeout=20)
    r.raise_for_status()
    return r.json()

###############################################################################
# Image-»repo auto-resolver (labels → Hub API → heuristics → GH search)
###############################################################################
LABEL_KEYS = [
    "org.opencontainers.image.source",
    "org.label-schema.vcs-url",
    "org.opencontainers.image.url",
]
GITHUB_RE = re.compile(r"github.com[:/](?P<owner>[^/]+)/(?P<repo>[^/.]+)")


def resolve_repo(image: str) -> Optional[str]:
    if "/" not in image:
        return None
    owner, img = image.split("/", 1)

    # 1) OCI labels from local image (if present)
    try:
        insp = subprocess.check_output(["docker", "image", "inspect", image], text=True)
        labels = json.loads(insp)[0]["Config"].get("Labels", {}) or {}
        for key in LABEL_KEYS:
            m = GITHUB_RE.search(labels.get(key, ""))
            if m:
                cand = f"{m['owner']}/{m['repo']}"
                logging.debug("Label resolved %s -> %s", image, cand)
                return cand
    except Exception:  # noqa: BLE001
        pass

    # 2) Docker Hub source_repository pointer
    try:
        r = requests.get(f"https://hub.docker.com/v2/repositories/{owner}/{img}/", timeout=10)
        if r.ok:
            src = (r.json() or {}).get("source_repository", {})
            if src.get("provider") == "github":
                cand = src.get("full_name")
                logging.debug("Hub resolved %s -> %s", image, cand)
                return cand
    except Exception:  # noqa: BLE001
        pass

    # 3) Quick heuristic variants
    variants = {
        f"{owner}/{img}",
        f"{owner}/docker-{img}",
        f"{owner}/{img.replace('-', '_')}",
        f"{owner}/{img.replace('_', '-')}",
    }
    for cand in variants:
        if requests.get(f"https://api.github.com/repos/{cand}", headers=gh_headers(), timeout=10).status_code == 200:
            logging.debug("Heuristic resolved %s -> %s", image, cand)
            return cand

    # 4) GitHub search (last resort, 1 result)
    try:
        r = requests.get(
            "https://api.github.com/search/repositories",
            headers=gh_headers(),
            params={"q": f"{img} in:name user:{owner}", "per_page": 1},
            timeout=20,
        )
        items = (r.json() or {}).get("items", [])
        if items:
            cand = items[0]["full_name"]
            logging.debug("Search resolved %s -> %s", image, cand)
            return cand
    except Exception:  # noqa: BLE001
        pass

    logging.trace("Failed to resolve repo for %s", image)
    return None

###############################################################################
# YAML + DB helpers
###############################################################################

def load_config() -> dict:
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
            return yaml.safe_load(fh) or {}
    except FileNotFoundError:
        return {}


def merge_repo_cfg(repo_cfg: Dict, global_cfg: Dict) -> Dict:
    return {
        "name": repo_cfg["name"],
        "repo": repo_cfg["repo"],
        "interval": repo_cfg.get("interval", global_cfg.get("check_interval", "24h")),
        "break_keywords": [k.lower() for k in repo_cfg.get("break_keywords", global_cfg.get("break_keywords", []))],
    }


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

###############################################################################
# Compose marker helper (for desktop notification integration)
###############################################################################

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

###############################################################################
# Notify (stub)
###############################################################################

def send_notification(title: str, body: str) -> None:  # noqa: D401
    logging.warning("%s — %s", title, body)

###############################################################################
# Core checker
###############################################################################

def check_repo(repo: Dict, con: sqlite3.Connection) -> None:
    cur = con.cursor()
    cur.execute("SELECT last_release_id FROM checks WHERE repo=?", (repo["repo"],))
    row = cur.fetchone()
    last_seen = row[0] if row else 0

    # ------------------------------------------------------------------
    # Fetch release list (auto-resolve 403/404 to new repo if possible)
    # ------------------------------------------------------------------
    try:
        releases = fetch_releases(repo["repo"])
    except requests.HTTPError as err:
        if err.response.status_code in (403, 404):
            corrected = resolve_repo(repo["repo"])
            if corrected:
                logging.info("Resolved %s -> %s", repo["repo"], corrected)
                repo["repo"] = corrected
                releases = fetch_releases(corrected)
            else:
                logging.error("Unresolved repo for %s", repo["name"])
                return
        else:
            raise

    # ------------------------------------------------------------------
    # Scan new releases for break keywords
    # ------------------------------------------------------------------
    for rel in releases:
        rid = rel.get("id", 0)
        if rid <= last_seen:
            break
        blob = f"{rel.get('name', '')}\n{rel.get('body', '')}".lower()
        if any(k in blob for k in repo["break_keywords"]):
            if compose_has_autonope():
                send_notification(
                    f"AutoNope: breaking change in {repo['name']}",
                    rel.get("html_url", ""),
                )
            break

    newest = releases[0].get("id", last_seen) if releases else last_seen
    cur.execute(
        "INSERT OR REPLACE INTO checks(repo,last_release_id) VALUES (?,?)",
        (repo["repo"], newest),
    )
    con.commit()

###############################################################################
# Entry point
###############################################################################

def main() -> None:  # noqa: D401
    cfg = load_config()
    configure_logging(cfg)
    con = init_db()

    for repo_cfg in cfg.get("repos", []):
        eff = merge_repo_cfg(repo_cfg, cfg)
        hours = int(eff["interval"].rstrip("hdw")) * {"h": 1, "d": 24, "w": 168}[eff["interval"][-1]]
        schedule.every(hours).hours.do(check_repo, eff, con)
        logging.info("Scheduled %s every %s", eff["name"], eff["interval"])
        check_repo(eff, con)  # immediate first run

    logging.info("Initial scan complete; entering loop.")
    while True:
        schedule.run_pending()
        time.sleep(30)


if __name__ == "__main__":
    main()
