# -*- coding: utf-8 -*-
"""Ortak UI kiti: tum sekmelerde ayni olcu, ayni dil, ayni davranis.

Kullanim: sekmeler daginik QWidget/QVBoxLayout yapmak yerine buradaki
yardimcilari kullanir:
  - page(): standart dis kenar (6px) + aralik (6px) iceren sayfa duzeni
  - section(title): QGroupBox baslikli bolum (basliklar ayni renkte)
  - action_bar(): FlowLayout'lu buton cubugu
  - status_label(): gri durum satiri (kelime kaydirma acik)
  - hint_label(): silik ipucu satiri
  - make_table(cols, headers): ayni stilli tablo (secim+zebra+24px satir)
  - set_busy(widgets, busy): buton kilitleme (cift worker onler)
  - confirm(): No-varsayilanli onay (dialogs.confirm_action kisayolu)
"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QGroupBox, QLabel, QTableWidget,
    QAbstractItemView, QMessageBox,
)

from .flowlayout import FlowLayout

MARGIN = 6
SPACING = 6
ROW_H = 24

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
    lbl.setStyleSheet(faint(dark_from(lbl) if dark is None else dark))
    lbl.setWordWrap(True)
    return lbl


def status_label(text='Hazir.', dark=None):
    lbl = QLabel(text)
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


def make_table(cols, headers):
    grid = QTableWidget(0, cols)
    grid.setHorizontalHeaderLabels(headers)
    grid.setSelectionBehavior(QAbstractItemView.SelectRows)
    grid.setSelectionMode(QAbstractItemView.ExtendedSelection)
    grid.setAlternatingRowColors(True)
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
    from PySide6.QtWidgets import QHBoxLayout as _HB, QPushButton as _PB, QLabel as _LB
    from .flowlayout import FlowLayout as _FL
    bar = _FL()
    btn_all = _PB('Tumunu Sec')
    btn_none = _PB('Secimi Birak')
    btn_inv = _PB('Ters Cevir')
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
            lbl.setText('Secili: {}/{}'.format(n, total))
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
