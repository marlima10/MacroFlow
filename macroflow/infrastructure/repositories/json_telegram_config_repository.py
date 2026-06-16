import json
from pathlib import Path

from macroflow.domain.entities.telegram_config import TelegramConfig


class JsonTelegramConfigRepository:
    def __init__(self, path: Path):
        self.path = path

    def load(self) -> TelegramConfig:
        if not self.path.exists():
            config = TelegramConfig()
            self.save(config)
            return config
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            data = {}
        return TelegramConfig.from_dict(data)

    def save(self, config: TelegramConfig) -> None:
        self.path.write_text(json.dumps(config.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
