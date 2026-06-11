from dataclasses import dataclass, field
from typing import Any


DEFAULT_MACRO_COLOR = "#07111f"


@dataclass(frozen=True)
class MacroMetadata:
    ordem: int | None = None
    possicaoMarca: bool = False
    posicaoCarro: bool = False
    posicaoUltimoCarro: bool = False
    ativarRepeticao: bool = False
    maestria: bool = False
    manual: str = ""
    cor: str = DEFAULT_MACRO_COLOR


@dataclass(frozen=True)
class Macro:
    name: str
    events: list[dict[str, Any]] = field(default_factory=list)
    metadata: MacroMetadata = field(default_factory=MacroMetadata)
    version: int = 1
    updated_at: str = ""

    @property
    def display_name(self) -> str:
        if self.metadata.ordem is None:
            return self.name
        return f"[{self.metadata.ordem}] {self.name}"
