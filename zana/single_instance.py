"""Prevent duplicate Zana instances; a second launch just wakes the first."""

import getpass
import os

from PySide6.QtCore import QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket


def default_name() -> str:
    override = os.environ.get("ZANA_INSTANCE_NAME")  # lets tests run beside a real Zana
    if override:
        return override
    try:
        user = getpass.getuser()
    except Exception:
        user = "user"
    return f"ZanaVoiceAssistant-{user}"


class SingleInstance(QObject):
    """``acquire()`` is True for the first instance. Later ones return False after
    asking the first to show its window (``activated`` is emitted there)."""

    activated = Signal()

    def __init__(self, name: str | None = None, parent=None):
        super().__init__(parent)
        self._name = name or default_name()
        self._server: QLocalServer | None = None

    def acquire(self, timeout_ms: int = 500) -> bool:
        sock = QLocalSocket()
        sock.connectToServer(self._name)
        if sock.waitForConnected(timeout_ms):
            sock.write(b"show")
            sock.waitForBytesWritten(timeout_ms)
            sock.disconnectFromServer()
            return False
        QLocalServer.removeServer(self._name)  # stale pipe from a crashed run
        server = QLocalServer(self)
        if not server.listen(self._name):
            return True  # can't guard (rare); better to run than to refuse
        server.newConnection.connect(self._on_connection)
        self._server = server
        return True

    def _on_connection(self) -> None:
        while self._server is not None and self._server.hasPendingConnections():
            conn = self._server.nextPendingConnection()
            conn.waitForReadyRead(200)
            conn.readAll()
            conn.disconnectFromServer()
            self.activated.emit()

    def release(self) -> None:
        if self._server is not None:
            self._server.close()
            self._server = None
