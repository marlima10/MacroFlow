import json
import queue
import re
import subprocess
import sys
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

import customtkinter as ctk
from PIL import Image
from pynput import keyboard, mouse

from .constants import (
    APP_CONFIG_FILE,
    APP_ICON_FILE,
    APP_ICON_PNG_FILE,
    DEFAULT_SHORTCUTS,
    FARM_CONFIG_FILE,
    FOLDER_ICON_FILE,
    LANGUAGE_DIR,
    MANUAL_DIR,
    MACROS_DIR,
    SHORTCUT_LABELS,
    SHORTCUTS_FILE,
    SPLASH_IMAGE_FILE,
    TELEGRAM_CONFIG_FILE,
)
from .engine import (
    DEFAULT_MATRIX_STEP_DELAY,
    MacroEngine,
    build_matrix_navigation_events,
    matrix_target_for_repeat,
    normalize_playback_events,
    resolve_playlist_item_for_repeat,
)
from .application.use_cases.calculate_last_car_position import CalculateLastCarPosition
from .application.use_cases.save_macro import SaveMacro
from .application.use_cases.send_telegram_notification import SendTelegramNotification
from .domain.entities.telegram_config import TelegramConfig
from .domain.value_objects.matrix_position import MatrixPosition
from .infrastructure.notification.telegram_notifier import TelegramNotifier
from .infrastructure.repositories.json_config_repository import JsonAppConfigRepository, JsonFarmConfigRepository
from .infrastructure.repositories.json_language_repository import JsonLanguageRepository
from .infrastructure.repositories.json_macro_repository import JsonMacroRepository
from .infrastructure.repositories.json_shortcut_repository import JsonShortcutRepository
from .infrastructure.repositories.json_telegram_config_repository import JsonTelegramConfigRepository
from .input_utils import event_details, is_valid_shortcut, normalize_shortcut, shortcut_label
from .smart_engine import SmartMacroEngine
from .timeline import render_timeline


DEFAULT_MACRO_COLOR = "#07111f"
HOME_CARD_WIDTH = 205
HOME_CARD_HEIGHT = 300
HOME_CARD_ICON_SIZE = 74
MACRO_COLOR_PALETTE = (
    DEFAULT_MACRO_COLOR,
    "#14395c",
    "#1d4f7a",
    "#3b1764",
    "#14532d",
    "#7f1d1d",
    "#78350f",
    "#334155",
)


def patch_customtkinter_entry_placeholder():
    if getattr(ctk.CTkEntry, "_macroflow_placeholder_patch", False):
        return
    original_activate_placeholder = ctk.CTkEntry._activate_placeholder
    original_textvariable_callback = ctk.CTkEntry._textvariable_callback

    def should_ignore_destroyed_widget_error(exc):
        return isinstance(exc, tk.TclError) and "invalid command name" in str(exc)

    def safe_activate_placeholder(self):
        try:
            original_activate_placeholder(self)
        except tk.TclError as exc:
            if not should_ignore_destroyed_widget_error(exc):
                raise

    def safe_textvariable_callback(self, *args):
        try:
            original_textvariable_callback(self, *args)
        except tk.TclError as exc:
            if not should_ignore_destroyed_widget_error(exc):
                raise

    ctk.CTkEntry._activate_placeholder = safe_activate_placeholder
    ctk.CTkEntry._textvariable_callback = safe_textvariable_callback
    ctk.CTkEntry._macroflow_placeholder_patch = True


patch_customtkinter_entry_placeholder()


class MacroApp(ctk.CTk):
    def __init__(self):
        self.app_config_repository = JsonAppConfigRepository(APP_CONFIG_FILE)
        self.farm_config_repository = JsonFarmConfigRepository(FARM_CONFIG_FILE)
        self.language_repository = JsonLanguageRepository(LANGUAGE_DIR)
        self.shortcut_repository = JsonShortcutRepository(SHORTCUTS_FILE, DEFAULT_SHORTCUTS)
        self.telegram_config_repository = JsonTelegramConfigRepository(TELEGRAM_CONFIG_FILE)
        self.macro_repository = JsonMacroRepository()
        self.save_macro_use_case = SaveMacro(self.macro_repository)
        self.calculate_last_car_position_use_case = CalculateLastCarPosition()
        self.send_telegram_notification_use_case = SendTelegramNotification(TelegramNotifier())
        self.app_config = self.load_app_config()
        ctk.set_appearance_mode(self.app_config["theme"])
        ctk.set_default_color_theme("blue")
        super().__init__()

        self.title("MacroFlow")
        self.geometry("1240x876")
        self.minsize(1240, 876)
        self.set_window_icon()
        self.after(250, self.set_window_icon)
        self.after(1000, self.set_window_icon)
        self.withdraw()
        splash_visible = self.show_splash_screen()

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
        self.playlist_macro_buttons = []
        self.playlist_macro_paths = []
        self.playlist_selected_path = None
        self.playlist_items = []
        self.playlist_selected_index = None
        self.farm_items = []
        self.farm_config = self.load_farm_config()
        self.telegram_config = self.load_telegram_config()
        self.selected_macro_path = None
        self.pressed_inputs = set()
        self.language = self.app_config["language"]
        self.texts = self.load_language(self.language)
        self.theme_var = tk.StringVar(value=self.app_config["theme"])
        self.startup_var = tk.BooleanVar(value=self.app_config["start_with_windows"])
        self.farm_mode_var = tk.BooleanVar(value=self.app_config["farm_mode"])
        self.telegram_enabled_var = tk.BooleanVar(value=self.telegram_config.enabled)
        self.telegram_bot_token_var = tk.StringVar(value=self.telegram_config.bot_token)
        self.telegram_chat_id_var = tk.StringVar(value=self.telegram_config.chat_id)
        self.telegram_status_var = tk.StringVar(value="")
        self.last_notified_farm_macro = None
        self.order_var = tk.StringVar()
        self.brand_position_var = tk.BooleanVar(value=False)
        self.car_position_var = tk.BooleanVar(value=False)
        self.last_car_position_var = tk.BooleanVar(value=False)
        self.repeat_enabled_var = tk.BooleanVar(value=False)
        self.mastery_var = tk.BooleanVar(value=False)
        self.manual_var = tk.StringVar(value="")
        self.color_var = tk.StringVar(value=DEFAULT_MACRO_COLOR)
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
        self.record_timer_running = False
        self.record_timer_started_at = 0.0
        self.playlist_timer_running = False
        self.playlist_timer_started_at = 0.0
        self.farm_timer_running = False
        self.farm_timer_started_at = 0.0

        self.create_widgets()
        self.apply_tree_style()
        self.refresh_macro_list()
        self.start_listeners()
        self.after(100, self.process_queue)
        self.after(2200 if splash_visible else 0, self.close_splash_screen)
        self.protocol("WM_DELETE_WINDOW", self.close)

    def show_splash_screen(self):
        if not SPLASH_IMAGE_FILE.exists():
            return False
        try:
            image = tk.PhotoImage(file=str(SPLASH_IMAGE_FILE))
        except tk.TclError:
            return False
        while image.width() > 760 or image.height() > 600:
            image = image.subsample(2, 2)
        self.splash_image = image
        self.splash_window = tk.Toplevel(self)
        self.splash_window.overrideredirect(True)
        self.splash_window.attributes("-topmost", True)
        self.splash_window.configure(bg="#020812")
        label = tk.Label(self.splash_window, image=self.splash_image, borderwidth=0, highlightthickness=0, bg="#020812")
        label.pack()
        width = self.splash_image.width()
        height = self.splash_image.height()
        x = max(0, (self.winfo_screenwidth() - width) // 2)
        y = max(0, (self.winfo_screenheight() - height) // 2)
        self.splash_window.geometry(f"{width}x{height}+{x}+{y}")
        return True

    def close_splash_screen(self):
        splash = getattr(self, "splash_window", None)
        if splash is not None and splash.winfo_exists():
            splash.destroy()
        self.splash_window = None
        self.deiconify()
        self.lift()
        self.focus_force()

    def load_app_config(self):
        return self.app_config_repository.load()

    def save_app_config(self):
        self.app_config.update(
            {
                "language": self.language,
                "theme": self.theme_var.get(),
                "start_with_windows": self.startup_var.get(),
                "farm_mode": self.farm_mode_var.get(),
            }
        )
        self.app_config_repository.save(self.app_config)

    def load_farm_config(self):
        return self.farm_config_repository.load()

    def load_telegram_config(self):
        return self.telegram_config_repository.load()

    def current_telegram_config(self):
        return TelegramConfig(
            enabled=bool(self.telegram_enabled_var.get()) if hasattr(self, "telegram_enabled_var") else False,
            bot_token=self.telegram_bot_token_var.get().strip() if hasattr(self, "telegram_bot_token_var") else "",
            chat_id=self.telegram_chat_id_var.get().strip() if hasattr(self, "telegram_chat_id_var") else "",
        )

    def save_telegram_config(self):
        self.telegram_config = self.current_telegram_config()
        self.telegram_config_repository.save(self.telegram_config)
        if hasattr(self, "telegram_status_var"):
            self.telegram_status_var.set(self.t("settings.telegram_saved"))

    def send_telegram_test_message(self):
        self.save_telegram_config()
        self.telegram_status_var.set(self.t("settings.telegram_testing"))
        message = self.telegram_message(
            self.t("telegram.test_title"),
            self.t("telegram.test_message"),
        )
        self.send_telegram_notification_use_case.test_async(
            self.telegram_config,
            message,
            self.on_telegram_test_result,
        )

    def on_telegram_test_result(self, success, error):
        status = self.t("settings.telegram_test_ok") if success else f"{self.t('settings.telegram_test_error')} {error}"
        self.ui_queue.put(("telegram_status", status))

    def notify_telegram(self, message, config=None):
        telegram_config = config or self.telegram_config
        self.send_telegram_notification_use_case.execute_async(
            telegram_config,
            message,
            self.on_telegram_notification_result,
        )

    def on_telegram_notification_result(self, success, error):
        if success:
            return
        self.ui_queue.put(("farm_log", f"{self.t('telegram.send_error')} {error}"))

    def telegram_message(self, title, *lines):
        parts = ["MacroFlow", title]
        parts.extend(line for line in lines if line)
        parts.append(f"{self.t('telegram.datetime')}: {time.strftime('%d/%m/%Y %H:%M:%S')}")
        return "\n".join(parts)

    @staticmethod
    def format_elapsed_seconds(total_seconds):
        seconds = max(0, int(total_seconds))
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        seconds = seconds % 60
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"

    def save_farm_config(self):
        data = {
            "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "interval_ms": self.farm_interval_var.get() if hasattr(self, "farm_interval_var") else 1000,
            "roulette_quantity": self.farm_roulette_quantity_var.get() if hasattr(self, "farm_roulette_quantity_var") else 1,
            "shutdown_on_finish": bool(self.farm_shutdown_var.get()) if hasattr(self, "farm_shutdown_var") else False,
            "positions": self.current_farm_positions_config(),
            "macros": {},
        }
        for item in getattr(self, "farm_items", []):
            data["macros"][self.farm_macro_config_key(item)] = {
                "name": item.get("name"),
                "ordem": item.get("ordem"),
                "cor": self.normalized_macro_color(item),
                "ignorarItem": bool(item["ignore_var"].get()),
                "possicaoMarca": bool(item.get("possicaoMarca", False)),
                "posicaoCarro": bool(item.get("posicaoCarro", False)),
                "posicaoUltimoCarro": bool(item.get("posicaoUltimoCarro", False)),
                "ativarRepeticao": bool(item.get("ativarRepeticao", False)),
                "maestria": bool(item.get("maestria", False)),
            }
        self.farm_config_repository.save(data)
        self.farm_config = data

    def current_farm_positions_config(self):
        return {
            "brand": {
                "cima": self.farm_brand_up_var.get() if hasattr(self, "farm_brand_up_var") else 0,
                "baixo": self.farm_brand_down_var.get() if hasattr(self, "farm_brand_down_var") else 0,
                "esquerda": self.farm_brand_left_var.get() if hasattr(self, "farm_brand_left_var") else 0,
                "direita": self.farm_brand_right_var.get() if hasattr(self, "farm_brand_right_var") else 0,
            },
            "car": {
                "linha": self.farm_car_row_var.get() if hasattr(self, "farm_car_row_var") else 1,
                "coluna": self.farm_car_column_var.get() if hasattr(self, "farm_car_column_var") else 1,
            },
            "last_car": {
                "linha": self.farm_last_car_row_var.get() if hasattr(self, "farm_last_car_row_var") else 1,
                "coluna": self.farm_last_car_column_var.get() if hasattr(self, "farm_last_car_column_var") else 1,
            },
        }

    def load_language(self, language):
        return self.language_repository.load(language)

    def t(self, key):
        value = self.texts
        for part in key.split("."):
            if not isinstance(value, dict) or part not in value:
                return key
            value = value[part]
        return value

    def set_window_icon(self):
        if APP_ICON_PNG_FILE.exists():
            try:
                self.window_icon = tk.PhotoImage(file=str(APP_ICON_PNG_FILE))
                self.iconphoto(True, self.window_icon)
            except tk.TclError:
                self.window_icon = None
        try:
            if APP_ICON_FILE.exists():
                self.iconbitmap(default=str(APP_ICON_FILE))
        except tk.TclError:
            pass

    def create_widgets(self):
        self.grid_columnconfigure(0, weight=0)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self.create_home_view()
        self.create_farm_view()
        self.create_playlist_view()
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

    def create_playlist_view(self):
        self.playlist_view = ctk.CTkFrame(self, corner_radius=0, fg_color="#020812")
        self.playlist_view.grid(row=0, column=0, columnspan=2, sticky="nsew")
        self.playlist_view.grid_columnconfigure(0, weight=0)
        self.playlist_view.grid_columnconfigure(1, weight=1)
        self.playlist_view.grid_rowconfigure(1, weight=1)

        header = ctk.CTkFrame(self.playlist_view, fg_color="transparent")
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
        ctk.CTkLabel(header, text=self.t("playlist.title"), font=ctk.CTkFont(size=28, weight="bold")).grid(
            row=0, column=1, sticky="w"
        )
        ctk.CTkLabel(
            header,
            text=self.t("playlist.description"),
            font=ctk.CTkFont(size=14),
            text_color=("gray35", "gray72"),
        ).grid(row=1, column=1, sticky="w", pady=(2, 0))

        list_card = self.create_execute_card(self.playlist_view)
        list_card.grid(row=1, column=0, padx=(34, 10), pady=(0, 24), sticky="nsew")
        list_card.grid_rowconfigure(1, weight=1)
        ctk.CTkLabel(
            list_card,
            text=self.t("playlist.saved_macros"),
            font=ctk.CTkFont(size=16, weight="bold"),
        ).grid(row=0, column=0, padx=18, pady=(18, 8), sticky="w")
        self.playlist_macro_scroll = ctk.CTkScrollableFrame(list_card, fg_color="transparent")
        self.playlist_macro_scroll.grid(row=1, column=0, padx=14, pady=(0, 14), sticky="nsew")
        self.playlist_macro_scroll.grid_columnconfigure(0, weight=1)

        content = ctk.CTkFrame(self.playlist_view, fg_color="transparent")
        content.grid(row=1, column=1, padx=(10, 34), pady=(0, 24), sticky="nsew")
        content.grid_columnconfigure(0, weight=1)
        content.grid_rowconfigure(2, weight=1)

        controls = self.create_execute_card(content)
        controls.grid(row=0, column=0, sticky="ew", pady=(0, 14))
        controls.grid_columnconfigure(4, weight=1)
        self.playlist_selected_var = tk.StringVar(value=self.t("playlist.select_hint"))
        ctk.CTkLabel(controls, textvariable=self.playlist_selected_var, text_color=("gray35", "gray72")).grid(
            row=0, column=0, columnspan=5, padx=18, pady=(18, 8), sticky="w"
        )
        ctk.CTkButton(controls, text=self.t("playlist.add"), height=38, command=self.add_selected_macro_to_playlist).grid(
            row=1, column=0, padx=(18, 8), pady=(0, 18), sticky="ew"
        )
        ctk.CTkLabel(controls, text=self.t("playlist.repeats")).grid(row=1, column=1, padx=(8, 6), pady=(0, 18))
        self.playlist_repeats_var = tk.StringVar(value="1")
        ctk.CTkEntry(controls, width=72, textvariable=self.playlist_repeats_var).grid(
            row=1, column=2, padx=(0, 8), pady=(0, 18)
        )
        self.playlist_play_button = ctk.CTkButton(
            controls,
            text=f"{shortcut_label(self.shortcuts['play_playlist'])}  {self.t('playlist.play')}",
            height=38,
            command=self.play_playlist,
        )
        self.playlist_play_button.grid(
            row=1, column=3, padx=8, pady=(0, 18), sticky="ew"
        )
        self.playlist_stop_button = ctk.CTkButton(
            controls,
            text=f"{shortcut_label(self.shortcuts['stop_playlist'])}  {self.t('playlist.stop')}",
            height=38,
            fg_color="#5c5f66",
            hover_color="#4d5056",
            command=self.engine.stop_playback,
        )
        self.playlist_stop_button.grid(row=1, column=4, padx=(8, 18), pady=(0, 18), sticky="e")

        status_card = self.create_execute_card(content)
        status_card.grid(row=1, column=0, sticky="ew", pady=(0, 14))
        status_card.grid_columnconfigure((0, 1, 2), weight=1, uniform="playlist_status")
        ctk.CTkLabel(
            status_card,
            text=self.t("playlist.current_macro").upper(),
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=("gray35", "gray70"),
        ).grid(row=0, column=0, padx=18, pady=(18, 6), sticky="w")
        ctk.CTkLabel(
            status_card,
            text=self.t("playlist.elapsed_time").upper(),
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=("gray35", "gray70"),
        ).grid(row=0, column=1, padx=18, pady=(18, 6), sticky="w")
        ctk.CTkLabel(
            status_card,
            text=self.t("playlist.progress").upper(),
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=("gray35", "gray70"),
        ).grid(row=0, column=2, padx=18, pady=(18, 6), sticky="w")
        self.playlist_current_var = tk.StringVar(value="-")
        self.playlist_elapsed_var = tk.StringVar(value="00:00:00")
        self.playlist_progress_var = tk.StringVar(value="-")
        ctk.CTkLabel(
            status_card,
            textvariable=self.playlist_current_var,
            font=ctk.CTkFont(size=18, weight="bold"),
        ).grid(row=1, column=0, padx=18, pady=(0, 18), sticky="w")
        ctk.CTkLabel(
            status_card,
            textvariable=self.playlist_elapsed_var,
            font=ctk.CTkFont(size=24, weight="bold"),
            text_color="#a855f7",
        ).grid(row=1, column=1, padx=18, pady=(0, 18), sticky="w")
        ctk.CTkLabel(
            status_card,
            textvariable=self.playlist_progress_var,
            font=ctk.CTkFont(size=24, weight="bold"),
            text_color="#a855f7",
        ).grid(row=1, column=2, padx=18, pady=(0, 18), sticky="w")

        sequence = self.create_execute_card(content)
        sequence.grid(row=2, column=0, sticky="nsew")
        sequence.grid_columnconfigure(0, weight=1)
        sequence.grid_rowconfigure(1, weight=1)
        ctk.CTkLabel(
            sequence,
            text=self.t("playlist.sequence"),
            font=ctk.CTkFont(size=16, weight="bold"),
        ).grid(row=0, column=0, padx=18, pady=(18, 8), sticky="w")
        self.playlist_sequence_scroll = ctk.CTkScrollableFrame(sequence, fg_color="transparent")
        self.playlist_sequence_scroll.grid(row=1, column=0, padx=14, pady=(0, 10), sticky="nsew")
        self.playlist_sequence_scroll.grid_columnconfigure(0, weight=1)

        actions = ctk.CTkFrame(sequence, fg_color="transparent")
        actions.grid(row=2, column=0, padx=18, pady=(0, 18), sticky="ew")
        ctk.CTkButton(
            actions,
            text=self.t("playlist.remove"),
            fg_color="#5c5f66",
            hover_color="#4d5056",
            command=self.remove_selected_playlist_item,
        ).pack(side="left", padx=(0, 8))
        ctk.CTkButton(
            actions,
            text=self.t("playlist.clear"),
            fg_color="#5c5f66",
            hover_color="#4d5056",
            command=self.clear_playlist,
        ).pack(side="left")

        self.playlist_view.grid_remove()
        self.refresh_playlist_macro_list()
        self.render_playlist_items()

    def create_farm_view(self):
        self.farm_view = ctk.CTkFrame(self, corner_radius=0, fg_color="#020812")
        self.farm_view.grid(row=0, column=0, columnspan=2, sticky="nsew")
        self.farm_view.grid_columnconfigure(0, weight=1)
        self.farm_view.grid_columnconfigure(1, weight=0, minsize=330)
        self.farm_view.grid_rowconfigure(4, weight=1)

        header = ctk.CTkFrame(self.farm_view, fg_color="transparent")
        header.grid(row=0, column=0, columnspan=2, padx=18, pady=(14, 12), sticky="ew")
        header.grid_columnconfigure(1, weight=1)
        ctk.CTkButton(
            header,
            text="‹",
            width=38,
            height=38,
            corner_radius=19,
            fg_color=("#e7edf5", "#152033"),
            hover_color=("#d9e4f1", "#1c2b43"),
            text_color=("gray10", "gray90"),
            command=self.show_home,
        ).grid(row=0, column=0, padx=(0, 14), sticky="w")
        ctk.CTkLabel(
            header,
            text=f"◆  {self.t('farm.title')}",
            font=ctk.CTkFont(size=24, weight="bold"),
        ).grid(row=0, column=1)

        controls = self.create_execute_card(self.farm_view)
        controls.grid(row=1, column=0, padx=(18, 10), pady=(0, 12), sticky="ew")
        controls.grid_columnconfigure(3, weight=1)
        ctk.CTkLabel(
            controls,
            text=f"⏱  {self.t('farm.interval')}",
            font=ctk.CTkFont(size=14, weight="bold"),
        ).grid(row=0, column=0, padx=(22, 10), pady=14)
        self.farm_interval_var = tk.StringVar(value=str(self.farm_config.get("interval_ms", 1000)))
        ctk.CTkEntry(controls, width=112, textvariable=self.farm_interval_var).grid(row=0, column=1, pady=14)
        ctk.CTkLabel(controls, text="ms").grid(row=0, column=2, padx=(8, 24), pady=14)
        self.farm_play_button = ctk.CTkButton(
            controls,
            text=f"▶  {shortcut_label(self.shortcuts['play_playlist'])} {self.t('farm.play')}",
            height=38,
            command=self.play_farm,
        )
        self.farm_play_button.grid(row=0, column=3, padx=(0, 12), pady=14, sticky="ew")
        self.farm_stop_button = ctk.CTkButton(
            controls,
            text=f"■  {shortcut_label(self.shortcuts['stop_playlist'])} {self.t('farm.stop')}",
            height=38,
            fg_color="#5c5f66",
            hover_color="#4d5056",
            command=self.engine.stop_playback,
        )
        self.farm_stop_button.grid(row=0, column=4, padx=(0, 22), pady=14, sticky="ew")
        self.farm_shutdown_var = tk.BooleanVar(value=bool(self.farm_config.get("shutdown_on_finish", False)))

        self.create_farm_positions_panel(self.farm_view).grid(row=2, column=0, padx=(18, 10), pady=(0, 12), sticky="ew")

        status = self.create_execute_card(self.farm_view)
        status.grid(row=3, column=0, padx=(18, 10), pady=(0, 12), sticky="ew")
        status.grid_columnconfigure((0, 1, 2), weight=1, uniform="farm_status")
        self.farm_current_var = tk.StringVar(value="-")
        self.farm_elapsed_var = tk.StringVar(value="00:00:00")
        self.farm_progress_var = tk.StringVar(value="-")
        for column, (label, variable, size) in enumerate(
            (
                (f"●  {self.t('farm.current_macro').upper()}", self.farm_current_var, 16),
                (f"⏱  {self.t('farm.playlist_time').upper()}", self.farm_elapsed_var, 24),
                (f"↻  {self.t('farm.repetition').upper()}", self.farm_progress_var, 20),
            )
        ):
            ctk.CTkLabel(
                status,
                text=label,
                font=ctk.CTkFont(size=12, weight="bold"),
                text_color=("gray35", "gray70"),
            ).grid(row=0, column=column, padx=22, pady=(16, 8), sticky="w")
            ctk.CTkLabel(
                status,
                textvariable=variable,
                font=ctk.CTkFont(size=size, weight="bold"),
                text_color="#a855f7" if column else ("gray10", "gray90"),
            ).grid(row=1, column=column, padx=22, pady=(0, 18), sticky="w")

        self.farm_macro_scroll = ctk.CTkScrollableFrame(self.farm_view, fg_color="transparent")
        self.farm_macro_scroll.grid(row=4, column=0, padx=(18, 10), pady=(0, 16), sticky="nsew")
        self.farm_macro_scroll.grid_columnconfigure(0, weight=1)

        side = ctk.CTkFrame(self.farm_view, fg_color="transparent")
        side.grid(row=1, column=1, rowspan=4, padx=(6, 18), pady=(0, 16), sticky="nsew")
        side.grid_columnconfigure(0, weight=1, minsize=320)
        side.grid_rowconfigure(1, weight=1)
        details = self.create_execute_card(side)
        details.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        self.farm_status_var = tk.StringVar(value=self.t("farm.waiting"))
        self.farm_next_var = tk.StringVar(value="-")
        self.farm_total_var = tk.StringVar(value="0")
        ctk.CTkLabel(details, text=f"☰  {self.t('farm.details')}", font=ctk.CTkFont(size=15, weight="bold")).grid(
            row=0, column=0, columnspan=2, padx=24, pady=(20, 14), sticky="w"
        )
        for row, (label, var) in enumerate(
            (
                (self.t("farm.status"), self.farm_status_var),
                (self.t("farm.next_action"), self.farm_next_var),
                (self.t("farm.total_executions"), self.farm_total_var),
            ),
            start=1,
        ):
            ctk.CTkLabel(details, text=label, text_color=("gray35", "gray70")).grid(
                row=row, column=0, padx=(24, 22), pady=8, sticky="w"
            )
            ctk.CTkLabel(details, textvariable=var).grid(row=row, column=1, padx=(0, 24), pady=8, sticky="e")

        log_card = self.create_execute_card(side)
        log_card.grid(row=1, column=0, sticky="nsew")
        log_card.grid_columnconfigure(0, weight=1)
        log_card.grid_rowconfigure(1, weight=1)
        ctk.CTkLabel(log_card, text=f"▣  {self.t('farm.log')}", font=ctk.CTkFont(size=15, weight="bold")).grid(
            row=0, column=0, padx=18, pady=(18, 8), sticky="w"
        )
        self.farm_log = ctk.CTkTextbox(log_card, width=300, height=300)
        self.farm_log.grid(row=1, column=0, padx=14, pady=(0, 14), sticky="nsew")
        self.farm_view.grid_remove()
        self.refresh_farm_macros()

    def create_farm_positions_panel(self, parent):
        positions = self.farm_config.get("positions", {})
        brand = positions.get("brand", {})
        car = positions.get("car", {})
        last_car = positions.get("last_car", {})

        self.farm_brand_up_var = tk.StringVar(value=str(brand.get("cima", 0)))
        self.farm_brand_down_var = tk.StringVar(value=str(brand.get("baixo", 0)))
        self.farm_brand_left_var = tk.StringVar(value=str(brand.get("esquerda", 0)))
        self.farm_brand_right_var = tk.StringVar(value=str(brand.get("direita", 0)))
        self.farm_car_row_var = tk.StringVar(value=str(car.get("linha", 1)))
        self.farm_car_column_var = tk.StringVar(value=str(car.get("coluna", 1)))
        self.farm_last_car_row_var = tk.StringVar(value=str(last_car.get("linha", 1)))
        self.farm_last_car_column_var = tk.StringVar(value=str(last_car.get("coluna", 1)))

        panel = ctk.CTkFrame(
            parent,
            corner_radius=8,
            fg_color=("#eaf4ff", "#0d2138"),
            border_width=1,
            border_color=("#8cc7ff", "#2f74ba"),
        )
        panel.grid_columnconfigure(0, weight=1)
        self.farm_parameters_open = False
        self.farm_parameters_button = ctk.CTkButton(
            panel,
            text=f">  {self.t('farm.general_parameters')}",
            height=42,
            anchor="w",
            fg_color="transparent",
            hover_color=("#d8e6f3", "#1b2b42"),
            text_color=("gray10", "gray90"),
            font=ctk.CTkFont(size=15, weight="bold"),
            command=self.toggle_farm_parameters_panel,
        )
        self.farm_parameters_button.grid(row=0, column=0, padx=18, pady=14, sticky="ew")

        self.farm_parameters_content = ctk.CTkFrame(panel, fg_color="transparent")
        self.farm_parameters_content.grid_columnconfigure(0, weight=1)
        self.create_farm_general_action_controls(self.farm_parameters_content).grid(
            row=0, column=0, padx=18, pady=(0, 6), sticky="ew"
        )
        self.create_farm_repetition_controls(self.farm_parameters_content).grid(
            row=1, column=0, padx=18, pady=6, sticky="ew"
        )
        self.create_farm_brand_position_controls(self.farm_parameters_content).grid(
            row=2, column=0, padx=18, pady=6, sticky="ew"
        )
        self.create_farm_matrix_position_controls(
            self.farm_parameters_content,
            self.t("farm.car_position"),
            self.t("farm.car_position_hint"),
            self.farm_car_row_var,
            self.farm_car_column_var,
        ).grid(row=3, column=0, padx=18, pady=6, sticky="ew")
        self.create_farm_matrix_position_controls(
            self.farm_parameters_content,
            self.t("farm.last_car_position"),
            self.t("farm.last_car_position_hint"),
            self.farm_last_car_row_var,
            self.farm_last_car_column_var,
            readonly=True,
            action_text=self.t("farm.update_last_car"),
            action_command=self.update_farm_last_car_position,
        ).grid(row=4, column=0, padx=18, pady=(6, 14), sticky="ew")
        self.farm_parameters_content.grid(row=1, column=0, sticky="ew")
        self.farm_parameters_content.grid_remove()
        return panel

    def toggle_farm_parameters_panel(self):
        if not hasattr(self, "farm_parameters_content"):
            return
        self.farm_parameters_open = not self.farm_parameters_open
        if self.farm_parameters_open:
            self.farm_parameters_content.grid()
            self.farm_parameters_button.configure(text=f"v  {self.t('farm.general_parameters')}")
        else:
            self.farm_parameters_content.grid_remove()
            self.farm_parameters_button.configure(text=f">  {self.t('farm.general_parameters')}")

    def create_farm_general_action_controls(self, parent):
        card = self.create_farm_position_subcard(parent)
        actions = ctk.CTkFrame(card, fg_color="transparent")
        actions.grid(row=0, column=0, padx=14, pady=12, sticky="ew")
        actions.grid_columnconfigure(1, weight=1)
        self.farm_shutdown_button = ctk.CTkButton(
            actions,
            width=230,
            height=34,
            corner_radius=7,
            command=self.toggle_farm_shutdown_on_finish,
        )
        self.farm_shutdown_button.grid(row=0, column=0, sticky="w")
        self.update_farm_shutdown_button()
        ctk.CTkButton(
            actions,
            text=self.t("farm.open_tutorial"),
            image=self.get_folder_icon_image(),
            compound="left",
            width=180,
            height=34,
            corner_radius=7,
            fg_color="#facc15",
            hover_color="#eab308",
            text_color="#1f2937",
            command=self.open_farm_parameters_tutorial,
        ).grid(row=0, column=1, padx=(12, 0), sticky="w")
        return card

    def create_farm_repetition_controls(self, parent):
        card = self.create_farm_position_subcard(parent)
        card.grid_columnconfigure(0, weight=1)
        self.farm_roulette_quantity_var = tk.StringVar(value=str(self.farm_config.get("roulette_quantity", 1)))
        ctk.CTkLabel(
            card,
            text=self.t("farm.repeats"),
            font=ctk.CTkFont(size=14, weight="bold"),
        ).grid(row=0, column=0, padx=14, pady=(12, 8), sticky="w")
        controls = ctk.CTkFrame(card, fg_color="transparent")
        controls.grid(row=1, column=0, padx=14, pady=(0, 8), sticky="ew")
        controls.grid_columnconfigure(0, weight=1)
        ctk.CTkEntry(controls, width=120, textvariable=self.farm_roulette_quantity_var).grid(
            row=0, column=0, sticky="w"
        )
        self.farm_roulette_quantity_var.trace_add("write", lambda *_args: self.update_farm_total())
        self.farm_repetitions_status_var = tk.StringVar(value="")
        ctk.CTkLabel(
            card,
            textvariable=self.farm_repetitions_status_var,
            text_color=("gray35", "gray70"),
        ).grid(row=2, column=0, padx=14, pady=(0, 12), sticky="w")
        return card

    def create_farm_brand_position_controls(self, parent):
        card = self.create_farm_position_subcard(parent)
        card.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            card,
            text=self.t("farm.brand_position"),
            font=ctk.CTkFont(size=14, weight="bold"),
        ).grid(row=0, column=0, padx=14, pady=(12, 2), sticky="w")
        ctk.CTkLabel(
            card,
            text=self.t("farm.brand_position_hint"),
            text_color=("gray35", "gray70"),
            font=ctk.CTkFont(size=11),
        ).grid(row=1, column=0, padx=14, pady=(0, 10), sticky="w")
        fields = ctk.CTkFrame(card, fg_color="transparent")
        fields.grid(row=2, column=0, padx=14, pady=(0, 12), sticky="ew")
        for label_key, variable in (
            ("farm.up", self.farm_brand_up_var),
            ("farm.down", self.farm_brand_down_var),
            ("farm.left", self.farm_brand_left_var),
            ("farm.right", self.farm_brand_right_var),
        ):
            ctk.CTkLabel(fields, text=self.t(label_key)).pack(side="left", padx=(0, 4))
            ctk.CTkEntry(fields, width=44, textvariable=variable).pack(side="left", padx=(0, 8))
        return card

    def create_farm_matrix_position_controls(
        self,
        parent,
        title,
        hint,
        row_var,
        column_var,
        readonly=False,
        action_text=None,
        action_command=None,
    ):
        card = self.create_farm_position_subcard(parent)
        ctk.CTkLabel(card, text=title, font=ctk.CTkFont(size=14, weight="bold")).grid(
            row=0, column=0, padx=14, pady=(12, 2), sticky="w"
        )
        ctk.CTkLabel(
            card,
            text=hint,
            text_color=("gray35", "gray70"),
            font=ctk.CTkFont(size=11),
        ).grid(row=1, column=0, padx=14, pady=(0, 10), sticky="w")
        fields = ctk.CTkFrame(card, fg_color="transparent")
        fields.grid(row=2, column=0, padx=14, pady=(0, 12), sticky="w")
        ctk.CTkLabel(fields, text=self.t("farm.row")).pack(side="left", padx=(0, 6))
        row_entry = ctk.CTkEntry(fields, width=64, textvariable=row_var, state="disabled" if readonly else "normal")
        row_entry.pack(side="left", padx=(0, 12))
        ctk.CTkLabel(fields, text=self.t("farm.column")).pack(side="left", padx=(0, 6))
        column_entry = ctk.CTkEntry(fields, width=64, textvariable=column_var, state="disabled" if readonly else "normal")
        column_entry.pack(side="left")
        if action_text and action_command:
            ctk.CTkButton(
                fields,
                text=action_text,
                width=120,
                height=32,
                command=action_command,
            ).pack(side="left", padx=(12, 0))
        return card

    def create_settings_view(self):
        self.settings_view = ctk.CTkFrame(self, corner_radius=0, fg_color="#020812")
        self.settings_view.grid(row=0, column=0, columnspan=2, sticky="nsew")
        self.settings_view.grid_columnconfigure(0, weight=1)
        self.settings_view.grid_rowconfigure(8, weight=1)

        header = ctk.CTkFrame(self.settings_view, fg_color="transparent")
        header.grid(row=0, column=0, padx=34, pady=(28, 18), sticky="ew")
        header.grid_columnconfigure(1, weight=1)

        ctk.CTkButton(
            header,
            text="‹",
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
        self.create_farm_mode_settings_card()
        self.create_shortcuts_settings_card()
        self.create_telegram_settings_card()
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
            font=ctk.CTkFont(size=17, weight="bold"),
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
            1, self.t("settings.language_title"), self.t("settings.language_description"), "#1877d8", "◎"
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
            text="●" if selected else "○",
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
            2, self.t("settings.theme_title"), self.t("settings.theme_description"), "#5842a6", "◐"
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
            3, self.t("settings.startup_title"), self.t("settings.startup_description"), "#16a34a", "⏻"
        )
        ctk.CTkSwitch(
            section,
            text=self.t("settings.startup_windows"),
            variable=self.startup_var,
            command=self.save_app_config,
        ).grid(row=0, column=3, rowspan=2, padx=(18, 18), pady=18, sticky="e")

    def create_farm_mode_settings_card(self):
        section = self.create_settings_section(
            4, self.t("settings.farm_mode_title"), self.t("settings.farm_mode_description"), "#eab308", "◆"
        )
        ctk.CTkSwitch(
            section,
            text=self.t("settings.farm_mode_toggle"),
            variable=self.farm_mode_var,
            command=self.toggle_farm_mode,
        ).grid(row=0, column=3, rowspan=2, padx=(18, 18), pady=18, sticky="e")

    def create_shortcuts_settings_card(self):
        section = self.create_settings_section(
            5, self.t("settings.shortcuts_title"), self.t("settings.shortcuts_description"), "#ef8a2f", "⌘"
        )
        ctk.CTkButton(
            section,
            text=self.t("settings.shortcuts_button"),
            height=36,
            command=self.open_shortcut_editor,
        ).grid(row=0, column=3, rowspan=2, padx=(18, 18), pady=18, sticky="e")

    def create_telegram_settings_card(self):
        section = self.create_settings_section(
            6,
            self.t("settings.telegram_title"),
            self.t("settings.telegram_description"),
            "#229ed9",
            "T",
        )
        controls = ctk.CTkFrame(section, fg_color="transparent")
        controls.grid(row=2, column=1, columnspan=3, padx=(0, 18), pady=(0, 18), sticky="ew")
        controls.grid_columnconfigure(1, weight=1)
        ctk.CTkSwitch(
            controls,
            text=self.t("settings.telegram_enable"),
            variable=self.telegram_enabled_var,
            command=self.save_telegram_config,
        ).grid(row=0, column=0, columnspan=2, pady=(0, 10), sticky="w")
        ctk.CTkLabel(controls, text=self.t("settings.telegram_token")).grid(
            row=1, column=0, padx=(0, 10), pady=4, sticky="w"
        )
        ctk.CTkEntry(controls, textvariable=self.telegram_bot_token_var, show="*", width=360).grid(
            row=1, column=1, pady=4, sticky="ew"
        )
        ctk.CTkLabel(controls, text=self.t("settings.telegram_chat_id")).grid(
            row=2, column=0, padx=(0, 10), pady=4, sticky="w"
        )
        ctk.CTkEntry(controls, textvariable=self.telegram_chat_id_var, width=220).grid(
            row=2, column=1, pady=4, sticky="w"
        )
        buttons = ctk.CTkFrame(controls, fg_color="transparent")
        buttons.grid(row=3, column=0, columnspan=2, pady=(10, 0), sticky="ew")
        ctk.CTkButton(
            buttons,
            text=self.t("settings.telegram_save"),
            width=120,
            command=self.save_telegram_config,
        ).pack(side="left")
        ctk.CTkButton(
            buttons,
            text=self.t("settings.telegram_test"),
            width=180,
            fg_color="#229ed9",
            hover_color="#1b82b4",
            command=self.send_telegram_test_message,
        ).pack(side="left", padx=(10, 0))
        ctk.CTkLabel(
            controls,
            textvariable=self.telegram_status_var,
            text_color=("gray35", "gray72"),
            anchor="w",
        ).grid(row=4, column=0, columnspan=2, pady=(8, 0), sticky="ew")

    def create_about_settings_card(self):
        section = self.create_settings_section(
            7, self.t("settings.about_title"), self.t("settings.about_description"), "#1877d8", "i"
        )
        ctk.CTkLabel(section, text="›", font=ctk.CTkFont(size=22), text_color=("gray35", "gray72")).grid(
            row=0, column=3, rowspan=2, padx=(18, 28), pady=18
        )

    def create_settings_footer(self):
        footer = ctk.CTkFrame(self.settings_view, corner_radius=10, fg_color=("#eef3f8", "#07111f"))
        footer.grid(row=8, column=0, padx=68, pady=(8, 18), sticky="sew")
        footer.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            footer,
            text=f"</>  {self.t('app.developer')}",
            font=ctk.CTkFont(size=14),
            text_color=("#1b6fb8", "#4aa7ff"),
        ).grid(row=0, column=0, padx=24, pady=16)

    def hide_root_views(self):
        for view_name in ("home_view", "farm_view", "playlist_view", "execute_view", "settings_view", "sidebar", "main"):
            view = getattr(self, view_name, None)
            if view is not None:
                view.grid_remove()

    def configure_fullscreen_layout(self):
        self.grid_columnconfigure(0, weight=1, minsize=0)
        self.grid_columnconfigure(1, weight=0, minsize=0)
        self.grid_rowconfigure(0, weight=1)

    def configure_shell_layout(self):
        self.grid_columnconfigure(0, weight=0, minsize=0)
        self.grid_columnconfigure(1, weight=1, minsize=0)
        self.grid_rowconfigure(0, weight=1)

    def show_home(self):
        self.hide_root_views()
        self.active_screen = "home"
        self.configure_fullscreen_layout()
        self.home_view.grid(row=0, column=0, columnspan=2, sticky="nsew")
        self.home_view.tkraise()

    def show_placeholder(self, name):
        self.hide_root_views()
        self.active_screen = name
        self.configure_fullscreen_layout()
        view = getattr(self, f"{name}_view")
        view.grid(row=0, column=0, columnspan=2, sticky="nsew")
        view.tkraise()

    def show_app_shell(self, view="conventional"):
        self.hide_root_views()
        self.active_screen = "macro_editor"
        self.configure_shell_layout()
        self.configure(fg_color="#020812")
        self.sidebar.grid(row=0, column=0, sticky="nsew")
        self.main.grid(row=0, column=1, sticky="nsew", padx=18, pady=18)
        self.show_view(view)
        self.sidebar.tkraise()
        self.main.tkraise()

    def open_macro_editor(self):
        self.show_app_shell("conventional")

    def open_smart_macro_editor(self):
        self.show_app_shell("smart")

    def open_macro_playlist(self):
        self.refresh_playlist_macro_list()
        self.show_placeholder("playlist")

    def open_farm_subaru_impreza_22b(self):
        self.refresh_farm_macros()
        self.show_placeholder("farm")

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
        self.rebuild_interface()
        self.show_placeholder("settings")

    def change_theme_from_settings(self, selected_theme):
        dark_label = self.t("settings.theme_dark")
        self.theme_var.set("Dark" if selected_theme == dark_label else "Light")
        self.change_theme()
        self.save_app_config()

    def toggle_farm_mode(self):
        self.save_app_config()
        self.rebuild_interface()
        self.show_placeholder("settings")

    def rebuild_interface(self):
        current_file = self.current_file
        selected_macro_path = self.selected_macro_path
        name = self.name_var.get() if hasattr(self, "name_var") else ""
        order = self.order_var.get() if hasattr(self, "order_var") else ""
        brand_position = self.brand_position_var.get() if hasattr(self, "brand_position_var") else False
        car_position = self.car_position_var.get() if hasattr(self, "car_position_var") else False
        last_car_position = self.last_car_position_var.get() if hasattr(self, "last_car_position_var") else False
        repeat_enabled = self.repeat_enabled_var.get() if hasattr(self, "repeat_enabled_var") else False
        mastery = self.mastery_var.get() if hasattr(self, "mastery_var") else False
        manual = self.manual_var.get() if hasattr(self, "manual_var") else ""
        color = self.color_var.get() if hasattr(self, "color_var") else DEFAULT_MACRO_COLOR
        events = list(self.events)
        active_view = self.active_view

        for view_name in ("home_view", "farm_view", "playlist_view", "execute_view", "settings_view", "sidebar", "main"):
            view = getattr(self, view_name, None)
            if view is not None:
                view.destroy()
                setattr(self, view_name, None)

        self.macro_buttons = []
        self.execute_macro_buttons = []
        self.create_home_view()
        self.create_farm_view()
        self.create_playlist_view()
        self.create_execute_view()
        self.create_settings_view()
        self.create_sidebar()
        self.create_main_area()

        self.current_file = current_file
        self.selected_macro_path = selected_macro_path
        self.name_var.set(name)
        self.order_var.set(order)
        self.brand_position_var.set(brand_position)
        self.car_position_var.set(car_position)
        self.last_car_position_var.set(last_car_position)
        self.repeat_enabled_var.set(repeat_enabled)
        self.mastery_var.set(mastery)
        self.manual_var.set(manual if manual in self.load_manual_options() else "")
        self.color_var.set(self.normalized_macro_color({"cor": color}))
        self.update_color_palette_selection()
        self.events = events
        self.engine.events = list(events)
        self.render_events()
        self.refresh_macro_list()
        self.update_macro_selection()
        self.refresh_execute_macro_list(select_path=self.execute_selected_path)
        self.show_view(active_view)

    def create_home_view(self):
        self.home_view = ctk.CTkFrame(self, corner_radius=0, fg_color="#020812")
        self.home_view.grid(row=0, column=0, columnspan=2, sticky="nsew")
        column_count = 1 if self.farm_mode_var.get() else 5
        self.home_view.grid_columnconfigure(tuple(range(column_count)), weight=1)
        self.home_view.grid_rowconfigure(0, weight=1)
        self.home_view.grid_rowconfigure(5, weight=1)

        ctk.CTkLabel(
            self.home_view,
            text=self.t("home.title"),
            font=ctk.CTkFont(size=32, weight="bold"),
        ).grid(row=1, column=0, columnspan=column_count, padx=24, pady=(24, 8))
        ctk.CTkLabel(
            self.home_view,
            text=self.t("home.subtitle"),
            font=ctk.CTkFont(size=16),
            text_color=("gray30", "gray78"),
        ).grid(row=2, column=0, columnspan=column_count, padx=24, pady=(0, 26))

        if not self.farm_mode_var.get():
            self.create_home_card(
                row=3,
                column=0,
                title=self.t("home.create_title"),
                description=self.t("home.create_description"),
                icon="✎",
                accent="#168bff",
                command=self.open_macro_editor,
            )
            self.create_home_card(
                row=3,
                column=1,
                title=self.t("home.smart_title"),
                description=self.t("home.smart_description"),
                icon="✦",
                accent="#ef8a2f",
                command=self.open_smart_macro_editor,
            )
            self.create_home_card(
                row=3,
                column=2,
                title=self.t("home.execute_title"),
                description=self.t("home.execute_description"),
                icon="▶",
                accent="#62df45",
                command=self.open_execute_screen,
            )
            farm_column = 3
            playlist_column = 4
        else:
            farm_column = 0
            playlist_column = None

        self.create_home_card(
            row=3,
            column=farm_column,
            title=self.t("home.farm_title"),
            description=self.t("home.farm_description"),
            icon="◆",
            accent="#eab308",
            command=self.open_farm_subaru_impreza_22b,
        )
        if playlist_column is not None:
            self.create_home_card(
                row=3,
                column=playlist_column,
                title=self.t("home.playlist_title"),
                description=self.t("home.playlist_description"),
                icon="☰",
                accent="#a855f7",
                command=self.open_macro_playlist,
            )

        if not self.farm_mode_var.get():
            footer = ctk.CTkFrame(self.home_view, corner_radius=10, fg_color=("#eef3f8", "#07111f"))
            footer.grid(row=4, column=0, columnspan=4, padx=(34, 24), pady=(30, 0), sticky="ew")
            footer.grid_columnconfigure(0, weight=1)
            ctk.CTkLabel(
                footer,
                text=f"</>  {self.t('app.developer')}",
                font=ctk.CTkFont(size=15),
                text_color=("#1b6fb8", "#4aa7ff"),
            ).grid(row=0, column=0, padx=24, pady=18)

        ctk.CTkButton(
            self.home_view,
            text=f"⚙  {self.t('home.settings')}",
            height=42,
            fg_color=("#eef3f8", "#07111f"),
            hover_color=("#dfe9f4", "#0d1b2e"),
            text_color=("gray10", "gray90"),
            border_width=1,
            border_color=("#d3dbe5", "#1d2a3d"),
            command=self.open_settings_screen,
        ).grid(row=4, column=column_count - 1, padx=(0, 34), pady=(30, 0), sticky="ew")

    def create_home_card(self, row, column, title, description, icon, accent, command):
        card = ctk.CTkFrame(
            self.home_view,
            width=HOME_CARD_WIDTH,
            height=HOME_CARD_HEIGHT,
            corner_radius=16,
            fg_color=("#eef6ff", "#031123"),
            border_width=2,
            border_color=accent,
        )
        card.grid(row=row, column=column, padx=8, pady=0)
        card.grid_propagate(False)
        card.grid_columnconfigure(0, weight=1)

        icon_badge = ctk.CTkFrame(
            card,
            width=HOME_CARD_ICON_SIZE,
            height=HOME_CARD_ICON_SIZE,
            corner_radius=HOME_CARD_ICON_SIZE // 2,
            fg_color=accent,
        )
        icon_badge.grid(row=0, column=0, padx=18, pady=(30, 16))
        icon_badge.grid_propagate(False)
        ctk.CTkLabel(
            icon_badge,
            text=icon,
            font=ctk.CTkFont(size=32, weight="bold"),
            text_color="#ffffff",
        ).place(relx=0.5, rely=0.5, anchor="center")
        ctk.CTkLabel(
            card,
            text="",
            width=HOME_CARD_WIDTH - 42,
            height=1,
            fg_color=accent,
        ).grid(
            row=1, column=0, padx=21, pady=(0, 14)
        )
        ctk.CTkLabel(
            card,
            text=title,
            font=ctk.CTkFont(size=17, weight="bold"),
            wraplength=175,
            justify="center",
        ).grid(
            row=2, column=0, padx=18, pady=(0, 10)
        )
        ctk.CTkLabel(
            card,
            text=description,
            font=ctk.CTkFont(size=13),
            text_color=("gray25", "gray78"),
            wraplength=175,
            justify="center",
        ).grid(row=3, column=0, padx=18, pady=(0, 22))
        ctk.CTkButton(
            card,
            text="›",
            width=46,
            height=46,
            corner_radius=23,
            fg_color=accent,
            hover_color=accent,
            font=ctk.CTkFont(size=22, weight="bold"),
            command=command,
        ).grid(row=4, column=0, pady=(0, 24))

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

        self.new_macro_button = ctk.CTkButton(self.sidebar, text=self.t("macro.new"), height=38, command=self.new_macro)
        self.new_macro_button.grid(
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
        if self.theme_var.get() == "Dark":
            self.theme_switch.select()
        else:
            self.theme_switch.deselect()
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
        header.grid_columnconfigure(1, weight=0)

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
        self.name_entry.grid(row=1, column=0, padx=(18, 14), pady=(0, 12), sticky="ew")

        ctk.CTkLabel(header, text=self.t("macro.recording_status"), font=ctk.CTkFont(size=14, weight="bold")).grid(
            row=0, column=1, padx=(14, 18), pady=(16, 6), sticky="w"
        )
        self.recording_status_var = tk.StringVar(value=f"*  {self.t('macro.not_recording')}")
        self.recording_status_label = ctk.CTkLabel(
            header,
            textvariable=self.recording_status_var,
            width=250,
            height=40,
            anchor="w",
            corner_radius=7,
            fg_color=("#f8fbff", "#0b1628"),
            text_color=("#d63d3d", "#ff5a5f"),
            font=ctk.CTkFont(weight="bold"),
        )
        self.recording_status_label.grid(row=1, column=1, padx=(14, 18), pady=(0, 12), sticky="ew")

        metadata = ctk.CTkFrame(header, fg_color="transparent")
        metadata.grid(row=2, column=0, columnspan=2, padx=18, pady=(0, 12), sticky="ew")
        metadata.grid_columnconfigure(9, weight=1)

        ctk.CTkLabel(metadata, text=self.t("macro.order")).grid(row=0, column=0, padx=(0, 8), sticky="w")
        ctk.CTkEntry(
            metadata,
            width=90,
            textvariable=self.order_var,
            placeholder_text=self.t("macro.order_placeholder"),
        ).grid(row=0, column=1, padx=(0, 18), sticky="w")
        ctk.CTkCheckBox(
            metadata,
            text=self.t("macro.brand_position"),
            variable=self.brand_position_var,
            command=self.update_composite_hint,
        ).grid(row=0, column=2, padx=(0, 18), sticky="w")
        ctk.CTkCheckBox(
            metadata,
            text=self.t("macro.car_position"),
            variable=self.car_position_var,
            command=self.update_composite_hint,
        ).grid(row=0, column=3, padx=(0, 18), sticky="w")
        ctk.CTkCheckBox(
            metadata,
            text=self.t("macro.repeat_enabled"),
            variable=self.repeat_enabled_var,
        ).grid(row=0, column=4, padx=(0, 18), sticky="w")
        ctk.CTkCheckBox(
            metadata,
            text=self.t("macro.last_car_position"),
            variable=self.last_car_position_var,
            command=self.update_composite_hint,
        ).grid(row=0, column=5, padx=(0, 18), sticky="w")
        ctk.CTkCheckBox(
            metadata,
            text=self.t("macro.mastery"),
            variable=self.mastery_var,
        ).grid(row=0, column=6, padx=(0, 18), sticky="w")
        ctk.CTkLabel(metadata, text=self.t("macro.color")).grid(row=0, column=7, padx=(0, 8), sticky="w")
        self.color_palette_frame = ctk.CTkFrame(metadata, fg_color="transparent")
        self.color_palette_frame.grid(row=0, column=8, sticky="w")
        self.color_buttons = []
        for index, color in enumerate(MACRO_COLOR_PALETTE):
            button = ctk.CTkButton(
                self.color_palette_frame,
                text="",
                width=24,
                height=24,
                corner_radius=12,
                fg_color=color,
                hover_color=color,
                border_width=2,
                border_color="#ffffff" if color == self.color_var.get() else "#334155",
                command=lambda selected=color: self.select_macro_color(selected),
            )
            button.grid(row=0, column=index, padx=(0, 6))
            self.color_buttons.append((button, color))

        self.composite_hint_label = ctk.CTkLabel(
            metadata,
            text=self.t("macro.composite_hint"),
            anchor="w",
            justify="left",
            wraplength=900,
            corner_radius=8,
            fg_color=("#e8f1ff", "#0b1f35"),
            text_color=("#23415f", "#b8d7ff"),
        )
        ctk.CTkLabel(metadata, text=self.t("macro.link_manual")).grid(
            row=1, column=0, padx=(0, 8), pady=(10, 0), sticky="w"
        )
        self.manual_options = self.load_manual_options()
        self.manual_select = ctk.CTkComboBox(
            metadata,
            values=self.manual_options,
            variable=self.manual_var,
            width=260,
            state="readonly",
        )
        self.manual_select.grid(row=1, column=1, columnspan=3, padx=(0, 18), pady=(10, 0), sticky="w")
        self.composite_hint_label.grid(row=2, column=0, columnspan=10, pady=(10, 0), sticky="ew")
        self.update_composite_hint()

        actions = ctk.CTkFrame(header, fg_color="transparent")
        actions.grid(row=3, column=0, columnspan=2, padx=18, pady=(4, 16), sticky="ew")
        for column in range(6):
            actions.grid_columnconfigure(column, weight=1, uniform="macro_actions")

        self.record_button = ctk.CTkButton(
            actions,
            text=self.t("macro.record"),
            height=38,
            fg_color="#d63d3d",
            hover_color="#b83232",
            command=self.toggle_recording,
        )
        self.record_button.grid(row=0, column=0, padx=(0, 8), sticky="ew")

        ctk.CTkButton(actions, text=self.t("macro.save"), height=38, command=self.save_current).grid(
            row=0, column=1, padx=8, sticky="ew"
        )
        ctk.CTkButton(
            actions,
            text=self.t("macro.import_json"),
            height=38,
            fg_color="#5c5f66",
            hover_color="#4d5056",
            command=self.import_macro_json,
        ).grid(row=0, column=2, padx=8, sticky="ew")
        ctk.CTkButton(
            actions,
            text=self.t("macro.export_json"),
            height=38,
            fg_color="#5c5f66",
            hover_color="#4d5056",
            command=self.export_macro_json,
        ).grid(row=0, column=3, padx=8, sticky="ew")
        ctk.CTkButton(
            actions,
            text=self.t("macro.clear"),
            height=38,
            fg_color="#5c5f66",
            hover_color="#4d5056",
            command=self.clear_macro,
        ).grid(row=0, column=4, padx=8, sticky="ew")
        ctk.CTkButton(
            actions,
            text=self.t("macro.delete"),
            height=38,
            fg_color="#5c5f66",
            hover_color="#4d5056",
            command=self.delete_current,
        ).grid(row=0, column=5, padx=(8, 0), sticky="ew")

    def load_manual_options(self):
        return [""] + sorted(path.name for path in MANUAL_DIR.glob("*.md"))

    def create_status_card(self):
        status_card = ctk.CTkFrame(
            self.conventional_view,
            corner_radius=10,
            fg_color=("#eef6ff", "#07111f"),
            border_width=1,
            border_color=("#d8e0ea", "#132034"),
        )
        status_card.grid(row=1, column=0, sticky="ew", pady=(0, 14))
        status_card.grid_columnconfigure((0, 1, 2), weight=1, uniform="status_columns")

        ctk.CTkLabel(
            status_card,
            text=self.t("macro.shortcuts_during_recording").upper(),
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=("gray35", "gray70"),
        ).grid(row=0, column=0, padx=18, pady=(16, 8), sticky="w")
        ctk.CTkLabel(
            status_card,
            text=self.t("macro.live").upper(),
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=("gray35", "gray70"),
        ).grid(row=0, column=1, padx=18, pady=(16, 8), sticky="w")
        ctk.CTkLabel(
            status_card,
            text=self.t("macro.elapsed_time").upper(),
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=("gray35", "gray70"),
        ).grid(row=0, column=2, padx=18, pady=(16, 8), sticky="w")

        self.shortcuts_frame = ctk.CTkFrame(status_card, fg_color="transparent")
        self.shortcuts_frame.grid(row=1, column=0, padx=18, pady=(0, 16), sticky="w")
        self.render_shortcut_pills()

        self.live_inputs_var = tk.StringVar(value=self.t("macro.nothing_pressed"))
        self.live_action_var = tk.StringVar(value=self.t("macro.user_waiting"))
        ctk.CTkLabel(status_card, textvariable=self.live_inputs_var, font=ctk.CTkFont(size=14)).grid(
            row=1, column=1, padx=18, pady=(0, 16), sticky="w"
        )

        self.record_elapsed_var = tk.StringVar(value="00:00:00")
        ctk.CTkLabel(
            status_card,
            textvariable=self.record_elapsed_var,
            font=ctk.CTkFont(size=18, weight="bold"),
        ).grid(row=1, column=2, padx=18, pady=(0, 16), sticky="w")

        separator = ctk.CTkFrame(status_card, height=1, fg_color=("#d8e0ea", "#132034"))
        separator.grid(row=2, column=0, columnspan=3, sticky="ew")

        self.status_var = tk.StringVar(value=self.t("macro.ready"))
        ctk.CTkLabel(status_card, textvariable=self.status_var, anchor="w").grid(
            row=3, column=0, columnspan=2, padx=18, pady=(10, 12), sticky="ew"
        )
        ctk.CTkLabel(status_card, textvariable=self.live_action_var, anchor="e").grid(
            row=3, column=2, padx=18, pady=(10, 12), sticky="e"
        )

        self.countdown_var = tk.StringVar(value="")
        self.countdown_label = ctk.CTkLabel(
            status_card,
            textvariable=self.countdown_var,
            font=ctk.CTkFont(size=18, weight="bold"),
            text_color="#ef8a2f",
        )
        self.countdown_label.grid(row=4, column=0, columnspan=3, padx=18, pady=(0, 12), sticky="w")
        self.countdown_label.grid_remove()

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
        self.timeline_frame = ctk.CTkFrame(parent, corner_radius=8)
        self.timeline_frame.grid(row=1, column=0, columnspan=2, padx=18, pady=(0, 14), sticky="ew")
        self.timeline_frame.grid_columnconfigure(0, weight=1)

        self.timeline_canvas = tk.Canvas(self.timeline_frame, height=116, highlightthickness=0, bd=0, xscrollincrement=24)
        self.timeline_canvas.grid(row=0, column=0, sticky="ew", padx=10, pady=(10, 0))
        self.timeline_scrollbar = ttk.Scrollbar(self.timeline_frame, orient="horizontal", command=self.timeline_canvas.xview)
        self.timeline_scrollbar.grid(row=1, column=0, sticky="ew", padx=10, pady=(0, 10))
        self.timeline_canvas.configure(xscrollcommand=self.timeline_scrollbar.set)

        self.empty_events_frame = ctk.CTkFrame(parent, corner_radius=8, fg_color=("#f8fbff", "#0b1628"))
        self.empty_events_frame.grid(row=1, column=0, columnspan=2, padx=18, pady=(0, 14), sticky="ew")
        self.empty_events_frame.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            self.empty_events_frame,
            text="KEY",
            font=ctk.CTkFont(size=42, weight="bold"),
            text_color=("gray45", "gray70"),
        ).grid(row=0, column=0, pady=(22, 6))
        ctk.CTkLabel(
            self.empty_events_frame,
            text=self.t("macro.no_events_title"),
            font=ctk.CTkFont(size=17, weight="bold"),
        ).grid(row=1, column=0, pady=(0, 6))
        ctk.CTkLabel(
            self.empty_events_frame,
            text=self.t("macro.no_events_description"),
            text_color=("gray35", "gray72"),
        ).grid(row=2, column=0, pady=(0, 24))

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
        header.grid_columnconfigure(5, weight=1)

        ctk.CTkLabel(
            header,
            text=self.t("smart.title"),
            font=ctk.CTkFont(size=22, weight="bold"),
        ).grid(row=0, column=0, columnspan=6, padx=18, pady=(18, 8), sticky="w")

        self.smart_row_var = tk.StringVar(value="2")
        self.smart_column_var = tk.StringVar(value="3")
        self.smart_delay_var = tk.StringVar(value=f"{DEFAULT_MATRIX_STEP_DELAY:.2f}")

        ctk.CTkLabel(header, text=self.t("smart.target_row")).grid(
            row=1, column=0, padx=(18, 8), pady=(0, 18), sticky="w"
        )
        ctk.CTkEntry(header, width=72, textvariable=self.smart_row_var, height=38).grid(
            row=1, column=1, padx=(0, 12), pady=(0, 18)
        )
        ctk.CTkLabel(header, text=self.t("smart.target_column")).grid(
            row=1, column=2, padx=(0, 8), pady=(0, 18), sticky="w"
        )
        ctk.CTkEntry(header, width=72, textvariable=self.smart_column_var, height=38).grid(
            row=1, column=3, padx=(0, 12), pady=(0, 18)
        )
        ctk.CTkLabel(header, text=self.t("smart.delay")).grid(
            row=1, column=4, padx=(0, 8), pady=(0, 18), sticky="w"
        )
        ctk.CTkEntry(header, width=82, textvariable=self.smart_delay_var, height=38).grid(
            row=1, column=5, padx=(0, 12), pady=(0, 18), sticky="w"
        )

        ctk.CTkButton(header, text=self.t("smart.preview"), height=38, command=self.preview_smart_grid_path).grid(
            row=2, column=0, columnspan=2, padx=(18, 6), pady=(0, 18), sticky="ew"
        )
        ctk.CTkButton(header, text=self.t("smart.run"), height=38, command=self.run_smart_navigation).grid(
            row=2, column=2, columnspan=2, padx=6, pady=(0, 18), sticky="ew"
        )
        ctk.CTkButton(
            header,
            text=self.t("smart.save"),
            height=38,
            command=self.save_smart_grid_macro,
        ).grid(row=2, column=4, padx=6, pady=(0, 18), sticky="ew")
        ctk.CTkButton(
            header,
            text=self.t("smart.stop"),
            height=38,
            fg_color="#5c5f66",
            hover_color="#4d5056",
            command=self.smart_engine.stop_navigation,
        ).grid(row=2, column=5, padx=(6, 18), pady=(0, 18), sticky="ew")

        settings = ctk.CTkFrame(
            self.smart_view,
            corner_radius=10,
            fg_color=("#eef6ff", "#07111f"),
            border_width=1,
            border_color=("#d8e0ea", "#132034"),
        )
        settings.grid(row=1, column=0, sticky="ew", pady=(0, 14))
        settings.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            settings,
            text=self.t("smart.grid_help"),
            justify="left",
            text_color=("#4d5562", "#aab3c1"),
        ).grid(row=0, column=0, columnspan=2, padx=18, pady=16, sticky="w")

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
            text=self.t("smart.execution_log"),
            font=ctk.CTkFont(size=16, weight="bold"),
        ).grid(row=0, column=0, padx=18, pady=(18, 8), sticky="w")

        self.smart_log = ctk.CTkTextbox(panel, height=260)
        self.smart_log.grid(row=1, column=0, padx=18, pady=(0, 18), sticky="nsew")
        self.set_smart_status(self.t("smart.initial_log"))

    def show_view(self, view):
        self.active_view = view
        if view == "smart":
            self.smart_view.tkraise()
            self.conventional_nav_button.grid_remove()
            self.smart_nav_button.grid(row=2, column=0, padx=22, pady=(0, 12), sticky="ew")
            self.smart_nav_button.configure(fg_color=("#3b8ed0", "#1f6aa5"), hover_color=("#36719f", "#144870"))
            return

        self.conventional_view.tkraise()
        self.conventional_nav_button.grid(row=2, column=0, padx=22, pady=(0, 8), sticky="ew")
        self.smart_nav_button.grid_remove()
        self.conventional_nav_button.configure(fg_color=("#3b8ed0", "#1f6aa5"), hover_color=("#36719f", "#144870"))

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

    def preview_smart_grid_path(self):
        try:
            target_row, target_column, _step_delay = self.get_smart_grid_values()
        except ValueError as exc:
            messagebox.showerror(self.t("smart.invalid_config_title"), str(exc))
            return

        right_steps = max(0, target_column - 1)
        down_steps = max(0, target_row - 1)
        self.set_smart_status(
            self.t("smart.path_preview").format(
                row=target_row,
                column=target_column,
                right=right_steps,
                down=down_steps,
            )
        )

    def run_smart_navigation(self):
        try:
            target_row, target_column, step_delay = self.get_smart_grid_values()
        except ValueError as exc:
            messagebox.showerror(self.t("smart.invalid_config_title"), str(exc))
            return
        self.smart_engine.start_grid_navigation(target_row, target_column, step_delay=step_delay)

    def save_smart_grid_macro(self):
        try:
            target_row, target_column, _step_delay = self.get_smart_grid_values()
        except ValueError as exc:
            messagebox.showerror(self.t("smart.invalid_config_title"), str(exc))
            return

        name = self.smart_grid_macro_name(target_row, target_column)
        step_delay = DEFAULT_MATRIX_STEP_DELAY
        path = MACROS_DIR / f"{self.safe_macro_name(name)}.json"
        data = {
            "version": 1,
            "name": name,
            "kind": "matrix_navigation",
            "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "ordem": None,
            "possicaoMarca": False,
            "posicaoCarro": False,
            "posicaoUltimoCarro": False,
            "ativarRepeticao": False,
            "maestria": False,
            "manual": "",
            "cor": DEFAULT_MACRO_COLOR,
            "matrix": {
                "start_row": 1,
                "start_column": 1,
                "target_row": target_row,
                "target_column": target_column,
                "step_delay": step_delay,
            },
            "events": self.build_smart_grid_events(target_row, target_column, step_delay),
        }
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        self.refresh_macro_list()
        if hasattr(self, "execute_macro_scroll"):
            self.refresh_execute_macro_list()
        if hasattr(self, "playlist_macro_scroll"):
            self.refresh_playlist_macro_list(select_path=path)
        self.set_smart_status(f"{self.t('smart.saved')}: {name}")

    def build_smart_grid_events(self, target_row, target_column, step_delay):
        return build_matrix_navigation_events(target_row, target_column, step_delay)

    @staticmethod
    def smart_grid_macro_name(target_row, target_column):
        return f"L{target_row}C{target_column}(Matriz)"

    def get_smart_grid_values(self):
        try:
            target_row = int(self.smart_row_var.get())
            target_column = int(self.smart_column_var.get())
            step_delay = float(self.smart_delay_var.get().replace(",", "."))
        except ValueError as exc:
            raise ValueError(self.t("smart.invalid_numbers")) from exc
        if target_row < 1 or target_row > 3:
            raise ValueError(self.t("smart.invalid_row"))
        if target_column < 1:
            raise ValueError(self.t("smart.invalid_column"))
        if step_delay < 0:
            raise ValueError(self.t("smart.invalid_delay"))
        return target_row, target_column, step_delay

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
        elif action == "telegram_status":
            if hasattr(self, "telegram_status_var"):
                self.telegram_status_var.set(payload)
        elif action == "farm_log":
            self.log_farm(payload)
        elif action == "playing":
            if hasattr(self, "execute_play_button"):
                self.execute_play_button.configure(state="disabled" if payload else "normal")
                if payload:
                    if self.active_screen == "playlist":
                        self.start_playlist_timer()
                    elif self.active_screen == "farm":
                        self.start_farm_timer()
                    else:
                        self.start_execute_timer()
                else:
                    self.stop_execute_timer()
                    self.stop_playlist_timer()
                    self.stop_farm_timer()
            self.set_playback_alert(payload)
        elif action == "playback_finished":
            self.handle_playback_finished(payload)
        elif action == "playlist_current":
            if hasattr(self, "playlist_current_var"):
                self.playlist_current_var.set(payload)
            if hasattr(self, "farm_current_var"):
                self.farm_current_var.set(payload)
                self.farm_next_var.set(payload)
                self.log_farm(payload)
                self.highlight_running_farm_card(payload)
        elif action == "playlist_current_details":
            self.handle_playlist_current_details(payload)
        elif action == "playlist_progress":
            if hasattr(self, "playlist_progress_var"):
                current, total = payload
                self.playlist_progress_var.set(f"{current} de {total}")
            if hasattr(self, "farm_progress_var"):
                current, total = payload
                if self.active_screen != "farm":
                    self.farm_progress_var.set(f"{current} de {total}")
        elif action == "play_shortcut":
            if self.active_screen == "execute":
                self.play_execute_macro()
                return
            self.status_var.set("Use a tela Executar Macro para reproduzir macros.")
        elif action == "play_playlist_shortcut":
            if self.active_screen == "playlist":
                self.play_playlist()
                return
            if self.active_screen == "farm":
                self.play_farm()
                return
            self.status_var.set("Use a tela Playlist de macro para executar playlists.")
        elif action == "stop_playlist_shortcut":
            if self.active_screen in {"playlist", "farm"}:
                self.engine.stop_playback()
                return
            self.status_var.set("Use a tela Playlist de macro para parar playlists.")
        elif action == "stop_playback_shortcut":
            if self.active_screen == "execute":
                self.stop_execute_playback()
            else:
                self.engine.stop_playback()
        elif action == "close_shortcut":
            self.handle_close_shortcut()

    def handle_close_shortcut(self):
        if self.focus_displayof() is None:
            self.status_var.set("F2 ignorado: MacroFlow nao esta em foco.")
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
        self.recording_status_var.set(f"*  {self.t('macro.recording')}")
        self.recording_status_label.configure(text_color=("#16a34a", "#22c55e"))
        self.start_record_timer()
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
        self.recording_status_var.set(f"*  {self.t('macro.not_recording')}")
        self.recording_status_label.configure(text_color=("#d63d3d", "#ff5a5f"))
        self.stop_record_timer()
        self.set_record_button_idle()

    def change_theme(self):
        ctk.set_appearance_mode(self.theme_var.get())
        self.apply_tree_style()
        self.save_app_config()

    def render_shortcut_pills(self):
        for child in self.shortcuts_frame.winfo_children():
            child.destroy()

        for action in ("record", "close"):
            label = self.shortcut_action_label(action)
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

    def shortcut_action_label(self, action):
        label = self.t(f"shortcuts.{action}")
        return label if label != f"shortcuts.{action}" else SHORTCUT_LABELS[action]

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
        self.refresh_shortcut_button_labels()
        self.status_var.set("Atalhos atualizados.")
        return True

    def refresh_shortcut_button_labels(self):
        if hasattr(self, "execute_play_button"):
            self.execute_play_button.configure(text=f"{shortcut_label(self.shortcuts['play'])}  {self.t('execute.play')}")
        if hasattr(self, "execute_stop_button"):
            self.execute_stop_button.configure(
                text=f"{shortcut_label(self.shortcuts['stop_playback'])}  {self.t('execute.stop')}"
            )
        if hasattr(self, "playlist_play_button"):
            self.playlist_play_button.configure(
                text=f"{shortcut_label(self.shortcuts['play_playlist'])}  {self.t('playlist.play')}"
            )
        if hasattr(self, "playlist_stop_button"):
            self.playlist_stop_button.configure(
                text=f"{shortcut_label(self.shortcuts['stop_playlist'])}  {self.t('playlist.stop')}"
            )
        if hasattr(self, "farm_play_button"):
            self.farm_play_button.configure(text=f"{shortcut_label(self.shortcuts['play_playlist'])} {self.t('farm.play')}")
        if hasattr(self, "farm_stop_button"):
            self.farm_stop_button.configure(text=f"{shortcut_label(self.shortcuts['stop_playlist'])} {self.t('farm.stop')}")

    def reset_shortcuts(self):
        self.apply_shortcuts(dict(DEFAULT_SHORTCUTS))

    def load_shortcuts(self):
        return self.shortcut_repository.load()

    def save_shortcuts(self):
        self.shortcut_repository.save(self.shortcuts)

    def set_playback_alert(self, is_playing):
        if not hasattr(self, "playback_alert"):
            return
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

    def start_record_timer(self):
        self.record_timer_running = True
        self.record_timer_started_at = time.perf_counter()
        if hasattr(self, "record_elapsed_var"):
            self.record_elapsed_var.set("00:00:00")
        self.update_record_timer()

    def stop_record_timer(self):
        self.record_timer_running = False
        if hasattr(self, "record_elapsed_var"):
            self.record_elapsed_var.set("00:00:00")

    def update_record_timer(self):
        if not self.record_timer_running or not hasattr(self, "record_elapsed_var"):
            return
        elapsed = int(time.perf_counter() - self.record_timer_started_at)
        hours = elapsed // 3600
        minutes = (elapsed % 3600) // 60
        seconds = elapsed % 60
        self.record_elapsed_var.set(f"{hours:02d}:{minutes:02d}:{seconds:02d}")
        self.after(250, self.update_record_timer)

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

    def start_playlist_timer(self):
        self.playlist_timer_running = True
        self.playlist_timer_started_at = time.perf_counter()
        if hasattr(self, "playlist_elapsed_var"):
            self.playlist_elapsed_var.set("00:00:00")
        if hasattr(self, "playlist_current_var"):
            self.playlist_current_var.set("-")
        if hasattr(self, "playlist_progress_var"):
            self.playlist_progress_var.set("-")
        self.update_playlist_timer()

    def stop_playlist_timer(self):
        self.playlist_timer_running = False
        if hasattr(self, "playlist_elapsed_var"):
            self.playlist_elapsed_var.set("00:00:00")
        if hasattr(self, "playlist_current_var"):
            self.playlist_current_var.set("-")
        if hasattr(self, "playlist_progress_var"):
            self.playlist_progress_var.set("-")

    def update_playlist_timer(self):
        if not self.playlist_timer_running or not hasattr(self, "playlist_elapsed_var"):
            return
        elapsed = int(time.perf_counter() - self.playlist_timer_started_at)
        hours = elapsed // 3600
        minutes = (elapsed % 3600) // 60
        seconds = elapsed % 60
        self.playlist_elapsed_var.set(f"{hours:02d}:{minutes:02d}:{seconds:02d}")
        self.after(250, self.update_playlist_timer)

    def start_farm_timer(self):
        self.farm_timer_running = True
        self.farm_timer_started_at = time.perf_counter()
        if hasattr(self, "farm_elapsed_var"):
            self.farm_elapsed_var.set("00:00:00")
        if hasattr(self, "farm_progress_var"):
            self.farm_progress_var.set("-")
        if hasattr(self, "farm_status_var"):
            self.farm_status_var.set(self.t("farm.running"))
        self.update_farm_timer()

    def stop_farm_timer(self):
        self.farm_timer_running = False
        if hasattr(self, "farm_elapsed_var"):
            self.farm_elapsed_var.set("00:00:00")
        if hasattr(self, "farm_current_var"):
            self.farm_current_var.set("-")
        if hasattr(self, "farm_progress_var"):
            self.farm_progress_var.set("-")
        if hasattr(self, "farm_status_var"):
            self.farm_status_var.set(self.t("farm.waiting"))
        self.reset_farm_card_highlights()

    def handle_playback_finished(self, payload):
        if self.active_screen != "farm" or not isinstance(payload, dict):
            return
        elapsed = 0
        if self.farm_timer_running:
            elapsed = int(time.perf_counter() - self.farm_timer_started_at)
        message = str(payload.get("message") or "")
        if message.lower().startswith("erro"):
            if self.telegram_config.notify_errors:
                self.notify_telegram(
                    self.telegram_message(
                        self.t("telegram.farm_error"),
                        f"{self.t('telegram.error')}: {message}",
                    )
                )
        elif payload.get("completed"):
            if self.telegram_config.notify_farm_finished:
                self.notify_telegram(
                    self.telegram_message(
                        self.t("telegram.farm_finished"),
                        f"{self.t('telegram.total_time')}: {self.format_elapsed_seconds(elapsed)}",
                    )
                )
        elif self.telegram_config.notify_farm_stopped:
            self.notify_telegram(
                self.telegram_message(
                    self.t("telegram.farm_stopped"),
                    f"{self.t('telegram.total_time')}: {self.format_elapsed_seconds(elapsed)}",
                )
            )
        shutdown_enabled = hasattr(self, "farm_shutdown_var") and self.farm_shutdown_var.get()
        if not payload.get("completed") or not shutdown_enabled:
            return
        self.log_farm(self.t("farm.shutdown_started"))
        try:
            subprocess.Popen(["shutdown", "/s", "/f", "/t", "0"])
        except OSError as exc:
            self.log_farm(f"{self.t('farm.shutdown_error')} {exc}")

    def toggle_farm_shutdown_on_finish(self):
        self.farm_shutdown_var.set(not self.farm_shutdown_var.get())
        self.update_farm_shutdown_button()
        self.save_farm_config()

    def update_farm_shutdown_button(self):
        if not hasattr(self, "farm_shutdown_button"):
            return
        if self.farm_shutdown_var.get():
            self.farm_shutdown_button.configure(
                text=f"[PC]  {self.t('farm.shutdown_enabled')}",
                fg_color="#16a34a",
                hover_color="#15803d",
                text_color="#ffffff",
            )
        else:
            self.farm_shutdown_button.configure(
                text=f"[PC]  {self.t('farm.shutdown_disabled')}",
                fg_color="#dc2626",
                hover_color="#b91c1c",
                text_color="#ffffff",
            )

    def update_farm_last_car_position(self):
        try:
            row = int(self.farm_car_row_var.get())
            column = int(self.farm_car_column_var.get())
            repeats = int(self.farm_roulette_quantity_var.get())
        except ValueError:
            messagebox.showerror(self.t("farm.calculate_last_car"), self.t("farm.invalid_calculator_values"))
            return False

        if row < 1 or row > 3 or column < 1 or repeats < 1 or repeats > 33:
            messagebox.showerror(self.t("farm.calculate_last_car"), self.t("farm.invalid_calculator_values"))
            return False

        try:
            target = self.calculate_last_car_position_use_case.execute(MatrixPosition(row, column), repeats)
        except ValueError:
            messagebox.showerror(self.t("farm.calculate_last_car"), self.t("farm.invalid_calculator_values"))
            return False
        self.farm_last_car_row_var.set(str(target.linha))
        self.farm_last_car_column_var.set(str(target.coluna))
        result = f"L{target.linha}C{target.coluna}"
        self.log_farm(f"{self.t('farm.last_car_result')}: {result}")
        self.save_farm_config()
        return True

    def handle_playlist_current_details(self, payload):
        if not isinstance(payload, dict):
            return
        name = payload.get("farm_source_name") or payload.get("name")
        if not name:
            return
        if self.active_screen == "farm" and hasattr(self, "farm_current_var"):
            self.farm_current_var.set(name)
            self.farm_next_var.set(name)
            self.highlight_running_farm_card(name)
            if self.telegram_config.notify_macro_started and name != self.last_notified_farm_macro:
                self.last_notified_farm_macro = name
                self.notify_telegram(
                    self.telegram_message(
                        self.t("telegram.macro_started"),
                        f"{self.t('telegram.macro')}: {name}",
                    )
                )
            current = payload.get("farm_repeat_current")
            total = payload.get("farm_repeat_total")
            if current is not None and total is not None:
                self.farm_progress_var.set(f"{current} de {total}")

    def update_farm_timer(self):
        if not self.farm_timer_running or not hasattr(self, "farm_elapsed_var"):
            return
        elapsed = int(time.perf_counter() - self.farm_timer_started_at)
        hours = elapsed // 3600
        minutes = (elapsed % 3600) // 60
        seconds = elapsed % 60
        self.farm_elapsed_var.set(f"{hours:02d}:{minutes:02d}:{seconds:02d}")
        self.after(250, self.update_farm_timer)

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

    def new_macro(self):
        self.current_file = None
        self.selected_macro_path = None
        self.events = []
        self.engine.events = []
        self.name_var.set("")
        self.order_var.set("")
        self.brand_position_var.set(False)
        self.car_position_var.set(False)
        self.last_car_position_var.set(False)
        self.repeat_enabled_var.set(False)
        self.mastery_var.set(False)
        self.manual_var.set("")
        self.color_var.set(DEFAULT_MACRO_COLOR)
        self.update_color_palette_selection()
        self.update_composite_hint()
        self.render_events()
        self.update_macro_selection()
        self.live_inputs_var.set(self.t("macro.nothing_pressed"))
        self.live_action_var.set(self.t("macro.user_waiting"))
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

        try:
            metadata = self.current_macro_metadata()
        except ValueError as exc:
            messagebox.showerror(self.t("macro.invalid_order_title"), str(exc))
            return

        path = MACROS_DIR / f"{safe_name}.json"
        data = {
            "version": 1,
            "name": name,
            "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "events": self.events,
            **metadata,
        }
        self.save_macro_use_case.execute(path, data)
        self.current_file = path
        self.selected_macro_path = path
        self.refresh_macro_list(select_path=path)
        if hasattr(self, "execute_macro_scroll"):
            self.refresh_execute_macro_list(select_path=path)
        if hasattr(self, "playlist_macro_scroll"):
            self.refresh_playlist_macro_list(select_path=path)
        self.status_var.set(f"Macro salva: {path.name}")

    def import_macro_json(self):
        file_path = filedialog.askopenfilename(
            title=self.t("macro.import_json"),
            filetypes=(("JSON", "*.json"), (self.t("macro.all_files"), "*.*")),
        )
        if not file_path:
            return

        path = Path(file_path)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            messagebox.showerror(
                self.t("macro.invalid_title"),
                f"{self.t('macro.import_error')} {path.name}.\n\n{exc}",
            )
            return

        events = data.get("events")
        if not isinstance(events, list):
            messagebox.showerror(self.t("macro.invalid_title"), self.t("macro.events_required"))
            return

        self.current_file = None
        self.selected_macro_path = None
        self.name_var.set(data.get("name") or path.stem)
        self.apply_macro_metadata(data)
        self.events = events
        self.engine.events = list(self.events)
        self.render_events()
        self.update_macro_selection()
        self.status_var.set(f"{self.t('macro.imported')}: {path.name}")

    def export_macro_json(self):
        self.sync_events_from_engine()
        name = self.name_var.get().strip() or "macro"
        default_name = f"{self.safe_macro_name(name) or 'macro'}.json"
        file_path = filedialog.asksaveasfilename(
            title=self.t("macro.export_json"),
            defaultextension=".json",
            initialfile=default_name,
            filetypes=(("JSON", "*.json"), (self.t("macro.all_files"), "*.*")),
        )
        if not file_path:
            return

        path = Path(file_path)
        try:
            metadata = self.current_macro_metadata()
        except ValueError as exc:
            messagebox.showerror(self.t("macro.invalid_order_title"), str(exc))
            return
        data = {
            "version": 1,
            "name": name,
            "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "events": self.events,
            **metadata,
        }
        try:
            self.macro_repository.save(path, data)
        except OSError as exc:
            messagebox.showerror(
                self.t("macro.export_error_title"),
                f"{self.t('macro.export_error')} {path.name}.\n\n{exc}",
            )
            return
        self.status_var.set(f"{self.t('macro.exported')}: {path.name}")

    def current_macro_metadata(self):
        order_text = self.order_var.get().strip()
        if order_text:
            try:
                order = int(order_text)
            except ValueError as exc:
                raise ValueError(self.t("macro.invalid_order")) from exc
        else:
            order = None
        return {
            "ordem": order,
            "possicaoMarca": bool(self.brand_position_var.get()),
            "posicaoCarro": bool(self.car_position_var.get()),
            "posicaoUltimoCarro": bool(self.last_car_position_var.get()),
            "ativarRepeticao": bool(self.repeat_enabled_var.get()),
            "maestria": bool(self.mastery_var.get()),
            "manual": self.manual_var.get().strip(),
            "cor": self.normalized_macro_color({"cor": self.color_var.get()}),
        }

    def apply_macro_metadata(self, data):
        order = data.get("ordem")
        self.order_var.set("" if order is None else str(order))
        self.brand_position_var.set(bool(data.get("possicaoMarca", False)))
        self.car_position_var.set(bool(data.get("posicaoCarro", False)))
        self.last_car_position_var.set(bool(data.get("posicaoUltimoCarro", False)))
        self.repeat_enabled_var.set(bool(data.get("ativarRepeticao", False)))
        self.mastery_var.set(bool(data.get("maestria", False)))
        manual = str(data.get("manual", "") or "")
        self.manual_var.set(manual if manual in self.load_manual_options() else "")
        self.color_var.set(self.normalized_macro_color(data))
        self.update_color_palette_selection()
        self.update_composite_hint()

    def select_macro_color(self, color):
        self.color_var.set(self.normalized_macro_color({"cor": color}))
        self.update_color_palette_selection()

    def update_color_palette_selection(self):
        if not hasattr(self, "color_buttons"):
            return
        selected_color = self.normalized_macro_color({"cor": self.color_var.get()})
        for button, color in self.color_buttons:
            button.configure(border_color="#ffffff" if color == selected_color else "#334155")

    def update_composite_hint(self):
        if not hasattr(self, "composite_hint_label"):
            return
        if self.brand_position_var.get() or self.car_position_var.get() or self.last_car_position_var.get():
            self.composite_hint_label.grid()
        else:
            self.composite_hint_label.grid_remove()

    @staticmethod
    def normalized_macro_color(data):
        color = (data or {}).get("cor", DEFAULT_MACRO_COLOR)
        if not isinstance(color, str):
            return DEFAULT_MACRO_COLOR
        color = color.strip()
        if len(color) != 7 or not color.startswith("#"):
            return DEFAULT_MACRO_COLOR
        try:
            int(color[1:], 16)
        except ValueError:
            return DEFAULT_MACRO_COLOR
        return color.lower()

    def macro_display_name(self, path=None, data=None):
        data = data or self.read_macro_data(path)
        name = (data or {}).get("name") or (path.stem if path else self.t("execute.none"))
        order = (data or {}).get("ordem")
        if order is None or order == "":
            return name
        return f"[{order}] {name}"

    def macro_color_for_path(self, path):
        return self.normalized_macro_color(self.read_macro_data(path))

    @staticmethod
    def read_macro_data(path):
        return JsonMacroRepository().read(path)

    def load_macro(self, path):
        data = self.macro_repository.read(path)
        if not data:
            messagebox.showerror("Macro invalida", f"Nao foi possivel carregar {path.name}.")
            self.status_var.set(f"Erro ao carregar macro: {path.name}")
            return

        self.current_file = path
        self.selected_macro_path = path
        self.name_var.set(data.get("name") or path.stem)
        self.apply_macro_metadata(data)
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
        if hasattr(self, "playlist_macro_scroll"):
            self.refresh_playlist_macro_list()

    def refresh_macro_list(self, select_path=None):
        for button, _path in self.macro_buttons:
            button.destroy()
        self.macro_buttons = []
        self.macro_paths = sorted(MACROS_DIR.glob("*.json"))

        for index, path in enumerate(self.macro_paths):
            data = self.read_macro_data(path)
            color = self.normalized_macro_color(data)
            button = ctk.CTkButton(
                self.macro_scroll,
                text=self.macro_display_name(path, data),
                anchor="w",
                fg_color="transparent",
                text_color=("gray10", "gray90"),
                hover_color=("#d8e6f3", "#333333"),
                command=lambda selected=path: self.load_macro(selected),
                border_width=1,
                border_color=color,
            )
            button.grid(row=index, column=0, sticky="ew", padx=4, pady=4)
            self.macro_buttons.append((button, path))

        self.update_macro_selection()

        if select_path in self.macro_paths:
            self.load_macro(select_path)

    def update_macro_selection(self):
        for button, path in self.macro_buttons:
            if self.selected_macro_path == path:
                color = self.macro_color_for_path(path)
                button.configure(
                    fg_color=("#d8ecff", "#14395c"),
                    hover_color=("#c7e2fb", "#1d4f7a"),
                    border_width=2,
                    border_color=color,
                    text_color=("#0f172a", "#ffffff"),
                )
            else:
                color = self.macro_color_for_path(path)
                button.configure(
                    fg_color="transparent",
                    hover_color=("#d8e6f3", "#333333"),
                    border_width=1,
                    border_color=color,
                    text_color=("gray10", "gray90"),
                )

    def refresh_execute_macro_list(self, select_path=None):
        for button, _path in self.execute_macro_buttons:
            button.destroy()
        self.execute_macro_buttons = []
        self.execute_macro_paths = sorted(MACROS_DIR.glob("*.json"))

        for index, path in enumerate(self.execute_macro_paths):
            data = self.read_macro_data(path)
            color = self.normalized_macro_color(data)
            button = ctk.CTkButton(
                self.execute_macro_scroll,
                text=self.macro_display_name(path, data),
                anchor="w",
                fg_color="transparent",
                text_color=("gray10", "gray90"),
                hover_color=("#d8e6f3", "#1b2b42"),
                command=lambda selected=path: self.select_execute_macro(selected),
                border_width=1,
                border_color=color,
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
        display_name = self.macro_display_name(path, data)
        duration = self.macro_duration(self.execute_selected_events)
        self.execute_summary_var.set(
            f"{display_name} | {len(self.execute_selected_events)} {self.t('execute.events')} | "
            f"{self.t('execute.duration')}: {duration}"
        )
        self.execute_status_label.configure(text=display_name)
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
                color = self.macro_color_for_path(path)
                button.configure(
                    fg_color=("#d8ecff", "#14395c"),
                    hover_color=("#c7e2fb", "#1d4f7a"),
                    border_width=2,
                    border_color=color,
                    text_color=("#0f172a", "#ffffff"),
                )
            else:
                color = self.macro_color_for_path(path)
                button.configure(
                    fg_color="transparent",
                    hover_color=("#d8e6f3", "#1b2b42"),
                    border_width=1,
                    border_color=color,
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

    def refresh_playlist_macro_list(self, select_path=None):
        for button, _path in self.playlist_macro_buttons:
            button.destroy()
        self.playlist_macro_buttons = []
        self.playlist_macro_paths = sorted(MACROS_DIR.glob("*.json"))

        for index, path in enumerate(self.playlist_macro_paths):
            data = self.read_macro_data(path)
            color = self.normalized_macro_color(data)
            button = ctk.CTkButton(
                self.playlist_macro_scroll,
                text=self.macro_display_name(path, data),
                anchor="w",
                fg_color="transparent",
                text_color=("gray10", "gray90"),
                hover_color=("#d8e6f3", "#1b2b42"),
                command=lambda selected=path: self.select_playlist_macro(selected),
                border_width=1,
                border_color=color,
            )
            button.grid(row=index, column=0, sticky="ew", padx=4, pady=4)
            self.playlist_macro_buttons.append((button, path))

        if select_path in self.playlist_macro_paths:
            self.select_playlist_macro(select_path)
        elif self.playlist_selected_path not in self.playlist_macro_paths:
            self.playlist_selected_path = None
            if hasattr(self, "playlist_selected_var"):
                self.playlist_selected_var.set(self.t("playlist.select_hint"))
        self.update_playlist_macro_selection()

    def select_playlist_macro(self, path):
        self.playlist_selected_path = path
        self.playlist_selected_var.set(self.macro_display_name(path))
        self.update_playlist_macro_selection()

    def update_playlist_macro_selection(self):
        for button, path in self.playlist_macro_buttons:
            if self.playlist_selected_path == path:
                color = self.macro_color_for_path(path)
                button.configure(
                    fg_color=("#d8ecff", "#14395c"),
                    hover_color=("#c7e2fb", "#1d4f7a"),
                    border_width=2,
                    border_color=color,
                    text_color=("#0f172a", "#ffffff"),
                )
            else:
                color = self.macro_color_for_path(path)
                button.configure(
                    fg_color="transparent",
                    hover_color=("#d8e6f3", "#1b2b42"),
                    border_width=1,
                    border_color=color,
                    text_color=("gray10", "gray90"),
                )

    def add_selected_macro_to_playlist(self):
        if self.playlist_selected_path is None:
            self.playlist_selected_var.set(self.t("playlist.select_hint"))
            return
        try:
            data = json.loads(self.playlist_selected_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            messagebox.showerror("Macro invalida", f"Nao foi possivel carregar {self.playlist_selected_path.name}.\n\n{exc}")
            return
        self.playlist_items.append(
            {
                "name": data.get("name") or self.playlist_selected_path.stem,
                "display_name": self.macro_display_name(self.playlist_selected_path, data),
                "ordem": data.get("ordem"),
                "possicaoMarca": bool(data.get("possicaoMarca", False)),
                "posicaoCarro": bool(data.get("posicaoCarro", False)),
                "cor": self.normalized_macro_color(data),
                "path": self.playlist_selected_path,
                "kind": data.get("kind"),
                "matrix": data.get("matrix"),
                "events": data.get("events", []),
            }
        )
        self.playlist_selected_index = len(self.playlist_items) - 1
        self.render_playlist_items()

    def render_playlist_items(self):
        for child in self.playlist_sequence_scroll.winfo_children():
            child.destroy()
        if not self.playlist_items:
            ctk.CTkLabel(
                self.playlist_sequence_scroll,
                text=self.t("playlist.empty"),
                text_color=("gray35", "gray72"),
            ).grid(row=0, column=0, padx=12, pady=16, sticky="w")
            return
        for index, item in enumerate(self.playlist_items):
            selected = index == self.playlist_selected_index
            color = self.normalized_macro_color(item)
            button = ctk.CTkButton(
                self.playlist_sequence_scroll,
                text=f"{index + 1}. {item.get('display_name') or item['name']}",
                anchor="w",
                fg_color=("#eadcff", "#3b1764") if selected else "transparent",
                hover_color=("#e1d0fb", "#4a2377"),
                text_color=("gray10", "gray90"),
                border_width=2 if selected else 1,
                border_color=color,
                command=lambda selected_index=index: self.select_playlist_item(selected_index),
            )
            button.grid(row=index, column=0, sticky="ew", padx=4, pady=4)

    def select_playlist_item(self, index):
        self.playlist_selected_index = index
        self.render_playlist_items()

    def remove_selected_playlist_item(self):
        if self.playlist_selected_index is None:
            return
        del self.playlist_items[self.playlist_selected_index]
        if not self.playlist_items:
            self.playlist_selected_index = None
        else:
            self.playlist_selected_index = min(self.playlist_selected_index, len(self.playlist_items) - 1)
        self.render_playlist_items()

    def clear_playlist(self):
        self.playlist_items = []
        self.playlist_selected_index = None
        self.render_playlist_items()

    def play_playlist(self):
        try:
            repeats = int(self.playlist_repeats_var.get())
        except ValueError:
            messagebox.showerror(self.t("playlist.title"), self.t("playlist.invalid_repeats"))
            return
        if repeats <= 0:
            messagebox.showerror(self.t("playlist.title"), self.t("playlist.invalid_repeats"))
            return
        self.engine.play_playlist(list(self.playlist_items), repeats)

    def refresh_farm_macros(self):
        if not hasattr(self, "farm_macro_scroll"):
            return
        for child in self.farm_macro_scroll.winfo_children():
            child.destroy()
        self.farm_items = self.load_farm_macros()
        self.render_farm_repetition_controls()
        if not self.farm_items:
            ctk.CTkLabel(
                self.farm_macro_scroll,
                text=self.t("farm.empty"),
                text_color=("gray35", "gray72"),
            ).grid(row=0, column=0, padx=16, pady=18, sticky="w")
            self.update_farm_total()
            return
        for index, item in enumerate(self.farm_items):
            self.create_farm_macro_row(index, item)
        self.update_farm_total()
        self.log_farm(self.t("farm.ready"))

    def render_farm_repetition_controls(self):
        if not hasattr(self, "farm_repetitions_status_var"):
            return
        repeat_items = [item for item in getattr(self, "farm_items", []) if item.get("ativarRepeticao")]
        if not repeat_items:
            self.farm_repetitions_status_var.set(self.t("farm.no_repeat_macros"))
            return
        self.farm_repetitions_status_var.set(self.t("farm.global_repeats_hint"))

    def load_farm_macros(self):
        items = []
        for path in MACROS_DIR.glob("*.json"):
            data = self.read_macro_data(path)
            order = data.get("ordem")
            if not isinstance(order, int) or order <= 0:
                continue
            item = {
                "path": path,
                "name": data.get("name") or path.stem,
                "display_name": self.macro_display_name(path, data),
                "ordem": order,
                "cor": self.normalized_macro_color(data),
                "possicaoMarca": bool(data.get("possicaoMarca", False)),
                "posicaoCarro": bool(data.get("posicaoCarro", False)),
                "posicaoUltimoCarro": bool(data.get("posicaoUltimoCarro", False)),
                "ativarRepeticao": bool(data.get("ativarRepeticao", False)),
                "maestria": bool(data.get("maestria", False)),
                "manual": str(data.get("manual", "") or ""),
                "kind": data.get("kind"),
                "matrix": data.get("matrix"),
                "events": data.get("events", []),
            }
            saved = self.farm_config.get("macros", {}).get(self.farm_macro_config_key(item), {})
            item["ignore_var"] = tk.BooleanVar(value=bool(saved.get("ignorarItem", False)))
            items.append(item)
        return sorted(items, key=lambda item: item["ordem"])

    @staticmethod
    def farm_macro_config_key(item):
        path = item.get("path")
        if path:
            return str(Path(path).name)
        return item.get("name", "")

    def create_farm_macro_row(self, index, item):
        row = self.create_execute_card(self.farm_macro_scroll)
        row.configure(border_width=2, border_color=self.normalized_macro_color(item))
        item["row_card"] = row
        row.grid(row=index, column=0, padx=0, pady=(0, 10), sticky="ew")
        row.grid_columnconfigure(1, weight=1)
        row.grid_columnconfigure(2, weight=0, minsize=170)
        ctk.CTkLabel(row, text="::", text_color=("gray45", "gray60"), font=ctk.CTkFont(size=18, weight="bold")).grid(
            row=0, column=0, padx=(18, 12), pady=16
        )
        title = ctk.CTkFrame(row, fg_color="transparent")
        title.grid(row=0, column=1, padx=(0, 18), pady=(16, 8), sticky="w")
        if item.get("manual"):
            ctk.CTkButton(
                title,
                text="",
                image=self.get_folder_icon_image(),
                width=28,
                height=28,
                corner_radius=6,
                fg_color="#facc15",
                hover_color="#eab308",
                command=lambda selected=item: self.open_farm_macro_popup(selected),
            ).pack(side="left", padx=(0, 8))
        ctk.CTkLabel(title, text=item["display_name"], font=ctk.CTkFont(size=16, weight="bold")).pack(side="left")
        for label_text, label_color in self.farm_position_badges(item):
            ctk.CTkLabel(
                title,
                text=label_text,
                height=24,
                corner_radius=4,
                fg_color=label_color,
                text_color="#ffffff",
                font=ctk.CTkFont(size=12, weight="bold"),
            ).pack(side="left", padx=(10, 0))

        actions = ctk.CTkFrame(row, fg_color="transparent")
        actions.grid(row=0, column=2, padx=(12, 18), pady=(16, 8), sticky="e")
        ignore_button = ctk.CTkButton(
            actions,
            width=118,
            height=28,
            corner_radius=6,
            command=lambda selected=item: self.toggle_farm_ignore_item(selected),
        )
        ignore_button.pack(side="left")
        item["ignore_button"] = ignore_button
        self.update_farm_ignore_card(item)

    def get_folder_icon_image(self):
        if not hasattr(self, "folder_icon_image"):
            try:
                folder_image = Image.open(FOLDER_ICON_FILE)
                self.folder_icon_image = ctk.CTkImage(
                    light_image=folder_image,
                    dark_image=folder_image,
                    size=(18, 18),
                )
            except (OSError, tk.TclError):
                self.folder_icon_image = None
        return self.folder_icon_image

    def open_farm_parameters_tutorial(self):
        self.open_manual_popup(self.t("farm.general_parameters"), "parametros_gerais.md")

    def open_farm_macro_popup(self, item):
        self.open_manual_popup(item.get("display_name") or item.get("name") or self.t("farm.title"), item.get("manual"))

    def open_manual_popup(self, title, manual_name):
        manual_name = str(manual_name or "")
        manual_path = MANUAL_DIR / manual_name
        try:
            manual_content = manual_path.read_text(encoding="utf-8")
        except OSError:
            manual_content = self.t("farm.manual_not_found")
            manual_path = MANUAL_DIR

        dialog = ctk.CTkToplevel(self)
        dialog.title(title)
        dialog.geometry("820x640")
        dialog.minsize(640, 460)
        dialog.resizable(True, True)
        dialog.transient(self)
        dialog.grid_columnconfigure(0, weight=1)
        dialog.grid_rowconfigure(1, weight=1)
        ctk.CTkLabel(
            dialog,
            text=title,
            font=ctk.CTkFont(size=18, weight="bold"),
        ).grid(row=0, column=0, padx=22, pady=(22, 8), sticky="w")
        manual_frame = ctk.CTkScrollableFrame(dialog, fg_color=("#f8fbff", "#07111f"))
        manual_frame.grid(row=1, column=0, padx=22, pady=(0, 14), sticky="nsew")
        manual_frame.grid_columnconfigure(0, weight=1)
        dialog.manual_images = []
        self.render_manual_markdown(manual_frame, manual_content, manual_path.parent, dialog.manual_images)
        ctk.CTkButton(
            dialog,
            text=self.t("common.close"),
            fg_color="#5c5f66",
            hover_color="#4d5056",
            command=dialog.destroy,
        ).grid(row=2, column=0, padx=22, pady=(0, 22), sticky="ew")

    def render_manual_markdown(self, parent, content, base_dir, image_refs):
        in_code = False
        code_lines = []
        table_lines = []
        row = 0
        for raw_line in content.splitlines():
            line = raw_line.rstrip()
            if line.strip().startswith("```"):
                if table_lines:
                    row = self.add_manual_code_block(parent, table_lines, row)
                    table_lines = []
                if in_code:
                    row = self.add_manual_code_block(parent, code_lines, row)
                    code_lines = []
                in_code = not in_code
                continue
            if in_code:
                code_lines.append(line)
                continue
            if line.strip().startswith("|"):
                table_lines.append(line)
                continue
            if table_lines:
                row = self.add_manual_code_block(parent, table_lines, row)
                table_lines = []
            row = self.add_manual_markdown_line(parent, line, base_dir, image_refs, row)
        if code_lines:
            row = self.add_manual_code_block(parent, code_lines, row)
        if table_lines:
            self.add_manual_code_block(parent, table_lines, row)

    def add_manual_markdown_line(self, parent, line, base_dir, image_refs, row):
        stripped = line.strip()
        if not stripped:
            return row
        if stripped == "---":
            separator = ctk.CTkFrame(parent, height=1, fg_color=("#d8e0ea", "#20324c"))
            separator.grid(row=row, column=0, padx=6, pady=12, sticky="ew")
            return row + 1

        image_match = re.fullmatch(r"!\[(.*?)\]\((.*?)\)", stripped)
        if image_match:
            return self.add_manual_image(parent, image_match.group(1), image_match.group(2), base_dir, image_refs, row)

        if stripped.startswith("#"):
            level = len(stripped) - len(stripped.lstrip("#"))
            text = self.clean_markdown_text(stripped[level:].strip())
            size = max(16, 28 - (level * 3))
            ctk.CTkLabel(parent, text=text, font=ctk.CTkFont(size=size, weight="bold"), anchor="w").grid(
                row=row, column=0, padx=6, pady=(12, 6), sticky="ew"
            )
            return row + 1

        if stripped.startswith("- "):
            text = f"• {self.clean_markdown_text(stripped[2:])}"
            ctk.CTkLabel(parent, text=text, anchor="w", justify="left", wraplength=720).grid(
                row=row, column=0, padx=18, pady=2, sticky="ew"
            )
            return row + 1

        ctk.CTkLabel(
            parent,
            text=self.clean_markdown_text(stripped),
            anchor="w",
            justify="left",
            wraplength=720,
        ).grid(row=row, column=0, padx=6, pady=3, sticky="ew")
        return row + 1

    def add_manual_image(self, parent, alt_text, image_path, base_dir, image_refs, row):
        resolved = (base_dir / image_path).resolve()
        try:
            image = tk.PhotoImage(file=str(resolved))
        except tk.TclError:
            ctk.CTkLabel(parent, text=f"{alt_text}: {self.t('farm.manual_image_not_found')}", anchor="w").grid(
                row=row, column=0, padx=6, pady=6, sticky="ew"
            )
            return row + 1
        while image.width() > 720:
            image = image.subsample(2, 2)
        image_refs.append(image)
        ctk.CTkLabel(parent, text="", image=image).grid(row=row, column=0, padx=6, pady=10, sticky="w")
        return row + 1

    def add_manual_code_block(self, parent, lines, row):
        text = "\n".join(lines).strip()
        if not text:
            return row
        box = ctk.CTkTextbox(parent, height=min(180, max(54, (len(lines) + 1) * 24)), wrap="none")
        box.grid(row=row, column=0, padx=6, pady=8, sticky="ew")
        box.insert("1.0", text)
        box.configure(state="disabled")
        return row + 1

    @staticmethod
    def clean_markdown_text(text):
        text = re.sub(r"\*\*(.*?)\*\*", r"\1", text)
        text = re.sub(r"`([^`]*)`", r"\1", text)
        return text

    def create_farm_position_subcard(self, parent):
        card = ctk.CTkFrame(
            parent,
            corner_radius=8,
            fg_color=("#f8fbff", "#102033"),
            border_width=1,
            border_color=("#d8e0ea", "#20324c"),
        )
        card.grid_columnconfigure(0, weight=1)
        card.grid_columnconfigure(1, weight=0)
        return card

    def farm_position_badges(self, item):
        badges = []
        if item.get("possicaoMarca"):
            badges.append((self.t("farm.brand_position"), "#2563eb"))
        if item.get("posicaoCarro"):
            badges.append((self.t("farm.car_position"), "#16a34a"))
        if item.get("posicaoUltimoCarro"):
            badges.append((self.t("farm.last_car_position"), "#9333ea"))
        if item.get("maestria"):
            badges.append((self.t("macro.mastery"), "#f59e0b"))
        return badges

    def update_farm_total(self):
        total = 0
        for item in getattr(self, "farm_items", []):
            if item["ignore_var"].get():
                continue
            try:
                total += self.farm_item_repeats(item)
            except ValueError:
                pass
        if hasattr(self, "farm_total_var"):
            self.farm_total_var.set(str(total))

    def farm_item_repeats(self, item):
        if not item.get("ativarRepeticao"):
            return 1
        try:
            repeats = max(0, int(self.farm_roulette_quantity_var.get()))
        except ValueError:
            raise ValueError(self.t("farm.invalid_repeats")) from None
        if item.get("maestria"):
            mastery_repeats = repeats * 3
            if repeats > 9:
                mastery_repeats += 3
            return mastery_repeats
        return repeats

    def toggle_farm_ignore_item(self, item):
        item["ignore_var"].set(not item["ignore_var"].get())
        self.update_farm_ignore_card(item)
        self.update_farm_total()

    def update_farm_ignore_card(self, item):
        button = item.get("ignore_button")
        if button is None:
            return
        if item["ignore_var"].get():
            button.configure(
                text=self.t("farm.ignored"),
                fg_color="#dc2626",
                hover_color="#b91c1c",
                text_color="#ffffff",
            )
        else:
            button.configure(
                text=self.t("farm.active_item"),
                fg_color="#16a34a",
                hover_color="#15803d",
                text_color="#ffffff",
            )

    def highlight_running_farm_card(self, running_name):
        for item in getattr(self, "farm_items", []):
            card = item.get("row_card")
            if card is None:
                continue
            is_running = running_name in {item.get("display_name"), item.get("name")}
            card.configure(
                fg_color="#06402B" if is_running else ("#eef6ff", "#07111f"),
                border_color=self.normalized_macro_color(item),
            )
            if is_running:
                self.scroll_farm_card_into_view(card)

    def scroll_farm_card_into_view(self, card):
        if not hasattr(self, "farm_macro_scroll"):
            return
        self.after(50, lambda selected_card=card: self.perform_farm_card_scroll(selected_card))

    def perform_farm_card_scroll(self, card):
        if not card.winfo_exists() or not hasattr(self, "farm_macro_scroll"):
            return
        canvas = getattr(self.farm_macro_scroll, "_parent_canvas", None)
        if canvas is None or not canvas.winfo_exists():
            return

        self.farm_macro_scroll.update_idletasks()
        canvas.update_idletasks()
        scroll_region = canvas.bbox("all")
        if not scroll_region:
            return

        content_height = max(1, scroll_region[3] - scroll_region[1])
        visible_height = max(1, canvas.winfo_height())
        if content_height <= visible_height:
            canvas.yview_moveto(0)
            return

        card_top = card.winfo_y()
        card_height = max(1, card.winfo_height())
        centered_top = card_top - max(0, (visible_height - card_height) // 2)
        max_scroll = max(1, content_height - visible_height)
        fraction = max(0, min(1, centered_top / max_scroll))
        canvas.yview_moveto(fraction)

    def reset_farm_card_highlights(self):
        for item in getattr(self, "farm_items", []):
            card = item.get("row_card")
            if card is not None:
                card.configure(fg_color=("#eef6ff", "#07111f"), border_color=self.normalized_macro_color(item))

    def play_farm(self):
        self.update_farm_total()
        try:
            interval_ms = max(0, int(self.farm_interval_var.get()))
        except ValueError:
            messagebox.showerror(self.t("farm.title"), self.t("farm.invalid_interval"))
            return
        if not self.update_farm_last_car_position():
            return
        self.save_farm_config()
        try:
            expanded_items = self.build_farm_execution_items(interval_ms)
        except ValueError as exc:
            messagebox.showerror(self.t("farm.title"), str(exc) or self.t("farm.invalid_repeats"))
            return
        if not expanded_items:
            self.log_farm(self.t("farm.empty"))
            return
        self.reset_farm_card_highlights()
        self.last_notified_farm_macro = None
        self.farm_status_var.set(self.t("farm.running"))
        self.farm_next_var.set(expanded_items[0].get("display_name") or expanded_items[0].get("name", "-"))
        if self.telegram_config.notify_farm_started:
            self.notify_telegram(
                self.telegram_message(
                    self.t("telegram.farm_started"),
                    f"{self.t('telegram.total_executions')}: {len(expanded_items)}",
                )
            )
        self.engine.play_playlist(expanded_items, 1)

    def build_farm_execution_items(self, interval_ms):
        expanded_items = []
        for item in self.farm_items:
            if item["ignore_var"].get():
                continue
            repeats = self.farm_item_repeats(item)
            for repeat_index in range(max(0, repeats)):
                play_item = dict(item)
                if item.get("kind") == "matrix_navigation":
                    play_item = resolve_playlist_item_for_repeat(item, repeat_index)
                    play_item["display_name"] = item.get("display_name")
                play_item["farm_repeat_current"] = repeat_index + 1
                play_item["farm_repeat_total"] = max(0, repeats)
                play_item["farm_source_name"] = item.get("display_name") or item.get("name")
                play_item["events"] = self.build_farm_execution_events(
                    play_item.get("events", []),
                    item,
                    interval_ms / 1000,
                    repeat_index,
                )
                expanded_items.append(play_item)
        return expanded_items

    def build_farm_execution_events(self, events, item, interval_seconds, repeat_index=0):
        events = normalize_playback_events(events)
        if self.is_composite_farm_macro(item):
            updated, replaced_marker = self.build_composite_farm_events(events, item, repeat_index)
            if replaced_marker:
                base_duration = self.events_duration(updated)
                if interval_seconds > 0:
                    updated.append({"type": "wait", "t": round(base_duration + interval_seconds, 4)})
                return updated

        updated = [dict(event) for event in events]
        base_duration = self.events_duration(updated)
        if item.get("possicaoMarca"):
            position_events = self.build_brand_position_events()
            updated.extend(self.shift_events(position_events, base_duration + interval_seconds))
            base_duration = self.events_duration(updated)
        if item.get("posicaoCarro"):
            row, column = self.farm_car_position_values_for_repeat(repeat_index)
            position_events = build_matrix_navigation_events(row, column, DEFAULT_MATRIX_STEP_DELAY)
            updated.extend(self.shift_events(position_events, base_duration + interval_seconds))
            base_duration = self.events_duration(updated)
        if item.get("posicaoUltimoCarro"):
            row, column = self.farm_last_car_position_values()
            position_events = build_matrix_navigation_events(row, column, DEFAULT_MATRIX_STEP_DELAY)
            updated.extend(self.shift_events(position_events, base_duration + interval_seconds))
            base_duration = self.events_duration(updated)
        if interval_seconds > 0:
            updated.append({"type": "wait", "t": round(base_duration + interval_seconds, 4)})
        return updated

    @staticmethod
    def is_composite_farm_macro(item):
        return bool(item.get("possicaoMarca")) or bool(item.get("posicaoCarro")) or bool(item.get("posicaoUltimoCarro"))

    def build_composite_farm_events(self, events, item, repeat_index):
        updated = []
        offset = 0.0
        replaced_marker = False
        for event in sorted(events, key=lambda value: float(value.get("t", 0))):
            marker = self.composite_marker_for_event(event, item)
            event_start = float(event.get("t", 0))
            event_duration = float(event.get("duration", 0))
            if marker is None:
                copied = dict(event)
                copied["t"] = round(event_start + offset, 4)
                updated.append(copied)
                continue

            routine_events = self.composite_marker_events(marker, item, repeat_index)
            updated.extend(self.shift_events(routine_events, event_start + offset))
            routine_duration = self.events_duration(routine_events)
            offset += max(0, routine_duration - event_duration)
            replaced_marker = True
        return updated, replaced_marker

    def composite_marker_events(self, marker, item, repeat_index):
        if marker == "insert":
            return self.build_brand_position_events()
        if marker == "end":
            row, column = self.farm_last_car_position_values()
            return build_matrix_navigation_events(row, column, DEFAULT_MATRIX_STEP_DELAY)
        row, column = self.farm_car_position_values_for_repeat(repeat_index)
        return build_matrix_navigation_events(row, column, DEFAULT_MATRIX_STEP_DELAY)

    @staticmethod
    def composite_marker_for_event(event, item):
        if event.get("type") not in ("key", "key_hold"):
            return None
        key = event.get("key", {})
        if key.get("kind") != "special":
            return None
        value = str(key.get("value", "")).lower()
        if value == "insert" and item.get("possicaoMarca"):
            return "insert"
        if value == "delete" and item.get("posicaoCarro"):
            return "delete"
        if value == "end" and item.get("posicaoUltimoCarro"):
            return "end"
        return None

    def build_brand_position_events(self):
        counts = self.farm_brand_direction_counts()
        events = []
        directions = (
            ("up", counts["up"]),
            ("down", counts["down"]),
            ("left", counts["left"]),
            ("right", counts["right"]),
        )
        index = 0
        for direction, count in directions:
            for _ in range(count):
                events.append(
                    {
                        "type": "key_hold",
                        "key": {"kind": "special", "value": direction},
                        "t": round(index * DEFAULT_MATRIX_STEP_DELAY, 4),
                        "duration": 0.05,
                    }
                )
                index += 1
        return events

    def farm_brand_direction_counts(self):
        fields = {
            "up": self.farm_brand_up_var,
            "down": self.farm_brand_down_var,
            "left": self.farm_brand_left_var,
            "right": self.farm_brand_right_var,
        }
        counts = {}
        for direction, variable in fields.items():
            try:
                value = int(variable.get())
            except ValueError as exc:
                raise ValueError(self.t("farm.invalid_direction_counts")) from exc
            counts[direction] = max(0, value)
        return counts

    @staticmethod
    def events_duration(events):
        duration = 0.0
        for event in events:
            start = float(event.get("t", 0))
            duration = max(duration, start + float(event.get("duration", 0)))
        return duration

    def farm_position_values(self, row_var, column_var):
        try:
            row = int(row_var.get())
            column = int(column_var.get())
        except ValueError as exc:
            raise ValueError(self.t("farm.invalid_position")) from exc
        if row < 1 or row > 3:
            raise ValueError(self.t("smart.invalid_row"))
        if column < 1:
            raise ValueError(self.t("smart.invalid_column"))
        return row, column

    def farm_car_position_values(self):
        return self.farm_position_values(self.farm_car_row_var, self.farm_car_column_var)

    def farm_last_car_position_values(self):
        return self.farm_position_values(self.farm_last_car_row_var, self.farm_last_car_column_var)

    def farm_car_position_values_for_repeat(self, repeat_index):
        row, column = self.farm_car_position_values()
        return matrix_target_for_repeat({"target_row": row, "target_column": column}, repeat_index)

    @staticmethod
    def shift_events(events, seconds):
        updated = []
        for event in events:
            item = dict(event)
            item["t"] = round(float(item.get("t", 0)) + seconds, 4)
            updated.append(item)
        return updated

    def log_farm(self, text):
        if not hasattr(self, "farm_log"):
            return
        self.farm_log.insert("end", f"{time.strftime('%H:%M:%S')}  {text}\n")
        self.farm_log.see("end")

    def render_events(self):
        self.table.delete(*self.table.get_children())
        for index, event in enumerate(self.events):
            self.table.insert("", "end", iid=str(index), values=(event.get("t", ""), event.get("type", ""), event_details(event)))
        if self.events:
            self.empty_events_frame.grid_remove()
            self.timeline_frame.grid()
        else:
            self.timeline_frame.grid_remove()
            self.empty_events_frame.grid()
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
        return "".join(ch for ch in name if ch.isalnum() or ch in (" ", "-", "_", "(", ")")).strip()


class LastCarCalculatorDialog(ctk.CTkToplevel):
    def __init__(self, app):
        super().__init__(app)
        self.app = app
        self.title(app.t("farm.calculate_last_car"))
        self.geometry("420x360")
        self.resizable(False, False)
        self.transient(app)
        self.grab_set()

        self.row_var = tk.StringVar(value="1")
        self.column_var = tk.StringVar(value="1")
        self.repeats_var = tk.StringVar(value="1")
        self.result_var = tk.StringVar(value="-")
        self.create_widgets()

    def create_widgets(self):
        self.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            self,
            text=self.app.t("farm.calculate_last_car"),
            font=ctk.CTkFont(size=18, weight="bold"),
        ).grid(row=0, column=0, columnspan=2, padx=22, pady=(22, 8), sticky="w")

        ctk.CTkLabel(
            self,
            text=self.app.t("farm.calculate_last_car_hint"),
            text_color=("gray35", "gray75"),
            wraplength=360,
            justify="left",
        ).grid(row=1, column=0, columnspan=2, padx=22, pady=(0, 16), sticky="w")

        for row, (label_key, variable) in enumerate(
            (
                ("farm.start_row", self.row_var),
                ("farm.start_column", self.column_var),
                ("farm.repeat_count", self.repeats_var),
            ),
            start=2,
        ):
            ctk.CTkLabel(self, text=self.app.t(label_key)).grid(row=row, column=0, padx=(22, 12), pady=8, sticky="w")
            ctk.CTkEntry(self, textvariable=variable).grid(row=row, column=1, padx=(0, 22), pady=8, sticky="ew")

        buttons = ctk.CTkFrame(self, fg_color="transparent")
        buttons.grid(row=5, column=0, columnspan=2, padx=22, pady=(12, 8), sticky="ew")
        buttons.grid_columnconfigure(0, weight=1)
        ctk.CTkButton(
            buttons,
            text=self.app.t("farm.calculate"),
            height=36,
            command=self.calculate,
        ).grid(row=0, column=0, sticky="ew")
        ctk.CTkButton(
            buttons,
            text=self.app.t("shortcuts.cancel"),
            height=36,
            fg_color="#5c5f66",
            hover_color="#4d5056",
            command=self.destroy,
        ).grid(row=0, column=1, padx=(8, 0))

        result = ctk.CTkFrame(self, corner_radius=8, fg_color=("#eef6ff", "#07111f"))
        result.grid(row=6, column=0, columnspan=2, padx=22, pady=(8, 22), sticky="ew")
        result.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(
            result,
            text=self.app.t("farm.last_car_result"),
            font=ctk.CTkFont(size=14, weight="bold"),
        ).grid(row=0, column=0, padx=14, pady=12, sticky="w")
        ctk.CTkLabel(
            result,
            textvariable=self.result_var,
            font=ctk.CTkFont(size=18, weight="bold"),
            text_color="#a855f7",
        ).grid(row=0, column=1, padx=14, pady=12, sticky="e")

    def calculate(self):
        try:
            row = int(self.row_var.get())
            column = int(self.column_var.get())
            repeats = int(self.repeats_var.get())
        except ValueError:
            messagebox.showerror(self.app.t("farm.calculate_last_car"), self.app.t("farm.invalid_calculator_values"))
            return

        if row < 1 or row > 3 or column < 1 or repeats < 1:
            messagebox.showerror(self.app.t("farm.calculate_last_car"), self.app.t("farm.invalid_calculator_values"))
            return

        target_row, target_column = matrix_target_for_repeat(
            {"target_row": row, "target_column": column},
            repeats - 1,
        )
        result = f"L{target_row}C{target_column}"
        self.result_var.set(result)
        self.app.log_farm(f"{self.app.t('farm.last_car_result')}: {result}")


class ShortcutEditor(ctk.CTkToplevel):
    def __init__(self, app, shortcuts):
        super().__init__(app)
        self.app = app
        self.title(app.t("settings.shortcuts_button"))
        self.geometry("500x430")
        self.resizable(False, False)
        self.transient(app)
        self.grab_set()

        self.entries = {}
        self.create_widgets(shortcuts)

    def create_widgets(self, shortcuts):
        self.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            self,
            text=self.app.t("shortcuts.title"),
            font=ctk.CTkFont(size=18, weight="bold"),
        ).grid(row=0, column=0, columnspan=2, padx=22, pady=(22, 8), sticky="w")

        ctk.CTkLabel(
            self,
            text=self.app.t("shortcuts.hint"),
            text_color=("gray35", "gray75"),
        ).grid(row=1, column=0, columnspan=2, padx=22, pady=(0, 16), sticky="w")

        for row, action in enumerate(("play_playlist", "stop_playlist", "record", "play", "stop_playback", "close"), start=2):
            ctk.CTkLabel(self, text=self.app.shortcut_action_label(action)).grid(
                row=row, column=0, padx=(22, 12), pady=8, sticky="w"
            )
            entry = ctk.CTkEntry(self)
            entry.insert(0, shortcut_label(shortcuts[action]))
            entry.grid(row=row, column=1, padx=(0, 22), pady=8, sticky="ew")
            self.entries[action] = entry

        buttons = ctk.CTkFrame(self, fg_color="transparent")
        buttons.grid(row=8, column=0, columnspan=2, padx=22, pady=(18, 22), sticky="ew")

        ctk.CTkButton(
            buttons,
            text=self.app.t("shortcuts.restore"),
            fg_color="#5c5f66",
            hover_color="#4d5056",
            command=self.restore_defaults,
        ).pack(side="left")
        ctk.CTkButton(
            buttons,
            text=self.app.t("shortcuts.cancel"),
            fg_color="#5c5f66",
            hover_color="#4d5056",
            command=self.destroy,
        ).pack(
            side="right", padx=(8, 0)
        )
        ctk.CTkButton(buttons, text=self.app.t("shortcuts.save"), command=self.save).pack(side="right")

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
