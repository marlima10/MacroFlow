from pathlib import Path
from typing import Any

from macroflow.domain.repositories.macro_repository import MacroRepository


class SaveMacro:
    def __init__(self, repository: MacroRepository):
        self.repository = repository

    def execute(self, path: Path, data: dict[str, Any]) -> None:
        self.repository.save(path, data)
