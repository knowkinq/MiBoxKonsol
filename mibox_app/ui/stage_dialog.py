# -*- coding: utf-8 -*-
"""Sahne önizleme diyaloğu: işlem listesini göster, onayla/iptal et."""
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QTableWidget, QTableWidgetItem,
    QLabel, QHeaderView, QAbstractItemView, QDialogButtonBox,
)
from PySide6.QtCore import Qt

from ..stage import ACTION_TR, ACTION_ICON, RISKY_ACTIONS
from . import kit


class StageDialog(QDialog):
    def __init__(self, parent, stage, friendly=None):
        super().__init__(parent)
        self.setWindowTitle('İşlem Önizleme — Sahne')
        self.resize(620, 420)
        lay = QVBoxLayout(self)
        lay.setSpacing(4)

        self._info = QLabel('Aşağıdaki işlemler sırayla uygulanacak. '
                      'Önce otomatik güvenlik snapshot alınır, sonuçlar geçmişe yazılır.')
        self._info.setWordWrap(True)
        self._info.setStyleSheet(kit.muted(kit.dark_from(parent)))
        lay.addWidget(self._info)

        self.grid = QTableWidget(0, 3)
        self.grid.setHorizontalHeaderLabels(['İşlem', 'Paket', 'Not'])
        hdr = self.grid.horizontalHeader()
        hdr.setSectionResizeMode(1, QHeaderView.Stretch)
        hdr.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.grid.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.grid.setAlternatingRowColors(True)
        lay.addWidget(self.grid, 1)

        for action, pkg in stage.items():
            r = self.grid.rowCount()
            self.grid.insertRow(r)
            icon = ACTION_ICON.get(action, '•')
            ai = QTableWidgetItem('{} {}'.format(icon, ACTION_TR.get(action, action)))
            pi = QTableWidgetItem('{}{}'.format(
                pkg, '' if (friendly is None or friendly(pkg) == pkg)
                else '  (' + friendly(pkg) + ')'))
            note = '⚠ geri dönüşü zor' if action in RISKY_ACTIONS else ''
            ni = QTableWidgetItem(note)
            for it in (ai, pi, ni):
                it.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            self.grid.setItem(r, 0, ai)
            self.grid.setItem(r, 1, pi)
            self.grid.setItem(r, 2, ni)

        self.lbl = QLabel('Toplam {} işlem.'.format(stage.count()))
        lay.addWidget(self.lbl)

    def apply_theme(self):
        """Tema degisince: bilgi etiketi yeni palete gecer."""
        try:
            self._info.setStyleSheet(kit.muted(kit.dark_from(self)))
        except (RuntimeError, AttributeError):
            pass

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.button(QDialogButtonBox.Ok).setText('Uygula')
        btns.button(QDialogButtonBox.Ok).setProperty('accent', True)
        btns.button(QDialogButtonBox.Cancel).setText('Vazgeç')
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        lay.addWidget(btns)
