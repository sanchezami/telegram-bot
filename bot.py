import asyncio
import logging
import os
import random
from datetime import datetime, timedelta

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)

# =========================================================
# НАСТРОЙКИ
# =========================================================

TOKEN = os.getenv("BOT_TOKEN")

# В Railway можно добавить:
# ADMIN_ID = твой Telegram ID
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

if not TOKEN:
    raise RuntimeError("Не найден BOT_TOKEN в переменных Railway")

bot = Bot(TOKEN)
dp = Dispatcher()

# Простая база прямо в памяти.
# Для первой версии этого достаточно.
users = {}

subjects = {
    "math": "📐 Математика",
    "physics": "⚡ Физика",
    "chemistry": "🧪 Химия",
    "history": "🏛 История",
    "english": "🇬🇧 Английский",
    "literature": "📚 Литература",
    "informatics": "💻 Информатика",
}

tests = {
    "math": [
        ("Сколько будет 7 × 8?", ["54", "56", "64", "48"], "56"),
        ("Сколько будет 100 ÷ 4?", ["20", "25", "30", "40"], "25"),
        ("Чему равен квадрат числа 9?", ["18", "72", "81", "99"], "81"),
    ],
    "physics": [
        ("Единица измерения силы?", ["Ватт", "Ньютон", "Джоуль", "Паскаль"], "Ньютон"),
        ("Скорость измеряется в:", ["кг", "Н", "м/с", "Дж"], "м/с"),
        ("Что притягивает тела к Земле?", ["Свет", "Гравитация", "Звук", "Трение"], "Гравитация"),
    ],
    "history": [
        ("Столица Древней Руси?", ["Киев", "Минск", "Москва", "Полоцк"], "Киев"),
        ("В каком году закончилась Вторая мировая война?", ["1943", "1944", "1945", "1946"], "1945"),
    ],
}


# =========================================================
# ПОЛЬЗОВАТЕЛИ
# =========================================================

def get_user(user_id: int):
    if user_id not in users:
        users[user_id] = {
            "requests": 0,
            "correct": 0,
            "tests": 0,
            "history": [],
            "referrals": 0,
            "referred_by": None,
            "reminders": [],
            "test": None,
        }

    return users[user_id]


# =========================================================
# ГЛАВНОЕ МЕНЮ
# =========================================================

def main_menu():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🤖 Помощник",
                    callback_data="assistant"
                ),
                InlineKeyboardButton(
                    text="📸 Задание по фото",
                    callback_data="photo_help"
                ),
            ],
            [
                InlineKeyboardButton(
                    text="📚 Предметы",
                    callback_data="subjects"
                ),
                InlineKeyboardButton(
                    text="🧠 Тесты",
                    callback_data="tests"
                ),
            ],
            [
                InlineKeyboardButton(
                    text="📊 Мой прогресс",
                    callback_data="profile"
                ),
                InlineKeyboardButton(
                    text="📂 История",
                    callback_data="history"
                ),
            ],
            [
                InlineKeyboardButton(
                    text="🎁 Пригласить друга",
                    callback_data="referral"
                ),
                InlineKeyboardButton(
                    text="⏰ Напоминание",
                    callback_data="reminder"
                ),
            ],
        ]
    )


def back_button():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="⬅️ Главное меню",
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

    user = get_user(message.from_user.id)

    args = message.text.split()

    # Реферальная ссылка
    if len(args) > 1:
        try:
            referrer = int(args[1])

            if (
                referrer != message.from_user.id
                and user["referred_by"] is None
            ):
                user["referred_by"] = referrer

                ref_user = get_user(referrer)
                ref_user["referrals"] += 1

        except ValueError:
            pass

    await message.answer(
        "👋 <b>Привет!</b>\n\n"
        "Я — учебный помощник.\n"
        "Могу помочь разобраться с заданиями, "
        "подготовиться к тесту и потренироваться.\n\n"
        "Выбирай нужный раздел 👇",
        reply_markup=main_menu(),
        parse_mode="HTML"
    )


# =========================================================
# ГЛАВНОЕ МЕНЮ
# =========================================================

@dp.callback_query(F.data == "home")
async def home(callback: CallbackQuery):

    await callback.message.edit_text(
        "🏠 <b>Главное меню</b>\n\n"
        "Что будем делать?",
        reply_markup=main_menu(),
        parse_mode="HTML"
    )

    await callback.answer()


# =========================================================
# ПОМОЩНИК
# =========================================================

@dp.callback_query(F.data == "assistant")
async def assistant(callback: CallbackQuery):

    await callback.message.edit_text(
        "🤖 <b>Учебный помощник</b>\n\n"
        "Напиши мне вопрос или задание.\n\n"
        "Например:\n"
        "• Реши 2x + 5 = 15\n"
        "• Объясни закон Ома\n"
        "• Сделай краткий пересказ текста\n"
        "• Помоги подготовиться к контрольной",
        reply_markup=back_button(),
        parse_mode="HTML"
    )

    await callback.answer()


# =========================================================
# СООБЩЕНИЯ ПОЛЬЗОВАТЕЛЯ
# =========================================================

@dp.message(F.text)
async def text_handler(message: Message):

    # Команды не обрабатываем здесь
    if message.text.startswith("/"):
        return

    user = get_user(message.from_user.id)

    user["requests"] += 1

    user["history"].append({
        "text": message.text,
        "date": datetime.now().strftime("%d.%m.%Y %H:%M")
    })

    # Если идёт тест
    if user["test"]:

        test = user["test"]

        answer_number = None

        try:
            answer_number = int(message.text.strip())
        except:
            pass

        if answer_number and 1 <= answer_number <= len(test["options"]):

            chosen = test["options"][answer_number - 1]

            if chosen == test["correct"]:
                user["correct"] += 1
                result = "✅ Правильно!"
            else:
                result = (
                    f"❌ Неправильно.\n"
                    f"Правильный ответ: <b>{test['correct']}</b>"
                )

            user["test"] = None
            user["tests"] += 1

            await message.answer(
                result,
                reply_markup=main_menu(),
                parse_mode="HTML"
            )

            return

    # Заглушка помощника
    # Здесь позже можно подключить AI API
    await message.answer(
        "🧠 <b>Получил задание.</b>\n\n"
        f"Твой запрос:\n<code>{message.text}</code>\n\n"
        "В этой версии я сохранил его в историю. "
        "AI-модуль можно подключить отдельно.",
        reply_markup=main_menu(),
        parse_mode="HTML"
    )


# =========================================================
# ФОТО
# =========================================================

@dp.callback_query(F.data == "photo_help")
async def photo_help(callback: CallbackQuery):

    await callback.message.edit_text(
        "📸 <b>Задание по фото</b>\n\n"
        "Отправь фотографию задания следующим сообщением.\n\n"
        "Например:\n"
        "📐 фотографию задачи\n"
        "📚 страницу учебника\n"
        "🧪 химическую реакцию",
        reply_markup=back_button(),
        parse_mode="HTML"
    )

    await callback.answer()


@dp.message(F.photo)
async def photo_handler(message: Message):

    user = get_user(message.from_user.id)

    user["requests"] += 1

    await message.answer(
        "📸 Фото получил.\n\n"
        "В полноценной версии здесь можно подключить "
        "распознавание изображения и AI, который разберёт "
        "задание по фотографии."
    )


# =========================================================
# ПРЕДМЕТЫ
# =========================================================

@dp.callback_query(F.data == "subjects")
async def subjects_menu(callback: CallbackQuery):

    buttons = []

    for key, name in subjects.items():
        buttons.append([
            InlineKeyboardButton(
                text=name,
                callback_data=f"subject:{key}"
            )
        ])

    buttons.append([
        InlineKeyboardButton(
            text="⬅️ Назад",
            callback_data="home"
        )
    ])

    await callback.message.edit_text(
        "📚 <b>Выбери предмет</b>",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=buttons
        ),
        parse_mode="HTML"
    )

    await callback.answer()


@dp.callback_query(F.data.startswith("subject:"))
async def subject_selected(callback: CallbackQuery):

    key = callback.data.split(":")[1]

    await callback.message.edit_text(
        f"{subjects[key]}\n\n"
        "Можешь отправить мне задание по этому предмету.",
        reply_markup=back_button()
    )

    await callback.answer()


# =========================================================
# ТЕСТЫ
# =========================================================

@dp.callback_query(F.data == "tests")
async def tests_menu(callback: CallbackQuery):

    buttons = []

    for key in tests:
        buttons.append([
            InlineKeyboardButton(
                text=subjects.get(key, key),
                callback_data=f"test:{key}"
            )
        ])

    buttons.append([
        InlineKeyboardButton(
            text="⬅️ Назад",
            callback_data="home"
        )
    ])

    await callback.message.edit_text(
        "🧠 <b>Тренировочные тесты</b>\n\n"
        "Выбери предмет:",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=buttons
        ),
        parse_mode="HTML"
    )

    await callback.answer()


@dp.callback_query(F.data.startswith("test:"))
async def start_test(callback: CallbackQuery):

    key = callback.data.split(":")[1]

    question = random.choice(tests[key])

    text, options, correct = question

    user = get_user(callback.from_user.id)

    user["test"] = {
        "subject": key,
        "question": text,
        "options": options,
        "correct": correct,
    }

    buttons = []

    for i, option in enumerate(options, 1):
        buttons.append([
            InlineKeyboardButton(
                text=f"{i}. {option}",
                callback_data=f"answer:{i}"
            )
        ])

    await callback.message.edit_text(
        f"🧠 <b>{subjects[key]}</b>\n\n"
        f"{text}",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=buttons
        ),
        parse_mode="HTML"
    )

    await callback.answer()


@dp.callback_query(F.data.startswith("answer:"))
async def answer_test(callback: CallbackQuery):

    user = get_user(callback.from_user.id)

    if not user["test"]:
        await callback.answer("Тест уже закончен")
        return

    number = int(callback.data.split(":")[1])

    test = user["test"]

    chosen = test["options"][number - 1]

    if chosen == test["correct"]:
        user["correct"] += 1

        text = "✅ <b>Правильно!</b>"
    else:
        text = (
            "❌ <b>Неправильно.</b>\n\n"
            f"Правильный ответ: {test['correct']}"
        )

    user["tests"] += 1
    user["test"] = None

    await callback.message.edit_text(
        text,
        reply_markup=main_menu(),
        parse_mode="HTML"
    )

    await callback.answer()


# =========================================================
# ПРОФИЛЬ
# =========================================================

@dp.callback_query(F.data == "profile")
async def profile(callback: CallbackQuery):

    user = get_user(callback.from_user.id)

    await callback.message.edit_text(
        "📊 <b>Твой прогресс</b>\n\n"
        f"📝 Запросов: <b>{user['requests']}</b>\n"
        f"🧠 Тестов: <b>{user['tests']}</b>\n"
        f"✅ Правильных ответов: <b>{user['correct']}</b>\n"
        f"👥 Приглашено друзей: <b>{user['referrals']}</b>",
        reply_markup=back_button(),
        parse_mode="HTML"
    )

    await callback.answer()


# =========================================================
# ИСТОРИЯ
# =========================================================

@dp.callback_query(F.data == "history")
async def history(callback: CallbackQuery):

    user = get_user(callback.from_user.id)

    history_items = user["history"][-5:]

    if not history_items:

        text = (
            "📂 <b>История</b>\n\n"
            "Здесь пока ничего нет."
        )

    else:

        text = "📂 <b>Последние запросы</b>\n\n"

        for item in reversed(history_items):
            text += (
                f"• {item['text'][:80]}\n"
                f"<i>{item['date']}</i>\n\n"
            )

    await callback.message.edit_text(
        text,
        reply_markup=back_button(),
        parse_mode="HTML"
    )

    await callback.answer()


# =========================================================
# РЕФЕРАЛЫ
# =========================================================

@dp.callback_query(F.data == "referral")
async def referral(callback: CallbackQuery):

    user = get_user(callback.from_user.id)

    link = (
        f"https://t.me/"
        f"{(await bot.get_me()).username}"
        f"?start={callback.from_user.id}"
    )

    await callback.message.edit_text(
        "🎁 <b>Пригласи друга</b>\n\n"
        "Отправь ему свою ссылку:\n\n"
        f"<code>{link}</code>\n\n"
        f"👥 Приглашено: <b>{user['referrals']}</b>",
        reply_markup=back_button(),
        parse_mode="HTML"
    )

    await callback.answer()


# =========================================================
# НАПОМИНАНИЕ
# =========================================================

@dp.callback_query(F.data == "reminder")
async def reminder(callback: CallbackQuery):

    await callback.message.edit_text(
        "⏰ <b>Напоминания</b>\n\n"
        "Напиши в чат, например:\n\n"
        "<code>напомни через 30 минут сделать математику</code>\n\n"
        "Или:\n"
        "<code>напомни через 2 часа подготовиться к контрольной</code>",
        reply_markup=back_button(),
        parse_mode="HTML"
    )

    await callback.answer()


# =========================================================
# АДМИН
# =========================================================

@dp.message(Command("stats"))
async def admin_stats(message: Message):

    if message.from_user.id != ADMIN_ID:
        return

    total_requests = sum(
        user["requests"]
        for user in users.values()
    )

    await message.answer(
        "👑 <b>Админ-панель</b>\n\n"
        f"👥 Пользователей: {len(users)}\n"
        f"📝 Запросов: {total_requests}",
        parse_mode="HTML"
    )


@dp.message(Command("users"))
async def admin_users(message: Message):

    if message.from_user.id != ADMIN_ID:
        return

    await message.answer(
        f"👥 Пользователей в памяти: {len(users)}"
    )


# =========================================================
# ЗАПУСК
# =========================================================

async def main():

    logging.basicConfig(level=logging.INFO)

    print("BOT STARTED")

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())