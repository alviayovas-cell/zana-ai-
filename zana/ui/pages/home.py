"""Home page: greeting, animated orb, status, microphone, suggestions and system status."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget,
)

from .. import theme
from ..mic_button import MicButton
from ..status_pill import _Dot
from ..system_status import SystemStatus
from ..visualizer import VoiceVisualizer

# Things Zana can really do today; clicking one runs it just as if you had typed it.
SUGGESTIONS = (
    ("Open an app", "open Notepad", "open Notepad"),
    ("Ask anything", "tell me a fun fact", "tell me a fun fact"),
    ("Open WhatsApp", "open WhatsApp", "open WhatsApp"),
)


class HomePage(QWidget):
    mic_toggled = Signal(bool)
    suggestion_clicked = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(40, 30, 40, 24)
        layout.setSpacing(6)

        self.greeting = QLabel("What can I do for you today?")
        self.greeting.setObjectName("greeting")
        self.greeting.setAlignment(Qt.AlignCenter)
        sub = QLabel("Say “Hey Zana” and a command, or press the microphone. Try one of these:")
        sub.setObjectName("pageSub")
        sub.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.greeting)
        layout.addWidget(sub)

        self.visualizer = VoiceVisualizer()
        layout.addWidget(self.visualizer, 1)

        self.status = QLabel("")
        self.status.setObjectName("homeStatus")
        self.status.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.status)

        # microphone button with a small listening indicator beside it
        row = QHBoxLayout()
        row.setSpacing(16)
        row.addStretch(1)
        self.mic = MicButton(68)
        self.mic.toggled.connect(self.mic_toggled)
        row.addWidget(self.mic)
        self._ind_dot = _Dot()
        self._ind_text = QLabel("Microphone off")
        self._ind_text.setStyleSheet(f"font-size: 12px; color: {theme.MUTED};")
        ind = QHBoxLayout()
        ind.setSpacing(7)
        ind.addWidget(self._ind_dot, 0, Qt.AlignVCenter)
        ind.addWidget(self._ind_text)
        row.addLayout(ind)
        row.addStretch(1)
        layout.addLayout(row)
        layout.addSpacing(8)

        # suggested commands
        sug = QHBoxLayout()
        sug.setSpacing(12)
        self.suggestion_buttons: list[QPushButton] = []
        for title, shown, command in SUGGESTIONS:
            b = QPushButton(f"{title}\n“{shown}”")
            b.setObjectName("suggestion")
            b.setCursor(Qt.PointingHandCursor)
            b.setToolTip(f"Runs: {command}")
            b.clicked.connect(lambda _=False, c=command: self.suggestion_clicked.emit(c))
            sug.addWidget(b, 1)
            self.suggestion_buttons.append(b)
        layout.addLayout(sug)
        layout.addSpacing(4)

        self.system_status = SystemStatus()
        layout.addWidget(self.system_status)

    def set_status(self, text: str) -> None:
        self.status.setText(text)

    def set_mic_indicator(self, level: str, text: str) -> None:
        color = {"ok": theme.GREEN, "warn": theme.WARN, "error": theme.DANGER}.get(level, theme.MUTED)
        self._ind_dot.color = QColor(color)
        self._ind_dot.update()
        self._ind_text.setText(text)
        self._ind_text.setStyleSheet(f"font-size: 12px; color: {theme.MINT if level == 'ok' else theme.MUTED};")
