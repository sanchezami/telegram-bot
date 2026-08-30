import asyncio
import logging
import os
import random
import sqlite3
import time
from contextlib import closing
from datetime import datetime

from aiogram import Bot, Dispatcher, F
from aiogram.enums import ChatType
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LabeledPrice,
    PreCheckoutQuery,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder


# =========================================================
# CONFIG
# =========================================================

TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0") or 0)

DB = "bot.db"

PREMIUM_STARS = 59
PREMIUM_DAYS = 30

if not TOKEN:
    raise RuntimeError("Не найден BOT_TOKEN")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

bot = Bot(TOKEN)
dp = Dispatcher()


# =========================================================
# DATABASE
# =========================================================

def connect():
    return sqlite3.connect(DB, timeout=30)


def init_db():
    with closing(connect()) as db:

        db.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY,
            username TEXT DEFAULT '',
            name TEXT DEFAULT '',
            coins INTEGER DEFAULT 100,
            xp INTEGER DEFAULT 0,
            level INTEGER DEFAULT 1,
            games INTEGER DEFAULT 0,
            wins INTEGER DEFAULT 0,
            losses INTEGER DEFAULT 0,
            streak INTEGER DEFAULT 0,
            last_daily INTEGER DEFAULT 0,
            premium_until INTEGER DEFAULT 0,
            referrals INTEGER DEFAULT 0,
            banned INTEGER DEFAULT 0,
            created INTEGER DEFAULT 0
        )
        """)

        db.execute("""
        CREATE TABLE IF NOT EXISTS groups (
            id INTEGER PRIMARY KEY,
            title TEXT DEFAULT '',
            xp INTEGER DEFAULT 0,
            level INTEGER DEFAULT 1,
            created INTEGER DEFAULT 0
        )
        """)

        db.execute("""
        CREATE TABLE IF NOT EXISTS group_users (
            group_id INTEGER,
            user_id INTEGER,
            games INTEGER DEFAULT 0,
            wins INTEGER DEFAULT 0,
            coins INTEGER DEFAULT 0,
            PRIMARY KEY(group_id, user_id)
        )
        """)

        db.execute("""
        CREATE TABLE IF NOT EXISTS referrals (
            user_id INTEGER PRIMARY KEY,
            inviter INTEGER,
            created INTEGER
        )
        """)

        db.execute("""
        CREATE TABLE IF NOT EXISTS payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            stars INTEGER,
            payload TEXT,
            charge_id TEXT,
            created INTEGER
        )
        """)

        db.execute("""
        CREATE TABLE IF NOT EXISTS achievements (
            user_id INTEGER,
            achievement TEXT,
            created INTEGER,
            UNIQUE(user_id, achievement)
        )
        """)

        db.commit()


# =========================================================
# USERS
# =========================================================

def ensure_user(user):
    now = int(time.time())

    with closing(connect()) as db:
        db.execute("""
        INSERT INTO users
        (id, username, name, created)
        VALUES (?, ?, ?, ?)

        ON CONFLICT(id)
        DO UPDATE SET
            username=excluded.username,
            name=excluded.name
        """, (
            user.id,
            user.username or "",
            user.first_name or "Игрок",
            now
        ))

        db.commit()


def get_user(user_id):
    with closing(connect()) as db:
        return db.execute("""
        SELECT
            id,
            username,
            name,
            coins,
            xp,
            level,
            games,
            wins,
            losses,
            streak,
            last_daily,
            premium_until,
            referrals,
            banned
        FROM users
        WHERE id=?
        """, (user_id,)).fetchone()


def add_coins(user_id, amount):
    with closing(connect()) as db:
        db.execute("""
        UPDATE users
        SET coins = coins + ?
        WHERE id=?
        """, (amount, user_id))
        db.commit()


def remove_coins(user_id, amount):
    with closing(connect()) as db:
        db.execute("""
        UPDATE users
        SET coins = MAX(0, coins - ?)
        WHERE id=?
        """, (amount, user_id))
        db.commit()


def add_xp(user_id, amount):
    with closing(connect()) as db:

        row = db.execute("""
        SELECT xp, level
        FROM users
        WHERE id=?
        """, (user_id,)).fetchone()

        if not row:
            return

        xp, level = row
        xp += amount

        while xp >= level * 100:
            xp -= level * 100
            level += 1

        db.execute("""
        UPDATE users
        SET xp=?, level=?
        WHERE id=?
        """, (
            xp,
            level,
            user_id
        ))

        db.commit()


def is_premium(user_id):
    row = get_user(user_id)

    return bool(
        row and
        row[11] > int(time.time())
    )


def premium_until(user_id):
    row = get_user(user_id)

    if not row:
        return 0

    return row[11]


def activate_premium(user_id, days):
    now = int(time.time())

    current = premium_until(user_id)

    start = max(
        now,
        current
    )

    until = start + days * 86400

    with closing(connect()) as db:
        db.execute("""
        UPDATE users
        SET premium_until=?
        WHERE id=?
        """, (
            until,
            user_id
        ))

        db.commit()

    return until


def game_result(
    user_id,
    win=False,
    reward=0
):
    if is_premium(user_id):
        reward = int(reward * 1.5)

    with closing(connect()) as db:
        db.execute("""
        UPDATE users
        SET
            games=games+1,
            wins=wins+?,
            losses=losses+?,
            coins=coins+?
        WHERE id=?
        """, (
            1 if win else 0,
            0 if win else 1,
            reward,
            user_id
        ))

        db.commit()

    add_xp(
        user_id,
        25 if win else 10
    )

    check_achievements(user_id)


# =========================================================
# ACHIEVEMENTS
# =========================================================

def achievement(user_id, name):
    with closing(connect()) as db:

        exists = db.execute("""
        SELECT 1
        FROM achievements
        WHERE user_id=? AND achievement=?
        """, (
            user_id,
            name
        )).fetchone()

        if exists:
            return False

        db.execute("""
        INSERT INTO achievements
        (user_id, achievement, created)
        VALUES (?, ?, ?)
        """, (
            user_id,
            name,
            int(time.time())
        ))

        db.commit()

    add_coins(
        user_id,
        250
    )

    return True


def check_achievements(user_id):

    row = get_user(user_id)

    if not row:
        return

    games = row[6]
    wins = row[7]
    coins = row[3]
    level = row[5]

    if games >= 1:
        achievement(
            user_id,
            "Первый матч"
        )

    if wins >= 10:
        achievement(
            user_id,
            "10 побед"
        )

    if wins >= 50:
        achievement(
            user_id,
            "50 побед"
        )

    if coins >= 10000:
        achievement(
            user_id,
            "Богач"
        )

    if level >= 10:
        achievement(
            user_id,
            "Уровень 10"
        )


# =========================================================
# GROUPS
# =========================================================

def ensure_group(message):
    if message.chat.type not in (
        ChatType.GROUP,
        ChatType.SUPERGROUP
    ):
        return

    now = int(time.time())

    with closing(connect()) as db:

        db.execute("""
        INSERT INTO groups
        (id, title, created)
        VALUES (?, ?, ?)

        ON CONFLICT(id)
        DO UPDATE SET
            title=excluded.title
        """, (
            message.chat.id,
            message.chat.title or "Группа",
            now
        ))

        db.execute("""
        INSERT OR IGNORE INTO group_users
        (group_id, user_id)
        VALUES (?, ?)
        """, (
            message.chat.id,
            message.from_user.id
        ))

        db.commit()


def group_game(
    chat_id,
    user_id,
    win=False,
    reward=0
):
    with closing(connect()) as db:

        db.execute("""
        INSERT OR IGNORE INTO group_users
        (group_id, user_id)
        VALUES (?, ?)
        """, (
            chat_id,
            user_id
        ))

        db.execute("""
        UPDATE group_users
        SET
            games=games+1,
            wins=wins+?,
            coins=coins+?
        WHERE group_id=? AND user_id=?
        """, (
            1 if win else 0,
            reward,
            chat_id,
            user_id
        ))

        db.execute("""
        UPDATE groups
        SET xp=xp+?
        WHERE id=?
        """, (
            20,
            chat_id
        ))

        db.commit()

    game_result(
        user_id,
        win,
        reward
    )


def group_members(chat_id):

    with closing(connect()) as db:
        return db.execute("""
        SELECT
            gu.user_id,
            u.name,
            u.username,
            gu.games,
            gu.wins,
            gu.coins
        FROM group_users gu
        JOIN users u
        ON u.id=gu.user_id
        WHERE gu.group_id=?
        """, (
            chat_id
        )).fetchall()


# =========================================================
# KEYBOARDS
# =========================================================

def main_menu():

    b = InlineKeyboardBuilder()

    b.button(
        text="🎮 Играть",
        callback_data="games"
    )

    b.button(
        text="👤 Профиль",
        callback_data="profile"
    )

    b.button(
        text="💰 Экономика",
        callback_data="economy"
    )

    b.button(
        text="🏆 Топ",
        callback_data="top"
    )

    b.button(
        text="🎁 Награда",
        callback_data="daily"
    )

    b.button(
        text="🏅 Достижения",
        callback_data="achievements"
    )

    b.button(
        text="👥 Пригласить",
        callback_data="referrals"
    )

    b.button(
        text="⭐ Premium",
        callback_data="premium"
    )

    b.button(
        text="👥 Добавить в группу",
        callback_data="add_group"
    )

    b.button(
        text="ℹ️ Помощь",
        callback_data="help"
    )

    b.adjust(
        2, 2, 2, 2, 1, 1
    )

    return b.as_markup()


def games_menu():

    b = InlineKeyboardBuilder()

    games = [
        ("🪙 Монетка", "coin"),
        ("🎲 Кубик", "dice"),
        ("🎰 Слот", "slot"),
        ("✊ КНБ", "rps"),
        ("🔢 Число", "number"),
        ("⚡ Множитель", "multiplier"),
        ("🎁 Сундук", "chest"),
        ("🧠 Викторина", "quiz"),
        ("💎 Premium Jackpot", "premium_jackpot"),
    ]

    for text, callback in games:
        b.button(
            text=text,
            callback_data="game_" + callback
        )

    b.button(
        text="⬅️ Назад",
        callback_data="home"
    )

    b.adjust(
        2, 2, 2, 2, 1, 1
    )

    return b.as_markup()


def back():
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


# =========================================================
# START
# =========================================================

@dp.message(CommandStart())
async def start(
    message: Message,
    command: CommandObject
):

    if message.chat.type != ChatType.PRIVATE:
        return

    user = message.from_user

    ensure_user(user)

    row = get_user(user.id)

    if row and row[13]:
        await message.answer(
            "🚫 Ты заблокирован."
        )
        return

    # REFERRAL
    if command.args:

        arg = command.args

        if arg.startswith("ref_"):

            raw = arg[4:]

            if raw.isdigit():

                inviter = int(raw)

                if inviter != user.id:

                    with closing(connect()) as db:

                        exists = db.execute("""
                        SELECT 1
                        FROM referrals
                        WHERE user_id=?
                        """, (
                            user.id,
                        )).fetchone()

                        inviter_exists = db.execute("""
                        SELECT 1
                        FROM users
                        WHERE id=?
                        """, (
                            inviter,
                        )).fetchone()

                        if not exists and inviter_exists:

                            db.execute("""
                            INSERT INTO referrals
                            (user_id, inviter, created)
                            VALUES (?, ?, ?)
                            """, (
                                user.id,
                                inviter,
                                int(time.time())
                            ))

                            db.execute("""
                            UPDATE users
                            SET referrals=referrals+1
                            WHERE id=?
                            """, (
                                inviter,
                            ))

                            db.commit()

                            add_coins(
                                inviter,
                                500
                            )

                            activate_premium(
                                inviter,
                                1
                            )

                            try:
                                await bot.send_message(
                                    inviter,
                                    "🎉 Новый реферал!\n\n"
                                    "🪙 +500 монет\n"
                                    "⭐ +1 день Premium"
                                )
                            except Exception:
                                pass

    await message.answer(
        """
<b>🎲 RANDOM PARTY</b>

Добро пожаловать.

Это социальный Telegram-бот, где можно:

🎮 играть
💰 зарабатывать
📈 прокачивать уровень
🏆 соревноваться
👥 играть в группах
🏅 получать достижения
⭐ использовать Premium

Добавляй меня в группу и устраивайте свою арену.

👇 Выбирай:
""",
        reply_markup=main_menu()
    )


# =========================================================
# HOME
# =========================================================

@dp.callback_query(F.data == "home")
async def home(call: CallbackQuery):

    await call.answer()

    await call.message.edit_text(
        """
<b>🎲 RANDOM PARTY</b>

Главное меню 👇
""",
        reply_markup=main_menu()
    )


# =========================================================
# PROFILE
# =========================================================

@dp.callback_query(F.data == "profile")
async def profile(call: CallbackQuery):

    await call.answer()

    row = get_user(
        call.from_user.id
    )

    if not row:
        return

    (
        uid,
        username,
        name,
        coins,
        xp,
        level,
        games,
        wins,
        losses,
        streak,
        daily,
        premium,
        referrals,
        banned
    ) = row

    premium_text = (
        "⭐ PREMIUM"
        if premium > int(time.time())
        else "FREE"
    )

    winrate = (
        round(wins / games * 100, 1)
        if games
        else 0
    )

    await call.message.edit_text(
        f"""
<b>👤 ПРОФИЛЬ</b>

{name}

{premium_text}

🏅 Уровень: <b>{level}</b>
⚡ XP: <b>{xp}/{level * 100}</b>

💰 Монеты: <b>{coins}</b>

🎮 Игр: <b>{games}</b>
🏆 Побед: <b>{wins}</b>
💀 Поражений: <b>{losses}</b>

📊 Винрейт: <b>{winrate}%</b>

🔥 Streak: <b>{streak}</b>

👥 Рефералов: <b>{referrals}</b>
""",
        reply_markup=back()
    )


# =========================================================
# ECONOMY
# =========================================================

@dp.callback_query(F.data == "economy")
async def economy(call: CallbackQuery):

    await call.answer()

    row = get_user(
        call.from_user.id
    )

    coins = row[3] if row else 0

    await call.message.edit_text(
        f"""
<b>💰 ЭКОНОМИКА</b>

Твой баланс:

🪙 <b>{coins}</b>

Как заработать:

🎮 Игры
🎁 Daily
🎯 Задания
👥 Рефералы
🏆 Победы
🎉 События

Чем активнее играешь — тем выше уровень.
""",
        reply_markup=back()
    )


# =========================================================
# TOP
# =========================================================

@dp.callback_query(F.data == "top")
async def top(call: CallbackQuery):

    await call.answer()

    with closing(connect()) as db:

        rows = db.execute("""
        SELECT
            name,
            wins,
            coins,
            level
        FROM users
        WHERE banned=0
        ORDER BY wins DESC, level DESC, coins DESC
        LIMIT 10
        """).fetchall()

    text = "<b>🏆 ГЛОБАЛЬНЫЙ ТОП</b>\n\n"

    medals = [
        "🥇",
        "🥈",
        "🥉"
    ]

    for i, row in enumerate(rows, 1):

        name, wins, coins, level = row

        icon = (
            medals[i - 1]
            if i <= 3
            else f"{i}."
        )

        text += (
            f"{icon} <b>{name}</b>\n"
            f"   🏆 {wins} | "
            f"🪙 {coins} | "
            f"LVL {level}\n"
        )

    await call.message.edit_text(
        text,
        reply_markup=back()
    )


# =========================================================
# DAILY
# =========================================================

@dp.callback_query(F.data == "daily")
async def daily(call: CallbackQuery):

    await call.answer()

    user_id = call.from_user.id

    row = get_user(user_id)

    if not row:
        return

    last = row[10]
    streak = row[9]

    now = int(time.time())

    if now - last < 86400:

        left = 86400 - (
            now - last
        )

        hours = left // 3600
        minutes = (
            left % 3600
        ) // 60

        await call.message.edit_text(
            f"""
<b>🎁 DAILY</b>

Ты уже получил награду.

⏳ Осталось:
<b>{hours}ч {minutes}мин</b>

🔥 Streak: {streak}
""",
            reply_markup=back()
        )

        return

    streak += 1

    reward = 100 + min(
        streak * 25,
        500
    )

    if is_premium(user_id):
        reward *= 2

    with closing(connect()) as db:

        db.execute("""
        UPDATE users
        SET
            coins=coins+?,
            last_daily=?,
            streak=?
        WHERE id=?
        """, (
            reward,
            now,
            streak,
            user_id
        ))

        db.commit()

    add_xp(
        user_id,
        30
    )

    await call.message.edit_text(
        f"""
🎉 <b>DAILY ПОЛУЧЕН!</b>

🪙 +<b>{reward}</b>

🔥 Streak: <b>{streak}</b>

Продолжай заходить каждый день.
""",
        reply_markup=back()
    )


# =========================================================
# ACHIEVEMENTS
# =========================================================

@dp.callback_query(F.data == "achievements")
async def achievements(call: CallbackQuery):

    await call.answer()

    with closing(connect()) as db:

        rows = db.execute("""
        SELECT achievement
        FROM achievements
        WHERE user_id=?
        ORDER BY created DESC
        """, (
            call.from_user.id,
        )).fetchall()

    if not rows:

        text = """
<b>🏅 ДОСТИЖЕНИЯ</b>

Пока пусто.

Играй и открывай достижения!
"""

    else:

        text = "<b>🏅 ДОСТИЖЕНИЯ</b>\n\n"

        for row in rows:

            text += (
                f"🏅 {row[0]}\n"
            )

    await call.message.edit_text(
        text,
        reply_markup=back()
    )


# =========================================================
# REFERRALS
# =========================================================

@dp.callback_query(F.data == "referrals")
async def referrals(call: CallbackQuery):

    await call.answer()

    me = await bot.get_me()

    link = (
        f"https://t.me/{me.username}"
        f"?start=ref_{call.from_user.id}"
    )

    row = get_user(
        call.from_user.id
    )

    refs = row[12] if row else 0

    share = (
        "https://t.me/share/url"
        f"?url={link}"
        "&text=🎲%20Залетай%20в%20RANDOM%20PARTY!"
    )

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📤 Пригласить",
                    url=share
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
<b>👥 РЕФЕРАЛЫ</b>

Приглашено:
<b>{refs}</b>

За каждого нового игрока:

🪙 +500 монет
⭐ +1 день Premium

Твоя ссылка:

<code>{link}</code>
""",
        reply_markup=kb
    )


# =========================================================
# GAMES
# =========================================================

@dp.callback_query(F.data == "games")
async def games(call: CallbackQuery):

    await call.answer()

    await call.message.edit_text(
        """
<b>🎮 ИГРЫ</b>

Выбирай игру:

🪙 Монетка
🎲 Кубик
🎰 Слот
✊ КНБ
🔢 Число
⚡ Множитель
🎁 Сундук
🧠 Викторина
💎 Premium Jackpot
""",
        reply_markup=games_menu()
    )


# =========================================================
# COIN
# =========================================================

@dp.callback_query(F.data == "game_coin")
async def coin(call: CallbackQuery):

    result = random.choice([
        "🦅 ОРЁЛ",
        "🪙 РЕШКА"
    ])

    reward = 15

    game_result(
        call.from_user.id,
        reward=reward
    )

    await call.answer(
        f"{result}\n\n🪙 +{reward}",
        show_alert=True
    )


# =========================================================
# DICE
# =========================================================

@dp.callback_query(F.data == "game_dice")
async def dice(call: CallbackQuery):

    value = random.randint(
        1,
        6
    )

    reward = value * 10

    game_result(
        call.from_user.id,
        reward=reward
    )

    await call.answer(
        f"🎲 Выпало: {value}\n\n"
        f"🪙 +{reward}",
        show_alert=True
    )


# =========================================================
# SLOT
# =========================================================

@dp.callback_query(F.data == "game_slot")
async def slot(call: CallbackQuery):

    symbols = [
        "🍒",
        "🍋",
        "🍊",
        "⭐",
        "💎",
        "7️⃣"
    ]

    a, b, c = [
        random.choice(symbols)
        for _ in range(3)
    ]

    if a == b == c:

        reward = 1000
        win = True

        result = "💎 ДЖЕКПОТ!"

    elif (
        a == b
        or
        b == c
        or
        a == c
    ):

        reward = 150
        win = True

        result = "🔥 ПАРА!"

    else:

        reward = 10
        win = False

        result = "😈 Не повезло"

    game_result(
        call.from_user.id,
        win=win,
        reward=reward
    )

    await call.answer(
        f"""
🎰 {a} {b} {c}

{result}

🪙 +{reward}
""",
        show_alert=True
    )


# =========================================================
# RPS
# =========================================================

@dp.callback_query(F.data == "game_rps")
async def rps(call: CallbackQuery):

    user = random.choice([
        "✊",
        "✌️",
        "📄"
    ])

    enemy = random.choice([
        "✊",
        "✌️",
        "📄"
    ])

    if user == enemy:

        reward = 20
        win = False

        text = "🤝 Ничья"

    elif (
        (user == "✊" and enemy == "✌️")
        or
        (user == "✌️" and enemy == "📄")
        or
        (user == "📄" and enemy == "✊")
    ):

        reward = 100
        win = True

        text = "🏆 Победа!"

    else:

        reward = 5
        win = False

        text = "💀 Поражение"

    game_result(
        call.from_user.id,
        win=win,
        reward=reward
    )

    await call.answer(
        f"""
Ты: {user}
Бот: {enemy}

{text}

🪙 +{reward}
""",
        show_alert=True
    )


# =========================================================
# NUMBER
# =========================================================

@dp.callback_query(F.data == "game_number")
async def number_game(call: CallbackQuery):

    number = random.randint(
        1,
        10000
    )

    reward = 50

    game_result(
        call.from_user.id,
        reward=reward
    )

    await call.answer(
        f"""
🔢 Твоё число:

<b>{number}</b>

🪙 +{reward}
""",
        show_alert=True
    )


# =========================================================
# MULTIPLIER
# =========================================================

@dp.callback_query(F.data == "game_multiplier")
async def multiplier(call: CallbackQuery):

    n = random.randint(
        1,
        100
    )

    if n >= 98:
        mult = "x10"
        reward = 1000

    elif n >= 90:
        mult = "x5"
        reward = 500

    elif n >= 70:
        mult = "x2"
        reward = 200

    else:
        mult = "x1"
        reward = 25

    game_result(
        call.from_user.id,
        win=reward >= 200,
        reward=reward
    )

    await call.answer(
        f"""
⚡ МНОЖИТЕЛЬ

🎯 {n}

<b>{mult}</b>

🪙 +{reward}
""",
        show_alert=True
    )


# =========================================================
# CHEST
# =========================================================

@dp.callback_query(F.data == "game_chest")
async def chest(call: CallbackQuery):

    rewards = [
        50,
        100,
        150,
        250,
        500,
        1000,
        2500
    ]

    reward = random.choice(
        rewards
    )

    if is_premium(
        call.from_user.id
    ):
        reward = int(
            reward * 1.5
        )

    add_coins(
        call.from_user.id,
        reward
    )

    add_xp(
        call.from_user.id,
        25
    )

    await call.answer(
        f"""
🎁 СУНДУК ОТКРЫТ!

🪙 +<b>{reward}</b>
""",
        show_alert=True
    )


# =========================================================
# PREMIUM JACKPOT
# =========================================================

@dp.callback_query(
    F.data == "game_premium_jackpot"
)
async def premium_jackpot(
    call: CallbackQuery
):

    if not is_premium(
        call.from_user.id
    ):

        await call.answer(
            "⭐ Эта игра только для Premium.",
            show_alert=True
        )

        return

    n = random.randint(
        1,
        100
    )

    if n >= 97:
        reward = 5000
    elif n >= 85:
        reward = 1000
    elif n >= 60:
        reward = 500
    else:
        reward = 100

    add_coins(
        call.from_user.id,
        reward
    )

    add_xp(
        call.from_user.id,
        75
    )

    await call.answer(
        f"""
💎 PREMIUM JACKPOT

🎯 {n}

🪙 +<b>{reward}</b>
""",
        show_alert=True
    )


# =========================================================
# QUIZ
# =========================================================

QUESTIONS = [
    (
        "Столица Франции?",
        ["Париж", "Лион", "Марсель", "Ницца"],
        0
    ),
    (
        "Самая большая планета?",
        ["Марс", "Юпитер", "Земля", "Венера"],
        1
    ),
    (
        "15 × 6 = ?",
        ["80", "90", "100", "120"],
        1
    ),
    (
        "Единица силы тока?",
        ["Вольт", "Ампер", "Ом", "Ватт"],
        1
    ),
    (
        "Кто написал «Евгения Онегина»?",
        ["Пушкин", "Гоголь", "Толстой", "Лермонтов"],
        0
    ),
]


@dp.callback_query(F.data == "game_quiz")
async def quiz(call: CallbackQuery):

    question, answers, correct = random.choice(
        QUESTIONS
    )

    b = InlineKeyboardBuilder()

    for i, answer in enumerate(answers):

        b.button(
            text=answer,
            callback_data=f"quiz:{correct}:{i}"
        )

    b.adjust(1)

    await call.message.edit_text(
        f"""
<b>🧠 ВИКТОРИНА</b>

{question}
""",
        reply_markup=b.as_markup()
    )


@dp.callback_query(
    F.data.startswith("quiz:")
)
async def quiz_answer(
    call: CallbackQuery
):

    _, correct, answer = call.data.split(":")

    correct = int(correct)
    answer = int(answer)

    if correct == answer:

        reward = 250

        game_result(
            call.from_user.id,
            win=True,
            reward=reward
        )

        text = (
            "🎉 <b>ПРАВИЛЬНО!</b>\n\n"
            f"🪙 +{reward}"
        )

    else:

        game_result(
            call.from_user.id
        )

        text = "❌ Неправильно."

    await call.answer(
        text,
        show_alert=True
    )

    await call.message.edit_text(
        text,
        reply_markup=games_menu()
    )


# =========================================================
# PREMIUM
# =========================================================

@dp.callback_query(F.data == "premium")
async def premium(call: CallbackQuery):

    await call.answer()

    active = is_premium(
        call.from_user.id
    )

    status = (
        "🟢 Premium активен"
        if active
        else "⚪ Premium не активен"
    )

    await call.message.edit_text(
        f"""
<b>⭐ RANDOM PARTY PREMIUM</b>

{status}

<b>Что ты получаешь:</b>

⚡ <b>+50% ко всем игровым наградам</b>
🎁 <b>x2 Daily</b>
💎 Premium Jackpot
🎁 усиленные сундуки
🏅 Premium-достижения
👑 Premium-статус
🏟️ специальные групповые возможности
🔥 эксклюзивные события
📈 ускоренная прокачка

<b>{PREMIUM_STARS} ⭐ / 30 дней</b>
""",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=f"⭐ Купить за {PREMIUM_STARS} Stars",
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
    )


@dp.callback_query(F.data == "buy_premium")
async def buy_premium(
    call: CallbackQuery
):

    await call.answer()

    payload = (
        f"premium:"
        f"{call.from_user.id}:"
        f"{int(time.time())}"
    )

    await bot.send_invoice(
        chat_id=call.from_user.id,
        title="RANDOM PARTY Premium",
        description="Premium на 30 дней",
        payload=payload,
        currency="XTR",
        prices=[
            LabeledPrice(
                label="Premium 30 дней",
                amount=PREMIUM_STARS
            )
        ]
    )


@dp.pre_checkout_query()
async def checkout(
    query: PreCheckoutQuery
):

    if query.currency != "XTR":
        await query.answer(
            ok=False,
            error_message="Неверная валюта."
        )
        return

    if query.total_amount != PREMIUM_STARS:
        await query.answer(
            ok=False,
            error_message="Неверная сумма."
        )
        return

    await query.answer(
        ok=True
    )


@dp.message(F.successful_payment)
async def payment(
    message: Message
):

    payment = message.successful_payment

    if not payment.invoice_payload.startswith(
        "premium:"
    ):
        return

    user_id = message.from_user.id

    activate_premium(
        user_id,
        PREMIUM_DAYS
    )

    with closing(connect()) as db:

        db.execute("""
        INSERT INTO payments
        (user_id, stars, payload, charge_id, created)
        VALUES (?, ?, ?, ?, ?)
        """, (
            user_id,
            payment.total_amount,
            payment.invoice_payload,
            payment.telegram_payment_charge_id,
            int(time.time())
        ))

        db.commit()

    await message.answer(
        """
🎉 <b>PREMIUM АКТИВИРОВАН!</b>

⭐ 30 дней Premium активированы.

Теперь доступны:

⚡ повышенные награды
🎁 усиленный Daily
💎 Premium Jackpot
🎁 усиленные сундуки
👑 Premium-статус
🏟️ специальные функции
""",
        reply_markup=main_menu()
    )

    if ADMIN_ID:

        try:
            await bot.send_message(
                ADMIN_ID,
                f"""
💰 <b>НОВАЯ ПОКУПКА</b>

👤 ID:
<code>{user_id}</code>

⭐ Stars:
<b>{payment.total_amount}</b>
"""
            )
        except Exception:
            pass


# =========================================================
# ADD GROUP
# =========================================================

@dp.callback_query(F.data == "add_group")
async def add_group(call: CallbackQuery):

    await call.answer()

    me = await bot.get_me()

    url = (
        f"https://t.me/{me.username}"
        "?startgroup=true"
    )

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="➕ Добавить в группу",
                    url=url
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
        """
<b>👥 RANDOM PARTY ДЛЯ ГРУПП</b>

Добавь бота в чат.

После этого участники смогут:

🎮 играть
⚔️ устраивать дуэли
🎯 выбирать случайного игрока
🏆 соревноваться
📈 прокачивать группу
🎉 запускать события
💰 зарабатывать монеты

Команды можно использовать прямо в группе.
""",
        reply_markup=kb
    )


# =========================================================
# GROUP START
# =========================================================

@dp.message(Command("party"))
async def party(message: Message):

    if message.chat.type not in (
        ChatType.GROUP,
        ChatType.SUPERGROUP
    ):
        return

    ensure_group(message)

    await message.answer(
        """
🎲 <b>RANDOM PARTY подключён!</b>

Теперь эта группа — игровая арена.

🎮 <b>Играть</b> — /games
⚔️ <b>Дуэль</b> — /duel
🎯 <b>Случайный игрок</b> — /random
🎲 <b>Кубик</b> — /dice
🎰 <b>Слот</b> — /slot
🧠 <b>Викторина</b> — /quiz
🏆 <b>Рейтинг</b> — /top
🎉 <b>Событие</b> — /event

🔥 Зови друзей и прокачивай арену!
"""
    )


@dp.message(Command("games"))
async def group_games(message: Message):

    if message.chat.type not in (
        ChatType.GROUP,
        ChatType.SUPERGROUP
    ):
        return

    ensure_group(message)

    await message.answer(
        """
🎮 <b>ИГРЫ</b>

/dice — кубик
/coin — монетка
/slot — слот
/duel — дуэль
/random — случайный игрок
/quiz — викторина
/event — групповое событие
/top — рейтинг
"""
    )


# =========================================================
# GROUP RANDOM
# =========================================================

@dp.message(Command("random"))
async def random_player(message: Message):

    if message.chat.type not in (
        ChatType.GROUP,
        ChatType.SUPERGROUP
    ):
        return

    ensure_group(message)

    players = group_members(
        message.chat.id
    )

    if not players:

        await message.answer(
            "👥 Пока никто не зарегистрирован."
        )
        return

    player = random.choice(
        players
    )

    name = (
        player[1]
        or player[2]
        or "Игрок"
    )

    await message.answer(
        f"""
🎯 <b>СЛУЧАЙНЫЙ ИГРОК</b>

Сегодня выбран:

🔥 <b>{name}</b>
"""
    )


# =========================================================
# GROUP DUEL
# =========================================================

@dp.message(Command("duel"))
async def duel(message: Message):

    if message.chat.type not in (
        ChatType.GROUP,
        ChatType.SUPERGROUP
    ):
        return

    ensure_group(message)

    players = group_members(
        message.chat.id
    )

    if len(players) < 2:

        await message.answer(
            "⚔️ Нужно минимум 2 участника."
        )

        return

    a, b = random.sample(
        players,
        2
    )

    winner = random.choice(
        [a, b]
    )

    a_name = (
        a[1]
        or a[2]
        or "Игрок"
    )

    b_name = (
        b[1]
        or b[2]
        or "Игрок"
    )

    winner_name = (
        winner[1]
        or winner[2]
        or "Игрок"
    )

    reward = 300

    group_game(
        message.chat.id,
        winner[0],
        win=True,
        reward=reward
    )

    await message.answer(
        f"""
⚔️ <b>ДУЭЛЬ</b>

🥊 {a_name}
VS
🥊 {b_name}

━━━━━━━━━━━━

🏆 Победитель:

<b>{winner_name}</b>

🪙 +{reward}
"""
    )


# =========================================================
# GROUP DICE
# =========================================================

@dp.message(Command("dice"))
async def group_dice(message: Message):

    if message.chat.type not in (
        ChatType.GROUP,
        ChatType.SUPERGROUP
    ):
        return

    ensure_group(message)

    value = random.randint(
        1,
        6
    )

    reward = value * 15

    group_game(
        message.chat.id,
        message.from_user.id,
        reward=reward
    )

    await message.answer(
        f"""
🎲 <b>КУБИК</b>

{message.from_user.first_name}

выпало:

<b>{value}</b>

🪙 +{reward}
"""
    )


# =========================================================
# GROUP COIN
# =========================================================

@dp.message(Command("coin"))
async def group_coin(message: Message):

    if message.chat.type not in (
        ChatType.GROUP,
        ChatType.SUPERGROUP
    ):
        return

    result = random.choice([
        "🦅 ОРЁЛ",
        "🪙 РЕШКА"
    ])

    await message.answer(
        f"🪙 <b>{result}</b>"
    )


# =========================================================
# GROUP SLOT
# =========================================================

@dp.message(Command("slot"))
async def group_slot(message: Message):

    if message.chat.type not in (
        ChatType.GROUP,
        ChatType.SUPERGROUP
    ):
        return

    ensure_group(message)

    symbols = [
        "🍒",
        "🍋",
        "⭐",
        "💎",
        "7️⃣"
    ]

    a, b, c = [
        random.choice(symbols)
        for _ in range(3)
    ]

    if a == b == c:

        reward = 1000
        win = True

        result = "💎 ДЖЕКПОТ!"

    elif (
        a == b
        or
        b == c
        or
        a == c
    ):

        reward = 150
        win = True

        result = "🔥 ПАРА!"

    else:

        reward = 10
        win = False

        result = "😈 Не повезло"

    group_game(
        message.chat.id,
        message.from_user.id,
        win=win,
        reward=reward
    )

    await message.answer(
        f"""
🎰 {a} {b} {c}

{result}

🪙 +{reward}
"""
    )


# =========================================================
# GROUP QUIZ
# =========================================================

@dp.message(Command("quiz"))
async def group_quiz(message: Message):

    if message.chat.type not in (
        ChatType.GROUP,
        ChatType.SUPERGROUP
    ):
        return

    ensure_group(message)

    question, answers, correct = random.choice(
        QUESTIONS
    )

    await message.answer(
        f"""
🧠 <b>ВИКТОРИНА</b>

{question}

1️⃣ {answers[0]}
2️⃣ {answers[1]}
3️⃣ {answers[2]}
4️⃣ {answers[3]}

Первый правильный ответ получает 🪙 <b>500</b>.
"""
    )


@dp.message(
    F.chat.type.in_({
        ChatType.GROUP,
        ChatType.SUPERGROUP
    })
)
async def quiz_text_handler(message: Message):

    # Обычные сообщения не обрабатываем,
    # если это не число 1-4.

    if not message.text:
        return

    if message.text not in (
        "1",
        "2",
        "3",
        "4"
    ):
        return

    # Ничего не начисляем без активной
    # игровой сессии.
    #
    # Этот обработчик оставлен специально,
    # чтобы позже можно было добавить
    # полноценные live-раунды.


# =========================================================
# GROUP TOP
# =========================================================

@dp.message(Command("top"))
async def group_top(message: Message):

    if message.chat.type not in (
        ChatType.GROUP,
        ChatType.SUPERGROUP
    ):
        return

    ensure_group(message)

    rows = group_members(
        message.chat.id
    )

    rows = sorted(
        rows,
        key=lambda x: (
            x[4],
            x[5]
        ),
        reverse=True
    )[:10]

    text = "<b>🏆 ТОП ГРУППЫ</b>\n\n"

    for i, row in enumerate(
        rows,
        1
    ):

        name = (
            row[1]
            or row[2]
            or "Игрок"
        )

        text += (
            f"{i}. <b>{name}</b>\n"
            f"   🏆 {row[4]} | "
            f"🪙 {row[5]}\n"
        )

    await message.answer(
        text
    )


# =========================================================
# GROUP EVENT
# =========================================================

@dp.message(Command("event"))
async def event(message: Message):

    if message.chat.type not in (
        ChatType.GROUP,
        ChatType.SUPERGROUP
    ):
        return

    ensure_group(message)

    players = group_members(
        message.chat.id
    )

    if len(players) < 2:

        await message.answer(
            """
🎉 <b>СОБЫТИЕ</b>

Для запуска события нужно минимум
<b>2 участника</b>.

Пусть участники напишут:

/party
"""
        )

        return

    event_name = random.choice([
        "⚔️ БИТВА АРЕНЫ",
        "💎 ОХОТА ЗА СОКРОВИЩЕМ",
        "🔥 CHAOS EVENT",
        "👑 КОРОЛЬ ГРУППЫ",
        "🎯 ОХОТА"
    ])

    participants = random.sample(
        players,
        min(
            len(players),
            8
        )
    )

    winner = random.choice(
        participants
    )

    winner_name = (
        winner[1]
        or winner[2]
        or "Игрок"
    )

    reward = random.randint(
        500,
        1500
    )

    group_game(
        message.chat.id,
        winner[0],
        win=True,
        reward=reward
    )

    await message.answer(
        f"""
🎉 <b>{event_name}</b>

Участников:
<b>{len(participants)}</b>

🔥 Арена начинается...

3...
2...
1...

━━━━━━━━━━━━

👑 ПОБЕДИТЕЛЬ:

<b>{winner_name}</b>

🪙 <b>+{reward}</b>

🔥 Следующее событие можно
запустить снова через /event
"""
    )


# =========================================================
# USER ID
# =========================================================

@dp.message(Command("id"))
async def get_id(message: Message):

    await message.answer(
        f"""
🆔 Твой Telegram ID:

<code>{message.from_user.id}</code>
"""
    )


# =========================================================
# ADMIN
# =========================================================

@dp.message(Command("stats"))
async def stats(message: Message):

    if message.from_user.id != ADMIN_ID:
        return

    with closing(connect()) as db:

        users = db.execute(
            "SELECT COUNT(*) FROM users"
        ).fetchone()[0]

        groups = db.execute(
            "SELECT COUNT(*) FROM groups"
        ).fetchone()[0]

        premium = db.execute("""
        SELECT COUNT(*)
        FROM users
        WHERE premium_until>?
        """, (
            int(time.time()),
        )).fetchone()[0]

        payments = db.execute(
            "SELECT COUNT(*) FROM payments"
        ).fetchone()[0]

        stars = db.execute(
            "SELECT COALESCE(SUM(stars),0)"
            " FROM payments"
        ).fetchone()[0]

    await message.answer(
        f"""
<b>📊 СТАТИСТИКА</b>

👤 Пользователей:
<b>{users}</b>

👥 Групп:
<b>{groups}</b>

⭐ Premium:
<b>{premium}</b>

💳 Покупок:
<b>{payments}</b>

🌟 Stars:
<b>{stars}</b>
"""
    )


@dp.message(Command("ban"))
async def ban(message: Message):

    if message.from_user.id != ADMIN_ID:
        return

    parts = message.text.split()

    if len(parts) != 2:
        await message.answer(
            "/ban ID"
        )
        return

    if not parts[1].isdigit():
        return

    target = int(
        parts[1]
    )

    with closing(connect()) as db:
        db.execute("""
        UPDATE users
        SET banned=1
        WHERE id=?
        """, (
            target,
        ))
        db.commit()

    await message.answer(
        "🔨 Пользователь заблокирован."
    )


@dp.message(Command("unban"))
async def unban(message: Message):

    if message.from_user.id != ADMIN_ID:
        return

    parts = message.text.split()

    if len(parts) != 2:
        return

    if not parts[1].isdigit():
        return

    target = int(
        parts[1]
    )

    with closing(connect()) as db:
        db.execute("""
        UPDATE users
        SET banned=0
        WHERE id=?
        """, (
            target,
        ))
        db.commit()

    await message.answer(
        "✅ Пользователь разблокирован."
    )


# =========================================================
# HELP
# =========================================================

@dp.callback_query(F.data == "help")
async def help_menu(call: CallbackQuery):

    await call.answer()

    await call.message.edit_text(
        """
<b>ℹ️ RANDOM PARTY</b>

<b>В личке:</b>

/start
/id

<b>В группе:</b>

/party
/games
/duel
/random
/dice
/coin
/slot
/quiz
/top
/event

<b>Админ:</b>

/stats
/ban ID
/unban ID

Главное меню доступно через /start.
""",
        reply_markup=back()
    )


# =========================================================
# PRIVATE FALLBACK
# =========================================================

@dp.message()
async def fallback(message: Message):

    if message.chat.type != ChatType.PRIVATE:
        return

    ensure_user(
        message.from_user
    )

    row = get_user(
        message.from_user.id
    )

    if row and row[13]:
        return

    await message.answer(
        "👇 Выбирай действие:",
        reply_markup=main_menu()
    )


# =========================================================
# START BOT
# =========================================================

async def main():

    init_db()

    me = await bot.get_me()

    logging.info(
        "Started @%s",
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
    asyncio.run(main())