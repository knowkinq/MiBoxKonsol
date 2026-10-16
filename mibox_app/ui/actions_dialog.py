# -*- coding: utf-8 -*-
"""Searchable, keyboard-accessible navigation and safe quick actions."""
import unicodedata

from PySide6.QtCore import Qt, QEvent, QRect, QSize
from PySide6.QtWidgets import QDialog, QVBoxLayout, QLineEdit, QListWidget, QListWidgetItem, QLabel


def search_key(text):
    text = str(text).casefold().replace('ı', 'i')
    return ''.join(c for c in unicodedata.normalize('NFKD', text)
                   if not unicodedata.combining(c))


class ActionsDialog(QDialog):
    def __init__(self, parent, actions):
        super().__init__(parent)
        self.setWindowTitle('Hızlı erişim')
        self.resize(520, 430)
        self._actions = actions
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(10)
        self.search = QLineEdit()
        self.search.setPlaceholderText('Sayfa veya işlem ara…')
        self.search.setAccessibleName('Hızlı erişimde ara')
        self.search.setClearButtonEnabled(True)
        self.search.installEventFilter(self)
        layout.addWidget(self.search)
        self.results = QListWidget()
        self.results.setAccessibleName('Hızlı erişim sonuçları')
        self.results.setWordWrap(True)
        self.results.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        layout.addWidget(self.results, 1)
        self.empty = QLabel('Eşleşen sayfa veya işlem yok.')
        self.empty.setProperty('role', 'quiet')
        layout.addWidget(self.empty)
        hint = QLabel('↑ ↓ Seç   ·   Enter Aç   ·   Esc Kapat')
        hint.setProperty('role', 'quiet')
        layout.addWidget(hint)
        self.search.textChanged.connect(self._filter)
        self.search.returnPressed.connect(self._activate)
        self.results.itemClicked.connect(self._activate)
        self.results.installEventFilter(self)
        self._filter('')

    def _filter(self, text):
        terms = search_key(text).split()
        self.results.clear()
        for index, (title, description, callback, enabled) in enumerate(self._actions):
            if all(term in search_key(title + ' ' + description) for term in terms):
                item = QListWidgetItem(title + '\n' + description)
                item.setToolTip(description)
                item.setSizeHint(QSize(0, max(66, self.results.fontMetrics().height() * 3 + 12)))
                item.setData(Qt.UserRole, index)
                if not enabled():
                    item.setFlags(item.flags() & ~Qt.ItemIsEnabled & ~Qt.ItemIsSelectable)
                self.results.addItem(item)
        self.empty.setVisible(self.results.count() == 0)
        for row in range(self.results.count()):
            if self.results.item(row).flags() & Qt.ItemIsEnabled:
                self.results.setCurrentRow(row)
                break
        self._size_results()

    def _size_results(self):
        width = max(120, self.results.viewport().width() - 24)
        metrics = self.results.fontMetrics()
        for row in range(self.results.count()):
            item = self.results.item(row)
            bounds = metrics.boundingRect(QRect(0, 0, width, 10000), Qt.TextWordWrap, item.text())
            item.setSizeHint(QSize(0, max(66, bounds.height() + 20)))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._size_results()

    def _activate(self, item=None):
        if item is None:
            item = self.results.currentItem()
        if item is None or not (item.flags() & Qt.ItemIsEnabled):
            return
        action = self._actions[item.data(Qt.UserRole)]
        if action[3]():
            self.accept()
            action[2]()

    def eventFilter(self, obj, event):
        if obj is self.results and event.type() == QEvent.KeyPress and event.key() in (Qt.Key_Return, Qt.Key_Enter):
            self._activate()
            return True
        if obj is self.search and event.type() == QEvent.KeyPress and event.key() in (Qt.Key_Up, Qt.Key_Down):
            step = 1 if event.key() == Qt.Key_Down else -1
            row = self.results.currentRow() + step
            while 0 <= row < self.results.count():
                if self.results.item(row).flags() & Qt.ItemIsEnabled:
                    self.results.setCurrentRow(row)
                    break
                row += step
            return True
        return super().eventFilter(obj, event)
