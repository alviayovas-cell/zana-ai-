"""System tray icon: open Zana, see listening status, exit completely."""

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import QMenu, QSystemTrayIcon


def tray_available() -> bool:
    return QSystemTrayIcon.isSystemTrayAvailable()


class TrayController(QObject):
    open_requested = Signal()
    exit_requested = Signal()
    pause_toggled = Signal()

    def __init__(self, icon: QIcon, parent=None):
        super().__init__(parent)
        self._tray = QSystemTrayIcon(icon, self)
        self._tray.setToolTip("Zana")
        self._menu = QMenu()
        open_action = QAction("Open Zana", self._menu)
        open_action.triggered.connect(self.open_requested)
        self._status = QAction("Microphone off", self._menu)
        self._status.setEnabled(False)
        self._pause = QAction("Pause listening", self._menu)
        self._pause.setEnabled(False)
        self._pause.triggered.connect(self.pause_toggled)
        exit_action = QAction("Exit Zana", self._menu)
        exit_action.triggered.connect(self.exit_requested)
        self._menu.addAction(open_action)
        self._menu.addAction(self._status)
        self._menu.addAction(self._pause)
        self._menu.addSeparator()
        self._menu.addAction(exit_action)
        self._tray.setContextMenu(self._menu)
        self._tray.activated.connect(self._on_activated)

    def _on_activated(self, reason) -> None:
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            self.open_requested.emit()

    def show(self) -> None:
        self._tray.show()

    def hide(self) -> None:
        self._tray.hide()

    def set_status(self, text: str) -> None:
        self._status.setText(text)
        self._tray.setToolTip(f"Zana — {text}")

    def set_pause_state(self, available: bool, paused: bool) -> None:
        """Pause/Resume is only offered while hands-free listening is switched on."""
        self._pause.setEnabled(available)
        self._pause.setText("Resume listening" if paused else "Pause listening")

    def notify(self, title: str, message: str) -> None:
        if self._tray.isVisible():
            self._tray.showMessage(title, message, QSystemTrayIcon.Information, 5000)
