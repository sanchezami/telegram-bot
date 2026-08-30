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
    Message,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LabeledPrice,
    PreCheckoutQuery,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder


# ============================================================
# CONFIG
# ============================================================

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0") or 0)
DB_PATH = os.getenv("DB_PATH", "randomparty.db")

PREMIUM_PRICE = 59
PREMIUM_DAYS = 30

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN не найден в Railway Variables")


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

        con.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT DEFAULT '',
            first_name TEXT DEFAULT '',
            joined_at INTEGER,
            last_seen INTEGER,
            coins INTEGER DEFAULT 0,
            games INTEGER DEFAULT 0,
            wins INTEGER DEFAULT 0,
            losses INTEGER DEFAULT 0,
            referrals INTEGER DEFAULT 0,
            premium_until INTEGER DEFAULT 0,
            daily_claim INTEGER DEFAULT 0,
            streak INTEGER DEFAULT 0,
            streak_protect INTEGER DEFAULT 0,
            level INTEGER DEFAULT 1,
            xp INTEGER DEFAULT 0,
            banned INTEGER DEFAULT 0
        )
        """)

        con.execute("""
        CREATE TABLE IF NOT EXISTS referrals (
            invited_id INTEGER PRIMARY KEY,
            inviter_id INTEGER,
            created_at INTEGER
        )
        """)

        con.execute("""
        CREATE TABLE IF NOT EXISTS payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            stars INTEGER,
            payload TEXT,
            charge_id TEXT,
            created_at INTEGER
        )
        """)

        con.execute("""
        CREATE TABLE IF NOT EXISTS group_members (
            chat_id INTEGER,
            user_id INTEGER,
            username TEXT DEFAULT '',
            first_name TEXT DEFAULT '',
            joined_at INTEGER,
            PRIMARY KEY(chat_id,user_id)
        )
        """)

        con.execute("""
        CREATE TABLE IF NOT EXISTS group_stats (
            chat_id INTEGER,
            user_id INTEGER,
            games INTEGER DEFAULT 0,
            wins INTEGER DEFAULT 0,
            coins INTEGER DEFAULT 0,
            PRIMARY KEY(chat_id,user_id)
        )
        """)

        con.execute("""
        CREATE TABLE IF NOT EXISTS groups (
            chat_id INTEGER PRIMARY KEY,
            title TEXT DEFAULT '',
            level INTEGER DEFAULT 1,
            xp INTEGER DEFAULT 0,
            events INTEGER DEFAULT 0,
            premium_until INTEGER DEFAULT 0
        )
        """)

        con.execute("""
        CREATE TABLE IF NOT EXISTS quests (
            user_id INTEGER,
            quest_date TEXT,
            games INTEGER DEFAULT 0,
            wins INTEGER DEFAULT 0,
            coins INTEGER DEFAULT 0,
            claimed INTEGER DEFAULT 0,
            PRIMARY KEY(user_id,quest_date)
        )
        """)

        con.commit()


# ============================================================
# USER SYSTEM
# ============================================================

def register(user):

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
        VALUES(?,?,?,?,?)

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


def is_banned(user_id):

    with closing(db()) as con:

        row = con.execute(
            "SELECT banned FROM users WHERE user_id=?",
            (user_id,)
        ).fetchone()

    return bool(row and row[0])


def is_premium(user_id):

    with closing(db()) as con:

        row = con.execute(
            "SELECT premium_until FROM users WHERE user_id=?",
            (user_id,)
        ).fetchone()

    return bool(row and row[0] > int(time.time()))


def get_user(user_id):

    with closing(db()) as con:

        return con.execute("""
        SELECT
            coins,
            games,
            wins,
            losses,
            referrals,
            premium_until,
            daily_claim,
            streak,
            streak_protect,
            level,
            xp
        FROM users
        WHERE user_id=?
        """, (user_id,)).fetchone()


def add_coins(user_id, amount):

    with closing(db()) as con:

        con.execute("""
        UPDATE users
        SET coins=coins+?
        WHERE user_id=?
        """, (
            amount,
            user_id
        ))

        con.commit()


def add_xp(user_id, amount):

    with closing(db()) as con:

        row = con.execute(
            "SELECT xp,level FROM users WHERE user_id=?",
            (user_id,)
        ).fetchone()

        if not row:
            return

        xp, level = row

        xp += amount

        needed = level * 100

        while xp >= needed:

            xp -= needed
            level += 1
            needed = level * 100

        con.execute("""
        UPDATE users
        SET xp=?, level=?
        WHERE user_id=?
        """, (
            xp,
            level,
            user_id
        ))

        con.commit()


def record_game(user_id, win=False, reward=0):

    if is_premium(user_id):

        reward = int(reward * 1.5)

    with closing(db()) as con:

        con.execute("""
        UPDATE users
        SET
            games=games+1,
            wins=wins+?,
            losses=losses+?,
            coins=coins+?
        WHERE user_id=?
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


# ============================================================
# GROUP SYSTEM
# ============================================================

def register_group(message):

    if message.chat.type not in (
        ChatType.GROUP,
        ChatType.SUPERGROUP
    ):
        return

    now = int(time.time())

    with closing(db()) as con:

        con.execute("""
        INSERT INTO groups(
            chat_id,
            title
        )
        VALUES(?,?)

        ON CONFLICT(chat_id)
        DO UPDATE SET
            title=excluded.title
        """, (
            message.chat.id,
            message.chat.title or "Group"
        ))

        con.execute("""
        INSERT OR IGNORE INTO group_members(
            chat_id,
            user_id,
            username,
            first_name,
            joined_at
        )
        VALUES(?,?,?,?,?)
        """, (
            message.chat.id,
            message.from_user.id,
            message.from_user.username or "",
            message.from_user.first_name or "",
            now
        ))

        con.execute("""
        INSERT OR IGNORE INTO group_stats(
            chat_id,
            user_id
        )
        VALUES(?,?)
        """, (
            message.chat.id,
            message.from_user.id
        ))

        con.commit()


def add_group_member(chat_id, user):

    now = int(time.time())

    with closing(db()) as con:

        con.execute("""
        INSERT INTO group_members(
            chat_id,
            user_id,
            username,
            first_name,
            joined_at
        )
        VALUES(?,?,?,?,?)

        ON CONFLICT(chat_id,user_id)
        DO UPDATE SET
            username=excluded.username,
            first_name=excluded.first_name
        """, (
            chat_id,
            user.id,
            user.username or "",
            user.first_name or "",
            now
        ))

        con.execute("""
        INSERT OR IGNORE INTO group_stats(
            chat_id,
            user_id
        )
        VALUES(?,?)
        """, (
            chat_id,
            user.id
        ))

        con.commit()


def group_players(chat_id):

    with closing(db()) as con:

        return con.execute("""
        SELECT
            user_id,
            first_name,
            username
        FROM group_members
        WHERE chat_id=?
        """, (
            chat_id,
        )).fetchall()


def group_reward(chat_id, user_id, win=False, coins=0):

    with closing(db()) as con:

        con.execute("""
        INSERT OR IGNORE INTO group_stats(
            chat_id,
            user_id
        )
        VALUES(?,?)
        """, (
            chat_id,
            user_id
        ))

        con.execute("""
        UPDATE group_stats
        SET
            games=games+1,
            wins=wins+?,
            coins=coins+?
        WHERE chat_id=? AND user_id=?
        """, (
            1 if win else 0,
            coins,
            chat_id,
            user_id
        ))

        con.execute("""
        UPDATE groups
        SET xp=xp+?
        WHERE chat_id=?
        """, (
            20,
            chat_id
        ))

        con.commit()


# ============================================================
# PREMIUM
# ============================================================

def activate_premium(user_id, days):

    now = int(time.time())

    with closing(db()) as con:

        row = con.execute(
            "SELECT premium_until FROM users WHERE user_id=?",
            (user_id,)
        ).fetchone()

        current = row[0] if row else 0

        start = max(now, current)

        until = start + days * 86400

        con.execute("""
        UPDATE users
        SET premium_until=?
        WHERE user_id=?
        """, (
            until,
            user_id
        ))

        con.commit()

    return until


# ============================================================
# MAIN KEYBOARD
# ============================================================

def main_keyboard():

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
        text="🏆 Рейтинг",
        callback_data="rating"
    )

    b.button(
        text="🎁 Бонус",
        callback_data="daily"
    )

    b.button(
        text="🎯 Задания",
        callback_data="quests"
    )

    b.button(
        text="👥 Пригласить",
        callback_data="ref"
    )

    b.button(
        text="⭐ Premium",
        callback_data="premium"
    )

    b.button(
        text="➕ В группу",
        callback_data="add_group"
    )

    b.button(
        text="ℹ️ Помощь",
        callback_data="help"
    )

    b.adjust(2, 2, 2, 2, 1)

    return b.as_markup()


def games_keyboard():

    b = InlineKeyboardBuilder()

    games = [
        ("🪙 Монетка", "coin"),
        ("🎲 Кубик", "dice"),
        ("🎰 Слот", "slot"),
        ("🎯 Дартс", "dart"),
        ("✊ КНБ", "rps"),
        ("🔢 Число", "number"),
        ("🧠 Викторина", "quiz"),
        ("⚡ Множитель", "multiplier"),
        ("🎁 Сундук", "chest"),
        ("💎 Premium игра", "premium_game"),
    ]

    for text, callback in games:

        b.button(
            text=text,
            callback_data=f"game_{callback}"
        )

    b.button(
        text="⬅️ Назад",
        callback_data="home"
    )

    b.adjust(2, 2, 2, 2, 2, 1)

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


# ============================================================
# START
# ============================================================

@dp.message(CommandStart())
async def start(
    message: Message,
    command: CommandObject
):

    if message.chat.type != ChatType.PRIVATE:
        return

    user = message.from_user

    register(user)

    if is_banned(user.id):

        await message.answer(
            "🚫 Доступ ограничен."
        )

        return

    if command.args:

        if command.args.startswith("ref_"):

            raw = command.args[4:]

            if raw.isdigit():

                inviter = int(raw)

                if inviter != user.id:

                    with closing(db()) as con:

                        exists = con.execute(
                            "SELECT 1 FROM referrals WHERE invited_id=?",
                            (user.id,)
                        ).fetchone()

                        inviter_exists = con.execute(
                            "SELECT 1 FROM users WHERE user_id=?",
                            (inviter,)
                        ).fetchone()

                        if not exists and inviter_exists:

                            con.execute("""
                            INSERT INTO referrals(
                                invited_id,
                                inviter_id,
                                created_at
                            )
                            VALUES(?,?,?)
                            """, (
                                user.id,
                                inviter,
                                int(time.time())
                            ))

                            con.execute("""
                            UPDATE users
                            SET referrals=referrals+1
                            WHERE user_id=?
                            """, (
                                inviter,
                            ))

                            con.commit()

                            activate_premium(
                                inviter,
                                1
                            )

                            try:

                                await bot.send_message(
                                    inviter,
                                    "🎉 По твоей ссылке пришёл новый игрок!\n"
                                    "⭐ +1 день Premium"
                                )

                            except Exception:
                                pass

    await message.answer(
        """
<b>🎲 RANDOM PARTY</b>

Твоя Telegram-площадка для игр.

🎮 Играй
⚔️ Соревнуйся
🏆 Поднимайся в рейтинге
👥 Зови друзей
🏟️ Прокачивай группы
⭐ Открывай Premium

Добавляй бота в группы и устраивайте свои мини-турниры.
""",
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

🔥 Игры
🏆 Рейтинги
🎁 Награды
👥 Группы
⭐ Premium

Выбирай 👇
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
<b>ℹ️ КОМАНДЫ</b>

<b>ЛС:</b>

/start
/id

<b>Группа:</b>

/party
/join
/random
/duel
/coin
/dice
/slot
/quiz
/top
/event

<b>Админ:</b>

/stats
/ban ID
/unban ID

Добавляй бота в группу и используй /party.
""",
        reply_markup=back_keyboard()
    )


# ============================================================
# ADD TO GROUP
# ============================================================

@dp.callback_query(F.data == "add_group")
async def add_group(call: CallbackQuery):

    await call.answer()

    me = await bot.get_me()

    url = f"https://t.me/{me.username}?startgroup=true"

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
<b>👥 RANDOM PARTY В ГРУППЕ</b>

Добавь меня в группу.

Участники смогут:

⚔️ устраивать дуэли
🎰 играть
🎯 выбирать случайного игрока
🏆 соревноваться за первое место
🏟️ прокачивать уровень группы
🎉 запускать события

Чем больше людей в группе — тем интереснее.
""",
        reply_markup=kb
    )


# ============================================================
# PROFILE
# ============================================================

@dp.callback_query(F.data == "profile")
async def profile(call: CallbackQuery):

    await call.answer()

    data = get_user(call.from_user.id)

    if not data:
        return

    (
        coins,
        games,
        wins,
        losses,
        referrals,
        premium_until,
        daily,
        streak,
        protect,
        level,
        xp
    ) = data

    premium = (
        "⭐ PREMIUM"
        if premium_until > int(time.time())
        else "⚪ FREE"
    )

    await call.message.edit_text(
        f"""
<b>👤 ТВОЙ ПРОФИЛЬ</b>

{premium}

🏅 Уровень: <b>{level}</b>
⚡ XP: <b>{xp}/{level * 100}</b>

🪙 Монеты: <b>{coins}</b>

🎮 Игр: <b>{games}</b>
🏆 Побед: <b>{wins}</b>
💀 Поражений: <b>{losses}</b>

🔥 Streak: <b>{streak}</b>
🛡️ Защита streak: <b>{protect}</b>

👥 Рефералов: <b>{referrals}</b>
""",
        reply_markup=back_keyboard()
    )


# ============================================================
# GLOBAL RATING
# ============================================================

@dp.callback_query(F.data == "rating")
async def rating(call: CallbackQuery):

    await call.answer()

    with closing(db()) as con:

        rows = con.execute("""
        SELECT
            first_name,
            username,
            wins,
            coins,
            level
        FROM users
        WHERE banned=0
        ORDER BY wins DESC, coins DESC
        LIMIT 10
        """).fetchall()

    text = "<b>🏆 ГЛОБАЛЬНЫЙ ТОП</b>\n\n"

    medals = ["🥇", "🥈", "🥉"]

    for i, row in enumerate(rows, 1):

        first, username, wins, coins, level = row

        name = first or username or "Игрок"

        icon = medals[i - 1] if i <= 3 else f"{i}."

        text += (
            f"{icon} <b>{name}</b>\n"
            f"   🏆 {wins} | 🪙 {coins} | LVL {level}\n"
        )

    await call.message.edit_text(
        text,
        reply_markup=back_keyboard()
    )


# ============================================================
# DAILY
# ============================================================

@dp.callback_query(F.data == "daily")
async def daily(call: CallbackQuery):

    await call.answer()

    user_id = call.from_user.id

    data = get_user(user_id)

    if not data:
        return

    last_claim = data[6]
    streak = data[7]

    now = int(time.time())

    if now - last_claim < 86400:

        remaining = 86400 - (now - last_claim)

        hours = remaining // 3600
        minutes = (remaining % 3600) // 60

        await call.message.edit_text(
            f"""
<b>🎁 DAILY</b>

Ты уже получил награду.

⏳ Через:
<b>{hours}ч {minutes}мин</b>

🔥 Streak: {streak}
""",
            reply_markup=back_keyboard()
        )

        return

    reward = 75 + min(streak * 15, 300)

    if is_premium(user_id):

        reward *= 2

    with closing(db()) as con:

        con.execute("""
        UPDATE users
        SET
            coins=coins+?,
            daily_claim=?,
            streak=streak+1
        WHERE user_id=?
        """, (
            reward,
            now,
            user_id
        ))

        con.commit()

    add_xp(
        user_id,
        20
    )

    await call.message.edit_text(
        f"""
🎉 <b>DAILY ПОЛУЧЕН!</b>

🪙 +<b>{reward}</b>

🔥 Streak: <b>{streak + 1}</b>

Завтра награда будет ещё больше.
""",
        reply_markup=back_keyboard()
    )


# ============================================================
# QUESTS
# ============================================================

def today():

    return time.strftime(
        "%Y-%m-%d"
    )


def quest_data(user_id):

    date = today()

    with closing(db()) as con:

        row = con.execute("""
        SELECT
            games,
            wins,
            coins,
            claimed
        FROM quests
        WHERE user_id=? AND quest_date=?
        """, (
            user_id,
            date
        )).fetchone()

    if row:
        return row

    with closing(db()) as con:

        con.execute("""
        INSERT INTO quests(
            user_id,
            quest_date
        )
        VALUES(?,?)
        """, (
            user_id,
            date
        ))

        con.commit()

    return 0, 0, 0, 0


@dp.callback_query(F.data == "quests")
async def quests(call: CallbackQuery):

    await call.answer()

    games, wins, coins, claimed = quest_data(
        call.from_user.id
    )

    completed = (
        games >= 5
        and wins >= 2
        and coins >= 100
    )

    status = "✅ Выполнено" if completed else "⏳ В процессе"

    await call.message.edit_text(
        f"""
<b>🎯 ДНЕВНЫЕ ЗАДАНИЯ</b>

🎮 Сыграть: <b>{games}/5</b>
🏆 Победить: <b>{wins}/2</b>
🪙 Заработать: <b>{coins}/100</b>

Статус: {status}

Награда:
🎁 <b>500 монет + XP</b>
""",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="🎁 Забрать награду",
                        callback_data="claim_quest"
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


@dp.callback_query(F.data == "claim_quest")
async def claim_quest(call: CallbackQuery):

    games, wins, coins, claimed = quest_data(
        call.from_user.id
    )

    if claimed:

        await call.answer(
            "Ты уже забрал награду.",
            show_alert=True
        )

        return

    if games < 5 or wins < 2 or coins < 100:

        await call.answer(
            "❌ Задание ещё не выполнено.",
            show_alert=True
        )

        return

    with closing(db()) as con:

        con.execute("""
        UPDATE quests
        SET claimed=1
        WHERE user_id=? AND quest_date=?
        """, (
            call.from_user.id,
            today()
        ))

        con.commit()

    add_coins(
        call.from_user.id,
        500
    )

    add_xp(
        call.from_user.id,
        100
    )

    await call.answer(
        "🎉 +500 монет и +100 XP!",
        show_alert=True
    )


# ============================================================
# REFERRALS
# ============================================================

@dp.callback_query(F.data == "ref")
async def referrals(call: CallbackQuery):

    await call.answer()

    me = await bot.get_me()

    link = (
        f"https://t.me/{me.username}"
        f"?start=ref_{call.from_user.id}"
    )

    data = get_user(call.from_user.id)

    refs = data[4] if data else 0

    await call.message.edit_text(
        f"""
<b>👥 РЕФЕРАЛЬНАЯ СИСТЕМА</b>

Приглашено:
<b>{refs}</b>

За нового игрока:

⭐ +1 день Premium

А твой друг получает стартовый бонус.

Твоя ссылка:

<code>{link}</code>
""",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="📤 Пригласить",
                        url=(
                            "https://t.me/share/url"
                            f"?url={link}"
                            "&text=🎲%20Залетай%20в%20RANDOM%20PARTY!"
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

🪙 Монетка
🎲 Кубик
🎰 Слот
🎯 Дартс
✊ КНБ
🔢 Число
🧠 Викторина
⚡ Множитель
🎁 Сундук
💎 Premium-игра
""",
        reply_markup=games_keyboard()
    )


# ============================================================
# COIN
# ============================================================

@dp.callback_query(F.data == "game_coin")
async def game_coin(call: CallbackQuery):

    result = random.choice([
        "🦅 ОРЁЛ",
        "🪙 РЕШКА"
    ])

    reward = 10

    record_game(
        call.from_user.id,
        reward=reward
    )

    await call.answer(
        f"{result}\n\n🪙 +{reward}",
        show_alert=True
    )


# ============================================================
# DICE
# ============================================================

@dp.callback_query(F.data == "game_dice")
async def game_dice(call: CallbackQuery):

    value = random.randint(1, 6)

    reward = value * 5

    record_game(
        call.from_user.id,
        reward=reward
    )

    await call.answer(
        f"🎲 Выпало: {value}\n"
        f"🪙 +{reward}",
        show_alert=True
    )


# ============================================================
# DART
# ============================================================

@dp.callback_query(F.data == "game_dart")
async def game_dart(call: CallbackQuery):

    value = random.randint(1, 60)

    reward = max(
        5,
        value // 3
    )

    record_game(
        call.from_user.id,
        reward=reward
    )

    await call.answer(
        f"🎯 {value}/60\n\n"
        f"🪙 +{reward}",
        show_alert=True
    )


# ============================================================
# NUMBER
# ============================================================

@dp.callback_query(F.data == "game_number")
async def game_number(call: CallbackQuery):

    number = random.randint(
        1,
        10000
    )

    reward = 20

    record_game(
        call.from_user.id,
        reward=reward
    )

    await call.answer(
        f"🔢 Твоё число:\n\n"
        f"<b>{number}</b>\n\n"
        f"🪙 +{reward}",
        show_alert=True
    )


# ============================================================
# SLOT
# ============================================================

@dp.callback_query(F.data == "game_slot")
async def game_slot(call: CallbackQuery):

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

        reward = 500

        record_game(
            call.from_user.id,
            win=True,
            reward=reward
        )

        result = f"""
🎉 <b>ДЖЕКПОТ!</b>

{a} {b} {c}

🪙 +{reward}
"""

    elif a == b or b == c or a == c:

        reward = 75

        record_game(
            call.from_user.id,
            win=True,
            reward=reward
        )

        result = f"""
🔥 <b>ПАРА!</b>

{a} {b} {c}

🪙 +{reward}
"""

    else:

        reward = 10

        record_game(
            call.from_user.id,
            reward=reward
        )

        result = f"""
{a} {b} {c}

Не повезло 😈

🪙 +{reward}
"""

    await call.answer(
        result,
        show_alert=True
    )


# ============================================================
# RPS
# ============================================================

@dp.callback_query(F.data == "game_rps")
async def game_rps(call: CallbackQuery):

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

        record_game(
            call.from_user.id,
            reward=reward
        )

        result = f"""
Ты: {user}
Бот: {enemy}

🤝 Ничья

🪙 +{reward}
"""

    elif (
        (user == "✊" and enemy == "✌️")
        or
        (user == "✌️" and enemy == "📄")
        or
        (user == "📄" and enemy == "✊")
    ):

        reward = 100

        record_game(
            call.from_user.id,
            win=True,
            reward=reward
        )

        result = f"""
Ты: {user}
Бот: {enemy}

🏆 ПОБЕДА!

🪙 +{reward}
"""

    else:

        record_game(
            call.from_user.id
        )

        result = f"""
Ты: {user}
Бот: {enemy}

💀 ПОРАЖЕНИЕ
"""

    await call.answer(
        result,
        show_alert=True
    )


# ============================================================
# MULTIPLIER
# ============================================================

@dp.callback_query(F.data == "game_multiplier")
async def multiplier(call: CallbackQuery):

    number = random.randint(
        1,
        100
    )

    if number >= 98:

        multiplier_value = "x10"
        reward = 500

    elif number >= 85:

        multiplier_value = "x5"
        reward = 250

    elif number >= 60:

        multiplier_value = "x2"
        reward = 100

    else:

        multiplier_value = "x1"
        reward = 20

    record_game(
        call.from_user.id,
        win=reward >= 100,
        reward=reward
    )

    await call.answer(
        f"""
⚡ МНОЖИТЕЛЬ

Выпало: {number}

<b>{multiplier_value}</b>

🪙 +{reward}
""",
        show_alert=True
    )


# ============================================================
# CHEST
# ============================================================

@dp.callback_query(F.data == "game_chest")
async def chest(call: CallbackQuery):

    rewards = [
        50,
        75,
        100,
        150,
        250,
        500,
        1000
    ]

    reward = random.choice(
        rewards
    )

    if is_premium(call.from_user.id):

        reward = int(
            reward * 1.5
        )

    add_coins(
        call.from_user.id,
        reward
    )

    add_xp(
        call.from_user.id,
        20
    )

    await call.answer(
        f"""
🎁 СУНДУК ОТКРЫТ!

🪙 +<b>{reward}</b>
""",
        show_alert=True
    )


# ============================================================
# PREMIUM GAME
# ============================================================

@dp.callback_query(F.data == "game_premium_game")
async def premium_game(call: CallbackQuery):

    if not is_premium(call.from_user.id):

        await call.answer(
            "⭐ Эта игра доступна только Premium.",
            show_alert=True
        )

        return

    roll = random.randint(
        1,
        100
    )

    if roll >= 95:

        reward = 1000

    elif roll >= 75:

        reward = 400

    elif roll >= 50:

        reward = 200

    else:

        reward = 50

    add_coins(
        call.from_user.id,
        reward
    )

    add_xp(
        call.from_user.id,
        50
    )

    await call.answer(
        f"""
💎 <b>PREMIUM JACKPOT</b>

🎯 Выпало: {roll}

🪙 +<b>{reward}</b>
""",
        show_alert=True
    )


# ============================================================
# QUIZ
# ============================================================

QUIZ = [

    (
        "🌍 Столица Японии?",
        ["Токио", "Киото", "Осака", "Нагоя"],
        0
    ),

    (
        "🪐 Какая планета самая большая?",
        ["Земля", "Марс", "Юпитер", "Венера"],
        2
    ),

    (
        "🧮 15 × 6?",
        ["80", "90", "100", "120"],
        1
    ),

    (
        "⚡ Единица силы тока?",
        ["Вольт", "Ампер", "Ом", "Ватт"],
        1
    ),

    (
        "📚 Кто написал «Евгения Онегина»?",
        ["Пушкин", "Толстой", "Гоголь", "Лермонтов"],
        0
    ),

]


@dp.callback_query(F.data == "game_quiz")
async def quiz(call: CallbackQuery):

    question, answers, correct = random.choice(
        QUIZ
    )

    builder = InlineKeyboardBuilder()

    for i, answer in enumerate(answers):

        builder.button(
            text=answer,
            callback_data=f"answer:{correct}:{i}"
        )

    builder.adjust(1)

    await call.message.edit_text(
        f"""
<b>🧠 ВИКТОРИНА</b>

{question}
""",
        reply_markup=builder.as_markup()
    )


@dp.callback_query(F.data.startswith("answer:"))
async def quiz_answer(call: CallbackQuery):

    _, correct, selected = call.data.split(":")

    correct = int(correct)
    selected = int(selected)

    if correct == selected:

        reward = 150

        record_game(
            call.from_user.id,
            win=True,
            reward=reward
        )

        text = f"""
🎉 ПРАВИЛЬНО!

🏆 Победа
🪙 +{reward}
"""

    else:

        record_game(
            call.from_user.id
        )

        text = "❌ Неправильно."

    await call.answer(
        text,
        show_alert=True
    )

    await call.message.edit_text(
        text,
        reply_markup=games_keyboard()
    )


# ============================================================
# PREMIUM MENU
# ============================================================

@dp.callback_query(F.data == "premium")
async def premium_menu(call: CallbackQuery):

    await call.answer()

    active = is_premium(
        call.from_user.id
    )

    status = (
        "🟢 Premium активен"
        if active
        else "⚪ Premium отсутствует"
    )

    await call.message.edit_text(
        f"""
<b>⭐ RANDOM PARTY PREMIUM</b>

{status}

<b>Что получает Premium:</b>

⚡ <b>+50% к наградам игр</b>
🎁 <b>x2 Daily</b>
💎 Premium Jackpot
🎁 Premium-сундуки
🛡️ защита Streak
👑 Premium-статус
🏆 специальный рейтинг
🎨 эксклюзивные титулы
🏟️ специальные групповые события
🔥 больше наград за задания

Цена:

<b>{PREMIUM_PRICE} ⭐ / 30 дней</b>
""",
        reply_markup=InlineKeyboardMarkup(
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
    )


# ============================================================
# STARS PAYMENT
# ============================================================

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
        provider_token="",
        currency="XTR",
        prices=[
            LabeledPrice(
                label="Premium 30 дней",
                amount=PREMIUM_PRICE
            )
        ]
    )


@dp.pre_checkout_query()
async def pre_checkout(
    query: PreCheckoutQuery
):

    if query.currency != "XTR":

        await query.answer(
            ok=False,
            error_message="Неверная валюта."
        )

        return

    if query.total_amount != PREMIUM_PRICE:

        await query.answer(
            ok=False,
            error_message="Неверная цена."
        )

        return

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

    activate_premium(
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
        VALUES(?,?,?,?,?)
        """, (
            user_id,
            payment.total_amount,
            payment.invoice_payload,
            payment.telegram_payment_charge_id,
            int(time.time())
        ))

        con.commit()

    await message.answer(
        """
🎉 <b>PREMIUM АКТИВИРОВАН!</b>

⭐ Добро пожаловать в Premium.

Теперь тебе доступны:

⚡ +50% наград
🎁 x2 Daily
💎 Premium Jackpot
🛡️ дополнительные возможности
🏟️ специальные события
""",
        reply_markup=main_keyboard()
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


# ============================================================
# GROUP COMMANDS
# ============================================================

@dp.message(Command("party"))
async def party(message: Message):

    if message.chat.type not in (
        ChatType.GROUP,
        ChatType.SUPERGROUP
    ):
        return

    register_group(
        message
    )

    await message.answer(
        """
<b>🎉 RANDOM PARTY</b>

Теперь эта группа — игровая арена.

🎮 /join — войти
⚔️ /duel — дуэль
🎯 /random — случайный игрок
🪙 /coin — монетка
🎲 /dice — кубик
🎰 /slot — слот
🧠 /quiz — викторина
🎉 /event — событие
🏆 /top — рейтинг

🔥 Зовите друзей и прокачивайте арену.
"""
    )


@dp.message(Command("join"))
async def join(message: Message):

    if message.chat.type not in (
        ChatType.GROUP,
        ChatType.SUPERGROUP
    ):
        return

    register_group(
        message
    )

    await message.answer(
        f"🎮 <b>{message.from_user.first_name}</b> присоединился к арене!"
    )


# ============================================================
# RANDOM PLAYER
# ============================================================

@dp.message(Command("random"))
async def random_player(message: Message):

    if message.chat.type not in (
        ChatType.GROUP,
        ChatType.SUPERGROUP
    ):
        return

    register_group(
        message
    )

    players = group_players(
        message.chat.id
    )

    if len(players) < 1:

        await message.answer(
            "Никого нет. Напишите /join"
        )

        return

    player = random.choice(
        players
    )

    user_id, first, username = player

    name = first or username or "Игрок"

    await message.answer(
        f"""
🎯 <b>СЛУЧАЙНЫЙ ИГРОК</b>

Сегодня судьба выбрала:

🔥 <b>{name}</b>
"""
    )


# ============================================================
# DUEL
# ============================================================

@dp.message(Command("duel"))
async def duel(message: Message):

    if message.chat.type not in (
        ChatType.GROUP,
        ChatType.SUPERGROUP
    ):
        return

    register_group(
        message
    )

    players = group_players(
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

    a_name = a[1] or a[2] or "Игрок"
    b_name = b[1] or b[2] or "Игрок"

    winner_name = (
        winner[1]
        or winner[2]
        or "Игрок"
    )

    group_reward(
        message.chat.id,
        winner[0],
        win=True,
        coins=100
    )

    record_game(
        winner[0],
        win=True,
        reward=100
    )

    await message.answer(
        f"""
⚔️ <b>ДУЭЛЬ</b>

🥊 {a_name}
VS
🥊 {b_name}

━━━━━━━━━━━━

🏆 ПОБЕДИТЕЛЬ:

<b>{winner_name}</b>

🪙 +100
"""
    )


# ============================================================
# GROUP COIN
# ============================================================

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


# ============================================================
# GROUP DICE
# ============================================================

@dp.message(Command("dice"))
async def group_dice(message: Message):

    if message.chat.type not in (
        ChatType.GROUP,
        ChatType.SUPERGROUP
    ):
        return

    register_group(
        message
    )

    value = random.randint(
        1,
        6
    )

    reward = value * 10

    group_reward(
        message.chat.id,
        message.from_user.id,
        coins=reward
    )

    record_game(
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


# ============================================================
# GROUP SLOT
# ============================================================

@dp.message(Command("slot"))
async def group_slot(message: Message):

    if message.chat.type not in (
        ChatType.GROUP,
        ChatType.SUPERGROUP
    ):
        return

    register_group(
        message
    )

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

        reward = 500

        group_reward(
            message.chat.id,
            message.from_user.id,
            win=True,
            coins=reward
        )

        record_game(
            message.from_user.id,
            win=True,
            reward=reward
        )

        result = "🎉 <b>ДЖЕКПОТ!</b>"

    elif a == b or b == c or a == c:

        reward = 100

        group_reward(
            message.chat.id,
            message.from_user.id,
            win=True,
            coins=reward
        )

        record_game(
            message.from_user.id,
            win=True,
            reward=reward
        )

        result = "🔥 <b>ПАРА!</b>"

    else:

        reward = 10

        group_reward(
            message.chat.id,
            message.from_user.id,
            coins=reward
        )

        record_game(
            message.from_user.id,
            reward=reward
        )

        result = "😈 Не повезло"

    await message.answer(
        f"""
🎰 {a} {b} {c}

{result}

🪙 +{reward}
"""
    )


# ============================================================
# GROUP QUIZ
# ============================================================

@dp.message(Command("quiz"))
async def group_quiz(message: Message):

    if message.chat.type not in (
        ChatType.GROUP,
        ChatType.SUPERGROUP
    ):
        return

    question, answers, correct = random.choice(
        QUIZ
    )

    text = f"""
<b>🧠 ВИКТОРИНА</b>

{question}

"""

    for i, answer in enumerate(
        answers,
        1
    ):

        text += f"{i}. {answer}\n"

    text += "\nПервый правильный ответ получает награду."

    await message.answer(
        text
    )


# ============================================================
# GROUP TOP
# ============================================================

@dp.message(Command("top"))
async def group_top(message: Message):

    if message.chat.type not in (
        ChatType.GROUP,
        ChatType.SUPERGROUP
    ):
        return

    register_group(
        message
    )

    with closing(db()) as con:

        rows = con.execute("""
        SELECT
            gm.first_name,
            gm.username,
            gs.wins,
            gs.coins
        FROM group_stats gs
        JOIN group_members gm
          ON gm.chat_id=gs.chat_id
         AND gm.user_id=gs.user_id
        WHERE gs.chat_id=?
        ORDER BY gs.wins DESC, gs.coins DESC
        LIMIT 10
        """, (
            message.chat.id
        )).fetchall()

    if not rows:

        await message.answer(
            "🏆 Рейтинг пуст."
        )

        return

    text = "<b>🏆 ТОП ГРУППЫ</b>\n\n"

    for i, row in enumerate(
        rows,
        1
    ):

        first, username, wins, coins = row

        name = first or username or "Игрок"

        text += (
            f"{i}. <b>{name}</b>\n"
            f"   🏆 {wins} | 🪙 {coins}\n"
        )

    await message.answer(
        text
    )


# ============================================================
# GROUP EVENT
# ============================================================

@dp.message(Command("event"))
async def group_event(message: Message):

    if message.chat.type not in (
        ChatType.GROUP,
        ChatType.SUPERGROUP
    ):
        return

    register_group(
        message
    )

    players = group_players(
        message.chat.id
    )

    if len(players) < 2:

        await message.answer(
            "🎉 Для события нужно хотя бы 2 участника.\n"
            "Пусть люди напишут /join"
        )

        return

    event = random.choice([
        "⚔️ БИТВА",
        "🎯 ОХОТА",
        "💎 СОКРОВИЩЕ",
        "👑 КОРОЛЬ АРЕНЫ",
        "🔥 CHAOS EVENT"
    ])

    winner = random.choice(
        players
    )

    name = winner[1] or winner[2] or "Игрок"

    reward = random.randint(
        100,
        500
    )

    group_reward(
        message.chat.id,
        winner[0],
        win=True,
        coins=reward
    )

    record_game(
        winner[0],
        win=True,
        reward=reward
    )

    with closing(db()) as con:

        con.execute("""
        UPDATE groups
        SET events=events+1
        WHERE chat_id=?
        """, (
            message.chat.id
        ))

        con.commit()

    await message.answer(
        f"""
🎉 <b>СОБЫТИЕ: {event}</b>

🔥 Участники вышли на арену...

👑 Победитель:

<b>{name}</b>

🪙 +<b>{reward}</b>
"""
    )


# ============================================================
# ID
# ============================================================

@dp.message(Command("id"))
async def user_id(message: Message):

    await message.answer(
        f"🆔 Твой ID:\n\n"
        f"<code>{message.from_user.id}</code>"
    )


# ============================================================
# ADMIN
# ============================================================

@dp.message(Command("stats"))
async def admin_stats(message: Message):

    if message.from_user.id != ADMIN_ID:
        return

    with closing(db()) as con:

        users = con.execute(
            "SELECT COUNT(*) FROM users"
        ).fetchone()[0]

        premium = con.execute("""
        SELECT COUNT(*)
        FROM users
        WHERE premium_until>?
        """, (
            int(time.time()),
        )).fetchone()[0]

        payments = con.execute(
            "SELECT COUNT(*) FROM payments"
        ).fetchone()[0]

        stars = con.execute(
            "SELECT COALESCE(SUM(stars),0) FROM payments"
        ).fetchone()[0]

        groups = con.execute(
            "SELECT COUNT(*) FROM groups"
        ).fetchone()[0]

    await message.answer(
        f"""
<b>📊 ADMIN PANEL</b>

👤 Пользователи:
<b>{users}</b>

👥 Группы:
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
            "/ban USER_ID"
        )
        return

    if not parts[1].isdigit():
        return

    target = int(
        parts[1]
    )

    with closing(db()) as con:

        con.execute("""
        UPDATE users
        SET banned=1
        WHERE user_id=?
        """, (
            target
        ))

        con.commit()

    await message.answer(
        f"🔨 Заблокирован:\n"
        f"<code>{target}</code>"
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

    with closing(db()) as con:

        con.execute("""
        UPDATE users
        SET banned=0
        WHERE user_id=?
        """, (
            target
        ))

        con.commit()

    await message.answer(
        f"✅ Разблокирован:\n"
        f"<code>{target}</code>"
    )


# ============================================================
# PRIVATE FALLBACK
# ============================================================

@dp.message()
async def fallback(message: Message):

    if message.chat.type != ChatType.PRIVATE:
        return

    register(
        message.from_user
    )

    if is_banned(
        message.from_user.id
    ):
        return

    await message.answer(
        "Выбирай действие 👇",
        reply_markup=main_keyboard()
    )


# ============================================================
# RUN
# ============================================================

async def main():

    init_db()

    me = await bot.get_me()

    logging.info(
        "RANDOM PARTY started: @%s",
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

        logging.info(
            "Bot stopped"
        )