# -*- coding: utf-8 -*-
"""Slate/indigo dark and light themes with shared semantic design tokens."""
from string import Template

_DARK = {
    'background': '#0b1220', 'workspace': '#10192b', 'sidebar': '#0c1424',
    'surface': '#172238', 'surface_alt': '#1d2b43', 'input': '#111c30',
    'button': '#253450', 'hover': '#30415f', 'selected': '#343b65',
    'selected_hover': '#404974', 'text': '#edf2fc', 'muted': '#a5b3cc',
    'faint': '#8798b5', 'accent': '#7666e8', 'accent_hover': '#6655dc',
    'accent_ink': '#ffffff', 'border': '#2a3a55', 'border_hover': '#506284',
    'grid': '#21314b', 'alternate': '#152137', 'selection': '#343b65',
    'selection_text': '#ffffff', 'success': '#b6aafa', 'warning': '#f5b455',
    'danger': '#ef4444', 'danger_surface': '#331a20',
    'danger_hover': '#451f28', 'accent_surface': '#2d2e54',
    'accent_surface_hover': '#3b3c69', 'disabled': '#8492ab',
    'disabled_bg': '#1a263c', 'tooltip': '#1d2b43',
    'progress_bg': '#111c30', 'favorite': '#b6aafa',
}

_LIGHT = {
    'background': '#f3f5fa', 'workspace': '#f3f5fa', 'sidebar': '#ffffff',
    'surface': '#ffffff', 'surface_alt': '#eef1f8', 'input': '#f9faff',
    'button': '#eef1f8', 'hover': '#e4e8f3', 'selected': '#eae5fc',
    'selected_hover': '#e0d9fa', 'text': '#202c44', 'muted': '#586884',
    'faint': '#677994', 'accent': '#6554d9', 'accent_hover': '#5443c4',
    'accent_ink': '#ffffff', 'border': '#dce2ef', 'border_hover': '#a9b6ce',
    'grid': '#e9edf5', 'alternate': '#f6f8fc', 'selection': '#eae5fc',
    'selection_text': '#302657', 'success': '#6554d9', 'warning': '#ad6509',
    'danger': '#dc2626', 'danger_surface': '#fef2f2',
    'danger_hover': '#fee2e2', 'accent_surface': '#eeeafd',
    'accent_surface_hover': '#e0d9fa', 'disabled': '#7d8ba3',
    'disabled_bg': '#eef1f7', 'tooltip': '#ffffff',
    'progress_bg': '#e4e9f4', 'favorite': '#6554d9',
}

_QSS = Template("""
* {
    font-family: 'Segoe UI Variable Display', 'Segoe UI', -apple-system, BlinkMacSystemFont, sans-serif;
    font-size: 10pt;
}
QMainWindow, QDialog { background-color: $background; }
QWidget { color: $text; background-color: $workspace; }
QLabel, QCheckBox, QRadioButton { background: transparent; }
QScrollArea, QScrollArea > QWidget > QWidget { background: $workspace; border: none; }
QWidget#workspace { background-color: $workspace; }
QWidget#sidebarHeader, QWidget#pageHeader, QWidget#connectionControls,
QWidget#deviceOptionsPanel, QWidget#statusActivity { background: transparent; }
QWidget#sidebar {
    background-color: $sidebar;
    border-right: 1px solid $border;
}
QWidget#connectionCard, QWidget#logCard {
    background-color: $surface;
    border: 1px solid $border;
    border-radius: 12px;
}
QFrame#contentCard, QFrame#metricCard, QFrame#maintenanceCard {
    background-color: $surface;
    border: 1px solid $border;
    border-radius: 12px;
}

QLabel[role="quiet"], QLabel[role="secondary"] { color: $muted; }
QLabel#brandTitle { color: $text; font-size: 18pt; font-weight: 700; letter-spacing: -0.5px; }
QLabel#brandSubtitle { color: $faint; font-size: 9pt; }
QLabel#sidebarFooter { color: $faint; font-size: 8pt; padding: 4px 2px; }
QPushButton#sidebarLogToggle { background: $surface; border-color: $border; }
QPushButton#sidebarLogToggle:checked { background: $accent_surface; border-color: $accent; }
QPushButton#quickActionsButton {
    color: $muted; background: $surface; border: 1px solid $border;
    border-radius: 8px; padding: 5px 12px;
}
QPushButton#quickActionsButton:hover { color: $text; border-color: $accent; }
QLabel#pageTitle { color: $text; font-size: 20pt; font-weight: 700; letter-spacing: -0.5px; }
QLabel#pageSubtitle { color: $muted; font-size: 10pt; }
QLabel#cardTitle { color: $text; font-size: 12pt; font-weight: 600; }
QLabel#metricValue { color: $text; font-size: 22pt; font-weight: 700; }
QLabel#metricLabel { color: $muted; font-size: 9pt; font-weight: 500; }
QLabel#emptyState { color: $muted; background: transparent; font-size: 11pt; }

/* Rozetler / Badge */
QLabel[role="badge"] {
    background-color: $surface_alt;
    color: $muted;
    border: 1px solid $border;
    border-radius: 6px;
    padding: 2px 8px;
    font-size: 8.5pt;
    font-weight: 600;
}
QLabel[role="badge-success"] {
    background-color: $surface_alt;
    color: $success;
    border: 1px solid $success;
    border-radius: 6px;
    padding: 2px 8px;
    font-size: 8.5pt;
    font-weight: 600;
}
QLabel[role="badge-accent"] {
    background-color: $accent_surface;
    color: $accent;
    border: 1px solid $accent;
    border-radius: 6px;
    padding: 2px 8px;
    font-size: 8.5pt;
    font-weight: 600;
}

QWidget#remotePad {
    background: $surface_alt;
    border: 1.5px solid $border;
    border-radius: 24px;
}
QWidget#errorBanner {
    background: $danger_surface;
    border: 1px solid $danger;
    border-radius: 10px;
}
QPushButton#remoteKey {
    min-width: 40px; min-height: 40px;
    border-radius: 20px;
}
QPushButton#btnMute {
    min-width: 28px; min-height: 24px;
    padding: 0px; margin: 0px;
    border-radius: 6px;
}
QPushButton[compact="true"], QToolButton[compact="true"] {
    padding: 2px 8px;
    min-height: 18px;
}
QPushButton[role="primary"] {
    color: $accent_ink;
    background: $accent;
    border: 1px solid $accent;
    font-weight: 600;
}
QPushButton[role="primary"]:hover { background: $accent_hover; border-color: $accent_hover; }
QPushButton[role="quiet"] {
    color: $muted;
    background: transparent;
    border-color: transparent;
}
QPushButton[role="quiet"]:hover { color: $text; background: $hover; }
QPushButton[role="primary"]:disabled, QPushButton[role="quiet"]:disabled {
    color: $disabled;
    background: $disabled_bg;
    border-color: $border;
}

QTabWidget::pane {
    background: $workspace;
    border: none;
}
QTabBar::tab {
    color: $muted;
    background: transparent;
    border: 1px solid transparent;
    padding: 7px 16px;
    margin: 2px 4px 8px 0;
    border-radius: 8px;
    font-weight: 500;
}
QTabBar::tab:selected {
    color: $text;
    background: $accent_surface;
    border-color: $border_hover;
    font-weight: 600;
}
QTabBar::tab:hover { color: $text; background: $hover; }

QPushButton, QToolButton {
    color: $text;
    background: $button;
    border: 1px solid $border;
    border-radius: 8px;
    padding: 6px 12px;
    min-height: 20px;
    font-weight: 500;
}
QPushButton:hover, QToolButton:hover {
    background: $hover;
    border-color: $border_hover;
}
QPushButton:pressed, QToolButton:pressed { background: $selected; }
QPushButton:checked, QToolButton:checked {
    color: $text;
    background: $accent_surface;
    border-color: $accent;
}
QPushButton:focus, QToolButton:focus {
    border: 1px solid $accent;
}
QPushButton[flat="true"] { border: none; background: transparent; }
QPushButton[accent="true"] {
    color: $accent_ink;
    background: $accent;
    border: 1px solid $accent;
    font-weight: 600;
}
QPushButton[accent="true"]:hover {
    background: $accent_hover;
    border-color: $accent_hover;
}
QPushButton[danger="true"] {
    color: $danger;
    background: $danger_surface;
    border: 1px solid $danger;
}
QPushButton[danger="true"]:hover { background: $danger_hover; }
QPushButton:disabled, QToolButton:disabled {
    color: $disabled;
    background: $disabled_bg;
    border-color: $border;
}
QPushButton[accent="true"]:disabled, QPushButton[danger="true"]:disabled {
    color: $disabled;
    background: $disabled_bg;
    border-color: $border;
}

QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QDateEdit, QTimeEdit,
QDateTimeEdit, QPlainTextEdit, QTextEdit {
    color: $text;
    background: $input;
    border: 1px solid $border;
    border-radius: 8px;
    padding: 7px 10px;
    selection-background-color: $selection;
    selection-color: $selection_text;
}
/* Tek satirli alanlar 28px kontrol yuksekliginde de metni kirpmamali. */
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QDateEdit, QTimeEdit, QDateTimeEdit {
    padding: 2px 10px;
    min-height: 20px;
}
QComboBox QLineEdit {
    background: transparent;
    border: none;
    border-radius: 0;
    padding: 0;
    min-height: 0;
}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus,
QDateEdit:focus, QTimeEdit:focus, QDateTimeEdit:focus,
QPlainTextEdit:focus, QTextEdit:focus {
    border: 1px solid $accent;
}
QComboBox QLineEdit:focus { border: none; }
QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled,
QDoubleSpinBox:disabled, QDateEdit:disabled, QTimeEdit:disabled,
QDateTimeEdit:disabled, QPlainTextEdit:disabled, QTextEdit:disabled {
    color: $disabled;
    background: $disabled_bg;
}
QComboBox::drop-down { width: 26px; border: none; }
QSlider::groove:horizontal {
    height: 4px;
    background: $border_hover;
    border-radius: 2px;
}
QSlider::sub-page:horizontal { background: $accent; border-radius: 2px; }
QSlider::handle:horizontal {
    width: 12px;
    margin: -5px 0;
    background: $text;
    border: 2px solid $accent;
    border-radius: 7px;
}
QSlider::handle:horizontal:disabled { background: $disabled; border-color: $border; }
QSlider::sub-page:horizontal:disabled { background: $border; }
QComboBox QAbstractItemView {
    color: $text;
    background: $surface;
    border: 1px solid $border;
    border-radius: 8px;
    padding: 4px;
    selection-background-color: $selection;
    selection-color: $selection_text;
}

QTableWidget, QTableView, QListWidget, QTreeWidget {
    color: $text;
    background: $input;
    alternate-background-color: $alternate;
    border: 1px solid $border;
    border-radius: 10px;
    gridline-color: $grid;
    selection-background-color: $selection;
    selection-color: $selection_text;
    outline: 0;
}
QTableView::item, QTableWidget::item { padding: 5px 8px; }
QTableView::item:selected, QTableWidget::item:selected,
QListWidget::item:selected, QTreeWidget::item:selected {
    background: $selection;
    color: $selection_text;
    border: none;
    border-radius: 0;
}
QAbstractItemView::item:disabled { color: $disabled; }
QHeaderView::section {
    color: $muted;
    background: $surface_alt;
    border: none;
    border-bottom: 1px solid $border;
    padding: 8px 12px;
    font-weight: 600;
    font-size: 9pt;
}
QTableCornerButton::section { background: $surface_alt; border: none; }

QListWidget#navigation {
    color: $muted;
    background: transparent;
    border: none;
    padding: 4px 0;
}
QListWidget#navigation::item {
    color: $muted;
    background: transparent;
    border: 1px solid transparent;
    border-left: 3px solid transparent;
    border-radius: 8px;
    padding: 9px 10px;
    margin: 2px 0;
    font-weight: 500;
}
QListWidget#navigation::item:hover {
    color: $text;
    background: $hover;
}
QListWidget#navigation::item:selected {
    color: $text;
    background: $selected;
    border-left-color: $accent;
    font-weight: 600;
}
QListWidget#navigation::item:selected:hover { background: $selected_hover; }

QScrollBar:vertical {
    background: transparent;
    width: 8px;
    margin: 2px;
    border-radius: 4px;
}
QScrollBar:horizontal {
    background: transparent;
    height: 8px;
    margin: 2px;
    border-radius: 4px;
}
QScrollBar::handle:vertical, QScrollBar::handle:horizontal {
    background: $border_hover;
    border-radius: 4px;
    min-height: 28px;
    min-width: 28px;
}
QScrollBar::handle:vertical:hover, QScrollBar::handle:horizontal:hover {
    background: $accent;
}
QScrollBar::add-line, QScrollBar::sub-line {
    background: transparent;
    border: none;
    width: 0;
    height: 0;
}

QStatusBar {
    color: $muted;
    background: $sidebar;
    border-top: 1px solid $border;
    font-size: 9pt;
}
QMenuBar { color: $text; background: $sidebar; }
QMenuBar::item:selected, QMenu::item:selected { color: $text; background: $selected; }
QMenu {
    color: $text;
    background: $surface;
    border: 1px solid $border;
    border-radius: 8px;
    padding: 6px;
}
QMenu::item {
    padding: 6px 24px 6px 12px;
    border-radius: 6px;
}
QMenu::item:disabled { color: $disabled; }
QGroupBox {
    background: $surface;
    border: 1px solid $border;
    border-radius: 12px;
    margin-top: 6px;
    padding: 26px 14px 14px;
    font-weight: 600;
}
QGroupBox#settingsCard {
    margin-top: 0;
    padding: 12px 14px;
}
QGroupBox#compactCard {
    margin-top: 0;
    padding: 28px 14px 12px;
}
QGroupBox::title {
    subcontrol-origin: padding;
    subcontrol-position: top left;
    left: 14px;
    top: 8px;
    padding: 0;
    color: $text;
}
QCheckBox, QRadioButton { spacing: 8px; }
QCheckBox::indicator, QRadioButton::indicator {
    width: 17px; height: 17px;
    background: $input;
    border: 1px solid $border_hover;
}
QCheckBox::indicator { border-radius: 4px; }
QRadioButton::indicator { border-radius: 9px; }
QCheckBox::indicator:checked, QRadioButton::indicator:checked {
    background: $accent;
    border: 2px solid $accent;
}
QCheckBox::indicator:focus, QRadioButton::indicator:focus { border-color: $accent; }
QCheckBox:disabled, QRadioButton:disabled { color: $disabled; }
QToolTip {
    color: $text;
    background: $tooltip;
    border: 1px solid $border_hover;
    border-radius: 6px;
    padding: 6px 10px;
}
""")

_EXTRA_QSS = Template("""
QSplitter::handle:vertical { background: $border; height: 5px; }
QSplitter::handle:horizontal { background: $border; width: 5px; }
QSplitter::handle:hover { background: $accent; }
QProgressBar {
    color: $muted;
    background: $progress_bg;
    border: 1px solid $border;
    border-radius: 6px;
    text-align: center;
    max-height: 16px;
    font-size: 8.5pt;
}
QProgressBar::chunk {
    background: $accent;
    border-radius: 5px;
}
QPlainTextEdit#terminalView, QPlainTextEdit#logView {
    font-family: 'Cascadia Code', 'Fira Code', 'Consolas', 'Courier New', monospace;
    font-size: 10pt;
    line-height: 1.45;
    background-color: $input;
    border: 1px solid $border;
    border-radius: 8px;
    padding: 10px;
}
""")


def _build_qss(tokens, template):
    return template.substitute(tokens)


# Public stylesheet constants
DARK_QSS = _build_qss(_DARK, _QSS)
LIGHT_QSS = _build_qss(_LIGHT, _QSS)
DARK_EXTRA_QSS = _build_qss(_DARK, _EXTRA_QSS)
LIGHT_EXTRA_QSS = _build_qss(_LIGHT, _EXTRA_QSS)

# Public semantic palettes retain their established keys.
_COLOR_KEYS = ('text', 'muted', 'faint', 'accent', 'success', 'warning', 'danger', 'border')
DARK_COLORS = {key: _DARK[key] for key in _COLOR_KEYS}
LIGHT_COLORS = {key: _LIGHT[key] for key in _COLOR_KEYS}
LEVEL_COLORS = {
    'INFO': _DARK['success'], 'WARN': _DARK['warning'], 'ERROR': _DARK['danger'],
    'ADB': _DARK['accent'], 'VERBOSE': _DARK['faint'],
}
LIGHT_LEVEL_COLORS = {
    'INFO': _LIGHT['success'], 'WARN': _LIGHT['warning'], 'ERROR': _LIGHT['danger'],
    'ADB': _LIGHT['accent'], 'VERBOSE': _LIGHT['faint'],
}


def colors_for(dark=True):
    return DARK_COLORS if dark else LIGHT_COLORS


def muted_style(dark=True):
    return 'color: {};'.format(colors_for(dark)['muted'])


def faint_style(dark=True):
    return 'color: {};'.format(colors_for(dark)['faint'])


def title_style(dark=True):
    return 'color: {}; font-weight: bold;'.format(colors_for(dark)['accent'])


def conn_style(dark=True, online=True):
    key = 'success' if online else 'muted'
    return 'color: {}; font-weight: bold;'.format(colors_for(dark)[key])


def logcat_colors_for(dark=True):
    c = colors_for(dark)
    return {'V': c['faint'], 'D': c['accent'], 'I': c['success'],
            'W': c['warning'], 'E': c['danger'], 'F': c['danger']}


def cat_colors_for(dark=True):
    tokens = _DARK if dark else _LIGHT
    return {'guvenli': tokens['success'], 'opsiyonel': tokens['accent'],
            'riskli': tokens['warning'], 'dokunma': tokens['danger'],
            'favoriler': tokens['favorite']}


def removal_colors_for(dark=True):
    tokens = _DARK if dark else _LIGHT
    return {'Recommended': tokens['success'], 'Advanced': tokens['accent'],
            'Expert': tokens['warning'], 'Unsafe': tokens['danger']}


def qss_for(dark=True):
    if dark:
        return DARK_QSS + DARK_EXTRA_QSS
    return LIGHT_QSS + LIGHT_EXTRA_QSS


def level_colors_for(dark=True):
    return LEVEL_COLORS if dark else LIGHT_LEVEL_COLORS
