from dataclasses import dataclass


@dataclass(frozen=True)
class Shortcut:
    action: str
    key: str
