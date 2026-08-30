import asyncio
import logging
import os
import random
from datetime import datetime, date

import aiosqlite
from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from dotenv import load_dotenv


# =========================================================
# CONFIG
# =========================================================

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

# Необязательно.
# Если оставишь пустым — AI-функция просто сообщит,
# что AI пока не настроен.
AI_API_KEY = os.getenv("AI_API_KEY", "")

DB_NAME = "bot.db"

logging.basicConfig(level=logging.INFO)


# =========================================================
# BOT
# =========================================================

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN не найден в переменных окружения.")

bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)

dp = Dispatcher()


# =========================================================
# DATABASE
# =========================================================

async def init_db():
    async with aiosqlite.connect(DB_NAME) as db:

        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                balance INTEGER DEFAULT 0,
                xp INTEGER DEFAULT 0,
                level INTEGER DEFAULT 1,
                games INTEGER DEFAULT 0,
                referrals INTEGER DEFAULT 0,
                streak INTEGER DEFAULT 0,
                last_bonus TEXT,
                joined_at TEXT
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS achievements (
                user_id INTEGER,
                achievement TEXT,
                UNIQUE(user_id, achievement)
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS ai_history (
                user_id INTEGER,
                role TEXT,
                text TEXT,
                created_at TEXT
            )
        """)

        await db.commit()


async def create_user(user: Message):
    async with aiosqlite.connect(DB_NAME) as db:

        cur = await db.execute(
            "SELECT id FROM users WHERE id = ?",
            (user.from_user.id,)
        )

        exists = await cur.fetchone()

        if not exists:
            await db.execute("""
                INSERT INTO users
                (id, username, first_name, joined_at)
                VALUES (?, ?, ?, ?)
            """, (
                user.from_user.id,
                user.from_user.username or "",
                user.from_user.first_name or "",
                datetime.now().isoformat()
            ))

            await db.commit()


async def get_user(user_id):
    async with aiosqlite.connect(DB_NAME) as db:

        cur = await db.execute(
            "SELECT * FROM users WHERE id = ?",
            (user_id,)
        )

        return await cur.fetchone()


async def add_xp(user_id, amount):

    async with aiosqlite.connect(DB_NAME) as db:

        cur = await db.execute(
            "SELECT xp, level FROM users WHERE id = ?",
            (user_id,)
        )

        row = await cur.fetchone()

        if not row:
            return

        xp, level = row

        xp += amount

        new_level = max(1, xp // 100 + 1)

        await db.execute("""
            UPDATE users
            SET xp = ?, level = ?
            WHERE id = ?
        """, (
            xp,
            new_level,
            user_id
        ))

        await db.commit()


async def add_balance(user_id, amount):

    async with aiosqlite.connect(DB_NAME) as db:

        await db.execute("""
            UPDATE users
            SET balance = balance + ?
            WHERE id = ?
        """, (
            amount,
            user_id
        ))

        await db.commit()


# =========================================================
# KEYBOARDS
# =========================================================

def main_menu():

    return InlineKeyboardMarkup(
        inline_keyboard=[

            [
                InlineKeyboardButton(
                    text="👤 Профиль",
                    callback_data="profile"
                ),
                InlineKeyboardButton(
                    text="🤖 AI",
                    callback_data="ai"
                )
            ],

            [
                InlineKeyboardButton(
                    text="🎮 Игры",
                    callback_data="games"
                ),
                InlineKeyboardButton(
                    text="🎁 Бонус",
                    callback_data="bonus"
                )
            ],

            [
                InlineKeyboardButton(
                    text="🏆 Рейтинг",
                    callback_data="rating"
                ),
                InlineKeyboardButton(
                    text="👥 Рефералы",
                    callback_data="ref"
                )
            ],

            [
                InlineKeyboardButton(
                    text="🏅 Достижения",
                    callback_data="achievements"
                )
            ],

            [
                InlineKeyboardButton(
                    text="ℹ️ Помощь",
                    callback_data="help"
                )
            ]

        ]
    )


def games_menu():

    return InlineKeyboardMarkup(
        inline_keyboard=[

            [
                InlineKeyboardButton(
                    text="🎲 Кубик",
                    callback_data="dice"
                ),
                InlineKeyboardButton(
                    text="🪙 Монетка",
                    callback_data="coin"
                )
            ],

            [
                InlineKeyboardButton(
                    text="🎯 Число",
                    callback_data="number"
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


# =========================================================
# START
# =========================================================

@dp.message(CommandStart())
async def start(message: Message):

    await create_user(message)

    await message.answer(
        f"""
<b>🚀 Добро пожаловать, {message.from_user.first_name}!</b>

Это твой личный бот с AI, играми,
профилем, XP, достижениями и рейтингом.

Выбирай нужный раздел ниже 👇
        """,
        reply_markup=main_menu()
    )


# =========================================================
# PROFILE
# =========================================================

@dp.callback_query(F.data == "profile")
async def profile(callback: CallbackQuery):

    user = await get_user(callback.from_user.id)

    if not user:
        await callback.answer("Сначала нажми /start")
        return

    (
        uid,
        username,
        first_name,
        balance,
        xp,
        level,
        games,
        referrals,
        streak,
        last_bonus,
        joined
    ) = user

    await callback.message.edit_text(
        f"""
<b>👤 ТВОЙ ПРОФИЛЬ</b>

🆔 ID: <code>{uid}</code>
👤 Имя: {first_name}

⭐ Уровень: <b>{level}</b>
✨ XP: <b>{xp}</b>
💰 Монеты: <b>{balance}</b>

🎮 Игр сыграно: {games}
👥 Рефералов: {referrals}
🔥 Серия бонусов: {streak}
        """,
        reply_markup=main_menu()
    )

    await callback.answer()


# =========================================================
# BONUS
# =========================================================

@dp.callback_query(F.data == "bonus")
async def bonus(callback: CallbackQuery):

    user_id = callback.from_user.id

    user = await get_user(user_id)

    if not user:
        await callback.answer("Ошибка")
        return

    last_bonus = user[9]

    today = date.today().isoformat()

    if last_bonus == today:

        await callback.answer(
            "🎁 Ты уже получил сегодняшний бонус!",
            show_alert=True
        )

        return

    reward = random.randint(50, 150)

    async with aiosqlite.connect(DB_NAME) as db:

        await db.execute("""
            UPDATE users
            SET balance = balance + ?,
                xp = xp + ?,
                last_bonus = ?,
                streak = streak + 1
            WHERE id = ?
        """, (
            reward,
            10,
            today,
            user_id
        ))

        await db.commit()

    await callback.message.edit_text(
        f"""
<b>🎁 ЕЖЕДНЕВНОЙ БОНУС</b>

Ты получил:

💰 <b>+{reward}</b> монет
✨ <b>+10 XP</b>

Заходи завтра за новым бонусом 🔥
        """,
        reply_markup=main_menu()
    )

    await callback.answer()


# =========================================================
# GAMES
# =========================================================

@dp.callback_query(F.data == "games")
async def games(callback: CallbackQuery):

    await callback.message.edit_text(
        """
<b>🎮 ИГРЫ</b>

Выбери игру:
        """,
        reply_markup=games_menu()
    )

    await callback.answer()


async def game_played(user_id):

    async with aiosqlite.connect(DB_NAME) as db:

        await db.execute("""
            UPDATE users
            SET games = games + 1
            WHERE id = ?
        """, (user_id,))

        await db.commit()

    await add_xp(user_id, 5)


@dp.callback_query(F.data == "dice")
async def dice(callback: CallbackQuery):

    result = random.randint(1, 6)

    reward = result * 5

    await add_balance(
        callback.from_user.id,
        reward
    )

    await game_played(
        callback.from_user.id
    )

    await callback.message.edit_text(
        f"""
🎲 <b>КУБИК</b>

Выпало: <b>{result}</b>

💰 Награда: <b>+{reward}</b> монет
✨ +5 XP
        """,
        reply_markup=games_menu()
    )

    await callback.answer()


@dp.callback_query(F.data == "coin")
async def coin(callback: CallbackQuery):

    result = random.choice(
        ["ОРЁЛ", "РЕШКА"]
    )

    reward = 25

    await add_balance(
        callback.from_user.id,
        reward
    )

    await game_played(
        callback.from_user.id
    )

    await callback.message.edit_text(
        f"""
🪙 <b>МОНЕТКА</b>

Выпало: <b>{result}</b>

💰 +{reward} монет
✨ +5 XP
        """,
        reply_markup=games_menu()
    )

    await callback.answer()


@dp.callback_query(F.data == "number")
async def number(callback: CallbackQuery):

    secret = random.randint(1, 10)

    await add_balance(
        callback.from_user.id,
        secret * 3
    )

    await game_played(
        callback.from_user.id
    )

    await callback.message.edit_text(
        f"""
🎯 <b>СЛУЧАЙНОЕ ЧИСЛО</b>

Твоё число: <b>{secret}</b>

💰 +{secret * 3} монет
✨ +5 XP
        """,
        reply_markup=games_menu()
    )

    await callback.answer()


# =========================================================
# RATING
# =========================================================

@dp.callback_query(F.data == "rating")
async def rating(callback: CallbackQuery):

    async with aiosqlite.connect(DB_NAME) as db:

        cur = await db.execute("""
            SELECT first_name, xp, level
            FROM users
            ORDER BY xp DESC
            LIMIT 10
        """)

        users = await cur.fetchall()

    text = "<b>🏆 ТОП 10</b>\n\n"

    if not users:
        text += "Пока никого нет."
    else:

        for i, user in enumerate(users, 1):

            name, xp, level = user

            text += (
                f"<b>{i}.</b> {name} "
                f"— ⭐ {level} "
                f"({xp} XP)\n"
            )

    await callback.message.edit_text(
        text,
        reply_markup=main_menu()
    )

    await callback.answer()


# =========================================================
# REFERRALS
# =========================================================

@dp.callback_query(F.data == "ref")
async def referrals(callback: CallbackQuery):

    me = await bot.get_me()

    link = (
        f"https://t.me/{me.username}"
        f"?start=ref_{callback.from_user.id}"
    )

    user = await get_user(
        callback.from_user.id
    )

    referrals_count = user[7] if user else 0

    await callback.message.edit_text(
        f"""
<b>👥 РЕФЕРАЛЬНАЯ СИСТЕМА</b>

Приглашай друзей и получай бонусы.

Твоя ссылка:

<code>{link}</code>

👥 Приглашено: <b>{referrals_count}</b>
💰 Награда: <b>100 монет</b> за нового пользователя
        """,
        reply_markup=main_menu()
    )

    await callback.answer()


# =========================================================
# ACHIEVEMENTS
# =========================================================

@dp.callback_query(F.data == "achievements")
async def achievements(callback: CallbackQuery):

    user = await get_user(
        callback.from_user.id
    )

    if not user:
        await callback.answer()
        return

    xp = user[4]
    games = user[6]
    referrals = user[7]

    achievements_list = []

    if xp >= 100:
        achievements_list.append("⭐ 100 XP")

    if games >= 10:
        achievements_list.append("🎮 10 игр")

    if referrals >= 5:
        achievements_list.append("👥 5 рефералов")

    if not achievements_list:
        achievements_list.append(
            "🔒 Пока нет достижений"
        )

    text = (
        "<b>🏅 ДОСТИЖЕНИЯ</b>\n\n"
        + "\n".join(achievements_list)
    )

    await callback.message.edit_text(
        text,
        reply_markup=main_menu()
    )

    await callback.answer()


# =========================================================
# AI
# =========================================================

@dp.callback_query(F.data == "ai")
async def ai_button(callback: CallbackQuery):

    await callback.message.edit_text(
        """
<b>🤖 AI-ПОМОЩНИК</b>

Напиши сообщение командой:

<code>/ai твой вопрос</code>

Например:

<code>/ai Объясни мне Python простыми словами</code>

Для выхода:
<code>/cancel</code>
        """,
        reply_markup=main_menu()
    )

    await callback.answer()


@dp.message(Command("ai"))
async def ai_command(message: Message):

    if not AI_API_KEY:

        await message.answer(
            """
🤖 <b>AI пока не настроен.</b>

Добавь <code>AI_API_KEY</code>
в переменные окружения Railway.
            """
        )

        return

    question = message.text.replace(
        "/ai",
        "",
        1
    ).strip()

    if not question:

        await message.answer(
            "Напиши вопрос после /ai"
        )

        return

    # Здесь можно подключить API выбранной
    # AI-модели.
    #
    # Бот специально не содержит ключ внутри кода.
    #
    # Это место предназначено для API-запроса.

    await message.answer(
        """
🤖 AI получил твой запрос.

Для подключения реальных ответов
нужно указать API-провайдера и его API endpoint.
        """
    )


@dp.message(Command("cancel"))
async def cancel(message: Message):

    await message.answer(
        "✅ Режим AI закрыт.",
        reply_markup=main_menu()
    )


# =========================================================
# HELP
# =========================================================

@dp.callback_query(F.data == "help")
async def help_button(callback: CallbackQuery):

    await callback.message.edit_text(
        """
<b>ℹ️ ПОМОЩЬ</b>

Основные возможности:

👤 Профиль
🎁 Ежедневные бонусы
🎮 Мини-игры
🏆 Рейтинг
👥 Реферальная система
🏅 Достижения
🤖 AI

Команды:

/start — главное меню
/ai — AI
/cancel — отменить AI
        """,
        reply_markup=main_menu()
    )

    await callback.answer()


# =========================================================
# HOME
# =========================================================

@dp.callback_query(F.data == "home")
async def home(callback: CallbackQuery):

    await callback.message.edit_text(
        """
<b>🏠 ГЛАВНОЕ МЕНЮ</b>

Выбирай нужный раздел 👇
        """,
        reply_markup=main_menu()
    )

    await callback.answer()


# =========================================================
# ADMIN
# =========================================================

def is_admin(user_id):

    return ADMIN_ID != 0 and user_id == ADMIN_ID


@dp.message(Command("admin"))
async def admin(message: Message):

    if not is_admin(message.from_user.id):

        await message.answer(
            "⛔ Доступ запрещён."
        )

        return

    async with aiosqlite.connect(DB_NAME) as db:

        cur = await db.execute(
            "SELECT COUNT(*) FROM users"
        )

        total = (await cur.fetchone())[0]

        cur = await db.execute(
            "SELECT SUM(balance) FROM users"
        )

        total_balance = (await cur.fetchone())[0] or 0

    await message.answer(
        f"""
<b>🛠 ADMIN PANEL</b>

👥 Пользователей: <b>{total}</b>
💰 Всего монет: <b>{total_balance}</b>

Команды:

/users — пользователи
/give ID количество — выдать монеты
        """
    )


@dp.message(Command("users"))
async def users_command(message: Message):

    if not is_admin(message.from_user.id):
        return

    async with aiosqlite.connect(DB_NAME) as db:

        cur = await db.execute("""
            SELECT id, first_name, balance, xp
            FROM users
            ORDER BY xp DESC
            LIMIT 20
        """)

        users = await cur.fetchall()

    text = "<b>👥 USERS</b>\n\n"

    for user in users:

        uid, name, balance, xp = user

        text += (
            f"<code>{uid}</code> "
            f"{name} | 💰{balance} | XP {xp}\n"
        )

    await message.answer(text)


@dp.message(Command("give"))
async def give_command(message: Message):

    if not is_admin(message.from_user.id):
        return

    args = message.text.split()

    if len(args) != 3:

        await message.answer(
            "/give ID количество"
        )

        return

    try:

        user_id = int(args[1])
        amount = int(args[2])

    except ValueError:

        await message.answer(
            "❌ Неверные числа."
        )

        return

    await add_balance(
        user_id,
        amount
    )

    await message.answer(
        f"✅ Пользователю {user_id} начислено {amount} монет."
    )


# =========================================================
# ERROR HANDLER
# =========================================================

@dp.errors()
async def errors_handler(event):

    logging.exception(
        "Bot error: %s",
        event.exception
    )


# =========================================================
# RUN
# =========================================================

async def main():

    await init_db()

    logging.info(
        "BOT STARTED"
    )

    await dp.start_polling(
        bot
    )


if __name__ == "__main__":

    try:
        asyncio.run(main())

    except KeyboardInterrupt:

        logging.info
            "BOT STOPPED"

### Переменные в Railway

В **Variables** добавь:

```text
BOT_TOKEN=токен_от_BotFather
ADMIN_ID=твой_Telegram_ID
AI_API_KEY=твой_AI_API_ключ