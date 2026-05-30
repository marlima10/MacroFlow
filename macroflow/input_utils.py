from pynput import keyboard


def key_to_data(key):
    if isinstance(key, keyboard.KeyCode):
        return {"kind": "char", "value": key.char}
    return {"kind": "special", "value": key.name}


def key_from_data(data):
    if data["kind"] == "char":
        return keyboard.KeyCode.from_char(data["value"])
    return getattr(keyboard.Key, data["value"])


def key_label(key):
    if isinstance(key, keyboard.KeyCode):
        return key.char or "tecla"
    return key.name.replace("_", " ").title()


def event_details(event):
    data = {key: value for key, value in event.items() if key not in ("t", "type")}
    import json

    return json.dumps(data, ensure_ascii=False)

