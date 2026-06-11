import json
from pathlib import Path
from typing import Any

from macroflow.domain.repositories.config_repository import AppConfigRepository, FarmConfigRepository


DEFAULT_APP_CONFIG = {
    "language": "pt-br",
    "theme": "Dark",
    "start_with_windows": False,
    "farm_mode": False,
}

DEFAULT_FARM_POSITIONS = {
    "brand": {"cima": 0, "baixo": 0, "esquerda": 0, "direita": 0},
    "car": {"linha": 1, "coluna": 1},
    "last_car": {"linha": 1, "coluna": 1},
}

DEFAULT_FARM_CONFIG = {
    "interval_ms": 1000,
    "roulette_quantity": 1,
    "shutdown_on_finish": False,
    "positions": DEFAULT_FARM_POSITIONS,
    "macros": {},
}


class JsonAppConfigRepository(AppConfigRepository):
    def __init__(self, path: Path):
        self.path = path

    def load(self) -> dict[str, Any]:
        if not self.path.exists():
            self.save(DEFAULT_APP_CONFIG)
            return dict(DEFAULT_APP_CONFIG)
        try:
            saved_config = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            saved_config = {}
        if not isinstance(saved_config, dict):
            saved_config = {}
        return {**DEFAULT_APP_CONFIG, **saved_config}

    def save(self, config: dict[str, Any]) -> None:
        self.path.write_text(json.dumps(config, indent=2, ensure_ascii=False), encoding="utf-8")


class JsonFarmConfigRepository(FarmConfigRepository):
    def __init__(self, path: Path):
        self.path = path

    def load(self) -> dict[str, Any]:
        if not self.path.exists():
            return self.default_config()
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return self.default_config()
        if not isinstance(data, dict):
            return self.default_config()

        macros = data.get("macros")
        if not isinstance(macros, dict):
            macros = {}

        roulette_quantity = data.get("roulette_quantity", data.get("repeticoes", 1))
        if "roulette_quantity" not in data:
            for saved_macro in macros.values():
                if isinstance(saved_macro, dict) and "repeticoes" in saved_macro:
                    roulette_quantity = saved_macro.get("repeticoes", 1)
                    break

        positions = data.get("positions")
        if not isinstance(positions, dict):
            positions = {}
        merged_positions = {}
        for group, defaults in DEFAULT_FARM_POSITIONS.items():
            saved_group = positions.get(group, {})
            if not isinstance(saved_group, dict):
                saved_group = {}
            merged_positions[group] = {**defaults, **saved_group}

        return {
            "interval_ms": data.get("interval_ms", 1000),
            "roulette_quantity": roulette_quantity,
            "shutdown_on_finish": bool(data.get("shutdown_on_finish", False)),
            "positions": merged_positions,
            "macros": macros,
        }

    def save(self, config: dict[str, Any]) -> None:
        self.path.write_text(json.dumps(config, indent=2, ensure_ascii=False), encoding="utf-8")

    @staticmethod
    def default_config() -> dict[str, Any]:
        return {
            "interval_ms": 1000,
            "roulette_quantity": 1,
            "shutdown_on_finish": False,
            "positions": {group: dict(values) for group, values in DEFAULT_FARM_POSITIONS.items()},
            "macros": {},
        }
