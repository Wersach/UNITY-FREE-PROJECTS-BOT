import asyncio
import logging
import random
from datetime import datetime

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters,
)
from telegram.constants import ParseMode

import config
import database as db
from github_search import random_repo, search_repos
from ai_search import translate_to_github_query
from payments import generate_payment_url

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

WAITING_SEARCH = set()
WAITING_AI = set()
WAITING_NOTIF = set()
WAITING_PROMO = set()


# ============================================================
# КАРТОЧКА РЕПОЗИТОРИЯ
# ============================================================

WARNING_TEXT = "\n\n<i>⚠️ Бот может ошибаться. Всегда проверяйте репозиторий перед использованием.</i>"


async def send_repo_card(bot, chat_id: int, repo: dict, show_save: bool = True):
    text = (
        f"🎮 <b>{repo['name']}</b>\n\n"
        f"<blockquote>{repo['description'][:300]}</blockquote>\n\n"
        f"⭐ {repo['stars']}  |  🗓 {repo['updated']}  |  📄 {repo['license']}"
        + WARNING_TEXT
    )
    buttons = []
    if show_save:
        buttons.append([
            InlineKeyboardButton("⭐ В избранное", callback_data=f"save:{repo['url']}"),
            InlineKeyboardButton("🔗 GitHub", url=repo['url']),
        ])
    else:
        buttons.append([InlineKeyboardButton("🔗 GitHub", url=repo['url'])])

    keyboard = InlineKeyboardMarkup(buttons)
    screenshot = repo.get("screenshot")

    if screenshot:
        try:
            import requests as req, io
            r = req.get(screenshot, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
            r.raise_for_status()
            await bot.send_photo(
                chat_id=chat_id,
                photo=io.BytesIO(r.content),
                caption=text,
                parse_mode=ParseMode.HTML,
                reply_markup=keyboard,
            )
            return
        except Exception:
            pass

    await bot.send_message(
        chat_id=chat_id,
        text=text,
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard,
        disable_web_page_preview=True,
    )


# ============================================================
# КЛАВИАТУРЫ
# ============================================================

def main_menu(is_sub: bool) -> InlineKeyboardMarkup:
    if is_sub:
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("🎲 Случайный репо", callback_data="random")],
            [InlineKeyboardButton("🔍 Поиск", callback_data="search"),
             InlineKeyboardButton("🤖 AI-поиск", callback_data="ai_search")],
            [InlineKeyboardButton("⭐ Избранное", callback_data="favorites"),
             InlineKeyboardButton("🔔 Уведомления", callback_data="notifications")],
            [InlineKeyboardButton("👤 Профиль", callback_data="profile"),
             InlineKeyboardButton("📢 Канал", url="https://t.me/unity_free_projects")],
        ])
    else:
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("🎲 Случайный репо", callback_data="random")],
            [InlineKeyboardButton("💎 Получить подписку", callback_data="subscribe")],
            [InlineKeyboardButton("🎟 Промокод", callback_data="promo"),
             InlineKeyboardButton("👥 Реферал", callback_data="referral")],
            [InlineKeyboardButton("👤 Профиль", callback_data="profile"),
             InlineKeyboardButton("📢 Канал", url="https://t.me/unity_free_projects")],
        ])


def subscribe_keyboard() -> InlineKeyboardMarkup:
    buttons = []
    for key, plan in config.PLANS.items():
        buttons.append([InlineKeyboardButton(plan["label"], callback_data=f"buy:{key}")])
    buttons.append([InlineKeyboardButton("🎟 Промокод", callback_data="promo"),
                    InlineKeyboardButton("◀️ Назад", callback_data="back")])
    return InlineKeyboardMarkup(buttons)


# ============================================================
# СТАРТ
# ============================================================

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    args = context.args
    referred_by = None
    if args and args[0].startswith("ref"):
        try:
            referred_by = int(args[0][3:])
            if referred_by == user.id:
                referred_by = None
        except ValueError:
            pass

    existing = db.get_user(user.id)
    db.create_user(user.id, user.username or "", referred_by)

    if referred_by and not existing:
        db.add_subscription(referred_by, config.REFERRAL_BONUS_DAYS)
        try:
            await context.bot.send_message(
                chat_id=referred_by,
                text=f"🎉 По вашей ссылке зарегистрировался новый пользователь!\n"
                     f"+{config.REFERRAL_BONUS_DAYS} дней подписки.",
            )
        except Exception:
            pass

    is_sub = db.is_subscribed(user.id)
    await update.message.reply_text(
        f"👋 Привет, <b>{user.first_name}</b>!\n\n"
        f"Я помогаю находить Unity-проекты на GitHub.\n\n"
        f"{'✅ У вас активна подписка' if is_sub else f'🆓 Бесплатный план: {config.FREE_DAILY_LIMIT} случайных репо в день'}",
        parse_mode=ParseMode.HTML,
        reply_markup=main_menu(is_sub),
    )


# ============================================================
# CALLBACK
# ============================================================

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    data = query.data
    is_sub = db.is_subscribed(user_id)

    if data == "random":
        if not is_sub:
            if not db.check_daily_limit(user_id, config.FREE_DAILY_LIMIT):
                used = db.get_daily_used(user_id)
                await query.edit_message_text(
                    f"⛔ Дневной лимит исчерпан ({used}/{config.FREE_DAILY_LIMIT}).\n\n"
                    f"Оформите подписку для безлимитного доступа 👇",
                    reply_markup=subscribe_keyboard(),
                )
                return
        await query.edit_message_text("🎲 Ищу случайный репозиторий...")
        # Ищем репо которого пользователь ещё не видел
        for _ in range(5):
            repo = random_repo()
            if repo and not db.is_repo_seen(user_id, repo["url"]):
                break
        if not repo:
            await query.edit_message_text("😔 Не удалось найти репозиторий. Попробуйте ещё раз.")
            return
        db.mark_repo_seen(user_id, repo["url"])
        await send_repo_card(context.bot, user_id, repo, show_save=is_sub)
        await context.bot.send_message(
            chat_id=user_id,
            text="Главное меню 👇",
            reply_markup=main_menu(is_sub),
        )

    elif data == "search":
        if not is_sub:
            await query.edit_message_text(
                "🔍 Поиск доступен только по подписке.\n\nПолучите доступ 👇",
                reply_markup=subscribe_keyboard(),
            )
            return
        WAITING_SEARCH.add(user_id)
        await query.edit_message_text(
            "🔍 Введите поисковый запрос:\n\n"
            "<i>Примеры: roguelike, 2D platformer, horror</i>\n\n"
            "Фильтры через запятую:\n"
            "<i>roguelike, stars:50-500, updated:2023, license:MIT</i>",
            parse_mode=ParseMode.HTML,
        )

    elif data == "ai_search":
        if not is_sub:
            await query.edit_message_text(
                "🤖 AI-поиск доступен только по подписке.",
                reply_markup=subscribe_keyboard(),
            )
            return
        WAITING_AI.add(user_id)
        await query.edit_message_text(
            "🤖 Опишите что хотите найти:\n\n"
            "<i>— хочу платформер с процедурной генерацией\n"
            "— мобильная RPG с открытым кодом\n"
            "— шутер от первого лица для новичков</i>",
            parse_mode=ParseMode.HTML,
        )

    elif data == "subscribe":
        await query.edit_message_text(
            "💎 <b>Подписка Unity Search</b>\n\n"
            "✅ Безлимитный поиск\n"
            "✅ AI-поиск на естественном языке\n"
            "✅ Фильтры по звёздам, дате, лицензии\n"
            "✅ Избранные репозитории\n"
            "✅ Уведомления о новых проектах\n\n"
            "Выберите тариф:",
            parse_mode=ParseMode.HTML,
            reply_markup=subscribe_keyboard(),
        )

    elif data.startswith("buy:"):
        plan_key = data.split(":")[1]
        plan = config.PLANS.get(plan_key)
        if not plan:
            return
        inv_id = int(str(user_id)[-6:] + str(random.randint(100, 999)))
        db.create_payment(user_id, inv_id, plan_key, plan["price"])
        url = generate_payment_url(inv_id, plan["price"], f"Unity Search {plan['label']}")
        await query.edit_message_text(
            f"💳 Оплата: <b>{plan['label']}</b>\n\n"
            f"После оплаты подписка активируется автоматически.\n\n"
            f"<a href='{url}'>👉 Перейти к оплате</a>",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Назад", callback_data="subscribe")]]),
            disable_web_page_preview=True,
        )

    elif data == "promo":
        WAITING_PROMO.add(user_id)
        await query.edit_message_text(
            "🎟 Введите промокод:",
        )

    elif data == "profile":
        user = db.get_user(user_id)
        sub_until = user["sub_until"]
        if sub_until and sub_until > datetime.now():
            sub_text = f"✅ Активна до {sub_until.strftime('%d.%m.%Y')}"
        else:
            sub_text = "❌ Нет подписки"
        ref_count = db.get_referral_count(user_id)
        me = await context.bot.get_me()
        ref_link = f"https://t.me/{me.username}?start=ref{user_id}"
        await query.edit_message_text(
            f"👤 <b>Профиль</b>\n\n"
            f"🔑 ID: <code>{user_id}</code>\n"
            f"📅 Подписка: {sub_text}\n"
            f"👥 Рефералов: {ref_count} (+{ref_count * config.REFERRAL_BONUS_DAYS} дней)\n\n"
            f"Реферальная ссылка:\n<code>{ref_link}</code>",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("💎 Купить подписку", callback_data="subscribe")],
                [InlineKeyboardButton("◀️ Назад", callback_data="back")],
            ]),
        )

    elif data == "referral":
        ref_count = db.get_referral_count(user_id)
        me = await context.bot.get_me()
        ref_link = f"https://t.me/{me.username}?start=ref{user_id}"
        await query.edit_message_text(
            f"👥 <b>Реферальная программа</b>\n\n"
            f"За каждого приглашённого — <b>{config.REFERRAL_BONUS_DAYS} дня</b> подписки.\n\n"
            f"Ваших рефералов: <b>{ref_count}</b>\n"
            f"Заработано дней: <b>{ref_count * config.REFERRAL_BONUS_DAYS}</b>\n\n"
            f"Ваша ссылка:\n<code>{ref_link}</code>",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Назад", callback_data="back")]]),
        )

    elif data == "favorites":
        if not is_sub:
            await query.edit_message_text(
                "⭐ Избранное доступно только по подписке.",
                reply_markup=subscribe_keyboard(),
            )
            return
        favs = db.get_favorites(user_id)
        if not favs:
            await query.edit_message_text(
                "⭐ Избранное пусто.\n\nДобавляйте репозитории кнопкой ⭐",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Назад", callback_data="back")]]),
            )
            return
        await show_favorites_page(query, user_id, favs, page=0)

    elif data.startswith("fav_page:"):
        page = int(data.split(":")[1])
        favs = db.get_favorites(user_id)
        await show_favorites_page(query, user_id, favs, page=page)

    elif data.startswith("save:"):
        if not is_sub:
            await query.answer("⭐ Избранное доступно только по подписке.", show_alert=True)
            return
        repo_url = data[5:]
        repo_name = "/".join(repo_url.split("/")[-2:])
        db.add_favorite(user_id, repo_url, repo_name, 0)
        await query.answer("✅ Добавлено в избранное!")

    elif data.startswith("unfav:"):
        repo_url = data[6:]
        db.remove_favorite(user_id, repo_url)
        await query.answer("🗑 Удалено")
        favs = db.get_favorites(user_id)
        if not favs:
            await query.edit_message_text(
                "⭐ Избранное пусто.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Назад", callback_data="back")]]),
            )
        else:
            await show_favorites_page(query, user_id, favs, page=0)

    elif data == "notifications":
        if not is_sub:
            await query.edit_message_text(
                "🔔 Уведомления доступны только по подписке.",
                reply_markup=subscribe_keyboard(),
            )
            return
        WAITING_NOTIF.add(user_id)
        await query.edit_message_text(
            "🔔 Введите тему для уведомлений:\n\n"
            "<i>Примеры: roguelike, horror, 2D platformer</i>\n\n"
            "Бот будет присылать новые репозитории раз в день.",
            parse_mode=ParseMode.HTML,
        )

    elif data == "back":
        await query.edit_message_text(
            "Главное меню 👇",
            reply_markup=main_menu(is_sub),
        )


async def show_favorites_page(query, user_id: int, favs: list, page: int):
    total = len(favs)
    fav = favs[page]
    text = (
        f"⭐ <b>Избранное</b>  {page + 1}/{total}\n\n"
        f"<b>{fav['repo_name']}</b>\n"
        f"⭐ {fav['stars']}\n"
        f"🔗 {fav['repo_url']}"
    )
    buttons = []
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("◀️", callback_data=f"fav_page:{page - 1}"))
    nav.append(InlineKeyboardButton(f"{page + 1}/{total}", callback_data="noop"))
    if page < total - 1:
        nav.append(InlineKeyboardButton("▶️", callback_data=f"fav_page:{page + 1}"))
    buttons.append(nav)
    buttons.append([InlineKeyboardButton("🗑 Удалить", callback_data=f"unfav:{fav['repo_url']}")])
    buttons.append([InlineKeyboardButton("◀️ Назад", callback_data="back")])
    await query.edit_message_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(buttons),
        disable_web_page_preview=True,
    )


# ============================================================
# ТЕКСТ
# ============================================================

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()
    is_sub = db.is_subscribed(user_id)

    if user_id in WAITING_PROMO:
        WAITING_PROMO.discard(user_id)
        result = db.use_promo(user_id, text)
        if not result:
            await update.message.reply_text(
                "❌ Промокод не найден.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ В меню", callback_data="back")]]),
            )
        elif result.get("error") == "expired":
            await update.message.reply_text(
                "❌ Промокод больше не активен.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ В меню", callback_data="back")]]),
            )
        elif result.get("error") == "already_used":
            await update.message.reply_text(
                "❌ Вы уже использовали этот промокод.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ В меню", callback_data="back")]]),
            )
        else:
            until = db.add_subscription(user_id, result["days"])
            await update.message.reply_text(
                f"✅ Промокод активирован! +{result['days']} дней подписки.\n"
                f"Подписка до: {until.strftime('%d.%m.%Y')}",
                reply_markup=main_menu(True),
            )

    elif user_id in WAITING_SEARCH:
        WAITING_SEARCH.discard(user_id)
        await update.message.reply_text("🔍 Ищу...")
        parts = [p.strip() for p in text.split(",")]
        query_str = parts[0]
        stars_min, stars_max = 0, 10000
        updated_after = None
        license_filter = None
        for part in parts[1:]:
            if part.startswith("stars:"):
                try:
                    s = part[6:].split("-")
                    stars_min = int(s[0])
                    stars_max = int(s[1]) if len(s) > 1 else 10000
                except Exception:
                    pass
            elif part.startswith("updated:"):
                updated_after = part[8:] + "-01-01"
            elif part.startswith("license:"):
                license_filter = part[8:]
        results = search_repos(query_str, stars_min, stars_max, updated_after, license_filter)
        if not results:
            await update.message.reply_text(
                "😔 По вашему запросу репозитории не найдены.\nПопробуйте другие ключевые слова.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ В меню", callback_data="back")]]),
            )
            return
        await update.message.reply_text(f"🔍 Результаты по запросу <b>{query_str}</b>:", parse_mode=ParseMode.HTML)
        for repo in results:
            await send_repo_card(context.bot, user_id, repo, show_save=True)
            await asyncio.sleep(0.5)
        await update.message.reply_text("Главное меню 👇", reply_markup=main_menu(True))

    elif user_id in WAITING_AI:
        WAITING_AI.discard(user_id)
        await update.message.reply_text("🤖 Обрабатываю запрос...")
        github_query = translate_to_github_query(text)
        if not github_query:
            await update.message.reply_text(
                "😔 Не удалось понять запрос. Попробуйте описать подробнее.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ В меню", callback_data="back")]]),
            )
            return
        results = search_repos(github_query)
        if not results:
            await update.message.reply_text(
                "😔 По вашему запросу репозитории не найдены.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ В меню", callback_data="back")]]),
            )
            return
        await update.message.reply_text(f"🤖 Нашёл по запросу <b>{github_query}</b>:", parse_mode=ParseMode.HTML)
        for repo in results:
            await send_repo_card(context.bot, user_id, repo, show_save=True)
            await asyncio.sleep(0.5)
        await update.message.reply_text("Главное меню 👇", reply_markup=main_menu(True))

    elif user_id in WAITING_NOTIF:
        WAITING_NOTIF.discard(user_id)
        db.add_notification(user_id, text)
        await update.message.reply_text(
            f"✅ Буду присылать новые репозитории по теме: <b>{text}</b>",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ В меню", callback_data="back")]]),
        )
    else:
        await update.message.reply_text("Используйте меню 👇", reply_markup=main_menu(is_sub))


# ============================================================
# УВЕДОМЛЕНИЯ
# ============================================================

async def send_notifications(context: ContextTypes.DEFAULT_TYPE):
    notifs = db.get_all_notifications()
    for notif in notifs:
        if not db.is_subscribed(notif["user_id"]):
            continue
        results = search_repos(notif["query"], per_page=3)
        if not results:
            continue
        await context.bot.send_message(
            chat_id=notif["user_id"],
            text=f"🔔 Новые репозитории по теме <b>{notif['query']}</b>:",
            parse_mode=ParseMode.HTML,
        )
        for repo in results:
            try:
                await send_repo_card(context.bot, notif["user_id"], repo, show_save=True)
                await asyncio.sleep(0.5)
            except Exception as e:
                logger.error(f"[NOTIF] Ошибка: {e}")
        db.update_notification_sent(notif["id"])


# ============================================================
# КОМАНДЫ АДМИНИСТРАТОРА
# ============================================================

async def cmd_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != config.ADMIN_ID:
        return
    stats = db.get_stats()
    await update.message.reply_text(
        f"📊 <b>Статистика</b>\n\n"
        f"👥 Пользователей: {stats['total']}\n"
        f"💎 Активных подписок: {stats['subscribed']}\n"
        f"💳 Оплат: {stats['paid']}\n"
        f"💰 Выручка: {stats['revenue']}₽",
        parse_mode=ParseMode.HTML,
    )


async def cmd_give(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != config.ADMIN_ID:
        return
    args = context.args
    if len(args) != 2:
        await update.message.reply_text("Использование: /give [user_id] [days]")
        return
    try:
        uid = int(args[0])
        days = int(args[1])
        until = db.add_subscription(uid, days)
        await update.message.reply_text(f"✅ Пользователю {uid} добавлено {days} дней. До: {until.strftime('%d.%m.%Y')}")
    except Exception as e:
        await update.message.reply_text(f"Ошибка: {e}")


async def cmd_promo_create(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != config.ADMIN_ID:
        return
    args = context.args
    if len(args) < 2:
        await update.message.reply_text("Использование: /createpromo [код] [дней] [макс_использований=1]")
        return
    try:
        code = args[0].upper()
        days = int(args[1])
        max_uses = int(args[2]) if len(args) > 2 else 1
        db.create_promo(code, days, max_uses, update.effective_user.id)
        await update.message.reply_text(f"✅ Промокод создан: <code>{code}</code> — {days} дней, до {max_uses} использований", parse_mode=ParseMode.HTML)
    except Exception as e:
        await update.message.reply_text(f"Ошибка: {e}")


async def cmd_me(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != config.ADMIN_ID:
        return
    await update.message.reply_text(f"Ваш ID: <code>{update.effective_user.id}</code>", parse_mode=ParseMode.HTML)


# ============================================================
# ТОЧКА ВХОДА
# ============================================================

def main():
    db.init_db()
    app = Application.builder().token(config.BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("admin", cmd_admin))
    app.add_handler(CommandHandler("give", cmd_give))
    app.add_handler(CommandHandler("createpromo", cmd_promo_create))
    app.add_handler(CommandHandler("me", cmd_me))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    app.job_queue.run_repeating(send_notifications, interval=86400, first=60)

    logger.info("🤖 Unity Search Bot запущен")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
