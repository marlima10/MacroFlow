from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class FarmItem:
    path: Path
    name: str
    ordem: int
    macro_data: dict[str, Any]
    ignored: bool = False
