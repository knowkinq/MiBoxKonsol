# -*- coding: utf-8 -*-
"""Shared charcoal/indigo and light UI themes from semantic tokens."""
from string import Template


_DARK = {
    'background': '#111318', 'workspace': '#15171d', 'sidebar': '#111318',
    'surface': '#1b1e26', 'surface_alt': '#222630', 'input': '#111318',
    'button': '#252933', 'hover': '#303542', 'selected': '#2d3150',
    'selected_hover': '#373c60', 'text': '#edf0f7', 'muted': '#a6aebf',
    'faint': '#828c9f', 'accent': '#8795ff', 'accent_hover': '#a0abff',
    'accent_ink': '#11152e', 'border': '#303542', 'border_hover': '#454c5c',
    'grid': '#272c37', 'alternate': '#1d2029', 'selection': '#343b61',
    'selection_text': '#f4f5ff', 'success': '#79c7a2', 'warning': '#d8b677',
    'danger': '#e592a0', 'danger_surface': '#33252b',
    'danger_hover': '#442d35', 'accent_surface': '#2e3456',
    'accent_surface_hover': '#3c4470', 'disabled': '#788294',
    'disabled_bg': '#222630', 'tooltip': '#262b36',
    'progress_bg': '#111318', 'favorite': '#a8a3df',
}
_LIGHT = {
    'background': '#f5f6fa', 'workspace': '#f5f6fa', 'sidebar': '#eef0f5',
    'surface': '#ffffff', 'surface_alt': '#f6f7fb', 'input': '#ffffff',
    'button': '#f2f3f8', 'hover': '#e8ebf3', 'selected': '#e9ecff',
    'selected_hover': '#dfe4ff', 'text': '#202637', 'muted': '#667086',
    'faint': '#778297', 'accent': '#5365d8', 'accent_hover': '#4253bb',
    'accent_ink': '#ffffff', 'border': '#dfe3ec', 'border_hover': '#bcc5d7',
    'grid': '#edf0f5', 'alternate': '#fafbfe', 'selection': '#e0e5ff',
    'selection_text': '#222c4a', 'success': '#2e795c', 'warning': '#966927',
    'danger': '#b44960', 'danger_surface': '#fbf0f3',
    'danger_hover': '#f6e0e7', 'accent_surface': '#e9ecff',
    'accent_surface_hover': '#dce2ff', 'disabled': '#929bad',
    'disabled_bg': '#f0f2f7', 'tooltip': '#ffffff',
    'progress_bg': '#ffffff', 'favorite': '#5365d8',
}

_QSS = Template("""
* { font-family: 'Segoe UI', sans-serif; font-size: 10pt; }
QMainWindow, QDialog { background-color: $background; }
QWidget { color: $text; background-color: $workspace; }
QLabel, QCheckBox, QRadioButton { background: transparent; }
QScrollArea, QScrollArea > QWidget > QWidget { background: $workspace; border: none; }
QWidget#workspace { background-color: $workspace; }
QWidget#sidebar { background-color: $sidebar; border-right: 1px solid $border; }
QWidget#connectionCard, QWidget#logCard {
    background-color: $surface; border: 1px solid $border; border-radius: 12px;
}
QFrame#contentCard, QFrame#metricCard, QFrame#maintenanceCard {
    background-color: $surface; border: 1px solid $border; border-radius: 10px;
}
QLabel[role="quiet"], QLabel[role="secondary"] { color: $muted; }
QLabel#brandTitle { color: $accent; font-size: 17pt; font-weight: 700; }
QLabel#brandSubtitle { color: $faint; font-size: 9pt; }
QLabel#pageTitle { color: $text; font-size: 20pt; font-weight: 700; }
QLabel#pageSubtitle { color: $muted; font-size: 10pt; }
QLabel#cardTitle { color: $text; font-size: 11pt; font-weight: 600; }
QLabel#metricValue { color: $text; font-size: 22pt; font-weight: 600; }
QLabel#metricLabel { color: $muted; font-size: 9pt; }
QLabel#emptyState { color: $muted; background: transparent; font-size: 11pt; }
QWidget#remotePad { background: $surface_alt; border: 1px solid $border; border-radius: 24px; }
QWidget#errorBanner { background: $danger_surface; border: 1px solid $danger; border-radius: 10px; }
QPushButton#remoteKey { min-width: 38px; min-height: 38px; border-radius: 20px; }
QPushButton[compact="true"] { padding: 4px 7px; }
QPushButton[role="primary"] { color: $accent_ink; background: $accent; border-color: $accent; font-weight: 600; }
QPushButton[role="primary"]:hover { background: $accent_hover; }
QPushButton[role="quiet"] { color: $muted; background: transparent; border-color: transparent; }
QPushButton[role="quiet"]:hover { color: $text; background: $hover; }
QPushButton[role="primary"]:disabled, QPushButton[role="quiet"]:disabled { color: $disabled; background: $disabled_bg; border-color: $border; }

QTabWidget::pane { background: $surface; border: 1px solid $border; border-radius: 10px; }
QTabBar::tab {
    color: $muted; background: $sidebar; border: 1px solid $border;
    padding: 8px 16px; border-top-left-radius: 7px; border-top-right-radius: 7px;
}
QTabBar::tab:selected { color: $text; background: $surface; }
QTabBar::tab:hover { color: $text; background: $hover; }

QPushButton, QToolButton {
    color: $text; background: $button; border: 1px solid $border;
    border-radius: 8px; padding: 7px 13px; min-height: 18px;
}
QPushButton:hover, QToolButton:hover { background: $hover; border-color: $border_hover; }
QPushButton:pressed, QToolButton:pressed { background: $selected; }
QPushButton:checked, QToolButton:checked {
    color: $text; background: $accent_surface; border-color: $accent;
}
QPushButton:focus, QToolButton:focus { border: 2px solid $accent; }
QPushButton[flat="true"] { border: none; background: transparent; }
QPushButton[accent="true"] { color: $accent_ink; background: $accent; border-color: $accent; font-weight: 600; }
QPushButton[accent="true"]:hover { background: $accent_hover; border-color: $accent_hover; }
QPushButton[danger="true"] { color: $danger; background: $danger_surface; border-color: $danger; }
QPushButton[danger="true"]:hover { background: $danger_hover; }
QPushButton:disabled, QToolButton:disabled {
    color: $disabled; background: $disabled_bg; border-color: $border;
}
QPushButton[accent="true"]:disabled, QPushButton[danger="true"]:disabled {
    color: $disabled; background: $disabled_bg; border-color: $border;
}

QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QDateEdit, QTimeEdit,
QDateTimeEdit, QPlainTextEdit, QTextEdit {
    color: $text; background: $input; border: 1px solid $border;
    border-radius: 7px; padding: 6px 9px;
    selection-background-color: $selection; selection-color: $selection_text;
}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus,
QDateEdit:focus, QTimeEdit:focus, QDateTimeEdit:focus,
QPlainTextEdit:focus, QTextEdit:focus { border: 1px solid $accent; }
QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled,
QDoubleSpinBox:disabled, QDateEdit:disabled, QTimeEdit:disabled,
QDateTimeEdit:disabled, QPlainTextEdit:disabled, QTextEdit:disabled {
    color: $disabled; background: $disabled_bg;
}
QComboBox::drop-down { width: 24px; border: none; }
QComboBox QAbstractItemView {
    color: $text; background: $surface; border: 1px solid $border;
    selection-background-color: $selection; selection-color: $selection_text;
}

QTableWidget, QTableView, QListWidget, QTreeWidget {
    color: $text; background: $input; alternate-background-color: $alternate;
    border: 1px solid $border; border-radius: 8px; gridline-color: $grid;
    selection-background-color: $selection; selection-color: $selection_text;
    outline: 0;
}
QTableView::item, QTableWidget::item { padding: 3px 8px; }
QAbstractItemView::item:disabled { color: $disabled; }
QHeaderView::section {
    color: $muted; background: $surface_alt; border: none;
    border-bottom: 1px solid $border; padding: 7px 10px; font-weight: 600;
}
QTableCornerButton::section { background: $surface_alt; border: none; }
QListWidget#navigation { color: $muted; background: transparent; border: none; padding: 0; }
QListWidget#navigation::item {
    color: $muted; background: transparent; border: 1px solid transparent;
    border-left: 3px solid transparent; border-radius: 8px;
    padding: 6px 9px; margin: 0;
}
QListWidget#navigation::item:hover { color: $text; background: $hover; }
QListWidget#navigation::item:selected {
    color: $text; background: $selected; border-left-color: $accent; font-weight: 600;
}
QListWidget#navigation::item:selected:hover { background: $selected_hover; }

QScrollBar:vertical { background: $surface_alt; width: 11px; margin: 2px; }
QScrollBar:horizontal { background: $surface_alt; height: 11px; margin: 2px; }
QScrollBar::handle:vertical, QScrollBar::handle:horizontal {
    background: $border_hover; border-radius: 5px; min-height: 28px; min-width: 28px;
}
QScrollBar::handle:vertical:hover, QScrollBar::handle:horizontal:hover { background: $accent; }
QScrollBar::add-line, QScrollBar::sub-line { background: transparent; border: none; width: 0; height: 0; }

QStatusBar { color: $muted; background: $sidebar; border-top: 1px solid $border; }
QMenuBar { color: $text; background: $sidebar; }
QMenuBar::item:selected, QMenu::item:selected { color: $text; background: $selected; }
QMenu { color: $text; background: $surface; border: 1px solid $border; padding: 4px; }
QMenu::item { padding: 6px 22px 6px 10px; border-radius: 5px; }
QMenu::item:disabled { color: $disabled; }
QGroupBox { background: $surface; border: 1px solid $border; border-radius: 10px; margin-top: 4px; padding: 28px 12px 12px; font-weight: 600; }
QGroupBox#settingsCard, QGroupBox#compactCard { margin-top: 0; padding: 10px 12px; }
QGroupBox::title { subcontrol-origin: padding; subcontrol-position: top left; left: 12px; top: 8px; padding: 0; color: $text; }
QCheckBox, QRadioButton { spacing: 8px; }
QCheckBox::indicator, QRadioButton::indicator {
    width: 17px; height: 17px; background: $input; border: 1px solid $border_hover;
}
QCheckBox::indicator { border-radius: 4px; }
QRadioButton::indicator { border-radius: 9px; }
QCheckBox::indicator:checked, QRadioButton::indicator:checked {
    background: $accent; border: 2px solid $accent;
}
QCheckBox::indicator:focus, QRadioButton::indicator:focus { border-color: $accent; }
QCheckBox:disabled, QRadioButton:disabled { color: $disabled; }
QToolTip { color: $text; background: $tooltip; border: 1px solid $border_hover; padding: 5px 7px; }
""")

_EXTRA_QSS = Template("""
QSplitter::handle:vertical { background: $border; height: 5px; }
QSplitter::handle:horizontal { background: $border; width: 5px; }
QSplitter::handle:hover { background: $accent; }
QProgressBar {
    color: $muted; background: $progress_bg; border: 1px solid $border;
    border-radius: 6px; text-align: center; max-height: 18px;
}
QProgressBar::chunk { background: $accent; border-radius: 5px; }
""")


def _build_qss(tokens, template):
    return template.substitute(tokens)


# Public stylesheet constants retained for callers that import them directly.
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
