"""Small, consistent line icons rendered by Qt without external assets."""
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap


def line_icon(name, color='#9aa4b5', size=20):
    pixmap = QPixmap(size * 2, size * 2)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.scale(size * 2 / 24, size * 2 / 24)
    painter.setPen(QPen(QColor(color), 1.6, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))

    def line(x1, y1, x2, y2):
        painter.drawLine(QPointF(x1, y1), QPointF(x2, y2))

    def rect(x, y, w, h, radius=2):
        painter.drawRoundedRect(QRectF(x, y, w, h), radius, radius)

    if name == 'home':
        line(3, 11, 12, 3)
        line(12, 3, 21, 11)
        line(5, 10, 5, 21)
        line(5, 21, 19, 21)
        line(19, 21, 19, 10)
        rect(9, 14, 6, 7, 1)
    elif name == 'apps':
        for x in (4, 14):
            for y in (4, 14):
                rect(x, y, 6, 6, 1.5)
    elif name == 'remote':
        rect(7, 2, 10, 20, 4)
        painter.drawEllipse(QRectF(9, 7, 6, 6))
        line(10, 17, 14, 17)
    elif name == 'cleanup':
        line(4, 7, 20, 7)
        rect(6, 7, 12, 14, 1)
        line(9, 3, 15, 3)
        line(10, 11, 10, 17)
        line(14, 11, 14, 17)
    elif name == 'health':
        line(2, 12, 6, 12)
        line(6, 12, 9, 5)
        line(9, 5, 13, 19)
        line(13, 19, 16, 12)
        line(16, 12, 22, 12)
    elif name == 'optimization':
        painter.drawArc(QRectF(3, 5, 18, 18), 0, 180 * 16)
        line(12, 14, 17, 8)
        painter.drawEllipse(QRectF(10, 12, 4, 4))
        line(4, 19, 20, 19)
    elif name == 'history':
        painter.drawArc(QRectF(4, 4, 16, 16), 30 * 16, 300 * 16)
        line(3, 3, 3, 9)
        line(3, 9, 8, 9)
        line(12, 7, 12, 12)
        line(12, 12, 16, 14)
    elif name == 'logs':
        rect(3, 4, 18, 16)
        line(7, 9, 10, 12)
        line(10, 12, 7, 15)
        line(13, 15, 17, 15)
    elif name == 'files':
        rect(3, 7, 18, 13)
        line(3, 7, 3, 4)
        line(3, 4, 10, 4)
        line(10, 4, 13, 7)
    elif name == 'install':
        line(12, 3, 12, 15)
        line(7, 10, 12, 15)
        line(12, 15, 17, 10)
        line(4, 16, 4, 21)
        line(4, 21, 20, 21)
        line(20, 21, 20, 16)
    elif name == 'network':
        painter.drawEllipse(QRectF(9, 2, 6, 6))
        rect(2, 16, 6, 5, 1)
        rect(16, 16, 6, 5, 1)
        line(12, 8, 12, 12)
        line(5, 12, 19, 12)
        line(5, 12, 5, 16)
        line(19, 12, 19, 16)
    elif name == 'settings':
        for y, x in ((6, 9), (12, 16), (18, 7)):
            line(3, y, x - 2, y)
            line(x + 2, y, 21, y)
            painter.drawEllipse(QRectF(x - 2, y - 2, 4, 4))
    elif name == 'terminal':
        rect(3, 4, 18, 16, 2)
        line(6, 9, 10, 12)
        line(10, 12, 6, 15)
        line(12, 15, 17, 15)
    elif name in ('mute', 'volume-mute'):
        rect(3, 8, 4, 8, 1)
        line(7, 8, 12, 4)
        line(12, 4, 12, 20)
        line(12, 20, 7, 16)
        line(15, 9, 21, 15)
        line(21, 9, 15, 15)
    elif name in ('volume', 'speaker'):
        rect(3, 8, 4, 8, 1)
        line(7, 8, 12, 4)
        line(12, 4, 12, 20)
        line(12, 20, 7, 16)
        painter.drawArc(QRectF(13, 7, 6, 10), -50 * 16, 100 * 16)
    elif name in ('tv', 'display'):
        rect(3, 4, 18, 14)
        line(8, 21, 16, 21)
        line(12, 18, 12, 21)
    else:
        rect(3, 4, 18, 14)
        line(8, 21, 16, 21)
        line(12, 18, 12, 21)
    painter.end()
    pixmap.setDevicePixelRatio(2)
    return QIcon(pixmap)
