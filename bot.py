import os
import time
import requests

TOKEN = os.environ["BOT_TOKEN"]
API = f"https://api.telegram.org/bot{TOKEN}/"

offset = 0

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

            message = update.get("message")

            if not message:
                continue

            chat_id = message["chat"]["id"]
            text = message.get("text", "")

            if text == "/start":
                answer = (
                    "Привет! 👋\n\n"
                    "Бот работает.\n"
                    "Напиши мне что-нибудь."
                )
            else:
                answer = f"Ты написал: {text}"

            requests.post(
                API + "sendMessage",
                data={
                    "chat_id": chat_id,
                    "text": answer
                }
            )

    except Exception as error:
        print("ERROR:", error)
        time.sleep(5)