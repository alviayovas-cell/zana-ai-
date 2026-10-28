"""Left navigation sidebar."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup, QFrame, QLabel, QPushButton, QVBoxLayout, QWidget,
)

from . import icons
from .status_pill import StatusPill

PAGES = ("Home", "Chat", "Applications", "Memory", "Settings")
_ICON = {"Home": "home", "Chat": "chat", "Applications": "apps",
         "Memory": "memory", "Settings": "settings"}


class Sidebar(QFrame):
    page_selected = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("sidebar")
        self.setFixedWidth(224)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 30, 0, 20)
        layout.setSpacing(0)

        brand = QLabel("ZANA")
        brand.setObjectName("brand")
        sub = QLabel("VOICE ASSISTANT")
        sub.setObjectName("brandSub")
        for lab in (brand, sub):
            lab.setContentsMargins(26, 0, 0, 0)
            layout.addWidget(lab)
        layout.addSpacing(34)

        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._buttons: list[QPushButton] = []
        for i, name in enumerate(PAGES):
            btn = QPushButton(f"   {name}")
            btn.setObjectName("navButton")
            btn.setCheckable(True)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setIcon(icons.nav_icon(_ICON[name]))
            btn.setIconSize(icons.ICON_SIZE)
            self._group.addButton(btn, i)
            self._buttons.append(btn)
            layout.addWidget(btn)
        layout.addStretch(1)

        pill_row = QWidget()
        pr = QVBoxLayout(pill_row)
        pr.setContentsMargins(26, 0, 14, 0)
        self.status_pill = StatusPill()
        pr.addWidget(self.status_pill)
        layout.addWidget(pill_row)
        layout.addSpacing(10)
        footer = QLabel("Local • Private")
        footer.setObjectName("brandSub")
        footer.setContentsMargins(26, 0, 0, 0)
        layout.addWidget(footer)

        self._group.idClicked.connect(self.page_selected.emit)
        self._buttons[0].setChecked(True)

    def select(self, index: int) -> None:
        self._buttons[index].setChecked(True)
