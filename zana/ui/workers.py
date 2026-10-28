"""Background threads so the UI never blocks on the model."""

import threading

from PySide6.QtCore import QThread, Signal

from ..core.assistant import Assistant
from ..core.ollama_client import OllamaError


class ChatWorker(QThread):
    token = Signal(str)
    failed = Signal(str)

    def __init__(self, assistant: Assistant, text: str, spoken: bool = False, parent=None):
        super().__init__(parent)
        self._assistant = assistant
        self._text = text
        self._spoken = spoken
        self._cancel = threading.Event()

    def cancel(self) -> None:
        self._cancel.set()

    def run(self) -> None:
        try:
            for chunk in self._assistant.reply_stream(self._text, self._cancel, self._spoken):
                self.token.emit(chunk)
        except OllamaError as e:
            self.failed.emit(str(e))
        except Exception as e:  # keep the UI alive on unexpected errors
            self.failed.emit(f"Unexpected error: {e}")


class AppTaskWorker(QThread):
    """Runs one app step (resolve a command, close windows, force-close) off the UI thread.

    Closing waits for the app to react and discovery queries Windows, so none of it may
    block the interface. ``fallback_on_error`` decides what a crash means: ``None`` (the
    first step: treat the text as ordinary chat) or an error reply (later steps).
    """

    resolved = Signal(object)  # AppCommandResult | None

    def __init__(self, fn, fallback_on_error: bool = False, parent=None):
        super().__init__(parent)
        self._fn = fn
        self._fallback = fallback_on_error

    def run(self) -> None:
        try:
            self.resolved.emit(self._fn())
        except Exception as e:
            from ..apps.registry import AppCommandResult
            self.resolved.emit(None if self._fallback else
                               AppCommandResult(f"Something went wrong with that app: {e}"))


class AppCommandWorker(QThread):
    """Resolves "open X" off the UI thread (discovery may query Windows for a second)."""

    resolved = Signal(object)  # AppCommandResult | None

    def __init__(self, handler, text: str, parent=None):
        super().__init__(parent)
        self._handler = handler
        self._text = text

    def run(self) -> None:
        try:
            self.resolved.emit(self._handler.handle_ex(self._text))
        except Exception:
            self.resolved.emit(None)  # fall back to normal chat
