# -*- coding: utf-8 -*-
"""Dar ekranlarda butonlarin alt satira kaymasini saglayan FlowLayout.

Qt ornek FlowLayout'un sadelestirilmis hali: icindeki widget'lari
yatayda dizer, sigmayinca alt satira gecer. Islem cubuklari ve
kumanda tuslari icin kullanilir.
"""
from PySide6.QtCore import QRect, QSize, Qt
from PySide6.QtWidgets import QLayout, QSizePolicy


class FlowLayout(QLayout):
    def __init__(self, parent=None, margin=0, hspacing=6, vspacing=6):
        self._items = []
        self._h = hspacing
        self._v = vspacing
        super().__init__(parent)
        self.setContentsMargins(margin, margin, margin, margin)

    def __del__(self):
        while self.takeAt(0):
            pass

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(getattr(self, '_items', ()))

    def itemAt(self, index):
        items = getattr(self, '_items', ())
        if 0 <= index < len(items):
            return items[index]
        return None

    def takeAt(self, index):
        items = getattr(self, '_items', [])
        if 0 <= index < len(items):
            return items.pop(index)
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
            if item.isEmpty():
                continue
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
        line_items = []

        def place_line():
            if test_only:
                return
            for item, item_x, item_w, item_h in line_items:
                item.setGeometry(QRect(item_x, y + (line_h - item_h) // 2,
                                       item_w, item_h))

        for item in self._items:
            if item.isEmpty():
                continue
            w = item.widget()
            space_x = self._h
            space_y = self._v
            if w is not None:
                space_x += max(0, w.style().layoutSpacing(
                    QSizePolicy.PushButton, QSizePolicy.PushButton, Qt.Horizontal))
                space_y += max(0, w.style().layoutSpacing(
                    QSizePolicy.PushButton, QSizePolicy.PushButton, Qt.Vertical))
            nxt_x = x + item.sizeHint().width() + space_x
            if nxt_x - space_x > area.right() + 1 and line_h > 0:
                place_line()
                x = area.x()
                y = y + line_h + space_y
                nxt_x = x + item.sizeHint().width() + space_x
                line_h = 0
                line_items = []
            size = item.sizeHint()
            line_items.append((item, x, size.width(), size.height()))
            x = nxt_x
            line_h = max(line_h, item.sizeHint().height())
        place_line()
        return y + line_h - rect.y() + m.bottom()
