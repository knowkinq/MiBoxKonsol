# -*- coding: utf-8 -*-
"""Sahne önizleme diyaloğu: işlem listesini göster, onayla/iptal et."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QHeaderView,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from ..stage import ACTION_ICON, ACTION_TR, RISKY_ACTIONS
from . import kit


class StageDialog(QDialog):
    def __init__(self, parent, stage, friendly=None, description=None, summary=None):
        super().__init__(parent)
        self.setWindowTitle('İşlem Önizleme — Sahne')
        self.resize(620, 420)
        lay = QVBoxLayout(self)
        lay.setSpacing(4)

        self._info = QLabel('Aşağıdaki işlemler sırayla uygulanacak. '
                      'Önce paket durum kaydı alınır, sonuçlar geçmişe yazılır. '
                      'Bu kayıt uygulama verilerini yedeklemez.')
        self._info.setWordWrap(True)
        self._info.setStyleSheet(kit.muted(kit.dark_from(parent)))
        lay.addWidget(self._info)

        self._description = None
        if description:
            self._description = QLabel(description)
            self._description.setWordWrap(True)
            self._description.setStyleSheet(kit.muted(kit.dark_from(parent)))
            lay.addWidget(self._description)

        self._summary = None
        if summary:
            self._summary = QLabel(summary)
            self._summary.setWordWrap(True)
            self._summary.setStyleSheet(kit.muted(kit.dark_from(parent)))
            lay.addWidget(self._summary)

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
            icon = ACTION_ICON.get(action, '⚡' if action == 'smart' else '•')
            label = ACTION_TR.get(
                action, 'Akıllı kaldır' if action == 'smart' else action)
            ai = QTableWidgetItem('{} {}'.format(icon, label))
            pi = QTableWidgetItem('{}{}'.format(
                pkg, '' if (friendly is None or friendly(pkg) == pkg)
                else '  (' + friendly(pkg) + ')'))
            if action == 'smart':
                note = '⚠ önce devre dışı, olmazsa kaldır'
            else:
                note = '⚠ geri dönüşü zor' if action in RISKY_ACTIONS else ''
            ni = QTableWidgetItem(note)
            for it in (ai, pi, ni):
                it.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            self.grid.setItem(r, 0, ai)
            self.grid.setItem(r, 1, pi)
            self.grid.setItem(r, 2, ni)

        self.lbl = QLabel('Toplam {} işlem.'.format(stage.count()))
        lay.addWidget(self.lbl)

        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.buttons.button(QDialogButtonBox.Ok).setText('Uygula')
        self.buttons.button(QDialogButtonBox.Ok).setProperty('accent', True)
        self.buttons.button(QDialogButtonBox.Cancel).setText('Vazgeç')
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        lay.addWidget(self.buttons)

    def apply_theme(self):
        """Tema degisince: bilgi etiketleri yeni palete gecer."""
        try:
            style = kit.muted(kit.dark_from(self))
            for label in (self._info, self._description, self._summary):
                if label is not None:
                    label.setStyleSheet(style)
        except (RuntimeError, AttributeError):
            pass
