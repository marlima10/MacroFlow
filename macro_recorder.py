import json
import math
import queue
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, simpledialog, ttk

import customtkinter as ctk
from pynput import keyboard, mouse
from pynput.keyboard import Controller as KeyboardController
from pynput.mouse import Button, Controller as MouseController


APP_DIR = Path(__file__).resolve().parent
MACROS_DIR = APP_DIR / "macros"
MACROS_DIR.mkdir(exist_ok=True)

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

    def timestamp(self):
        return round(time.perf_counter() - self.started_at, 4)

    def add_event(self, event):
        if not self.recording:
            return
        event["t"] = self.timestamp()
        self.events.append(event)
        self.ui_queue.put(("event_added", list(self.events)))

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
            button = getattr(Button, event["button"])
            if event["pressed"]:
                self.mouse_controller.press(button)
            else:
                self.mouse_controller.release(button)
        elif event_type == "mouse_scroll":
            self.mouse_controller.scroll(int(event["dx"]), int(event["dy"]))
        elif event_type == "key":
            key = key_from_data(event["key"])
            if event["pressed"]:
                self.keyboard_controller.press(key)
            else:
                self.keyboard_controller.release(key)

    def on_mouse_move(self, x, y):
        if not self.recording:
            return

        now = self.timestamp()
        last = self.last_mouse_move
        if last is not None:
            last_t, last_x, last_y = last
            distance = math.hypot(x - last_x, y - last_y)
            if now - last_t < 0.03 and distance < 8:
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
        if key == keyboard.Key.f8:
            if self.recording:
                self.stop_recording()
            else:
                self.start_recording()
            return
        if key == keyboard.Key.f9:
            self.ui_queue.put(("play_shortcut", None))
            return
        if key == keyboard.Key.esc:
            self.ui_queue.put(("escape", None))
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


class MacroApp(ctk.CTk):
    def __init__(self):
        ctk.set_appearance_mode("Dark")
        ctk.set_default_color_theme("blue")
        super().__init__()

        self.title("Macro Recorder")
        self.geometry("1100x680")
        self.minsize(940, 560)

        self.ui_queue = queue.Queue()
        self.engine = MacroEngine(self.ui_queue)
        self.current_file = None
        self.events = []
        self.macro_buttons = []
        self.theme_var = tk.StringVar(value="Dark")
        self.cell_editor = None
        self.pressed_inputs = set()

        self.create_widgets()
        self.apply_tree_style()
        self.refresh_macro_list()
        self.start_listeners()
        self.after(100, self.process_queue)
        self.protocol("WM_DELETE_WINDOW", self.close)

    def create_widgets(self):
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self.sidebar = ctk.CTkFrame(self, width=230, corner_radius=0)
        self.sidebar.grid(row=0, column=0, sticky="nsew")
        self.sidebar.grid_rowconfigure(2, weight=1)

        ctk.CTkLabel(
            self.sidebar,
            text="Macro Recorder",
            font=ctk.CTkFont(size=22, weight="bold"),
        ).grid(row=0, column=0, padx=22, pady=(24, 16), sticky="w")

        ctk.CTkButton(self.sidebar, text="Nova macro", height=38, command=self.new_macro).grid(
            row=1, column=0, padx=22, pady=(0, 12), sticky="ew"
        )

        self.macro_scroll = ctk.CTkScrollableFrame(self.sidebar, label_text="Macros salvas")
        self.macro_scroll.grid(row=2, column=0, padx=16, pady=(0, 16), sticky="nsew")

        self.theme_switch = ctk.CTkSwitch(
            self.sidebar,
            text="Modo escuro",
            variable=self.theme_var,
            onvalue="Dark",
            offvalue="Light",
            command=self.change_theme,
        )
        self.theme_switch.select()
        self.theme_switch.grid(row=3, column=0, padx=22, pady=(0, 18), sticky="w")

        self.main = ctk.CTkFrame(self, corner_radius=0, fg_color="transparent")
        self.main.grid(row=0, column=1, sticky="nsew", padx=18, pady=18)
        self.main.grid_columnconfigure(0, weight=1)
        self.main.grid_rowconfigure(2, weight=1)

        header = ctk.CTkFrame(self.main, corner_radius=10)
        header.grid(row=0, column=0, sticky="ew", pady=(0, 14))
        header.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(header, text="Nome da macro", font=ctk.CTkFont(size=14, weight="bold")).grid(
            row=0, column=0, padx=18, pady=(16, 6), sticky="w"
        )
        self.name_var = tk.StringVar()
        self.name_entry = ctk.CTkEntry(
            header,
            textvariable=self.name_var,
            height=40,
            placeholder_text="Ex: abrir sistema e preencher relatorio",
        )
        self.name_entry.grid(row=1, column=0, columnspan=7, padx=18, pady=(0, 12), sticky="ew")

        actions = ctk.CTkFrame(header, fg_color="transparent")
        actions.grid(row=2, column=0, columnspan=7, padx=18, pady=(0, 16), sticky="ew")

        self.record_button = ctk.CTkButton(
            actions,
            text="Gravar",
            height=38,
            fg_color="#d63d3d",
            hover_color="#b83232",
            command=self.toggle_recording,
        )
        self.record_button.pack(side="left", padx=(0, 8))

        self.play_button = ctk.CTkButton(actions, text="Reproduzir", height=38, command=self.play_current)
        self.play_button.pack(side="left", padx=8)

        ctk.CTkButton(actions, text="Salvar", height=38, command=self.save_current).pack(side="left", padx=8)
        ctk.CTkButton(
            actions,
            text="Limpar",
            height=38,
            fg_color="#5c5f66",
            hover_color="#4d5056",
            command=self.clear_macro,
        ).pack(side="left", padx=8)
        ctk.CTkButton(
            actions,
            text="Excluir",
            height=38,
            fg_color="#5c5f66",
            hover_color="#4d5056",
            command=self.delete_current,
        ).pack(side="left", padx=8)

        status_card = ctk.CTkFrame(self.main, corner_radius=10)
        status_card.grid(row=1, column=0, sticky="ew", pady=(0, 14))
        status_card.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(status_card, text="Atalhos", font=ctk.CTkFont(weight="bold")).grid(
            row=0, column=0, padx=(18, 12), pady=(14, 4), sticky="w"
        )
        ctk.CTkLabel(status_card, text="F8 grava/para  |  F9 reproduz  |  Esc fecha").grid(
            row=0, column=1, padx=0, pady=(14, 4), sticky="w"
        )
        self.status_var = tk.StringVar(value="Pronto para gravar.")
        ctk.CTkLabel(status_card, textvariable=self.status_var, anchor="e").grid(
            row=0, column=2, padx=(12, 18), pady=(14, 4), sticky="e"
        )

        ctk.CTkLabel(status_card, text="Ao vivo", font=ctk.CTkFont(weight="bold")).grid(
            row=1, column=0, padx=(18, 12), pady=(4, 14), sticky="w"
        )
        self.live_inputs_var = tk.StringVar(value="Nada pressionado")
        self.live_action_var = tk.StringVar(value="Aguardando gravacao")
        ctk.CTkLabel(status_card, textvariable=self.live_inputs_var).grid(
            row=1, column=1, padx=0, pady=(4, 14), sticky="w"
        )
        ctk.CTkLabel(status_card, textvariable=self.live_action_var, anchor="e").grid(
            row=1, column=2, padx=(12, 18), pady=(4, 14), sticky="e"
        )

        table_card = ctk.CTkFrame(self.main, corner_radius=10)
        table_card.grid(row=2, column=0, sticky="nsew")
        table_card.grid_columnconfigure(0, weight=1)
        table_card.grid_rowconfigure(2, weight=1)

        ctk.CTkLabel(
            table_card,
            text="Eventos da macro",
            font=ctk.CTkFont(size=16, weight="bold"),
        ).grid(row=0, column=0, sticky="w", padx=18, pady=(16, 8))

        timeline_frame = ctk.CTkFrame(table_card, corner_radius=8)
        timeline_frame.grid(row=1, column=0, columnspan=2, padx=18, pady=(0, 14), sticky="ew")
        timeline_frame.grid_columnconfigure(0, weight=1)

        self.timeline_canvas = tk.Canvas(
            timeline_frame,
            height=116,
            highlightthickness=0,
            bd=0,
            xscrollincrement=24,
        )
        self.timeline_canvas.grid(row=0, column=0, sticky="ew", padx=10, pady=(10, 0))
        self.timeline_scrollbar = ttk.Scrollbar(
            timeline_frame,
            orient="horizontal",
            command=self.timeline_canvas.xview,
        )
        self.timeline_scrollbar.grid(row=1, column=0, sticky="ew", padx=10, pady=(0, 10))
        self.timeline_canvas.configure(xscrollcommand=self.timeline_scrollbar.set)

        columns = ("t", "type", "details")
        self.table = ttk.Treeview(table_card, columns=columns, show="headings", selectmode="browse")
        self.table.heading("t", text="Tempo")
        self.table.heading("type", text="Tipo")
        self.table.heading("details", text="Dados")
        self.table.column("t", width=90, stretch=False)
        self.table.column("type", width=130, stretch=False)
        self.table.column("details", width=640)
        self.table.grid(row=2, column=0, padx=(18, 0), pady=(0, 14), sticky="nsew")
        self.table.bind("<<TreeviewSelect>>", self.on_event_select)
        self.table.bind("<Double-1>", self.start_cell_edit)

        scrollbar = ttk.Scrollbar(table_card, orient="vertical", command=self.table.yview)
        scrollbar.grid(row=2, column=1, padx=(0, 18), pady=(0, 14), sticky="ns")
        self.table.configure(yscrollcommand=scrollbar.set)

        editor = ctk.CTkFrame(self.main, corner_radius=10)
        editor.grid(row=3, column=0, sticky="ew", pady=(14, 0))
        editor.grid_columnconfigure(5, weight=1)

        self.event_time = tk.StringVar()
        self.event_type = tk.StringVar()
        self.event_data = tk.StringVar()

        ctk.CTkLabel(editor, text="Tempo").grid(row=0, column=0, padx=(18, 6), pady=16)
        ctk.CTkEntry(editor, width=90, textvariable=self.event_time).grid(row=0, column=1, pady=16)
        ctk.CTkLabel(editor, text="Tipo").grid(row=0, column=2, padx=(12, 6), pady=16)
        ctk.CTkEntry(editor, width=130, textvariable=self.event_type).grid(row=0, column=3, pady=16)
        ctk.CTkLabel(editor, text="Dados JSON").grid(row=0, column=4, padx=(12, 6), pady=16)
        ctk.CTkEntry(editor, textvariable=self.event_data).grid(
            row=0, column=5, padx=(0, 10), pady=16, sticky="ew"
        )
        ctk.CTkButton(editor, text="Aplicar", width=92, command=self.apply_event_edit).grid(
            row=0, column=6, padx=4, pady=16
        )
        ctk.CTkButton(
            editor,
            text="Remover",
            width=92,
            fg_color="#5c5f66",
            hover_color="#4d5056",
            command=self.remove_event,
        ).grid(row=0, column=7, padx=(4, 18), pady=16)

    def apply_tree_style(self):
        dark = self.theme_var.get() == "Dark"
        bg = "#242424" if dark else "#f5f5f5"
        field = "#2b2b2b" if dark else "#ffffff"
        fg = "#e8e8e8" if dark else "#222222"
        selected = "#1f6aa5"
        heading = "#333333" if dark else "#e4e4e4"

        style = ttk.Style(self)
        style.theme_use("default")
        style.configure(
            "Treeview",
            background=field,
            foreground=fg,
            fieldbackground=field,
            borderwidth=0,
            rowheight=30,
        )
        style.configure("Treeview.Heading", background=heading, foreground=fg, relief="flat")
        style.map("Treeview", background=[("selected", selected)], foreground=[("selected", "#ffffff")])
        self.configure(fg_color=bg)
        if hasattr(self, "timeline_canvas"):
            self.timeline_canvas.configure(bg="#050505" if dark else "#f2f4f8")
            self.render_timeline()

    def start_listeners(self):
        self.mouse_listener = mouse.Listener(
            on_move=self.engine.on_mouse_move,
            on_click=self.engine.on_mouse_click,
            on_scroll=self.engine.on_mouse_scroll,
        )
        self.keyboard_listener = keyboard.Listener(
            on_press=self.engine.on_key_press,
            on_release=self.engine.on_key_release,
        )
        self.mouse_listener.start()
        self.keyboard_listener.start()

    def process_queue(self):
        while not self.ui_queue.empty():
            action, payload = self.ui_queue.get()
            if action == "status":
                self.status_var.set(payload)
            elif action == "events_changed":
                self.events = payload
                self.render_events()
                self.record_button.configure(text="Gravar", fg_color="#d63d3d", hover_color="#b83232")
            elif action == "recording_started":
                self.events = []
                self.render_events()
                self.pressed_inputs.clear()
                self.live_inputs_var.set("Nada pressionado")
                self.live_action_var.set("Gravando em tempo real")
            elif action == "recording_stopped":
                self.pressed_inputs.clear()
                self.live_inputs_var.set("Nada pressionado")
                self.live_action_var.set("Gravacao encerrada")
            elif action == "event_added":
                self.events = payload
                self.render_events()
            elif action == "input_down":
                self.pressed_inputs.add(payload)
                self.update_live_inputs()
            elif action == "input_up":
                self.pressed_inputs.discard(payload)
                self.update_live_inputs()
            elif action == "live_action":
                self.live_action_var.set(payload)
            elif action == "playing":
                self.play_button.configure(state="disabled" if payload else "normal")
            elif action == "play_shortcut":
                self.play_current()
            elif action == "escape":
                self.close()
        self.after(100, self.process_queue)

    def change_theme(self):
        ctk.set_appearance_mode(self.theme_var.get())
        self.apply_tree_style()

    def update_live_inputs(self):
        if self.pressed_inputs:
            self.live_inputs_var.set(" + ".join(sorted(self.pressed_inputs)))
        else:
            self.live_inputs_var.set("Nada pressionado")

    def toggle_recording(self):
        if self.engine.recording:
            self.engine.stop_recording()
            self.record_button.configure(text="Gravar", fg_color="#d63d3d", hover_color="#b83232")
        else:
            self.engine.start_recording()
            self.record_button.configure(text="Parar", fg_color="#ef8a2f", hover_color="#c96f24")

    def play_current(self):
        self.sync_events_from_engine()
        self.engine.play_events(list(self.events))

    def new_macro(self):
        self.current_file = None
        self.events = []
        self.engine.events = []
        self.name_var.set("")
        self.render_events()
        self.live_inputs_var.set("Nada pressionado")
        self.live_action_var.set("Aguardando gravacao")
        self.status_var.set("Nova macro em branco.")

    def clear_macro(self):
        if not self.events and not self.engine.events:
            self.status_var.set("A macro ja esta vazia.")
            return
        if not messagebox.askyesno("Limpar macro", "Remover todos os eventos desta macro?"):
            return
        self.events = []
        self.engine.events = []
        self.render_events()
        self.event_time.set("")
        self.event_type.set("")
        self.event_data.set("")
        self.status_var.set("Eventos da macro removidos. Clique em Salvar para gravar a alteracao.")

    def save_current(self):
        self.sync_events_from_engine()
        name = self.name_var.get().strip()
        if not name:
            name = simpledialog.askstring("Nome da macro", "Digite um nome para a macro:")
            if not name:
                return
            self.name_var.set(name)

        safe_name = "".join(ch for ch in name if ch.isalnum() or ch in (" ", "-", "_")).strip()
        if not safe_name:
            messagebox.showerror("Nome invalido", "Use pelo menos uma letra ou numero no nome.")
            return

        path = MACROS_DIR / f"{safe_name}.json"
        data = {
            "version": 1,
            "name": name,
            "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "events": self.events,
        }
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        self.current_file = path
        self.refresh_macro_list(select_path=path)
        self.status_var.set(f"Macro salva: {path.name}")

    def load_macro(self, path):
        data = json.loads(path.read_text(encoding="utf-8"))
        self.current_file = path
        self.name_var.set(data.get("name") or path.stem)
        self.events = data.get("events", [])
        self.engine.events = list(self.events)
        self.render_events()
        self.status_var.set(f"Macro carregada: {path.name}")

    def delete_current(self):
        if not self.current_file:
            return
        if not messagebox.askyesno("Excluir macro", f"Excluir {self.current_file.name}?"):
            return
        self.current_file.unlink()
        self.new_macro()
        self.refresh_macro_list()

    def refresh_macro_list(self, select_path=None):
        for button in self.macro_buttons:
            button.destroy()
        self.macro_buttons = []
        self.macro_paths = sorted(MACROS_DIR.glob("*.json"))

        for index, path in enumerate(self.macro_paths):
            button = ctk.CTkButton(
                self.macro_scroll,
                text=path.stem,
                anchor="w",
                fg_color="transparent",
                text_color=("gray10", "gray90"),
                hover_color=("#d8e6f3", "#333333"),
                command=lambda selected=path: self.load_macro(selected),
            )
            button.grid(row=index, column=0, sticky="ew", padx=4, pady=4)
            self.macro_buttons.append(button)

        if select_path in self.macro_paths:
            self.load_macro(select_path)

    def render_events(self):
        self.table.delete(*self.table.get_children())
        for index, event in enumerate(self.events):
            self.table.insert(
                "",
                "end",
                iid=str(index),
                values=(event.get("t", ""), event.get("type", ""), event_details(event)),
            )
        self.render_timeline()

    def render_timeline(self):
        if not hasattr(self, "timeline_canvas"):
            return

        canvas = self.timeline_canvas
        canvas.delete("all")
        dark = self.theme_var.get() == "Dark"
        bg = "#050505" if dark else "#f2f4f8"
        text_color = "#ffffff" if dark else "#111827"
        muted_color = "#d7d7d7" if dark else "#4b5563"
        line_color = "#a3a3a3" if dark else "#6b7280"
        key_color = "#8f1237"
        mouse_color = "#111111" if dark else "#ffffff"
        mouse_outline = "#f4f4f5" if dark else "#111827"

        canvas.configure(bg=bg)
        visible_events = [
            (index, event)
            for index, event in enumerate(self.events)
            if event.get("type") in ("key", "mouse_click", "mouse_scroll")
        ]

        if not visible_events:
            canvas.create_text(
                24,
                58,
                anchor="w",
                text="Grave uma macro para ver os eventos aqui.",
                fill=muted_color,
                font=("Segoe UI", 11),
            )
            canvas.configure(scrollregion=(0, 0, 760, 116))
            return

        x = 22
        center_y = 58
        previous_t = 0.0
        for position, (_index, event) in enumerate(visible_events):
            current_t = float(event.get("t", 0))
            if position > 0:
                delay = max(0, current_t - previous_t)
                delay_text = format_delay(delay)
                canvas.create_line(x, center_y, x + 36, center_y, fill=line_color, width=1)
                canvas.create_text(
                    x + 18,
                    center_y - 16,
                    text=delay_text[0],
                    fill=text_color,
                    font=("Segoe UI", 8, "bold"),
                )
                canvas.create_text(
                    x + 18,
                    center_y + 2,
                    text=delay_text[1],
                    fill=muted_color,
                    font=("Segoe UI", 7),
                )
                x += 48

            event_type = event.get("type")
            pressed = bool(event.get("pressed", True))
            if event_type == "mouse_click":
                draw_mouse_icon(canvas, x, center_y, event.get("button", "left"), pressed, mouse_color, mouse_outline)
                x += 36
            elif event_type == "mouse_scroll":
                draw_scroll_icon(canvas, x, center_y, mouse_color, mouse_outline)
                x += 36
            else:
                label = timeline_key_label(event)
                box_width = max(26, min(74, 18 + len(label) * 8))
                rounded_rect(canvas, x, center_y - 16, x + box_width, center_y + 16, 4, fill=key_color, outline=key_color)
                canvas.create_text(
                    x + box_width / 2,
                    center_y,
                    text=label,
                    fill="#ffffff",
                    font=("Segoe UI", 8, "bold"),
                )
                triangle_y = center_y - 28 if pressed else center_y + 28
                draw_triangle(canvas, x + box_width / 2, triangle_y, pressed, text_color)
                x += box_width + 10
            previous_t = current_t

        canvas.configure(scrollregion=(0, 0, max(x + 40, 760), 116))

    def on_event_select(self, _event=None):
        selected = self.table.selection()
        if not selected:
            return
        index = int(selected[0])
        event = self.events[index]
        self.event_time.set(str(event.get("t", "")))
        self.event_type.set(str(event.get("type", "")))
        data = {key: value for key, value in event.items() if key not in ("t", "type")}
        self.event_data.set(json.dumps(data, ensure_ascii=False))

    def start_cell_edit(self, event):
        row_id = self.table.identify_row(event.y)
        column_id = self.table.identify_column(event.x)
        if not row_id or column_id == "#0":
            return

        column_index = int(column_id.replace("#", "")) - 1
        column_name = self.table["columns"][column_index]
        bbox = self.table.bbox(row_id, column_id)
        if not bbox:
            return

        if self.cell_editor is not None:
            self.cell_editor.destroy()

        x, y, width, height = bbox
        current_value = self.table.set(row_id, column_name)
        self.cell_editor = tk.Entry(self.table)
        self.cell_editor.insert(0, current_value)
        self.cell_editor.select_range(0, tk.END)
        self.cell_editor.focus_set()
        self.cell_editor.place(x=x, y=y, width=width, height=height)

        def commit(_event=None):
            if self.cell_editor is None:
                return
            value = self.cell_editor.get()
            self.cell_editor.destroy()
            self.cell_editor = None
            self.update_event_cell(int(row_id), column_name, value)

        def cancel(_event=None):
            if self.cell_editor is not None:
                self.cell_editor.destroy()
                self.cell_editor = None

        self.cell_editor.bind("<Return>", commit)
        self.cell_editor.bind("<FocusOut>", commit)
        self.cell_editor.bind("<Escape>", cancel)

    def update_event_cell(self, index, column_name, value):
        try:
            event = dict(self.events[index])
            if column_name == "t":
                event["t"] = float(value)
            elif column_name == "type":
                event["type"] = value.strip()
                if not event["type"]:
                    raise ValueError("Tipo nao pode ficar vazio.")
            elif column_name == "details":
                details = json.loads(value or "{}")
                event = {"t": event.get("t", 0), "type": event.get("type", ""), **details}
            self.events[index] = event
            self.engine.events = list(self.events)
            self.render_events()
            self.table.selection_set(str(index))
            self.on_event_select()
            self.status_var.set("Evento editado na tabela.")
        except Exception as exc:
            messagebox.showerror("Celula invalida", str(exc))
            self.render_events()

    def apply_event_edit(self):
        selected = self.table.selection()
        if not selected:
            return
        index = int(selected[0])
        try:
            data = json.loads(self.event_data.get() or "{}")
            data["t"] = float(self.event_time.get())
            data["type"] = self.event_type.get().strip()
        except Exception as exc:
            messagebox.showerror("Evento invalido", str(exc))
            return
        self.events[index] = data
        self.engine.events = list(self.events)
        self.render_events()
        self.table.selection_set(str(index))

    def remove_event(self):
        selected = self.table.selection()
        if not selected:
            return
        index = int(selected[0])
        del self.events[index]
        self.engine.events = list(self.events)
        self.render_events()

    def sync_events_from_engine(self):
        if self.engine.events is not self.events and self.engine.events:
            self.events = list(self.engine.events)

    def close(self):
        try:
            self.mouse_listener.stop()
            self.keyboard_listener.stop()
        finally:
            self.destroy()


def event_details(event):
    data = {key: value for key, value in event.items() if key not in ("t", "type")}
    return json.dumps(data, ensure_ascii=False)


def format_delay(seconds):
    if seconds >= 1:
        return (f"{seconds:.1f}", "s")
    return (str(int(round(seconds * 1000))), "ms")


def timeline_key_label(event):
    key = event.get("key", {})
    if key.get("kind") == "char":
        value = key.get("value") or ""
        return value.upper() if len(value) == 1 else value
    value = key.get("value", "")
    names = {
        "space": "Space",
        "enter": "Enter",
        "shift": "Shift",
        "shift_r": "Shift",
        "ctrl": "Ctrl",
        "ctrl_l": "Ctrl",
        "ctrl_r": "Ctrl",
        "alt": "Alt",
        "alt_l": "Alt",
        "alt_r": "Alt",
        "tab": "Tab",
        "backspace": "Back",
        "esc": "Esc",
    }
    return names.get(value, value.replace("_", " ").title())


def rounded_rect(canvas, x1, y1, x2, y2, radius, **kwargs):
    points = [
        x1 + radius,
        y1,
        x2 - radius,
        y1,
        x2,
        y1,
        x2,
        y1 + radius,
        x2,
        y2 - radius,
        x2,
        y2,
        x2 - radius,
        y2,
        x1 + radius,
        y2,
        x1,
        y2,
        x1,
        y2 - radius,
        x1,
        y1 + radius,
        x1,
        y1,
    ]
    return canvas.create_polygon(points, smooth=True, **kwargs)


def draw_triangle(canvas, x, y, pressed, color):
    if pressed:
        points = (x, y - 4, x - 5, y + 3, x + 5, y + 3)
    else:
        points = (x, y + 4, x - 5, y - 3, x + 5, y - 3)
    canvas.create_polygon(points, fill=color, outline=color)


def draw_mouse_icon(canvas, x, center_y, button, pressed, fill, outline):
    top = center_y - 22
    bottom = center_y + 22
    canvas.create_oval(x + 4, top, x + 24, bottom, outline=outline, width=2, fill=fill)
    canvas.create_line(x + 14, top + 5, x + 14, top + 15, fill=outline, width=1)
    if button == "left":
        canvas.create_arc(x + 4, top, x + 24, top + 22, start=90, extent=90, outline=outline, width=3 if pressed else 1)
    elif button == "right":
        canvas.create_arc(x + 4, top, x + 24, top + 22, start=0, extent=90, outline=outline, width=3 if pressed else 1)
    else:
        canvas.create_oval(x + 11, top + 8, x + 17, top + 16, outline=outline, width=2, fill=outline if pressed else fill)


def draw_scroll_icon(canvas, x, center_y, fill, outline):
    draw_mouse_icon(canvas, x, center_y, "middle", False, fill, outline)
    canvas.create_line(x + 14, center_y - 8, x + 14, center_y + 8, fill=outline, width=2, arrow=tk.LAST)


def key_to_data(key):
    if isinstance(key, keyboard.KeyCode):
        return {"kind": "char", "value": key.char}
    return {"kind": "special", "value": key.name}


def key_label(key):
    if isinstance(key, keyboard.KeyCode):
        return key.char or "tecla"
    return key.name.replace("_", " ").title()


def key_from_data(data):
    if data["kind"] == "char":
        return keyboard.KeyCode.from_char(data["value"])
    return getattr(keyboard.Key, data["value"])


def main():
    app = MacroApp()
    app.mainloop()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
