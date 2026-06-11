from abc import ABC, abstractmethod


class ShortcutRepository(ABC):
    @abstractmethod
    def load(self) -> dict[str, str]:
        raise NotImplementedError

    @abstractmethod
    def save(self, shortcuts: dict[str, str]) -> None:
        raise NotImplementedError
