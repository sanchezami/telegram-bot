import os
import time
import requests

TOKEN = os.environ["BOT_TOKEN"]
API = f"https://api.telegram.org/bot{TOKEN}/"

offset = 0

# Временное хранение данных пользователей
users = {}


def send_message(chat_id, text, keyboard=None):
    data = {
        "chat_id": chat_id,
        "text": text
    }

    if keyboard:
        data["reply_markup"] = keyboard

    requests.post(
        API + "sendMessage",
        json=data,
        timeout=20
    )


def main_menu():
    return {
        "keyboard": [
            [{"text": "🔧 Услуги"}, {"text": "💰 Цены"}],
            [{"text": "📅 Записаться"}, {"text": "📞 Контакты"}]
        ],
        "resize_keyboard": True
    }


def services_menu():
    return {
        "inline_keyboard": [
            [{"text": "🚗 Комплексная мойка", "callback_data": "wash"}],
            [{"text": "✨ Полировка", "callback_data": "polish"}],
            [{"text": "🛡 Керамика", "callback_data": "ceramic"}],
            [{"text": "🧼 Химчистка салона", "callback_data": "clean"}],
            [{"text": "💎 Детейлинг", "callback_data": "detail"}],
            [{"text": "⬅️ Назад", "callback_data": "back"}]
        ]
    }


def prices_menu():
    return {
        "inline_keyboard": [
            [{"text": "🚗 Мойка — от 35 BYN", "callback_data": "price_wash"}],
            [{"text": "✨ Полировка — от 150 BYN", "callback_data": "price_polish"}],
            [{"text": "🛡 Керамика — от 300 BYN", "callback_data": "price_ceramic"}],
            [{"text": "🧼 Химчистка — от 120 BYN", "callback_data": "price_clean"}],
            [{"text": "💎 Детейлинг — от 200 BYN", "callback_data": "price_detail"}],
            [{"text": "⬅️ Назад", "callback_data": "back"}]
        ]
    }


def start():
    global offset

    print("BOT STARTED")

    while True:

        try:

            response = requests.get(
                API + "getUpdates",
                params={
                    "offset": offset,
                    "timeout": 30
                },
                timeout=40
            )

            data = response.json()

            for update in data.get("result", []):

                offset = update["update_id"] + 1

                # =========================
                # CALLBACK BUTTON
                # =========================

                if "callback_query" in update:

                    callback = update["callback_query"]

                    chat_id = callback["message"]["chat"]["id"]
                    callback_id = callback["id"]
                    action = callback["data"]

                    requests.post(
                        API + "answerCallbackQuery",
                        json={
                            "callback_query_id": callback_id
                        }
                    )

                    if action == "back":

                        send_message(
                            chat_id,
                            "Главное меню 👇",
                            main_menu()
                        )

                    elif action == "wash":

                        send_message(
                            chat_id,
                            "🚗 Комплексная мойка\n\n"
                            "Профессиональная мойка кузова "
                            "и уход за автомобилем.\n\n"
                            "Стоимость — от 35 BYN."
                        )

                    elif action == "polish":

                        send_message(
                            chat_id,
                            "✨ Полировка кузова\n\n"
                            "Удаление мелких царапин, "
                            "восстановление блеска и глубины цвета.\n\n"
                            "Стоимость — от 150 BYN."
                        )

                    elif action == "ceramic":

                        send_message(
                            chat_id,
                            "🛡 Керамическое покрытие\n\n"
                            "Защита кузова от загрязнений, "
                            "воды и внешнего воздействия.\n\n"
                            "Стоимость — от 300 BYN."
                        )

                    elif action == "clean":

                        send_message(
                            chat_id,
                            "🧼 Химчистка салона\n\n"
                            "Глубокая очистка салона "
                            "и удаление загрязнений.\n\n"
                            "Стоимость — от 120 BYN."
                        )

                    elif action == "detail":

                        send_message(
                            chat_id,
                            "💎 Детейлинг\n\n"
                            "Комплексный уход за автомобилем "
                            "с обработкой всех основных элементов.\n\n"
                            "Стоимость — от 200 BYN."
                        )

                    continue

                # =========================
                # MESSAGE
                # =========================

                message = update.get("message")

                if not message:
                    continue

                chat_id = message["chat"]["id"]
                text = message.get("text", "")

                # START

                if text == "/start":

                    send_message(
                        chat_id,
                        "👋 Добро пожаловать!\n\n"
                        "Здесь можно посмотреть услуги, "
                        "цены и записаться.",
                        main_menu()
                    )

                # SERVICES

                elif text == "🔧 Услуги":

                    send_message(
                        chat_id,
                        "Выберите услугу:",
                        services_menu()
                    )

                # PRICES

                elif text == "💰 Цены":

                    send_message(
                        chat_id,
                        "💰 Наши цены:",
                        prices_menu()
                    )

                # CONTACTS

                elif text == "📞 Контакты":

                    send_message(
                        chat_id,
                        "📞 Связаться с нами\n\n"
                        "Telegram: @oguzok3351\n\n"
                        "Напишите нам, чтобы узнать "
                        "свободные даты и стоимость."
                    )

                # BOOKING

                elif text == "📅 Записаться":

                    users[chat_id] = {
                        "step": "name"
                    }

                    send_message(
                        chat_id,
                        "📅 Запись\n\n"
                        "Как вас зовут?"
                    )

                # BOOKING NAME

                elif chat_id in users and users[chat_id]["step"] == "name":

                    users[chat_id]["name"] = text
                    users[chat_id]["step"] = "phone"

                    send_message(
                        chat_id,
                        "Отлично 👍\n\n"
                        "Теперь отправьте номер телефона."
                    )

                # BOOKING PHONE

                elif chat_id in users and users[chat_id]["step"] == "phone":

                    users[chat_id]["phone"] = text

                    name = users[chat_id]["name"]
                    phone = users[chat_id]["phone"]

                    del users[chat_id]

                    send_message(
                        chat_id,
                        "✅ Заявка принята!\n\n"
                        f"Имя: {name}\n"
                        f"Телефон: {phone}\n\n"
                        "Мы свяжемся с вами в ближайшее время."
                    )

                else:

                    send_message(
                        chat_id,
                        "Выберите действие в меню 👇",
                        main_menu()
                    )

        except Exception as error:

            print("ERROR:", error)

            time.sleep(5)


start()