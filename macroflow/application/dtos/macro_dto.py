from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class MacroDTO:
    path: Path
    data: dict[str, Any]
