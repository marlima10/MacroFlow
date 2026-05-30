from pathlib import Path


APP_DIR = Path(__file__).resolve().parents[1]
MACROS_DIR = APP_DIR / "macros"
MACROS_DIR.mkdir(exist_ok=True)

