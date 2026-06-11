from abc import ABC, abstractmethod
from typing import Any


class AppConfigRepository(ABC):
    @abstractmethod
    def load(self) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def save(self, config: dict[str, Any]) -> None:
        raise NotImplementedError


class FarmConfigRepository(ABC):
    @abstractmethod
    def load(self) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def save(self, config: dict[str, Any]) -> None:
        raise NotImplementedError
