"""Modern animated toggle switch; a drop-in QCheckBox (same API and signals)."""

from PySide6.QtCore import Property, QEasingCurve, QPropertyAnimation, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import QCheckBox

from . import theme

_TRACK_W, _TRACK_H, _GAP = 42, 22, 12


class ToggleSwitch(QCheckBox):
    def __init__(self, text: str = "", parent=None):
        super().__init__(text, parent)
        self._knob = 0.0
        self._anim = QPropertyAnimation(self, b"knob", self)
        self._anim.setDuration(160)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(32)
        self.toggled.connect(self._on_toggled)

    # animated 0..1 position of the knob
    def _get_knob(self) -> float:
        return self._knob

    def _set_knob(self, v: float) -> None:
        self._knob = v
        self.update()

    knob = Property(float, _get_knob, _set_knob)

    def _on_toggled(self, on: bool) -> None:
        self._anim.stop()
        self._anim.setStartValue(self._knob)
        self._anim.setEndValue(1.0 if on else 0.0)
        self._anim.start()

    def setChecked(self, checked: bool) -> None:  # also covers blockSignals(True) updates
        super().setChecked(checked)
        if self._anim.state() != QPropertyAnimation.Running:
            self._knob = 1.0 if self.isChecked() else 0.0
            self.update()

    def sizeHint(self) -> QSize:
        w = _TRACK_W + (_GAP + QFontMetrics(self.font()).horizontalAdvance(self.text()) if self.text() else 0)
        return QSize(w + 4, max(32, _TRACK_H + 10))

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        on = self.isChecked() if self._anim.state() != QPropertyAnimation.Running else self._knob > 0.5
        t = self._knob if self._anim.state() == QPropertyAnimation.Running else (1.0 if on else 0.0)
        enabled = self.isEnabled()
        y = (self.height() - _TRACK_H) / 2
        track = QRectF(2, y, _TRACK_W, _TRACK_H)

        off_col, on_col = QColor(theme.CARD), QColor(theme.GREEN)
        on_col.setAlpha(int(70 + 90 * 1))  # dim emerald fill, never a flat bright block
        fill = QColor(
            int(off_col.red() + (on_col.red() - off_col.red()) * t),
            int(off_col.green() + (on_col.green() - off_col.green()) * t),
            int(off_col.blue() + (on_col.blue() - off_col.blue()) * t),
        )
        border = QColor(theme.GREEN if t > 0.5 else (theme.MUTED if self.underMouse() else theme.BORDER))
        if t > 0.01:  # soft glow when enabled
            glow = QColor(theme.GREEN)
            glow.setAlpha(int(55 * t))
            p.setPen(Qt.NoPen)
            p.setBrush(glow)
            p.drawRoundedRect(track.adjusted(-3, -3, 3, 3), _TRACK_H / 2 + 3, _TRACK_H / 2 + 3)
        p.setPen(QPen(border, 1.2))
        p.setBrush(fill if enabled else QColor(theme.BG2))
        p.drawRoundedRect(track, _TRACK_H / 2, _TRACK_H / 2)

        r = _TRACK_H / 2 - 4
        cx = track.left() + _TRACK_H / 2 + (_TRACK_W - _TRACK_H) * t
        knob_col = QColor(theme.MINT if t > 0.5 else theme.MUTED)
        if not enabled:
            knob_col.setAlpha(110)
        p.setPen(Qt.NoPen)
        p.setBrush(knob_col)
        p.drawEllipse(QRectF(cx - r, track.center().y() - r, 2 * r, 2 * r))

        if self.text():
            p.setPen(QColor(theme.TEXT if enabled else theme.MUTED))
            p.setFont(self.font())
            p.drawText(QRectF(_TRACK_W + _GAP + 2, 0, self.width() - _TRACK_W - _GAP, self.height()),
                       Qt.AlignVCenter | Qt.AlignLeft, self.text())
        if self.hasFocus():
            p.setPen(QPen(QColor(theme.GREEN), 1, Qt.DotLine))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(self.rect().adjusted(0, 3, -1, -3), 8, 8)
        p.end()

    def enterEvent(self, e) -> None:
        self.update()
        super().enterEvent(e)

    def leaveEvent(self, e) -> None:
        self.update()
        super().leaveEvent(e)
