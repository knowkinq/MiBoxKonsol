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
  - confirm(): No-varsayilanli onay (dialogs.confirm_action kisayolu)
"""
from PySide6.QtCore import Qt, QPointF
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QVBoxLayout, QGroupBox, QLabel, QTableWidget, QCheckBox,
    QAbstractItemView, QMessageBox, QStyle, QStyleOptionButton,
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
    while ancestor is not None:
        core = getattr(ancestor, 'core', ancestor)
        cfg = getattr(core, 'config', None)
        if cfg is not None and hasattr(cfg, 'dark_mode'):
            return bool(cfg.dark_mode)
        parent = getattr(ancestor, 'parentWidget', None)
        ancestor = parent() if callable(parent) else None
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


def _size_to_hint(w):
    """Buton/combo yazisi tasmasin: minimum genislik = hint olcusu."""
    try:
        hint = w.sizeHint()
        w.setMinimumWidth(max(w.minimumWidth(), hint.width()))
    except (RuntimeError, AttributeError):
        pass
    return w


def fit_buttons(*widgets):
    for w in widgets:
        _size_to_hint(w)


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


def select_bar(grid, check_col):
    """Standart toplu secim cubugu: Tumunu Sec / Birak / Ters Cevir.

    grid: QTableWidget, check_col: checkbox sutun indexi. Tik-crash
    korumasina uygun: sinyal bastirma + bayrak esitlik kontrolu.
    Donus: (bar_layout, secilen_sayisi_fonksiyonu).
    """
    from PySide6.QtCore import Qt as _Qt
    from PySide6.QtWidgets import QPushButton as _PB, QLabel as _LB
    from .flowlayout import FlowLayout as _FL
    bar = _FL()
    btn_all = _PB('Tümünü Seç')
    btn_none = _PB('Seçimi Bırak')
    btn_inv = _PB('Ters Çevir')
    lbl = _LB('')
    lbl.setStyleSheet(faint(dark_from(grid)))

    def _set_all(on):
        st = _Qt.Checked if on else _Qt.Unchecked
        grid.blockSignals(True)
        try:
            for row in range(grid.rowCount()):
                it = grid.item(row, check_col)
                if it and (it.flags() & _Qt.ItemIsUserCheckable):
                    if it.checkState() != st:
                        it.setCheckState(st)
        finally:
            try:
                grid.blockSignals(False)
            except RuntimeError:
                pass
        _update_count()

    def _invert():
        grid.blockSignals(True)
        try:
            for row in range(grid.rowCount()):
                it = grid.item(row, check_col)
                if it and (it.flags() & _Qt.ItemIsUserCheckable):
                    it.setCheckState(
                        _Qt.Unchecked if it.checkState() == _Qt.Checked else _Qt.Checked)
        finally:
            try:
                grid.blockSignals(False)
            except RuntimeError:
                pass
        _update_count()

    def _update_count():
        try:
            n = sum(1 for row in range(grid.rowCount())
                    for _ in [grid.item(row, check_col)]
                    if _ is not None and (_.flags() & _Qt.ItemIsUserCheckable)
                    and _.checkState() == _Qt.Checked)
            total = grid.rowCount()
            lbl.setText('Seçili: {}/{}'.format(n, total))
        except RuntimeError:
            pass

    def selected():
        """Secili checkbox satirlari (yoksa secili satirlar)."""
        out = []
        try:
            for row in range(grid.rowCount()):
                it = grid.item(row, check_col)
                if it and (it.flags() & _Qt.ItemIsUserCheckable) \
                        and it.checkState() == _Qt.Checked:
                    out.append(it.data(_Qt.UserRole))
        except RuntimeError:
            return out
        return out

    btn_all.clicked.connect(lambda: _set_all(True))
    btn_none.clicked.connect(lambda: _set_all(False))
    btn_inv.clicked.connect(_invert)
    for w in (btn_all, btn_none, btn_inv):
        bar.addWidget(w)
        fit_buttons(w)
    bar.addWidget(lbl)
    try:
        grid.itemChanged.connect(lambda _it: _update_count())
    except (RuntimeError, AttributeError):
        pass
    _update_count()
    return bar, selected, _update_count


def confirm(parent, title, body):
    return QMessageBox.question(parent, title, body,
                                QMessageBox.Yes | QMessageBox.No,
                                QMessageBox.No) == QMessageBox.Yes
