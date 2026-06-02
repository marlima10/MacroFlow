from pynput import keyboard


def key_to_data(key):
    if isinstance(key, keyboard.KeyCode):
        return {"kind": "char", "value": key.char}
    return {"kind": "special", "value": key.name}


def key_from_data(data):
    if data["kind"] == "char":
        return keyboard.KeyCode.from_char(data["value"])
    value = data["value"]
    if hasattr(keyboard.Key, value):
        return getattr(keyboard.Key, value)
    if isinstance(value, str) and len(value) == 1:
        return keyboard.KeyCode.from_char(value)
    raise AttributeError(f"Tecla especial desconhecida: {value}")


def key_label(key):
    if isinstance(key, keyboard.KeyCode):
        return key.char or "tecla"
    return key.name.replace("_", " ").title()


def key_to_shortcut(key):
    if isinstance(key, keyboard.KeyCode):
        return (key.char or "").lower()
    return key.name.lower()


def normalize_shortcut(value):
    return value.strip().lower().replace(" ", "_")


def is_valid_shortcut(value):
    normalized = normalize_shortcut(value)
    if len(normalized) == 1:
        return normalized.isalnum()
    if normalized.startswith("f") and normalized[1:].isdigit():
        number = int(normalized[1:])
        return 1 <= number <= 24
    return normalized in {
        "esc",
        "enter",
        "space",
        "tab",
        "shift",
        "shift_l",
        "shift_r",
        "ctrl",
        "ctrl_l",
        "ctrl_r",
        "alt",
        "alt_l",
        "alt_r",
        "backspace",
        "delete",
        "insert",
        "home",
        "end",
        "page_up",
        "page_down",
        "up",
        "down",
        "left",
        "right",
    }


def shortcut_label(value):
    normalized = normalize_shortcut(value)
    names = {
        "esc": "Esc",
        "enter": "Enter",
        "space": "Space",
        "tab": "Tab",
        "shift": "Shift",
        "ctrl": "Ctrl",
        "alt": "Alt",
    }
    if normalized.startswith("f") and normalized[1:].isdigit():
        return normalized.upper()
    return names.get(normalized, normalized.replace("_", " ").title())


def event_details(event):
    data = {key: value for key, value in event.items() if key not in ("t", "type")}
    import json

    return json.dumps(data, ensure_ascii=False)
