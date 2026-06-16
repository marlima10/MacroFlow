import sys
from pathlib import Path


APP_DIR = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parents[1]
MACROS_DIR = APP_DIR / "macros"
CONFIG_DIR = APP_DIR / "config"
LANGUAGE_DIR = APP_DIR / "language"
MANUAL_DIR = APP_DIR / "manual"
APP_CONFIG_FILE = CONFIG_DIR / "app.json"
FARM_CONFIG_FILE = CONFIG_DIR / "farm_subaru_impreza_22b.json"
TELEGRAM_CONFIG_FILE = CONFIG_DIR / "telegram.json"
ASSETS_DIR = APP_DIR / "assets"
ICON_DIR = APP_DIR / "icon"
IMAGE_DIR = APP_DIR / "imagem"
APP_ICON_FILE = ASSETS_DIR / "macroflow.ico"
APP_ICON_PNG_FILE = ASSETS_DIR / "macroflow.png"
FOLDER_ICON_FILE = ICON_DIR / "icone_pasta.png"
SPLASH_IMAGE_FILE = IMAGE_DIR / "splash.png"
SHORTCUTS_FILE = CONFIG_DIR / "shortcuts.json"
MACROS_DIR.mkdir(exist_ok=True)
CONFIG_DIR.mkdir(exist_ok=True)
LANGUAGE_DIR.mkdir(exist_ok=True)
MANUAL_DIR.mkdir(exist_ok=True)
ASSETS_DIR.mkdir(exist_ok=True)
ICON_DIR.mkdir(exist_ok=True)
IMAGE_DIR.mkdir(exist_ok=True)

DEFAULT_SHORTCUTS = {
    "play_playlist": "f6",
    "stop_playlist": "f7",
    "record": "f8",
    "play": "f9",
    "stop_playback": "f10",
    "close": "f2",
}

SHORTCUT_LABELS = {
    "play_playlist": "Executa playlist",
    "stop_playlist": "Para playlist",
    "record": "Grava/Para",
    "play": "Reproduz",
    "stop_playback": "Para reproducao",
    "close": "Fecha",
}
