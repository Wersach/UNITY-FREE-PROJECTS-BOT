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


def _format_repo(item) -> dict:
    return {
        "name": item["full_name"],
        "url": item["html_url"],
        "description": item.get("description") or "Описание отсутствует",
        "stars": item.get("stargazers_count", 0),
        "language": item.get("language") or "C#",
        "updated": item.get("updated_at", "")[:10],
        "license": (item.get("license") or {}).get("spdx_id", "—"),
    }


def format_repo_text(repo: dict, index: int = None) -> str:
    prefix = f"{index}. " if index else ""
    return (
        f"{prefix}<b>{repo['name']}</b>\n"
        f"⭐ {repo['stars']} | 🗓 {repo['updated']} | 📄 {repo['license']}\n"
        f"<i>{repo['description'][:150]}</i>\n"
        f"🔗 {repo['url']}"
    )


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
    return _format_repo(items[0])


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
    return [_format_repo(item) for item in data["items"]]
