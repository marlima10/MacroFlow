import math
import threading
import time

from pynput.keyboard import Controller as KeyboardController
from pynput.mouse import Button, Controller as MouseController

from .constants import DEFAULT_SHORTCUTS
from .input_utils import key_from_data, key_label, key_to_data, key_to_shortcut, shortcut_label


MATRIX_ROW_LIMIT = 3
DEFAULT_MATRIX_STEP_DELAY = 0.3


class MacroEngine:
    def __init__(self, ui_queue, shortcuts=None):
        self.events = []
        self.recording = False
        self.recording_pending = False
        self.playing = False
        self.started_at = 0.0
        self.last_mouse_move = None
        self.active_keys = {}
        self.ui_queue = ui_queue
        self.shortcuts = dict(shortcuts or DEFAULT_SHORTCUTS)
        self.stop_playback_requested = threading.Event()
        self.keyboard_controller = KeyboardController()
        self.mouse_controller = MouseController()

    def set_shortcuts(self, shortcuts):
        self.shortcuts = dict(shortcuts)

    def start_recording(self):
        if self.playing:
            self.notify("Pare a reproducao antes de gravar.")
            return
        if self.recording_pending:
            self.notify("A gravacao ja esta em contagem regressiva.")
            return

        self.recording_pending = True
        self.events = []
        thread = threading.Thread(target=self._recording_countdown_worker, daemon=True)
        thread.start()

    def _recording_countdown_worker(self):
        for remaining in (3, 2, 1):
            if not self.recording_pending:
                return
            self.ui_queue.put(("recording_countdown", remaining))
            self.notify(f"Gravacao comeca em {remaining}...")
            time.sleep(1)

        if not self.recording_pending:
            return

        self.recording_pending = False
        self.recording = True
        self.started_at = time.perf_counter()
        self.last_mouse_move = None
        self.active_keys = {}
        self.ui_queue.put(("recording_started", None))
        self.notify(f"Gravando... pressione {shortcut_label(self.shortcuts['record'])} para parar.")

    def stop_recording(self):
        if self.recording_pending:
            self.recording_pending = False
            self.ui_queue.put(("recording_stopped", None))
            self.notify("Contagem de gravacao cancelada.")
            return
        if not self.recording:
            return

        self.flush_active_keys()
        self.recording = False
        self.ui_queue.put(("recording_stopped", None))
        self.notify(f"Gravacao parada. {len(self.events)} eventos capturados.")
        self.ui_queue.put(("events_changed", list(self.events)))

    def play_events(self, events, loop=False):
        if self.recording:
            self.notify("Pare a gravacao antes de reproduzir.")
            return
        if self.playing:
            self.notify("Uma macro ja esta em reproducao.")
            return
        if not events:
            self.notify("Nao ha eventos para reproduzir.")
            return

        events = normalize_playback_events(events)
        self.stop_playback_requested.clear()
        thread = threading.Thread(target=self._play_worker, args=(events, loop), daemon=True)
        thread.start()

    def play_playlist(self, items, repeats):
        if self.recording:
            self.notify("Pare a gravacao antes de reproduzir.")
            return
        if self.playing:
            self.notify("Uma macro ja esta em reproducao.")
            return
        if not items:
            self.notify("Nao ha macros na playlist.")
            return

        normalized_items = []
        for item in items:
            if is_matrix_navigation_item(item):
                normalized_items.append(
                    {
                        "name": item.get("name", "Macro"),
                        "kind": "matrix_navigation",
                        "matrix": dict(item.get("matrix", {})),
                    }
                )
                continue
            events = normalize_playback_events(item.get("events", []))
            if events:
                normalized_items.append({"name": item.get("name", "Macro"), "events": events})
        if not normalized_items:
            self.notify("Nao ha eventos para reproduzir.")
            return

        self.stop_playback_requested.clear()
        thread = threading.Thread(target=self._playlist_worker, args=(normalized_items, repeats), daemon=True)
        thread.start()

    def stop_playback(self):
        if not self.playing:
            self.notify("Nenhuma reproducao em andamento.")
            return

        self.stop_playback_requested.set()
        self.notify("Parando reproducao...")

    def timestamp(self):
        return round(time.perf_counter() - self.started_at, 4)

    def add_event(self, event):
        if not self.recording:
            return

        event["t"] = self.timestamp()
        self.events.append(event)
        self.ui_queue.put(("event_added", list(self.events)))

    def _play_worker(self, events, loop):
        self.playing = True
        self.ui_queue.put(("playing", True))
        self.notify("Reproduzindo em loop..." if loop else "Reproduzindo...")

        finish_message = "Reproducao finalizada."
        try:
            while True:
                playback_started_at = time.perf_counter()
                for event in events:
                    elapsed = time.perf_counter() - playback_started_at
                    delay = max(0, float(event.get("t", 0)) - elapsed)
                    if self.stop_playback_requested.wait(delay):
                        finish_message = "Reproducao interrompida."
                        return
                    self.run_event(event)
                if not loop:
                    return
                self.notify("Loop concluido. Reiniciando macro...")
        except Exception as exc:
            finish_message = f"Erro na reproducao: {exc}"
        finally:
            self._finish_playback(finish_message)

    def _playlist_worker(self, items, repeats):
        self.playing = True
        self.ui_queue.put(("playing", True))
        self.notify(f"Executando playlist {repeats} vez(es)...")

        finish_message = "Playlist finalizada."
        try:
            for repeat_index in range(repeats):
                self.ui_queue.put(("playlist_progress", (repeat_index + 1, repeats)))
                for item in items:
                    if self.stop_playback_requested.is_set():
                        finish_message = "Playlist interrompida."
                        return
                    play_item = resolve_playlist_item_for_repeat(item, repeat_index)
                    self.ui_queue.put(("playlist_current", play_item["name"]))
                    self.notify(f"Playlist {repeat_index + 1}/{repeats}: {play_item['name']}")
                    self._run_timed_events(play_item["events"])
        except Exception as exc:
            finish_message = f"Erro na playlist: {exc}"
        finally:
            self._finish_playback(finish_message)

    def _run_timed_events(self, events):
        playback_started_at = time.perf_counter()
        for event in events:
            elapsed = time.perf_counter() - playback_started_at
            delay = max(0, float(event.get("t", 0)) - elapsed)
            if self.stop_playback_requested.wait(delay):
                return
            self.run_event(event)

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
        elif event_type == "key_hold":
            self._run_key_hold(event)

    def on_mouse_move(self, x, y):
        if not self.recording:
            return

        now = self.timestamp()
        if self._should_skip_mouse_move(now, x, y):
            return

        self.last_mouse_move = (now, x, y)
        self.events.append({"type": "mouse_move", "t": now, "x": x, "y": y})
        self.ui_queue.put(("event_added", list(self.events)))

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

        if self.recording and not self._is_control_shortcut(key):
            key_id = key_event_id(key_to_data(key))
            if key_id in self.active_keys:
                return
            label = key_label(key)
            self.active_keys[key_id] = {
                "key": key_to_data(key),
                "t": self.timestamp(),
                "label": label,
            }
            self.ui_queue.put(("input_down", label))
            self.ui_queue.put(("live_action", f"Tecla {label} pressionada"))

    def on_key_release(self, key):
        if self.recording and not self._is_control_shortcut(key):
            key_data = key_to_data(key)
            key_id = key_event_id(key_data)
            active = self.active_keys.pop(key_id, None)
            label = active["label"] if active else key_label(key)
            self.ui_queue.put(("input_up", label))
            self.ui_queue.put(("live_action", f"Tecla {label} solta"))
            if active is None:
                return
            now = self.timestamp()
            self.events.append(
                {
                    "type": "key_hold",
                    "key": active["key"],
                    "t": active["t"],
                    "duration": round(max(0, now - active["t"]), 4),
                }
            )
            self.ui_queue.put(("event_added", list(self.events)))

    def notify(self, text):
        self.ui_queue.put(("status", text))

    def _handle_control_key(self, key):
        shortcut = key_to_shortcut(key)
        if shortcut == self.shortcuts["record"]:
            if self.recording or self.recording_pending:
                self.stop_recording()
            else:
                self.start_recording()
            return True
        if shortcut == self.shortcuts["play"]:
            self.ui_queue.put(("play_shortcut", None))
            return True
        if shortcut == self.shortcuts["play_playlist"]:
            self.ui_queue.put(("play_playlist_shortcut", None))
            return True
        if shortcut == self.shortcuts["stop_playlist"]:
            self.ui_queue.put(("stop_playlist_shortcut", None))
            return True
        if shortcut == self.shortcuts["stop_playback"]:
            self.ui_queue.put(("stop_playback_shortcut", None))
            return True
        if shortcut == self.shortcuts["close"]:
            self.ui_queue.put(("escape", None))
            return True
        return False

    def _is_control_shortcut(self, key):
        return key_to_shortcut(key) in set(self.shortcuts.values())

    def flush_active_keys(self):
        if not self.active_keys:
            return
        now = self.timestamp()
        for active in list(self.active_keys.values()):
            self.events.append(
                {
                    "type": "key_hold",
                    "key": active["key"],
                    "t": active["t"],
                    "duration": round(max(0, now - active["t"]), 4),
                }
            )
            self.ui_queue.put(("input_up", active["label"]))
        self.active_keys.clear()
        self.ui_queue.put(("event_added", list(self.events)))

    def _finish_playback(self, message):
        self.playing = False
        self.stop_playback_requested.clear()
        self.ui_queue.put(("playing", False))
        self.notify(message)

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

    def _run_key_hold(self, event):
        key = key_from_data(event["key"])
        duration = max(0, float(event.get("duration", 0)))
        self.keyboard_controller.press(key)
        try:
            self.stop_playback_requested.wait(duration)
        finally:
            self.keyboard_controller.release(key)


def key_event_id(key_data):
    return f"{key_data.get('kind')}:{key_data.get('value')}"


def is_matrix_navigation_item(item):
    return item.get("kind") == "matrix_navigation" and isinstance(item.get("matrix"), dict)


def resolve_playlist_item_for_repeat(item, repeat_index):
    if not is_matrix_navigation_item(item):
        return item

    matrix = item["matrix"]
    target_row, target_column = matrix_target_for_repeat(matrix, repeat_index)
    step_delay = float(matrix.get("step_delay", DEFAULT_MATRIX_STEP_DELAY))
    return {
        "name": f"L{target_row}C{target_column}(Matriz)",
        "events": build_matrix_navigation_events(target_row, target_column, step_delay),
    }


def matrix_target_for_repeat(matrix, repeat_index):
    start_row = int(matrix.get("target_row", 1))
    start_column = int(matrix.get("target_column", 1))
    linear_position = ((start_column - 1) * MATRIX_ROW_LIMIT) + (start_row - 1) + repeat_index
    target_row = (linear_position % MATRIX_ROW_LIMIT) + 1
    target_column = (linear_position // MATRIX_ROW_LIMIT) + 1
    return target_row, target_column


def build_matrix_navigation_events(target_row, target_column, step_delay=DEFAULT_MATRIX_STEP_DELAY):
    events = []
    for index, direction in enumerate(matrix_navigation_steps(target_row, target_column)):
        events.append(
            {
                "type": "key_hold",
                "key": {"kind": "special", "value": direction},
                "t": round(index * step_delay, 4),
                "duration": 0.05,
            }
        )
    return events


def matrix_navigation_steps(target_row, target_column):
    steps = []
    steps.extend(["right"] * max(0, target_column - 1))
    steps.extend(["down"] * max(0, target_row - 1))
    return steps


def normalize_playback_events(events):
    normalized = []
    active_keys = {}

    for event in events:
        if event.get("type") != "key":
            normalized.append(event)
            continue

        key_id = key_event_id(event.get("key", {}))
        pressed = bool(event.get("pressed"))
        if pressed:
            if key_id not in active_keys:
                active_keys[key_id] = event
            continue

        start_event = active_keys.pop(key_id, None)
        if start_event is None:
            normalized.append(event)
            continue

        start_t = float(start_event.get("t", 0))
        end_t = float(event.get("t", start_t))
        normalized.append(
            {
                "type": "key_hold",
                "key": start_event["key"],
                "t": start_t,
                "duration": round(max(0, end_t - start_t), 4),
            }
        )

    normalized.extend(active_keys.values())
    return sorted(normalized, key=lambda item: float(item.get("t", 0)))
