"""Round microphone toggle with an emerald glow (and a soft pulse while active)."""

import math

from PySide6.QtCore import QElapsedTimer, QPointF, QSize, Qt, QTimer
from PySide6.QtGui import QBrush, QColor, QLinearGradient, QPainter, QPen, QRadialGradient
from PySide6.QtWidgets import QAbstractButton

from . import icons, theme


class MicButton(QAbstractButton):
    def __init__(self, diameter: int = 64, parent=None):
        super().__init__(parent)
        self._d = diameter
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(diameter, diameter)
        self.setToolTip("Talk to Zana (push to talk)")
        self._clock = QElapsedTimer()
        self._clock.start()
        self._pulse = QTimer(self)
        self._pulse.setInterval(50)
        self._pulse.timeout.connect(self.update)
        self.toggled.connect(self._on_toggled)

    def sizeHint(self) -> QSize:
        return QSize(self._d, self._d)

    def _on_toggled(self, on: bool) -> None:
        self._pulse.start() if on else self._pulse.stop()
        self.update()

    def setChecked(self, checked: bool) -> None:  # also handles blockSignals(True) callers
        super().setChecked(checked)
        if checked and not self._pulse.isActive():
            self._pulse.start()
        elif not checked:
            self._pulse.stop()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        c = QPointF(self.width() / 2, self.height() / 2)
        half = self.width() / 2
        r = half - 6
        active = self.isChecked()
        hover = self.underMouse()
        t = self._clock.elapsed() / 1000.0
        breathe = 0.5 + 0.5 * math.sin(t * 4.0) if active else 0.0

        # soft outer glow (always faint, stronger on hover / when listening)
        strength = 0.55 + 0.35 * breathe if active else (0.30 if hover else 0.14)
        glow = QRadialGradient(c, half)
        g = QColor(theme.GREEN)
        g.setAlphaF(strength * 0.55)
        glow.setColorAt(0.55, g)
        g2 = QColor(theme.GREEN)
        g2.setAlpha(0)
        glow.setColorAt(1.0, g2)
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(glow))
        p.drawEllipse(c, half, half)

        grad = QLinearGradient(0, 0, self.width(), self.height())
        if active:
            grad.setColorAt(0, QColor(theme.GLOW))
            grad.setColorAt(1, QColor("#00B97A"))
        else:
            grad.setColorAt(0, QColor(theme.CARD))
            grad.setColorAt(1, QColor(theme.BG2))
        edge = QColor(theme.MINT if active else (theme.GREEN if hover else theme.BORDER))
        p.setPen(QPen(edge, 1.5))
        p.setBrush(QBrush(grad))
        p.drawEllipse(c, r, r)

        isz = int(r * 1.0)
        color = "#03120B" if active else (theme.MINT if hover else theme.GREEN)
        px = icons.pixmap("mic", color, isz)
        p.drawPixmap(int(c.x() - isz / 2), int(c.y() - isz / 2), px)
        p.end()

    def enterEvent(self, event) -> None:
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self.update()
        super().leaveEvent(event)
