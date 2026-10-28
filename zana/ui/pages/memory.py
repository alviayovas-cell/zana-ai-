"""Memory page: browse and delete locally stored conversations."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMessageBox,
    QPushButton, QTextBrowser, QVBoxLayout, QWidget,
)

from ...storage.history import HistoryStore


class MemoryPage(QWidget):
    def __init__(self, store: HistoryStore, parent=None):
        super().__init__(parent)
        self._store = store
        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 28, 32, 28)
        title = QLabel("Memory")
        title.setObjectName("pageTitle")
        sub = QLabel("Conversations are stored only on this PC.")
        sub.setObjectName("pageSub")
        layout.addWidget(title)
        layout.addWidget(sub)

        body = QHBoxLayout()
        self.list = QListWidget()
        self.list.setFixedWidth(280)
        self.view = QTextBrowser()
        body.addWidget(self.list)
        body.addWidget(self.view, 1)
        layout.addLayout(body, 1)

        row = QHBoxLayout()
        self.delete_button = QPushButton("Delete conversation")
        self.clear_button = QPushButton("Clear all")
        for b in (self.delete_button, self.clear_button):
            b.setCursor(Qt.PointingHandCursor)
            row.addWidget(b)
        row.addStretch(1)
        layout.addLayout(row)

        self.list.currentItemChanged.connect(self._show_selected)
        self.delete_button.clicked.connect(self._delete_selected)
        self.clear_button.clicked.connect(self._clear_all)
        self.refresh()

    def refresh(self) -> None:
        self.list.clear()
        self.view.clear()
        for c in self._store.list_conversations():
            item = QListWidgetItem(f"{c['title']}\n{c['updated_at'][:16].replace('T', ' ')}")
            item.setData(Qt.UserRole, c["id"])
            self.list.addItem(item)
        has = self.list.count() > 0
        self.delete_button.setEnabled(has)
        self.clear_button.setEnabled(has)
        if not has:
            self.view.setPlainText("No saved conversations yet.")

    def _show_selected(self, current, _previous) -> None:
        if current is None:
            return
        msgs = self._store.get_messages(current.data(Qt.UserRole))
        lines = [f"{'You' if m['role'] == 'user' else 'Zana'}: {m['content']}" for m in msgs]
        self.view.setPlainText("\n\n".join(lines))

    def _confirm(self, text: str) -> bool:
        return QMessageBox.question(self, "Zana", text) == QMessageBox.Yes

    def _delete_selected(self) -> None:
        item = self.list.currentItem()
        if item is not None and self._confirm("Delete this conversation?"):
            self._store.delete_conversation(item.data(Qt.UserRole))
            self.refresh()

    def _clear_all(self) -> None:
        if self._confirm("Delete ALL saved conversations? This cannot be undone."):
            self._store.clear_all()
            self.refresh()
