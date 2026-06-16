import json
import threading
import urllib.error
import urllib.parse
import urllib.request


class TelegramNotifier:
    def __init__(self, timeout=8):
        self.timeout = timeout

    def send_async(self, bot_token, chat_id, message, on_result=None):
        thread = threading.Thread(
            target=self._send_and_report,
            args=(bot_token, chat_id, message, on_result),
            daemon=True,
        )
        thread.start()

    def _send_and_report(self, bot_token, chat_id, message, on_result):
        try:
            self.send(bot_token, chat_id, message)
        except Exception as exc:
            if on_result:
                on_result(False, str(exc))
            return
        if on_result:
            on_result(True, "")

    def send(self, bot_token, chat_id, message):
        token = str(bot_token or "").strip()
        target_chat = str(chat_id or "").strip()
        text = str(message or "").strip()
        if not token:
            raise ValueError("Bot Token nao informado.")
        if not target_chat:
            raise ValueError("Chat ID nao informado.")
        if not text:
            raise ValueError("Mensagem vazia.")

        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = urllib.parse.urlencode({"chat_id": target_chat, "text": text}).encode("utf-8")
        request = urllib.request.Request(url, data=payload, method="POST")
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            body = response.read().decode("utf-8")
        try:
            result = json.loads(body)
        except json.JSONDecodeError as exc:
            raise RuntimeError("Resposta invalida do Telegram.") from exc
        if not result.get("ok"):
            description = result.get("description") or "Telegram retornou erro."
            raise RuntimeError(description)
        return result
