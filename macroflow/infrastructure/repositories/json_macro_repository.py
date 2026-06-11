import json
from pathlib import Path
from typing import Any

from macroflow.domain.repositories.macro_repository import MacroRepository


class JsonMacroRepository(MacroRepository):
    def read(self, path: Path | None) -> dict[str, Any]:
        if path is None:
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return data if isinstance(data, dict) else {}

    def save(self, path: Path, data: dict[str, Any]) -> None:
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
