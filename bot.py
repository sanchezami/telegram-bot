import asyncio
import logging
import os
import random
import sqlite3
import time
from contextlib import closing

from aiogram import Bot, Dispatcher, F
from aiogram.enums import ChatType
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LabeledPrice,
    Message,
    PreCheckoutQuery,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder


# ============================================================
# НАСТРОЙКИ
# ============================================================

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0") or 0)

# Для Railway Volume можно поставить:
# DB_PATH=/data/random_party.db
DB_PATH = os.getenv("DB_PATH", "random_party.db")

PREMIUM_DAYS = 30
PREMIUM_PRICE = 99

REFERRAL_PREMIUM_DAYS = 1

if not BOT_TOKEN:
    raise RuntimeError(
        "Не найден BOT_TOKEN. Добавь BOT_TOKEN в Railway → Variables."
    )


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

bot = Bot(BOT_TOKEN)
dp = Dispatcher()


# ============================================================
# DATABASE
# ============================================================

def db():
    return sqlite3.connect(DB_PATH, timeout=30)


def init_db():
    with closing(db()) as con:
        cur = con.cursor()

        cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT DEFAULT '',
            first_name TEXT DEFAULT '',
            joined_at INTEGER NOT NULL,
            last_seen INTEGER NOT NULL,
            premium_until INTEGER DEFAULT 0,
            referrals INTEGER DEFAULT 0,
            games INTEGER DEFAULT 0,
            wins INTEGER DEFAULT 0,
            coins INTEGER DEFAULT 0,
            banned INTEGER DEFAULT 0
        )
        """)

        cur.execute("""
        CREATE TABLE IF NOT EXISTS referrals (
            invited_id INTEGER PRIMARY KEY,
            inviter_id INTEGER NOT NULL,
            created_at INTEGER NOT NULL
        )
        """)

        cur.execute("""
        CREATE TABLE IF NOT EXISTS payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            stars INTEGER NOT NULL,
            payload TEXT NOT NULL,
            charge_id TEXT,
            created_at INTEGER NOT NULL
        )
        """)

        cur.execute("""
        CREATE TABLE IF NOT EXISTS group_players (
            chat_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            username TEXT DEFAULT '',
            first_name TEXT DEFAULT '',
            joined_at INTEGER NOT NULL,
            PRIMARY KEY(chat_id, user_id)
        )
        """)

        con.commit()


def register_user(user):
    now = int(time.time())

    with closing(db()) as con:
        con.execute("""
        INSERT INTO users(
            user_id,
            username,
            first_name,
            joined_at,
            last_seen
        )
        VALUES (?, ?, ?, ?, ?)

        ON CONFLICT(user_id)
        DO UPDATE SET
            username=excluded.username,
            first_name=excluded.first_name,
            last_seen=excluded.last_seen
        """, (
            user.id,
            user.username or "",
            user.first_name or "",
            now,
            now
        ))

        con.commit()


def user_banned(user_id):
    with closing(db()) as con:
        row = con.execute(
            "SELECT banned FROM users WHERE user_id=?",
            (user_id,)
        ).fetchone()

    return bool(row and row[0])


def get_premium_until(user_id):
    with closing(db()) as con:
        row = con.execute(
            "SELECT premium_until FROM users WHERE user_id=?",
            (user_id,)
        ).fetchone()

    return int(row[0]) if row else 0


def premium_active(user_id):
    return get_premium_until(user_id) > int(time.time())


def add_premium(user_id, days):
    now = int(time.time())
    current = get_premium_until(user_id)

    start = max(now, current)
    until = start + days * 86400

    with closing(db()) as con:
        con.execute(
            "UPDATE users SET premium_until=? WHERE user_id=?",
            (until, user_id)
        )
        con.commit()

    return until


def add_game(user_id, win=False, coins=0):
    with closing(db()) as con:
        con.execute("""
        UPDATE users
        SET
            games = games + 1,
            wins = wins + ?,
            coins = coins + ?
        WHERE user_id=?
        """, (
            1 if win else 0,
            coins,
            user_id
        ))

        con.commit()


def get_stats():
    with closing(db()) as con:
        users = con.execute(
            "SELECT COUNT(*) FROM users"
        ).fetchone()[0]

        premium = con.execute(
            "SELECT COUNT(*) FROM users WHERE premium_until>?",
            (int(time.time()),)
        ).fetchone()[0]

        payments = con.execute(
            "SELECT COUNT(*) FROM payments"
        ).fetchone()[0]

        stars = con.execute(
            "SELECT COALESCE(SUM(stars),0) FROM payments"
        ).fetchone()[0]

        referrals = con.execute(
            "SELECT COUNT(*) FROM referrals"
        ).fetchone()[0]

    return users, premium, payments, stars, referrals


# ============================================================
# REFERRALS
# ============================================================

def process_referral(inviter_id, invited_id):
    if inviter_id == invited_id:
        return False

    with closing(db()) as con:
        exists = con.execute(
            "SELECT 1 FROM referrals WHERE invited_id=?",
            (invited_id,)
        ).fetchone()

        if exists:
            return False

        inviter = con.execute(
            "SELECT 1 FROM users WHERE user_id=?",
            (inviter_id,)
        ).fetchone()

        if not inviter:
            return False

        con.execute("""
        INSERT INTO referrals(
            invited_id,
            inviter_id,
            created_at
        )
        VALUES (?, ?, ?)
        """, (
            invited_id,
            inviter_id,
            int(time.time())
        ))

        con.execute("""
        UPDATE users
        SET referrals=referrals+1
        WHERE user_id=?
        """, (inviter_id,))

        con.commit()

    add_premium(inviter_id, REFERRAL_PREMIUM_DAYS)

    return True


# ============================================================
# KEYBOARDS
# ============================================================

def main_keyboard():
    builder = InlineKeyboardBuilder()

    builder.button(
        text="🎮 Играть",
        callback_data="games"
    )

    builder.button(
        text="🏆 Рейтинг",
        callback_data="rating"
    )

    builder.button(
        text="👥 Пригласить",
        callback_data="referrals"
    )

    builder.button(
        text="⭐ Premium",
        callback_data="premium"
    )

    builder.button(
        text="👤 Профиль",
        callback_data="profile"
    )

    builder.button(
        text="ℹ️ Помощь",
        callback_data="help"
    )

    builder.adjust(2, 2, 2)

    return builder.as_markup()


def games_keyboard():
    builder = InlineKeyboardBuilder()

    builder.button(
        text="🪙 Орёл / решка",
        callback_data="coin"
    )

    builder.button(
        text="🎲 Кубик",
        callback_data="dice"
    )

    builder.button(
        text="🎯 Дартс",
        callback_data="dart"
    )

    builder.button(
        text="🎰 Слот",
        callback_data="slot"
    )

    builder.button(
        text="🔢 Число",
        callback_data="number"
    )

    builder.button(
        text="✊ КНБ",
        callback_data="rps"
    )

    builder.button(
        text="⬅️ Назад",
        callback_data="home"
    )

    builder.adjust(2, 2, 2, 1)

    return builder.as_markup()


def back_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="⬅️ Назад",
                    callback_data="home"
                )
            ]
        ]
    )


# ============================================================
# START
# ============================================================

@dp.message(CommandStart())
async def start(message: Message, command: CommandObject):

    if message.chat.type != ChatType.PRIVATE:
        return

    user = message.from_user

    register_user(user)

    if user_banned(user.id):
        await message.answer("🚫 Доступ к боту ограничен.")
        return

    # Реферальная ссылка:
    # /start ref_123456
    if command.args:

        if command.args.startswith("ref_"):

            inviter_text = command.args[4:]

            if inviter_text.isdigit():

                inviter_id = int(inviter_text)

                if process_referral(inviter_id, user.id):

                    try:
                        await bot.send_message(
                            inviter_id,
                            "🎉 Новый пользователь пришёл по твоей ссылке!\n\n"
                            f"⭐ Тебе начислен Premium на "
                            f"{REFERRAL_PREMIUM_DAYS} день."
                        )
                    except Exception:
                        pass

    text = """
<b>🎲 RANDOM PARTY</b>

Добро пожаловать!

Здесь можно:
🎮 играть в быстрые игры
🏆 соревноваться в рейтинге
👥 приглашать друзей
⭐ получать Premium
🎉 играть в группах

Выбирай действие ниже 👇
"""

    await message.answer(
        text,
        reply_markup=main_keyboard()
    )


# ============================================================
# HOME
# ============================================================

@dp.callback_query(F.data == "home")
async def home(call: CallbackQuery):

    await call.answer()

    await call.message.edit_text(
        """
<b>🎲 RANDOM PARTY</b>

Игры, рейтинг, друзья и Premium.

Выбирай действие 👇
""",
        reply_markup=main_keyboard()
    )


# ============================================================
# HELP
# ============================================================

@dp.callback_query(F.data == "help")
async def help_menu(call: CallbackQuery):

    await call.answer()

    await call.message.edit_text(
        """
<b>ℹ️ RANDOM PARTY</b>

🎮 <b>Играть</b>
Быстрые мини-игры.

🏆 <b>Рейтинг</b>
Топ игроков по победам.

👥 <b>Пригласить</b>
Получай Premium за новых пользователей.

⭐ <b>Premium</b>
Дополнительные возможности.

👥 <b>Группы</b>
Добавь бота в группу и используй:
<code>/join</code>
<code>/random</code>
<code>/leave</code>
<code>/top</code>

💳 Покупки Premium проходят через Telegram Stars.
""",
        reply_markup=back_keyboard()
    )


# ============================================================
# PROFILE
# ============================================================

@dp.callback_query(F.data == "profile")
async def profile(call: CallbackQuery):

    await call.answer()

    user_id = call.from_user.id

    with closing(db()) as con:
        row = con.execute("""
        SELECT
            games,
            wins,
            coins,
            referrals,
            premium_until
        FROM users
        WHERE user_id=?
        """, (user_id,)).fetchone()

    if not row:
        return

    games, wins, coins, referrals, premium = row

    if premium > int(time.time()):
        premium_text = "⭐ Premium активен"
    else:
        premium_text = "⚪ Premium не активен"

    await call.message.edit_text(
        f"""
<b>👤 Профиль</b>

🎮 Игр: <b>{games}</b>
🏆 Побед: <b>{wins}</b>
🪙 Очков: <b>{coins}</b>
👥 Приглашено: <b>{referrals}</b>

{premium_text}
""",
        reply_markup=back_keyboard()
    )


# ============================================================
# RATING
# ============================================================

@dp.callback_query(F.data == "rating")
async def rating(call: CallbackQuery):

    await call.answer()

    with closing(db()) as con:
        rows = con.execute("""
        SELECT
            first_name,
            username,
            wins
        FROM users
        WHERE banned=0
        ORDER BY wins DESC, games DESC
        LIMIT 10
        """).fetchall()

    if not rows:
        await call.message.edit_text(
            "🏆 Рейтинг пока пуст.",
            reply_markup=back_keyboard()
        )
        return

    medals = ["🥇", "🥈", "🥉"]

    lines = ["<b>🏆 ТОП-10</b>", ""]

    for i, row in enumerate(rows, 1):

        first_name, username, wins = row

        name = first_name or username or "Игрок"

        medal = medals[i - 1] if i <= 3 else f"{i}."

        lines.append(
            f"{medal} {name} — <b>{wins}</b> побед"
        )

    await call.message.edit_text(
        "\n".join(lines),
        reply_markup=back_keyboard()
    )


# ============================================================
# REFERRALS
# ============================================================

@dp.callback_query(F.data == "referrals")
async def referrals(call: CallbackQuery):

    await call.answer()

    me = await bot.get_me()

    link = (
        f"https://t.me/{me.username}"
        f"?start=ref_{call.from_user.id}"
    )

    with closing(db()) as con:
        row = con.execute(
            "SELECT referrals FROM users WHERE user_id=?",
            (call.from_user.id,)
        ).fetchone()

    count = row[0] if row else 0

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📤 Поделиться",
                    url=(
                        "https://t.me/share/url"
                        f"?url={link}"
                        "&text=🎲%20Заходи%20в%20RANDOM%20PARTY!"
                    )
                )
            ],
            [
                InlineKeyboardButton(
                    text="⬅️ Назад",
                    callback_data="home"
                )
            ]
        ]
    )

    await call.message.edit_text(
        f"""
<b>👥 Приглашай друзей</b>

Приглашено: <b>{count}</b>

За каждого нового пользователя:
⭐ +{REFERRAL_PREMIUM_DAYS} день Premium

Твоя ссылка:

<code>{link}</code>

Чем больше друзей — тем больше Premium 🔥
""",
        reply_markup=keyboard
    )


# ============================================================
# GAMES MENU
# ============================================================

@dp.callback_query(F.data == "games")
async def games(call: CallbackQuery):

    await call.answer()

    await call.message.edit_text(
        """
<b>🎮 ИГРЫ</b>

Выбирай игру 👇
""",
        reply_markup=games_keyboard()
    )


# ============================================================
# COIN
# ============================================================

@dp.callback_query(F.data == "coin")
async def coin(call: CallbackQuery):

    result = random.choice([
        "🦅 ОРЁЛ",
        "🪙 РЕШКА"
    ])

    add_game(call.from_user.id, coins=1)

    await call.answer(
        result,
        show_alert=True
    )


# ============================================================
# DICE
# ============================================================

@dp.callback_query(F.data == "dice")
async def dice(call: CallbackQuery):

    number = random.randint(1, 6)

    add_game(
        call.from_user.id,
        coins=number
    )

    await call.answer(
        f"🎲 Выпало: {number}",
        show_alert=True
    )


# ============================================================
# DART
# ============================================================

@dp.callback_query(F.data == "dart")
async def dart(call: CallbackQuery):

    number = random.randint(1, 60)

    add_game(
        call.from_user.id,
        coins=number // 10
    )

    await call.answer(
        f"🎯 Очков: {number}",
        show_alert=True
    )


# ============================================================
# SLOT
# ============================================================

@dp.callback_query(F.data == "slot")
async def slot(call: CallbackQuery):

    symbols = [
        "🍒",
        "🍋",
        "⭐",
        "7️⃣"
    ]

    a = random.choice(symbols)
    b = random.choice(symbols)
    c = random.choice(symbols)

    jackpot = a == b == c

    if jackpot:
        add_game(
            call.from_user.id,
            win=True,
            coins=20
        )

        result = (
            f"{a} {b} {c}\n\n"
            "🎉 ДЖЕКПОТ!\n"
            "+20 очков"
        )

    else:
        add_game(
            call.from_user.id,
            coins=1
        )

        result = (
            f"{a} {b} {c}\n\n"
            "+1 очко"
        )

    await call.answer(
        result,
        show_alert=True
    )


# ============================================================
# RANDOM NUMBER
# ============================================================

@dp.callback_query(F.data == "number")
async def number(call: CallbackQuery):

    value = random.randint(1, 1000)

    add_game(
        call.from_user.id,
        coins=1
    )

    await call.answer(
        f"🔢 Число: {value}",
        show_alert=True
    )


# ============================================================
# ROCK PAPER SCISSORS
# ============================================================

@dp.callback_query(F.data == "rps")
async def rps(call: CallbackQuery):

    result = random.choice([
        "✊ Камень",
        "✌️ Ножницы",
        "📄 Бумага"
    ])

    add_game(
        call.from_user.id,
        coins=1
    )

    await call.answer(
        f"🤖 Бот выбрал:\n{result}",
        show_alert=True
    )


# ============================================================
# PREMIUM
# ============================================================

@dp.callback_query(F.data == "premium")
async def premium(call: CallbackQuery):

    await call.answer()

    active = premium_active(call.from_user.id)

    if active:
        status = "🟢 Premium активен"
    else:
        status = "⚪ Premium не активен"

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"⭐ Купить за {PREMIUM_PRICE} Stars",
                    callback_data="buy_premium"
                )
            ],
            [
                InlineKeyboardButton(
                    text="⬅️ Назад",
                    callback_data="home"
                )
            ]
        ]
    )

    await call.message.edit_text(
        f"""
<b>⭐ PREMIUM</b>

{status}

Premium включает:

✨ Premium-статус
🔥 дополнительные бонусы
🏆 специальный статус
🎁 дополнительные награды
🚀 будущие Premium-функции

Цена:

<b>{PREMIUM_PRICE} ⭐ / 30 дней</b>
""",
        reply_markup=keyboard
    )


# ============================================================
# BUY PREMIUM — TELEGRAM STARS
# ============================================================

@dp.callback_query(F.data == "buy_premium")
async def buy_premium(call: CallbackQuery):

    await call.answer()

    user_id = call.from_user.id

    payload = (
        f"premium:"
        f"{user_id}:"
        f"{int(time.time())}"
    )

    await bot.send_invoice(
        chat_id=user_id,
        title="RANDOM PARTY Premium",
        description="Premium на 30 дней.",
        payload=payload,
        provider_token="",
        currency="XTR",
        prices=[
            LabeledPrice(
                label="Premium — 30 дней",
                amount=PREMIUM_PRICE
            )
        ]
    )


# ============================================================
# PRE-CHECKOUT
# ============================================================

@dp.pre_checkout_query()
async def pre_checkout(query: PreCheckoutQuery):

    if query.currency != "XTR":

        await query.answer(
            ok=False,
            error_message="Неподдерживаемая валюта."
        )

        return

    if query.total_amount != PREMIUM_PRICE:

        await query.answer(
            ok=False,
            error_message="Неверная цена."
        )

        return

    await query.answer(ok=True)


# ============================================================
# SUCCESSFUL PAYMENT
# ============================================================

@dp.message(F.successful_payment)
async def successful_payment(message: Message):

    payment = message.successful_payment

    if not payment.invoice_payload.startswith("premium:"):
        return

    user_id = message.from_user.id

    add_premium(
        user_id,
        PREMIUM_DAYS
    )

    with closing(db()) as con:

        con.execute("""
        INSERT INTO payments(
            user_id,
            stars,
            payload,
            charge_id,
            created_at
        )
        VALUES (?, ?, ?, ?, ?)
        """, (
            user_id,
            payment.total_amount,
            payment.invoice_payload,
            payment.telegram_payment_charge_id,
            int(time.time())
        ))

        con.commit()

    await message.answer(
        f"""
🎉 <b>Оплата прошла!</b>

⭐ Premium активирован.

Срок: <b>{PREMIUM_DAYS} дней</b>

Спасибо за поддержку RANDOM PARTY ❤️
""",
        reply_markup=main_keyboard()
    )

    if ADMIN_ID:

        try:

            await bot.send_message(
                ADMIN_ID,
                f"""
💰 <b>НОВАЯ ПОКУПКА</b>

👤 User ID: <code>{user_id}</code>
⭐ Stars: <b>{payment.total_amount}</b>
"""
            )

        except Exception:
            pass


# ============================================================
# PAYMENT SUPPORT
# ============================================================

@dp.message(Command("paysupport"))
async def paysupport(message: Message):

    if ADMIN_ID:

        text = (
            "💳 <b>Поддержка платежей</b>\n\n"
            "Если возникла проблема с покупкой, "
            "напиши владельцу бота.\n\n"
            f"ID поддержки: <code>{ADMIN_ID}</code>"
        )

    else:

        text = (
            "💳 <b>Поддержка платежей</b>\n\n"
            "Свяжись с владельцем бота и укажи "
            "информацию о покупке."
        )

    await message.answer(text)


# ============================================================
# TERMS
# ============================================================

@dp.message(Command("terms"))
async def terms(message: Message):

    await message.answer(
        f"""
<b>📜 Условия</b>

Premium является цифровой услугой внутри Telegram.

Стоимость:
<b>{PREMIUM_PRICE} Stars / 30 дней</b>

Покупка осуществляется через Telegram Stars.

Для вопросов по оплате:
<code>/paysupport</code>
"""
    )


# ============================================================
# USER ID
# ============================================================

@dp.message(Command("id"))
async def get_id(message: Message):

    await message.answer(
        f"🆔 Твой ID:\n<code>{message.from_user.id}</code>"
    )


# ============================================================
# GROUP — JOIN
# ============================================================

@dp.message(Command("join"))
async def group_join(message: Message):

    if message.chat.type not in (
        ChatType.GROUP,
        ChatType.SUPERGROUP
    ):
        return

    user = message.from_user

    with closing(db()) as con:

        con.execute("""
        INSERT INTO group_players(
            chat_id,
            user_id,
            username,
            first_name,
            joined_at
        )
        VALUES (?, ?, ?, ?, ?)

        ON CONFLICT(chat_id,user_id)
        DO UPDATE SET
            username=excluded.username,
            first_name=excluded.first_name
        """, (
            message.chat.id,
            user.id,
            user.username or "",
            user.first_name or "",
            int(time.time())
        ))

        con.commit()

    await message.answer(
        f"🎮 <b>{user.first_name}</b>, ты вошёл в игру!\n\n"
        "Теперь тебя можно выбрать через /random."
    )


# ============================================================
# GROUP — LEAVE
# ============================================================

@dp.message(Command("leave"))
async def group_leave(message: Message):

    if message.chat.type not in (
        ChatType.GROUP,
        ChatType.SUPERGROUP
    ):
        return

    with closing(db()) as con:

        con.execute(
            """
            DELETE FROM group_players
            WHERE chat_id=? AND user_id=?
            """,
            (
                message.chat.id,
                message.from_user.id
            )
        )

        con.commit()

    await message.answer(
        "👋 Ты вышел из списка игроков."
    )


# ============================================================
# GROUP — RANDOM
# ============================================================

@dp.message(Command("random"))
async def group_random(message: Message):

    if message.chat.type not in (
        ChatType.GROUP,
        ChatType.SUPERGROUP
    ):
        return

    with closing(db()) as con:

        players = con.execute("""
        SELECT
            first_name,
            username
        FROM group_players
        WHERE chat_id=?
        """, (
            message.chat.id,
        )).fetchall()

    if not players:

        await message.answer(
            "🎲 Пока никто не зарегистрирован.\n"
            "Напиши /join"
        )

        return

    player = random.choice(players)

    name = player[0] or player[1] or "Игрок"

    await message.answer(
        f"🎯 Выбран:\n\n"
        f"<b>{name}</b>"
    )


# ============================================================
# GROUP — TOP
# ============================================================

@dp.message(Command("top"))
async def group_top(message: Message):

    if message.chat.type not in (
        ChatType.GROUP,
        ChatType.SUPERGROUP
    ):
        return

    with closing(db()) as con:

        players = con.execute("""
        SELECT
            first_name,
            username
        FROM group_players
        WHERE chat_id=?
        LIMIT 10
        """, (
            message.chat.id,
        )).fetchall()

    if not players:

        await message.answer(
            "🏆 Рейтинг пока пуст."
        )

        return

    text = "<b>🏆 Участники группы</b>\n\n"

    for i, player in enumerate(players, 1):

        name = player[0] or player[1] or "Игрок"

        text += f"{i}. {name}\n"

    await message.answer(text)


# ============================================================
# GROUP HELP
# ============================================================

@dp.message(Command("grouphelp"))
async def group_help(message: Message):

    if message.chat.type not in (
        ChatType.GROUP,
        ChatType.SUPERGROUP
    ):
        return

    await message.answer(
        """
<b>👥 RANDOM PARTY — ГРУППА</b>

Добавь бота в группу.

Команды:

<code>/join</code> — войти в игру
<code>/leave</code> — выйти
<code>/random</code> — случайный участник
<code>/top</code> — список участников
<code>/grouphelp</code> — помощь
"""
    )


# ============================================================
# ADMIN
# ============================================================

def is_admin(user_id):
    return ADMIN_ID != 0 and user_id == ADMIN_ID


@dp.message(Command("stats"))
async def admin_stats(message: Message):

    if not is_admin(message.from_user.id):
        return

    users, premium, payments, stars, referrals = get_stats()

    await message.answer(
        f"""
<b>📊 ADMIN PANEL</b>

👤 Пользователей: <b>{users}</b>

⭐ Premium: <b>{premium}</b>

💳 Покупок: <b>{payments}</b>

🌟 Получено Stars: <b>{stars}</b>

👥 Рефералов: <b>{referrals}</b>
"""
    )


@dp.message(Command("ban"))
async def admin_ban(message: Message):

    if not is_admin(message.from_user.id):
        return

    parts = message.text.split()

    if len(parts) != 2 or not parts[1].isdigit():

        await message.answer(
            "Использование:\n"
            "<code>/ban USER_ID</code>"
        )

        return

    user_id = int(parts[1])

    with closing(db()) as con:

        con.execute(
            "UPDATE users SET banned=1 WHERE user_id=?",
            (user_id,)
        )

        con.commit()

    await message.answer(
        f"🔨 Пользователь <code>{user_id}</code> заблокирован."
    )


@dp.message(Command("unban"))
async def admin_unban(message: Message):

    if not is_admin(message.from_user.id):
        return

    parts = message.text.split()

    if len(parts) != 2 or not parts[1].isdigit():

        await message.answer(
            "Использование:\n"
            "<code>/unban USER_ID</code>"
        )

        return

    user_id = int(parts[1])

    with closing(db()) as con:

        con.execute(
            "UPDATE users SET banned=0 WHERE user_id=?",
            (user_id,)
        )

        con.commit()

    await message.answer(
        f"✅ Пользователь <code>{user_id}</code> разблокирован."
    )


# ============================================================
# FALLBACK
# ============================================================

@dp.message()
async def fallback(message: Message):

    if message.chat.type != ChatType.PRIVATE:
        return

    register_user(message.from_user)

    if user_banned(message.from_user.id):

        await message.answer(
            "🚫 Доступ ограничен."
        )

        return

    await message.answer(
        "Используй меню ниже 👇",
        reply_markup=main_keyboard()
    )


# ============================================================
# START BOT
# ============================================================

async def main():

    init_db()

    me = await bot.get_me()

    logging.info(
        "Bot started: @%s",
        me.username
    )

    await bot.delete_webhook(
        drop_pending_updates=True
    )

    await dp.start_polling(
        bot,
        allowed_updates=dp.resolve_used_update_types()
    )


if __name__ == "__main__":

    try:

        asyncio.run(main())

    except KeyboardInterrupt:

        logging.info("Bot stopped.")