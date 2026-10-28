"""Applications page: approved apps you can launch, add to or remove from."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFileDialog, QFrame, QHBoxLayout, QInputDialog, QLabel, QMessageBox, QPushButton,
    QScrollArea, QVBoxLayout, QWidget,
)

from ...apps.registry import AppError, AppRegistry


class ApplicationsPage(QWidget):
    launched = Signal(str)
    close_requested = Signal(str)   # app name; the main window runs the safe close flow

    def __init__(self, registry: AppRegistry, finder=None, parent=None):
        super().__init__(parent)
        self.registry = registry
        self._finder = finder
        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 28, 32, 28)
        layout.setSpacing(12)

        head = QHBoxLayout()
        title = QLabel("Applications")
        title.setObjectName("pageTitle")
        head.addWidget(title)
        head.addStretch(1)
        self.find_button = QPushButton("Find installed app…")
        self.find_button.setCursor(Qt.PointingHandCursor)
        self.find_button.clicked.connect(self._find_installed)
        head.addWidget(self.find_button)
        self.add_button = QPushButton("Add .exe…")
        self.add_button.setCursor(Qt.PointingHandCursor)
        self.add_button.clicked.connect(self._choose_and_add)
        head.addWidget(self.add_button)
        layout.addLayout(head)

        sub = QLabel("Zana can only open the apps listed here. Say “Hey Zana, open notepad” "
                     "or type “open notepad” in chat.")
        sub.setObjectName("pageSub")
        sub.setWordWrap(True)
        layout.addWidget(sub)

        scroll = QScrollArea()
        scroll.setObjectName("chatScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        self._holder = QWidget()
        self._rows = QVBoxLayout(self._holder)
        self._rows.setContentsMargins(0, 0, 0, 0)
        self._rows.setSpacing(10)
        scroll.setWidget(self._holder)
        layout.addWidget(scroll, 1)

        self.status = QLabel("")
        self.status.setObjectName("statusLabel")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.refresh()

    def refresh(self) -> None:
        while self._rows.count():
            item = self._rows.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        self.launch_buttons: dict[str, QPushButton] = {}
        self.close_buttons: dict[str, QPushButton] = {}
        for app in self.registry.list():
            card = QFrame()
            card.setObjectName("card")
            row = QHBoxLayout(card)
            row.setContentsMargins(18, 14, 18, 14)
            text = QVBoxLayout()
            name = QLabel(app.name)
            name.setStyleSheet("font-size: 15px; font-weight: 600;")
            detail = QLabel("Built-in" if app.builtin else app.path)
            detail.setObjectName("pageSub")
            text.addWidget(name)
            text.addWidget(detail)
            row.addLayout(text, 1)
            if not app.builtin:
                remove = QPushButton("Remove")
                remove.setCursor(Qt.PointingHandCursor)
                remove.clicked.connect(lambda _=False, a=app: self._remove(a.id))
                row.addWidget(remove)
            close_btn = QPushButton("Close")
            close_btn.setCursor(Qt.PointingHandCursor)
            close_btn.setToolTip(f"Ask {app.name} to close (Zana asks before force-closing anything)")
            close_btn.clicked.connect(lambda _=False, a=app: self.close_requested.emit(a.name))
            row.addWidget(close_btn)
            self.close_buttons[app.id] = close_btn
            btn = QPushButton("Launch")
            btn.setObjectName("sendButton")
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(lambda _=False, a=app: self.launch(a.id))
            row.addWidget(btn)
            self.launch_buttons[app.id] = btn
            self._rows.addWidget(card)
        self._rows.addStretch(1)

    def launch(self, app_id: str) -> None:
        try:
            entry = self.registry.launch(app_id)
        except AppError as e:
            self.status.setText(f"⚠ {e}")
            return
        self.status.setText(f"Opened {entry.name}.")
        self.launched.emit(entry.name)

    def add_app(self, path: str, name: str | None = None) -> bool:
        try:
            entry = self.registry.add_user_app(path, name)
        except AppError as e:
            self.status.setText(f"⚠ {e}")
            return False
        self.status.setText(f"Added {entry.name}.")
        self.refresh()
        return True

    def suggest(self, query: str) -> list:
        """Installed apps matching a name (nothing is added yet)."""
        if self._finder is None:
            return []
        return [e for e in self._finder(query) if self.registry.find(e.name) is None]

    def approve(self, entry, confirm) -> bool:
        """Add a discovered app only if ``confirm(entry)`` says the user agreed."""
        if not confirm(entry):
            self.status.setText(f"Did not add {entry.name}.")
            return False
        try:
            added = self.registry.add_entry(entry)
        except AppError as e:
            self.status.setText(f"⚠ {e}")
            return False
        self.status.setText(f"Added {added.name}.")
        self.refresh()
        return True

    def _find_installed(self) -> None:
        query, ok = QInputDialog.getText(self, "Find installed app", "App name (e.g. WhatsApp):")
        if not ok or not query.strip():
            return
        found = self.suggest(query.strip())
        if not found:
            self.status.setText(f"No installed app matching “{query.strip()}” was found "
                                "(or it is already approved).")
            return
        names = [e.name for e in found]
        name, ok = QInputDialog.getItem(self, "Choose app", "Installed apps found:", names, 0, False)
        if ok:
            entry = found[names.index(name)]
            self.approve(entry, lambda e: QMessageBox.question(
                self, "Allow this app?",
                f"Allow Zana to open {e.name}?\n\nOnly approve apps you trust.") == QMessageBox.Yes)

    def _choose_and_add(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Choose an application", "", "Applications (*.exe)")
        if not path:
            return
        path = path.replace("/", "\\")
        ok = QMessageBox.question(
            self, "Allow this app?",
            f"Allow Zana to launch this program?\n\n{path}\n\n"
            "Only add programs you trust. Zana will start it with no arguments.",
        )
        if ok == QMessageBox.Yes:
            self.add_app(path)

    def _remove(self, app_id: str) -> None:
        try:
            self.registry.remove_user_app(app_id)
        except AppError as e:
            self.status.setText(f"⚠ {e}")
            return
        self.status.setText("Removed.")
        self.refresh()
