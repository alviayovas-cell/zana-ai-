"""Crisp vector icons drawn with QPainter (no image files, scale to any DPI)."""

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap

from . import theme


def _draw(name: str, p: QPainter, s: float) -> None:
    """Draw an icon in a square of side ``s`` using the painter's current pen."""
    u = s / 24.0
    p.setBrush(Qt.NoBrush)
    if name == "home":
        path = QPainterPath()
        path.moveTo(3.5 * u, 11 * u)
        path.lineTo(12 * u, 4 * u)
        path.lineTo(20.5 * u, 11 * u)
        p.drawPath(path)
        body = QPainterPath()
        body.moveTo(5.5 * u, 9.5 * u)
        body.lineTo(5.5 * u, 19.5 * u)
        body.lineTo(18.5 * u, 19.5 * u)
        body.lineTo(18.5 * u, 9.5 * u)
        p.drawPath(body)
        p.drawLine(QPointF(10 * u, 19.5 * u), QPointF(10 * u, 14 * u))
        p.drawLine(QPointF(14 * u, 19.5 * u), QPointF(14 * u, 14 * u))
        p.drawLine(QPointF(10 * u, 14 * u), QPointF(14 * u, 14 * u))
    elif name == "chat":
        p.drawRoundedRect(QRectF(3.5 * u, 4.5 * u, 17 * u, 12 * u), 3.5 * u, 3.5 * u)
        tail = QPainterPath()
        tail.moveTo(8 * u, 16.5 * u)
        tail.lineTo(8 * u, 20.5 * u)
        tail.lineTo(12.5 * u, 16.5 * u)
        p.drawPath(tail)
        for x in (8.5, 12, 15.5):
            p.drawPoint(QPointF(x * u, 10.5 * u))
    elif name == "apps":
        for x in (4.5, 13.5):
            for y in (4.5, 13.5):
                p.drawRoundedRect(QRectF(x * u, y * u, 6 * u, 6 * u), 1.8 * u, 1.8 * u)
    elif name == "memory":
        # stacked discs: local storage
        p.drawEllipse(QRectF(4.5 * u, 3.8 * u, 15 * u, 4.4 * u))  # top disc
        p.drawLine(QPointF(4.5 * u, 6 * u), QPointF(4.5 * u, 18 * u))
        p.drawLine(QPointF(19.5 * u, 6 * u), QPointF(19.5 * u, 18 * u))
        for y in (12, 18):
            arc = QPainterPath()
            arc.moveTo(4.5 * u, (y - 0.0) * u)
            arc.arcTo(QRectF(4.5 * u, (y - 2.2) * u, 15 * u, 4.4 * u), 180, 180)
            p.drawPath(arc)
    elif name == "settings":
        for y, knob in ((6.5, 8.5), (12, 15.5), (17.5, 10)):
            p.drawLine(QPointF(4 * u, y * u), QPointF(20 * u, y * u))
            p.setBrush(p.pen().color().darker(300))
            p.drawEllipse(QPointF(knob * u, y * u), 2.2 * u, 2.2 * u)
            p.setBrush(Qt.NoBrush)
    elif name == "mic":
        p.drawRoundedRect(QRectF(9 * u, 3 * u, 6 * u, 11 * u), 3 * u, 3 * u)
        arc = QPainterPath()
        arc.moveTo(5.5 * u, 11 * u)
        arc.arcTo(QRectF(5.5 * u, 6 * u, 13 * u, 12 * u), 180, 180)
        p.drawPath(arc)
        p.drawLine(QPointF(12 * u, 18 * u), QPointF(12 * u, 21 * u))
        p.drawLine(QPointF(8.5 * u, 21 * u), QPointF(15.5 * u, 21 * u))


def pixmap(name: str, color: str, size: int = 22, dpr: float = 2.0) -> QPixmap:
    px = QPixmap(int(size * dpr), int(size * dpr))
    px.setDevicePixelRatio(dpr)
    px.fill(Qt.transparent)
    p = QPainter(px)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(QPen(QColor(color), size * 0.085, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    _draw(name, p, size)
    p.end()
    return px


def nav_icon(name: str) -> QIcon:
    """Muted when unselected, emerald when the (checkable) button is checked."""
    icon = QIcon()
    icon.addPixmap(pixmap(name, theme.MUTED), QIcon.Normal, QIcon.Off)
    icon.addPixmap(pixmap(name, theme.GREEN), QIcon.Normal, QIcon.On)
    icon.addPixmap(pixmap(name, theme.MUTED), QIcon.Disabled, QIcon.Off)
    return icon


ICON_SIZE = QSize(22, 22)
