import requests

# === НАСТРОЙКИ TELEGRAM ===
BOT_TOKEN = "8329968047:AAH72jgBWJz_-mVFVR7KeLok6VwL4zayumU"
CHAT_ID = "901637098"

# === ШАБЛОН СООБЩЕНИЯ ===
message = (
    "LONG открыт\n"
    "BTCUSDT @ 71 729,7\n"
    "Кол-во: 0.046\n"
    "SL: 63700.0 | TP: 67600.0\n"
    "Плечо: x10"
)


def send_screenshot_msg():
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": message
    }
    
    try:
        response = requests.post(url, json=payload)
        if response.status_code == 200:
            print("✨ Сообщение успешно отправлено! Можно скринить.")
        else:
            print(f"❌ Ошибка от Telegram: {response.text}")
    except Exception as e:
        print(f"❌ Не удалось отправить: {e}")

# Запуск
if __name__ == "__main__":
    send_screenshot_msg()