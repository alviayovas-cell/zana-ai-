"""Small microphone/listening status indicator (glowing dot + text)."""

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QHBoxLayout, QLabel, QWidget

from ..voice.engine import VoiceState
from . import theme

_STYLE = {
    VoiceState.OFF: (theme.MUTED, "Microphone off"),
    VoiceState.STARTING: (theme.WARN, "Starting…"),
    VoiceState.WAITING: (theme.GREEN, "Listening for “Hey Zana”"),
    VoiceState.LISTENING: (theme.GLOW, "Listening to you…"),
    VoiceState.TRANSCRIBING: (theme.MINT, "Processing…"),
    VoiceState.BUSY: (theme.MINT, "Processing…"),
    VoiceState.SPEAKING: (theme.GREEN, "Speaking…"),
    VoiceState.PAUSED: (theme.WARN, "Paused"),
    VoiceState.ERROR: (theme.DANGER, "Microphone problem"),
}


class _Dot(QWidget):
    def __init__(self):
        super().__init__()
        self.setFixedSize(16, 16)
        self.color = QColor(theme.MUTED)

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        glow = QColor(self.color)
        glow.setAlpha(60)
        p.setPen(Qt.NoPen)
        p.setBrush(glow)
        p.drawEllipse(QPointF(8, 8), 8, 8)
        p.setBrush(self.color)
        p.drawEllipse(QPointF(8, 8), 4, 4)
        p.end()


class StatusPill(QWidget):
    def __init__(self, parent=None, large: bool = False):
        super().__init__(parent)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(9)
        self._dot = _Dot()
        self._label = QLabel("")
        self._label.setObjectName("bannerText" if large else "brandSub")
        self._label.setWordWrap(True)
        row.addWidget(self._dot, 0, Qt.AlignVCenter)
        row.addWidget(self._label, 1)
        self.state = VoiceState.OFF
        self.set_state(VoiceState.OFF, "")

    def set_state(self, state: VoiceState, detail: str = "") -> None:
        self.state = state
        color, text = _STYLE[state]
        self._dot.color = QColor(color)
        self._dot.update()
        self._label.setText(text)
        self.setToolTip(detail or text)

    def text(self) -> str:
        return self._label.text()
