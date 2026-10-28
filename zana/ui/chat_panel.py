"""Chat panel: scrolling message list plus text input and mic button."""

import html
import re

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, Qt, QTimer, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QGraphicsDropShadowEffect, QGraphicsOpacityEffect, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

from . import theme
from .mic_button import MicButton

_BOLD = re.compile(r"\*\*(.+?)\*\*", re.S)
_CODE = re.compile(r"`([^`\n]+)`")


def format_reply(text: str) -> str:
    """Escape the model's text and highlight **bold** / `code` in emerald (safe HTML)."""
    out = html.escape(text)
    out = _BOLD.sub(rf'<b style="color:{theme.MINT}">\1</b>', out)
    out = _CODE.sub(rf'<span style="color:{theme.GREEN};font-family:Consolas,monospace">\1</span>', out)
    return out.replace("\n", "<br>")


class ChatPanel(QWidget):
    message_submitted = Signal(str)
    mic_toggled = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(14)

        self._scroll = QScrollArea()
        self._scroll.setObjectName("chatScroll")
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QScrollArea.NoFrame)
        self._list = QWidget()
        self._list_layout = QVBoxLayout(self._list)
        self._list_layout.setContentsMargins(4, 4, 10, 4)
        self._list_layout.setSpacing(12)
        self._list_layout.addStretch(1)
        self._scroll.setWidget(self._list)
        outer.addWidget(self._scroll, 1)

        row = QHBoxLayout()
        row.setSpacing(12)
        self.mic = MicButton(48)
        self.mic.toggled.connect(self.mic_toggled)
        self.input = QLineEdit()
        self.input.setObjectName("chatInput")
        self.input.setPlaceholderText("Message Zana...")
        self.send_button = QPushButton("Send")
        self.send_button.setObjectName("sendButton")
        self.send_button.setCursor(Qt.PointingHandCursor)
        glow = QGraphicsDropShadowEffect(self.send_button)
        glow.setBlurRadius(26)
        glow.setOffset(0, 0)
        glow.setColor(QColor(theme.GREEN))
        self.send_button.setGraphicsEffect(glow)
        row.addWidget(self.mic)
        row.addWidget(self.input, 1)
        row.addWidget(self.send_button)
        outer.addLayout(row)

        self.input.returnPressed.connect(self._submit)
        self.send_button.clicked.connect(self._submit)
        self._scroll.verticalScrollBar().rangeChanged.connect(self._stick_to_bottom)
        self._animations: list[QPropertyAnimation] = []

    def _submit(self) -> None:
        text = self.input.text().strip()
        if not text:
            return
        self.input.clear()
        self.message_submitted.emit(text)

    def _stick_to_bottom(self, _min, maximum) -> None:
        QTimer.singleShot(0, lambda: self._scroll.verticalScrollBar().setValue(maximum))

    # -- messages -----------------------------------------------------------
    def render_text(self, label: QLabel, text: str) -> None:
        """Update a (possibly still streaming) assistant bubble."""
        label.setTextFormat(Qt.RichText)
        label.setText(format_reply(text))

    def _fade_in(self, widget: QWidget) -> None:
        if not self.isVisible():
            return
        effect = QGraphicsOpacityEffect(widget)
        effect.setOpacity(0.0)
        widget.setGraphicsEffect(effect)
        anim = QPropertyAnimation(effect, b"opacity", widget)
        anim.setDuration(260)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.OutCubic)

        def done() -> None:
            widget.setGraphicsEffect(None)  # crisp text once settled
            if anim in self._animations:
                self._animations.remove(anim)

        anim.finished.connect(done)
        self._animations.append(anim)
        anim.start()

    def add_message(self, role: str, text: str) -> QLabel:
        """role is 'user', 'assistant' or 'system'."""
        label = QLabel()
        label.setWordWrap(True)
        label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        label.setObjectName({"user": "bubbleUser", "assistant": "bubbleAssistant"}.get(role, "bubbleSystem"))
        if role == "assistant":
            self.render_text(label, text)
        else:
            label.setTextFormat(Qt.PlainText)
            label.setText(text)
        label.setMaximumWidth(640)

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        if role == "user":
            row.addStretch(1)
            row.addWidget(label)
        elif role == "assistant":
            row.addWidget(label)
            row.addStretch(1)
        else:
            label.setAlignment(Qt.AlignCenter)
            label.setMaximumWidth(16777215)
            row.addWidget(label, 1)
        self._list_layout.insertLayout(self._list_layout.count() - 1, row)
        self._fade_in(label)
        return label

    def set_busy(self, busy: bool) -> None:
        self.input.setEnabled(not busy)
        self.send_button.setEnabled(not busy)
        if not busy:
            self.input.setFocus()

    def clear(self) -> None:
        while self._list_layout.count() > 1:
            item = self._list_layout.takeAt(0)
            layout = item.layout()
            if layout is not None:
                while layout.count():
                    w = layout.takeAt(0).widget()
                    if w is not None:
                        w.deleteLater()
                layout.deleteLater()

    def message_count(self) -> int:
        return self._list_layout.count() - 1
