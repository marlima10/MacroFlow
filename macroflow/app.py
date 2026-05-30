import json
import queue
import sys
import time
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk

import customtkinter as ctk
from pynput import keyboard, mouse

from .constants import MACROS_DIR
from .engine import MacroEngine
from .input_utils import event_details
from .timeline import render_timeline


class MacroApp(ctk.CTk):
    def __init__(self):
        ctk.set_appearance_mode("Dark")
        ctk.set_default_color_theme("blue")
        super().__init__()

        self.title("MacroFlow")
        self.geometry("1100x680")
        self.minsize(940, 560)

        self.ui_queue = queue.Queue()
        self.engine = MacroEngine(self.ui_queue)
        self.current_file = None
        self.events = []
        self.macro_buttons = []
        self.selected_macro_path = None
        self.pressed_inputs = set()
        self.theme_var = tk.StringVar(value="Dark")
        self.cell_editor = None
        self.playback_blink_on = False
        self.playback_blink_active = False

        self.create_widgets()
        self.apply_tree_style()
        self.refresh_macro_list()
        self.start_listeners()
        self.after(100, self.process_queue)
        self.protocol("WM_DELETE_WINDOW", self.close)

    def create_widgets(self):
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self.create_sidebar()
        self.create_main_area()

    def create_sidebar(self):
        self.sidebar = ctk.CTkFrame(self, width=230, corner_radius=0)
        self.sidebar.grid(row=0, column=0, sticky="nsew")
        self.sidebar.grid_rowconfigure(2, weight=1)

        ctk.CTkLabel(
            self.sidebar,
            text="MacroFlow",
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

    def create_main_area(self):
        self.main = ctk.CTkFrame(self, corner_radius=0, fg_color="transparent")
        self.main.grid(row=0, column=1, sticky="nsew", padx=18, pady=18)
        self.main.grid_columnconfigure(0, weight=1)
        self.main.grid_rowconfigure(2, weight=1)

        self.create_header()
        self.create_status_card()
        self.create_events_card()
        self.create_editor()

    def create_header(self):
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
        self.name_entry.grid(row=1, column=0, padx=18, pady=(0, 12), sticky="ew")

        actions = ctk.CTkFrame(header, fg_color="transparent")
        actions.grid(row=2, column=0, padx=18, pady=(0, 16), sticky="ew")

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

    def create_status_card(self):
        status_card = ctk.CTkFrame(self.main, corner_radius=10)
        status_card.grid(row=1, column=0, sticky="ew", pady=(0, 14))
        status_card.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(status_card, text="Atalhos", font=ctk.CTkFont(weight="bold")).grid(
            row=0, column=0, padx=(18, 12), pady=(14, 4), sticky="w"
        )
        ctk.CTkLabel(status_card, text="F8 grava/para  |  F9 reproduz  |  F10 para reproducao  |  Esc fecha").grid(
            row=0, column=1, padx=0, pady=(14, 4), sticky="w"
        )

        self.playback_alert = ctk.CTkLabel(
            status_card,
            text="● Reproduzindo",
            text_color="#22c55e",
            font=ctk.CTkFont(weight="bold"),
        )
        self.playback_alert.grid(row=0, column=2, padx=(12, 8), pady=(14, 4), sticky="e")
        self.playback_alert.grid_remove()

        self.status_var = tk.StringVar(value="Pronto para gravar.")
        ctk.CTkLabel(status_card, textvariable=self.status_var, anchor="e").grid(
            row=0, column=3, padx=(8, 18), pady=(14, 4), sticky="e"
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

    def create_events_card(self):
        table_card = ctk.CTkFrame(self.main, corner_radius=10)
        table_card.grid(row=2, column=0, sticky="nsew")
        table_card.grid_columnconfigure(0, weight=1)
        table_card.grid_rowconfigure(2, weight=1)

        ctk.CTkLabel(
            table_card,
            text="Eventos da macro",
            font=ctk.CTkFont(size=16, weight="bold"),
        ).grid(row=0, column=0, sticky="w", padx=18, pady=(16, 8))

        self.create_timeline(table_card)
        self.create_events_table(table_card)

    def create_timeline(self, parent):
        timeline_frame = ctk.CTkFrame(parent, corner_radius=8)
        timeline_frame.grid(row=1, column=0, columnspan=2, padx=18, pady=(0, 14), sticky="ew")
        timeline_frame.grid_columnconfigure(0, weight=1)

        self.timeline_canvas = tk.Canvas(timeline_frame, height=116, highlightthickness=0, bd=0, xscrollincrement=24)
        self.timeline_canvas.grid(row=0, column=0, sticky="ew", padx=10, pady=(10, 0))
        self.timeline_scrollbar = ttk.Scrollbar(timeline_frame, orient="horizontal", command=self.timeline_canvas.xview)
        self.timeline_scrollbar.grid(row=1, column=0, sticky="ew", padx=10, pady=(0, 10))
        self.timeline_canvas.configure(xscrollcommand=self.timeline_scrollbar.set)

    def create_events_table(self, parent):
        columns = ("t", "type", "details")
        self.table = ttk.Treeview(parent, columns=columns, show="headings", selectmode="browse")
        self.table.heading("t", text="Tempo")
        self.table.heading("type", text="Tipo")
        self.table.heading("details", text="Dados")
        self.table.column("t", width=90, stretch=False)
        self.table.column("type", width=130, stretch=False)
        self.table.column("details", width=640)
        self.table.grid(row=2, column=0, padx=(18, 0), pady=(0, 14), sticky="nsew")
        self.table.bind("<<TreeviewSelect>>", self.on_event_select)
        self.table.bind("<Double-1>", self.start_cell_edit)

        scrollbar = ttk.Scrollbar(parent, orient="vertical", command=self.table.yview)
        scrollbar.grid(row=2, column=1, padx=(0, 18), pady=(0, 14), sticky="ns")
        self.table.configure(yscrollcommand=scrollbar.set)

    def create_editor(self):
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
        ctk.CTkEntry(editor, textvariable=self.event_data).grid(row=0, column=5, padx=(0, 10), pady=16, sticky="ew")
        ctk.CTkButton(editor, text="Aplicar", width=92, command=self.apply_event_edit).grid(row=0, column=6, padx=4, pady=16)
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
        heading = "#333333" if dark else "#e4e4e4"

        style = ttk.Style(self)
        style.theme_use("default")
        style.configure("Treeview", background=field, foreground=fg, fieldbackground=field, borderwidth=0, rowheight=30)
        style.configure("Treeview.Heading", background=heading, foreground=fg, relief="flat")
        style.map("Treeview", background=[("selected", "#1f6aa5")], foreground=[("selected", "#ffffff")])
        self.configure(fg_color=bg)
        if hasattr(self, "timeline_canvas"):
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
            self.handle_ui_event(action, payload)
        self.after(100, self.process_queue)

    def handle_ui_event(self, action, payload):
        if action == "status":
            self.status_var.set(payload)
        elif action == "events_changed":
            self.events = payload
            self.render_events()
            self.set_record_button_idle()
        elif action == "recording_started":
            self.on_recording_started()
        elif action == "recording_stopped":
            self.on_recording_stopped()
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
            self.set_playback_alert(payload)
        elif action == "play_shortcut":
            self.play_current()
        elif action == "escape":
            self.close()

    def on_recording_started(self):
        self.events = []
        self.render_events()
        self.pressed_inputs.clear()
        self.live_inputs_var.set("Nada pressionado")
        self.live_action_var.set("Gravando em tempo real")

    def on_recording_stopped(self):
        self.pressed_inputs.clear()
        self.live_inputs_var.set("Nada pressionado")
        self.live_action_var.set("Gravacao encerrada")

    def change_theme(self):
        ctk.set_appearance_mode(self.theme_var.get())
        self.apply_tree_style()

    def set_playback_alert(self, is_playing):
        if is_playing:
            self.playback_blink_active = True
            self.playback_blink_on = True
            self.playback_alert.grid()
            self.blink_playback_alert()
            return

        self.playback_blink_active = False
        self.playback_blink_on = False
        self.playback_alert.grid_remove()

    def blink_playback_alert(self):
        if not self.playback_blink_active:
            return

        color = "#22c55e" if self.playback_blink_on else "#064e3b"
        self.playback_alert.configure(text_color=color)
        self.playback_blink_on = not self.playback_blink_on
        self.after(420, self.blink_playback_alert)

    def update_live_inputs(self):
        text = " + ".join(sorted(self.pressed_inputs)) if self.pressed_inputs else "Nada pressionado"
        self.live_inputs_var.set(text)

    def toggle_recording(self):
        if self.engine.recording:
            self.engine.stop_recording()
            self.set_record_button_idle()
        else:
            self.engine.start_recording()
            self.record_button.configure(text="Parar", fg_color="#ef8a2f", hover_color="#c96f24")

    def set_record_button_idle(self):
        self.record_button.configure(text="Gravar", fg_color="#d63d3d", hover_color="#b83232")

    def play_current(self):
        self.sync_events_from_engine()
        self.engine.play_events(list(self.events))

    def new_macro(self):
        self.current_file = None
        self.selected_macro_path = None
        self.events = []
        self.engine.events = []
        self.name_var.set("")
        self.render_events()
        self.update_macro_selection()
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
        name = self.name_var.get().strip() or simpledialog.askstring("Nome da macro", "Digite um nome para a macro:")
        if not name:
            return

        self.name_var.set(name)
        safe_name = self.safe_macro_name(name)
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
        self.selected_macro_path = path
        self.refresh_macro_list(select_path=path)
        self.status_var.set(f"Macro salva: {path.name}")

    def load_macro(self, path):
        data = json.loads(path.read_text(encoding="utf-8"))
        self.current_file = path
        self.selected_macro_path = path
        self.name_var.set(data.get("name") or path.stem)
        self.events = data.get("events", [])
        self.engine.events = list(self.events)
        self.render_events()
        self.update_macro_selection()
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
        for button, _path in self.macro_buttons:
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
                border_width=0,
            )
            button.grid(row=index, column=0, sticky="ew", padx=4, pady=4)
            self.macro_buttons.append((button, path))

        self.update_macro_selection()

        if select_path in self.macro_paths:
            self.load_macro(select_path)

    def update_macro_selection(self):
        for button, path in self.macro_buttons:
            if self.selected_macro_path == path:
                button.configure(
                    fg_color=("#d8ecff", "#14395c"),
                    hover_color=("#c7e2fb", "#1d4f7a"),
                    border_width=2,
                    border_color="#22c55e",
                    text_color=("#0f172a", "#ffffff"),
                )
            else:
                button.configure(
                    fg_color="transparent",
                    hover_color=("#d8e6f3", "#333333"),
                    border_width=0,
                    text_color=("gray10", "gray90"),
                )

    def render_events(self):
        self.table.delete(*self.table.get_children())
        for index, event in enumerate(self.events):
            self.table.insert("", "end", iid=str(index), values=(event.get("t", ""), event.get("type", ""), event_details(event)))
        self.render_timeline()

    def render_timeline(self):
        dark = self.theme_var.get() == "Dark"
        render_timeline(self.timeline_canvas, self.events, dark)

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
        self.cell_editor = tk.Entry(self.table)
        self.cell_editor.insert(0, self.table.set(row_id, column_name))
        self.cell_editor.select_range(0, tk.END)
        self.cell_editor.focus_set()
        self.cell_editor.place(x=x, y=y, width=width, height=height)
        self.cell_editor.bind("<Return>", lambda _event=None: self.commit_cell_edit(row_id, column_name))
        self.cell_editor.bind("<FocusOut>", lambda _event=None: self.commit_cell_edit(row_id, column_name))
        self.cell_editor.bind("<Escape>", self.cancel_cell_edit)

    def commit_cell_edit(self, row_id, column_name):
        if self.cell_editor is None:
            return
        value = self.cell_editor.get()
        self.cell_editor.destroy()
        self.cell_editor = None
        self.update_event_cell(int(row_id), column_name, value)

    def cancel_cell_edit(self, _event=None):
        if self.cell_editor is not None:
            self.cell_editor.destroy()
            self.cell_editor = None

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

    @staticmethod
    def safe_macro_name(name):
        return "".join(ch for ch in name if ch.isalnum() or ch in (" ", "-", "_")).strip()


def main():
    app = MacroApp()
    app.mainloop()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
