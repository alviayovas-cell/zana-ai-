"""Find and close the running processes of an *approved* app, safely.

Rules this module enforces (all covered by tests):
  * Only processes that positively match an approved allowlist entry are ever touched:
    by exe path, by Store package folder, or by the exe behind its Start-menu shortcut.
    A process whose path Windows won't reveal (elevated) is never matched or touched.
  * Closing is polite first (WM_CLOSE to the app's own windows). Force-closing is a
    separate, explicit step the caller may take only after the user confirmed it.
  * Windows system/shell processes, anything inside the Windows folder, security
    software, Zana itself (and its parents) and entries marked ``never_terminate``
    can be asked to close their windows but are never killed.
  * File Explorer closes folder windows only; explorer.exe (the desktop shell) is never killed.
"""

from __future__ import annotations

import os
import re
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from .processes import ProcessApi, ProcInfo, WindowInfo, WinProcessApi
from .registry import AppEntry, normalize, squash

PROTECTED_NAMES = frozenset({
    "system", "registry", "smss.exe", "csrss.exe", "wininit.exe", "winlogon.exe", "services.exe",
    "lsass.exe", "lsaiso.exe", "svchost.exe", "dwm.exe", "fontdrvhost.exe", "explorer.exe",
    "sihost.exe", "ctfmon.exe", "taskhostw.exe", "runtimebroker.exe", "applicationframehost.exe",
    "shellexperiencehost.exe", "startmenuexperiencehost.exe", "searchhost.exe", "searchapp.exe",
    "searchindexer.exe", "textinputhost.exe", "spoolsv.exe", "audiodg.exe", "conhost.exe",
    "lockapp.exe", "logonui.exe", "userinit.exe", "wmiprvse.exe", "dllhost.exe", "wudfhost.exe",
    "securityhealthservice.exe", "securityhealthsystray.exe", "msmpeng.exe", "nissrv.exe",
    "mpdefendercoreservice.exe", "sgrmbroker.exe", "memory compression", "vmmem", "dashost.exe",
})
SECURITY_HINTS = (
    "defender", "antivirus", "avast", "avg", "avira", "mcafee", "norton", "kaspersky", "bitdefender",
    "malwarebytes", "eset", "sophos", "trendmicro", "trend micro", "crowdstrike", "carbonblack",
    "sentinelone", "webroot", "f-secure", "panda security", "windowsdefender", "securityhealth",
)
_CORE_WINDOW = "Windows.UI.Core.CoreWindow"


@dataclass
class CloseOutcome:
    status: str                      # closed | not_running | choose | force | failed
    message: str
    entry: Optional[AppEntry] = None
    windows: list = field(default_factory=list)   # status "choose": windows to pick from
    pids: list = field(default_factory=list)      # status "force": processes that would be ended
    background: bool = False                      # status "force": the app only lives in the background


@dataclass
class Instances:
    procs: list
    windows: list
    blocked: list                    # same-named processes we may not inspect (elevated)


def _windir() -> str:
    return os.environ.get("SystemRoot", r"C:\Windows").lower().rstrip("\\")


def _under(path: str, root: str) -> bool:
    return path == root or path.startswith(root.rstrip("\\") + "\\")


def _trusted_image_location(path: str) -> bool:
    return _under(path, _windir()) or "\\windowsapps\\" in path


def _package_regex(pkg: str, publisher: str = "") -> "re.Pattern[str]":
    pub = re.escape(publisher.lower()) if publisher else r"[a-z0-9]+"
    return re.compile(r"\\windowsapps\\" + re.escape(pkg.lower()) + r"_[^\\]*__" + pub + r"\\")


def start_menu_target(entry: AppEntry) -> Optional[str]:
    """Exe behind the Start-menu shortcut named like the app (for plain AppIDs such as Chrome).

    The shortcut path travels in an environment variable, never inside the script text.
    """
    roots = [Path(os.environ.get("ProgramData", r"C:\ProgramData")) / "Microsoft/Windows/Start Menu/Programs",
             Path(os.environ.get("APPDATA", "")) / "Microsoft/Windows/Start Menu/Programs"]
    want = {normalize(entry.name), squash(entry.name)}
    for root in roots:
        if not root.is_dir():
            continue
        for dirpath, _dirs, files in os.walk(root):
            for f in files:
                if f.lower().endswith(".lnk") and (normalize(f[:-4]) in want or squash(f[:-4]) in want):
                    target = _lnk_target(os.path.join(dirpath, f))
                    if target and target.lower().endswith(".exe") and os.path.isfile(target):
                        return target
    return None


def _lnk_target(lnk: str) -> Optional[str]:
    script = "(New-Object -ComObject WScript.Shell).CreateShortcut($env:ZANA_LNK).TargetPath"
    try:
        out = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, text=True, timeout=15, shell=False, creationflags=0x08000000,
            env={**os.environ, "ZANA_LNK": lnk},
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None
    return out or None


class AppCloser:
    def __init__(self, api: Optional[ProcessApi] = None,
                 target_resolver: Callable[[AppEntry], Optional[str]] = start_menu_target,
                 wait_s: float = 5.0, poll_s: float = 0.2,
                 sleep: Callable[[float], None] = time.sleep,
                 clock: Callable[[], float] = time.monotonic):
        self.api = api or WinProcessApi()
        self._resolver = target_resolver
        self._wait_s = wait_s
        self._poll_s = poll_s
        self._sleep = sleep
        self._clock = clock
        self._targets: dict[str, Optional[str]] = {}

    # -- identification -------------------------------------------------------
    def _protected_pids(self, procs: list[ProcInfo]) -> set[int]:
        """Zana's own pid and every ancestor (never match, never touch)."""
        by_pid = {p.pid: p for p in procs}
        out, pid = set(), self.api.own_pid()
        while pid and pid not in out:
            out.add(pid)
            parent = by_pid.get(pid)
            pid = parent.ppid if parent else 0
        return out

    def _resolve(self, entry: AppEntry) -> str:
        if entry.id not in self._targets:
            self._targets[entry.id] = self._resolver(entry)
        return (self._targets[entry.id] or "").lower()

    def can_identify(self, entry: AppEntry) -> bool:
        return bool(entry.kind in ("exe", "uwp") or entry.match_images or entry.package)

    def _match(self, entry: AppEntry, procs: list[ProcInfo]) -> tuple[list[ProcInfo], list[ProcInfo]]:
        # Only Zana's own process is excluded from matching. Its parents (e.g. explorer.exe when
        # launched from the desktop) can still be found and closed politely; they are protected
        # from being killed by protection_reason() instead.
        own = {self.api.own_pid()}
        exe_path = entry.path.lower() if entry.kind == "exe" else ""
        pkg_re = None
        if entry.kind == "uwp" and "!" in entry.path:
            pkg, _, pub = entry.path.split("!", 1)[0].rpartition("_")
            pkg_re = _package_regex(pkg, pub) if pkg else None
        elif entry.package:
            pkg_re = _package_regex(entry.package)
        target = self._resolve(entry) if entry.kind == "uwp" and "!" not in entry.path else ""
        images = {i.lower() for i in entry.match_images}
        exe_name = os.path.basename(exe_path)
        matched, blocked = [], []
        for p in procs:
            if p.pid in own:
                continue
            path, name = p.path.lower(), p.name.lower()
            if not path:  # elevated / protected: we can neither verify nor touch it
                if name in images or (exe_name and name == exe_name):
                    blocked.append(p)
                continue
            if (exe_path and path == exe_path) or (target and path == target) \
                    or (pkg_re and pkg_re.search(path)) \
                    or (name in images and _trusted_image_location(path)):
                matched.append(p)
        return matched, blocked

    def _windows(self, entry: AppEntry, pids: set[int], wins: list[WindowInfo]) -> list[WindowInfo]:
        classes = set(entry.window_classes)
        framed = {pid for w in wins if w.cls == "ApplicationFrameWindow"
                  for pid in w.frame_pids if pid in pids}
        out = []
        for w in wins:
            if not (w.pid in pids or any(fp in pids for fp in w.frame_pids)):
                continue
            if classes:
                if w.cls not in classes:
                    continue
            else:
                if not w.title:
                    continue
                if w.cls == _CORE_WINDOW and w.pid in framed:
                    continue  # the frame window already represents this app
            out.append(w)
        return out

    def instances(self, entry: AppEntry) -> Instances:
        matched, blocked = self._match(entry, self.api.list_processes())
        pids = {p.pid for p in matched}
        wins = self._windows(entry, pids, self.api.list_windows()) if pids else []
        return Instances(matched, wins, blocked)

    # -- safety -----------------------------------------------------------------
    def protection_reason(self, entry: AppEntry, proc: ProcInfo, own: Optional[set] = None) -> Optional[str]:
        """Why this process must never be force-closed (None = allowed, after confirmation)."""
        name, path = proc.name.lower(), proc.path.lower()
        if own is None:
            own = self._protected_pids(self.api.list_processes())
        if proc.pid == self.api.own_pid():
            return "that is Zana itself"
        if entry.never_terminate:
            return f"{entry.name} can only be closed politely"
        if proc.pid in own:
            return "it started Zana"
        if name in PROTECTED_NAMES:
            return "it is a Windows system process"
        if any(h in name or h in path for h in SECURITY_HINTS):
            return "it is security software"
        if not path:
            return "Windows doesn't let me inspect it"
        if _under(path, _windir()):
            return "it is part of Windows"
        return None

    # -- closing ----------------------------------------------------------------
    def close(self, entry: AppEntry, hwnds: Optional[list] = None) -> CloseOutcome:
        name = entry.name
        if not self.can_identify(entry):
            return CloseOutcome("failed", f"I can't tell which window belongs to {name}, "
                                          "so please close it yourself.", entry)
        inst = self.instances(entry)
        if not inst.procs:
            if inst.blocked:
                return CloseOutcome("failed", f"{name} is running with administrator rights, "
                                              "so I can't close it.", entry)
            return CloseOutcome("not_running", f"{name} isn't running.", entry)
        wins = inst.windows
        if not wins:
            if entry.window_classes:
                return CloseOutcome("not_running", f"{name} has no open windows.", entry)
            return self._offer_force(entry, inst.procs,
                                     f"{name} is running in the background with no window to close.",
                                     background=True)
        if hwnds is None and len(wins) > 1:
            return CloseOutcome("choose", f"{name} has {len(wins)} windows open. Which should I close?",
                                entry, windows=wins)
        selected = wins if hwnds is None else [w for w in wins if w.hwnd in set(hwnds)]
        if not selected:
            return CloseOutcome("failed", f"Those {name} windows are already gone.", entry)
        everything = len(selected) == len(wins)
        for w in selected:
            self.api.post_close(w.hwnd)
        need_exit = everything and not entry.window_classes
        remaining, alive = self._wait(selected, inst.procs, need_exit)

        if not remaining and (not need_exit or not alive):
            what = (f"{name}" if everything and not entry.window_classes else
                    f"{len(selected)} {name} window{'s' if len(selected) != 1 else ''}")
            return CloseOutcome("closed", f"Closed {what}.", entry)
        if not remaining:  # windows are gone but the app lives on (tray / background)
            return self._offer_force(
                entry, alive, f"I closed {name}'s window, but it is still running in the background.",
                background=True, fallback_closed=True)
        # a window is still open: usually a "save changes?" prompt or a hung app
        if entry.window_classes:
            return CloseOutcome("failed", f"{name} didn't close. Please check for a prompt on screen.", entry)
        return self._offer_force(
            entry, alive, f"{name} didn't close (it may be asking you to save something).")

    def _offer_force(self, entry, procs, message, background=False, fallback_closed=False) -> CloseOutcome:
        own = self._protected_pids(self.api.list_processes())
        killable = [p for p in procs if self.protection_reason(entry, p, own) is None]
        if not killable:
            reasons = {self.protection_reason(entry, p, own) for p in procs} - {None}
            why = f" I can't force-close it ({'; '.join(sorted(reasons))})." if reasons else ""
            if fallback_closed:
                return CloseOutcome("closed", message + why, entry)
            return CloseOutcome("failed", message + why + " Please close it yourself.", entry)
        return CloseOutcome(
            "force", f"{message} Force-closing can lose unsaved work. Do you want me to force-close it?",
            entry, pids=[p.pid for p in killable], background=background)

    def _wait(self, selected, procs, need_exit):
        deadline = self._clock() + self._wait_s
        remaining, alive = list(selected), list(procs)
        while True:
            visible = {w.hwnd for w in self.api.list_windows()}
            remaining = [w for w in selected if w.hwnd in visible]
            identities = {(p.pid, p.created) for p in self.api.list_processes()}
            alive = [p for p in procs if (p.pid, p.created) in identities]
            if not remaining and (not need_exit or not alive):
                break
            if self._clock() >= deadline:
                break
            self._sleep(self._poll_s)
        return remaining, alive

    # -- force --------------------------------------------------------------------
    def force(self, entry: AppEntry) -> CloseOutcome:
        """Terminate the app's processes. Call only after the user confirmed."""
        name = entry.name
        inst = self.instances(entry)        # fresh match: never trust an old list of pids
        if not inst.procs:
            return CloseOutcome("closed", f"{name} isn't running any more.", entry)
        current = {p.pid: p for p in self.api.list_processes()}
        own = self._protected_pids(list(current.values()))
        killable, refused = [], []
        for p in inst.procs:
            why = self.protection_reason(entry, p, own)
            (refused if why else killable).append((p, why))
        if not killable:
            return CloseOutcome("failed", f"I won't force-close {name}: {refused[0][1]}.", entry)
        for p, _ in killable:
            if current.get(p.pid) == p:     # same pid, path and creation time: not a recycled pid
                self.api.terminate(p.pid)
        deadline = self._clock() + 3.0
        while True:
            identities = {(q.pid, q.created) for q in self.api.list_processes()}
            left = [p for p, _ in killable if (p.pid, p.created) in identities]
            if not left or self._clock() >= deadline:
                break
            self._sleep(self._poll_s)
        if left:
            return CloseOutcome("failed", f"I couldn't force-close {name}.", entry)
        note = f" (I left {len(refused)} protected process(es) alone.)" if refused else ""
        return CloseOutcome("closed", f"Force-closed {name}.{note}", entry)
