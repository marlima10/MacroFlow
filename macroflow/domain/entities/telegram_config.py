from dataclasses import dataclass


@dataclass(frozen=True)
class TelegramConfig:
    enabled: bool = False
    bot_token: str = ""
    chat_id: str = ""
    notify_farm_started: bool = True
    notify_macro_started: bool = True
    notify_errors: bool = True
    notify_farm_finished: bool = True
    notify_farm_stopped: bool = True

    @classmethod
    def from_dict(cls, data):
        if not isinstance(data, dict):
            data = {}
        return cls(
            enabled=bool(data.get("enabled", False)),
            bot_token=str(data.get("bot_token", "")),
            chat_id=str(data.get("chat_id", "")),
            notify_farm_started=bool(data.get("notify_farm_started", True)),
            notify_macro_started=bool(data.get("notify_macro_started", True)),
            notify_errors=bool(data.get("notify_errors", True)),
            notify_farm_finished=bool(data.get("notify_farm_finished", True)),
            notify_farm_stopped=bool(data.get("notify_farm_stopped", True)),
        )

    def to_dict(self):
        return {
            "enabled": self.enabled,
            "bot_token": self.bot_token,
            "chat_id": self.chat_id,
            "notify_farm_started": self.notify_farm_started,
            "notify_macro_started": self.notify_macro_started,
            "notify_errors": self.notify_errors,
            "notify_farm_finished": self.notify_farm_finished,
            "notify_farm_stopped": self.notify_farm_stopped,
        }
