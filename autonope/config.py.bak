"""Load config.yml and expose dataclasses."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any, Dict, List

import yaml

CONFIG_PATH = os.getenv("AUTONOPE_CONFIG", "config/config.yml")


@dataclass
class NotifyChannel:
    type: str
    params: Dict[str, Any]


@dataclass
class RepoCfg:
    name: str
    repo: str
    break_keywords: List[str]
    interval: str | None = None


@dataclass
class Config:
    check_interval: str
    notify_channels: List[NotifyChannel]
    repos: List[RepoCfg]

    @staticmethod
    def parse_interval(s: str) -> int:
        match = re.fullmatch(r"(\d+)([hdw])", s.strip())
        if not match:
            raise ValueError(f"Invalid interval: {s}")
        qty, unit = int(match.group(1)), match.group(2)
        return qty * {"h": 1, "d": 24, "w": 168}[unit]


def load() -> Config:
    with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)

    channels = [
        NotifyChannel(c["type"], {k: v for k, v in c.items() if k != "type"})
        for c in raw.get("notify", {}).get("channels", [])
    ]
    repos = [RepoCfg(**r) for r in raw.get("repos", [])]

    return Config(raw.get("check_interval", "24h"), channels, repos)
