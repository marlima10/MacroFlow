from pathlib import Path


APP_DIR = Path(__file__).resolve().parents[1]
MACROS_DIR = APP_DIR / "macros"
CONFIG_DIR = APP_DIR / "config"
LANGUAGE_DIR = APP_DIR / "language"
APP_CONFIG_FILE = CONFIG_DIR / "app.json"
ASSETS_DIR = APP_DIR / "assets"
APP_ICON_FILE = ASSETS_DIR / "macroflow.ico"
APP_ICON_PNG_FILE = ASSETS_DIR / "macroflow.png"
SHORTCUTS_FILE = APP_DIR / "shortcuts.json"
MACROS_DIR.mkdir(exist_ok=True)
CONFIG_DIR.mkdir(exist_ok=True)
LANGUAGE_DIR.mkdir(exist_ok=True)
ASSETS_DIR.mkdir(exist_ok=True)

DEFAULT_SHORTCUTS = {
    "play_playlist": "f6",
    "stop_playlist": "f7",
    "record": "f8",
    "play": "f9",
    "stop_playback": "f10",
    "close": "esc",
}

SHORTCUT_LABELS = {
    "play_playlist": "Executa playlist",
    "stop_playlist": "Para playlist",
    "record": "Grava/Para",
    "play": "Reproduz",
    "stop_playback": "Para reproducao",
    "close": "Fecha",
}
