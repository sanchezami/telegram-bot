import asyncio
import logging
import os
import random
import sqlite3
import time
from contextlib import closing

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode, ChatType
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
    raise RuntimeError("BOT_TOKEN не найден")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

bot = Bot(
    TOKEN,
    default=DefaultBotProperties(
        parse_mode=ParseMode.HTML
    )
)

dp = Dispatcher()


# =========================================================
# DATABASE
# =========================================================

def db():
    return sqlite3.connect(DB, timeout=30)


def init_db():
    with closing(db()) as con:

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
            streak INTEGER DEFAULT 0,
            last_daily INTEGER DEFAULT 0,
            premium_until INTEGER DEFAULT 0,
            referrals INTEGER DEFAULT 0,
            banned INTEGER DEFAULT 0,
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
            games INTEGER DEFAULT 0,
            wins INTEGER DEFAULT 0,
            coins INTEGER DEFAULT 0,
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
# USERS
# =========================================================

def ensure_user(user):
    with closing(db()) as con:
        con.execute("""
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
            int(time.time())
        ))

        con.commit()


def get_user(user_id):
    with closing(db()) as con:
        return con.execute("""
        SELECT *
        FROM users
        WHERE id=?
        """, (user_id,)).fetchone()


def add_coins(user_id, amount):
    with closing(db()) as con:
        con.execute("""
        UPDATE users
        SET coins = coins + ?
        WHERE id=?
        """, (amount, user_id))
        con.commit()


def add_xp(user_id, amount):
    with closing(db()) as con:

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
        """, (xp, level, user_id))

        con.commit()


def premium(user_id):
    row = get_user(user_id)

    return bool(
        row and row[11] > int(time.time())
    )


def game_result(user_id, win=False, reward=0):

    if premium(user_id):
        reward = int(reward * 1.5)

    with closing(db()) as con:
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
        25 if win else 10
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

    with closing(db()) as con:

        con.execute("""
        INSERT INTO groups
        (id, title, created)
        VALUES (?, ?, ?)

        ON CONFLICT(id)
        DO UPDATE SET title=excluded.title
        """, (
            message.chat.id,
            message.chat.title or "Группа",
            int(time.time())
        ))

        con.execute("""
        INSERT OR IGNORE INTO group_users
        (group_id, user_id)
        VALUES (?, ?)
        """, (
            message.chat.id,
            message.from_user.id
        ))

        con.commit()


def group_members(chat_id):

    with closing(db()) as con:

        return con.execute("""
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
        """, (chat_id,)).fetchall()


def group_game(chat_id, user_id, win=False, reward=0):

    with closing(db()) as con:

        con.execute("""
        INSERT OR IGNORE INTO group_users
        (group_id, user_id)
        VALUES (?, ?)
        """, (
            chat_id,
            user_id
        ))

        con.execute("""
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

        con.commit()

    game_result(
        user_id,
        win,
        reward
    )


# =========================================================
# KEYBOARDS
# =========================================================

def home_keyboard():

    b = InlineKeyboardBuilder()

    b.button(
        text="🎮 Игры",
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
        text="🎁 Daily",
        callback_data="daily"
    )

    b.button(
        text="🎭 Мафия",
        callback_data="mafia_info"
    )

    b.button(
        text="⭐ Premium",
        callback_data="premium"
    )

    b.button(
        text="👥 Добавить в группу",
        callback_data="add_group"
    )

    b.adjust(2, 2, 2, 1, 1)

    return b.as_markup()


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


# =========================================================
# START
# =========================================================

@dp.message(CommandStart())
async def start(
    message: Message,
    command: CommandObject
):

    ensure_user(message.from_user)

    if message.chat.type != ChatType.PRIVATE:
        return

    await message.answer(
        """
🎲 RANDOM PARTY

Социальный бот для Telegram-групп.

🎮 Игры
🎭 Мафия
💰 Экономика
📈 Уровни
🏆 Рейтинги
🎁 Daily
⭐ Premium

Добавляй меня в группу и играйте вместе.
""",
        reply_markup=home_keyboard()
    )


# =========================================================
# BOT ADDED TO GROUP
# =========================================================

@dp.my_chat_member()
async def bot_added(event):

    if event.chat.type not in (
        ChatType.GROUP,
        ChatType.SUPERGROUP
    ):
        return

    old = event.old_chat_member.status
    new = event.new_chat_member.status

    if new not in ("member", "administrator"):
        return

    if old in ("member", "administrator"):
        return

    chat_id = event.chat.id
    title = event.chat.title or "группа"

    with closing(db()) as con:
        con.execute("""
        INSERT OR REPLACE INTO groups
        (id, title, created)
        VALUES (?, ?, ?)
        """, (
            chat_id,
            title,
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
                    text="🎮 Игры",
                    callback_data="group_help"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🎭 Мафия",
                    callback_data="group_mafia"
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
        chat_id,
        f"""
🎉 RANDOM PARTY подключён!

Добро пожаловать в «{title}».

Теперь здесь доступны:

🎮 Игры
🎭 Мафия
⚔️ Дуэли
🎲 Кубик
🎰 Слоты
🎯 Случайный игрок
🏆 Рейтинг группы
🎉 События
💰 Экономика

Напиши:

/party

чтобы открыть меню группы.

А чтобы начать Мафию:

/mafia
""",
        reply_markup=keyboard
    )


# =========================================================
# GROUP HELP
# =========================================================

@dp.callback_query(F.data == "group_help")
async def group_help(call: CallbackQuery):

    await call.answer()

    await call.message.answer(
        """
🎮 ИГРЫ В ГРУППЕ

/dice — кубик
/coin — монетка
/slot — слот
/duel — дуэль
/random — случайный игрок
/top — рейтинг
/event — событие

🎭 Мафия:

/mafia — создать игру
/join — присоединиться
/startmafia — начать
/mafia_status — статус игры
"""
    )


@dp.callback_query(F.data == "group_mafia")
async def group_mafia_button(
    call: CallbackQuery
):

    await call.answer()

    await call.message.answer(
        """
🎭 МАФИЯ

Создай игру:

/mafia

После этого игроки пишут:

/join

Когда собралось минимум 5 человек:

/startmafia
"""
    )


# =========================================================
# GROUP PARTY
# =========================================================

@dp.message(Command("party"))
async def party(message: Message):

    if message.chat.type not in (
        ChatType.GROUP,
        ChatType.SUPERGROUP
    ):
        return

    ensure_user(message.from_user)
    ensure_group(message)

    await message.answer(
        """
🎲 RANDOM PARTY

🎮 Игры:
/games

🎭 Мафия:
/mafia

⚔️ Дуэль:
/duel

🎯 Случайный игрок:
/random

🎲 Кубик:
/dice

🎰 Слот:
/slot

🏆 Рейтинг:
/top

🎉 Событие:
/event
"""
    )


# =========================================================
# BASIC GROUP GAMES
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
    reward = value * 15

    group_game(
        message.chat.id,
        message.from_user.id,
        reward=reward
    )

    await message.answer(
        f"""
🎲 {message.from_user.first_name}

Выпало: {value}

🪙 +{reward}
"""
    )


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
        "🦅 ОРЁЛ",
        "🪙 РЕШКА"
    ])

    await message.answer(
        f"🪙 {result}"
    )


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

    elif a == b or b == c or a == c:
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
        win,
        reward
    )

    await message.answer(
        f"""
🎰 {a} {b} {c}

{result}

🪙 +{reward}
"""
    )


@dp.message(Command("random"))
async def random_player(message: Message):

    if message.chat.type not in (
        ChatType.GROUP,
        ChatType.SUPERGROUP
    ):
        return

    ensure_user(message.from_user)
    ensure_group(message)

    players = group_members(
        message.chat.id
    )

    if not players:
        await message.answer(
            "👥 Пока нет игроков."
        )
        return

    player = random.choice(players)

    name = (
        player[1]
        or player[2]
        or "Игрок"
    )

    await message.answer(
        f"""
🎯 СЛУЧАЙНЫЙ ИГРОК

🔥 {name}
"""
    )


@dp.message(Command("duel"))
async def duel(message: Message):

    if message.chat.type not in (
        ChatType.GROUP,
        ChatType.SUPERGROUP
    ):
        return

    ensure_user(message.from_user)
    ensure_group(message)

    players = group_members(
        message.chat.id
    )

    if len(players) < 2:
        await message.answer(
            "⚔️ Нужно минимум 2 игрока."
        )
        return

    a, b = random.sample(
        players,
        2
    )

    winner = random.choice([
        a,
        b
    ])

    winner_name = (
        winner[1]
        or winner[2]
        or "Игрок"
    )

    group_game(
        message.chat.id,
        winner[0],
        True,
        300
    )

    await message.answer(
        f"""
⚔️ ДУЭЛЬ

🥊 {a[1]} VS {b[1]}

🏆 Победитель:

{winner_name}

🪙 +300
"""
    )


# =========================================================
# GROUP TOP
# =========================================================

@dp.message(Command("top"))
async def top(message: Message):

    if message.chat.type not in (
        ChatType.GROUP,
        ChatType.SUPERGROUP
    ):
        return

    ensure_group(message)

    players = group_members(
        message.chat.id
    )

    players.sort(
        key=lambda x: (
            x[4],
            x[5]
        ),
        reverse=True
    )

    text = "🏆 ТОП ГРУППЫ\n\n"

    for i, p in enumerate(
        players[:10],
        1
    ):

        name = (
            p[1]
            or p[2]
            or "Игрок"
        )

        text += (
            f"{i}. {name} — "
            f"🏆 {p[4]} побед | "
            f"🪙 {p[5]}\n"
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

    players = group_members(
        message.chat.id
    )

    if len(players) < 2:
        await message.answer(
            "🎉 Для события нужно минимум 2 игрока."
        )
        return

    winner = random.choice(players)

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
        True,
        reward
    )

    await message.answer(
        f"""
🎉 СЛУЧАЙНОЕ СОБЫТИЕ

🔥 Все участники группы участвуют.

👑 Победитель:

{winner_name}

🪙 +{reward}

Следующее событие:
/event
"""
    )


# =========================================================
# ======================= MAFIA ===========================
# =========================================================

MAFIA = {}


def mafia_state(chat_id):

    if chat_id not in MAFIA:

        MAFIA[chat_id] = {
            "players": {},
            "active": False,
            "phase": "lobby",
            "night": 0,
            "votes": {},
            "killed": None
        }

    return MAFIA[chat_id]


def mafia_reset(chat_id):
    MAFIA[chat_id] = {
        "players": {},
        "active": False,
        "phase": "lobby",
        "night": 0,
        "votes": {},
        "killed": None
    }


@dp.message(Command("mafia"))
async def mafia_create(message: Message):

    if message.chat.type not in (
        ChatType.GROUP,
        ChatType.SUPERGROUP
    ):
        return

    ensure_user(message.from_user)
    ensure_group(message)

    state = mafia_state(
        message.chat.id
    )

    if state["active"]:
        await message.answer(
            "🎭 В этой группе уже идёт Мафия."
        )
        return

    if state["players"]:
        await message.answer(
            f"""
🎭 МАФИЯ УЖЕ СОБИРАЕТСЯ

Игроков:
{len(state["players"])}

Присоединиться:
/join

Начать:
/startmafia
"""
        )
        return

    state["players"][
        message.from_user.id
    ] = {
        "name": message.from_user.first_name,
        "alive": True,
        "role": None
    }

    await message.answer(
        """
🎭 МАФИЯ

Игра создана!

👥 Минимум: 5 игроков
👥 Оптимально: 7–12

Чтобы войти:

/join

Когда все собрались:

/startmafia
"""
    )


@dp.message(Command("join"))
async def mafia_join(message: Message):

    if message.chat.type not in (
        ChatType.GROUP,
        ChatType.SUPERGROUP
    ):
        return

    ensure_user(message.from_user)
    ensure_group(message)

    state = mafia_state(
        message.chat.id
    )

    if state["active"]:

        await message.answer(
            "🎭 Игра уже началась."
        )

        return

    if not state["players"]:

        await message.answer(
            "Сначала создай игру: /mafia"
        )

        return

    user_id = message.from_user.id

    if user_id in state["players"]:

        await message.answer(
            "Ты уже в игре."
        )

        return

    if len(state["players"]) >= 20:

        await message.answer(
            "🎭 Лобби заполнено. Максимум 20 игроков."
        )

        return

    state["players"][user_id] = {
        "name": message.from_user.first_name,
        "alive": True,
        "role": None
    }

    await message.answer(
        f"""
🎭 {message.from_user.first_name} присоединился!

👥 Игроков:
{len(state["players"])}

Минимум для старта: 5
"""
    )


@dp.message(Command("startmafia"))
async def mafia_start(message: Message):

    if message.chat.type not in (
        ChatType.GROUP,
        ChatType.SUPERGROUP
    ):
        return

    state = mafia_state(
        message.chat.id
    )

    if state["active"]:

        await message.answer(
            "🎭 Мафия уже идёт."
        )

        return

    players = list(
        state["players"].keys()
    )

    if len(players) < 5:

        await message.answer(
            f"""
🎭 Недостаточно игроков.

Сейчас: {len(players)}
Нужно: минимум 5

Приглашайте людей и пишите:
/join
"""
        )

        return

    # распределяем роли
    count = len(players)

    mafia_count = max(
        1,
        count // 4
    )

    roles = (
        ["🔪 Мафия"] * mafia_count
        + ["🕵️ Комиссар"]
        + ["❤️ Доктор"]
        + ["👤 Мирный"] * (
            count
            - mafia_count
            - 2
        )
    )

    random.shuffle(roles)

    for user_id, role in zip(
        players,
        roles
    ):

        state["players"][user_id]["role"] = role

        try:

            await bot.send_message(
                user_id,
                f"""
🎭 ТВОЯ РОЛЬ

{role}

Игра проходит в группе:
{message.chat.title}

Следи за событиями и не раскрывай свою роль.
"""
            )

        except Exception:

            pass

    state["active"] = True
    state["phase"] = "night"
    state["night"] = 1

    await message.answer(
        f"""
🎭 МАФИЯ НАЧАЛАСЬ!

👥 Игроков: {count}

🌙 НОЧЬ 1

Мирные жители засыпают...

🔪 Мафия выбирает жертву.
🕵️ Комиссар проверяет игрока.
❤️ Доктор спасает игрока.

Роли отправлены игрокам в личные сообщения.

Когда будете готовы к дневной фазе:
 /day
"""
    )


@dp.message(Command("mafia_status"))
async def mafia_status(message: Message):

    if message.chat.type not in (
        ChatType.GROUP,
        ChatType.SUPERGROUP
    ):
        return

    state = mafia_state(
        message.chat.id
    )

    if not state["players"]:

        await message.answer(
            "🎭 Сейчас Мафии нет."
        )

        return

    alive = sum(
        1
        for p in state["players"].values()
        if p["alive"]
    )

    await message.answer(
        f"""
🎭 СТАТУС МАФИИ

👥 Всего игроков:
{len(state["players"])}

❤️ Живых:
{alive}

🌙 Ночь:
{state["night"]}

📍 Фаза:
{state["phase"]}
"""
    )


@dp.message(Command("day"))
async def mafia_day(message: Message):

    if message.chat.type not in (
        ChatType.GROUP,
        ChatType.SUPERGROUP
    ):
        return

    state = mafia_state(
        message.chat.id
    )

    if not state["active"]:

        await message.answer(
            "🎭 Активной игры нет."
        )

        return

    state["phase"] = "day"

    alive_players = [
        p["name"]
        for p in state["players"].values()
        if p["alive"]
    ]

    text = "☀️ ДЕНЬ\n\n"
    text += "Живые игроки:\n\n"

    for i, name in enumerate(
        alive_players,
        1
    ):
        text += f"{i}. {name}\n"

    text += """
    
Обсуждайте подозреваемых.

Для голосования используйте:

/vote ИМЯ

Например:

/vote Алекс
"""

    await message.answer(text)


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

    state = mafia_state(
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
            "Ты не можешь голосовать."
        )

        return

    target_name = (
        command.args
        if command
        else None
    )

    if not target_name:

        await message.answer(
            "Используй: /vote ИМЯ"
        )

        return

    target = None

    for uid, player in state["players"].items():

        if (
            player["alive"]
            and
            player["name"].lower()
            == target_name.lower()
        ):
            target = uid
            break

    if target is None:

        await message.answer(
            "❌ Игрок не найден."
        )

        return

    state["votes"][
        message.from_user.id
    ] = target

    alive_count = sum(
        1
        for p in state["players"].values()
        if p["alive"]
    )

    await message.answer(
        f"""
🗳 {message.from_user.first_name}
проголосовал.

Голосов:
{len(state["votes"])}/{alive_count}
"""
    )

    if len(state["votes"]) >= alive_count:

        counts = {}

        for target_id in state["votes"].values():

            counts[target_id] = (
                counts.get(target_id, 0) + 1
            )

        eliminated = max(
            counts,
            key=counts.get
        )

        player = state["players"][eliminated]

        player["alive"] = False

        role = player["role"]

        state["votes"] = {}
        state["phase"] = "night"
        state["night"] += 1

        await message.answer(
            f"""
⚖️ ГОЛОСОВАНИЕ ОКОНЧЕНО

🚪 Выбывает:

{player["name"]}

🎭 Его роль:

{role}

🌙 Наступает ночь {state["night"]}.
"""
        )

        check_mafia_end(
            message.chat.id
        )


def check_mafia_end(chat_id):

    state = mafia_state(chat_id)

    if not state["active"]:
        return

    alive = [
        p
        for p in state["players"].values()
        if p["alive"]
    ]

    mafia = [
        p
        for p in alive
        if p["role"] == "🔪 Мафия"
    ]

    citizens = [
        p
        for p in alive
        if p["role"] != "🔪 Мафия"
    ]

    if not mafia:

        state["active"] = False

        return

    if len(mafia) >= len(citizens):

        state["active"] = False


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

    name = row[2]
    coins = row[3]
    xp = row[4]
    level = row[5]
    games = row[6]
    wins = row[7]
    losses = row[8]

    winrate = (
        round(wins / games * 100, 1)
        if games
        else 0
    )

    await call.message.edit_text(
        f"""
👤 ПРОФИЛЬ

{name}

🏅 Уровень: {level}
⚡ XP: {xp}/{level * 100}

💰 Монеты: {coins}

🎮 Игр: {games}
🏆 Побед: {wins}
💀 Поражений: {losses}

📊 Винрейт: {winrate}%

⭐ Premium:
{"Да" if premium(call.from_user.id) else "Нет"}
""",
        reply_markup=back_keyboard()
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
💰 ЭКОНОМИКА

Твой баланс:

🪙 {coins}

Зарабатывать можно через:

🎮 игры
🎁 Daily
🎭 Мафию
🏆 победы
👥 рефералов
🎉 события
""",
        reply_markup=back_keyboard()
    )


# =========================================================
# DAILY
# =========================================================

@dp.callback_query(F.data == "daily")
async def daily(call: CallbackQuery):

    await call.answer()

    user_id = call.from_user.id

    row = get_user(user_id)

    now = int(time.time())

    if now - row[10] < 86400:

        left = 86400 - (
            now - row[10]
        )

        hours = left // 3600
        minutes = (left % 3600) // 60

        await call.message.edit_text(
            f"""
🎁 DAILY

Ты уже получил награду.

⏳ {hours}ч {minutes}мин
""",
            reply_markup=back_keyboard()
        )

        return

    reward = 200

    if premium(user_id):
        reward *= 2

    add_coins(
        user_id,
        reward
    )

    add_xp(
        user_id,
        30
    )

    with closing(db()) as con:

        con.execute("""
        UPDATE users
        SET
            last_daily=?,
            streak=streak+1
        WHERE id=?
        """, (
            now,
            user_id
        ))

        con.commit()

    await call.message.edit_text(
        f"""
🎁 DAILY ПОЛУЧЕН!

🪙 +{reward}

🔥 Заходи завтра снова.
""",
        reply_markup=back_keyboard()
    )


# =========================================================
# GAMES MENU
# =========================================================

@dp.callback_query(F.data == "games")
async def games(call: CallbackQuery):

    await call.answer()

    await call.message.edit_text(
        """
🎮 ИГРЫ

В группе доступны:

🎲 /dice
🪙 /coin
🎰 /slot
⚔️ /duel
🎯 /random
🏆 /top
🎉 /event

🎭 Большая игра:

/mafia
""",
        reply_markup=back_keyboard()
    )


# =========================================================
# MAFIA INFO
# =========================================================

@dp.callback_query(F.data == "mafia_info")
async def mafia_info(call: CallbackQuery):

    await call.answer()

    await call.message.edit_text(
        """
🎭 МАФИЯ

Большая групповая игра.

Минимум:
👥 5 игроков

Роли:

🔪 Мафия
🕵️ Комиссар
❤️ Доктор
👤 Мирные

Как начать в группе:

/mafia

Игроки:

/join

Старт:

/startmafia

Статус:

/mafia_status
""",
        reply_markup=back_keyboard()
    )


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

    keyboard = InlineKeyboardMarkup(
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
👥 ДОБАВИТЬ RANDOM PARTY

Добавь бота в группу и запускай:

🎮 игры
🎭 Мафию
⚔️ дуэли
🏆 рейтинги
🎉 события

Бот сам отправит приветственное сообщение после добавления.
""",
        reply_markup=keyboard
    )


# =========================================================
# PREMIUM
# =========================================================

@dp.callback_query(F.data == "premium")
async def premium_menu(call: CallbackQuery):

    await call.answer()

    await call.message.edit_text(
        f"""
⭐ PREMIUM

Стоимость:
{PREMIUM_STARS} ⭐ / 30 дней

Premium даёт:

⚡ +50% игровые награды
🎁 x2 Daily
💎 Premium игры
🎁 усиленные сундуки
📈 ускоренную прокачку
👑 Premium статус
🎭 специальные функции

Покупка происходит через Telegram Stars.
""",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=f"⭐ Купить за {PREMIUM_STARS}",
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
async def buy_premium(call: CallbackQuery):

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
async def pre_checkout(
    query: PreCheckoutQuery
):

    await query.answer(
        ok=True
    )


@dp.message(F.successful_payment)
async def successful_payment(
    message: Message
):

    payment = message.successful_payment

    if not payment.invoice_payload.startswith(
        "premium:"
    ):
        return

    user_id = message.from_user.id

    now = int(time.time())

    with closing(db()) as con:

        current = con.execute("""
        SELECT premium_until
        FROM users
        WHERE id=?
        """, (
            user_id,
        )).fetchone()

        current_until = (
            current[0]
            if current
            else 0
        )

        start = max(
            now,
            current_until
        )

        until = (
            start
            + PREMIUM_DAYS * 86400
        )

        con.execute("""
        UPDATE users
        SET premium_until=?
        WHERE id=?
        """, (
            until,
            user_id
        ))

        con.execute("""
        INSERT INTO payments
        (user_id, stars, payload, charge_id, created)
        VALUES (?, ?, ?, ?, ?)
        """, (
            user_id,
            payment.total_amount,
            payment.invoice_payload,
            payment.telegram_payment_charge_id,
            now
        ))

        con.commit()

    await message.answer(
        """
🎉 PREMIUM АКТИВИРОВАН!

⭐ 30 дней

Теперь тебе доступны
повышенные награды и Premium-функции.
""",
        reply_markup=home_keyboard()
    )


# =========================================================
# HELP
# =========================================================

@dp.callback_query(F.data == "home")
async def home(call: CallbackQuery):

    await call.answer()

    await call.message.edit_text(
        """
🎲 RANDOM PARTY

Главное меню.
""",
        reply_markup=home_keyboard()
    )


# =========================================================
# ADMIN
# =========================================================

@dp.message(Command("id"))
async def get_id(message: Message):

    await message.answer(
        f"🆔 Твой ID: {message.from_user.id}"
    )


@dp.message(Command("stats"))
async def stats(message: Message):

    if message.from_user.id != ADMIN_ID:
        return

    with closing(db()) as con:

        users = con.execute(
            "SELECT COUNT(*) FROM users"
        ).fetchone()[0]

        groups = con.execute(
            "SELECT COUNT(*) FROM groups"
        ).fetchone()[0]

        payments = con.execute(
            "SELECT COUNT(*) FROM payments"
        ).fetchone()[0]

        stars = con.execute(
            "SELECT COALESCE(SUM(stars),0) FROM payments"
        ).fetchone()[0]

    await message.answer(
        f"""
📊 СТАТИСТИКА

👤 Пользователей: {users}
👥 Групп: {groups}

💳 Покупок: {payments}
⭐ Stars: {stars}
"""
    )


# =========================================================
# RUN
# =========================================================

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
    asyncio.run(main())