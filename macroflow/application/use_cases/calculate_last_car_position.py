from macroflow.domain.value_objects.matrix_position import MatrixPosition
from macroflow.engine import matrix_target_for_repeat


class CalculateLastCarPosition:
    def execute(self, start: MatrixPosition, repeats: int) -> MatrixPosition:
        start.validate()
        if repeats < 1:
            raise ValueError("A quantidade de repeticoes deve ser maior que zero.")
        target = matrix_target_for_repeat(
            {"target_row": start.linha, "target_column": start.coluna},
            repeats - 1,
        )
        return MatrixPosition(linha=target["target_row"], coluna=target["target_column"])
