import asyncio
import logging
import os
import sqlite3
import time
from contextlib import closing

from aiogram import Bot, Dispatcher, F
from aiogram.enums import ChatType
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

# =========================================================
# CONFIG
# =========================================================

BOT_TOKEN = os.getenv("BOT_TOKEN")

# Необязательно.
# Если добавишь ADMIN_ID в Railway Variables,
# бот будет отправлять админу жалобы и статистику.
ADMIN_ID_RAW = os.getenv("ADMIN_ID")
ADMIN_ID = int(ADMIN_ID_RAW) if ADMIN_ID_RAW and ADMIN_ID_RAW.isdigit() else None

DB_FILE = os.getenv("DB_FILE", "chatroulette.db")

# Через сколько секунд неактивный поиск считается устаревшим
QUEUE_TIMEOUT = 30 * 60

# Минимальный интервал между обычными сообщениями
MESSAGE_COOLDOWN = 0.7

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)

logger = logging.getLogger(__name__)

if not BOT_TOKEN:
    raise RuntimeError(
        "BOT_TOKEN не найден. Добавь BOT_TOKEN в Railway → Variables."
    )


# =========================================================
# BOT
# =========================================================

bot = Bot(BOT_TOKEN)
dp = Dispatcher()

# Защищает операции с очередью/парами от одновременных запросов
state_lock = asyncio.Lock()

# Последнее время отправки сообщения пользователем
last_message_time = {}


# =========================================================
# DATABASE
# =========================================================

def db():
    return sqlite3.connect(DB_FILE)


def init_db():
    with closing(db()) as conn:
        cur = conn.cursor()

        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                joined_at INTEGER NOT NULL,
                last_seen INTEGER NOT NULL,
                messages_sent INTEGER DEFAULT 0,
                messages_received INTEGER DEFAULT 0,
                reports INTEGER DEFAULT 0,
                banned INTEGER DEFAULT 0
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS queue (
                user_id INTEGER PRIMARY KEY,
                joined_at INTEGER NOT NULL
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS pairs (
                user1 INTEGER PRIMARY KEY,
                user2 INTEGER NOT NULL
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS blocks (
                user_id INTEGER NOT NULL,
                blocked_id INTEGER NOT NULL,
                PRIMARY KEY (user_id, blocked_id)
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                reporter INTEGER NOT NULL,
                reported INTEGER NOT NULL,
                created_at INTEGER NOT NULL
            )
        """)

        conn.commit()


def ensure_user(user_id: int):
    now = int(time.time())

    with closing(db()) as conn:
        cur = conn.cursor()

        cur.execute(
            "SELECT user_id FROM users WHERE user_id = ?",
            (user_id,),
        )

        exists = cur.fetchone()

        if exists:
            cur.execute(
                """
                UPDATE users
                SET last_seen = ?
                WHERE user_id = ?
                """,
                (now, user_id),
            )
        else:
            cur.execute(
                """
                INSERT INTO users
                (user_id, joined_at, last_seen)
                VALUES (?, ?, ?)
                """,
                (user_id, now, now),
            )

        conn.commit()


def is_banned(user_id: int) -> bool:
    with closing(db()) as conn:
        cur = conn.cursor()

        cur.execute(
            "SELECT banned FROM users WHERE user_id = ?",
            (user_id,),
        )

        row = cur.fetchone()

        return bool(row and row[0])


def get_partner(user_id: int):
    with closing(db()) as conn:
        cur = conn.cursor()

        cur.execute(
            "SELECT user2 FROM pairs WHERE user1 = ?",
            (user_id,),
        )

        row = cur.fetchone()

        if row:
            return row[0]

        cur.execute(
            "SELECT user1 FROM pairs WHERE user2 = ?",
            (user_id,),
        )

        row = cur.fetchone()

        if row:
            return row[0]

        return None


def add_pair(user1: int, user2: int):
    with closing(db()) as conn:
        cur = conn.cursor()

        cur.execute(
            "DELETE FROM queue WHERE user_id IN (?, ?)",
            (user1, user2),
        )

        cur.execute(
            "INSERT OR REPLACE INTO pairs (user1, user2) VALUES (?, ?)",
            (user1, user2),
        )

        conn.commit()


def remove_pair(user_id: int):
    with closing(db()) as conn:
        cur = conn.cursor()

        cur.execute(
            """
            DELETE FROM pairs
            WHERE user1 = ? OR user2 = ?
            """,
            (user_id, user_id),
        )

        conn.commit()


def add_to_queue(user_id: int):
    now = int(time.time())

    with closing(db()) as conn:
        cur = conn.cursor()

        cur.execute(
            """
            INSERT OR REPLACE INTO queue
            (user_id, joined_at)
            VALUES (?, ?)
            """,
            (user_id, now),
        )

        conn.commit()


def remove_from_queue(user_id: int):
    with closing(db()) as conn:
        cur = conn.cursor()

        cur.execute(
            "DELETE FROM queue WHERE user_id = ?",
            (user_id,),
        )

        conn.commit()


def get_queue_users():
    with closing(db()) as conn:
        cur = conn.cursor()

        cur.execute(
            """
            SELECT user_id
            FROM queue
            ORDER BY joined_at ASC
            """
        )

        return [row[0] for row in cur.fetchall()]


def cleanup_queue():
    cutoff = int(time.time()) - QUEUE_TIMEOUT

    with closing(db()) as conn:
        cur = conn.cursor()

        cur.execute(
            "DELETE FROM queue WHERE joined_at < ?",
            (cutoff,),
        )

        conn.commit()


def are_blocked(user1: int, user2: int) -> bool:
    with closing(db()) as conn:
        cur = conn.cursor()

        cur.execute(
            """
            SELECT 1
            FROM blocks
            WHERE user_id = ? AND blocked_id = ?
            """,
            (user1, user2),
        )

        return cur.fetchone() is not None


def block_user(user_id: int, blocked_id: int):
    with closing(db()) as conn:
        cur = conn.cursor()

        cur.execute(
            """
            INSERT OR IGNORE INTO blocks
            (user_id, blocked_id)
            VALUES (?, ?)
            """,
            (user_id, blocked_id),
        )

        conn.commit()


def add_report(reporter: int, reported: int):
    now = int(time.time())

    with closing(db()) as conn:
        cur = conn.cursor()

        cur.execute(
            """
            INSERT INTO reports
            (reporter, reported, created_at)
            VALUES (?, ?, ?)
            """,
            (reporter, reported, now),
        )

        cur.execute(
            """
            UPDATE users
            SET reports = reports + 1
            WHERE user_id = ?
            """,
            (reporter,),
        )

        conn.commit()


def add_message_stats(sender: int, receiver: int):
    with closing(db()) as conn:
        cur = conn.cursor()

        cur.execute(
            """
            UPDATE users
            SET messages_sent = messages_sent + 1
            WHERE user_id = ?
            """,
            (sender,),
        )

        cur.execute(
            """
            UPDATE users
            SET messages_received = messages_received + 1
            WHERE user_id = ?
            """,
            (receiver,),
        )

        conn.commit()


def get_stats():
    with closing(db()) as conn:
        cur = conn.cursor()

        cur.execute("SELECT COUNT(*) FROM users")
        users = cur.fetchone()[0]

        cur.execute("SELECT COUNT(*) FROM queue")
        queue = cur.fetchone()[0]

        cur.execute("SELECT COUNT(*) FROM pairs")
        pairs = cur.fetchone()[0]

        cur.execute("SELECT COUNT(*) FROM reports")
        reports = cur.fetchone()[0]

        cur.execute(
            "SELECT COALESCE(SUM(messages_sent), 0) FROM users"
        )
        messages = cur.fetchone()[0]

        return users, queue, pairs, reports, messages


# =========================================================
# KEYBOARDS
# =========================================================

def main_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🔎 Найти собеседника",
                    callback_data="find",
                )
            ],
            [
                InlineKeyboardButton(
                    text="ℹ️ Как это работает",
                    callback_data="help",
                )
            ],
        ]
    )


def searching_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="❌ Остановить поиск",
                    callback_data="stop_search",
                )
            ]
        ]
    )


def chat_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🔄 Следующий",
                    callback_data="next",
                ),
                InlineKeyboardButton(
                    text="⏹ Завершить",
                    callback_data="stop_chat",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="🚩 Пожаловаться",
                    callback_data="report",
                )
            ],
        ]
    )


def after_chat_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🔎 Найти нового",
                    callback_data="find",
                )
            ],
            [
                InlineKeyboardButton(
                    text="🏠 Главное меню",
                    callback_data="home",
                )
            ],
        ]
    )


# =========================================================
# TEXTS
# =========================================================

WELCOME_TEXT = """
👋 <b>Добро пожаловать в анонимную чат-рулетку.</b>

Здесь ты можешь случайно найти человека и общаться с ним через бота.

🔐 Твой Telegram-профиль не показывается собеседнику.

💬 Можно отправлять:
• текст
• фото
• видео
• голосовые
• документы
• стикеры
• GIF
• контакты
• геолокацию

Используй кнопки ниже.
"""

HELP_TEXT = """
ℹ️ <b>Как работает чат-рулетка</b>

1. Нажми «🔎 Найти собеседника».
2. Бот найдёт случайного человека.
3. После соединения отправляй сообщения как обычно.
4. Собеседник получит их от бота.
5. Нажми «🔄 Следующий», чтобы сменить человека.
6. Нажми «⏹ Завершить», чтобы закончить разговор.

🔐 Мы не показываем собеседнику твой username или профиль.

🚩 Если собеседник нарушает правила, используй кнопку «Пожаловаться».

⚠️ Не отправляй незнакомым людям пароли,
коды подтверждения, банковские данные или личные документы.
"""


# =========================================================
# UTILITIES
# =========================================================

async def safe_send(user_id: int, text: str, **kwargs):
    try:
        return await bot.send_message(
            user_id,
            text,
            **kwargs,
        )
    except Exception as e:
        logger.warning(
            "Не удалось отправить сообщение %s: %s",
            user_id,
            e,
        )
        return None


async def notify_partner_chat_ended(partner_id: int):
    await safe_send(
        partner_id,
        """
⏹ <b>Собеседник завершил разговор.</b>

Можешь найти нового человека.
""",
        reply_markup=after_chat_keyboard(),
    )


async def find_partner(user_id: int):
    async with state_lock:

        cleanup_queue()

        # Если уже есть собеседник
        existing = get_partner(user_id)

        if existing:
            return existing

        # Удаляем самого себя из очереди перед поиском
        remove_from_queue(user_id)

        users = get_queue_users()

        for candidate in users:

            if candidate == user_id:
                continue

            if is_banned(candidate):
                remove_from_queue(candidate)
                continue

            if are_blocked(user_id, candidate):
                continue

            if are_blocked(candidate, user_id):
                continue

            add_pair(user_id, candidate)

            return candidate

        add_to_queue(user_id)

        return None


async def end_chat(user_id: int, notify=True):
    async with state_lock:

        partner = get_partner(user_id)

        remove_pair(user_id)
        remove_from_queue(user_id)

    if partner and notify:
        await notify_partner_chat_ended(partner)

    return partner


async def next_chat(user_id: int):
    partner = await end_chat(user_id, notify=True)

    await safe_send(
        user_id,
        "🔄 Ищем нового собеседника...",
    )

    return await find_partner(user_id)


async def connect_message(user_id: int, partner_id: int):
    await safe_send(
        user_id,
        """
🎉 <b>Собеседник найден!</b>

Теперь можете общаться.

Твои сообщения будут передаваться через бота.

🔐 Не отправляй личные данные незнакомцам.
""",
        reply_markup=chat_keyboard(),
    )

    await safe_send(
        partner_id,
        """
🎉 <b>Собеседник найден!</b>

Теперь можете общаться.

Твои сообщения будут передаваться через бота.

🔐 Не отправляй личные данные незнакомцам.
""",
        reply_markup=chat_keyboard(),
    )


# =========================================================
# START
# =========================================================

@dp.message(CommandStart())
async def start_handler(message: Message):

    if message.chat.type != ChatType.PRIVATE:
        return

    user_id = message.from_user.id

    ensure_user(user_id)

    if is_banned(user_id):
        await message.answer(
            "🚫 Твой доступ к боту ограничен."
        )
        return

    partner = get_partner(user_id)

    if partner:
        await message.answer(
            """
💬 <b>Ты уже находишься в чате.</b>

Просто отправь сообщение.
""",
            reply_markup=chat_keyboard(),
        )
        return

    await message.answer(
        WELCOME_TEXT,
        reply_markup=main_keyboard(),
    )


# =========================================================
# HELP
# =========================================================

@dp.callback_query(F.data == "help")
async def help_callback(callback: CallbackQuery):

    await callback.answer()

    await callback.message.edit_text(
        HELP_TEXT,
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="🔎 Найти собеседника",
                        callback_data="find",
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="⬅️ Назад",
                        callback_data="home",
                    )
                ],
            ]
        ),
    )


@dp.message(Command("help"))
async def help_command(message: Message):

    ensure_user(message.from_user.id)

    await message.answer(
        HELP_TEXT,
        reply_markup=main_keyboard(),
    )


# =========================================================
# HOME
# =========================================================

@dp.callback_query(F.data == "home")
async def home_callback(callback: CallbackQuery):

    await callback.answer()

    await callback.message.edit_text(
        WELCOME_TEXT,
        reply_markup=main_keyboard(),
    )


# =========================================================
# FIND
# =========================================================

@dp.callback_query(F.data == "find")
async def find_callback(callback: CallbackQuery):

    user_id = callback.from_user.id

    ensure_user(user_id)

    await callback.answer()

    if is_banned(user_id):
        await callback.message.answer(
            "🚫 Твой доступ к боту ограничен."
        )
        return

    existing = get_partner(user_id)

    if existing:
        await callback.message.answer(
            """
💬 Ты уже находишься в разговоре.

Отправляй сообщения собеседнику.
""",
            reply_markup=chat_keyboard(),
        )
        return

    partner = await find_partner(user_id)

    if partner:

        await connect_message(
            user_id,
            partner,
        )

    else:

        await callback.message.edit_text(
            """
🔎 <b>Ищем собеседника...</b>

Ты добавлен в очередь.

Как только найдём человека,
бот автоматически соединит вас.
""",
            reply_markup=searching_keyboard(),
        )


# =========================================================
# STOP SEARCH
# =========================================================

@dp.callback_query(F.data == "stop_search")
async def stop_search_callback(callback: CallbackQuery):

    user_id = callback.from_user.id

    await callback.answer()

    async with state_lock:
        remove_from_queue(user_id)

    await callback.message.edit_text(
        """
⏹ <b>Поиск остановлен.</b>

Когда захочешь попробовать снова,
нажми кнопку ниже.
""",
        reply_markup=after_chat_keyboard(),
    )


# =========================================================
# STOP CHAT
# =========================================================

@dp.callback_query(F.data == "stop_chat")
async def stop_chat_callback(callback: CallbackQuery):

    user_id = callback.from_user.id

    await callback.answer()

    partner = await end_chat(
        user_id,
        notify=True,
    )

    if partner:
        await callback.message.edit_text(
            """
⏹ <b>Разговор завершён.</b>

Собеседник получил уведомление.
""",
            reply_markup=after_chat_keyboard(),
        )
    else:
        await callback.message.edit_text(
            """
⏹ <b>Чат завершён.</b>
""",
            reply_markup=after_chat_keyboard(),
        )


# =========================================================
# NEXT
# =========================================================

@dp.callback_query(F.data == "next")
async def next_callback(callback: CallbackQuery):

    user_id = callback.from_user.id

    await callback.answer(
        "Ищем нового собеседника..."
    )

    partner = await next_chat(user_id)

    if partner:

        await connect_message(
            user_id,
            partner,
        )

    else:

        await callback.message.edit_text(
            """
🔎 <b>Ищем нового собеседника...</b>

Ты в очереди.
Как только найдём человека —
соединим вас.
""",
            reply_markup=searching_keyboard(),
        )


# =========================================================
# REPORT
# =========================================================

@dp.callback_query(F.data == "report")
async def report_callback(callback: CallbackQuery):

    user_id = callback.from_user.id

    partner = get_partner(user_id)

    await callback.answer(
        "Жалоба отправлена.",
        show_alert=True,
    )

    if not partner:
        return

    add_report(
        reporter=user_id,
        reported=partner,
    )

    if ADMIN_ID:

        await safe_send(
            ADMIN_ID,
            f"""
🚩 <b>Новая жалоба</b>

Reporter ID:
<code>{user_id}</code>

Reported ID:
<code>{partner}</code>

Используй:
<code>/ban {partner}</code>
если нужно ограничить пользователя.
""",
        )

    # После жалобы автоматически разрываем чат
    await end_chat(
        user_id,
        notify=True,
    )

    await safe_send(
        user_id,
        """
🚩 <b>Жалоба принята.</b>

Разговор завершён.

Если хочешь, можешь найти нового собеседника.
""",
        reply_markup=after_chat_keyboard(),
    )


# =========================================================
# ADMIN
# =========================================================

def admin_only(user_id: int) -> bool:
    return ADMIN_ID is not None and user_id == ADMIN_ID


@dp.message(Command("stats"))
async def stats_handler(message: Message):

    if not admin_only(message.from_user.id):
        return

    users, queue, pairs, reports, messages = get_stats()

    await message.answer(
        f"""
📊 <b>Статистика бота</b>

👤 Пользователей: <b>{users}</b>
🔎 В очереди: <b>{queue}</b>
💬 Активных пар: <b>{pairs}</b>
🚩 Жалоб: <b>{reports}</b>
💌 Сообщений: <b>{messages}</b>
"""
    )


@dp.message(Command("ban"))
async def ban_handler(message: Message):

    if not admin_only(message.from_user.id):
        return

    args = message.text.split()

    if len(args) != 2 or not args[1].isdigit():
        await message.answer(
            "Использование: /ban USER_ID"
        )
        return

    target = int(args[1])

    ensure_user(target)

    with closing(db()) as conn:
        cur = conn.cursor()

        cur.execute(
            """
            UPDATE users
            SET banned = 1
            WHERE user_id = ?
            """,
            (target,),
        )

        conn.commit()

    await end_chat(
        target,
        notify=True,
    )

    await message.answer(
        f"🔨 Пользователь <code>{target}</code> заблокирован."
    )

    await safe_send(
        target,
        """
🚫 <b>Доступ ограничен.</b>

Ты больше не можешь использовать этот бот.
""",
    )


@dp.message(Command("unban"))
async def unban_handler(message: Message):

    if not admin_only(message.from_user.id):
        return

    args = message.text.split()

    if len(args) != 2 or not args[1].isdigit():
        await message.answer(
            "Использование: /unban USER_ID"
        )
        return

    target = int(args[1])

    ensure_user(target)

    with closing(db()) as conn:
        cur = conn.cursor()

        cur.execute(
            """
            UPDATE users
            SET banned = 0
            WHERE user_id = ?
            """,
            (target,),
        )

        conn.commit()

    await message.answer(
        f"✅ Пользователь <code>{target}</code> разблокирован."
    )


@dp.message(Command("id"))
async def id_handler(message: Message):

    await message.answer(
        f"🆔 Твой ID:\n<code>{message.from_user.id}</code>"
    )


# =========================================================
# MESSAGE RELAY
# =========================================================

@dp.message()
async def relay_message(message: Message):

    # Работаем только в личке
    if message.chat.type != ChatType.PRIVATE:
        return

    user_id = message.from_user.id

    ensure_user(user_id)

    if is_banned(user_id):
        await message.answer(
            "🚫 Доступ к боту ограничен."
        )
        return

    # Не пересылаем команды
    if message.text and message.text.startswith("/"):
        return

    partner = get_partner(user_id)

    if not partner:
        await message.answer(
            """
🔎 <b>Ты сейчас не в чате.</b>

Нажми «Найти собеседника», чтобы начать.
""",
            reply_markup=main_keyboard(),
        )
        return

    # Антиспам
    now = time.monotonic()

    previous = last_message_time.get(user_id, 0)

    if now - previous < MESSAGE_COOLDOWN:
        return

    last_message_time[user_id] = now

    # Проверяем, не заблокировали ли пользователи друг друга
    if are_blocked(user_id, partner):
        await end_chat(
            user_id,
            notify=False,
        )

        await message.answer(
            """
🚫 Этот чат больше недоступен.

Найди нового собеседника.
""",
            reply_markup=after_chat_keyboard(),
        )

        return

    # Передача сообщения через Telegram copyMessage.
    # В отличие от forwardMessage, копия не содержит
    # ссылку на исходное сообщение/автора.
    try:

        await bot.copy_message(
            chat_id=partner,
            from_chat_id=user_id,
            message_id=message.message_id,
        )

        add_message_stats(
            sender=user_id,
            receiver=partner,
        )

    except Exception as e:

        logger.warning(
            "Ошибка передачи сообщения %s -> %s: %s",
            user_id,
            partner,
            e,
        )

        await message.answer(
            """
⚠️ Не удалось передать это сообщение.

Попробуй отправить его ещё раз или используй обычный текст.
"""
        )


# =========================================================
# ERROR HANDLER
# =========================================================

@dp.errors()
async def errors_handler(event):

    logger.exception(
        "Ошибка обработчика: %s",
        event.exception,
    )


# =========================================================
# CLEANUP LOOP
# =========================================================

async def background_cleanup():

    while True:

        try:
            cleanup_queue()

            # Чистим старые cooldown-записи
            now = time.monotonic()

            expired = [
                user_id
                for user_id, timestamp
                in last_message_time.items()
                if now - timestamp > 300
            ]

            for user_id in expired:
                last_message_time.pop(
                    user_id,
                    None,
                )

        except Exception as e:

            logger.exception(
                "Ошибка фоновой очистки: %s",
                e,
            )

        await asyncio.sleep(60)


# =========================================================
# MAIN
# =========================================================

async def main():

    init_db()

    logger.info("===================================")
    logger.info("ANONYMOUS CHAT ROULETTE STARTING")
    logger.info("===================================")

    me = await bot.get_me()

    logger.info(
        "Bot started: @%s",
        me.username,
    )

    cleanup_task = asyncio.create_task(
        background_cleanup()
    )

    try:

        await bot.delete_webhook(
            drop_pending_updates=True
        )

        await dp.start_polling(
            bot,
            allowed_updates=dp.resolve_used_update_types(),
        )

    finally:

        cleanup_task.cancel()

        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped.")