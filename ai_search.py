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
Пользователь описывает что хочет найти на любом языке.
Твоя задача — перевести это в короткий поисковый запрос для GitHub API (3-6 слов, на английском).
Если запрос не имеет смысла или не связан с играми/разработкой — ответь только словом: INVALID
Отвечай ТОЛЬКО запросом или INVALID, без пояснений."""

    result = _ask(system, user_input, max_tokens=30)
    if not result or result.upper() == "INVALID":
        return None
    # Убираем кавычки если AI добавил
    return result.strip('"\'')


def is_valid_search_query(query: str) -> bool:
    if len(query.strip()) < 2:
        return False
    result = translate_to_github_query(query)
    return result is not None


def translate_description(text: str) -> str:
    if not text or text == "Описание отсутствует":
        return text
    # Проверяем нужен ли перевод (если текст уже на русском)
    russian_chars = sum(1 for c in text if "а" <= c <= "я" or "А" <= c <= "Я")
    if russian_chars > len(text) * 0.3:
        return text
    result = _ask(
        "Переведи текст на русский язык. Отвечай только переводом, без пояснений.",
        text,
        max_tokens=300,
    )
    return result if result else text
