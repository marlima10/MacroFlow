import json
from pathlib import Path
from typing import Any

from macroflow.domain.repositories.language_repository import LanguageRepository


class JsonLanguageRepository(LanguageRepository):
    def __init__(self, language_dir: Path, fallback: str = "pt-br"):
        self.language_dir = language_dir
        self.fallback = fallback

    def load(self, language: str) -> dict[str, Any]:
        language_file = self.language_dir / f"{language}.json"
        fallback_file = self.language_dir / f"{self.fallback}.json"
        try:
            return json.loads(language_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return json.loads(fallback_file.read_text(encoding="utf-8"))
