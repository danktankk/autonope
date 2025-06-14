"""Configuration loader & helpers for AutoNope."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any, Dict, List

import yaml

CONFIG_PATH = os.getenv("AUTONOPE_CONFIG", "config/config.yml")


# -----------------------------------------------------------------------------
# Dataclasses
# -----------------------------------------------------------------------------
@dataclass
class NotifyChannel:
    type: str
    params: Dict[str, Any]


@dataclass
class RepoCfg:
    name: str
    repo: str
    break_keywords: List[str]
    interval: str  # already merged with global default


@dataclass
class Config:
    check_interval: str
    break_keywords: List[str]
    notify_channels: List[NotifyChannel]
    repos: List[RepoCfg]

    # Helper to turn “6h / 2d / 1w” into hours
    @staticmethod
    def parse_interval(s: str) -> int:
        m = re.fullmatch(r"(\d+)([hdw])", s.strip())
        if not m:
            raise ValueError(f"Invalid interval: {s}")
        qty, unit = int(m.group(1)), m.group(2)
        return qty * {"h": 1, "d": 24, "w": 168}[unit]


# -----------------------------------------------------------------------------
# Loader
# -----------------------------------------------------------------------------
def load() -> Config:
    """Read config/config.yml and merge global defaults with per-repo overrides."""
    with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)

    # Global defaults
    global_interval: str = raw.get("check_interval", "24h")
    global_keywords: List[str] = [
        kw.lower() for kw in raw.get("break_keywords", [])
    ]

    # Notification channels
    channels = [
        NotifyChannel(c["type"], {k: v for k, v in c.items() if k != "type"})
        for c in raw.get("notify", {}).get("channels", [])
    ]

    # Merge defaults into repo entries
    merged_repos: List[RepoCfg] = []
    for r in raw.get("repos", []):
        interval = r.get("interval", global_interval)
        keywords = [kw.lower() for kw in r.get("break_keywords", global_keywords)]
        merged_repos.append(
            RepoCfg(
                name=r["name"],
                repo=r["repo"],
                break_keywords=keywords,
                interval=interval,
            )
        )

    return Config(
        check_interval=global_interval,
        break_keywords=global_keywords,
        notify_channels=channels,
        repos=merged_repos,
    )
