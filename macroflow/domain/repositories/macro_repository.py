from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any


class MacroRepository(ABC):
    @abstractmethod
    def read(self, path: Path | None) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def save(self, path: Path, data: dict[str, Any]) -> None:
        raise NotImplementedError
