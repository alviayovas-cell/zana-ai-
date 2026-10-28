"""Page shown for sections that are built in a later phase."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget


class PlaceholderPage(QWidget):
    def __init__(self, title: str, description: str, phase: str, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 28, 32, 28)
        head = QLabel(title)
        head.setObjectName("pageTitle")
        sub = QLabel(description)
        sub.setObjectName("pageSub")
        sub.setWordWrap(True)
        layout.addWidget(head)
        layout.addWidget(sub)
        layout.addStretch(1)
        note = QLabel(f"Not implemented yet — planned for {phase}.")
        note.setObjectName("statusLabel")
        note.setAlignment(Qt.AlignCenter)
        layout.addWidget(note)
        layout.addStretch(2)
