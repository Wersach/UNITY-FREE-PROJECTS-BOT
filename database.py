import logging
import psycopg2
import psycopg2.extras
from config import DATABASE_URL

logger = logging.getLogger(__name__)


def _conn():
    return psycopg2.connect(DATABASE_URL)


def init_db():
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id BIGINT PRIMARY KEY,
                    username TEXT,
                    referred_by BIGINT DEFAULT NULL,
                    sub_until TIMESTAMP DEFAULT NULL,
                    daily_count INTEGER DEFAULT 0,
                    daily_date DATE DEFAULT CURRENT_DATE,
                    created_at TIMESTAMP DEFAULT NOW()
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS payments (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT,
                    inv_id INTEGER UNIQUE,
                    plan TEXT,
                    amount INTEGER,
                    status TEXT DEFAULT 'pending',
                    created_at TIMESTAMP DEFAULT NOW()
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS favorites (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT,
                    repo_url TEXT,
                    repo_name TEXT,
                    stars INTEGER,
                    added_at TIMESTAMP DEFAULT NOW(),
                    UNIQUE(user_id, repo_url)
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS notifications (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT,
                    query TEXT,
                    last_sent TIMESTAMP DEFAULT NOW()
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS seen_repos (
                    user_id BIGINT,
                    repo_url TEXT,
                    PRIMARY KEY (user_id, repo_url)
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS promo_codes (
                    code TEXT PRIMARY KEY,
                    days INTEGER,
                    max_uses INTEGER DEFAULT 1,
                    used_count INTEGER DEFAULT 0,
                    created_by BIGINT
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS promo_uses (
                    user_id BIGINT,
                    code TEXT,
                    PRIMARY KEY (user_id, code)
                )
            """)
        conn.commit()
    logger.info("БД инициализирована")


# ==================== ПОЛЬЗОВАТЕЛИ ====================

def get_user(user_id: int) -> dict | None:
    with _conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT * FROM users WHERE user_id = %s", (user_id,))
            row = cur.fetchone()
            return dict(row) if row else None


def create_user(user_id: int, username: str, referred_by: int = None):
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO users (user_id, username, referred_by)
                   VALUES (%s, %s, %s) ON CONFLICT (user_id) DO NOTHING""",
                (user_id, username, referred_by),
            )
        conn.commit()


def is_subscribed(user_id: int) -> bool:
    from datetime import datetime
    user = get_user(user_id)
    if not user:
        return False
    if user["sub_until"] and user["sub_until"] > datetime.now():
        return True
    return False


def add_subscription(user_id: int, days: int):
    from datetime import datetime, timedelta
    user = get_user(user_id)
    now = datetime.now()
    if user and user["sub_until"] and user["sub_until"] > now:
        new_until = user["sub_until"] + timedelta(days=days)
    else:
        new_until = now + timedelta(days=days)
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE users SET sub_until = %s WHERE user_id = %s",
                (new_until, user_id),
            )
        conn.commit()
    return new_until


def check_daily_limit(user_id: int, limit: int) -> bool:
    from datetime import date
    user = get_user(user_id)
    if not user:
        return False
    today = date.today()
    if user["daily_date"] != today:
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE users SET daily_count = 1, daily_date = %s WHERE user_id = %s",
                    (today, user_id),
                )
            conn.commit()
        return True
    if user["daily_count"] < limit:
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE users SET daily_count = daily_count + 1 WHERE user_id = %s",
                    (user_id,),
                )
            conn.commit()
        return True
    return False


def get_daily_used(user_id: int) -> int:
    from datetime import date
    user = get_user(user_id)
    if not user:
        return 0
    if user["daily_date"] != date.today():
        return 0
    return user["daily_count"]


# ==================== ПЛАТЕЖИ ====================

def create_payment(user_id: int, inv_id: int, plan: str, amount: int):
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO payments (user_id, inv_id, plan, amount)
                   VALUES (%s, %s, %s, %s)""",
                (user_id, inv_id, plan, amount),
            )
        conn.commit()


def get_payment(inv_id: int) -> dict | None:
    with _conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT * FROM payments WHERE inv_id = %s", (inv_id,))
            row = cur.fetchone()
            return dict(row) if row else None


def confirm_payment(inv_id: int):
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE payments SET status = 'paid' WHERE inv_id = %s",
                (inv_id,),
            )
        conn.commit()


# ==================== ИЗБРАННОЕ ====================

def add_favorite(user_id: int, repo_url: str, repo_name: str, stars: int):
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO favorites (user_id, repo_url, repo_name, stars)
                   VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING""",
                (user_id, repo_url, repo_name, stars),
            )
        conn.commit()


def get_favorites(user_id: int) -> list:
    with _conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT * FROM favorites WHERE user_id = %s ORDER BY added_at DESC",
                (user_id,),
            )
            return [dict(r) for r in cur.fetchall()]


def remove_favorite(user_id: int, repo_url: str):
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM favorites WHERE user_id = %s AND repo_url = %s",
                (user_id, repo_url),
            )
        conn.commit()


# ==================== РЕФЕРАЛЬНАЯ СИСТЕМА ====================

def get_referral_count(user_id: int) -> int:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM users WHERE referred_by = %s",
                (user_id,),
            )
            return cur.fetchone()[0]


# ==================== УВЕДОМЛЕНИЯ ====================

def add_notification(user_id: int, query: str):
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO notifications (user_id, query) VALUES (%s, %s)",
                (user_id, query),
            )
        conn.commit()


def get_all_notifications() -> list:
    with _conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT * FROM notifications")
            return [dict(r) for r in cur.fetchall()]


def update_notification_sent(notif_id: int):
    from datetime import datetime
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE notifications SET last_sent = %s WHERE id = %s",
                (datetime.now(), notif_id),
            )
        conn.commit()


def remove_notification(notif_id: int):
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM notifications WHERE id = %s", (notif_id,))
        conn.commit()


# ==================== СТАТИСТИКА ====================

def get_stats() -> dict:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM users")
            total = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM users WHERE sub_until > NOW()")
            subscribed = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM payments WHERE status = 'paid'")
            paid = cur.fetchone()[0]
            cur.execute("SELECT COALESCE(SUM(amount), 0) FROM payments WHERE status = 'paid'")
            revenue = cur.fetchone()[0]
    return {"total": total, "subscribed": subscribed, "paid": paid, "revenue": revenue}


# ==================== SEEN REPOS (без повторов) ====================

def is_repo_seen(user_id: int, repo_url: str) -> bool:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM seen_repos WHERE user_id = %s AND repo_url = %s", (user_id, repo_url))
            return cur.fetchone() is not None


def mark_repo_seen(user_id: int, repo_url: str):
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO seen_repos (user_id, repo_url) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                (user_id, repo_url),
            )
        conn.commit()


# ==================== ПРОМОКОДЫ ====================

def create_promo(code: str, days: int, max_uses: int, created_by: int):
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO promo_codes (code, days, max_uses, created_by)
                   VALUES (%s, %s, %s, %s) ON CONFLICT (code) DO NOTHING""",
                (code.upper(), days, max_uses, created_by),
            )
        conn.commit()


def use_promo(user_id: int, code: str) -> dict | None:
    code = code.upper()
    with _conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT * FROM promo_codes WHERE code = %s", (code,))
            promo = cur.fetchone()
            if not promo:
                return None
            promo = dict(promo)
            if promo["used_count"] >= promo["max_uses"]:
                return {"error": "expired"}
            cur.execute("SELECT 1 FROM promo_uses WHERE user_id = %s AND code = %s", (user_id, code))
            if cur.fetchone():
                return {"error": "already_used"}
            cur.execute("UPDATE promo_codes SET used_count = used_count + 1 WHERE code = %s", (code,))
            cur.execute("INSERT INTO promo_uses (user_id, code) VALUES (%s, %s)", (user_id, code))
        conn.commit()
    return promo


# ==================== ЭКСКЛЮЗИВНЫЕ РЕПО ====================

def add_exclusive(repo_url: str, repo_name: str, description: str, stars: int, added_by: int):
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO favorites (user_id, repo_url, repo_name, stars)
                   VALUES (-1, %s, %s, %s) ON CONFLICT DO NOTHING""",
                (repo_url, repo_name, stars),
            )
        conn.commit()


def get_exclusives() -> list:
    with _conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT * FROM favorites WHERE user_id = -1 ORDER BY added_at DESC",
            )
            return [dict(r) for r in cur.fetchall()]


def remove_exclusive(repo_url: str):
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM favorites WHERE user_id = -1 AND repo_url = %s",
                (repo_url,),
            )
        conn.commit()
