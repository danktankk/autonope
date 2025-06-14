import json
import subprocess
import re
import requests

LABEL_KEYS = [
    "org.opencontainers.image.source",
    "org.label-schema.vcs-url",
    "org.opencontainers.image.url",
]
GITHUB_RE = re.compile(r"github.com[:/](?P<owner>[^/]+)/(?P<repo>[^/.]+)")


def from_labels(image: str) -> str | None:
    """Return owner/repo from OCI labels, or None."""
    try:
        inspect = subprocess.check_output(["docker", "image", "inspect", image])
        labels = json.loads(inspect)[0]["Config"].get("Labels", {})
    except Exception:
        return None

    for key in LABEL_KEYS:
        val = labels.get(key, "")
        m = GITHUB_RE.search(val)
        if m:
            return f"{m['owner']}/{m['repo'] }"
    return None


def from_docker_hub(owner: str, image: str) -> str | None:
    url = f"https://hub.docker.com/v2/repositories/{owner}/{image}/"
    try:
        data = requests.get(url, timeout=10).json()
        src = data.get("source_repository", {})
        if src and src.get("provider") == "github":
            return src["full_name"]
    except Exception:
        pass
    return None


def from_github_search(owner: str, img: str, gh_token: str | None = None) -> str | None:
    headers = {"Accept": "application/vnd.github+json"}
    if gh_token:
        headers["Authorization"] = f"Bearer {gh_token}"
    params = {"q": f"{img} in:name user:{owner}", "per_page": 1}
    try:
        r = requests.get("https://api.github.com/search/repositories", params=params, headers=headers, timeout=10)
        items = r.json().get("items", [])
        if items:
            return items[0]["full_name"]
    except Exception:
        pass
    return None


def resolve(image: str, gh_token: str | None = None) -> str | None:
    """Return owner/repo or None."""
    owner, img = image.split("/", 1)

    # 1) OCI labels
    repo = from_labels(image)
    if repo:
        return repo

    # 2) Docker Hub API
    repo = from_docker_hub(owner, img)
    if repo:
        return repo

    # 3) GitHub search fallback
    return from_github_search(owner, img, gh_token)
