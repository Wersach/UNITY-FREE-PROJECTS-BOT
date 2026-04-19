import logging
import requests
from config import GROQ_API_KEY, GROQ_MODEL

logger = logging.getLogger(__name__)
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"


def _ask(system: str, user: str, max_tokens: int = 200) -> str:
    try:
        resp = requests.post(
            GROQ_URL,
            headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
            json={
                "model": GROQ_MODEL,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "max_tokens": max_tokens,
                "temperature": 0.3,
            },
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        logger.error(f"[AI] Ошибка: {e}")
        return ""


def translate_to_github_query(user_input: str) -> str | None:
    system = """Ты помогаешь искать Unity-репозитории на GitHub.
Пользователь описывает что хочет найти — на любом языке, любыми словами.
Твоя задача — придумать несколько вариантов поискового запроса для GitHub API.

Правила:
- Запрос должен быть на английском, 2-5 слов
- Думай семантически: "рпг" → "RPG game unity", "платформер" → "platformer game unity", "стрелялка" → "shooter game unity"
- Если запрос совсем не связан с играми или разработкой — ответь только: INVALID
- Верни ТОЛЬКО один лучший запрос, без пояснений и кавычек"""

    result = _ask(system, user_input, max_tokens=20)
    if not result or result.upper() == "INVALID":
        return None
    return result.strip('"\'')


def is_valid_search_query(query: str) -> bool:
    if len(query.strip()) < 2:
        return False
    result = translate_to_github_query(query)
    return result is not None


def translate_description(text: str) -> str:
    if not text or text == "Описание отсутствует":
        return text
    russian_chars = sum(1 for c in text if "а" <= c <= "я" or "А" <= c <= "Я")
    if russian_chars > len(text) * 0.3:
        words = text.split()
        return " ".join(words[:30]) + ("..." if len(words) > 30 else "")
    result = _ask(
        "Переведи описание репозитория на русский язык. "
        "Итог — 1-3 предложения, понятно и по сути. "
        "Технические термины (Unity, GitHub, API, C#, UI и т.п.) не переводи. "
        "Переводи с любого языка включая китайский, японский, корейский. "
        "Отвечай ТОЛЬКО переводом, без пояснений и кавычек.",
        text,
        max_tokens=120,
    )
    if result:
        return result
    return text


def generate_title_and_author(repo_name: str, description: str, readme: str) -> tuple:
    parts = repo_name.split("/")
    raw_title = parts[-1].replace("-", " ").replace("_", " ").title() if len(parts) > 1 else repo_name
    raw_author = parts[0] if len(parts) > 1 else repo_name

    result = _ask(
        "Ты анализируешь Unity-репозиторий с GitHub. "
        "Верни ТОЛЬКО две строки:\n"
        "1) Красивое читаемое название проекта на русском или английском "
        "(если название техническое — переведи или улучши, если уже красивое — оставь). "
        "Не добавляй слово Unity.\n"
        "2) Имя или никнейм автора (возьми из username репозитория или README).\n"
        "Без пояснений, без кавычек, строго две строки.",
        f"Репозиторий: {repo_name}\nОписание: {description}\nREADME:\n{readme[:400]}",
        max_tokens=50,
    )
    lines = [l.strip() for l in result.strip().split("\n") if l.strip()]
    title = lines[0] if lines else raw_title
    author = lines[1] if len(lines) > 1 else raw_author
    return title, author
