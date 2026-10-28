"""Compact system status (Ollama, microphone, Whisper, Piper) for the Home screen."""

from __future__ import annotations

import threading
from typing import Callable

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from ..core.ollama_client import OllamaClient, OllamaError
from . import theme
from .status_pill import _Dot

_LEVEL_COLOR = {"ok": theme.GREEN, "warn": theme.WARN, "error": theme.DANGER, "off": theme.MUTED}
ITEMS = (("ollama", "Ollama"), ("microphone", "Microphone"), ("whisper", "Whisper"), ("piper", "Piper"))


class _Chip(QFrame):
    def __init__(self, title: str):
        super().__init__()
        self.setObjectName("card")
        row = QHBoxLayout(self)
        row.setContentsMargins(14, 9, 14, 9)
        row.setSpacing(9)
        self.dot = _Dot()
        col = QVBoxLayout()
        col.setSpacing(0)
        self.title = QLabel(title)
        self.title.setStyleSheet(f"font-size: 12px; font-weight: 600; color: {theme.TEXT};")
        self.state = QLabel("Checking…")
        self.state.setStyleSheet(f"font-size: 11px; color: {theme.MUTED};")
        col.addWidget(self.title)
        col.addWidget(self.state)
        row.addWidget(self.dot, 0, Qt.AlignVCenter)
        row.addLayout(col, 1)

    def set(self, level: str, text: str) -> None:
        self.dot.color = QColor(_LEVEL_COLOR.get(level, theme.MUTED))
        self.dot.update()
        self.state.setText(text)
        self.setToolTip(f"{self.title.text()}: {text}")


class SystemStatus(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(10)
        self._chips = {key: _Chip(title) for key, title in ITEMS}
        for chip in self._chips.values():
            row.addWidget(chip, 1)

    def set_item(self, key: str, level: str, text: str) -> None:
        self._chips[key].set(level, text)

    def item_text(self, key: str) -> str:
        return self._chips[key].state.text()

    def update_from(self, status: dict) -> None:
        for key, (level, text) in status.items():
            if key in self._chips:
                self.set_item(key, level, text)


def probe_system(client: OllamaClient, whisper_dir, piper_path) -> dict:
    """Real checks: is Ollama up with our model, and are the voice models on disk?"""
    from pathlib import Path

    out: dict = {}
    try:
        models = client.list_models()
        out["ollama"] = ("ok", "Ready") if client.model in models else \
            ("warn", f"Model {client.model} not pulled")
    except (OllamaError, ValueError):
        out["ollama"] = ("error", "Not running")
    out["whisper"] = ("ok", "Ready") if (Path(whisper_dir) / "model.bin").is_file() \
        else ("error", "Model missing")
    out["piper"] = ("ok", "Ready") if Path(piper_path).is_file() else ("error", "Voice missing")
    return out


class StatusPoller(QObject):
    """Runs a probe on a background thread and delivers the result on the UI thread."""

    result = Signal(object)

    def __init__(self, probe: Callable[[], dict], parent=None):
        super().__init__(parent)
        self._probe = probe
        self._busy = False

    def refresh(self) -> None:
        if self._busy:
            return
        self._busy = True

        def run() -> None:
            try:
                data = self._probe()
            except Exception:
                data = {}
            finally:
                self._busy = False
            try:
                self.result.emit(data)
            except RuntimeError:
                pass  # the window was closed while the probe ran

        threading.Thread(target=run, name="zana-status", daemon=True).start()
