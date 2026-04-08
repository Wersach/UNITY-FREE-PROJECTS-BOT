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
from github_search import random_repo, search_repos, get_repo_by_url, get_top_weekly
from ai_search import translate_to_github_query, translate_description, generate_title_and_author
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
WAITING_URL = set()

WARNING_TEXT = "\n\n<i>⚠️ Бот может ошибаться. Проверяйте репозиторий перед использованием.</i>"


# ============================================================
# КАРТОЧКА РЕПОЗИТОРИЯ
# ============================================================

async def send_repo_card(bot, chat_id: int, repo: dict, show_save: bool = True, translate: bool = True):
    description = repo["description"]
    readme = repo.get("readme", "")

    if translate:
        title, author = generate_title_and_author(repo["name"], description, readme)
        description = translate_description(description)
    else:
        parts = repo["name"].split("/")
        title = parts[-1].replace("-", " ").replace("_", " ").title()
        author = parts[0] if len(parts) > 1 else repo["name"]

    text = (
        f"<b>{title}</b> | <b>{author}</b>\n\n"
        f"<blockquote>{description[:300]}</blockquote>\n\n"
        f"⭐ <b>{repo['stars']}</b>\n"
        f"📅 <b>{repo['updated']}</b>\n"
        f"📄 <b>{repo['license']}</b>\n\n"
        f"🔗 <b>{repo['url']}</b>"
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
             InlineKeyboardButton("💎 Эксклюзив", callback_data="exclusive")],
            [InlineKeyboardButton("🏆 Топ недели", callback_data="top_weekly"),
             InlineKeyboardButton("🔗 Репо по ссылке", callback_data="by_url")],
            [InlineKeyboardButton("👤 Профиль", callback_data="profile"),
             InlineKeyboardButton("📢 Канал", url=f"https://t.me/{config.CHANNEL_USERNAME}")],
        ])
    else:
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("🎲 Случайный репо", callback_data="random")],
            [InlineKeyboardButton("⭐ Избранное", callback_data="favorites"),
             InlineKeyboardButton("🔗 Репо по ссылке", callback_data="by_url")],
            [InlineKeyboardButton("💎 Получить подписку", callback_data="subscribe")],
            [InlineKeyboardButton("🎟 Промокод", callback_data="promo"),
             InlineKeyboardButton("👥 Реферал", callback_data="referral")],
            [InlineKeyboardButton("👤 Профиль", callback_data="profile"),
             InlineKeyboardButton("📢 Канал", url=f"https://t.me/{config.CHANNEL_USERNAME}")],
        ])


def subscribe_keyboard() -> InlineKeyboardMarkup:
    buttons = []
    for key, plan in config.PLANS.items():
        buttons.append([InlineKeyboardButton(plan["label"], callback_data=f"buy:{key}")])
    buttons.append([
        InlineKeyboardButton("🎟 Промокод", callback_data="promo"),
        InlineKeyboardButton("◀️ Назад", callback_data="back"),
    ])
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

    # СЛУЧАЙНЫЙ РЕПО
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
        for _ in range(5):
            repo = random_repo()
            if repo and not db.is_repo_seen(user_id, repo["url"]):
                break
        if not repo:
            await query.edit_message_text("😔 Не удалось найти репозиторий. Попробуйте ещё раз.")
            return
        db.mark_repo_seen(user_id, repo["url"])
        await send_repo_card(context.bot, user_id, repo, show_save=True, translate=is_sub)
        await context.bot.send_message(chat_id=user_id, text="Главное меню 👇", reply_markup=main_menu(is_sub))

    # ПОИСК
    elif data == "search":
        if not is_sub:
            await query.edit_message_text("🔍 Поиск доступен только по подписке.", reply_markup=subscribe_keyboard())
            return
        WAITING_SEARCH.add(user_id)
        await query.edit_message_text(
            "🔍 Введите поисковый запрос:\n\n"
            "<i>Примеры: roguelike, 2D platformer, horror</i>\n\n"
            "Фильтры через запятую:\n"
            "<i>roguelike, stars:50-500, updated:2023, license:MIT</i>",
            parse_mode=ParseMode.HTML,
        )

    # AI-ПОИСК
    elif data == "ai_search":
        if not is_sub:
            await query.edit_message_text("🤖 AI-поиск доступен только по подписке.", reply_markup=subscribe_keyboard())
            return
        WAITING_AI.add(user_id)
        await query.edit_message_text(
            "🤖 Опишите что хотите найти:\n\n"
            "<i>— платформер с процедурной генерацией\n"
            "— мобильная RPG с открытым кодом\n"
            "— шутер от первого лица для новичков</i>",
            parse_mode=ParseMode.HTML,
        )

    # РЕПО ПО ССЫЛКЕ
    elif data == "by_url":
        WAITING_URL.add(user_id)
        await query.edit_message_text(
            "🔗 Отправьте ссылку на GitHub репозиторий:\n\n"
            "<i>Пример: https://github.com/owner/repo</i>",
            parse_mode=ParseMode.HTML,
        )

    # ТОП НЕДЕЛИ
    elif data == "top_weekly":
        if not is_sub:
            await query.edit_message_text("🏆 Топ недели доступен только по подписке.", reply_markup=subscribe_keyboard())
            return
        await query.edit_message_text("🏆 Собираю топ недели...")
        repos = get_top_weekly(per_page=7)
        if not repos:
            await query.edit_message_text("😔 Не удалось получить топ. Попробуйте позже.")
            return
        lines = ["🏆 <b>Топ Unity-проектов этой недели:</b>\n"]
        save_buttons = []
        for i, repo in enumerate(repos, 1):
            desc = translate_description(repo["description"])[:120]
            lines.append(
                f"{i}. <b>{repo['name'].split('/')[-1].replace('-',' ').replace('_',' ').title()}</b>\n"
                f"   ⭐ <b>{repo['stars']}</b> | 📅 <b>{repo['updated']}</b>\n"
                f"   <i>{desc}</i>\n"
                f"   🔗 {repo['url']}\n"
            )
            save_buttons.append([
                InlineKeyboardButton(f"⭐ {i}. {repo['name'].split('/')[-1][:20]}", callback_data=f"save:{repo['url']}"),
            ])
        save_buttons.append([InlineKeyboardButton("◀️ В меню", callback_data="back")])
        await context.bot.send_message(
            chat_id=user_id,
            text="\n".join(lines),
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
            reply_markup=InlineKeyboardMarkup(save_buttons),
        )

    # ЭКСКЛЮЗИВ
    elif data == "exclusive":
        if not is_sub:
            await query.edit_message_text(
                "💎 <b>Эксклюзивная коллекция</b>\n\n"
                "Ручная подборка лучших Unity-проектов — доступна только по подписке.",
                parse_mode=ParseMode.HTML,
                reply_markup=subscribe_keyboard(),
            )
            return
        exclusives = db.get_exclusives()
        if not exclusives:
            await query.edit_message_text(
                "💎 Эксклюзивная коллекция пока пуста.\nСкоро здесь появятся лучшие проекты!",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Назад", callback_data="back")]]),
            )
            return
        await query.edit_message_text("💎 Загружаю коллекцию...")
        await context.bot.send_message(
            chat_id=user_id,
            text=f"💎 <b>Эксклюзивная коллекция</b> — {len(exclusives)} проектов:",
            parse_mode=ParseMode.HTML,
        )
        for ex in exclusives:
            repo = get_repo_by_url(ex["repo_url"])
            if repo:
                await send_repo_card(context.bot, user_id, repo, show_save=True, translate=True)
            else:
                await context.bot.send_message(
                    chat_id=user_id,
                    text=f"⭐ <b>{ex['repo_name']}</b>\n🔗 {ex['repo_url']}",
                    parse_mode=ParseMode.HTML,
                    disable_web_page_preview=True,
                )
            await asyncio.sleep(0.5)
        await context.bot.send_message(chat_id=user_id, text="Главное меню 👇", reply_markup=main_menu(is_sub))

    # ПОДПИСКА
    elif data == "subscribe":
        await query.edit_message_text(
            "💎 <b>Подписка Unity Search</b>\n\n"
            "✅ Безлимитный поиск\n"
            "✅ AI-поиск на естественном языке\n"
            "✅ Топ проектов недели\n"
            "✅ Эксклюзивная коллекция\n"
            "✅ Репо по ссылке с переводом\n"
            "✅ Безлимитное избранное\n\n"
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

    # ПРОМОКОД
    elif data == "promo":
        WAITING_PROMO.add(user_id)
        await query.edit_message_text("🎟 Введите промокод:")

    # ПРОФИЛЬ
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

    # РЕФЕРАЛ
    elif data == "referral":
        ref_count = db.get_referral_count(user_id)
        me = await context.bot.get_me()
        ref_link = f"https://t.me/{me.username}?start=ref{user_id}"
        await query.edit_message_text(
            f"👥 <b>Реферальная программа</b>\n\n"
            f"За каждого приглашённого — <b>{config.REFERRAL_BONUS_DAYS} дня</b> подписки.\n\n"
            f"Рефералов: <b>{ref_count}</b> | Заработано: <b>{ref_count * config.REFERRAL_BONUS_DAYS} дней</b>\n\n"
            f"Ваша ссылка:\n<code>{ref_link}</code>",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Назад", callback_data="back")]]),
        )

    # ИЗБРАННОЕ
    elif data == "favorites":
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

    elif data == "back":
        await query.edit_message_text("Главное меню 👇", reply_markup=main_menu(is_sub))

    elif data == "noop":
        pass


async def show_favorites_page(query, user_id: int, favs: list, page: int):
    total = len(favs)
    fav = favs[page]
    text = (
        f"⭐ <b>Избранное</b>  {page + 1}/{total}\n\n"
        f"<b>{fav['repo_name']}</b>\n"
        f"⭐ {fav['stars']}\n"
        f"🔗 {fav['repo_url']}"
    )
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("◀️", callback_data=f"fav_page:{page - 1}"))
    nav.append(InlineKeyboardButton(f"{page + 1}/{total}", callback_data="noop"))
    if page < total - 1:
        nav.append(InlineKeyboardButton("▶️", callback_data=f"fav_page:{page + 1}"))
    await query.edit_message_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([
            nav,
            [InlineKeyboardButton("🗑 Удалить", callback_data=f"unfav:{fav['repo_url']}")],
            [InlineKeyboardButton("◀️ Назад", callback_data="back")],
        ]),
        disable_web_page_preview=True,
    )


# ============================================================
# ТЕКСТ
# ============================================================

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()
    is_sub = db.is_subscribed(user_id)

    if user_id in WAITING_URL:
        WAITING_URL.discard(user_id)
        await update.message.reply_text("🔗 Загружаю репозиторий...")
        if "github.com" not in text:
            await update.message.reply_text(
                "❌ Это не ссылка на GitHub.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ В меню", callback_data="back")]]),
            )
            return
        repo = get_repo_by_url(text)
        if not repo:
            await update.message.reply_text(
                "😔 Репозиторий не найден или недоступен.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ В меню", callback_data="back")]]),
            )
            return
        await send_repo_card(context.bot, user_id, repo, show_save=True, translate=is_sub)
        await update.message.reply_text("Главное меню 👇", reply_markup=main_menu(is_sub))

    elif user_id in WAITING_PROMO:
        WAITING_PROMO.discard(user_id)
        result = db.use_promo(user_id, text)
        if not result:
            await update.message.reply_text("❌ Промокод не найден.")
        elif result.get("error") == "expired":
            await update.message.reply_text("❌ Промокод больше не активен.")
        elif result.get("error") == "already_used":
            await update.message.reply_text("❌ Вы уже использовали этот промокод.")
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
            await send_repo_card(context.bot, user_id, repo, show_save=True, translate=True)
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
            await send_repo_card(context.bot, user_id, repo, show_save=True, translate=True)
            await asyncio.sleep(0.5)
        await update.message.reply_text("Главное меню 👇", reply_markup=main_menu(True))

    else:
        await update.message.reply_text("Используйте меню 👇", reply_markup=main_menu(is_sub))


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


async def cmd_createpromo(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
        await update.message.reply_text(
            f"✅ Промокод: <code>{code}</code> — {days} дней, до {max_uses} использований",
            parse_mode=ParseMode.HTML,
        )
    except Exception as e:
        await update.message.reply_text(f"Ошибка: {e}")


async def cmd_addexclusive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != config.ADMIN_ID:
        return
    args = context.args
    if not args:
        await update.message.reply_text("Использование: /addexclusive [github_url]")
        return
    url = args[0]
    await update.message.reply_text("🔍 Загружаю репозиторий...")
    repo = get_repo_by_url(url)
    if not repo:
        await update.message.reply_text("❌ Репозиторий не найден.")
        return
    db.add_exclusive(repo["url"], repo["name"], repo["description"], repo["stars"], update.effective_user.id)
    await update.message.reply_text(f"✅ Добавлено в эксклюзив: <b>{repo['name']}</b>", parse_mode=ParseMode.HTML)


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
    app.add_handler(CommandHandler("createpromo", cmd_createpromo))
    app.add_handler(CommandHandler("addexclusive", cmd_addexclusive))
    app.add_handler(CommandHandler("me", cmd_me))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    logger.info("🤖 Unity Search Bot запущен")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
