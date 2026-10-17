# -*- coding: utf-8 -*-
"""Ortak UI kiti: tum sekmelerde ayni olcu, ayni dil, ayni davranis.

Kullanim: sekmeler daginik QWidget/QVBoxLayout yapmak yerine buradaki
yardimcilari kullanir:
  - page(): standart dis kenar (10px) + aralik (8px) iceren sayfa duzeni
  - section(title): QGroupBox baslikli bolum (basliklar ayni renkte)
  - action_bar(): FlowLayout'lu buton cubugu
  - status_label(): gri durum satiri (kelime kaydirma acik)
  - hint_label(): silik ipucu satiri
  - make_table(cols, headers): ayni stilli tablo (secim+zebra+30px satir)
  - set_busy(widgets, busy): buton kilitleme (cift worker onler)
  - csv_cell(value): CSV hucrelerinde formul enjeksiyonunu etkisizlestirir
"""
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QGroupBox,
    QLabel,
    QStyle,
    QStyleOptionButton,
    QTableWidget,
    QVBoxLayout,
)

from .flowlayout import FlowLayout

MARGIN = 10
SPACING = 8
ROW_H = 30


class CheckBox(QCheckBox):
    """Tema gostergesi tik isaretini cizmediginde secili durumu belirginlestir."""

    def paintEvent(self, event):
        super().paintEvent(event)
        if not self.isChecked():
            return

        option = QStyleOptionButton()
        self.initStyleOption(option)
        indicator = self.style().subElementRect(
            QStyle.SE_CheckBoxIndicator, option, self)
        if not indicator.isValid():
            return

        ink = QColor('#11152e' if dark_from(self) else '#ffffff')
        pen = QPen(ink, max(1.5, indicator.height() * 0.12),
                   Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(pen)
        left, top = indicator.left(), indicator.top()
        width, height = indicator.width(), indicator.height()
        painter.drawLine(
            QPointF(left + width * 0.22, top + height * 0.52),
            QPointF(left + width * 0.43, top + height * 0.72))
        painter.drawLine(
            QPointF(left + width * 0.43, top + height * 0.72),
            QPointF(left + width * 0.79, top + height * 0.30))
        painter.end()

# Geriye uyumlu sabitler (koyu tema varsayilan). Yeni kod dark parametreli
# yardimcilari kullanmali: muted()/faint()/title().
MUTED = 'color: #a6adc8;'
FAINT = 'color: #6c7086;'
TITLE_BLUE = 'color: #89b4fa; font-weight: bold;'


def _dark_of(dark=True):
    try:
        return bool(dark)
    except Exception:
        return True


def muted(dark=True):
    from .theme import muted_style
    return muted_style(_dark_of(dark))


def faint(dark=True):
    from .theme import faint_style
    return faint_style(_dark_of(dark))


def title(dark=True):
    from .theme import title_style
    return title_style(_dark_of(dark))


def dark_from(widget=None, default=True):
    """Bir widget/core/window uzerinden koyu-tema bayragini coz."""
    ancestor = widget
    try:
        while ancestor is not None:
            core = getattr(ancestor, 'core', ancestor)
            cfg = getattr(core, 'config', None)
            if cfg is not None and hasattr(cfg, 'dark_mode'):
                return bool(cfg.dark_mode)
            parent = getattr(ancestor, 'parentWidget', None)
            ancestor = parent() if callable(parent) else None
    except Exception:
        # Silinmis C++ nesnesi (RuntimeError) ya da beklenmedik erisim:
        # varsayilana dus; cagirani patlatma (olasilik testi yakaladi).
        return default
    try:
        core = getattr(widget, 'core', widget)
        cfg = getattr(core, 'config', None)
        if cfg is not None and hasattr(cfg, 'dark_mode'):
            return bool(cfg.dark_mode)
    except Exception:
        pass
    try:
        win = getattr(widget, 'window', None)
        core = getattr(win, 'core', None)
        cfg = getattr(core, 'config', None)
        if cfg is not None and hasattr(cfg, 'dark_mode'):
            return bool(cfg.dark_mode)
    except Exception:
        pass
    return default


def colors(widget=None, default=True):
    """Tema-duyarli semantik palet {'text','muted','faint','accent',...}."""
    from .theme import colors_for
    return colors_for(dark_from(widget, default))


def mono_style():
    """Monospace konsol/metin kutulari: renk QSS'ten gelir, yalnizca tipografi."""
    return 'font-family: Consolas, "Courier New", monospace; font-size: 11px;'


def refresh_theme(widget):
    """Widget agacindaki tum `apply_theme()` uygulamali nesneleri yeniler.

    Tema degisince pencere bunu cagirir; boylece sabit renkler de
    (tablo on renkleri, ipucu etiketleri, log HTML) yeni palete gecer.
    """
    if widget is None:
        return
    if isinstance(widget, QLabel):
        role = widget.property('semanticRole')
        if role in ('muted', 'faint'):
            widget.setStyleSheet(muted(dark_from(widget)) if role == 'muted'
                                else faint(dark_from(widget)))
    try:
        if hasattr(widget, 'apply_theme'):
            widget.apply_theme()
    except RuntimeError:
        return
    except Exception:
        pass
    try:
        kids = list(widget.children())
    except RuntimeError:
        return
    for ch in kids:
        refresh_theme(ch)


def page(widget):
    root = QVBoxLayout(widget)
    root.setContentsMargins(MARGIN, MARGIN, MARGIN, MARGIN)
    root.setSpacing(SPACING)
    return root


def section(title):
    box = QGroupBox(title)
    return box


def hint_label(text='', dark=None):
    lbl = QLabel(text)
    lbl.setProperty('semanticRole', 'faint')
    lbl.setStyleSheet(faint(dark_from(lbl) if dark is None else dark))
    lbl.setWordWrap(True)
    return lbl


def status_label(text='Hazır.', dark=None):
    lbl = QLabel(text)
    lbl.setProperty('semanticRole', 'muted')
    lbl.setStyleSheet(muted(dark_from(lbl) if dark is None else dark))
    lbl.setWordWrap(True)
    return lbl


def action_bar():
    return FlowLayout()


class DataTable(QTableWidget):
    """Table with a useful empty state that follows real model changes."""

    def __init__(self, cols):
        super().__init__(0, cols)
        self.empty_title = 'Henüz veri yok'
        self.empty_description = 'Cihaza bağlanın ve listeyi yenileyin.'
        self.empty_label = QLabel(self.viewport())
        self.empty_label.setObjectName('emptyState')
        self.empty_label.setAlignment(Qt.AlignCenter)
        self.empty_label.setWordWrap(True)
        self.empty_label.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.apply_theme()
        for signal in (self.model().rowsInserted, self.model().rowsRemoved,
                       self.model().modelReset):
            signal.connect(self._update_empty)

    def apply_theme(self):
        def escape(text):
            return str(text).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('\n', '<br>')
        palette = colors(self)
        self.empty_label.setText(
            '<p style="font-size: 12pt; font-weight: 600; color: {}">{}</p>'
            '<p style="font-size: 10pt; color: {}">{}</p>'.format(
                palette['text'], escape(self.empty_title),
                palette['muted'], escape(self.empty_description)))

    def _update_empty(self, *_args):
        self.empty_label.setGeometry(self.viewport().rect().adjusted(20, 12, -20, -12))
        self.empty_label.setVisible(self.rowCount() == 0 and self.viewport().height() > 80)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_empty()


def empty_state(grid, title, description):
    if isinstance(grid, DataTable):
        grid.empty_title = title
        grid.empty_description = description
        grid.apply_theme()
        grid._update_empty()


def make_table(cols, headers):
    grid = DataTable(cols)
    grid.setHorizontalHeaderLabels(headers)
    grid.setSelectionBehavior(QAbstractItemView.SelectRows)
    grid.setSelectionMode(QAbstractItemView.ExtendedSelection)
    grid.setAlternatingRowColors(True)
    grid.setShowGrid(False)
    grid.setWordWrap(False)
    grid.verticalHeader().setDefaultSectionSize(ROW_H)
    grid.verticalHeader().setVisible(False)
    return grid


def single_table(cols, headers):
    grid = make_table(cols, headers)
    grid.setSelectionMode(QAbstractItemView.SingleSelection)
    return grid


def set_busy(widgets, busy):
    for w in widgets:
        try:
            w.setEnabled(not busy)
        except RuntimeError:
            pass


def csv_cell(value):
    """CSV hucre degeri; formul enjeksiyonunu ('=', '+', '-', '@') etkisizlestirir."""
    text = '' if value is None else str(value)
    if text.lstrip(' \t\r\n\v\f')[:1] in ('=', '+', '-', '@'):
        return "'" + text
    return text
