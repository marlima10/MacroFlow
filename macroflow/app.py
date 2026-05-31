import json
import queue
import sys
import time
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk

import customtkinter as ctk
from pynput import keyboard, mouse

from .constants import APP_CONFIG_FILE, APP_ICON_FILE, DEFAULT_SHORTCUTS, LANGUAGE_DIR, MACROS_DIR, SHORTCUT_LABELS, SHORTCUTS_FILE
from .engine import MacroEngine
from .input_utils import event_details, is_valid_shortcut, normalize_shortcut, shortcut_label
from .smart_engine import SmartMacroEngine
from .timeline import render_timeline


class MacroApp(ctk.CTk):
    def __init__(self):
        self.app_config = self.load_app_config()
        ctk.set_appearance_mode(self.app_config["theme"])
        ctk.set_default_color_theme("blue")
        super().__init__()

        self.title("MacroFlow")
        self.geometry("1100x680")
        self.minsize(940, 560)
        self.set_window_icon()

        self.ui_queue = queue.Queue()
        self.shortcuts = self.load_shortcuts()
        self.engine = MacroEngine(self.ui_queue, self.shortcuts)
        self.smart_engine = SmartMacroEngine(self.set_smart_status)
        self.current_file = None
        self.events = []
        self.macro_buttons = []
        self.execute_macro_buttons = []
        self.execute_macro_paths = []
        self.execute_selected_path = None
        self.execute_selected_events = []
        self.selected_macro_path = None
        self.pressed_inputs = set()
        self.language = self.app_config["language"]
        self.texts = self.load_language(self.language)
        self.theme_var = tk.StringVar(value=self.app_config["theme"])
        self.startup_var = tk.BooleanVar(value=self.app_config["start_with_windows"])
        self.loop_playback_var = tk.BooleanVar(value=False)
        self.cell_editor = None
        self.playback_blink_on = False
        self.playback_blink_active = False
        self.active_view = "conventional"
        self.active_screen = "home"
        self.execute_timer_running = False
        self.execute_timer_started_at = 0.0
        self.execute_countdown_active = False
        self.execute_countdown_after_id = None
        self.execute_countdown_step = 0

        self.create_widgets()
        self.apply_tree_style()
        self.refresh_macro_list()
        self.start_listeners()
        self.after(100, self.process_queue)
        self.protocol("WM_DELETE_WINDOW", self.close)

    def load_app_config(self):
        default_config = {"language": "pt-br", "theme": "Dark", "start_with_windows": False}
        if not APP_CONFIG_FILE.exists():
            APP_CONFIG_FILE.write_text(json.dumps(default_config, indent=2), encoding="utf-8")
            return default_config
        try:
            saved_config = json.loads(APP_CONFIG_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            saved_config = {}
        return {**default_config, **saved_config}

    def save_app_config(self):
        self.app_config.update(
            {
                "language": self.language,
                "theme": self.theme_var.get(),
                "start_with_windows": self.startup_var.get(),
            }
        )
        APP_CONFIG_FILE.write_text(json.dumps(self.app_config, indent=2), encoding="utf-8")

    def load_language(self, language):
        language_file = LANGUAGE_DIR / f"{language}.json"
        fallback_file = LANGUAGE_DIR / "pt-br.json"
        try:
            return json.loads(language_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return json.loads(fallback_file.read_text(encoding="utf-8"))

    def t(self, key):
        value = self.texts
        for part in key.split("."):
            if not isinstance(value, dict) or part not in value:
                return key
            value = value[part]
        return value

    def set_window_icon(self):
        if not APP_ICON_FILE.exists():
            return
        try:
            self.iconbitmap(str(APP_ICON_FILE))
        except tk.TclError:
            pass

    def create_widgets(self):
        self.grid_columnconfigure(0, weight=0)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self.create_home_view()
        self.create_execute_view()
        self.create_settings_view()
        self.create_sidebar()
        self.create_main_area()
        self.show_home()

    def create_placeholder_view(self, name, title, description, accent):
        view = ctk.CTkFrame(self, corner_radius=0, fg_color="#020812")
        view.grid(row=0, column=0, columnspan=2, sticky="nsew")
        view.grid_columnconfigure(0, weight=1)
        view.grid_rowconfigure((0, 4), weight=1)

        panel = ctk.CTkFrame(
            view,
            width=560,
            height=300,
            corner_radius=18,
            fg_color=("#eef6ff", "#06111f"),
            border_width=1,
            border_color=accent,
        )
        panel.grid(row=1, column=0, padx=28, pady=(24, 16))
        panel.grid_propagate(False)
        panel.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(panel, text=title, font=ctk.CTkFont(size=28, weight="bold")).grid(
            row=0, column=0, padx=34, pady=(42, 14)
        )
        ctk.CTkLabel(
            panel,
            text=description,
            font=ctk.CTkFont(size=16),
            text_color=("gray25", "gray78"),
            wraplength=430,
            justify="center",
        ).grid(row=1, column=0, padx=34, pady=(0, 28))
        ctk.CTkButton(
            panel,
            text="Voltar",
            width=130,
            height=42,
            fg_color=accent,
            hover_color=accent,
            command=self.show_home,
        ).grid(row=2, column=0, padx=34, pady=(0, 38))

        view.grid_remove()
        setattr(self, f"{name}_view", view)

    def create_execute_view(self):
        self.execute_view = ctk.CTkFrame(self, corner_radius=0, fg_color="#020812")
        self.execute_view.grid(row=0, column=0, columnspan=2, sticky="nsew")
        self.execute_view.grid_columnconfigure(0, weight=0)
        self.execute_view.grid_columnconfigure(1, weight=1)
        self.execute_view.grid_rowconfigure(1, weight=1)

        header = ctk.CTkFrame(self.execute_view, fg_color="transparent")
        header.grid(row=0, column=0, columnspan=2, padx=34, pady=(28, 18), sticky="ew")
        header.grid_columnconfigure(1, weight=1)

        ctk.CTkButton(
            header,
            text="<",
            width=42,
            height=42,
            corner_radius=21,
            fg_color=("#e7edf5", "#152033"),
            hover_color=("#d9e4f1", "#1c2b43"),
            text_color=("gray10", "gray90"),
            command=self.show_home,
        ).grid(row=0, column=0, rowspan=2, padx=(0, 16), pady=4)
        ctk.CTkLabel(header, text=self.t("execute.title"), font=ctk.CTkFont(size=28, weight="bold")).grid(
            row=0, column=1, sticky="w"
        )
        ctk.CTkLabel(
            header,
            text=self.t("execute.description"),
            font=ctk.CTkFont(size=14),
            text_color=("gray35", "gray72"),
        ).grid(row=1, column=1, sticky="w", pady=(2, 0))

        list_card = self.create_execute_card(self.execute_view)
        list_card.grid(row=1, column=0, padx=(34, 10), pady=(0, 24), sticky="nsew")
        list_card.grid_rowconfigure(1, weight=1)

        ctk.CTkLabel(
            list_card,
            text=self.t("execute.saved_macros"),
            font=ctk.CTkFont(size=16, weight="bold"),
        ).grid(row=0, column=0, padx=18, pady=(18, 8), sticky="w")
        self.execute_macro_scroll = ctk.CTkScrollableFrame(list_card, fg_color="transparent")
        self.execute_macro_scroll.grid(row=1, column=0, padx=14, pady=(0, 14), sticky="nsew")
        self.execute_macro_scroll.grid_columnconfigure(0, weight=1)

        content = ctk.CTkFrame(self.execute_view, fg_color="transparent")
        content.grid(row=1, column=1, padx=(10, 34), pady=(0, 24), sticky="nsew")
        content.grid_columnconfigure(0, weight=1)
        content.grid_rowconfigure(2, weight=1)

        controls = self.create_execute_card(content)
        controls.grid(row=0, column=0, sticky="ew", pady=(0, 14))
        controls.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(
            controls,
            text=self.t("execute.controls"),
            font=ctk.CTkFont(size=16, weight="bold"),
        ).grid(row=0, column=0, columnspan=4, padx=18, pady=(18, 10), sticky="w")

        self.execute_play_button = ctk.CTkButton(
            controls,
            text=f"{shortcut_label(self.shortcuts['play'])}  {self.t('execute.play')}",
            height=42,
            command=self.play_execute_macro,
        )
        self.execute_play_button.grid(row=1, column=0, padx=(18, 8), pady=(0, 18), sticky="ew")
        self.execute_stop_button = ctk.CTkButton(
            controls,
            text=f"{shortcut_label(self.shortcuts['stop_playback'])}  {self.t('execute.stop')}",
            height=42,
            fg_color="#5c5f66",
            hover_color="#4d5056",
            command=self.stop_execute_playback,
        )
        self.execute_stop_button.grid(row=1, column=1, padx=8, pady=(0, 18), sticky="w")
        self.execute_loop_var = tk.BooleanVar(value=False)
        ctk.CTkSwitch(controls, text=self.t("execute.loop"), variable=self.execute_loop_var).grid(
            row=1, column=2, padx=8, pady=(0, 18), sticky="w"
        )
        self.execute_status_label = ctk.CTkLabel(
            controls,
            text=self.t("execute.none"),
            text_color=("gray35", "gray72"),
        )
        self.execute_status_label.grid(row=1, column=3, padx=(8, 18), pady=(0, 18), sticky="e")

        timer_card = self.create_execute_card(content)
        timer_card.grid(row=1, column=0, sticky="ew", pady=(0, 14))
        timer_card.grid_columnconfigure(2, weight=1)
        ctk.CTkLabel(
            timer_card,
            text=self.t("execute.elapsed_time"),
            font=ctk.CTkFont(size=16, weight="bold"),
        ).grid(row=0, column=0, padx=18, pady=18, sticky="w")
        lights = ctk.CTkFrame(timer_card, fg_color="transparent")
        lights.grid(row=0, column=1, padx=(0, 16), pady=18, sticky="w")
        self.execute_lights = []
        for column in range(3):
            light = ctk.CTkFrame(lights, width=28, height=28, corner_radius=14, fg_color="#4b5563")
            light.grid(row=0, column=column, padx=4)
            light.grid_propagate(False)
            self.execute_lights.append(light)
        self.execute_elapsed_var = tk.StringVar(value="00:00:00")
        ctk.CTkLabel(
            timer_card,
            textvariable=self.execute_elapsed_var,
            font=ctk.CTkFont(size=30, weight="bold"),
            text_color="#62df45",
        ).grid(row=0, column=2, padx=18, pady=18, sticky="e")

        preview = self.create_execute_card(content)
        preview.grid(row=2, column=0, sticky="nsew")
        preview.grid_columnconfigure(0, weight=1)
        preview.grid_rowconfigure(2, weight=1)
        ctk.CTkLabel(
            preview,
            text=self.t("execute.selected_macro"),
            font=ctk.CTkFont(size=16, weight="bold"),
        ).grid(row=0, column=0, padx=18, pady=(18, 4), sticky="w")
        self.execute_summary_var = tk.StringVar(value=self.t("execute.select_hint"))
        ctk.CTkLabel(preview, textvariable=self.execute_summary_var, text_color=("gray35", "gray72")).grid(
            row=1, column=0, padx=18, pady=(0, 12), sticky="w"
        )
        timeline_frame = ctk.CTkFrame(preview, corner_radius=8)
        timeline_frame.grid(row=2, column=0, padx=18, pady=(0, 18), sticky="nsew")
        timeline_frame.grid_columnconfigure(0, weight=1)
        timeline_frame.grid_rowconfigure(0, weight=1)
        self.execute_timeline_canvas = tk.Canvas(timeline_frame, height=150, highlightthickness=0, bd=0)
        self.execute_timeline_canvas.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)

        self.execute_view.grid_remove()
        self.refresh_execute_macro_list()

    def create_execute_card(self, parent):
        return ctk.CTkFrame(
            parent,
            corner_radius=10,
            fg_color=("#eef6ff", "#07111f"),
            border_width=1,
            border_color=("#d8e0ea", "#132034"),
        )

    def create_settings_view(self):
        self.settings_view = ctk.CTkFrame(self, corner_radius=0, fg_color="#020812")
        self.settings_view.grid(row=0, column=0, columnspan=2, sticky="nsew")
        self.settings_view.grid_columnconfigure(0, weight=1)
        self.settings_view.grid_rowconfigure(5, weight=1)

        header = ctk.CTkFrame(self.settings_view, fg_color="transparent")
        header.grid(row=0, column=0, padx=34, pady=(28, 18), sticky="ew")
        header.grid_columnconfigure(1, weight=1)

        ctk.CTkButton(
            header,
            text="<",
            width=42,
            height=42,
            corner_radius=21,
            fg_color=("#e7edf5", "#152033"),
            hover_color=("#d9e4f1", "#1c2b43"),
            text_color=("gray10", "gray90"),
            command=self.show_home,
        ).grid(row=0, column=0, rowspan=2, padx=(0, 16), pady=4)
        ctk.CTkLabel(header, text=self.t("settings.title"), font=ctk.CTkFont(size=28, weight="bold")).grid(
            row=0, column=1, sticky="w"
        )
        ctk.CTkLabel(
            header,
            text=self.t("settings.subtitle"),
            font=ctk.CTkFont(size=14),
            text_color=("gray35", "gray72"),
        ).grid(row=1, column=1, sticky="w", pady=(2, 0))

        self.create_language_settings_card()
        self.create_theme_settings_card()
        self.create_startup_settings_card()
        self.create_about_settings_card()
        self.create_settings_footer()
        self.settings_view.grid_remove()

    def create_settings_section(self, row, title, description, accent, icon_text):
        section = ctk.CTkFrame(
            self.settings_view,
            corner_radius=10,
            fg_color=("#eef6ff", "#07111f"),
            border_width=1,
            border_color=("#d8e0ea", "#132034"),
        )
        section.grid(row=row, column=0, padx=68, pady=(0, 8), sticky="ew")
        section.grid_columnconfigure(2, weight=1)

        ctk.CTkLabel(
            section,
            text=icon_text,
            width=32,
            height=32,
            corner_radius=16,
            fg_color=accent,
            text_color="#ffffff",
            font=ctk.CTkFont(size=16, weight="bold"),
        ).grid(row=0, column=0, rowspan=2, padx=(18, 14), pady=18)
        ctk.CTkLabel(section, text=title, font=ctk.CTkFont(size=15, weight="bold")).grid(
            row=0, column=1, sticky="sw", pady=(18, 0)
        )
        ctk.CTkLabel(section, text=description, text_color=("gray35", "gray72")).grid(
            row=1, column=1, sticky="nw", pady=(0, 18)
        )
        return section

    def create_language_settings_card(self):
        section = self.create_settings_section(
            1, self.t("settings.language_title"), self.t("settings.language_description"), "#1877d8", "G"
        )
        options = ctk.CTkFrame(section, fg_color="transparent")
        options.grid(row=2, column=1, columnspan=2, padx=(0, 50), pady=(0, 18), sticky="ew")
        options.grid_columnconfigure(0, weight=1)
        self.create_language_option(options, 0, "pt-br", "BR", self.t("settings.pt_br"), self.t("settings.pt_br_note"))
        self.create_language_option(options, 1, "en", "EN", self.t("settings.en"), self.t("settings.en_note"))

    def create_language_option(self, parent, row, language, flag, title, note):
        selected = self.language == language
        option = ctk.CTkFrame(
            parent,
            height=48,
            corner_radius=7,
            fg_color=("#e8f2ff", "#0b1628") if selected else ("#f8fbff", "#07111f"),
            border_width=1,
            border_color="#168bff" if selected else ("#cfd9e6", "#1a2b42"),
        )
        option.grid(row=row, column=0, sticky="ew", pady=(0, 8))
        option.grid_propagate(False)
        option.grid_columnconfigure(2, weight=1)
        click_action = lambda _event: self.change_language(language)
        option.bind("<Button-1>", click_action)

        radio = ctk.CTkLabel(
            option,
            text="*" if selected else "o",
            text_color="#168bff" if selected else ("gray45", "gray60"),
            font=ctk.CTkFont(size=16, weight="bold"),
        )
        radio.grid(row=0, column=0, padx=(18, 12), pady=9)
        flag_label = ctk.CTkLabel(option, text=flag, font=ctk.CTkFont(size=18, weight="bold"))
        flag_label.grid(row=0, column=1, padx=(0, 14), pady=9)
        language_label = ctk.CTkLabel(
            option,
            text=f"{title} - {note}",
            font=ctk.CTkFont(size=14),
            text_color="#168bff" if selected else ("gray20", "gray82"),
        )
        language_label.grid(row=0, column=2, sticky="w", pady=9)
        for widget in (radio, flag_label, language_label):
            widget.bind("<Button-1>", click_action)

    def create_theme_settings_card(self):
        section = self.create_settings_section(
            2, self.t("settings.theme_title"), self.t("settings.theme_description"), "#5842a6", "T"
        )
        values = [self.t("settings.theme_dark"), self.t("settings.theme_light")]
        current_value = self.t("settings.theme_dark") if self.theme_var.get() == "Dark" else self.t("settings.theme_light")
        self.theme_menu = ctk.CTkOptionMenu(
            section,
            values=values,
            variable=tk.StringVar(value=current_value),
            command=self.change_theme_from_settings,
        )
        self.theme_menu.grid(row=0, column=3, rowspan=2, padx=(18, 18), pady=18, sticky="e")

    def create_startup_settings_card(self):
        section = self.create_settings_section(
            3, self.t("settings.startup_title"), self.t("settings.startup_description"), "#16a34a", "P"
        )
        ctk.CTkSwitch(
            section,
            text=self.t("settings.startup_windows"),
            variable=self.startup_var,
            command=self.save_app_config,
        ).grid(row=0, column=3, rowspan=2, padx=(18, 18), pady=18, sticky="e")

    def create_about_settings_card(self):
        section = self.create_settings_section(
            4, self.t("settings.about_title"), self.t("settings.about_description"), "#1877d8", "i"
        )
        ctk.CTkLabel(section, text=">", font=ctk.CTkFont(size=22), text_color=("gray35", "gray72")).grid(
            row=0, column=3, rowspan=2, padx=(18, 28), pady=18
        )

    def create_settings_footer(self):
        footer = ctk.CTkFrame(self.settings_view, corner_radius=10, fg_color=("#eef3f8", "#07111f"))
        footer.grid(row=5, column=0, padx=68, pady=(8, 18), sticky="sew")
        footer.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            footer,
            text=f"</>  {self.t('app.developer')}",
            font=ctk.CTkFont(size=14),
            text_color=("#1b6fb8", "#4aa7ff"),
        ).grid(row=0, column=0, padx=24, pady=16)

    def hide_root_views(self):
        for view_name in ("home_view", "execute_view", "settings_view", "sidebar", "main"):
            view = getattr(self, view_name, None)
            if view is not None:
                view.grid_remove()

    def show_home(self):
        self.hide_root_views()
        self.active_screen = "home"
        self.grid_columnconfigure(0, weight=1)
        self.home_view.grid(row=0, column=0, columnspan=2, sticky="nsew")
        self.home_view.tkraise()

    def show_placeholder(self, name):
        self.hide_root_views()
        self.active_screen = name
        self.grid_columnconfigure(0, weight=1)
        view = getattr(self, f"{name}_view")
        view.grid(row=0, column=0, columnspan=2, sticky="nsew")
        view.tkraise()

    def show_app_shell(self, view="conventional"):
        self.hide_root_views()
        self.active_screen = "macro_editor"
        self.grid_columnconfigure(0, weight=0)
        self.grid_columnconfigure(1, weight=1)
        self.configure(fg_color="#020812")
        self.sidebar.grid(row=0, column=0, sticky="nsew")
        self.main.grid(row=0, column=1, sticky="nsew", padx=18, pady=18)
        self.show_view(view)
        self.main.tkraise()

    def open_macro_editor(self):
        self.show_app_shell("conventional")

    def open_execute_screen(self):
        self.refresh_execute_macro_list()
        self.show_placeholder("execute")

    def open_settings_screen(self):
        self.show_placeholder("settings")

    def change_language(self, language):
        if self.language == language:
            return
        self.language = language
        self.texts = self.load_language(language)
        self.save_app_config()
        self.rebuild_home_and_settings()
        self.show_placeholder("settings")

    def change_theme_from_settings(self, selected_theme):
        dark_label = self.t("settings.theme_dark")
        self.theme_var.set("Dark" if selected_theme == dark_label else "Light")
        self.change_theme()
        self.save_app_config()

    def rebuild_home_and_settings(self):
        for view_name in ("home_view", "execute_view", "settings_view"):
            view = getattr(self, view_name, None)
            if view is not None:
                view.destroy()
        self.create_home_view()
        self.create_execute_view()
        self.create_settings_view()

    def create_home_view(self):
        self.home_view = ctk.CTkFrame(self, corner_radius=0, fg_color="#020812")
        self.home_view.grid(row=0, column=0, columnspan=2, sticky="nsew")
        self.home_view.grid_columnconfigure((0, 1, 2, 3), weight=1)
        self.home_view.grid_rowconfigure(0, weight=1)
        self.home_view.grid_rowconfigure(5, weight=1)

        ctk.CTkLabel(
            self.home_view,
            text=self.t("home.title"),
            font=ctk.CTkFont(size=32, weight="bold"),
        ).grid(row=1, column=0, columnspan=4, padx=24, pady=(24, 8))
        ctk.CTkLabel(
            self.home_view,
            text=self.t("home.subtitle"),
            font=ctk.CTkFont(size=16),
            text_color=("gray30", "gray78"),
        ).grid(row=2, column=0, columnspan=4, padx=24, pady=(0, 36))

        self.create_home_card(
            column=1,
            title=self.t("home.create_title"),
            description=self.t("home.create_description"),
            icon="[=]",
            accent="#168bff",
            command=self.open_macro_editor,
        )
        self.create_home_card(
            column=2,
            title=self.t("home.execute_title"),
            description=self.t("home.execute_description"),
            icon=">",
            accent="#62df45",
            command=self.open_execute_screen,
        )

        footer = ctk.CTkFrame(self.home_view, corner_radius=10, fg_color=("#eef3f8", "#07111f"))
        footer.grid(row=4, column=1, columnspan=2, padx=24, pady=(58, 0), sticky="ew")
        footer.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            footer,
            text=f"</>  {self.t('app.developer')}",
            font=ctk.CTkFont(size=15),
            text_color=("#1b6fb8", "#4aa7ff"),
        ).grid(row=0, column=0, padx=24, pady=18)

        ctk.CTkButton(
            self.home_view,
            text=self.t("home.settings"),
            height=46,
            fg_color=("#eef3f8", "#07111f"),
            hover_color=("#dfe9f4", "#0d1b2e"),
            text_color=("gray10", "gray90"),
            border_width=1,
            border_color=("#d3dbe5", "#1d2a3d"),
            command=self.open_settings_screen,
        ).grid(row=4, column=3, padx=(0, 34), pady=(58, 0), sticky="w")

    def create_home_card(self, column, title, description, icon, accent, command):
        card = ctk.CTkFrame(
            self.home_view,
            width=320,
            height=360,
            corner_radius=22,
            fg_color=("#eef6ff", "#031123"),
            border_width=2,
            border_color=accent,
        )
        card.grid(row=3, column=column, padx=20, pady=0, sticky="nsew")
        card.grid_propagate(False)
        card.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(card, text=icon, font=ctk.CTkFont(size=72, weight="bold"), text_color=accent).grid(
            row=0, column=0, padx=24, pady=(44, 22)
        )
        ctk.CTkLabel(card, text=title, font=ctk.CTkFont(size=22, weight="bold")).grid(
            row=1, column=0, padx=28, pady=(0, 14)
        )
        ctk.CTkLabel(
            card,
            text=description,
            font=ctk.CTkFont(size=15),
            text_color=("gray25", "gray78"),
            wraplength=250,
            justify="center",
        ).grid(row=2, column=0, padx=28, pady=(0, 30))
        ctk.CTkButton(
            card,
            text=">",
            width=58,
            height=58,
            corner_radius=29,
            fg_color=accent,
            hover_color=accent,
            font=ctk.CTkFont(size=28, weight="bold"),
            command=command,
        ).grid(row=3, column=0, pady=(0, 32))

    def create_sidebar(self):
        self.sidebar = ctk.CTkFrame(
            self,
            width=230,
            corner_radius=0,
            fg_color=("#eef6ff", "#07111f"),
            border_width=1,
            border_color=("#d8e0ea", "#132034"),
        )
        self.sidebar.grid(row=0, column=0, sticky="nsew")
        self.sidebar.grid_rowconfigure(5, weight=1)

        ctk.CTkButton(
            self.sidebar,
            text=f"<  {self.t('settings.back')}",
            height=36,
            fg_color=("#e7edf5", "#152033"),
            hover_color=("#d9e4f1", "#1c2b43"),
            text_color=("gray10", "gray90"),
            command=self.show_home,
        ).grid(row=0, column=0, padx=22, pady=(24, 10), sticky="ew")

        ctk.CTkLabel(
            self.sidebar,
            text="MacroFlow",
            font=ctk.CTkFont(size=22, weight="bold"),
        ).grid(row=1, column=0, padx=22, pady=(0, 16), sticky="w")

        self.conventional_nav_button = ctk.CTkButton(
            self.sidebar,
            text=self.t("macro.conventional"),
            height=38,
            command=lambda: self.show_view("conventional"),
        )
        self.conventional_nav_button.grid(row=2, column=0, padx=22, pady=(0, 8), sticky="ew")

        self.smart_nav_button = ctk.CTkButton(
            self.sidebar,
            text=self.t("macro.smart"),
            height=38,
            fg_color="#5c5f66",
            hover_color="#4d5056",
            command=lambda: self.show_view("smart"),
        )
        self.smart_nav_button.grid(row=3, column=0, padx=22, pady=(0, 12), sticky="ew")

        ctk.CTkButton(self.sidebar, text=self.t("macro.new"), height=38, command=self.new_macro).grid(
            row=4, column=0, padx=22, pady=(0, 12), sticky="ew"
        )

        self.macro_scroll = ctk.CTkScrollableFrame(self.sidebar, label_text=self.t("macro.saved"))
        self.macro_scroll.grid(row=5, column=0, padx=16, pady=(0, 16), sticky="nsew")

        self.theme_switch = ctk.CTkSwitch(
            self.sidebar,
            text=self.t("macro.dark_mode"),
            variable=self.theme_var,
            onvalue="Dark",
            offvalue="Light",
            command=self.change_theme,
        )
        self.theme_switch.select()
        self.theme_switch.grid(row=6, column=0, padx=22, pady=(0, 18), sticky="w")

    def create_main_area(self):
        self.main = ctk.CTkFrame(self, corner_radius=0, fg_color="transparent")
        self.main.grid(row=0, column=1, sticky="nsew", padx=18, pady=18)
        self.main.grid_columnconfigure(0, weight=1)
        self.main.grid_rowconfigure(1, weight=1)

        self.create_macro_shell_header()

        self.conventional_view = ctk.CTkFrame(self.main, fg_color="transparent")
        self.conventional_view.grid(row=1, column=0, sticky="nsew")
        self.conventional_view.grid_columnconfigure(0, weight=1)
        self.conventional_view.grid_rowconfigure(2, weight=1)

        self.smart_view = ctk.CTkFrame(self.main, fg_color="transparent")
        self.smart_view.grid(row=1, column=0, sticky="nsew")
        self.smart_view.grid_columnconfigure(0, weight=1)
        self.smart_view.grid_rowconfigure(2, weight=1)

        self.create_header()
        self.create_status_card()
        self.create_events_card()
        self.create_editor()
        self.create_smart_view()
        self.show_view("conventional")

    def create_macro_shell_header(self):
        header = ctk.CTkFrame(self.main, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", pady=(0, 16))
        header.grid_columnconfigure(1, weight=1)

        ctk.CTkButton(
            header,
            text="<",
            width=42,
            height=42,
            corner_radius=21,
            fg_color=("#e7edf5", "#152033"),
            hover_color=("#d9e4f1", "#1c2b43"),
            text_color=("gray10", "gray90"),
            command=self.show_home,
        ).grid(row=0, column=0, rowspan=2, padx=(0, 16), pady=4)
        self.macro_page_title = ctk.CTkLabel(
            header,
            text=self.t("macro.page_title"),
            font=ctk.CTkFont(size=28, weight="bold"),
        )
        self.macro_page_title.grid(row=0, column=1, sticky="w")
        self.macro_page_subtitle = ctk.CTkLabel(
            header,
            text=self.t("macro.page_subtitle"),
            font=ctk.CTkFont(size=14),
            text_color=("gray35", "gray72"),
        )
        self.macro_page_subtitle.grid(row=1, column=1, sticky="w", pady=(2, 0))

    def create_header(self):
        header = ctk.CTkFrame(
            self.conventional_view,
            corner_radius=10,
            fg_color=("#eef6ff", "#07111f"),
            border_width=1,
            border_color=("#d8e0ea", "#132034"),
        )
        header.grid(row=0, column=0, sticky="ew", pady=(0, 14))
        header.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(header, text=self.t("macro.macro_name"), font=ctk.CTkFont(size=14, weight="bold")).grid(
            row=0, column=0, padx=18, pady=(16, 6), sticky="w"
        )
        self.name_var = tk.StringVar()
        self.name_entry = ctk.CTkEntry(
            header,
            textvariable=self.name_var,
            height=40,
            placeholder_text=self.t("macro.name_placeholder"),
        )
        self.name_entry.grid(row=1, column=0, padx=18, pady=(0, 12), sticky="ew")

        actions = ctk.CTkFrame(header, fg_color="transparent")
        actions.grid(row=2, column=0, padx=18, pady=(0, 16), sticky="ew")

        self.record_button = ctk.CTkButton(
            actions,
            text=self.t("macro.record"),
            height=38,
            fg_color="#d63d3d",
            hover_color="#b83232",
            command=self.toggle_recording,
        )
        self.record_button.pack(side="left", padx=(0, 8))

        self.play_button = ctk.CTkButton(actions, text=self.t("macro.play"), height=38, command=self.play_current)
        self.play_button.pack(side="left", padx=8)

        ctk.CTkSwitch(actions, text=self.t("macro.loop"), variable=self.loop_playback_var).pack(side="left", padx=8)

        ctk.CTkButton(actions, text=self.t("macro.save"), height=38, command=self.save_current).pack(side="left", padx=8)
        ctk.CTkButton(
            actions,
            text=self.t("macro.clear"),
            height=38,
            fg_color="#5c5f66",
            hover_color="#4d5056",
            command=self.clear_macro,
        ).pack(side="left", padx=8)
        ctk.CTkButton(
            actions,
            text=self.t("macro.delete"),
            height=38,
            fg_color="#5c5f66",
            hover_color="#4d5056",
            command=self.delete_current,
        ).pack(side="left", padx=8)

    def create_status_card(self):
        status_card = ctk.CTkFrame(
            self.conventional_view,
            corner_radius=10,
            fg_color=("#eef6ff", "#07111f"),
            border_width=1,
            border_color=("#d8e0ea", "#132034"),
        )
        status_card.grid(row=1, column=0, sticky="ew", pady=(0, 14))
        status_card.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(status_card, text=self.t("macro.shortcuts"), font=ctk.CTkFont(weight="bold")).grid(
            row=0, column=0, padx=(18, 12), pady=(14, 6), sticky="w"
        )
        self.shortcuts_frame = ctk.CTkFrame(status_card, fg_color="transparent")
        self.shortcuts_frame.grid(row=0, column=1, padx=0, pady=(10, 6), sticky="w")
        self.render_shortcut_pills()

        ctk.CTkButton(
            status_card,
            text=self.t("macro.edit_shortcuts"),
            width=120,
            height=30,
            fg_color="#5c5f66",
            hover_color="#4d5056",
            command=self.open_shortcut_editor,
        ).grid(row=0, column=2, padx=(12, 8), pady=(10, 6), sticky="e")

        self.playback_alert = ctk.CTkLabel(
            status_card,
            text=self.t("macro.playing"),
            text_color="#22c55e",
            font=ctk.CTkFont(weight="bold"),
        )
        self.playback_alert.grid(row=0, column=3, padx=(8, 8), pady=(14, 4), sticky="e")
        self.playback_alert.grid_remove()

        self.status_var = tk.StringVar(value=self.t("macro.ready"))
        ctk.CTkLabel(status_card, textvariable=self.status_var, anchor="e").grid(
            row=0, column=4, padx=(8, 18), pady=(14, 4), sticky="e"
        )

        self.countdown_var = tk.StringVar(value="")
        self.countdown_label = ctk.CTkLabel(
            status_card,
            textvariable=self.countdown_var,
            font=ctk.CTkFont(size=18, weight="bold"),
            text_color="#ef8a2f",
        )
        self.countdown_label.grid(row=1, column=0, columnspan=5, padx=18, pady=(4, 2), sticky="w")
        self.countdown_label.grid_remove()

        ctk.CTkLabel(status_card, text=self.t("macro.live"), font=ctk.CTkFont(weight="bold")).grid(
            row=2, column=0, padx=(18, 12), pady=(4, 14), sticky="w"
        )
        self.live_inputs_var = tk.StringVar(value=self.t("macro.nothing_pressed"))
        self.live_action_var = tk.StringVar(value=self.t("macro.waiting_recording"))
        ctk.CTkLabel(status_card, textvariable=self.live_inputs_var).grid(
            row=2, column=1, padx=0, pady=(4, 14), sticky="w"
        )
        ctk.CTkLabel(status_card, textvariable=self.live_action_var, anchor="e").grid(
            row=2, column=2, padx=(12, 18), pady=(4, 14), sticky="e"
        )

    def create_events_card(self):
        table_card = ctk.CTkFrame(
            self.conventional_view,
            corner_radius=10,
            fg_color=("#eef6ff", "#07111f"),
            border_width=1,
            border_color=("#d8e0ea", "#132034"),
        )
        table_card.grid(row=2, column=0, sticky="nsew")
        table_card.grid_columnconfigure(0, weight=1)
        table_card.grid_rowconfigure(2, weight=1)

        ctk.CTkLabel(
            table_card,
            text=self.t("macro.events"),
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
        self.table.heading("t", text=self.t("macro.time"))
        self.table.heading("type", text=self.t("macro.type"))
        self.table.heading("details", text=self.t("macro.details"))
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
        editor = ctk.CTkFrame(
            self.conventional_view,
            corner_radius=10,
            fg_color=("#eef6ff", "#07111f"),
            border_width=1,
            border_color=("#d8e0ea", "#132034"),
        )
        editor.grid(row=3, column=0, sticky="ew", pady=(14, 0))
        editor.grid_columnconfigure(5, weight=1)

        self.event_time = tk.StringVar()
        self.event_type = tk.StringVar()
        self.event_data = tk.StringVar()

        ctk.CTkLabel(editor, text=self.t("macro.time")).grid(row=0, column=0, padx=(18, 6), pady=16)
        ctk.CTkEntry(editor, width=90, textvariable=self.event_time).grid(row=0, column=1, pady=16)
        ctk.CTkLabel(editor, text=self.t("macro.type")).grid(row=0, column=2, padx=(12, 6), pady=16)
        ctk.CTkEntry(editor, width=130, textvariable=self.event_type).grid(row=0, column=3, pady=16)
        ctk.CTkLabel(editor, text=self.t("macro.json_data")).grid(row=0, column=4, padx=(12, 6), pady=16)
        ctk.CTkEntry(editor, textvariable=self.event_data).grid(row=0, column=5, padx=(0, 10), pady=16, sticky="ew")
        ctk.CTkButton(editor, text=self.t("macro.apply"), width=92, command=self.apply_event_edit).grid(row=0, column=6, padx=4, pady=16)
        ctk.CTkButton(
            editor,
            text=self.t("macro.remove"),
            width=92,
            fg_color="#5c5f66",
            hover_color="#4d5056",
            command=self.remove_event,
        ).grid(row=0, column=7, padx=(4, 18), pady=16)

    def create_smart_view(self):
        header = ctk.CTkFrame(
            self.smart_view,
            corner_radius=10,
            fg_color=("#eef6ff", "#07111f"),
            border_width=1,
            border_color=("#d8e0ea", "#132034"),
        )
        header.grid(row=0, column=0, sticky="ew", pady=(0, 14))
        header.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            header,
            text=self.t("smart.title"),
            font=ctk.CTkFont(size=22, weight="bold"),
        ).grid(row=0, column=0, columnspan=4, padx=18, pady=(18, 8), sticky="w")

        ctk.CTkLabel(header, text=self.t("smart.target")).grid(row=1, column=0, padx=(18, 8), pady=(0, 18), sticky="w")
        self.smart_target_var = tk.StringVar(value="IMPREZA 22B")
        ctk.CTkEntry(
            header,
            textvariable=self.smart_target_var,
            placeholder_text=self.t("smart.target_placeholder"),
            height=38,
        ).grid(row=1, column=1, padx=(0, 8), pady=(0, 18), sticky="ew")

        ctk.CTkButton(header, text=self.t("smart.scan"), height=38, command=self.scan_smart_target).grid(
            row=1, column=2, padx=6, pady=(0, 18)
        )
        ctk.CTkButton(header, text=self.t("smart.run"), height=38, command=self.run_smart_navigation).grid(
            row=1, column=3, padx=6, pady=(0, 18)
        )
        ctk.CTkButton(
            header,
            text=self.t("smart.stop"),
            height=38,
            fg_color="#5c5f66",
            hover_color="#4d5056",
            command=self.smart_engine.stop_navigation,
        ).grid(row=1, column=4, padx=(6, 18), pady=(0, 18))

        settings = ctk.CTkFrame(
            self.smart_view,
            corner_radius=10,
            fg_color=("#eef6ff", "#07111f"),
            border_width=1,
            border_color=("#d8e0ea", "#132034"),
        )
        settings.grid(row=1, column=0, sticky="ew", pady=(0, 14))
        settings.grid_columnconfigure(3, weight=1)

        self.smart_max_steps_var = tk.StringVar(value="30")
        self.smart_delay_var = tk.StringVar(value="0.35")
        ctk.CTkLabel(settings, text=self.t("smart.max_steps")).grid(row=0, column=0, padx=(18, 8), pady=16)
        ctk.CTkEntry(settings, width=70, textvariable=self.smart_max_steps_var).grid(row=0, column=1, pady=16)
        ctk.CTkLabel(settings, text=self.t("smart.delay")).grid(row=0, column=2, padx=(18, 8), pady=16)
        ctk.CTkEntry(settings, width=70, textvariable=self.smart_delay_var).grid(row=0, column=3, pady=16, sticky="w")
        ctk.CTkButton(
            settings,
            text=self.t("smart.dependencies"),
            fg_color="#5c5f66",
            hover_color="#4d5056",
            command=self.show_smart_dependencies,
        ).grid(row=0, column=4, padx=(12, 18), pady=16)

        panel = ctk.CTkFrame(
            self.smart_view,
            corner_radius=10,
            fg_color=("#eef6ff", "#07111f"),
            border_width=1,
            border_color=("#d8e0ea", "#132034"),
        )
        panel.grid(row=2, column=0, sticky="nsew")
        panel.grid_columnconfigure(0, weight=1)
        panel.grid_rowconfigure(1, weight=1)

        ctk.CTkLabel(
            panel,
            text=self.t("smart.screen_reading"),
            font=ctk.CTkFont(size=16, weight="bold"),
        ).grid(row=0, column=0, padx=18, pady=(18, 8), sticky="w")

        self.smart_log = ctk.CTkTextbox(panel, height=260)
        self.smart_log.grid(row=1, column=0, padx=18, pady=(0, 18), sticky="nsew")
        self.set_smart_status(
            "Use esta tela para localizar um carro pelo texto na tela. "
            "O motor detecta a borda verde atual e tenta navegar com as setas ate o alvo."
        )

    def show_view(self, view):
        self.active_view = view
        if view == "smart":
            self.smart_view.tkraise()
            self.conventional_nav_button.configure(fg_color="#5c5f66", hover_color="#4d5056")
            self.smart_nav_button.configure(fg_color=("#3b8ed0", "#1f6aa5"), hover_color=("#36719f", "#144870"))
            return

        self.conventional_view.tkraise()
        self.conventional_nav_button.configure(fg_color=("#3b8ed0", "#1f6aa5"), hover_color=("#36719f", "#144870"))
        self.smart_nav_button.configure(fg_color="#5c5f66", hover_color="#4d5056")

    def set_smart_status(self, text):
        if not hasattr(self, "smart_log"):
            return
        self.smart_log.insert("end", f"{time.strftime('%H:%M:%S')}  {text}\n")
        self.smart_log.see("end")

    def show_smart_dependencies(self):
        status = self.smart_engine.dependency_status()
        lines = ["Dependencias da macro inteligente:"]
        for name, ok in status.items():
            lines.append(f"- {name}: {'OK' if ok else 'ausente'}")
        if not all(status.values()):
            lines.append("Instale as dependencias com: python -m pip install -r requirements.txt")
            lines.append("O pytesseract tambem precisa do Tesseract OCR instalado no Windows.")
        self.set_smart_status("\n".join(lines))

    def scan_smart_target(self):
        target = self.smart_target_var.get().strip()
        if not target:
            messagebox.showerror("Alvo vazio", "Digite o nome do carro alvo.")
            return
        result = self.smart_engine.scan_screen(target)
        self.set_smart_status(result["message"])
        if result.get("selected"):
            self.set_smart_status(f"Selecionado: {result['selected']}")
        if result.get("target"):
            self.set_smart_status(f"Alvo: {result['target']}")

    def run_smart_navigation(self):
        target = self.smart_target_var.get().strip()
        if not target:
            messagebox.showerror("Alvo vazio", "Digite o nome do carro alvo.")
            return
        try:
            max_steps = int(self.smart_max_steps_var.get())
            step_delay = float(self.smart_delay_var.get().replace(",", "."))
        except ValueError:
            messagebox.showerror("Configuracao invalida", "Passos max. e intervalo precisam ser numericos.")
            return
        self.smart_engine.start_navigation(target, max_steps=max_steps, step_delay=step_delay)

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
        if hasattr(self, "execute_timeline_canvas"):
            self.render_execute_timeline()

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
        elif action == "recording_countdown":
            self.on_recording_countdown(payload)
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
            if hasattr(self, "execute_play_button"):
                self.execute_play_button.configure(state="disabled" if payload else "normal")
                if payload:
                    self.start_execute_timer()
                else:
                    self.stop_execute_timer()
            self.set_playback_alert(payload)
        elif action == "play_shortcut":
            if self.active_screen == "execute":
                self.play_execute_macro()
            else:
                self.play_current()
        elif action == "stop_playback_shortcut":
            if self.active_screen == "execute":
                self.stop_execute_playback()
            else:
                self.engine.stop_playback()
        elif action == "escape":
            self.handle_close_shortcut()

    def handle_close_shortcut(self):
        if self.focus_displayof() is None:
            self.status_var.set("Esc ignorado: MacroFlow nao esta em foco.")
            return
        self.close()

    def on_recording_started(self):
        self.events = []
        self.render_events()
        self.pressed_inputs.clear()
        self.countdown_label.grid_remove()
        self.countdown_var.set("")
        self.live_inputs_var.set(self.t("macro.nothing_pressed"))
        self.live_action_var.set("Gravando agora")
        self.record_button.configure(text=self.t("macro.stop"), fg_color="#ef8a2f", hover_color="#c96f24")

    def on_recording_countdown(self, remaining):
        self.events = []
        self.render_events()
        self.pressed_inputs.clear()
        self.live_inputs_var.set(self.t("macro.nothing_pressed"))
        self.countdown_var.set(f"Gravacao comeca em {remaining}")
        self.countdown_label.grid()
        self.live_action_var.set("Preparando gravacao")
        self.record_button.configure(text=f"{remaining}...", fg_color="#ef8a2f", hover_color="#c96f24")

    def on_recording_stopped(self):
        self.pressed_inputs.clear()
        self.countdown_label.grid_remove()
        self.countdown_var.set("")
        self.live_inputs_var.set(self.t("macro.nothing_pressed"))
        self.live_action_var.set("Gravacao encerrada")
        self.set_record_button_idle()

    def change_theme(self):
        ctk.set_appearance_mode(self.theme_var.get())
        self.apply_tree_style()
        self.save_app_config()

    def render_shortcut_pills(self):
        for child in self.shortcuts_frame.winfo_children():
            child.destroy()

        for action in ("record", "play", "stop_playback", "close"):
            label = SHORTCUT_LABELS[action]
            key = shortcut_label(self.shortcuts[action])
            pill = ctk.CTkFrame(self.shortcuts_frame, corner_radius=8, fg_color=("#e8eef5", "#30343a"))
            pill.pack(side="left", padx=(0, 8))
            ctk.CTkLabel(pill, text=key, font=ctk.CTkFont(weight="bold"), width=42).pack(
                side="left", padx=(8, 4), pady=5
            )
            ctk.CTkLabel(pill, text=label, text_color=("gray25", "gray75")).pack(
                side="left", padx=(0, 8), pady=5
            )

    def open_shortcut_editor(self):
        ShortcutEditor(self, dict(self.shortcuts))

    def apply_shortcuts(self, shortcuts):
        normalized = {action: normalize_shortcut(value) for action, value in shortcuts.items()}
        values = list(normalized.values())
        if any(not value for value in values):
            messagebox.showerror("Atalho invalido", "Todos os atalhos precisam ter valor.")
            return False
        invalid = [shortcut_label(value) for value in values if not is_valid_shortcut(value)]
        if invalid:
            messagebox.showerror(
                "Atalho invalido",
                "Use teclas simples como F8, F9, F10, Esc, Enter, Ctrl, Alt ou letras/numeros.\n"
                f"Invalidos: {', '.join(invalid)}",
            )
            return False
        if len(set(values)) != len(values):
            messagebox.showerror("Atalho duplicado", "Cada acao precisa ter um atalho diferente.")
            return False

        self.shortcuts = normalized
        self.engine.set_shortcuts(normalized)
        self.save_shortcuts()
        self.render_shortcut_pills()
        self.status_var.set("Atalhos atualizados.")
        return True

    def reset_shortcuts(self):
        self.apply_shortcuts(dict(DEFAULT_SHORTCUTS))

    def load_shortcuts(self):
        if not SHORTCUTS_FILE.exists():
            return dict(DEFAULT_SHORTCUTS)
        try:
            data = json.loads(SHORTCUTS_FILE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return dict(DEFAULT_SHORTCUTS)

        shortcuts = dict(DEFAULT_SHORTCUTS)
        for action in shortcuts:
            if action in data:
                shortcuts[action] = normalize_shortcut(str(data[action]))
        values = list(shortcuts.values())
        if any(not is_valid_shortcut(value) for value in values) or len(set(values)) != len(values):
            return dict(DEFAULT_SHORTCUTS)
        return shortcuts

    def save_shortcuts(self):
        SHORTCUTS_FILE.write_text(json.dumps(self.shortcuts, indent=2), encoding="utf-8")

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

    def start_execute_timer(self):
        self.execute_timer_running = True
        self.execute_timer_started_at = time.perf_counter()
        if hasattr(self, "execute_elapsed_var"):
            self.execute_elapsed_var.set("00:00:00")
        self.update_execute_timer()

    def stop_execute_timer(self):
        self.execute_timer_running = False
        if hasattr(self, "execute_elapsed_var"):
            self.execute_elapsed_var.set("00:00:00")
        self.set_execute_lights("idle")

    def update_execute_timer(self):
        if not self.execute_timer_running or not hasattr(self, "execute_elapsed_var"):
            return

        elapsed = int(time.perf_counter() - self.execute_timer_started_at)
        hours = elapsed // 3600
        minutes = (elapsed % 3600) // 60
        seconds = elapsed % 60
        self.execute_elapsed_var.set(f"{hours:02d}:{minutes:02d}:{seconds:02d}")
        self.after(250, self.update_execute_timer)

    def set_execute_lights(self, state, red_count=0):
        if not hasattr(self, "execute_lights"):
            return
        colors = {
            "idle": "#4b5563",
            "red": "#ef4444",
            "green": "#22c55e",
        }
        for index, light in enumerate(self.execute_lights):
            if state == "green":
                color = colors["green"]
            elif state == "red" and index < red_count:
                color = colors["red"]
            else:
                color = colors["idle"]
            light.configure(fg_color=color)

    def start_execute_countdown(self):
        if self.execute_countdown_active or self.engine.playing:
            return
        self.execute_countdown_active = True
        self.execute_countdown_step = 0
        self.execute_play_button.configure(state="disabled")
        self.execute_status_label.configure(text=self.t("execute.starting"))
        self.execute_elapsed_var.set("00:00:00")
        self.set_execute_lights("idle")
        self.advance_execute_countdown()

    def advance_execute_countdown(self):
        if not self.execute_countdown_active:
            return
        self.execute_countdown_step += 1
        if self.execute_countdown_step <= 3:
            self.set_execute_lights("red", self.execute_countdown_step)
            self.execute_countdown_after_id = self.after(1000, self.advance_execute_countdown)
            return

        self.execute_countdown_active = False
        self.execute_countdown_after_id = None
        self.set_execute_lights("green")
        self.engine.play_events(list(self.execute_selected_events), loop=self.execute_loop_var.get())

    def cancel_execute_countdown(self):
        if not self.execute_countdown_active:
            return False
        self.execute_countdown_active = False
        if self.execute_countdown_after_id is not None:
            self.after_cancel(self.execute_countdown_after_id)
            self.execute_countdown_after_id = None
        self.execute_play_button.configure(state="normal")
        self.execute_status_label.configure(
            text=self.execute_selected_path.stem if self.execute_selected_path else self.t("execute.none")
        )
        self.execute_elapsed_var.set("00:00:00")
        self.set_execute_lights("idle")
        return True

    def update_live_inputs(self):
        text = " + ".join(sorted(self.pressed_inputs)) if self.pressed_inputs else self.t("macro.nothing_pressed")
        self.live_inputs_var.set(text)

    def toggle_recording(self):
        if self.engine.recording:
            self.engine.stop_recording()
            self.set_record_button_idle()
        elif self.engine.recording_pending:
            self.engine.stop_recording()
            self.set_record_button_idle()
        else:
            self.engine.start_recording()
            self.record_button.configure(text="3...", fg_color="#ef8a2f", hover_color="#c96f24")

    def set_record_button_idle(self):
        self.record_button.configure(text=self.t("macro.record"), fg_color="#d63d3d", hover_color="#b83232")

    def play_current(self):
        self.sync_events_from_engine()
        self.engine.play_events(list(self.events), loop=self.loop_playback_var.get())

    def new_macro(self):
        self.current_file = None
        self.selected_macro_path = None
        self.events = []
        self.engine.events = []
        self.name_var.set("")
        self.render_events()
        self.update_macro_selection()
        self.live_inputs_var.set(self.t("macro.nothing_pressed"))
        self.live_action_var.set(self.t("macro.waiting_recording"))
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
        if hasattr(self, "execute_macro_scroll"):
            self.refresh_execute_macro_list(select_path=path)
        self.status_var.set(f"Macro salva: {path.name}")

    def load_macro(self, path):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            messagebox.showerror("Macro invalida", f"Nao foi possivel carregar {path.name}.\n\n{exc}")
            self.status_var.set(f"Erro ao carregar macro: {path.name}")
            return

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
        if hasattr(self, "execute_macro_scroll"):
            self.refresh_execute_macro_list()

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

    def refresh_execute_macro_list(self, select_path=None):
        for button, _path in self.execute_macro_buttons:
            button.destroy()
        self.execute_macro_buttons = []
        self.execute_macro_paths = sorted(MACROS_DIR.glob("*.json"))

        for index, path in enumerate(self.execute_macro_paths):
            button = ctk.CTkButton(
                self.execute_macro_scroll,
                text=path.stem,
                anchor="w",
                fg_color="transparent",
                text_color=("gray10", "gray90"),
                hover_color=("#d8e6f3", "#1b2b42"),
                command=lambda selected=path: self.select_execute_macro(selected),
                border_width=0,
            )
            button.grid(row=index, column=0, sticky="ew", padx=4, pady=4)
            self.execute_macro_buttons.append((button, path))

        if select_path in self.execute_macro_paths:
            self.select_execute_macro(select_path)
        elif self.execute_selected_path not in self.execute_macro_paths:
            self.clear_execute_selection()
        else:
            self.update_execute_macro_selection()

    def select_execute_macro(self, path):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            messagebox.showerror("Macro invalida", f"Nao foi possivel carregar {path.name}.\n\n{exc}")
            return

        self.execute_selected_path = path
        self.execute_selected_events = data.get("events", [])
        name = data.get("name") or path.stem
        duration = self.macro_duration(self.execute_selected_events)
        self.execute_summary_var.set(
            f"{name} | {len(self.execute_selected_events)} {self.t('execute.events')} | "
            f"{self.t('execute.duration')}: {duration}"
        )
        self.execute_status_label.configure(text=name)
        self.update_execute_macro_selection()
        self.render_execute_timeline()

    def clear_execute_selection(self):
        self.execute_selected_path = None
        self.execute_selected_events = []
        if hasattr(self, "execute_summary_var"):
            self.execute_summary_var.set(self.t("execute.select_hint"))
            self.execute_status_label.configure(text=self.t("execute.none"))
            self.render_execute_timeline()

    def update_execute_macro_selection(self):
        for button, path in self.execute_macro_buttons:
            if self.execute_selected_path == path:
                button.configure(
                    fg_color=("#d8ecff", "#14395c"),
                    hover_color=("#c7e2fb", "#1d4f7a"),
                    border_width=2,
                    border_color="#62df45",
                    text_color=("#0f172a", "#ffffff"),
                )
            else:
                button.configure(
                    fg_color="transparent",
                    hover_color=("#d8e6f3", "#1b2b42"),
                    border_width=0,
                    text_color=("gray10", "gray90"),
                )

    def render_execute_timeline(self):
        dark = self.theme_var.get() == "Dark"
        render_timeline(self.execute_timeline_canvas, self.execute_selected_events, dark)

    def macro_duration(self, events):
        if not events:
            return "0s"
        last_event = max(events, key=lambda event: float(event.get("t", 0)))
        duration = float(last_event.get("t", 0)) + float(last_event.get("duration", 0))
        if duration >= 1:
            return f"{duration:.1f}s"
        return f"{int(duration * 1000)}ms"

    def play_execute_macro(self):
        if not self.execute_selected_events:
            self.status_var.set(self.t("execute.select_hint"))
            return
        self.start_execute_countdown()

    def stop_execute_playback(self):
        if self.cancel_execute_countdown():
            return
        self.engine.stop_playback()

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
            if not data["type"]:
                raise ValueError("Tipo nao pode ficar vazio.")
            if data["type"] not in {"mouse_move", "mouse_click", "mouse_scroll", "key", "key_hold"}:
                raise ValueError(f"Tipo desconhecido: {data['type']}")
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
            self.engine.stop_playback()
            self.smart_engine.stop_navigation()
            self.mouse_listener.stop()
            self.keyboard_listener.stop()
        finally:
            self.destroy()

    @staticmethod
    def safe_macro_name(name):
        return "".join(ch for ch in name if ch.isalnum() or ch in (" ", "-", "_")).strip()


class ShortcutEditor(ctk.CTkToplevel):
    def __init__(self, app, shortcuts):
        super().__init__(app)
        self.app = app
        self.title("Editar atalhos")
        self.geometry("460x340")
        self.resizable(False, False)
        self.transient(app)
        self.grab_set()

        self.entries = {}
        self.create_widgets(shortcuts)

    def create_widgets(self, shortcuts):
        self.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            self,
            text="Atalhos padrao",
            font=ctk.CTkFont(size=18, weight="bold"),
        ).grid(row=0, column=0, columnspan=2, padx=22, pady=(22, 8), sticky="w")

        ctk.CTkLabel(
            self,
            text="Use nomes como F8, F9, F10, Esc, Ctrl, Alt ou letras simples.",
            text_color=("gray35", "gray75"),
        ).grid(row=1, column=0, columnspan=2, padx=22, pady=(0, 16), sticky="w")

        for row, action in enumerate(("record", "play", "stop_playback", "close"), start=2):
            ctk.CTkLabel(self, text=SHORTCUT_LABELS[action]).grid(
                row=row, column=0, padx=(22, 12), pady=8, sticky="w"
            )
            entry = ctk.CTkEntry(self)
            entry.insert(0, shortcut_label(shortcuts[action]))
            entry.grid(row=row, column=1, padx=(0, 22), pady=8, sticky="ew")
            self.entries[action] = entry

        buttons = ctk.CTkFrame(self, fg_color="transparent")
        buttons.grid(row=6, column=0, columnspan=2, padx=22, pady=(18, 22), sticky="ew")

        ctk.CTkButton(
            buttons,
            text="Restaurar padrao",
            fg_color="#5c5f66",
            hover_color="#4d5056",
            command=self.restore_defaults,
        ).pack(side="left")
        ctk.CTkButton(buttons, text="Cancelar", fg_color="#5c5f66", hover_color="#4d5056", command=self.destroy).pack(
            side="right", padx=(8, 0)
        )
        ctk.CTkButton(buttons, text="Salvar", command=self.save).pack(side="right")

    def restore_defaults(self):
        for action, value in DEFAULT_SHORTCUTS.items():
            self.entries[action].delete(0, tk.END)
            self.entries[action].insert(0, shortcut_label(value))

    def save(self):
        shortcuts = {action: entry.get() for action, entry in self.entries.items()}
        if self.app.apply_shortcuts(shortcuts):
            self.destroy()


def main():
    app = MacroApp()
    app.mainloop()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
