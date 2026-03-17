import requests
import logging

log = logging.getLogger(__name__)


class TelegramNotifier:
    def __init__(self, token: str, chat_id: str):
        self.token = token
        self.chat_id = chat_id
        self.base_url = f"https://api.telegram.org/bot{token}"


    def send(self, message: str) -> bool:
        try:
            resp = requests.post(
                f"{self.base_url}/sendMessage",
                json={
                    "chat_id": self.chat_id,
                    "text": message,
                    "parse_mode": "HTML"
                },
                timeout=10
            )
            if not resp.ok:
                log.warning(f"Telegram error: {resp.text}")
                return False
            return True
        except Exception as e:
            log.warning(f"Telegram send failed: {e}")
            return False
