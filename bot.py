import asyncio
import logging
import os
import random
import sqlite3
from datetime import datetime, date
from html import escape

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


# =========================================================
# CONFIG
# =========================================================

BOT_TOKEN = os.getenv("BOT_TOKEN")

# AI_API_KEY можно добавить позже.
# Бот будет работать и БЕЗ него.
AI_API_KEY = os.getenv("AI_API_KEY")

if not BOT_TOKEN:
    raise RuntimeError(
        "BOT_TOKEN не найден. Добавь BOT_TOKEN в Railway Variables."
    )


# =========================================================
# LOGGING
# =========================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)

logger = logging.getLogger(__name__)


# =========================================================
# DATABASE
# =========================================================

DB_FILE = "studybot.db"


def db():
    return sqlite3.connect(DB_FILE)


def init_db():
    conn = db()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            name TEXT,
            xp INTEGER DEFAULT 0,
            level INTEGER DEFAULT 1,
            questions INTEGER DEFAULT 0,
            correct INTEGER DEFAULT 0,
            streak INTEGER DEFAULT 0,
            last_day TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            subject TEXT,
            question TEXT,
            answer TEXT,
            created_at TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS favorites (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            question TEXT,
            answer TEXT,
            created_at TEXT
        )
    """)

    conn.commit()
    conn.close()


def create_user(user_id: int, name: str):
    conn = db()
    cur = conn.cursor()

    cur.execute(
        "SELECT user_id FROM users WHERE user_id = ?",
        (user_id,),
    )

    if not cur.fetchone():
        cur.execute(
            """
            INSERT INTO users
            (user_id, name, xp, level, questions, correct, streak, last_day)
            VALUES (?, ?, 0, 1, 0, 0, 0, '')
            """,
            (user_id, name),
        )

    conn.commit()
    conn.close()


def get_user(user_id: int):
    conn = db()
    cur = conn.cursor()

    cur.execute(
        "SELECT * FROM users WHERE user_id = ?",
        (user_id,),
    )

    row = cur.fetchone()

    conn.close()

    return row


def add_xp(user_id: int, amount: int):
    conn = db()
    cur = conn.cursor()

    cur.execute(
        """
        UPDATE users
        SET xp = xp + ?
        WHERE user_id = ?
        """,
        (amount, user_id),
    )

    cur.execute(
        "SELECT xp FROM users WHERE user_id = ?",
        (user_id,),
    )

    row = cur.fetchone()

    if row:
        xp = row[0]
        level = xp // 100 + 1

        cur.execute(
            """
            UPDATE users
            SET level = ?
            WHERE user_id = ?
            """,
            (level, user_id),
        )

    conn.commit()
    conn.close()


def register_question(user_id: int):
    conn = db()
    cur = conn.cursor()

    cur.execute(
        """
        UPDATE users
        SET questions = questions + 1
        WHERE user_id = ?
        """,
        (user_id,),
    )

    conn.commit()
    conn.close()


def register_correct(user_id: int):
    conn = db()
    cur = conn.cursor()

    cur.execute(
        """
        UPDATE users
        SET correct = correct + 1
        WHERE user_id = ?
        """,
        (user_id,),
    )

    conn.commit()
    conn.close()


def update_streak(user_id: int):
    today = date.today().isoformat()

    conn = db()
    cur = conn.cursor()

    cur.execute(
        "SELECT last_day, streak FROM users WHERE user_id = ?",
        (user_id,),
    )

    row = cur.fetchone()

    if not row:
        conn.close()
        return

    last_day, streak = row

    if last_day == today:
        conn.close()
        return

    if last_day:
        try:
            old = date.fromisoformat(last_day)
            diff = (date.today() - old).days

            if diff == 1:
                streak += 1
            else:
                streak = 1

        except Exception:
            streak = 1

    else:
        streak = 1

    cur.execute(
        """
        UPDATE users
        SET streak = ?, last_day = ?
        WHERE user_id = ?
        """,
        (streak, today, user_id),
    )

    conn.commit()
    conn.close()


def save_history(
    user_id: int,
    subject: str,
    question: str,
    answer: str,
):
    conn = db()
    cur = conn.cursor()

    cur.execute(
        """
        INSERT INTO history
        (user_id, subject, question, answer, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            user_id,
            subject,
            question,
            answer,
            datetime.now().isoformat(),
        ),
    )

    conn.commit()
    conn.close()


def save_favorite(
    user_id: int,
    question: str,
    answer: str,
):
    conn = db()
    cur = conn.cursor()

    cur.execute(
        """
        INSERT INTO favorites
        (user_id, question, answer, created_at)
        VALUES (?, ?, ?, ?)
        """,
        (
            user_id,
            question,
            answer,
            datetime.now().isoformat(),
        ),
    )

    conn.commit()
    conn.close()


def get_history(user_id: int, limit: int = 10):
    conn = db()
    cur = conn.cursor()

    cur.execute(
        """
        SELECT subject, question, created_at
        FROM history
        WHERE user_id = ?
        ORDER BY id DESC
        LIMIT ?
        """,
        (user_id, limit),
    )

    rows = cur.fetchall()

    conn.close()

    return rows


# =========================================================
# KEYBOARDS
# =========================================================

def main_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🤖 ИИ-помощник",
                    callback_data="ai",
                )
            ],
            [
                InlineKeyboardButton(
                    text="📚 Предметы",
                    callback_data="subjects",
                ),
                InlineKeyboardButton(
                    text="🧠 Тренировка",
                    callback_data="training",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="🧮 Калькулятор",
                    callback_data="calculator",
                ),
                InlineKeyboardButton(
                    text="🎯 Задание дня",
                    callback_data="daily",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="📊 Статистика",
                    callback_data="stats",
                ),
                InlineKeyboardButton(
                    text="📖 История",
                    callback_data="history",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="⭐ Избранное",
                    callback_data="favorites",
                ),
            ],
        ]
    )


def subjects_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🧮 Математика",
                    callback_data="math",
                ),
                InlineKeyboardButton(
                    text="⚛️ Физика",
                    callback_data="physics",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="🧪 Химия",
                    callback_data="chemistry",
                ),
                InlineKeyboardButton(
                    text="📖 История",
                    callback_data="history_subject",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="🇷🇺 Русский",
                    callback_data="russian",
                ),
                InlineKeyboardButton(
                    text="🇬🇧 Английский",
                    callback_data="english",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="🇧🇾 Белорусский",
                    callback_data="belarusian",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="⬅️ Назад",
                    callback_data="home",
                )
            ],
        ]
    )


def back_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="⬅️ Главное меню",
                    callback_data="home",
                )
            ]
        ]
    )


# =========================================================
# SUBJECT INFO
# =========================================================

SUBJECTS = {
    "math": (
        "🧮 <b>Математика</b>\n\n"
        "Могу помочь с:\n"
        "• алгеброй\n"
        "• геометрией\n"
        "• уравнениями\n"
        "• функциями\n"
        "• процентами\n"
        "• дробями\n"
        "• вероятностями\n\n"
        "Просто отправь задачу."
    ),

    "physics": (
        "⚛️ <b>Физика</b>\n\n"
        "Помогу разобраться с:\n"
        "• механикой\n"
        "• электричеством\n"
        "• оптикой\n"
        "• теплотой\n"
        "• давлением\n"
        "• энергией\n\n"
        "Отправь условие задачи."
    ),

    "chemistry": (
        "🧪 <b>Химия</b>\n\n"
        "Помогу с:\n"
        "• реакциями\n"
        "• формулами\n"
        "• уравнениями\n"
        "• молями\n"
        "• периодической системой\n"
        "• расчётами."
    ),

    "history_subject": (
        "📖 <b>История</b>\n\n"
        "Могу объяснить исторические события,\n"
        "даты, личности и причины событий."
    ),

    "russian": (
        "🇷🇺 <b>Русский язык</b>\n\n"
        "Помогу с:\n"
        "• орфографией\n"
        "• пунктуацией\n"
        "• грамматикой\n"
        "• сочинениями\n"
        "• разбором предложений."
    ),

    "english": (
        "🇬🇧 <b>Английский язык</b>\n\n"
        "Помогу с переводом,\n"
        "грамматикой, временами,\n"
        "словами и упражнениями."
    ),

    "belarusian": (
        "🇧🇾 <b>Белорусский язык</b>\n\n"
        "Могу помочь с грамматикой,\n"
        "переводом, правописанием\n"
        "и школьными заданиями."
    ),
}


# =========================================================
# SIMPLE AI WITHOUT EXTERNAL API
# =========================================================

def local_ai(question: str) -> str:

    q = question.lower().strip()

    if not q:
        return "Напиши вопрос."

    if "привет" in q:
        return (
            "👋 Привет!\n\n"
            "Я учебный помощник. "
            "Можешь отправить мне задачу по математике, "
            "физике, химии, истории или языкам."
        )

    if "кто ты" in q:
        return (
            "🤖 Я учебный бот.\n\n"
            "Моя задача — помочь тебе разобраться "
            "с учебным материалом и объяснить решение."
        )

    if "формула" in q and "скорост" in q:
        return (
            "⚡ Формула скорости:\n\n"
            "<code>v = s / t</code>\n\n"
            "где:\n"
            "v — скорость\n"
            "s — путь\n"
            "t — время"
        )

    if "площадь" in q and "круг" in q:
        return (
            "⭕ Площадь круга:\n\n"
            "<code>S = πr²</code>\n\n"
            "где r — радиус."
        )

    if "процент" in q:
        return (
            "📊 Чтобы найти процент от числа:\n\n"
            "<code>число × процент / 100</code>\n\n"
            "Например:\n"
            "20% от 500 = 500 × 20 / 100 = 100."
        )

    return (
        "🧠 <b>Разберём задачу</b>\n\n"
        f"<b>Твой вопрос:</b>\n{escape(question)}\n\n"
        "Сейчас я работаю в базовом режиме.\n\n"
        "Чтобы получить полноценное ИИ-объяснение, "
        "можно подключить AI_API_KEY в Railway.\n\n"
        "А пока я могу помочь через разделы "
        "«Предметы», «Тренировка» и «Калькулятор»."
    )


# =========================================================
# MATH CALCULATOR
# =========================================================

def safe_calculate(expression: str):

    expression = expression.replace(",", ".")

    allowed = "0123456789+-*/(). "

    if any(char not in allowed for char in expression):
        return None

    try:
        result = eval(
            expression,
            {
                "__builtins__": {}
            },
            {},
        )

        if isinstance(result, (int, float)):
            return result

    except Exception:
        return None

    return None


# =========================================================
# TRAINING
# =========================================================

TRAINING = {}


def generate_question():

    a = random.randint(2, 20)
    b = random.randint(2, 20)

    answer = a + b

    return (
        f"🧠 <b>Тренировка</b>\n\n"
        f"Сколько будет:\n\n"
        f"<b>{a} + {b}</b> ?"
    ), answer


# =========================================================
# DAILY
# =========================================================

DAILY_TASKS = [
    (
        "🧮 <b>Задание дня</b>\n\n"
        "Если 20% от числа равны 40, "
        "чему равно число?"
    ),
    (
        "⚛️ <b>Задание дня</b>\n\n"
        "Как называется сила, с которой "
        "тело притягивается к Земле?"
    ),
    (
        "📖 <b>Задание дня</b>\n\n"
        "Что такое историческое событие?"
    ),
    (
        "🇬🇧 <b>Задание дня</b>\n\n"
        "Переведи слово <b>school</b>."
    ),
]


# =========================================================
# BOT
# =========================================================

dp = Dispatcher()


# =========================================================
# START
# =========================================================

@dp.message(CommandStart())
async def start(message: Message):

    create_user(
        message.from_user.id,
        message.from_user.full_name,
    )

    update_streak(message.from_user.id)
    add_xp(message.from_user.id, 5)

    await message.answer(
        "🚀 <b>STUDY AI</b>\n\n"
        f"Привет, <b>{escape(message.from_user.first_name)}</b>!\n\n"
        "Я твой учебный помощник.\n\n"
        "📚 Решение задач\n"
        "🧠 Объяснение тем\n"
        "🎯 Тренировки\n"
        "📊 Статистика\n"
        "🏆 Уровни и XP\n"
        "📖 История запросов\n"
        "⭐ Избранное\n"
        "🧮 Калькулятор\n\n"
        "Выбирай действие:",
        reply_markup=main_keyboard(),
    )


# =========================================================
# HELP
# =========================================================

@dp.message(Command("help"))
async def help_command(message: Message):

    await message.answer(
        "ℹ️ <b>Помощь</b>\n\n"
        "/start — главное меню\n"
        "/help — помощь\n"
        "/stats — статистика\n"
        "/history — история\n"
        "/daily — задание дня\n\n"
        "Также можешь просто написать мне вопрос."
    )


# =========================================================
# STATS COMMAND
# =========================================================

@dp.message(Command("stats"))
async def stats_command(message: Message):

    user = get_user(message.from_user.id)

    if not user:
        create_user(
            message.from_user.id,
            message.from_user.full_name,
        )
        user = get_user(message.from_user.id)

    _, name, xp, level, questions, correct, streak, _ = user

    accuracy = 0

    if questions:
        accuracy = int(correct / questions * 100)

    await message.answer(
        "📊 <b>Твоя статистика</b>\n\n"
        f"👤 {escape(name)}\n"
        f"⭐ XP: <b>{xp}</b>\n"
        f"🏆 Уровень: <b>{level}</b>\n"
        f"📚 Запросов: <b>{questions}</b>\n"
        f"✅ Правильных: <b>{correct}</b>\n"
        f"🎯 Точность: <b>{accuracy}%</b>\n"
        f"🔥 Серия дней: <b>{streak}</b>",
        reply_markup=back_keyboard(),
    )


# =========================================================
# HISTORY COMMAND
# =========================================================

@dp.message(Command("history"))
async def history_command(message: Message):

    rows = get_history(
        message.from_user.id,
        10,
    )

    if not rows:
        await message.answer(
            "📖 История пока пустая.",
            reply_markup=back_keyboard(),
        )
        return

    text = "📖 <b>Последние запросы</b>\n\n"

    for i, row in enumerate(rows, 1):

        subject, question, created = row

        short = question[:100]

        text += (
            f"<b>{i}.</b> "
            f"{escape(subject)}\n"
            f"{escape(short)}\n\n"
        )

    await message.answer(
        text,
        reply_markup=back_keyboard(),
    )


# =========================================================
# DAILY COMMAND
# =========================================================

@dp.message(Command("daily"))
async def daily_command(message: Message):

    task = DAILY_TASKS[
        datetime.now().day % len(DAILY_TASKS)
    ]

    await message.answer(
        task,
        reply_markup=back_keyboard(),
    )


# =========================================================
# CALLBACKS
# =========================================================

@dp.callback_query(F.data == "home")
async def callback_home(callback: CallbackQuery):

    await callback.message.edit_text(
        "🏠 <b>Главное меню</b>\n\n"
        "Выбирай нужный раздел:",
        reply_markup=main_keyboard(),
    )

    await callback.answer()


@dp.callback_query(F.data == "subjects")
async def callback_subjects(callback: CallbackQuery):

    await callback.message.edit_text(
        "📚 <b>Предметы</b>\n\n"
        "Выбери предмет:",
        reply_markup=subjects_keyboard(),
    )

    await callback.answer()


@dp.callback_query(F.data.in_(SUBJECTS.keys()))
async def callback_subject(callback: CallbackQuery):

    subject = callback.data

    await callback.message.edit_text(
        SUBJECTS[subject],
        reply_markup=back_keyboard(),
    )

    await callback.answer()


@dp.callback_query(F.data == "stats")
async def callback_stats(callback: CallbackQuery):

    user = get_user(callback.from_user.id)

    if not user:
        create_user(
            callback.from_user.id,
            callback.from_user.full_name,
        )
        user = get_user(callback.from_user.id)

    _, name, xp, level, questions, correct, streak, _ = user

    accuracy = 0

    if questions:
        accuracy = int(correct / questions * 100)

    await callback.message.edit_text(
        "📊 <b>Статистика</b>\n\n"
        f"👤 {escape(name)}\n"
        f"⭐ XP: {xp}\n"
        f"🏆 Уровень: {level}\n"
        f"📚 Запросов: {questions}\n"
        f"✅ Правильных: {correct}\n"
        f"🎯 Точность: {accuracy}%\n"
        f"🔥 Серия: {streak} дней",
        reply_markup=back_keyboard(),
    )

    await callback.answer()


@dp.callback_query(F.data == "history")
async def callback_history(callback: CallbackQuery):

    rows = get_history(
        callback.from_user.id,
        10,
    )

    if not rows:

        await callback.message.edit_text(
            "📖 <b>История</b>\n\n"
            "Пока здесь ничего нет.",
            reply_markup=back_keyboard(),
        )

        await callback.answer()
        return

    text = "📖 <b>История запросов</b>\n\n"

    for i, row in enumerate(rows, 1):

        subject, question, created = row

        text += (
            f"<b>{i}.</b> "
            f"{escape(subject)}\n"
            f"{escape(question[:100])}\n\n"
        )

    await callback.message.edit_text(
        text,
        reply_markup=back_keyboard(),
    )

    await callback.answer()


@dp.callback_query(F.data == "favorites")
async def callback_favorites(callback: CallbackQuery):

    conn = db()
    cur = conn.cursor()

    cur.execute(
        """
        SELECT question, answer
        FROM favorites
        WHERE user_id = ?
        ORDER BY id DESC
        LIMIT 5
        """,
        (callback.from_user.id,),
    )

    rows = cur.fetchall()

    conn.close()

    if not rows:

        await callback.message.edit_text(
            "⭐ <b>Избранное</b>\n\n"
            "Здесь пока ничего нет.",
            reply_markup=back_keyboard(),
        )

        await callback.answer()
        return

    text = "⭐ <b>Избранное</b>\n\n"

    for i, (question, answer) in enumerate(rows, 1):

        text += (
            f"<b>{i}.</b> "
            f"{escape(question[:100])}\n\n"
        )

    await callback.message.edit_text(
        text,
        reply_markup=back_keyboard(),
    )

    await callback.answer()


@dp.callback_query(F.data == "calculator")
async def callback_calculator(callback: CallbackQuery):

    await callback.message.edit_text(
        "🧮 <b>Калькулятор</b>\n\n"
        "Напиши пример обычным сообщением.\n\n"
        "Например:\n"
        "<code>125 * 4 + 20</code>\n\n"
        "Поддерживаются:\n"
        "+  −  ×  ÷  ( )",
        reply_markup=back_keyboard(),
    )

    await callback.answer()


@dp.callback_query(F.data == "training")
async def callback_training(callback: CallbackQuery):

    question, answer = generate_question()

    TRAINING[callback.from_user.id] = answer

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Ответить",
                    callback_data="answer_training",
                )
            ],
            [
                InlineKeyboardButton(
                    text="🔄 Другое",
                    callback_data="training",
                )
            ],
            [
                InlineKeyboardButton(
                    text="⬅️ Назад",
                    callback_data="home",
                )
            ],
        ]
    )

    await callback.message.edit_text(
        question,
        reply_markup=keyboard,
    )

    await callback.answer()


@dp.callback_query(F.data == "answer_training")
async def callback_answer_training(
    callback: CallbackQuery,
):

    answer = TRAINING.get(
        callback.from_user.id
    )

    if answer is None:

        await callback.answer(
            "Сначала получи задание.",
            show_alert=True,
        )

        return

    await callback.message.edit_text(
        "✏️ <b>Напиши свой ответ числом.</b>",
        reply_markup=back_keyboard(),
    )

    await callback.answer()


@dp.callback_query(F.data == "daily")
async def callback_daily(callback: CallbackQuery):

    task = DAILY_TASKS[
        datetime.now().day % len(DAILY_TASKS)
    ]

    await callback.message.edit_text(
        task,
        reply_markup=back_keyboard(),
    )

    await callback.answer()


@dp.callback_query(F.data == "ai")
async def callback_ai(callback: CallbackQuery):

    await callback.message.edit_text(
        "🤖 <b>ИИ-помощник</b>\n\n"
        "Просто отправь мне сообщение.\n\n"
        "Например:\n"
        "• Реши 2x + 5 = 17\n"
        "• Объясни закон Ома\n"
        "• Что такое фотосинтез?\n"
        "• Переведи текст\n"
        "• Помоги написать сочинение",
        reply_markup=back_keyboard(),
    )

    await callback.answer()


# =========================================================
# TEXT HANDLER
# =========================================================

@dp.message(F.text)
async def text_handler(message: Message):

    user_id = message.from_user.id
    text = message.text.strip()

    create_user(
        user_id,
        message.from_user.full_name,
    )

    update_streak(user_id)

    # -----------------------------------------------------
    # TRAINING ANSWER
    # -----------------------------------------------------

    if user_id in TRAINING:

        expected = TRAINING[user_id]

        try:
            user_answer = float(
                text.replace(",", ".")
            )

            if user_answer == expected:

                register_question(user_id)
                register_correct(user_id)
                add_xp(user_id, 20)

                del TRAINING[user_id]

                await message.answer(
                    "🎉 <b>Правильно!</b>\n\n"
                    "Ты получил <b>+20 XP</b> ⭐",
                    reply_markup=main_keyboard(),
                )

                return

            else:

                register_question(user_id)
                add_xp(user_id, 5)

                del TRAINING[user_id]

                await message.answer(
                    f"❌ Неправильно.\n\n"
                    f"Правильный ответ: "
                    f"<b>{expected}</b>\n\n"
                    "Ты получил +5 XP за попытку.",
                    reply_markup=main_keyboard(),
                )

                return

        except ValueError:
            pass

    # -----------------------------------------------------
    # CALCULATOR
    # -----------------------------------------------------

    if any(
        symbol in text
        for symbol in ["+", "-", "*", "/"]
    ):

        result = safe_calculate(text)

        if result is not None:

            register_question(user_id)
            add_xp(user_id, 5)

            await message.answer(
                "🧮 <b>Ответ:</b>\n\n"
                f"<code>{escape(text)}</code>"
                f" = <b>{result}</b>\n\n"
                "+5 XP ⭐",
                reply_markup=main_keyboard(),
            )

            return

    # -----------------------------------------------------
    # AI / GENERAL
    # -----------------------------------------------------

    register_question(user_id)
    add_xp(user_id, 5)

    answer = local_ai(text)

    save_history(
        user_id,
        "AI",
        text,
        answer,
    )

    await message.answer(
        answer,
        reply_markup=main_keyboard(),
    )


# =========================================================
# UNKNOWN CONTENT
# =========================================================

@dp.message()
async def unknown_message(message: Message):

    await message.answer(
        "🤔 Я пока умею работать с текстовыми сообщениями.\n\n"
        "Напиши задачу или используй меню.",
        reply_markup=main_keyboard(),
    )


# =========================================================
# ERROR HANDLER
# =========================================================

@dp.errors()
async def global_error_handler(event):

    logger.exception(
        "Unhandled error: %s",
        event.exception,
    )

    try:
        if event.update.message:
            await event.update.message.answer(
                "⚠️ Произошла внутренняя ошибка.\n"
                "Попробуй ещё раз."
            )
    except Exception:
        pass

    return True


# =========================================================
# START BOT
# =========================================================

async def main():

    init_db()

    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(
            parse_mode=ParseMode.HTML,
        ),
    )

    logger.info("Starting STUDY AI...")

    try:

        await bot.delete_webhook(
            drop_pending_updates=True
        )

        await dp.start_polling(
            bot,
            allowed_updates=dp.resolve_used_update_types(),
        )

    finally:

        await bot.session.close()


if __name__ == "__main__":

    try:
        asyncio.run(main())

    except KeyboardInterrupt:

        logger.info(
            "Bot stopped by user."
        )
        