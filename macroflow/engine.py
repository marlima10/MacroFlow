import math
import threading
import time

from pynput import keyboard
from pynput.keyboard import Controller as KeyboardController
from pynput.mouse import Button, Controller as MouseController

from .input_utils import key_from_data, key_label, key_to_data


CONTROL_KEYS = {
    keyboard.Key.f8,
    keyboard.Key.f9,
    keyboard.Key.esc,
}


class MacroEngine:
    def __init__(self, ui_queue):
        self.events = []
        self.recording = False
        self.playing = False
        self.started_at = 0.0
        self.last_mouse_move = None
        self.ui_queue = ui_queue
        self.keyboard_controller = KeyboardController()
        self.mouse_controller = MouseController()

    def start_recording(self):
        if self.playing:
            self.notify("Pare a reproducao antes de gravar.")
            return

        self.events = []
        self.recording = True
        self.started_at = time.perf_counter()
        self.last_mouse_move = None
        self.ui_queue.put(("recording_started", None))
        self.notify("Gravando... pressione F8 para parar.")

    def stop_recording(self):
        if not self.recording:
            return

        self.recording = False
        self.ui_queue.put(("recording_stopped", None))
        self.notify(f"Gravacao parada. {len(self.events)} eventos capturados.")
        self.ui_queue.put(("events_changed", list(self.events)))

    def play_events(self, events):
        if self.recording:
            self.notify("Pare a gravacao antes de reproduzir.")
            return
        if self.playing:
            self.notify("Uma macro ja esta em reproducao.")
            return
        if not events:
            self.notify("Nao ha eventos para reproduzir.")
            return

        thread = threading.Thread(target=self._play_worker, args=(events,), daemon=True)
        thread.start()

    def timestamp(self):
        return round(time.perf_counter() - self.started_at, 4)

    def add_event(self, event):
        if not self.recording:
            return

        event["t"] = self.timestamp()
        self.events.append(event)
        self.ui_queue.put(("event_added", list(self.events)))

    def _play_worker(self, events):
        self.playing = True
        self.ui_queue.put(("playing", True))
        self.notify("Reproduzindo em 3 segundos. Coloque a janela alvo em foco.")
        time.sleep(3)

        previous_t = 0.0
        try:
            for event in events:
                delay = max(0, float(event.get("t", 0)) - previous_t)
                time.sleep(delay)
                previous_t = float(event.get("t", 0))
                self.run_event(event)
        except Exception as exc:
            self.notify(f"Erro na reproducao: {exc}")
        finally:
            self.playing = False
            self.ui_queue.put(("playing", False))
            self.notify("Reproducao finalizada.")

    def run_event(self, event):
        event_type = event["type"]

        if event_type == "mouse_move":
            self.mouse_controller.position = (int(event["x"]), int(event["y"]))
        elif event_type == "mouse_click":
            self._run_mouse_click(event)
        elif event_type == "mouse_scroll":
            self.mouse_controller.scroll(int(event["dx"]), int(event["dy"]))
        elif event_type == "key":
            self._run_key(event)

    def on_mouse_move(self, x, y):
        if not self.recording:
            return

        now = self.timestamp()
        if self._should_skip_mouse_move(now, x, y):
            return

        self.last_mouse_move = (now, x, y)
        self.events.append({"type": "mouse_move", "t": now, "x": x, "y": y})

    def on_mouse_click(self, x, y, button, pressed):
        if self.recording:
            state = "pressionado" if pressed else "solto"
            self.ui_queue.put(("input_down" if pressed else "input_up", f"Mouse {button.name}"))
            self.ui_queue.put(("live_action", f"Mouse {button.name} {state} em {x}, {y}"))

        self.add_event(
            {
                "type": "mouse_click",
                "x": x,
                "y": y,
                "button": button.name,
                "pressed": pressed,
            }
        )

    def on_mouse_scroll(self, x, y, dx, dy):
        if self.recording:
            self.ui_queue.put(("live_action", f"Scroll dx={dx}, dy={dy} em {x}, {y}"))
        self.add_event({"type": "mouse_scroll", "x": x, "y": y, "dx": dx, "dy": dy})

    def on_key_press(self, key):
        if self._handle_control_key(key):
            return

        if self.recording and key not in CONTROL_KEYS:
            label = key_label(key)
            self.ui_queue.put(("input_down", label))
            self.ui_queue.put(("live_action", f"Tecla {label} pressionada"))
            self.add_event({"type": "key", "key": key_to_data(key), "pressed": True})

    def on_key_release(self, key):
        if self.recording and key not in CONTROL_KEYS:
            label = key_label(key)
            self.ui_queue.put(("input_up", label))
            self.ui_queue.put(("live_action", f"Tecla {label} solta"))
            self.add_event({"type": "key", "key": key_to_data(key), "pressed": False})

    def notify(self, text):
        self.ui_queue.put(("status", text))

    def _handle_control_key(self, key):
        if key == keyboard.Key.f8:
            if self.recording:
                self.stop_recording()
            else:
                self.start_recording()
            return True
        if key == keyboard.Key.f9:
            self.ui_queue.put(("play_shortcut", None))
            return True
        if key == keyboard.Key.esc:
            self.ui_queue.put(("escape", None))
            return True
        return False

    def _should_skip_mouse_move(self, now, x, y):
        if self.last_mouse_move is None:
            return False

        last_t, last_x, last_y = self.last_mouse_move
        distance = math.hypot(x - last_x, y - last_y)
        return now - last_t < 0.03 and distance < 8

    def _run_mouse_click(self, event):
        button = getattr(Button, event["button"])
        if event["pressed"]:
            self.mouse_controller.press(button)
        else:
            self.mouse_controller.release(button)

    def _run_key(self, event):
        key = key_from_data(event["key"])
        if event["pressed"]:
            self.keyboard_controller.press(key)
        else:
            self.keyboard_controller.release(key)

