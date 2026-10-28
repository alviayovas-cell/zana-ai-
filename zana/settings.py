"""User-editable settings persisted as JSON in the local data directory."""

import json
import os
from dataclasses import asdict, dataclass, fields
from pathlib import Path


@dataclass
class UserSettings:
    # Off by default: the microphone is never opened until the user opts in.
    wake_enabled: bool = False
    speak_replies: bool = True
    # Off by default: Zana never starts with Windows or stays running after the
    # window is closed unless the user asks for it (Settings, or the first-run offer).
    launch_at_startup: bool = False
    close_to_tray: bool = False
    # After a reply, keep listening this many seconds without needing "Hey Zana"
    # again. 0 disables follow-ups (the wake phrase is needed for every command).
    follow_up_seconds: int = 8
    # The one-time "make Zana hands-free?" offer has been shown.
    onboarding_done: bool = False

    @classmethod
    def load(cls, path: Path) -> "UserSettings":
        try:
            raw = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return cls()
        if not isinstance(raw, dict):
            return cls()
        defaults = cls()
        clean = {}
        for f in fields(cls):
            value = raw.get(f.name)
            want = type(getattr(defaults, f.name))
            if isinstance(value, bool) == (want is bool) and isinstance(value, want):
                clean[f.name] = value
        if "follow_up_seconds" in clean:
            clean["follow_up_seconds"] = max(0, min(60, clean["follow_up_seconds"]))
        return cls(**clean)

    def save(self, path: Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")
        os.replace(tmp, path)
