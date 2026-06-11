from dataclasses import dataclass


@dataclass(frozen=True)
class MatrixPosition:
    linha: int
    coluna: int

    def validate(self) -> None:
        if self.linha < 1 or self.linha > 3:
            raise ValueError("A linha deve estar entre 1 e 3.")
        if self.coluna < 1:
            raise ValueError("A coluna deve ser maior ou igual a 1.")
