"""Resolve a Docker image to its GitHub <owner>/<repo>."""
from __future__ import annotations

import json
import re
import subprocess
from typing import Optional

import requests

LABEL_KEYS = [
    "org.opencontainers.image.source",
    "org.label-schema.vcs-url",
    "org.opencontainers.image.url",
]
GITHUB_RE = re.compile(r"github.com[:/](?P<owner>[^/]+)/(?P<repo>[^/.]+)")


def _from_labels(image: str) -> Optional[str]:
    """Try to read OCI labels for repo URL."""
    try:
        out = subprocess.check_output(["docker", "image", "inspect", image], text=True)
        labels = json.loads(out)[0]["Config"].get("Labels", {})
    except Exception:
        return None

    for key in LABEL_KEYS:
        val = labels.get(key, "")
        m = GITHUB_RE.search(val)
        if m:
            return f"{m['owner']}/{m['repo']}"
    return None


def _from_docker_hub(owner: str, image: str) -> Optional[str]:
    url = f"https://hub.docker.com/v2/repositories/{owner}/{image}/"
    try:
        data = requests.get(url, timeout=10).json()
        src = data.get("source_repository", {})
        if src and src.get("provider") == "github":
            return src["full_name"]
    except Exception:
        pass
    return None


def resolve(image: str, gh_token: str | None = None) -> Optional[str]:
    """Return <owner>/<repo> or None."""
    if "/" not in image:
        return None

    owner, img = image.split("/", 1)

    repo = _from_labels(image)
    if repo:
        return repo

    return _from_docker_hub(owner, img)
