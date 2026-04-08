import os

# ==================== TELEGRAM ====================
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_ID = int(os.getenv("ADMIN_ID", "123456789"))

# ==================== GITHUB ====================
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")

# ==================== GROQ ====================
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = "llama-3.3-70b-versatile"

# ==================== ROBOKASSA ====================
ROBOKASSA_LOGIN = os.getenv("ROBOKASSA_LOGIN", "")
ROBOKASSA_PASSWORD1 = os.getenv("ROBOKASSA_PASSWORD1", "")
ROBOKASSA_PASSWORD2 = os.getenv("ROBOKASSA_PASSWORD2", "")
ROBOKASSA_TEST = os.getenv("ROBOKASSA_TEST", "1") == "1"

# ==================== БД ====================
DATABASE_URL = os.getenv("DATABASE_URL", "")

# ==================== ЛИМИТЫ ====================
FREE_DAILY_LIMIT = 5

# ==================== ПОДПИСКИ ====================
PLANS = {
    "week":    {"days": 7,   "price": 69,  "label": "7 дней — 69₽"},
    "month":   {"days": 30,  "price": 199, "label": "30 дней — 199₽"},
    "quarter": {"days": 90,  "price": 499, "label": "3 месяца — 499₽"},
}

# ==================== РЕФЕРАЛЬНАЯ СИСТЕМА ====================
REFERRAL_BONUS_DAYS = 3  # дней за каждого приглашённого

# ==================== КАНАЛ ====================
CHANNEL_USERNAME = os.getenv("CHANNEL_USERNAME", "unity_free_projects")
