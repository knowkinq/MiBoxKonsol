# -*- coding: utf-8 -*-
"""Dar ekranlarda butonlarin alt satira kaymasini saglayan FlowLayout.

Qt ornek FlowLayout'un sadelestirilmis hali: icindeki widget'lari
yatayda dizer, sigmayinca alt satira gecer. Islem cubuklari ve
kumanda tuslari icin kullanilir.
"""
from PySide6.QtCore import QPoint, QRect, QSize, Qt
from PySide6.QtWidgets import QLayout, QSizePolicy


class FlowLayout(QLayout):
    def __init__(self, parent=None, margin=0, hspacing=6, vspacing=6):
        super().__init__(parent)
        self._items = []
        self._h = hspacing
        self._v = vspacing
        self.setContentsMargins(margin, margin, margin, margin)

    def __del__(self):
        while self.takeAt(0):
            pass

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, index):
        if 0 <= index < len(self._items):
            return self._items[index]
        return None

    def takeAt(self, index):
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None

    def expandingDirections(self):
        return Qt.Orientations(Qt.Orientation(0))

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._do_layout(QRect(0, 0, width, 0), True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._do_layout(rect, False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        m = self.contentsMargins()
        size += QSize(m.left() + m.right(), m.top() + m.bottom())
        return size

    def _do_layout(self, rect, test_only):
        m = self.contentsMargins()
        area = rect.adjusted(m.left(), m.top(), -m.right(), -m.bottom())
        x = area.x()
        y = area.y()
        line_h = 0
        for item in self._items:
            w = item.widget()
            space_x = self._h
            space_y = self._v
            if w is not None:
                space_x += w.style().layoutSpacing(
                    QSizePolicy.PushButton, QSizePolicy.PushButton, Qt.Horizontal)
                space_y += w.style().layoutSpacing(
                    QSizePolicy.PushButton, QSizePolicy.PushButton, Qt.Vertical)
            nxt_x = x + item.sizeHint().width() + space_x
            if nxt_x - space_x > area.right() and line_h > 0:
                x = area.x()
                y = y + line_h + space_y
                nxt_x = x + item.sizeHint().width() + space_x
                line_h = 0
            if not test_only:
                item.setGeometry(QRect(QPoint(x, y), item.sizeHint()))
            x = nxt_x
            line_h = max(line_h, item.sizeHint().height())
        return y + line_h - rect.y() + m.top() + m.bottom()
