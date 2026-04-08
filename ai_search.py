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
    russian_chars = sum(1 for c in text if "а" <= c <= "я" or "А" <= c <= "Я")
    if russian_chars > len(text) * 0.3:
        return text
    result = _ask(
        "Переведи текст на русский язык. "
        "Если описание слишком короткое — дополни его 2-3 предложениями на основе названия. "
        "Итоговый текст должен быть 2-4 предложения. "
        "Отвечай ТОЛЬКО переводом/текстом, без пояснений и кавычек. "
        "Переводи с любого языка включая китайский, японский, корейский.",
        text,
        max_tokens=300,
    )
    return result if result else text


def generate_title_and_author(repo_name: str, description: str, readme: str) -> tuple:
    """Возвращает (название игры/проекта, имя автора)"""
    result = _ask(
        "Ты анализируешь Unity-репозиторий с GitHub. "
        "Верни ТОЛЬКО две строки: первая — красивое название игры или проекта (не технический slug, а читаемое имя). "
        "Вторая — имя автора (из README или username из названия репозитория). "
        "Без пояснений, без кавычек, строго две строки.",
        f"Репозиторий: {repo_name}\nОписание: {description}\nREADME (начало):\n{readme[:500]}",
        max_tokens=60,
    )
    lines = [l.strip() for l in result.strip().split("\n") if l.strip()]
    title = lines[0] if lines else repo_name.split("/")[-1].replace("-", " ").title()
    author = lines[1] if len(lines) > 1 else repo_name.split("/")[0]
    return title, author
