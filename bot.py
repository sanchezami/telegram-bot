import asyncio
import logging
import os
import random
import sqlite3
import time
from contextlib import closing

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ChatType
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    PreCheckoutQuery,
    LabeledPrice,
)


# =========================================================
# CONFIG
# =========================================================

TOKEN = os.getenv("BOT_TOKEN")

# ADMIN_ID необязателен.
ADMIN_ID = os.getenv("ADMIN_ID", "").strip()

DB_FILE = "bot.db"

if not TOKEN:
    raise RuntimeError(
        "BOT_TOKEN не найден. Добавь BOT_TOKEN в Railway Variables."
    )

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

bot = Bot(
    TOKEN,
    default=DefaultBotProperties(
        parse_mode=None
    )
)

dp = Dispatcher()


# =========================================================
# DATABASE
# =========================================================

def connect():
    return sqlite3.connect(
        DB_FILE,
        timeout=30
    )


def init_db():

    with closing(connect()) as con:

        con.execute("""
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
            messages INTEGER DEFAULT 0,
            last_active INTEGER DEFAULT 0,
            last_daily INTEGER DEFAULT 0,
            premium_until INTEGER DEFAULT 0,
            language TEXT DEFAULT 'ru',
            created INTEGER DEFAULT 0
        )
        """)

        con.execute("""
        CREATE TABLE IF NOT EXISTS groups (
            id INTEGER PRIMARY KEY,
            title TEXT DEFAULT '',
            created INTEGER DEFAULT 0
        )
        """)

        con.execute("""
        CREATE TABLE IF NOT EXISTS group_users (
            group_id INTEGER,
            user_id INTEGER,
            messages INTEGER DEFAULT 0,
            games INTEGER DEFAULT 0,
            wins INTEGER DEFAULT 0,
            last_active INTEGER DEFAULT 0,
            PRIMARY KEY(group_id, user_id)
        )
        """)

        con.execute("""
        CREATE TABLE IF NOT EXISTS payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            stars INTEGER,
            payload TEXT,
            charge_id TEXT,
            created INTEGER
        )
        """)

        con.commit()


# =========================================================
# USER SYSTEM
# =========================================================

def ensure_user(user):

    now = int(time.time())

    with closing(connect()) as con:

        con.execute("""
        INSERT INTO users (
            id,
            username,
            name,
            coins,
            xp,
            level,
            messages,
            last_active,
            created
        )
        VALUES (?, ?, ?, 100, 0, 1, 1, ?, ?)

        ON CONFLICT(id)
        DO UPDATE SET
            username=excluded.username,
            name=excluded.name,
            messages=users.messages + 1,
            last_active=excluded.last_active
        """, (
            user.id,
            user.username or "",
            user.first_name or "Игрок",
            now,
            now
        ))

        con.commit()


def get_user(user_id):

    with closing(connect()) as con:

        return con.execute(
            "SELECT * FROM users WHERE id=?",
            (user_id,)
        ).fetchone()


def set_language(user_id, language):

    with closing(connect()) as con:

        con.execute(
            "UPDATE users SET language=? WHERE id=?",
            (language, user_id)
        )

        con.commit()


def add_coins(user_id, amount):

    with closing(connect()) as con:

        con.execute("""
        UPDATE users
        SET coins = coins + ?
        WHERE id=?
        """, (
            amount,
            user_id
        ))

        con.commit()


def get_coins(user_id):

    row = get_user(user_id)

    if not row:
        return 0

    return row[3]


def add_xp(user_id, amount):

    with closing(connect()) as con:

        row = con.execute("""
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

        con.execute("""
        UPDATE users
        SET xp=?, level=?
        WHERE id=?
        """, (
            xp,
            level,
            user_id
        ))

        con.commit()


def record_game(
    user_id,
    win=False,
    reward=0
):

    with closing(connect()) as con:

        con.execute("""
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

        con.commit()

    add_xp(
        user_id,
        30 if win else 10
    )


# =========================================================
# GROUP ACTIVITY
# =========================================================

def ensure_group(message):

    if message.chat.type not in (
        ChatType.GROUP,
        ChatType.SUPERGROUP
    ):
        return

    now = int(time.time())

    with closing(connect()) as con:

        con.execute("""
        INSERT INTO groups (
            id,
            title,
            created
        )
        VALUES (?, ?, ?)

        ON CONFLICT(id)
        DO UPDATE SET title=excluded.title
        """, (
            message.chat.id,
            message.chat.title or "Группа",
            now
        ))

        con.execute("""
        INSERT INTO group_users (
            group_id,
            user_id,
            messages,
            last_active
        )
        VALUES (?, ?, 1, ?)

        ON CONFLICT(group_id, user_id)
        DO UPDATE SET
            messages=group_users.messages+1,
            last_active=excluded.last_active
        """, (
            message.chat.id,
            message.from_user.id,
            now
        ))

        con.commit()


def group_game(
    group_id,
    user_id,
    win=False
):

    with closing(connect()) as con:

        con.execute("""
        UPDATE group_users
        SET
            games=games+1,
            wins=wins+?
        WHERE group_id=? AND user_id=?
        """, (
            1 if win else 0,
            group_id,
            user_id
        ))

        con.commit()


def get_group_players(
    group_id,
    active_days=7
):

    cutoff = int(time.time()) - (
        active_days * 86400
    )

    with closing(connect()) as con:

        return con.execute("""
        SELECT
            gu.user_id,
            u.name,
            u.username,
            gu.messages,
            gu.games,
            gu.wins,
            gu.last_active
        FROM group_users gu
        JOIN users u
        ON u.id=gu.user_id
        WHERE gu.group_id=?
        AND gu.last_active>=?
        ORDER BY gu.last_active DESC
        """, (
            group_id,
            cutoff
        )).fetchall()


# =========================================================
# TEXT
# =========================================================

def user_name(user):

    return (
        user.first_name
        or user.username
        or "Игрок"
    )


def player_name(row):

    return (
        row[1]
        or row[2]
        or "Игрок"
    )


# =========================================================
# HOME
# =========================================================

def home_keyboard():

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🎮 Игры",
                    callback_data="games"
                ),
                InlineKeyboardButton(
                    text="👤 Профиль",
                    callback_data="profile"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🏆 Рейтинг",
                    callback_data="top"
                ),
                InlineKeyboardButton(
                    text="🎁 Daily",
                    callback_data="daily"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🎭 Мафия",
                    callback_data="mafia_help"
                ),
                InlineKeyboardButton(
                    text="🌐 Язык",
                    callback_data="language"
                )
            ],
            [
                InlineKeyboardButton(
                    text="👥 Добавить в группу",
                    callback_data="add_group"
                )
            ]
        ]
    )


# =========================================================
# START
# =========================================================

@dp.message(CommandStart())
async def start(message: Message):

    ensure_user(message.from_user)

    if message.chat.type != ChatType.PRIVATE:
        return

    await message.answer(
        """
🎲 RANDOM PARTY

Бот для общения и игр в Telegram.

Что здесь есть:

🎮 мини-игры
🎭 полноценная Мафия
👥 взаимодействие участников
🏆 рейтинги
📊 активность
⚔️ дуэли
🎁 Daily
📈 уровни и XP
💰 виртуальная экономика
🌐 русский / English

Для группы добавь бота и напиши:

/party
""",
        reply_markup=home_keyboard()
    )


# =========================================================
# BOT ADDED
# =========================================================

@dp.my_chat_member()
async def bot_added(event):

    if event.chat.type not in (
        ChatType.GROUP,
        ChatType.SUPERGROUP
    ):
        return

    old_status = event.old_chat_member.status
    new_status = event.new_chat_member.status

    if new_status not in (
        "member",
        "administrator"
    ):
        return

    if old_status in (
        "member",
        "administrator"
    ):
        return

    with closing(connect()) as con:

        con.execute("""
        INSERT OR REPLACE INTO groups (
            id,
            title,
            created
        )
        VALUES (?, ?, ?)
        """, (
            event.chat.id,
            event.chat.title or "Группа",
            int(time.time())
        ))

        con.commit()

    me = await bot.get_me()

    add_url = (
        f"https://t.me/{me.username}"
        "?startgroup=true"
    )

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🎮 Что умеет бот",
                    callback_data="group_help"
                )
            ],
            [
                InlineKeyboardButton(
                    text="➕ Добавить в другую группу",
                    url=add_url
                )
            ]
        ]
    )

    await bot.send_message(
        event.chat.id,
        """
🎉 RANDOM PARTY подключён!

Теперь участники группы могут:

🎮 играть
🎭 запускать Мафию
⚔️ устраивать дуэли
🎯 выбирать случайного участника
🏆 соревноваться в рейтинге
📊 прокачивать уровни
🎁 получать Daily
💬 взаимодействовать друг с другом

Напиши:

/party

чтобы открыть команды.

🎭 Мафия:

/mafia
""",
        reply_markup=keyboard
    )


# =========================================================
# PARTY
# =========================================================

@dp.message(Command("party"))
async def party(message: Message):

    if message.chat.type not in (
        ChatType.GROUP,
        ChatType.SUPERGROUP
    ):
        await message.answer(
            "Эта команда предназначена для групп."
        )
        return

    ensure_user(message.from_user)
    ensure_group(message)

    await message.answer(
        """
🎲 RANDOM PARTY

🎮 ИГРЫ

/dice
/coin
/slot
/duel
/random

🎭 МАФИЯ

/mafia
/join
/startmafia
/mafia_status
/day
/vote ИМЯ

🏆 СОЦИАЛЬНОЕ

/top
/activity
/event

👤 ПРОФИЛЬ

/profile
"""
    )


# =========================================================
# DICE
# =========================================================

@dp.message(Command("dice"))
async def dice(message: Message):

    if message.chat.type not in (
        ChatType.GROUP,
        ChatType.SUPERGROUP
    ):
        return

    ensure_user(message.from_user)
    ensure_group(message)

    value = random.randint(1, 6)

    reward = {
        1: -30,
        2: -10,
        3: 0,
        4: 10,
        5: 25,
        6: 50
    }[value]

    add_coins(
        message.from_user.id,
        reward
    )

    record_game(
        message.from_user.id,
        reward > 0,
        reward
    )

    group_game(
        message.chat.id,
        message.from_user.id,
        reward > 0
    )

    sign = "+" if reward > 0 else ""

    await message.answer(
        f"""
🎲 {user_name(message.from_user)}

Выпало: {value}

🪙 {sign}{reward}
"""
    )


# =========================================================
# COIN
# =========================================================

@dp.message(Command("coin"))
async def coin(message: Message):

    if message.chat.type not in (
        ChatType.GROUP,
        ChatType.SUPERGROUP
    ):
        return

    ensure_user(message.from_user)
    ensure_group(message)

    result = random.choice([
        "ОРЁЛ",
        "РЕШКА"
    ])

    await message.answer(
        f"""
🪙 МОНЕТКА

{result}
"""
    )


# =========================================================
# SLOT
# =========================================================

@dp.message(Command("slot"))
async def slot(message: Message):

    if message.chat.type not in (
        ChatType.GROUP,
        ChatType.SUPERGROUP
    ):
        return

    ensure_user(message.from_user)
    ensure_group(message)

    symbols = [
        "🍒",
        "🍋",
        "🍊",
        "⭐",
        "💎",
        "7"
    ]

    result = [
        random.choice(symbols)
        for _ in range(3)
    ]

    a, b, c = result

    if a == b == c:

        reward = 300
        win = True
        text = "💎 ДЖЕКПОТ"

    elif a == b or b == c or a == c:

        reward = 50
        win = True
        text = "🔥 ПАРА"

    else:

        reward = -25
        win = False
        text = "❌ Не повезло"

    add_coins(
        message.from_user.id,
        reward
    )

    record_game(
        message.from_user.id,
        win,
        reward
    )

    group_game(
        message.chat.id,
        message.from_user.id,
        win
    )

    sign = "+" if reward > 0 else ""

    await message.answer(
        f"""
🎰 {a} {b} {c}

{text}

🪙 {sign}{reward}
"""
    )


# =========================================================
# RANDOM PLAYER
# =========================================================

@dp.message(Command("random"))
async def random_player(message: Message):

    if message.chat.type not in (
        ChatType.GROUP,
        ChatType.SUPERGROUP
    ):
        return

    ensure_user(message.from_user)
    ensure_group(message)

    players = get_group_players(
        message.chat.id,
        active_days=7
    )

    players = [
        p for p in players
        if p[0] != message.from_user.id
    ]

    if not players:

        await message.answer(
            """
🎯 Пока недостаточно активных участников.

Пусть несколько человек напишут сообщения в группе.
"""
        )

        return

    # Учитываем активность.
    # Чем активнее участник, тем выше его шанс,
    # но это не гарантирует выбор.
    weighted = []

    for p in players:

        messages = p[3] or 0
        games = p[4] or 0
        wins = p[5] or 0

        weight = 1

        weight += min(messages // 10, 10)
        weight += min(games, 5)
        weight += min(wins, 5)

        weighted.extend(
            [p] * weight
        )

    selected = random.choice(
        weighted
    )

    await message.answer(
        f"""
🎯 СЛУЧАЙНЫЙ УЧАСТНИК

👤 {player_name(selected)}

💬 Сообщений: {selected[3]}
🎮 Игр: {selected[4]}
🏆 Побед: {selected[5]}

👥 Учитывались активные участники
за последние 7 дней.
"""
    )


# =========================================================
# DUEL
# =========================================================

@dp.message(Command("duel"))
async def duel(message: Message):

    if message.chat.type not in (
        ChatType.GROUP,
        ChatType.SUPERGROUP
    ):
        return

    ensure_user(message.from_user)
    ensure_group(message)

    players = get_group_players(
        message.chat.id
    )

    players = [
        p for p in players
        if p[0] != message.from_user.id
    ]

    if not players:

        await message.answer(
            "⚔️ Нужен хотя бы ещё один активный участник."
        )

        return

    opponent = random.choice(players)

    winner_id = random.choice([
        message.from_user.id,
        opponent[0]
    ])

    if winner_id == message.from_user.id:

        reward = 100
        winner_name = user_name(
            message.from_user
        )

        record_game(
            winner_id,
            True,
            reward
        )

        add_coins(
            winner_id,
            reward
        )

        group_game(
            message.chat.id,
            winner_id,
            True
        )

    else:

        reward = 100
        winner_name = player_name(opponent)

        record_game(
            winner_id,
            True,
            reward
        )

        add_coins(
            winner_id,
            reward
        )

        group_game(
            message.chat.id,
            winner_id,
            True
        )

    await message.answer(
        f"""
⚔️ ДУЭЛЬ

🥊 {user_name(message.from_user)}
VS
🥊 {player_name(opponent)}

🏆 Победитель:

{winner_name}

🪙 Победитель получает +100
"""
    )


# =========================================================
# TOP
# =========================================================

@dp.message(Command("top"))
async def top(message: Message):

    if message.chat.type not in (
        ChatType.GROUP,
        ChatType.SUPERGROUP
    ):
        return

    ensure_group(message)

    players = get_group_players(
        message.chat.id,
        active_days=30
    )

    players.sort(
        key=lambda p: (
            p[5],
            p[4],
            p[3]
        ),
        reverse=True
    )

    if not players:

        await message.answer(
            "🏆 Пока рейтинг пуст."
        )

        return

    text = "🏆 РЕЙТИНГ ГРУППЫ\n\n"

    for i, p in enumerate(
        players[:10],
        1
    ):

        text += (
            f"{i}. {player_name(p)} — "
            f"{p[5]} побед | "
            f"{p[4]} игр | "
            f"{p[3]} сообщений\n"
        )

    await message.answer(text)


# =========================================================
# ACTIVITY
# =========================================================

@dp.message(Command("activity"))
async def activity(message: Message):

    if message.chat.type not in (
        ChatType.GROUP,
        ChatType.SUPERGROUP
    ):
        return

    ensure_group(message)

    players = get_group_players(
        message.chat.id,
        active_days=7
    )

    players.sort(
        key=lambda p: p[3],
        reverse=True
    )

    if not players:

        await message.answer(
            "📊 Пока нет статистики."
        )

        return

    text = "📊 АКТИВНОСТЬ ЗА 7 ДНЕЙ\n\n"

    for i, p in enumerate(
        players[:10],
        1
    ):

        text += (
            f"{i}. {player_name(p)} — "
            f"💬 {p[3]}\n"
        )

    await message.answer(text)


# =========================================================
# EVENT
# =========================================================

@dp.message(Command("event"))
async def event(message: Message):

    if message.chat.type not in (
        ChatType.GROUP,
        ChatType.SUPERGROUP
    ):
        return

    ensure_group(message)

    players = get_group_players(
        message.chat.id
    )

    if len(players) < 2:

        await message.answer(
            "🎉 Для события нужно минимум 2 активных участника."
        )

        return

    selected = random.choice(players)

    reward = random.randint(
        100,
        500
    )

    add_coins(
        selected[0],
        reward
    )

    record_game(
        selected[0],
        True,
        reward
    )

    await message.answer(
        f"""
🎉 СОБЫТИЕ

Сегодня повезло:

👤 {player_name(selected)}

🪙 +{reward}
"""
    )


# =========================================================
# PROFILE
# =========================================================

@dp.message(Command("profile"))
async def profile_command(message: Message):

    ensure_user(message.from_user)

    row = get_user(
        message.from_user.id
    )

    games = row[6]
    wins = row[7]
    losses = row[8]

    winrate = (
        round(wins / games * 100, 1)
        if games
        else 0
    )

    await message.answer(
        f"""
👤 ПРОФИЛЬ

{row[2]}

🪙 Монеты: {row[3]}

🏅 Уровень: {row[5]}
⚡ XP: {row[4]}/{row[5] * 100}

🎮 Игр: {games}
🏆 Побед: {wins}
💀 Поражений: {losses}

📊 Винрейт: {winrate}%

💬 Сообщений: {row[9]}
"""
    )


# =========================================================
# DAILY
# =========================================================

@dp.message(Command("daily"))
async def daily_command(message: Message):

    ensure_user(message.from_user)

    user = get_user(
        message.from_user.id
    )

    now = int(time.time())

    if now - user[11] < 86400:

        remaining = (
            86400
            - (now - user[11])
        )

        hours = remaining // 3600
        minutes = (
            remaining % 3600
        ) // 60

        await message.answer(
            f"""
🎁 DAILY

Ты уже забрал награду.

⏳ Осталось:
{hours}ч {minutes}мин
"""
        )

        return

    reward = 200

    add_coins(
        message.from_user.id,
        reward
    )

    add_xp(
        message.from_user.id,
        25
    )

    with closing(connect()) as con:

        con.execute("""
        UPDATE users
        SET last_daily=?
        WHERE id=?
        """, (
            now,
            message.from_user.id
        ))

        con.commit()

    await message.answer(
        f"""
🎁 DAILY

🪙 +{reward}

Возвращайся завтра.
"""
    )


# =========================================================
# MAFIA
# =========================================================

MAFIA = {}


def mafia_get(chat_id):

    if chat_id not in MAFIA:

        MAFIA[chat_id] = {
            "players": {},
            "active": False,
            "phase": "lobby",
            "night": 0,
            "votes": {},
            "night_actions": {},
            "message_id": None
        }

    return MAFIA[chat_id]


def mafia_reset(chat_id):

    MAFIA.pop(
        chat_id,
        None
    )


def alive_players(state):

    return {
        uid: p
        for uid, p in state["players"].items()
        if p["alive"]
    }


def mafia_count(state):

    return sum(
        1
        for p in state["players"].values()
        if p["alive"]
        and p["role"] == "mafia"
    )


def citizen_count(state):

    return sum(
        1
        for p in state["players"].values()
        if p["alive"]
        and p["role"] != "mafia"
    )


async def mafia_finish_if_needed(
    chat_id
):

    state = mafia_get(chat_id)

    if not state["active"]:
        return True

    mafia = mafia_count(state)
    citizens = citizen_count(state)

    if mafia == 0:

        state["active"] = False

        await bot.send_message(
            chat_id,
            """
🏁 МАФИЯ ЗАКОНЧИЛАСЬ

👥 Победили мирные жители!
"""
        )

        mafia_reset(chat_id)

        return True

    if mafia >= citizens:

        state["active"] = False

        await bot.send_message(
            chat_id,
            """
🏁 МАФИЯ ЗАКОНЧИЛАСЬ

🔪 Мафия получила большинство и победила!
"""
        )

        mafia_reset(chat_id)

        return True

    return False


# =========================================================
# CREATE MAFIA
# =========================================================

@dp.message(Command("mafia"))
async def mafia_create(message: Message):

    if message.chat.type not in (
        ChatType.GROUP,
        ChatType.SUPERGROUP
    ):
        await message.answer(
            "🎭 Мафия запускается в группе."
        )
        return

    ensure_user(message.from_user)
    ensure_group(message)

    state = mafia_get(
        message.chat.id
    )

    if state["active"]:

        await message.answer(
            "🎭 Игра уже идёт."
        )

        return

    if state["players"]:

        await message.answer(
            f"""
🎭 Мафия уже собирается.

👥 Игроков:
{len(state["players"])}

/join — присоединиться
/startmafia — начать
"""
        )

        return

    state["players"][
        message.from_user.id
    ] = {
        "name": user_name(message.from_user),
        "role": None,
        "alive": True
    }

    await message.answer(
        """
🎭 МАФИЯ

Игра создана.

Минимум: 5 игроков
Максимум: 15 игроков

Для участия:

/join

Когда соберётся команда:

/startmafia
"""
    )


# =========================================================
# JOIN
# =========================================================

@dp.message(Command("join"))
async def mafia_join(message: Message):

    if message.chat.type not in (
        ChatType.GROUP,
        ChatType.SUPERGROUP
    ):
        return

    ensure_user(message.from_user)
    ensure_group(message)

    state = mafia_get(
        message.chat.id
    )

    if state["active"]:

        await message.answer(
            "🎭 Игра уже началась."
        )

        return

    if not state["players"]:

        await message.answer(
            "Сначала напиши /mafia"
        )

        return

    if message.from_user.id in state["players"]:

        await message.answer(
            "Ты уже участвуешь."
        )

        return

    if len(state["players"]) >= 15:

        await message.answer(
            "🎭 Лобби заполнено. Максимум 15 игроков."
        )

        return

    state["players"][
        message.from_user.id
    ] = {
        "name": user_name(message.from_user),
        "role": None,
        "alive": True
    }

    await message.answer(
        f"""
➕ {user_name(message.from_user)}
вошёл в Мафию.

👥 Игроков:
{len(state["players"])}
"""
    )


# =========================================================
# START MAFIA
# =========================================================

@dp.message(Command("startmafia"))
async def mafia_start(message: Message):

    if message.chat.type not in (
        ChatType.GROUP,
        ChatType.SUPERGROUP
    ):
        return

    state = mafia_get(
        message.chat.id
    )

    if state["active"]:

        await message.answer(
            "🎭 Игра уже идёт."
        )

        return

    players = list(
        state["players"].keys()
    )

    if len(players) < 5:

        await message.answer(
            f"""
❌ Недостаточно игроков.

Сейчас:
{len(players)}

Нужно минимум:
5

/join
"""
        )

        return

    random.shuffle(players)

    count = len(players)

    mafia_number = max(
        1,
        count // 4
    )

    roles = (
        ["mafia"] * mafia_number
        + ["commissioner"]
        + ["doctor"]
        + ["citizen"] * (
            count
            - mafia_number
            - 2
        )
    )

    random.shuffle(roles)

    for uid, role in zip(
        players,
        roles
    ):

        state["players"][uid]["role"] = role

    state["active"] = True
    state["phase"] = "night"
    state["night"] = 1

    # ВАЖНО:
    # роли отправляются ТОЛЬКО в личные сообщения.
    # В группу роли не отправляются.

    for uid, player in state["players"].items():

        role = player["role"]

        if role == "mafia":

            role_text = """
🔪 ТЫ — МАФИЯ

Ночью выбери жертву.

Используй:

/kill ИМЯ
"""

        elif role == "commissioner":

            role_text = """
🕵️ ТЫ — КОМИССАР

Ночью можешь проверить одного игрока.

Используй:

/check ИМЯ

Ты узнаешь, является ли он мафией.
"""

        elif role == "doctor":

            role_text = """
❤️ ТЫ — ДОКТОР

Ночью можешь спасти одного игрока.

Используй:

/save ИМЯ
"""

        else:

            role_text = """
👤 ТЫ — МИРНЫЙ ЖИТЕЛЬ

Твоя задача — вычислить мафию
и голосовать против неё днём.
"""

        try:

            await bot.send_message(
                uid,
                f"""
🎭 ТВОЯ РОЛЬ

{role_text}

⚠️ Никому не показывай это сообщение.
"""
            )

        except Exception:

            pass

    await message.answer(
        f"""
🎭 МАФИЯ НАЧАЛАСЬ

👥 Игроков: {count}

🌙 НОЧЬ 1

Роли отправлены игрокам
в личные сообщения.

🔪 Мафия — выбирает жертву.
🕵️ Комиссар — проверяет игрока.
❤️ Доктор — спасает игрока.

⚠️ Роли скрыты от группы.

Когда ночные действия выполнены,
бот автоматически начнёт день.
"""
    )


# =========================================================
# MAFIA STATUS
# =========================================================

@dp.message(Command("mafia_status"))
async def mafia_status(message: Message):

    if message.chat.type not in (
        ChatType.GROUP,
        ChatType.SUPERGROUP
    ):
        return

    state = mafia_get(
        message.chat.id
    )

    if not state["players"]:

        await message.answer(
            "🎭 Активной Мафии нет."
        )

        return

    alive = alive_players(state)

    text = f"""
🎭 МАФИЯ

👥 Всего:
{len(state["players"])}

❤️ Живых:
{len(alive)}

🌙 Ночь:
{state["night"]}

📍 Фаза:
{state["phase"]}

Живые игроки:

"""

    for p in alive.values():

        text += f"• {p['name']}\n"

    await message.answer(text)


# =========================================================
# NIGHT ACTION HELP
# =========================================================

async def mafia_check_night(
    chat_id
):

    state = mafia_get(chat_id)

    if not state["active"]:
        return

    actions = state["night_actions"]

    mafia_action = any(
        a[0] == "kill"
        for a in actions.values()
    )

    doctor_action = any(
        a[0] == "save"
        for a in actions.values()
    )

    commissioner_action = any(
        a[0] == "check"
        for a in actions.values()
    )

    mafia_exists = any(
        p["alive"]
        and p["role"] == "mafia"
        for p in state["players"].values()
    )

    commissioner_exists = any(
        p["alive"]
        and p["role"] == "commissioner"
        for p in state["players"].values()
    )

    doctor_exists = any(
        p["alive"]
        and p["role"] == "doctor"
        for p in state["players"].values()
    )

    mafia_done = (
        not mafia_exists
        or mafia_action
    )

    doctor_done = (
        not doctor_exists
        or doctor_action
    )

    commissioner_done = (
        not commissioner_exists
        or commissioner_action
    )

    if (
        mafia_done
        and doctor_done
        and commissioner_done
    ):

        await resolve_night(
            chat_id
        )


# =========================================================
# KILL
# =========================================================

@dp.message(Command("kill"))
async def mafia_kill(
    message: Message,
    command: CommandObject
):

    if message.chat.type != ChatType.PRIVATE:
        await message.answer(
            "🔪 Эту команду используй в личке с ботом."
        )
        return

    # Ищем игру пользователя
    found = None

    for chat_id, state in MAFIA.items():

        if (
            message.from_user.id
            in state["players"]
            and state["active"]
        ):

            found = (
                chat_id,
                state
            )

            break

    if not found:
        return

    chat_id, state = found

    player = state["players"][
        message.from_user.id
    ]

    if player["role"] != "mafia":
        await message.answer(
            "❌ Ты не мафия."
        )
        return

    if not player["alive"]:
        await message.answer(
            "💀 Ты выбыл."
        )
        return

    if state["phase"] != "night":
        await message.answer(
            "☀️ Сейчас день."
        )
        return

    if not command.args:
        await message.answer(
            "Используй:\n/kill ИМЯ"
        )
        return

    target_name = command.args.strip()

    target_id = None

    for uid, p in state["players"].items():

        if (
            p["alive"]
            and p["name"].lower()
            == target_name.lower()
        ):
            target_id = uid
            break

    if target_id is None:

        await message.answer(
            "❌ Игрок не найден."
        )
        return

    if target_id == message.from_user.id:

        await message.answer(
            "❌ Нельзя выбрать себя."
        )
        return

    state["night_actions"][
        message.from_user.id
    ] = (
        "kill",
        target_id
    )

    await message.answer(
        f"🔪 Цель выбрана: {state['players'][target_id]['name']}"
    )

    await mafia_check_night(
        chat_id
    )


# =========================================================
# SAVE
# =========================================================

@dp.message(Command("save"))
async def mafia_save(
    message: Message,
    command: CommandObject
):

    if message.chat.type != ChatType.PRIVATE:
        await message.answer(
            "❤️ Эту команду используй в личке."
        )
        return

    found = None

    for chat_id, state in MAFIA.items():

        if (
            message.from_user.id
            in state["players"]
            and state["active"]
        ):

            found = (
                chat_id,
                state
            )

            break

    if not found:
        return

    chat_id, state = found

    player = state["players"][
        message.from_user.id
    ]

    if player["role"] != "doctor":

        await message.answer(
            "❌ Ты не доктор."
        )
        return

    if state["phase"] != "night":

        await message.answer(
            "☀️ Сейчас день."
        )
        return

    if not command.args:

        await message.answer(
            "Используй:\n/save ИМЯ"
        )
        return

    target_name = command.args.strip()

    target_id = None

    for uid, p in state["players"].items():

        if (
            p["alive"]
            and p["name"].lower()
            == target_name.lower()
        ):
            target_id = uid
            break

    if target_id is None:

        await message.answer(
            "❌ Игрок не найден."
        )
        return

    state["night_actions"][
        message.from_user.id
    ] = (
        "save",
        target_id
    )

    await message.answer(
        f"❤️ Ты выбрал: {state['players'][target_id]['name']}"
    )

    await mafia_check_night(
        chat_id
    )


# =========================================================
# CHECK
# =========================================================

@dp.message(Command("check"))
async def mafia_check(
    message: Message,
    command: CommandObject
):

    if message.chat.type != ChatType.PRIVATE:
        await message.answer(
            "🕵️ Эту команду используй в личке."
        )
        return

    found = None

    for chat_id, state in MAFIA.items():

        if (
            message.from_user.id
            in state["players"]
            and state["active"]
        ):

            found = (
                chat_id,
                state
            )

            break

    if not found:
        return

    chat_id, state = found

    player = state["players"][
        message.from_user.id
    ]

    if player["role"] != "commissioner":

        await message.answer(
            "❌ Ты не комиссар."
        )
        return

    if state["phase"] != "night":

        await message.answer(
            "☀️ Сейчас день."
        )
        return

    if not command.args:

        await message.answer(
            "Используй:\n/check ИМЯ"
        )
        return

    target_name = command.args.strip()

    target_id = None

    for uid, p in state["players"].items():

        if (
            p["alive"]
            and p["name"].lower()
            == target_name.lower()
        ):
            target_id = uid
            break

    if target_id is None:

        await message.answer(
            "❌ Игрок не найден."
        )
        return

    if target_id == message.from_user.id:

        await message.answer(
            "❌ Нельзя проверить себя."
        )
        return

    target = state["players"][target_id]

    result = (
        "🔴 МАФИЯ"
        if target["role"] == "mafia"
        else "🟢 НЕ МАФИЯ"
    )

    # Результат видит только комиссар.
    await message.answer(
        f"""
🕵️ РЕЗУЛЬТАТ ПРОВЕРКИ

Игрок:
{target['name']}

Результат:
{result}
"""
    )

    state["night_actions"][
        message.from_user.id
    ] = (
        "check",
        target_id
    )

    await mafia_check_night(
        chat_id
    )


# =========================================================
# RESOLVE NIGHT
# =========================================================

async def resolve_night(chat_id):

    state = mafia_get(chat_id)

    if not state["active"]:
        return

    if state["phase"] != "night":
        return

    kill_target = None
    save_target = None

    for action in state["night_actions"].values():

        action_type, target = action

        if action_type == "kill":
            kill_target = target

        elif action_type == "save":
            save_target = target

    victim = None

    if (
        kill_target is not None
        and kill_target != save_target
    ):

        if state["players"][kill_target]["alive"]:

            state["players"][kill_target]["alive"] = False
            victim = state["players"][kill_target]["name"]

    state["night_actions"] = {}

    if victim:

        await bot.send_message(
            chat_id,
            f"""
🌅 НАСТУПИЛО УТРО

Ночью погиб:

💀 {victim}

Его роль не раскрывается сразу.

Обсуждайте подозреваемых.
"""
        )

    else:

        await bot.send_message(
            chat_id,
            """
🌅 НАСТУПИЛО УТРО

Никто не погиб.

Возможно, доктор спас жертву.
"""
        )

    ended = await mafia_finish_if_needed(
        chat_id
    )

    if ended:
        return

    state["phase"] = "day"
    state["votes"] = {}

    alive = alive_players(state)

    text = """
☀️ ДЕНЬ

Живые игроки:

"""

    for p in alive.values():

        text += (
            f"• {p['name']}\n"
        )

    text += """

Обсуждайте подозреваемых.

Голосование:

/vote ИМЯ
"""

    await bot.send_message(
        chat_id,
        text
    )


# =========================================================
# DAY
# =========================================================

@dp.message(Command("day"))
async def mafia_day(message: Message):

    if message.chat.type not in (
        ChatType.GROUP,
        ChatType.SUPERGROUP
    ):
        return

    state = mafia_get(
        message.chat.id
    )

    if not state["active"]:
        return

    if state["phase"] != "night":

        await message.answer(
            "☀️ Уже день."
        )

        return

    await resolve_night(
        message.chat.id
    )


# =========================================================
# VOTE
# =========================================================

@dp.message(Command("vote"))
async def mafia_vote(
    message: Message,
    command: CommandObject
):

    if message.chat.type not in (
        ChatType.GROUP,
        ChatType.SUPERGROUP
    ):
        return

    state = mafia_get(
        message.chat.id
    )

    if not state["active"]:
        return

    if state["phase"] != "day":

        await message.answer(
            "🌙 Сейчас ночь."
        )

        return

    voter = state["players"].get(
        message.from_user.id
    )

    if not voter or not voter["alive"]:

        await message.answer(
            "💀 Ты не можешь голосовать."
        )

        return

    if message.from_user.id in state["votes"]:

        await message.answer(
            "🗳 Ты уже проголосовал."
        )

        return

    if not command.args:

        await message.answer(
            "Используй:\n/vote ИМЯ"
        )

        return

    target_name = command.args.strip()

    target_id = None

    for uid, p in state["players"].items():

        if (
            p["alive"]
            and p["name"].lower()
            == target_name.lower()
        ):
            target_id = uid
            break

    if target_id is None:

        await message.answer(
            "❌ Игрок не найден."
        )

        return

    if target_id == message.from_user.id:

        await message.answer(
            "❌ Нельзя голосовать за себя."
        )

        return

    state["votes"][
        message.from_user.id
    ] = target_id

    alive = alive_players(state)

    await message.answer(
        f"""
🗳 Голос принят.

Проголосовало:
{len(state["votes"])}/{len(alive)}
"""
    )

    if len(state["votes"]) >= len(alive):

        counts = {}

        for target in state["votes"].values():

            counts[target] = (
                counts.get(target, 0) + 1
            )

        max_votes = max(
            counts.values()
        )

        candidates = [
            uid
            for uid, votes in counts.items()
            if votes == max_votes
        ]

        # При ничьей никто не выбывает.
        if len(candidates) > 1:

            await message.answer(
                """
⚖️ НИЧЬЯ

Никто не выбывает.

Наступает ночь.
"""
            )

            state["votes"] = {}
            state["phase"] = "night"
            state["night"] += 1

            await bot.send_message(
                message.chat.id,
                f"""
🌙 НОЧЬ {state['night']}

Мафия, комиссар и доктор
могут выполнять свои действия
в личных сообщениях.
"""
            )

            return

        eliminated = candidates[0]

        state["players"][
            eliminated
        ]["alive"] = False

        eliminated_name = state["players"][
            eliminated
        ]["name"]

        # Роль раскрывается только после дневного голосования.
        eliminated_role = state["players"][
            eliminated
        ]["role"]

        role_names = {
            "mafia": "🔪 Мафия",
            "commissioner": "🕵️ Комиссар",
            "doctor": "❤️ Доктор",
            "citizen": "👤 Мирный житель"
        }

        await message.answer(
            f"""
⚖️ ГОЛОСОВАНИЕ ЗАКОНЧЕНО

💀 Выбывает:

{eliminated_name}

🎭 Его роль:

{role_names[eliminated_role]}
"""
        )

        state["votes"] = {}

        ended = await mafia_finish_if_needed(
            message.chat.id
        )

        if ended:
            return

        state["phase"] = "night"
        state["night"] += 1

        await message.answer(
            f"""
🌙 НОЧЬ {state['night']}

Все ночные действия выполняются
в личной переписке с ботом.

🔪 Мафия:
/kill ИМЯ

🕵️ Комиссар:
/check ИМЯ

❤️ Доктор:
/save ИМЯ
"""
        )


# =========================================================
# LANGUAGE
# =========================================================

@dp.callback_query(F.data == "language")
async def language_menu(
    call: CallbackQuery
):

    await call.answer()

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🇷🇺 Русский",
                    callback_data="lang_ru"
                ),
                InlineKeyboardButton(
                    text="🇬🇧 English",
                    callback_data="lang_en"
                )
            ]
        ]
    )

    await call.message.answer(
        "🌐 Выбери язык / Choose language:",
        reply_markup=keyboard
    )


@dp.callback_query(F.data.startswith("lang_"))
async def language_change(
    call: CallbackQuery
):

    language = call.data.replace(
        "lang_",
        ""
    )

    set_language(
        call.from_user.id,
        language
    )

    await call.answer(
        "Язык изменён."
    )


# =========================================================
# BUTTONS
# =========================================================

@dp.callback_query(F.data == "games")
async def games_button(
    call: CallbackQuery
):

    await call.answer()

    await call.message.answer(
        """
🎮 ИГРЫ

В группе:

/dice
/coin
/slot
/duel
/random
/event

Большая игра:

/mafia
"""
    )


@dp.callback_query(F.data == "profile")
async def profile_button(
    call: CallbackQuery
):

    await call.answer()

    row = get_user(
        call.from_user.id
    )

    if not row:
        return

    games = row[6]
    wins = row[7]

    winrate = (
        round(
            wins / games * 100,
            1
        )
        if games
        else 0
    )

    await call.message.answer(
        f"""
👤 ПРОФИЛЬ

{row[2]}

🪙 {row[3]} монет
🏅 Уровень {row[5]}
⚡ XP {row[4]}/{row[5] * 100}

🎮 Игр: {games}
🏆 Побед: {wins}
📊 Винрейт: {winrate}%

💬 Сообщений: {row[9]}
"""
    )


@dp.callback_query(F.data == "top")
async def top_button(
    call: CallbackQuery
):

    await call.answer()

    await call.message.answer(
        "🏆 В группе используй /top"
    )


@dp.callback_query(F.data == "daily")
async def daily_button(
    call: CallbackQuery
):

    await call.answer()

    await call.message.answer(
        "🎁 Для получения Daily используй /daily"
    )


@dp.callback_query(F.data == "mafia_help")
async def mafia_help_button(
    call: CallbackQuery
):

    await call.answer()

    await call.message.answer(
        """
🎭 МАФИЯ

Создание:

/mafia

Вход:

/join

Старт:

/startmafia

Статус:

/mafia_status

Днём:

/vote ИМЯ

Ночью бот сам отправляет
каждому специальную роль
в личные сообщения.

🔪 Мафия — /kill ИМЯ
🕵️ Комиссар — /check ИМЯ
❤️ Доктор — /save ИМЯ

Роли не публикуются в группе.
"""
    )


@dp.callback_query(F.data == "group_help")
async def group_help_button(
    call: CallbackQuery
):

    await call.answer()

    await call.message.answer(
        """
🎮 КОМАНДЫ ГРУППЫ

/party — меню
/random — случайный активный участник
/top — рейтинг
/activity — активность

/dice — кубик
/coin — монетка
/slot — слот
/duel — дуэль
/event — событие

🎭 МАФИЯ

/mafia
/join
/startmafia
/mafia_status
/vote ИМЯ
"""
    )


@dp.callback_query(F.data == "add_group")
async def add_group_button(
    call: CallbackQuery
):

    await call.answer()

    me = await bot.get_me()

    url = (
        f"https://t.me/{me.username}"
        "?startgroup=true"
    )

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="➕ Добавить в группу",
                    url=url
                )
            ]
        ]
    )

    await call.message.answer(
        """
👥 ДОБАВИТЬ БОТА

Добавь RANDOM PARTY в группу.

После добавления бот сам покажет
участникам команды.
""",
        reply_markup=keyboard
    )


# =========================================================
# TRACK ALL GROUP MESSAGES
# =========================================================

@dp.message()
async def track_activity(
    message: Message
):

    if message.from_user.is_bot:
        return

    ensure_user(
        message.from_user
    )

    if message.chat.type in (
        ChatType.GROUP,
        ChatType.SUPERGROUP
    ):

        ensure_group(message)


# =========================================================
# ADMIN STATS
# =========================================================

@dp.message(Command("stats"))
async def admin_stats(
    message: Message
):

    if not ADMIN_ID:
        return

    if str(message.from_user.id) != ADMIN_ID:
        return

    with closing(connect()) as con:

        users = con.execute(
            "SELECT COUNT(*) FROM users"
        ).fetchone()[0]

        groups = con.execute(
            "SELECT COUNT(*) FROM groups"
        ).fetchone()[0]

        messages = con.execute(
            "SELECT COALESCE(SUM(messages),0) FROM users"
        ).fetchone()[0]

    await message.answer(
        f"""
📊 СТАТИСТИКА БОТА

👤 Пользователей: {users}
👥 Групп: {groups}
💬 Сообщений: {messages}
"""
    )


# =========================================================
# RUN
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