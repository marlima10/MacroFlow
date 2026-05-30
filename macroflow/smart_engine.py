import threading
import time

from pynput.keyboard import Controller as KeyboardController
from pynput.keyboard import Key


class SmartMacroEngine:
    def __init__(self, status_callback):
        self.status_callback = status_callback
        self.keyboard = KeyboardController()
        self.stop_requested = threading.Event()
        self.running = False

    def dependency_status(self):
        modules = {
            "Pillow": "PIL",
            "OpenCV": "cv2",
            "pytesseract": "pytesseract",
        }
        status = {}
        for label, module in modules.items():
            try:
                __import__(module)
                status[label] = True
            except ImportError:
                status[label] = False
        return status

    def scan_screen(self, target_text):
        missing = [name for name, ok in self.dependency_status().items() if not ok]
        if missing:
            return {
                "ok": False,
                "message": "Dependencias ausentes: " + ", ".join(missing),
                "selected": None,
                "target": None,
            }

        image = self.capture_screen()
        selected = self.find_selected_card(image)
        target = self.find_target_text(image, target_text)
        if selected is None:
            return {"ok": False, "message": "Nao encontrei a borda verde de selecao.", "selected": None, "target": target}
        if target is None:
            return {"ok": False, "message": f"Nao encontrei o alvo: {target_text}", "selected": selected, "target": None}
        return {"ok": True, "message": "Selecao e alvo encontrados.", "selected": selected, "target": target}

    def start_navigation(self, target_text, max_steps=30, step_delay=0.35):
        if self.running:
            self.status_callback("Busca inteligente ja esta em execucao.")
            return
        self.stop_requested.clear()
        thread = threading.Thread(
            target=self._navigation_worker,
            args=(target_text, max_steps, step_delay),
            daemon=True,
        )
        thread.start()

    def stop_navigation(self):
        self.stop_requested.set()
        self.status_callback("Parando busca inteligente...")

    def _navigation_worker(self, target_text, max_steps, step_delay):
        self.running = True
        try:
            for step in range(max_steps):
                if self.stop_requested.is_set():
                    self.status_callback("Busca inteligente interrompida.")
                    return

                result = self.scan_screen(target_text)
                self.status_callback(result["message"])
                if not result["ok"]:
                    return

                selected = result["selected"]
                target = result["target"]
                if rectangles_overlap(selected, target):
                    self.status_callback(f"Alvo selecionado: {target_text}")
                    return

                direction = direction_to_target(selected, target)
                self.status_callback(f"Passo {step + 1}: seta {direction}")
                key = arrow_key(direction)
                self.keyboard.press(key)
                self.keyboard.release(key)
                time.sleep(step_delay)

            self.status_callback("Limite de passos atingido sem selecionar o alvo.")
        finally:
            self.running = False

    def capture_screen(self):
        from PIL import ImageGrab

        return ImageGrab.grab()

    def find_selected_card(self, image):
        import cv2
        import numpy as np

        frame = cv2.cvtColor(np.array(image), cv2.COLOR_RGB2BGR)
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        lower_green = np.array([35, 80, 80])
        upper_green = np.array([90, 255, 255])
        mask = cv2.inRange(hsv, lower_green, upper_green)
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        candidates = []
        for contour in contours:
            x, y, w, h = cv2.boundingRect(contour)
            area = w * h
            if 12000 <= area <= 180000 and w > 80 and h > 60:
                candidates.append((x, y, x + w, y + h))

        if not candidates:
            return None
        return max(candidates, key=rectangle_area)

    def find_target_text(self, image, target_text):
        import pytesseract

        data = pytesseract.image_to_data(image, output_type=pytesseract.Output.DICT, config="--psm 6")
        target = normalize_text(target_text)
        words = data.get("text", [])
        for index, word in enumerate(words):
            if target in normalize_text(word):
                x = data["left"][index]
                y = data["top"][index]
                w = data["width"][index]
                h = data["height"][index]
                return (x, y, x + w, y + h)

        joined = " ".join(words)
        if target not in normalize_text(joined):
            return None

        # Fallback: when OCR sees the phrase only across multiple words, use the
        # first matching word as a coarse target. Navigation still re-scans each step.
        first_piece = target.split()[0]
        for index, word in enumerate(words):
            if first_piece in normalize_text(word):
                x = data["left"][index]
                y = data["top"][index]
                w = data["width"][index]
                h = data["height"][index]
                return (x, y, x + w, y + h)
        return None


def normalize_text(value):
    return " ".join(str(value).upper().replace("-", " ").split())


def rectangle_area(rect):
    x1, y1, x2, y2 = rect
    return max(0, x2 - x1) * max(0, y2 - y1)


def rectangle_center(rect):
    x1, y1, x2, y2 = rect
    return ((x1 + x2) / 2, (y1 + y2) / 2)


def rectangles_overlap(a, b):
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    return ax1 <= bx2 and ax2 >= bx1 and ay1 <= by2 and ay2 >= by1


def direction_to_target(selected, target):
    sx, sy = rectangle_center(selected)
    tx, ty = rectangle_center(target)
    dx = tx - sx
    dy = ty - sy
    if abs(dx) >= abs(dy):
        return "right" if dx > 0 else "left"
    return "down" if dy > 0 else "up"


def arrow_key(direction):
    return {
        "right": Key.right,
        "left": Key.left,
        "down": Key.down,
        "up": Key.up,
    }[direction]
