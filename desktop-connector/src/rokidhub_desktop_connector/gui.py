from __future__ import annotations

import codecs
import re
import sys
import threading
from pathlib import Path
from typing import Any, NamedTuple

from PySide6.QtCore import QProcess, QProcessEnvironment, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QAction, QActionGroup, QCloseEvent, QDesktopServices, QIcon, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QStackedWidget,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

from .app_server import discover_models
from .api import HubApi
from .autostart import is_autostart_enabled, set_autostart
from .config import ConfigStore, is_local_hub_url, normalize_hub_url
from .icons import IconFactory
from .i18n import Translator
from .token_store import DpapiTokenStore
from . import __version__


ACCESS_KEYS = {
    "read_only": "access_read_only",
    "ask": "access_ask",
    "full_project": "access_full",
}
EFFORT_KEYS = {
    "none": "analysis_none",
    "minimal": "analysis_minimal",
    "low": "analysis_low",
    "medium": "analysis_medium",
    "high": "analysis_high",
    "xhigh": "analysis_xhigh",
    "max": "analysis_max",
    "ultra": "analysis_ultra",
}


class HeroStatusAppearance(NamedTuple):
    title_key: str
    detail_key: str
    icon_name: str
    icon_color: str
    detail_color: str


def hero_status_appearance(
    *,
    running: bool,
    paired: bool,
    local_hub: bool,
    token_for_current_hub: bool,
) -> HeroStatusAppearance:
    if local_hub and paired:
        return HeroStatusAppearance(
            "pc_local_test", "local_hub_not_production", "warning", "#e8b63e", "#f1cb66"
        )
    if paired and not token_for_current_hub:
        return HeroStatusAppearance(
            "pair_required", "hub_changed_pair_hint", "warning", "#e8b63e", "#f1cb66"
        )
    if running:
        return HeroStatusAppearance(
            "pc_connected", "connector_running", "check-circle", "#62f238", "#72f04c"
        )
    if token_for_current_hub:
        return HeroStatusAppearance(
            "pc_paired", "connector_stopped", "power-off", "#899089", "#a8aea7"
        )
    return HeroStatusAppearance("pair_required", "pair_hint", "warning", "#e8b63e", "#f1cb66")


def effort_label(value: str, description: str = "", language: str = "ru") -> str:
    translator = Translator(language)
    title = translator.text(EFFORT_KEYS[value]) if value in EFFORT_KEYS else value
    return f"{title} · {value}" if title != value else value


def utf8_process_environment() -> QProcessEnvironment:
    environment = QProcessEnvironment.systemEnvironment()
    environment.insert("PYTHONUTF8", "1")
    environment.insert("PYTHONIOENCODING", "utf-8")
    return environment


def pairing_code_from_line(line: str) -> str | None:
    prefix = "Одноразовый код:"
    if not line.startswith(prefix):
        return None
    code = line[len(prefix):].strip()
    return code or None


class Utf8LogDecoder:
    """Decode QProcess chunks without breaking UTF-8 characters or partial lines."""

    def __init__(self):
        self._decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        self._pending = ""

    def feed(self, payload: bytes, *, final: bool = False) -> list[str]:
        self._pending += self._decoder.decode(payload, final=final)
        parts = self._pending.splitlines(keepends=True)
        self._pending = ""
        lines: list[str] = []
        for part in parts:
            if part.endswith(("\r", "\n")):
                lines.append(part.rstrip("\r\n"))
            else:
                self._pending = part
        if final and self._pending:
            lines.append(self._pending)
            self._pending = ""
        return lines


class ProjectRadioButton(QRadioButton):
    def __init__(self, text: str, icons: IconFactory):
        super().__init__(text)
        self._icons = icons
        self.setIconSize(QSize(19, 19))
        self.toggled.connect(self._sync_icon)
        self._sync_icon(False)

    def _sync_icon(self, checked: bool) -> None:
        self.setIcon(self._icons.icon("dot-circle-o" if checked else "circle-o", "#62f238" if checked else "#687069"))


class ConnectorWindow(QMainWindow):
    models_ready = Signal(object)
    models_error = Signal(str)
    hub_status_ready = Signal(object)
    hub_status_error = Signal(str)

    def __init__(
        self,
        config_store: ConfigStore,
        token_store: DpapiTokenStore,
        *,
        minimized: bool = False,
        auto_start: bool = False,
    ):
        super().__init__()
        self.config_store = config_store
        self.token_store = token_store
        self.config = config_store.load()
        self.translator = Translator(self.config.language)
        self.icons = IconFactory()
        self.folder_paths = list(self.config.allowed_roots)
        self.models: list[dict[str, Any]] = []
        self.process = QProcess(self)
        self.process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self.process.setProcessEnvironment(utf8_process_environment())
        self.process_output = Utf8LogDecoder()
        self.process.readyReadStandardOutput.connect(self._read_process_output)
        self.process.finished.connect(self._process_finished)
        self.process_purpose = ""
        self.pending_cli: tuple[str, list[str]] | None = None
        self.previous_access_mode = self.config.access_mode
        self._quitting = False
        self._tray_notice_shown = False
        self._log_started = False
        self._syncing = False
        self._nav_buttons: dict[str, QPushButton] = {}
        self._page_headers: dict[str, tuple[QLabel, QLabel | None]] = {}
        self.hub_status: dict[str, Any] | None = None
        self.hub_status_error_message = ""
        self.hub_status_loading = False

        self.models_ready.connect(self._models_loaded)
        self.models_error.connect(self._models_failed)
        self.hub_status_ready.connect(self._hub_status_loaded)
        self.hub_status_error.connect(self._hub_status_failed)

        self.setWindowTitle(self._t("app_title"))
        self.resize(1180, 780)
        self.setMinimumSize(1020, 680)
        icon = self._app_icon()
        if not icon.isNull():
            self.setWindowIcon(icon)
        self._apply_style()
        self._build_ui()
        self._build_tray()
        self._populate_projects()
        self._restore_model_selections()
        self._update_status()
        self._retranslate()
        self.hub_status_timer = QTimer(self)
        self.hub_status_timer.setInterval(30_000)
        self.hub_status_timer.timeout.connect(self._refresh_hub_status)
        self.hub_status_timer.start()
        QTimer.singleShot(0, self._refresh_hub_status)

        if minimized and QSystemTrayIcon.isSystemTrayAvailable():
            self.hide()
        else:
            self.show()
        if auto_start:
            QTimer.singleShot(450, self._start_connector)

    def _t(self, key: str, **values: object) -> str:
        return self.translator.text(key, **values)

    def _apply_style(self) -> None:
        self.setStyleSheet(
            """
            QMainWindow, QWidget#root { background: #050706; color: #f5f6f3; }
            QWidget { color: #f5f6f3; font-family: "Segoe UI Variable", "Segoe UI"; font-size: 14px; }
            QFrame#sidebar { background: #080a09; border-right: 1px solid #202421; }
            QLabel#productName { color: #a8aea7; font-size: 15px; font-weight: 600; }
            QPushButton#navButton { background: transparent; color: #b8bdb7; border: 0; border-radius: 7px;
                text-align: left; padding: 12px 14px; font-size: 15px; }
            QPushButton#navButton:hover { background: #121513; color: #ffffff; }
            QPushButton#navButton:checked { background: #202321; color: #ffffff; border-left: 3px solid #62f238; }
            QLabel#pageTitle { font-size: 30px; font-weight: 700; color: #ffffff; }
            QLabel#pageIntro, QLabel#muted { color: #9da39c; }
            QLabel#statusTitle { font-size: 34px; font-weight: 750; color: #ffffff; }
            QLabel#statusDetail { font-size: 19px; font-weight: 650; }
            QLabel#sectionTitle { font-size: 17px; font-weight: 700; color: #ffffff; }
            QLabel#fieldTitle { color: #a8aea7; font-size: 13px; font-weight: 600; }
            QLabel#pairingCode { color: #ffffff; font-size: 27px; font-weight: 750; letter-spacing: 2px; }
            QFrame#divider { background: #252925; min-height: 1px; max-height: 1px; }
            QFrame#surface { background: #0b0e0c; border: 1px solid #272c28; border-radius: 8px; }
            QPushButton { background: #141815; border: 1px solid #343a35; border-radius: 7px; padding: 9px 15px; }
            QPushButton:hover { background: #1c211d; border-color: #505851; }
            QPushButton:disabled { color: #636963; background: #0d100e; border-color: #232724; }
            QPushButton#primaryButton { background: #65ed3f; color: #071006; border: 0; font-size: 15px; font-weight: 750;
                padding: 12px 22px; min-height: 22px; }
            QPushButton#primaryButton:hover { background: #78f456; }
            QPushButton#dangerButton { color: #ffb6ba; border-color: #694145; }
            QPushButton#connectionCard { background: #0b0e0c; border: 1px solid #303631; border-radius: 9px;
                text-align: left; padding: 13px 16px; min-height: 25px; font-size: 14px; font-weight: 650; }
            QPushButton#connectionCard:hover { background: #121713; border-color: #596159; }
            QPushButton#connectionCard[state="good"] { border-color: #35632f; color: #8ef774; }
            QPushButton#connectionCard[state="warning"] { border-color: #67572e; color: #f1cb66; }
            QPushButton#connectionCard[state="muted"] { color: #a0a7a0; }
            QComboBox, QLineEdit { background: #0d100e; border: 1px solid #303531; border-radius: 7px;
                padding: 9px 11px; min-height: 20px; selection-background-color: #315e2b; }
            QComboBox:hover, QLineEdit:hover { border-color: #505851; }
            QComboBox:focus, QLineEdit:focus { border-color: #62f238; }
            QComboBox QAbstractItemView { background: #111411; color: #f5f6f3; border: 1px solid #343a35;
                selection-background-color: #244b20; outline: 0; }
            QListWidget, QPlainTextEdit { background: #080b09; border: 1px solid #272c28; border-radius: 7px;
                padding: 8px; selection-background-color: #244b20; }
            QListWidget::item { padding: 10px 8px; border-bottom: 1px solid #202420; }
            QListWidget::item:selected { background: #173117; color: #ffffff; }
            QListWidget#activityList { background: transparent; border: 0; padding: 0; }
            QListWidget#activityList::item { padding: 7px 5px; border-bottom: 1px solid #202420; }
            QCheckBox { spacing: 9px; color: #d2d6d0; }
            QCheckBox::indicator { width: 18px; height: 18px; }
            QCheckBox::indicator:unchecked { background: #0d100e; border: 1px solid #4b514c; border-radius: 4px; }
            QCheckBox::indicator:checked { background: #62f238; border: 1px solid #62f238; border-radius: 4px; }
            QRadioButton { spacing: 12px; color: #f5f6f3; font-size: 14px; }
            QRadioButton::indicator { image: none; width: 0px; height: 0px; margin: 0px; padding: 0px; }
            QScrollArea { border: 0; background: transparent; }
            QScrollBar:vertical { background: #080a09; width: 10px; }
            QScrollBar::handle:vertical { background: #343a35; min-height: 30px; border-radius: 5px; }
            QMenu { background: #111411; color: #f5f6f3; border: 1px solid #343a35; padding: 6px; }
            QMenu::item { padding: 8px 28px 8px 12px; border-radius: 4px; }
            QMenu::item:selected { background: #244b20; }
            """
        )

    def _build_ui(self) -> None:
        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)
        layout = QHBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        layout.addWidget(self._build_sidebar())
        self.pages = QStackedWidget()
        self.pages.addWidget(self._build_overview_page())
        self.pages.addWidget(self._build_projects_page())
        self.pages.addWidget(self._build_codex_page())
        self.pages.addWidget(self._build_security_page())
        self.pages.addWidget(self._build_activity_page())
        self.pages.addWidget(self._build_settings_page())
        layout.addWidget(self.pages, 1)

    def _build_sidebar(self) -> QWidget:
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(238)
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(18, 22, 18, 18)
        layout.setSpacing(7)

        brand = QLabel()
        brand.setFixedHeight(54)
        logo = self._asset_path("rokidhub-logo-v1.png")
        if logo:
            pixmap = QPixmap(str(logo)).scaled(190, 52, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            brand.setPixmap(pixmap)
        else:
            brand.setText("RokidHub")
        layout.addWidget(brand)
        self.product_label = QLabel()
        self.product_label.setObjectName("productName")
        self.product_label.setContentsMargins(8, 0, 0, 18)
        layout.addWidget(self.product_label)

        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)
        nav_specs = [
            ("overview", "home", 0),
            ("projects", "folder", 1),
            ("codex", "code", 2),
            ("security", "shield", 3),
            ("activity", "activity", 4),
        ]
        for key, icon_name, index in nav_specs:
            button = QPushButton()
            button.setObjectName("navButton")
            button.setCheckable(True)
            button.setIcon(self.icons.icon(icon_name, "#899089"))
            button.setIconSize(QSize(20, 20))
            button.clicked.connect(lambda _checked=False, page=index: self.pages.setCurrentIndex(page))
            button.toggled.connect(
                lambda checked, target=button, name=icon_name: target.setIcon(
                    self.icons.icon(name, "#62f238" if checked else "#899089")
                )
            )
            self.nav_group.addButton(button)
            self._nav_buttons[key] = button
            layout.addWidget(button)
        self._nav_buttons["overview"].setChecked(True)
        layout.addStretch(1)

        settings = QPushButton()
        settings.setObjectName("navButton")
        settings.setCheckable(True)
        settings.setIcon(self.icons.icon("settings", "#899089"))
        settings.setIconSize(QSize(20, 20))
        settings.clicked.connect(lambda: self.pages.setCurrentIndex(5))
        settings.toggled.connect(
            lambda checked: settings.setIcon(self.icons.icon("settings", "#62f238" if checked else "#899089"))
        )
        self.nav_group.addButton(settings)
        self._nav_buttons["settings"] = settings
        layout.addWidget(settings)
        return sidebar

    def _page_shell(self, key: str, intro_key: str | None = None) -> tuple[QWidget, QVBoxLayout]:
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(40, 32, 40, 32)
        outer.setSpacing(20)
        title = QLabel()
        title.setObjectName("pageTitle")
        outer.addWidget(title)
        intro = None
        if intro_key:
            intro = QLabel()
            intro.setObjectName("pageIntro")
            intro.setWordWrap(True)
            outer.addWidget(intro)
        self._page_headers[key] = (title, intro)
        return page, outer

    def _build_overview_page(self) -> QWidget:
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(42, 34, 42, 30)
        outer.setSpacing(18)

        hero = QHBoxLayout()
        self.status_icon = QLabel()
        self.status_icon.setFixedSize(104, 104)
        self.status_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hero.addWidget(self.status_icon)
        status_text = QVBoxLayout()
        status_text.setSpacing(4)
        self.status_title = QLabel()
        self.status_title.setObjectName("statusTitle")
        self.status_title.setWordWrap(True)
        self.status_title.setMinimumWidth(0)
        self.status_detail = QLabel()
        self.status_detail.setObjectName("statusDetail")
        self.status_detail.setWordWrap(True)
        self.status_detail.setMinimumWidth(0)
        status_text.addStretch(1)
        status_text.addWidget(self.status_title)
        status_text.addWidget(self.status_detail)
        status_text.addStretch(1)
        hero.addLayout(status_text, 1)
        self.start_button = QPushButton()
        self.start_button.setObjectName("primaryButton")
        self.start_button.setIcon(self.icons.icon("play", "#071006"))
        self.start_button.clicked.connect(self._start_connector)
        hero.addWidget(self.start_button, 0, Qt.AlignmentFlag.AlignVCenter)
        self.stop_button = QPushButton()
        self.stop_button.setIcon(self.icons.icon("stop", "#a8aea7"))
        self.stop_button.clicked.connect(self._stop_process)
        hero.addWidget(self.stop_button, 0, Qt.AlignmentFlag.AlignVCenter)
        outer.addLayout(hero)

        self.privacy_label = QLabel()
        self.privacy_label.setObjectName("pageIntro")
        self.privacy_label.setWordWrap(True)
        outer.addWidget(self.privacy_label)

        connections = QHBoxLayout()
        connections.setSpacing(12)
        self.pc_connection_button = QPushButton()
        self.pc_connection_button.setObjectName("connectionCard")
        self.pc_connection_button.setIconSize(QSize(20, 20))
        self.pc_connection_button.clicked.connect(self._show_settings)
        connections.addWidget(self.pc_connection_button, 1)
        self.glasses_connection_button = QPushButton()
        self.glasses_connection_button.setObjectName("connectionCard")
        self.glasses_connection_button.setIconSize(QSize(20, 20))
        self.glasses_connection_button.clicked.connect(self._open_hub_dashboard)
        connections.addWidget(self.glasses_connection_button, 1)
        outer.addLayout(connections)
        outer.addWidget(self._divider())

        grid = QGridLayout()
        grid.setHorizontalSpacing(38)
        grid.setVerticalSpacing(8)
        self.current_project_title = self._field_title()
        self.access_title = self._field_title()
        grid.addWidget(self.current_project_title, 0, 0)
        grid.addWidget(self.access_title, 0, 1)
        self.project_combo = QComboBox()
        self.project_combo.currentIndexChanged.connect(self._overview_project_changed)
        self.overview_access_combo = QComboBox()
        self.overview_access_combo.currentIndexChanged.connect(lambda: self._access_changed(self.overview_access_combo))
        grid.addWidget(self.project_combo, 1, 0)
        grid.addWidget(self.overview_access_combo, 1, 1)
        self.voice_alias_title = self._field_title()
        grid.addWidget(self.voice_alias_title, 2, 0)
        self.voice_alias_label = QLabel()
        self.voice_alias_label.setObjectName("muted")
        grid.addWidget(self.voice_alias_label, 3, 0)
        self.overview_security_label = QLabel()
        self.overview_security_label.setObjectName("muted")
        self.overview_security_label.setWordWrap(True)
        grid.addWidget(self.overview_security_label, 2, 1, 2, 1)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        outer.addLayout(grid)

        self.recent_title = QLabel()
        self.recent_title.setObjectName("sectionTitle")
        outer.addWidget(self.recent_title)
        self.activity_preview = QListWidget()
        self.activity_preview.setObjectName("activityList")
        self.activity_preview.setIconSize(QSize(18, 18))
        self.activity_preview.setMaximumHeight(190)
        outer.addWidget(self.activity_preview, 1)
        return page

    def _build_projects_page(self) -> QWidget:
        page, outer = self._page_shell("projects", "projects_intro")
        self.project_list = QListWidget()
        outer.addWidget(self.project_list, 1)
        actions = QHBoxLayout()
        self.add_project_button = QPushButton()
        self.add_project_button.setIcon(self.icons.icon("plus", "#a8aea7"))
        self.add_project_button.clicked.connect(self._add_folder)
        self.rename_project_button = QPushButton()
        self.rename_project_button.clicked.connect(self._rename_project)
        self.remove_project_button = QPushButton()
        self.remove_project_button.setObjectName("dangerButton")
        self.remove_project_button.clicked.connect(self._remove_folder)
        actions.addWidget(self.add_project_button)
        actions.addWidget(self.rename_project_button)
        actions.addWidget(self.remove_project_button)
        actions.addStretch(1)
        outer.addLayout(actions)
        self.primary_project_note = QLabel()
        self.primary_project_note.setObjectName("muted")
        outer.addWidget(self.primary_project_note)
        return page

    def _build_codex_page(self) -> QWidget:
        page, outer = self._page_shell("codex", "codex_intro")
        surface = self._surface()
        form = QFormLayout(surface)
        form.setContentsMargins(22, 22, 22, 22)
        form.setSpacing(14)
        self.model_combo = QComboBox()
        self.model_combo.currentIndexChanged.connect(self._update_effort_options)
        model_row = QWidget()
        model_layout = QHBoxLayout(model_row)
        model_layout.setContentsMargins(0, 0, 0, 0)
        model_layout.addWidget(self.model_combo, 1)
        self.refresh_models_button = QPushButton()
        self.refresh_models_button.clicked.connect(self._refresh_models)
        model_layout.addWidget(self.refresh_models_button)
        self.effort_combo = QComboBox()
        self.tier_combo = QComboBox()
        self.model_label = QLabel()
        self.effort_label_widget = QLabel()
        self.tier_label = QLabel()
        form.addRow(self.model_label, model_row)
        form.addRow(self.effort_label_widget, self.effort_combo)
        form.addRow(self.tier_label, self.tier_combo)
        self.mock_checkbox = QCheckBox()
        self.mock_checkbox.setChecked(self.config.mock_mode)
        form.addRow("", self.mock_checkbox)
        outer.addWidget(surface)
        outer.addStretch(1)
        return page

    def _build_security_page(self) -> QWidget:
        page, outer = self._page_shell("security", "security_intro")
        surface = self._surface()
        layout = QVBoxLayout(surface)
        layout.setContentsMargins(22, 22, 22, 22)
        layout.setSpacing(14)
        self.security_access_combo = QComboBox()
        self.security_access_combo.currentIndexChanged.connect(lambda: self._access_changed(self.security_access_combo))
        layout.addWidget(self.security_access_combo)
        self.security_description = QLabel()
        self.security_description.setWordWrap(True)
        self.security_description.setObjectName("pageIntro")
        layout.addWidget(self.security_description)
        outer.addWidget(surface)
        outer.addStretch(1)
        return page

    def _build_activity_page(self) -> QWidget:
        page, outer = self._page_shell("activity", "activity_private")
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(500)
        outer.addWidget(self.log, 1)
        return page

    def _build_settings_page(self) -> QWidget:
        page, outer = self._page_shell("settings")
        surface = self._surface()
        form = QFormLayout(surface)
        form.setContentsMargins(22, 22, 22, 22)
        form.setSpacing(14)
        self.name_edit = QLineEdit(self.config.name)
        self.hub_edit = QLineEdit(self.config.hub_url)
        self.hub_edit.textChanged.connect(self._update_hub_environment_hint)
        self.hub_environment_label = QLabel()
        self.hub_environment_label.setWordWrap(True)
        self.hub_environment_label.setObjectName("pageIntro")
        self.language_combo = QComboBox()
        for preference in ("auto", "ru", "en"):
            self.language_combo.addItem("", preference)
        self.language_combo.currentIndexChanged.connect(self._language_combo_changed)
        self.autostart_checkbox = QCheckBox()
        self.autostart_checkbox.setChecked(is_autostart_enabled())
        self.autostart_checkbox.toggled.connect(self._autostart_checkbox_changed)
        self.name_label = QLabel()
        self.hub_label = QLabel()
        self.language_label = QLabel()
        form.addRow(self.name_label, self.name_edit)
        form.addRow(self.hub_label, self.hub_edit)
        form.addRow("", self.hub_environment_label)
        form.addRow(self.language_label, self.language_combo)
        form.addRow("", self.autostart_checkbox)
        outer.addWidget(surface)

        actions = QHBoxLayout()
        self.save_button = QPushButton()
        self.save_button.clicked.connect(self._save_clicked)
        self.pair_button = QPushButton()
        self.pair_button.clicked.connect(self._pair)
        self.doctor_button = QPushButton()
        self.doctor_button.clicked.connect(self._doctor)
        actions.addWidget(self.save_button)
        actions.addWidget(self.pair_button)
        actions.addWidget(self.doctor_button)
        actions.addStretch(1)
        outer.addLayout(actions)
        self.pairing_panel = self._surface()
        pairing_layout = QHBoxLayout(self.pairing_panel)
        pairing_layout.setContentsMargins(18, 14, 18, 14)
        pairing_text = QVBoxLayout()
        self.pairing_code_title = QLabel()
        self.pairing_code_title.setObjectName("fieldTitle")
        self.pairing_code_label = QLabel()
        self.pairing_code_label.setObjectName("pairingCode")
        self.pairing_status_label = QLabel()
        self.pairing_status_label.setObjectName("pageIntro")
        self.pairing_status_label.setWordWrap(True)
        pairing_text.addWidget(self.pairing_code_title)
        pairing_text.addWidget(self.pairing_code_label)
        pairing_text.addWidget(self.pairing_status_label)
        pairing_layout.addLayout(pairing_text, 1)
        self.copy_pairing_code_button = QPushButton()
        self.copy_pairing_code_button.clicked.connect(self._copy_pairing_code)
        pairing_layout.addWidget(self.copy_pairing_code_button)
        self.pairing_panel.hide()
        outer.addWidget(self.pairing_panel)
        outer.addStretch(1)
        return page

    def _build_tray(self) -> None:
        self.tray = QSystemTrayIcon(self._app_icon(), self)
        self.tray.setToolTip(self._t("app_title"))
        self.tray.activated.connect(self._tray_activated)
        self.tray_menu = QMenu()
        self.tray_open_action = QAction(self)
        self.tray_open_action.setIcon(self.icons.icon("desktop", "#a8aea7"))
        self.tray_open_action.triggered.connect(self._show_window)
        self.tray_start_action = QAction(self)
        self.tray_start_action.setIcon(self.icons.icon("play", "#62f238"))
        self.tray_start_action.triggered.connect(self._start_connector)
        self.tray_stop_action = QAction(self)
        self.tray_stop_action.setIcon(self.icons.icon("stop", "#a8aea7"))
        self.tray_stop_action.triggered.connect(self._stop_process)
        self.tray_autostart_action = QAction(self)
        self.tray_autostart_action.setCheckable(True)
        self.tray_autostart_action.setChecked(is_autostart_enabled())
        self.tray_autostart_action.toggled.connect(self._tray_autostart_changed)
        self.tray_language_menu = self.tray_menu.addMenu("")
        self.tray_language_group = QActionGroup(self)
        self.tray_language_group.setExclusive(True)
        self.tray_language_actions: dict[str, QAction] = {}
        for preference in ("auto", "ru", "en"):
            action = QAction(self)
            action.setCheckable(True)
            action.setData(preference)
            action.setChecked(preference == self.config.language)
            action.triggered.connect(lambda _checked=False, value=preference: self._set_language(value))
            self.tray_language_group.addAction(action)
            self.tray_language_menu.addAction(action)
            self.tray_language_actions[preference] = action
        self.tray_exit_action = QAction(self)
        self.tray_exit_action.setIcon(self.icons.icon("sign-out", "#a8aea7"))
        self.tray_exit_action.triggered.connect(self._quit_from_tray)
        self.tray_menu.insertAction(self.tray_language_menu.menuAction(), self.tray_open_action)
        self.tray_menu.insertSeparator(self.tray_language_menu.menuAction())
        self.tray_menu.insertAction(self.tray_language_menu.menuAction(), self.tray_start_action)
        self.tray_menu.insertAction(self.tray_language_menu.menuAction(), self.tray_stop_action)
        self.tray_menu.insertAction(self.tray_language_menu.menuAction(), self.tray_autostart_action)
        self.tray_menu.addSeparator()
        self.tray_menu.addAction(self.tray_exit_action)
        self.tray.setContextMenu(self.tray_menu)
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray.show()

    def _retranslate(self) -> None:
        self.setWindowTitle(self._t("app_title"))
        self.product_label.setText(self._t("product"))
        for key, button in self._nav_buttons.items():
            if key == "settings":
                button.setText(f"  {self._t('settings')}")
            else:
                button.setText(f"  {self._t(key)}")
        for key, (title, intro) in self._page_headers.items():
            title.setText(self._t(key))
            if intro:
                intro.setText(self._t({"projects": "projects_intro", "codex": "codex_intro", "security": "security_intro", "activity": "activity_private"}[key]))
        self.privacy_label.setText(self._t("privacy"))
        self.start_button.setText(self._t("start"))
        self.stop_button.setText(self._t("stop"))
        self.current_project_title.setText(self._t("default_project"))
        self.access_title.setText(self._t("access_mode"))
        self.voice_alias_title.setText(self._t("voice_alias"))
        self.recent_title.setText(self._t("recent_activity"))
        if not self._log_started:
            self._refresh_readiness_activity()
        self.add_project_button.setText(self._t("add_project"))
        self.rename_project_button.setText(self._t("rename_alias"))
        self.remove_project_button.setText(self._t("remove"))
        self.primary_project_note.setText(self._t("primary_project"))
        self.model_label.setText(self._t("model"))
        self.effort_label_widget.setText(self._t("reasoning"))
        self.tier_label.setText(self._t("speed"))
        self.refresh_models_button.setText(self._t("refresh_models"))
        self.mock_checkbox.setText(self._t("mock"))
        self.name_label.setText(self._t("pc_name"))
        self.hub_label.setText(self._t("hub_url"))
        self._update_hub_environment_hint()
        self.language_label.setText(self._t("language"))
        self.autostart_checkbox.setText(self._t("startup"))
        self.save_button.setText(self._t("save"))
        self.pair_button.setText(self._t("pair_pc"))
        self.pairing_code_title.setText(self._t("pairing_code_title"))
        self.copy_pairing_code_button.setText(self._t("copy_code"))
        self.doctor_button.setText(self._t("check"))
        self._retranslate_language_options()
        self._refresh_access_combos()
        self._restore_model_selections()
        self._populate_projects()
        self._update_status()
        self._update_connection_statuses()
        self._retranslate_tray()

    def _retranslate_language_options(self) -> None:
        self._syncing = True
        try:
            labels = {"auto": "language_auto", "ru": "language_ru", "en": "language_en"}
            for index in range(self.language_combo.count()):
                preference = str(self.language_combo.itemData(index))
                self.language_combo.setItemText(index, self._t(labels[preference]))
                if preference == self.config.language:
                    self.language_combo.setCurrentIndex(index)
        finally:
            self._syncing = False

    def _retranslate_tray(self) -> None:
        self.tray.setToolTip(self._t("app_title"))
        self.tray_open_action.setText(self._t("open"))
        self.tray_start_action.setText(self._t("start"))
        self.tray_stop_action.setText(self._t("stop"))
        self.tray_autostart_action.setText(self._t("startup"))
        self.tray_language_menu.setTitle(self._t("language"))
        self.tray_exit_action.setText(self._t("exit"))
        for preference, key in {"auto": "language_auto", "ru": "language_ru", "en": "language_en"}.items():
            self.tray_language_actions[preference].setText(self._t(key))

    def _populate_projects(self) -> None:
        selected = self.project_list.currentRow() if hasattr(self, "project_list") else 0
        if hasattr(self, "project_list"):
            self.project_list.clear()
            if hasattr(self, "default_project_group"):
                self.default_project_group.deleteLater()
            self.default_project_group = QButtonGroup(self.project_list)
            self.default_project_group.setExclusive(True)
            default_path = self._default_project_path()
            for index, path in enumerate(self.folder_paths):
                item = QListWidgetItem()
                item.setData(Qt.ItemDataRole.UserRole, path)
                item.setSizeHint(QSize(0, 54))
                self.project_list.addItem(item)
                radio = ProjectRadioButton(f"{self.config.project_alias(path)}  ·  {path}", self.icons)
                aliases = ", ".join(self.config.project_voice_aliases(path))
                radio.setToolTip(f"{self._t('default_project_action')}\n{self._t('voice_prefix', alias=aliases)}")
                radio.setChecked(path.casefold() == default_path.casefold())
                radio.toggled.connect(
                    lambda checked, project=path, row=index: self._default_project_toggled(checked, project, row)
                )
                self.default_project_group.addButton(radio)
                self.project_list.setItemWidget(item, radio)
            if self.folder_paths:
                self.project_list.setCurrentRow(max(0, min(selected, len(self.folder_paths) - 1)))
        if hasattr(self, "project_combo"):
            self._syncing = True
            try:
                self.project_combo.clear()
                for path in self.folder_paths:
                    self.project_combo.addItem(Path(path).name, path)
                if not self.folder_paths:
                    self.project_combo.addItem("—", "")
                else:
                    default_index = self.project_combo.findData(self._default_project_path())
                    self.project_combo.setCurrentIndex(max(0, default_index))
            finally:
                self._syncing = False
            self._update_voice_alias()
        if hasattr(self, "activity_preview") and not self._log_started:
            self._refresh_readiness_activity()

    def _refresh_readiness_activity(self) -> None:
        self.activity_preview.clear()
        if not self.token_store.path.exists() and not self.folder_paths:
            self.activity_preview.addItem(self._t("no_activity"))
            return
        if self.token_store.path.exists():
            self._add_activity_item(self._t("ready_paired"), "link")
        if self.folder_paths:
            self._add_activity_item(self._t("ready_project", project=Path(self._default_project_path()).name), "folder")
        self._add_activity_item(self._t("ready_access", access=self._t(ACCESS_KEYS[self.config.access_mode])), "shield")
        self._add_activity_item(self._t("ready_local"), "desktop")

    def _add_activity_item(self, text: str, icon_name: str) -> None:
        item = QListWidgetItem(self.icons.icon(icon_name, "#62f238"), text)
        self.activity_preview.addItem(item)

    def _overview_project_changed(self, index: int) -> None:
        if self._syncing or index < 0 or index >= len(self.folder_paths):
            return
        self._set_default_project(self.folder_paths[index])

    def _update_voice_alias(self) -> None:
        alias = ", ".join(self.config.project_voice_aliases(self._default_project_path())) if self.folder_paths else "—"
        self.voice_alias_label.setText(self._t("voice_prefix", alias=alias))

    def _default_project_path(self) -> str:
        if not self.folder_paths:
            return ""
        wanted = self.config.default_root
        return next((path for path in self.folder_paths if path.casefold() == wanted.casefold()), self.folder_paths[0])

    def _default_project_toggled(self, checked: bool, path: str, row: int) -> None:
        if not checked or self._syncing:
            return
        self.project_list.setCurrentRow(row)
        self._set_default_project(path)

    def _set_default_project(self, path: str) -> None:
        if not path or path.casefold() == self._default_project_path().casefold() and self.config.default_root:
            self._update_voice_alias()
            return
        self.config.default_root = path
        self.config.allowed_roots = list(self.folder_paths)
        try:
            self.config_store.save(self.config)
        except (OSError, ValueError) as exc:
            self._show_error(str(exc))
            return
        self._populate_projects()

    def _refresh_access_combos(self) -> None:
        self._syncing = True
        try:
            for combo in (self.overview_access_combo, self.security_access_combo):
                combo.clear()
                for mode, key in ACCESS_KEYS.items():
                    combo.addItem(self._t(key), mode)
                    if mode == self.config.access_mode:
                        combo.setCurrentIndex(combo.count() - 1)
        finally:
            self._syncing = False
        self._update_security_text()

    def _access_changed(self, combo: QComboBox) -> None:
        if self._syncing or combo.currentIndex() < 0:
            return
        selected = str(combo.currentData())
        if selected == "full_project" and self.previous_access_mode != "full_project":
            answer = QMessageBox.question(
                self,
                self._t("full_access_title"),
                self._t("full_access_confirm"),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                self._refresh_access_combos()
                return
        self.config.access_mode = selected
        try:
            self.config_store.save(self.config)
        except (OSError, ValueError) as exc:
            self._show_error(str(exc))
            self.config.access_mode = self.previous_access_mode
        else:
            self.previous_access_mode = selected
        self._refresh_access_combos()

    def _update_security_text(self) -> None:
        key = {
            "read_only": "security_read_only",
            "ask": "security_ask",
            "full_project": "security_full",
        }[self.config.access_mode]
        text = self._t(key)
        self.overview_security_label.setText(text)
        self.security_description.setText(text)
        if hasattr(self, "activity_preview") and not self._log_started:
            self._refresh_readiness_activity()

    def _add_folder(self) -> None:
        selected = QFileDialog.getExistingDirectory(self, self._t("add_project"))
        if not selected:
            return
        try:
            root = Path(selected).resolve(strict=True)
            if not root.is_dir():
                raise ValueError(self._t("folder_error"))
        except (OSError, ValueError) as exc:
            self._show_error(str(exc))
            return
        if str(root).casefold() not in {item.casefold() for item in self.folder_paths}:
            self.folder_paths.append(str(root))
            if not self.config.default_root:
                self.config.default_root = str(root)
            self._save(silent=True)
            self._populate_projects()

    def _remove_folder(self) -> None:
        index = self.project_list.currentRow()
        if index < 0 or index >= len(self.folder_paths):
            return
        path = self.folder_paths.pop(index)
        self.config.project_aliases = {key: value for key, value in self.config.project_aliases.items() if key.casefold() != path.casefold()}
        if self.config.default_root.casefold() == path.casefold():
            self.config.default_root = self.folder_paths[0] if self.folder_paths else ""
        self._save(silent=True)
        self._populate_projects()

    def _rename_project(self) -> None:
        index = self.project_list.currentRow()
        if index < 0 or index >= len(self.folder_paths):
            QMessageBox.information(self, self._t("alias_title"), self._t("select_project_first"))
            return
        path = self.folder_paths[index]
        aliases_text, accepted = QInputDialog.getMultiLineText(
            self,
            self._t("alias_title"),
            self._t("alias_prompt"),
            "\n".join(self.config.project_voice_aliases(path)),
        )
        if not accepted:
            return
        aliases = [" ".join(item.strip().split()) for item in re.split(r"[,;\n]+", aliases_text) if item.strip()]
        if not aliases or len(aliases) > 12 or any(len(alias) > 80 for alias in aliases):
            self._show_error(self._t("alias_invalid"))
            return
        previous = self.config.project_aliases.get(path)
        self.config.project_aliases[path] = aliases
        try:
            self.config.allowed_roots = list(self.folder_paths)
            self.config.validate()
            self.config_store.save(self.config)
        except (OSError, ValueError) as exc:
            if previous is None:
                self.config.project_aliases.pop(path, None)
            else:
                self.config.project_aliases[path] = previous
            self._show_error(str(exc))
            return
        self._populate_projects()
        self.project_list.setCurrentRow(index)

    def _restore_model_selections(self) -> None:
        if not hasattr(self, "model_combo"):
            return
        selected_model = self.config.model
        existing = [(self.model_combo.itemText(i), self.model_combo.itemData(i)) for i in range(self.model_combo.count()) if self.model_combo.itemData(i)]
        self._syncing = True
        try:
            self.model_combo.clear()
            self.model_combo.addItem(self._t("model_default"), "")
            for label, value in existing:
                self.model_combo.addItem(label, value)
            if selected_model and self.model_combo.findData(selected_model) < 0:
                self.model_combo.addItem(selected_model, selected_model)
            self.model_combo.setCurrentIndex(max(0, self.model_combo.findData(selected_model)))
        finally:
            self._syncing = False
        self._update_effort_options()

    def _refresh_models(self) -> None:
        try:
            self._save(silent=True)
            self.config.primary_allowed_root()
        except (OSError, ValueError, RuntimeError) as exc:
            self._show_error(str(exc))
            return
        self.status_detail.setText(self._t("models_loading"))
        threading.Thread(target=self._discover_models_worker, daemon=True, name="codex-model-list").start()

    def _discover_models_worker(self) -> None:
        try:
            models = discover_models(self.config)
        except Exception as exc:
            self.models_error.emit(str(exc))
            return
        self.models_ready.emit(models)

    def _models_failed(self, error: str) -> None:
        self._update_status()
        message = self._t("models_failed", error=error)
        self._append_log(message)
        self._show_error(message)

    def _models_loaded(self, models: object) -> None:
        self.models = list(models) if isinstance(models, list) else []
        self._syncing = True
        try:
            self.model_combo.clear()
            self.model_combo.addItem(self._t("model_default"), "")
            for model in self.models:
                model_id = str(model.get("model") or model.get("id") or "").strip()
                if not model_id:
                    continue
                display = str(model.get("displayName") or model_id)
                self.model_combo.addItem(f"{display} · {model_id}", model_id)
            index = self.model_combo.findData(self.config.model)
            self.model_combo.setCurrentIndex(max(0, index))
        finally:
            self._syncing = False
        self._update_effort_options()
        self._update_status()
        self._append_log(self._t("models_loaded", count=max(0, self.model_combo.count() - 1)))

    def _selected_model(self) -> dict[str, Any] | None:
        selected_id = str(self.model_combo.currentData() or "")
        if not selected_id:
            return next((item for item in self.models if item.get("isDefault")), None)
        return next((item for item in self.models if (item.get("model") or item.get("id")) == selected_id), None)

    def _update_effort_options(self) -> None:
        if self._syncing or not hasattr(self, "effort_combo"):
            return
        model = self._selected_model()
        options = model.get("supportedReasoningEfforts", []) if isinstance(model, dict) else []
        self._syncing = True
        try:
            self.effort_combo.clear()
            self.effort_combo.addItem(self._t("reasoning_default"), "")
            for option in options if isinstance(options, list) else []:
                value = str(option.get("reasoningEffort", "")).strip() if isinstance(option, dict) else ""
                if value:
                    self.effort_combo.addItem(effort_label(value, language=self.translator.language), value)
            if self.config.reasoning_effort and self.effort_combo.findData(self.config.reasoning_effort) < 0:
                self.effort_combo.addItem(effort_label(self.config.reasoning_effort, language=self.translator.language), self.config.reasoning_effort)
            self.effort_combo.setCurrentIndex(max(0, self.effort_combo.findData(self.config.reasoning_effort)))
            self._update_tier_options(model)
        finally:
            self._syncing = False

    def _update_tier_options(self, model: dict[str, Any] | None) -> None:
        options = model.get("serviceTiers", []) if isinstance(model, dict) else []
        self.tier_combo.clear()
        self.tier_combo.addItem(self._t("speed_default"), "")
        for option in options if isinstance(options, list) else []:
            value = str(option.get("id", "")).strip() if isinstance(option, dict) else ""
            if value:
                name = str(option.get("name") or value)
                self.tier_combo.addItem(f"{name} · {value}" if name != value else value, value)
        if self.config.service_tier and self.tier_combo.findData(self.config.service_tier) < 0:
            self.tier_combo.addItem(self.config.service_tier, self.config.service_tier)
        self.tier_combo.setCurrentIndex(max(0, self.tier_combo.findData(self.config.service_tier)))

    def _save_clicked(self) -> None:
        try:
            self._save()
        except (OSError, ValueError, RuntimeError) as exc:
            self._show_error(str(exc))
            return
        self._append_log(self._t("saved"))

    def _save(self, *, silent: bool = False) -> None:
        self.config.name = self.name_edit.text().strip()
        self.config.hub_url = self.hub_edit.text().strip().rstrip("/")
        self.config.allowed_roots = list(self.folder_paths)
        if self.folder_paths and not any(path.casefold() == self.config.default_root.casefold() for path in self.folder_paths):
            self.config.default_root = self.folder_paths[0]
        if not self.folder_paths:
            self.config.default_root = ""
        allowed = {item.casefold() for item in self.folder_paths}
        self.config.project_aliases = {path: alias for path, alias in self.config.project_aliases.items() if path.casefold() in allowed}
        self.config.model = str(self.model_combo.currentData() or "").strip()
        self.config.reasoning_effort = str(self.effort_combo.currentData() or "").strip()
        self.config.service_tier = str(self.tier_combo.currentData() or "").strip()
        self.config.mock_mode = self.mock_checkbox.isChecked()
        self.config_store.save(self.config)
        self.previous_access_mode = self.config.access_mode
        if not silent:
            self._update_status()

    def _update_hub_environment_hint(self) -> None:
        if not hasattr(self, "hub_environment_label"):
            return
        value = self.hub_edit.text().strip()
        paired_hub = normalize_hub_url(self.config.paired_hub_url)
        current_hub = normalize_hub_url(value)
        if is_local_hub_url(value):
            key = "hub_local_warning"
        elif paired_hub and current_hub.casefold() != paired_hub.casefold() and self.token_store.path.exists():
            key = "hub_changed_warning"
        else:
            key = "hub_production_hint"
        self.hub_environment_label.setText(self._t(key))

    def _pair(self) -> None:
        self.pairing_code_label.setText("…")
        self.pairing_status_label.setText(self._t("pairing_starting"))
        self.copy_pairing_code_button.setEnabled(False)
        self.pairing_panel.show()
        self._launch_cli("purpose_pair", ["pair"])

    def _doctor(self) -> None:
        self._launch_cli("purpose_check", ["doctor"])

    def _start_connector(self) -> None:
        args = ["run"]
        if self.mock_checkbox.isChecked():
            args.append("--mock")
        self._launch_cli("purpose_connector", args)

    def _launch_cli(self, purpose: str, arguments: list[str]) -> None:
        if self.process.state() != QProcess.ProcessState.NotRunning:
            if self.process_purpose == "purpose_connector" and purpose == "purpose_pair":
                self.pending_cli = (purpose, list(arguments))
                self._append_log(self._t("pairing_restarting"))
                self.process.terminate()
                QTimer.singleShot(2500, lambda: self._kill_stuck_process("purpose_connector"))
                self._update_status()
                return
            QMessageBox.information(self, self._t("information"), self._t("operation_busy"))
            return
        try:
            self._save(silent=True)
            if arguments[0] in {"doctor", "run"}:
                self.config.primary_allowed_root()
        except (OSError, ValueError, RuntimeError) as exc:
            self._show_error(str(exc))
            self._show_window()
            return
        command = self._child_command(arguments)
        self.process_purpose = purpose
        self.process_output = Utf8LogDecoder()
        self._append_log(f"> {' '.join(command)}")
        self.process.start(command[0], command[1:])
        if not self.process.waitForStarted(3000):
            self._show_error(self.process.errorString())
            self.process_purpose = ""
        self._update_status()

    def _child_command(self, arguments: list[str]) -> list[str]:
        executable = Path(sys.executable)
        if getattr(sys, "frozen", False):
            return [
                str(executable),
                "--config-dir",
                str(self.config_store.directory),
                *arguments,
            ]
        if executable.name.casefold() == "pythonw.exe":
            python = executable.with_name("python.exe")
            if python.is_file():
                executable = python
        return [
            str(executable),
            "-u",
            "-m",
            "rokidhub_desktop_connector",
            "--config-dir",
            str(self.config_store.directory),
            *arguments,
        ]

    def _read_process_output(self) -> None:
        self._drain_process_output()

    def _drain_process_output(self, *, final: bool = False) -> None:
        payload = bytes(self.process.readAllStandardOutput())
        for line in self.process_output.feed(payload, final=final):
            line = line.rstrip()
            self._capture_pairing_code(line)
            self._append_log(line)

    def _capture_pairing_code(self, line: str) -> None:
        code = pairing_code_from_line(line)
        if not code:
            return
        self.pairing_code_label.setText(code)
        self.pairing_status_label.setText(self._t("pairing_enter_code"))
        self.copy_pairing_code_button.setEnabled(True)
        self.pairing_panel.show()

    def _copy_pairing_code(self) -> None:
        code = self.pairing_code_label.text().strip()
        if not code:
            return
        QApplication.clipboard().setText(code)
        self._append_log(self._t("pairing_code_copied"))

    def _process_finished(self, code: int, _status: QProcess.ExitStatus) -> None:
        self._drain_process_output(final=True)
        purpose = self.process_purpose
        self.process_purpose = ""
        if purpose:
            self._append_log(self._t("finished", purpose=self._t(purpose), code=code))
        if purpose == "purpose_pair" and code != 0:
            self.pairing_code_label.setText("—")
            self.pairing_status_label.setText(self._t("pairing_failed"))
            self.copy_pairing_code_button.setEnabled(False)
            self.pairing_panel.show()
        self._update_status()
        if code == 0 and purpose in {"purpose_pair", "purpose_check"}:
            self._refresh_hub_status()
        pending = self.pending_cli
        self.pending_cli = None
        if pending is not None:
            QTimer.singleShot(0, lambda request=pending: self._launch_cli(*request))

    def _stop_process(self) -> None:
        if self.process.state() == QProcess.ProcessState.NotRunning:
            return
        self.pending_cli = None
        self.process.terminate()
        self._append_log(self._t("stop_requested"))
        QTimer.singleShot(2500, self._kill_stuck_process)

    def _kill_stuck_process(self, expected_purpose: str | None = None) -> None:
        if expected_purpose is not None and self.process_purpose != expected_purpose:
            return
        if self.process.state() != QProcess.ProcessState.NotRunning:
            self.process.kill()

    def _append_log(self, value: str) -> None:
        if not value:
            return
        if not self._log_started:
            self.activity_preview.clear()
            self._log_started = True
        self.log.appendPlainText(value)
        self.activity_preview.addItem(value)
        self.activity_preview.scrollToBottom()

    def _update_status(self) -> None:
        running = self.process.state() != QProcess.ProcessState.NotRunning and self.process_purpose == "purpose_connector"
        busy = self.process.state() != QProcess.ProcessState.NotRunning
        paired = self.token_store.path.exists()
        local_hub = is_local_hub_url(self.config.hub_url)
        paired_hub = normalize_hub_url(self.config.paired_hub_url)
        token_for_current_hub = paired and (not paired_hub or paired_hub.casefold() == normalize_hub_url(self.config.hub_url).casefold())
        appearance = hero_status_appearance(
            running=running,
            paired=paired,
            local_hub=local_hub,
            token_for_current_hub=token_for_current_hub,
        )
        self.status_title.setText(self._t(appearance.title_key))
        self.status_detail.setText(self._t(appearance.detail_key))
        self.status_detail.setStyleSheet(f"color: {appearance.detail_color};")
        self.status_icon.setPixmap(self.icons.pixmap(appearance.icon_name, appearance.icon_color, canvas=88))
        self.start_button.setEnabled(not busy)
        self.pair_button.setEnabled(not busy)
        self.stop_button.setEnabled(busy)
        self.start_button.setVisible(not busy)
        self.stop_button.setVisible(busy)
        if hasattr(self, "tray_start_action"):
            self.tray_start_action.setEnabled(not busy)
            self.tray_stop_action.setEnabled(busy)

    def _show_settings(self) -> None:
        self._nav_buttons["settings"].click()

    def _open_hub_dashboard(self) -> None:
        QDesktopServices.openUrl(QUrl(f"{self.config.hub_url.rstrip('/')}/dashboard/"))

    def _refresh_hub_status(self) -> None:
        if self.hub_status_loading:
            return
        if not self.token_store.path.exists():
            self.hub_status = None
            self.hub_status_error_message = ""
            self._update_connection_statuses()
            return
        self.hub_status_loading = True
        self.hub_status_error_message = ""
        self._update_connection_statuses()
        hub_url = self.config.hub_url
        connector_id = self.config.connector_id
        project_name = Path(self._default_project_path()).name if self._default_project_path() else ""
        threading.Thread(
            target=self._hub_status_worker,
            args=(hub_url, connector_id, project_name),
            daemon=True,
            name="rokidhub-status",
        ).start()

    def _hub_status_worker(self, hub_url: str, connector_id: str, project_name: str) -> None:
        try:
            token = self.token_store.load()
            status = HubApi(hub_url, connector_id, token, timeout_seconds=8).status(__version__, project_name)
        except Exception as exc:
            self.hub_status_error.emit(str(exc))
            return
        self.hub_status_ready.emit(status)

    def _hub_status_loaded(self, status: object) -> None:
        self.hub_status_loading = False
        self.hub_status_error_message = ""
        self.hub_status = dict(status) if isinstance(status, dict) else {}
        self._update_connection_statuses()

    def _hub_status_failed(self, error: str) -> None:
        self.hub_status_loading = False
        self.hub_status = None
        self.hub_status_error_message = error
        self._update_connection_statuses()

    def _update_connection_statuses(self) -> None:
        if not hasattr(self, "pc_connection_button"):
            return
        local_token = self.token_store.path.exists()
        local_hub = is_local_hub_url(self.config.hub_url)
        paired_hub = normalize_hub_url(self.config.paired_hub_url)
        token_for_current_hub = local_token and (
            not paired_hub or paired_hub.casefold() == normalize_hub_url(self.config.hub_url).casefold()
        )
        if local_hub and local_token:
            pc = ("pc_status_local", "pc_local_tooltip", "warning")
        elif not token_for_current_hub:
            pc = ("pc_status_unpaired", "pc_unpaired_tooltip", "warning")
        elif self.hub_status_loading or (self.hub_status is None and not self.hub_status_error_message):
            pc = ("pc_status_checking", "pc_paired_tooltip", "muted")
        elif self.hub_status_error_message:
            pc = ("pc_status_unavailable", "pc_unavailable_tooltip", "warning")
        else:
            pc = ("pc_status_paired", "pc_paired_tooltip", "good")
        self._set_connection_card(self.pc_connection_button, *pc, icon_name="desktop")

        if local_hub and local_token:
            glasses = ("glasses_status_local", "glasses_local_tooltip", "muted")
        elif not token_for_current_hub:
            glasses = ("glasses_status_requires_pc", "glasses_requires_pc_tooltip", "muted")
        elif self.hub_status_loading or (self.hub_status is None and not self.hub_status_error_message):
            glasses = ("glasses_status_checking", "glasses_unavailable_tooltip", "muted")
        elif self.hub_status_error_message:
            glasses = ("glasses_status_unavailable", "glasses_unavailable_tooltip", "warning")
        elif bool(self.hub_status.get("codex_nexus_paired")):
            glasses = ("glasses_status_paired", "glasses_paired_tooltip", "good")
        else:
            glasses = ("glasses_status_unpaired", "glasses_unpaired_tooltip", "warning")
        self._set_connection_card(self.glasses_connection_button, *glasses, icon_name="eye")

    def _set_connection_card(
        self,
        button: QPushButton,
        text_key: str,
        tooltip_key: str,
        state: str,
        *,
        icon_name: str,
    ) -> None:
        colors = {"good": "#62f238", "warning": "#e8b63e", "muted": "#899089"}
        button.setText(self._t(text_key))
        button.setToolTip(self._t(tooltip_key))
        button.setIcon(self.icons.icon(icon_name, colors[state]))
        button.setProperty("state", state)
        button.style().unpolish(button)
        button.style().polish(button)

    def _language_combo_changed(self) -> None:
        if self._syncing:
            return
        preference = str(self.language_combo.currentData())
        self._set_language(preference)

    def _set_language(self, preference: str) -> None:
        self.config.language = preference
        self.translator.set_preference(preference)
        try:
            self.config_store.save(self.config)
        except (OSError, ValueError) as exc:
            self._show_error(str(exc))
            return
        if hasattr(self, "tray_language_actions"):
            self.tray_language_actions[preference].setChecked(True)
        self._retranslate()

    def _autostart_checkbox_changed(self, enabled: bool) -> None:
        if self._syncing:
            return
        self._set_autostart(enabled, source="settings")

    def _tray_autostart_changed(self, enabled: bool) -> None:
        if self._syncing:
            return
        self._set_autostart(enabled, source="tray")

    def _set_autostart(self, enabled: bool, *, source: str) -> None:
        try:
            if enabled:
                self._save(silent=True)
                self.config.primary_allowed_root()
                if not self.token_store.path.exists():
                    raise RuntimeError(self._t("pair_required"))
            set_autostart(enabled, self.config_store.directory)
        except (OSError, RuntimeError, ValueError) as exc:
            self._syncing = True
            self.autostart_checkbox.setChecked(not enabled)
            self.tray_autostart_action.setChecked(not enabled)
            self._syncing = False
            self._show_window()
            self._show_error(str(exc))
            return
        self._syncing = True
        self.autostart_checkbox.setChecked(enabled)
        self.tray_autostart_action.setChecked(enabled)
        self._syncing = False
        self._append_log(self._t("autostart_on" if enabled else "autostart_off"))

    def _tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in {QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick}:
            self._show_window()

    def _show_window(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _quit_from_tray(self) -> None:
        self._quitting = True
        if self.process.state() != QProcess.ProcessState.NotRunning:
            self.process.terminate()
            if not self.process.waitForFinished(1800):
                self.process.kill()
                self.process.waitForFinished(800)
        self.tray.hide()
        QApplication.instance().quit()

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._quitting or not QSystemTrayIcon.isSystemTrayAvailable():
            event.accept()
            return
        event.ignore()
        self.hide()
        if not self._tray_notice_shown:
            self.tray.showMessage(self._t("app_title"), self._t("tray_running"), self._app_icon(), 4500)
            self._tray_notice_shown = True

    def _show_error(self, message: str) -> None:
        QMessageBox.critical(self, self._t("error"), message)

    def _field_title(self) -> QLabel:
        label = QLabel()
        label.setObjectName("fieldTitle")
        return label

    @staticmethod
    def _divider() -> QFrame:
        divider = QFrame()
        divider.setObjectName("divider")
        return divider

    @staticmethod
    def _surface() -> QFrame:
        surface = QFrame()
        surface.setObjectName("surface")
        return surface

    @staticmethod
    def _asset_path(filename: str) -> Path | None:
        package_asset = Path(__file__).resolve().parent / "assets" / filename
        repository_asset = Path(__file__).resolve().parents[3] / "rokidhub" / "hub" / "static" / "hub" / "images" / filename
        for candidate in (package_asset, repository_asset):
            if candidate.is_file():
                return candidate
        return None

    def _app_icon(self) -> QIcon:
        favicon = self._asset_path("favicon.png")
        if favicon:
            return QIcon(str(favicon))
        return self.icons.icon("desktop", "#62f238")


def main(
    config_directory: Path | None = None,
    *,
    minimized: bool = False,
    auto_start: bool = False,
) -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("RokidHub Desktop Connector")
    app.setOrganizationName("RokidHub")
    app.setQuitOnLastWindowClosed(False)
    app.setStyle("Fusion")
    window = ConnectorWindow(
        ConfigStore(config_directory),
        DpapiTokenStore(config_directory),
        minimized=minimized,
        auto_start=auto_start,
    )
    app.aboutToQuit.connect(lambda: window.tray.hide())
    return app.exec()


def script_main() -> int:
    return main()
