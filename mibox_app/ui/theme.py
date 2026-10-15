# -*- coding: utf-8 -*-
"""Modern charcoal/indigo ve light UI temaları ve semantik tasarım token'ları."""
from string import Template


_DARK = {
    'background': '#0c0e14', 'workspace': '#11141c', 'sidebar': '#0e1017',
    'surface': '#171a24', 'surface_alt': '#1e2230', 'input': '#11141c',
    'button': '#232838', 'hover': '#2d3348', 'selected': '#2e355c',
    'selected_hover': '#3a4373', 'text': '#f1f4fa', 'muted': '#9aa4ba',
    'faint': '#737e96', 'accent': '#6366f1', 'accent_hover': '#7c82f8',
    'accent_ink': '#ffffff', 'border': '#292e40', 'border_hover': '#3d4560',
    'grid': '#1f2434', 'alternate': '#141722', 'selection': '#373f6e',
    'selection_text': '#ffffff', 'success': '#10b981', 'warning': '#f59e0b',
    'danger': '#ef4444', 'danger_surface': '#331a20',
    'danger_hover': '#451f28', 'accent_surface': '#252a4e',
    'accent_surface_hover': '#343b6e', 'disabled': '#606b82',
    'disabled_bg': '#191d29', 'tooltip': '#1e2230',
    'progress_bg': '#11141c', 'favorite': '#a855f7',
}

_LIGHT = {
    'background': '#f8fafc', 'workspace': '#f8fafc', 'sidebar': '#f1f5f9',
    'surface': '#ffffff', 'surface_alt': '#f1f5f9', 'input': '#ffffff',
    'button': '#f1f5f9', 'hover': '#e2e8f0', 'selected': '#e0e7ff',
    'selected_hover': '#d5deff', 'text': '#0f172a', 'muted': '#64748b',
    'faint': '#94a3b8', 'accent': '#4f46e5', 'accent_hover': '#4338ca',
    'accent_ink': '#ffffff', 'border': '#e2e8f0', 'border_hover': '#cbd5e1',
    'grid': '#f1f5f9', 'alternate': '#f8fafc', 'selection': '#dbeafe',
    'selection_text': '#1e293b', 'success': '#059669', 'warning': '#d97706',
    'danger': '#dc2626', 'danger_surface': '#fef2f2',
    'danger_hover': '#fee2e2', 'accent_surface': '#e0e7ff',
    'accent_surface_hover': '#c7d2fe', 'disabled': '#94a3b8',
    'disabled_bg': '#f1f5f9', 'tooltip': '#ffffff',
    'progress_bg': '#e2e8f0', 'favorite': '#7c3aed',
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
QLabel#brandTitle { color: $accent; font-size: 18pt; font-weight: 800; letter-spacing: -0.5px; }
QLabel#brandSubtitle { color: $faint; font-size: 9pt; }
QLabel#pageTitle { color: $text; font-size: 21pt; font-weight: 700; letter-spacing: -0.5px; }
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
QPushButton[compact="true"] { padding: 4px 8px; }
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
    background: $surface;
    border: 1px solid $border;
    border-radius: 12px;
}
QTabBar::tab {
    color: $muted;
    background: $sidebar;
    border: 1px solid $border;
    padding: 8px 18px;
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
    font-weight: 500;
}
QTabBar::tab:selected {
    color: $text;
    background: $surface;
    border-bottom-color: $surface;
    font-weight: 600;
}
QTabBar::tab:hover { color: $text; background: $hover; }

QPushButton, QToolButton {
    color: $text;
    background: $button;
    border: 1px solid $border;
    border-radius: 8px;
    padding: 7px 14px;
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
    border: 1.5px solid $accent;
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
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus,
QDateEdit:focus, QTimeEdit:focus, QDateTimeEdit:focus,
QPlainTextEdit:focus, QTextEdit:focus {
    border: 1.5px solid $accent;
}
QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled,
QDoubleSpinBox:disabled, QDateEdit:disabled, QTimeEdit:disabled,
QDateTimeEdit:disabled, QPlainTextEdit:disabled, QTextEdit:disabled {
    color: $disabled;
    background: $disabled_bg;
}
QComboBox::drop-down { width: 26px; border: none; }
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
QAbstractItemView::item:disabled { color: $disabled; }
QHeaderView::section {
    color: $muted;
    background: $surface_alt;
    border: none;
    border-bottom: 1px solid $border;
    padding: 8px 12px;
    font-weight: 600;
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
    border-left: 3.5px solid transparent;
    border-radius: 8px;
    padding: 7px 10px;
    margin: 2px 4px;
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
    background: $surface_alt;
    width: 9px;
    margin: 2px;
    border-radius: 4px;
}
QScrollBar:horizontal {
    background: $surface_alt;
    height: 9px;
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
QGroupBox#settingsCard, QGroupBox#compactCard {
    margin-top: 0;
    padding: 10px 14px;
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
