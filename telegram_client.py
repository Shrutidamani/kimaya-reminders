import requests

class TelegramClient:
    def __init__(self, token=None, chat_id=None):
        self.token = token
        self.chat_id = chat_id

    def is_configured(self):
        return bool(self.token and self.chat_id)

    def send_message(self, text, parse_mode="HTML"):
        """Send a message to the configured Telegram chat."""
        if not self.is_configured():
            print("Telegram client is not fully configured with token and chat ID.")
            return False, "Not Configured"
            
        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": parse_mode
        }
        try:
            response = requests.post(url, json=payload, timeout=10)
            result = response.json()
            if response.status_code == 200 and result.get("ok"):
                return True, "Success"
            else:
                error_msg = result.get("description", "Unknown error")
                print(f"Telegram API Error: {error_msg}")
                return False, error_msg
        except Exception as e:
            print(f"Telegram Connection Error: {e}")
            return False, str(e)

    def test_connection(self):
        """Send a simple handshake test message to check credentials."""
        test_msg = "<b>🤖 Kimaya Reminders Bot</b>\n\nConnection successful! This bot is now configured to send payment reminders."
        return self.send_message(test_msg)
