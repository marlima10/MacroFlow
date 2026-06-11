import json
from pathlib import Path

from macroflow.domain.repositories.shortcut_repository import ShortcutRepository
from macroflow.input_utils import is_valid_shortcut, normalize_shortcut


class JsonShortcutRepository(ShortcutRepository):
    def __init__(self, path: Path, defaults: dict[str, str]):
        self.path = path
        self.defaults = defaults

    def load(self) -> dict[str, str]:
        if not self.path.exists():
            return dict(self.defaults)
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return dict(self.defaults)

        shortcuts = dict(self.defaults)
        for action in shortcuts:
            if action in data:
                shortcuts[action] = normalize_shortcut(str(data[action]))
        if shortcuts.get("close") == "esc":
            shortcuts["close"] = self.defaults["close"]
        values = list(shortcuts.values())
        if any(not is_valid_shortcut(value) for value in values) or len(set(values)) != len(values):
            return dict(self.defaults)
        return shortcuts

    def save(self, shortcuts: dict[str, str]) -> None:
        self.path.write_text(json.dumps(shortcuts, indent=2), encoding="utf-8")
