"""Central configuration. Everything is local; no API keys are used or stored."""

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path


def _data_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home())
    return Path(base) / "Zana"


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def resource_path(relative: str) -> Path:
    """Locate a bundled asset both from source and inside a PyInstaller build."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return base / relative


def _models_dir() -> Path:
    r"""Where the (large, never bundled) voice models live.

    Order: ZANA_MODELS_DIR, then - for the packaged app - ``models`` next to the
    exe, ``%LOCALAPPDATA%\Zana\models``, and the project's ``models`` folder when
    the build sits in ``<project>\dist\Zana``. From source: ``<project>\models``.
    """
    override = os.environ.get("ZANA_MODELS_DIR")
    if override:
        return Path(override)
    if is_frozen():
        exe_dir = Path(sys.executable).resolve().parent
        candidates = [exe_dir / "models", _data_dir() / "models", exe_dir.parent.parent / "models"]
        for c in candidates:
            if (c / "piper").is_dir() or (c / "whisper").is_dir():
                return c
        return _data_dir() / "models"
    return Path(__file__).resolve().parent.parent / "models"


@dataclass(frozen=True)
class Config:
    app_name: str = "Zana"
    ollama_url: str = field(
        default_factory=lambda: os.environ.get("ZANA_OLLAMA_URL", "http://localhost:11434")
    )
    ollama_model: str = field(
        default_factory=lambda: os.environ.get("ZANA_MODEL", "qwen3.5:4b")
    )
    data_dir: Path = field(default_factory=_data_dir)
    models_dir: Path = field(default_factory=_models_dir)
    whisper_model: str = "base.en"
    piper_voice: str = "en_US-lessac-medium"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "zana.db"

    @property
    def log_path(self) -> Path:
        return self.data_dir / "logs" / "zana.log"

    @property
    def apps_path(self) -> Path:
        return self.data_dir / "apps.json"

    @property
    def settings_path(self) -> Path:
        return self.data_dir / "settings.json"

    @property
    def whisper_dir(self) -> Path:
        return self.models_dir / "whisper" / self.whisper_model

    @property
    def piper_model_path(self) -> Path:
        return self.models_dir / "piper" / f"{self.piper_voice}.onnx"


CONFIG = Config()
