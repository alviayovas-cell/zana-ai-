"""Find installed apps by name so the user can be asked to approve them.

Discovery only *suggests* candidates; nothing is launched or added until the
user approves in a dialog. The only command run is a fixed ``Get-StartApps``
query - user text is never passed to a shell.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import time
from pathlib import Path
from typing import Callable, Optional

from .registry import (
    AppEntry, AppError, _slug, canonical, name_is_blocked, normalize, squash, validate_aumid,
    validate_executable,
)

# Start-menu AppIDs for classic apps look like "{known-folder-GUID}\Vendor\app.exe".
_GUID_PATH_RE = re.compile(r"^(\{[0-9A-Fa-f-]{36}\})\\(.+)$")


def _known_folders() -> dict[str, str]:
    sysroot = os.environ.get("SystemRoot", r"C:\Windows")
    pf = os.environ.get("ProgramW6432") or os.environ.get("ProgramFiles", r"C:\Program Files")
    return {
        "{6D809377-6AF0-444B-8957-A3773F02200E}": pf,
        "{905E63B6-C1BF-494E-B29C-65B732D3D21A}": os.environ.get("ProgramFiles", pf),
        "{7C5A40EF-A0FB-4BFC-874A-C0F2E0B9FA8E}": os.environ.get("ProgramFiles(x86)", pf),
        "{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}": str(Path(sysroot) / "System32"),
        "{F38BF404-1D43-42F2-9305-67DE0B28FC23}": sysroot,
        "{F1B32785-6FBA-4FCF-9D55-7B8E7F157091}": os.environ.get("LOCALAPPDATA", ""),
    }

_CACHE_SECONDS = 300
_cache: tuple[float, list[tuple[str, str]]] | None = None
_NO_WINDOW = 0x08000000  # CREATE_NO_WINDOW


def list_start_apps() -> list[tuple[str, str]]:
    """(name, AppID) for every Start menu app, cached for a few minutes."""
    global _cache
    if _cache and time.monotonic() - _cache[0] < _CACHE_SECONDS:
        return _cache[1]
    try:
        out = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
             "Get-StartApps | Select-Object Name,AppID | ConvertTo-Json -Compress"],
            capture_output=True, text=True, timeout=20, creationflags=_NO_WINDOW, shell=False,
        ).stdout
        data = json.loads(out) if out.strip() else []
    except (OSError, subprocess.SubprocessError, ValueError):
        return []
    if isinstance(data, dict):
        data = [data]
    apps = [(str(d.get("Name", "")), str(d.get("AppID", ""))) for d in data if isinstance(d, dict)]
    _cache = (time.monotonic(), apps)
    return apps


def _to_entry(name: str, app_id: str) -> Optional[AppEntry]:
    if not name or name_is_blocked(name):
        return None
    try:
        return AppEntry(_slug(name), name, validate_aumid(app_id), "uwp")
    except AppError:
        pass
    candidate = app_id
    m = _GUID_PATH_RE.match(app_id)
    if m:  # "{known-folder-GUID}\Vendor\app.exe" -> real path
        base = _known_folders().get(m.group(1).upper())
        if not base:
            return None
        candidate = str(Path(base) / m.group(2))
    try:  # classic desktop apps launched by their exe path
        return AppEntry(_slug(name), name, str(validate_executable(candidate)), "exe")
    except AppError:
        return None


def find_candidates(query: str, lister: Callable[[], list[tuple[str, str]]] = list_start_apps,
                    limit: int = 5) -> list[AppEntry]:
    q = canonical(query)
    if len(q) < 3:
        return []
    qs = squash(q)
    found: list[tuple[int, AppEntry]] = []
    for name, app_id in lister():
        n = normalize(name)
        ns = n.replace(" ", "")
        if q == n or qs == ns:
            rank = 0
        elif q in n.split():
            rank = 1
        elif q in n or qs in ns:
            rank = 2
        else:
            continue
        entry = _to_entry(name, app_id)
        if entry is not None:
            found.append((rank * 1000 + len(n), entry))
    found.sort(key=lambda t: t[0])
    seen, out = set(), []
    for _, e in found:
        if e.id not in seen:
            seen.add(e.id)
            out.append(e)
    return out[:limit]
