#!/usr/bin/env python3
"""
Emit config.yml repo stanzas by scanning docker-compose files.

Usage:
    compose_to_yaml.py <root_dir>
"""

from __future__ import annotations

import pathlib
import re
import sys

import yaml


def main() -> None:
    if len(sys.argv) != 2:
        print("Usage: compose_to_yaml.py <root_dir>", file=sys.stderr)
        sys.exit(1)

    root = pathlib.Path(sys.argv[1])
    print("repos:")

    for compose_file in root.rglob("docker-compose.y*ml"):
        data = yaml.safe_load(compose_file.read_text())
        for svc in data.get("services", {}).values():
            image = svc.get("image", "")
            match = re.match(r"([^:/]+/[^:@]+)", image)  # owner/repo
            if match is None:
                continue

            repo = match.group(1)
            name = repo.split("/")[1]
            print(f"  - name: {name}")
            print(f"    repo: {repo}")
            print("    break_keywords: []")


if __name__ == "__main__":
    main()
