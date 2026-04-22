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
Думай семантически: "рпг" -> "RPG game unity", "платформер" -> "platformer game unity".
Если запрос не связан с играми или разработкой — ответь только: INVALID
Верни ТОЛЬКО один запрос (2-5 слов на английском) или INVALID, без пояснений."""
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
        return "Описание отсутствует"
    russian_chars = sum(1 for c in text if "а" <= c <= "я" or "А" <= c <= "Я")
    if russian_chars > len(text) * 0.5:
        return text
    result = _ask(
        "Переведи описание Unity-репозитория на русский язык. "
        "Переводи ВСЕГДА. "
        "1 предложение в оригинале — 1 в переводе, больше — 2-3 предложения. "
        "Технические термины не переводи: Unity, GitHub, API, C#, UI, SDK, plugin, shader. "
        "Переводи с любого языка включая китайский, японский, корейский. "
        "Отвечай ТОЛЬКО переводом, без пояснений и кавычек.",
        text,
        max_tokens=150,
    )
    return result if result else text


def generate_title_and_author(repo_name: str, description: str, readme: str) -> tuple:
    parts = repo_name.split("/")
    raw_title = parts[-1].replace("-", " ").replace("_", " ").title() if len(parts) > 1 else repo_name
    raw_author = parts[0] if len(parts) > 1 else repo_name
    result = _ask(
        "Ты анализируешь Unity-репозиторий с GitHub. "
        "Верни ТОЛЬКО две строки:\n"
        "1) Красивое читаемое название проекта (если техническое — улучши).\n"
        "2) Имя или никнейм автора.\n"
        "Без пояснений, без кавычек, строго две строки.",
        f"Репозиторий: {repo_name}\nОписание: {description}\nREADME:\n{readme[:400]}",
        max_tokens=50,
    )
    lines = [l.strip() for l in result.strip().split("\n") if l.strip()]
    title = lines[0] if lines else raw_title
    author = lines[1] if len(lines) > 1 else raw_author
    return title, author
