from abc import ABC, abstractmethod
from typing import Any


class LanguageRepository(ABC):
    @abstractmethod
    def load(self, language: str) -> dict[str, Any]:
        raise NotImplementedError
