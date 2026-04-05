import re
import random
import logging
import requests
import base64
from config import GITHUB_TOKEN

logger = logging.getLogger(__name__)

HEADERS = {"Accept": "application/vnd.github+json"}
if GITHUB_TOKEN:
    HEADERS["Authorization"] = f"Bearer {GITHUB_TOKEN}"


def _get(url, params=None):
    try:
        resp = requests.get(url, headers=HEADERS, params=params, timeout=15)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        logger.error(f"[GitHub] Ошибка: {e}")
        return None


def _get_readme(owner, repo):
    data = _get(f"https://api.github.com/repos/{owner}/{repo}/readme")
    if not data:
        return ""
    try:
        return base64.b64decode(data.get("content", "")).decode("utf-8", errors="ignore")
    except Exception:
        return ""


def _find_screenshot(readme, owner, repo):
    skip = ["badge", "shield", "icon", "logo", "travis", "codecov", "workflow", "license"]
    for m in re.finditer(r"!\[[^\]]*\]\(([^)\s]+\.(?:png|jpg|jpeg|gif|webp))[^)]*\)", readme, re.IGNORECASE):
        path = m.group(1).strip()
        if not path.startswith("http"):
            path = f"https://raw.githubusercontent.com/{owner}/{repo}/HEAD/{path.lstrip('./')}"
        if not any(s in path.lower() for s in skip):
            return path
    for m in re.finditer(r"https://(?:user-images\.githubusercontent\.com|raw\.githubusercontent\.com)/\S+", readme, re.IGNORECASE):
        url = m.group(0).rstrip(".,)\"'")
        if not any(s in url.lower() for s in skip):
            return url
    return None


def _format_repo(item, readme="", screenshot=None) -> dict:
    return {
        "name": item["full_name"],
        "url": item["html_url"],
        "description": item.get("description") or "Описание отсутствует",
        "stars": item.get("stargazers_count", 0),
        "language": item.get("language") or "C#",
        "updated": item.get("updated_at", "")[:10],
        "license": (item.get("license") or {}).get("spdx_id", "—"),
        "screenshot": screenshot,
    }


def random_repo() -> dict | None:
    page = random.randint(1, 10)
    query = "topic:unity topic:game stars:10..500 created:>2020-01-01 language:C#"
    data = _get(
        "https://api.github.com/search/repositories",
        params={"q": query, "sort": "updated", "order": "desc", "per_page": 10, "page": page},
    )
    if not data or not data.get("items"):
        return None
    items = data["items"]
    random.shuffle(items)
    item = items[0]
    owner, repo = item["owner"]["login"], item["name"]
    readme = _get_readme(owner, repo)
    screenshot = _find_screenshot(readme, owner, repo)
    return _format_repo(item, readme, screenshot)


def search_repos(query: str, stars_min: int = 0, stars_max: int = 10000,
                 updated_after: str = None, license_filter: str = None,
                 per_page: int = 5) -> list:
    q = f"{query} topic:unity language:C#"
    if stars_min or stars_max < 10000:
        q += f" stars:{stars_min}..{stars_max}"
    if updated_after:
        q += f" pushed:>{updated_after}"
    if license_filter:
        q += f" license:{license_filter}"
    data = _get(
        "https://api.github.com/search/repositories",
        params={"q": q, "sort": "stars", "order": "desc", "per_page": per_page},
    )
    if not data or not data.get("items"):
        return []
    results = []
    for item in data["items"]:
        owner, repo = item["owner"]["login"], item["name"]
        readme = _get_readme(owner, repo)
        screenshot = _find_screenshot(readme, owner, repo)
        results.append(_format_repo(item, readme, screenshot))
    return results
