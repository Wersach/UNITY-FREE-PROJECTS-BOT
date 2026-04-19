import logging
import requests
from config import GROQ_API_KEY, GROQ_MODEL
import os

logger = logging.getLogger(__name__)

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent"
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")


def _ask(prompt: str, max_tokens: int = 200) -> str:
    try:
        resp = requests.post(
            f"{GEMINI_URL}?key={GEMINI_API_KEY}",
            headers={"Content-Type": "application/json"},
            json={
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {
                    "maxOutputTokens": max_tokens,
                    "temperature": 0.3,
                },
            },
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
    except Exception as e:
        logger.error(f"[AI] Ошибка: {e}")
        return ""


def translate_to_github_query(user_input: str) -> str | None:
    prompt = (
        "Ты помогаешь искать Unity-репозитории на GitHub.\n"
        "Пользователь описывает что хочет найти — на любом языке, любыми словами.\n"
        "Переведи это в короткий поисковый запрос для GitHub API (2-5 слов, на английском).\n"
        "Думай семантически: 'рпг' → 'RPG game unity', 'платформер' → 'platformer game unity'.\n"
        "Если запрос не связан с играми или разработкой — ответь только: INVALID\n"
        "Верни ТОЛЬКО запрос или INVALID, без пояснений.\n\n"
        f"Запрос пользователя: {user_input}"
    )
    result = _ask(prompt, max_tokens=20)
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
    prompt = (
        "Переведи описание Unity-репозитория на русский язык.\n"
        "Правила:\n"
        "1) Переводи ВСЕГДА — даже если текст короткий.\n"
        "2) Если в оригинале 1 предложение — переведи 1. Если больше — дай 2-3 предложения.\n"
        "3) Технические термины не переводи: Unity, GitHub, API, C#, UI, SDK, plugin, framework, shader.\n"
        "4) Переводи с любого языка включая китайский, японский, корейский.\n"
        "5) Отвечай ТОЛЬКО переводом, без пояснений и кавычек.\n\n"
        f"Текст: {text}"
    )
    result = _ask(prompt, max_tokens=150)
    if result:
        return result
    return text


def generate_title_and_author(repo_name: str, description: str, readme: str) -> tuple:
    parts = repo_name.split("/")
    raw_title = parts[-1].replace("-", " ").replace("_", " ").title() if len(parts) > 1 else repo_name
    raw_author = parts[0] if len(parts) > 1 else repo_name

    prompt = (
        "Ты анализируешь Unity-репозиторий с GitHub.\n"
        "Верни ТОЛЬКО две строки:\n"
        "1) Красивое читаемое название проекта на русском или английском "
        "(если название техническое — переведи или улучши, если уже красивое — оставь). "
        "Не добавляй слово Unity.\n"
        "2) Имя или никнейм автора (возьми из username репозитория или README).\n"
        "Без пояснений, без кавычек, строго две строки.\n\n"
        f"Репозиторий: {repo_name}\nОписание: {description}\nREADME:\n{readme[:400]}"
    )
    result = _ask(prompt, max_tokens=50)
    lines = [l.strip() for l in result.strip().split("\n") if l.strip()]
    title = lines[0] if lines else raw_title
    author = lines[1] if len(lines) > 1 else raw_author
    return title, author
