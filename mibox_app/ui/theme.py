# -*- coding: utf-8 -*-
"""Catppuccin tabanli tema (koyu Mocha + acik Latte)."""

DARK_QSS = """
* { font-family: 'Segoe UI', sans-serif; font-size: 10pt; }
QMainWindow, QDialog { background-color: #1e1e2e; }
QWidget { color: #cdd6f4; background-color: #1e1e2e; }
QTabWidget::pane { border: 1px solid #45475a; border-radius: 6px; background: #181825; }
QTabBar::tab {
    padding: 8px 22px; color: #a6adc8; background: #1e1e2e;
    border: 1px solid #45475a; border-bottom: none; border-top-left-radius: 6px; border-top-right-radius: 6px;
}
QTabBar::tab:selected { background: #313244; color: #cdd6f4; }
QTabBar::tab:hover { background: #2a2a3c; }
QPushButton {
    background-color: #313244; color: #cdd6f4;
    border: 1px solid #45475a; border-radius: 6px; padding: 6px 14px;
}
QPushButton:hover { background-color: #3b3b52; border-color: #89b4fa; }
QPushButton:pressed { background-color: #2a2a3c; }
QPushButton:disabled { color: #6c7086; background-color: #26263a; }
QPushButton[flat="true"] { border: none; background: transparent; }
QPushButton[danger="true"] { background-color: #45293a; border-color: #f38ba8; }
QPushButton[danger="true"]:hover { background-color: #54324a; }
QPushButton[accent="true"] { background-color: #1e5a8a; border-color: #89b4fa; }
QPushButton[accent="true"]:hover { background-color: #2a6fa8; }
QLineEdit, QComboBox, QSpinBox, QPlainTextEdit, QTextEdit {
    background-color: #11111b; color: #cdd6f4;
    border: 1px solid #45475a; border-radius: 5px; padding: 4px 8px;
}
QLineEdit:focus, QComboBox:focus { border-color: #89b4fa; }
QComboBox::drop-down { border: none; width: 22px; }
QComboBox QAbstractItemView { background-color: #181825; color: #cdd6f4; border: 1px solid #45475a; selection-background-color: #313244; }
QTableWidget, QTableView, QListWidget, QTreeWidget {
    background-color: #11111b; color: #cdd6f4;
    border: 1px solid #45475a; border-radius: 5px;
    gridline-color: #2a2a3c; alternate-background-color: #16162a;
    selection-background-color: #313244; selection-color: #cdd6f4;
}
QTableWidget::item:selected, QTableView::item:selected, QListWidget::item:selected {
    background-color: #45475a; color: #ffffff;
}
QHeaderView::section {
    background-color: #1e1e2e; color: #a6adc8;
    border: none; border-bottom: 1px solid #45475a; padding: 6px 8px;
}
QScrollBar:vertical { background: #11111b; width: 10px; margin: 0; }
QScrollBar::handle:vertical { background: #45475a; border-radius: 5px; min-height: 30px; }
QScrollBar::handle:vertical:hover { background: #585b70; }
QScrollBar:horizontal { background: #11111b; height: 10px; margin: 0; }
QScrollBar::handle:horizontal { background: #45475a; border-radius: 5px; min-width: 30px; }
QScrollBar::add-line, QScrollBar::sub-line { background: none; border: none; }
QStatusBar { background-color: #11111b; color: #a6adc8; border-top: 1px solid #45475a; }
QMenuBar { background-color: #1e1e2e; }
QMenu { background-color: #181825; border: 1px solid #45475a; }
QMenu::item:selected { background-color: #313244; }
QGroupBox { border: 1px solid #45475a; border-radius: 6px; margin-top: 14px; font-weight: bold; }
QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; color: #89b4fa; }
QCheckBox { spacing: 8px; }
QCheckBox::indicator { width: 16px; height: 16px; border: 1px solid #45475a; border-radius: 4px; background: #11111b; }
QCheckBox::indicator:checked { background: #89b4fa; border-color: #89b4fa; }
QToolTip { background-color: #313244; color: #cdd6f4; border: 1px solid #45475a; }
"""

LIGHT_QSS = """
* { font-family: 'Segoe UI', sans-serif; font-size: 10pt; }
QMainWindow, QDialog { background-color: #eff1f5; }
QWidget { color: #4c4f69; background-color: #eff1f5; }
QTabWidget::pane { border: 1px solid #ccd0da; border-radius: 6px; background: #ffffff; }
QTabBar::tab {
    padding: 8px 22px; color: #6c6f85; background: #eff1f5;
    border: 1px solid #ccd0da; border-bottom: none; border-top-left-radius: 6px; border-top-right-radius: 6px;
}
QTabBar::tab:selected { background: #ffffff; color: #4c4f69; }
QPushButton {
    background-color: #e6e9ef; color: #4c4f69;
    border: 1px solid #ccd0da; border-radius: 6px; padding: 6px 14px;
}
QPushButton:hover { border-color: #1e66f5; }
QPushButton:disabled { color: #9ca0b0; background-color: #e6e9ef; }
QPushButton[flat="true"] { border: none; background: transparent; }
QPushButton[danger="true"] { background-color: #f5d5d8; border-color: #d20f39; color: #d20f39; }
QPushButton[accent="true"] { background-color: #1e66f5; border-color: #1e66f5; color: #ffffff; }
QLineEdit, QComboBox, QSpinBox, QPlainTextEdit, QTextEdit {
    background-color: #ffffff; color: #4c4f69;
    border: 1px solid #ccd0da; border-radius: 5px; padding: 4px 8px;
}
QComboBox QAbstractItemView { background-color: #ffffff; color: #4c4f69; selection-background-color: #ccd0da; }
QTableWidget, QTableView, QListWidget, QTreeWidget {
    background-color: #ffffff; color: #4c4f69;
    border: 1px solid #ccd0da; border-radius: 5px;
    gridline-color: #e6e9ef; alternate-background-color: #f5f6fa;
    selection-background-color: #ccd0da; selection-color: #4c4f69;
}
QHeaderView::section { background-color: #eff1f5; color: #6c6f85; border: none; border-bottom: 1px solid #ccd0da; padding: 6px 8px; }
QStatusBar { background-color: #e6e9ef; color: #6c6f85; border-top: 1px solid #ccd0da; }
QMenu { background-color: #ffffff; border: 1px solid #ccd0da; }
QMenu::item:selected { background-color: #ccd0da; }
QGroupBox { border: 1px solid #ccd0da; border-radius: 6px; margin-top: 14px; font-weight: bold; }
QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; color: #1e66f5; }
QToolTip { background-color: #ffffff; color: #4c4f69; border: 1px solid #ccd0da; }
"""

DARK_EXTRA_QSS = """
QSplitter::handle:vertical { background: #45475a; height: 4px; }
QSplitter::handle:vertical:hover { background: #89b4fa; }
QProgressBar {
    background-color: #11111b; border: 1px solid #45475a;
    border-radius: 5px; text-align: center; color: #a6adc8; max-height: 14px;
}
QProgressBar::chunk { background-color: #89b4fa; border-radius: 4px; }
QTableWidget::item { padding: 2px 6px; }
QTableCornerButton::section { background: #1e1e2e; border: none; }
"""

LIGHT_EXTRA_QSS = """
QSplitter::handle:vertical { background: #ccd0da; height: 4px; }
QSplitter::handle:vertical:hover { background: #1e66f5; }
QProgressBar {
    background-color: #ffffff; border: 1px solid #ccd0da;
    border-radius: 5px; text-align: center; color: #6c6f85; max-height: 14px;
}
QProgressBar::chunk { background-color: #1e66f5; border-radius: 4px; }
QTableWidget::item { padding: 2px 6px; }
QTableCornerButton::section { background: #eff1f5; border: none; }
QScrollBar:vertical { background: #e6e9ef; width: 10px; margin: 0; }
QScrollBar::handle:vertical { background: #ccd0da; border-radius: 5px; min-height: 30px; }
QScrollBar:horizontal { background: #e6e9ef; height: 10px; margin: 0; }
QScrollBar::handle:horizontal { background: #ccd0da; border-radius: 5px; min-width: 30px; }
QScrollBar::add-line, QScrollBar::sub-line { background: none; border: none; }
QCheckBox { spacing: 8px; }
QCheckBox::indicator { width: 16px; height: 16px; border: 1px solid #ccd0da; border-radius: 4px; background: #ffffff; }
QCheckBox::indicator:checked { background: #1e66f5; border-color: #1e66f5; }
"""

LEVEL_COLORS = {
    'INFO': '#a6e3a1',
    'WARN': '#f9e2af',
    'ERROR': '#f38ba8',
    'ADB': '#89b4fa',
    'VERBOSE': '#6c7086',
}

LIGHT_LEVEL_COLORS = {
    'INFO': '#40a02b',
    'WARN': '#df8e00',
    'ERROR': '#d20f39',
    'ADB': '#1e66f5',
    'VERBOSE': '#9ca0b0',
}

# QSS disinda kalan widget boyalari icin tek, tema-duyarli semantik palet.
DARK_COLORS = {
    'text': '#cdd6f4', 'muted': '#a6adc8', 'faint': '#6c7086',
    'accent': '#89b4fa', 'success': '#a6e3a1', 'warning': '#f9e2af',
    'danger': '#f38ba8', 'border': '#45475a',
}
LIGHT_COLORS = {
    'text': '#4c4f69', 'muted': '#6c6f85', 'faint': '#9ca0b0',
    'accent': '#1e66f5', 'success': '#40a02b', 'warning': '#df8e00',
    'danger': '#d20f39', 'border': '#ccd0da',
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
    key = 'success' if online else 'danger'
    return 'color: {}; font-weight: bold;'.format(colors_for(dark)[key])


def logcat_colors_for(dark=True):
    c = colors_for(dark)
    return {'V': c['faint'], 'D': c['accent'], 'I': c['success'],
            'W': c['warning'], 'E': c['danger'], 'F': c['danger']}


def cat_colors_for(dark=True):
    if dark:
        return {'guvenli': '#a6e3a1', 'opsiyonel': '#89b4fa',
                'riskli': '#f9e2af', 'dokunma': '#f38ba8',
                'favoriler': '#94e2d5'}
    return {'guvenli': '#40a02b', 'opsiyonel': '#1e66f5',
            'riskli': '#df8e00', 'dokunma': '#d20f39',
            'favoriler': '#0b9e8e'}


def removal_colors_for(dark=True):
    if dark:
        return {'Recommended': '#a6e3a1', 'Advanced': '#89b4fa',
                'Expert': '#f9e2af', 'Unsafe': '#f38ba8'}
    return {'Recommended': '#40a02b', 'Advanced': '#1e66f5',
            'Expert': '#df8e00', 'Unsafe': '#d20f39'}


def qss_for(dark=True):
    if dark:
        return DARK_QSS + DARK_EXTRA_QSS
    return LIGHT_QSS + LIGHT_EXTRA_QSS


def level_colors_for(dark=True):
    return LEVEL_COLORS if dark else LIGHT_LEVEL_COLORS
