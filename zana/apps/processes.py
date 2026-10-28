"""Thin, dependency-free Windows process/window access (ctypes).

Only what closing an approved app needs: list processes with their executable path,
list visible top-level windows, politely ask a window to close (WM_CLOSE), and - only
after the caller got the user's confirmation - terminate a specific process.
"""

from __future__ import annotations

import ctypes
import os
from ctypes import wintypes
from dataclasses import dataclass
from typing import Optional, Protocol

WM_CLOSE = 0x0010
TH32CS_SNAPPROCESS = 0x2
PROCESS_TERMINATE = 0x0001
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
SYNCHRONIZE = 0x00100000
GW_OWNER = 4
GWL_EXSTYLE = -20
WS_EX_TOOLWINDOW = 0x00000080
INVALID_HANDLE = ctypes.c_void_p(-1).value


@dataclass(frozen=True)
class ProcInfo:
    pid: int
    ppid: int
    name: str           # image name, e.g. "Spotify.exe"
    path: str           # full path, or "" when Windows won't tell us (e.g. elevated process)
    created: int = 0    # process creation time (identity check against PID reuse)


@dataclass(frozen=True)
class WindowInfo:
    hwnd: int
    pid: int
    title: str
    cls: str
    frame_pids: tuple = ()   # for ApplicationFrameHost frames: pids of the apps hosted inside


class ProcessApi(Protocol):
    def list_processes(self) -> list[ProcInfo]: ...
    def list_windows(self) -> list[WindowInfo]: ...
    def post_close(self, hwnd: int) -> bool: ...
    def terminate(self, pid: int) -> bool: ...
    def own_pid(self) -> int: ...


class _PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD), ("th32DefaultHeapID", ctypes.c_size_t),
        ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", wintypes.LONG),
        ("dwFlags", wintypes.DWORD), ("szExeFile", wintypes.WCHAR * 260),
    ]


class WinProcessApi:
    """The real implementation; tests use a fake with the same methods."""

    def __init__(self):
        k = self._k = ctypes.WinDLL("kernel32", use_last_error=True)
        u = self._u = ctypes.WinDLL("user32", use_last_error=True)
        k.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
        k.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
        k.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(_PROCESSENTRY32W)]
        k.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(_PROCESSENTRY32W)]
        k.OpenProcess.restype = wintypes.HANDLE
        k.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        k.CloseHandle.argtypes = [wintypes.HANDLE]
        k.QueryFullProcessImageNameW.argtypes = [
            wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
        k.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
        k.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
        k.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        self._enum_proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        u.EnumWindows.argtypes = [self._enum_proc, wintypes.LPARAM]
        u.EnumChildWindows.argtypes = [wintypes.HWND, self._enum_proc, wintypes.LPARAM]
        u.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        u.IsWindowVisible.argtypes = [wintypes.HWND]
        u.IsWindow.argtypes = [wintypes.HWND]
        u.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        u.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        u.GetWindow.restype = wintypes.HWND
        u.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
        u.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
        u.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]

    # -- processes ----------------------------------------------------------
    def own_pid(self) -> int:
        return os.getpid()

    def _image_path_and_created(self, pid: int) -> tuple[str, int]:
        h = self._k.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not h:
            return "", 0  # protected/elevated process: we cannot (and must not) touch it
        try:
            buf = ctypes.create_unicode_buffer(1024)
            size = wintypes.DWORD(len(buf))
            path = buf.value if self._k.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)) else ""
            c, e, kt, ut = (wintypes.FILETIME() for _ in range(4))
            created = 0
            if self._k.GetProcessTimes(h, ctypes.byref(c), ctypes.byref(e), ctypes.byref(kt), ctypes.byref(ut)):
                created = (c.dwHighDateTime << 32) | c.dwLowDateTime
            return path, created
        finally:
            self._k.CloseHandle(h)

    def list_processes(self) -> list[ProcInfo]:
        snap = self._k.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
        if not snap or snap == INVALID_HANDLE:
            return []
        out: list[ProcInfo] = []
        try:
            entry = _PROCESSENTRY32W()
            entry.dwSize = ctypes.sizeof(entry)
            ok = self._k.Process32FirstW(snap, ctypes.byref(entry))
            while ok:
                path, created = self._image_path_and_created(entry.th32ProcessID)
                out.append(ProcInfo(entry.th32ProcessID, entry.th32ParentProcessID,
                                    entry.szExeFile, path, created))
                ok = self._k.Process32NextW(snap, ctypes.byref(entry))
        finally:
            self._k.CloseHandle(snap)
        return out

    def terminate(self, pid: int) -> bool:
        h = self._k.OpenProcess(PROCESS_TERMINATE | SYNCHRONIZE, False, pid)
        if not h:
            return False
        try:
            if not self._k.TerminateProcess(h, 1):
                return False
            return self._k.WaitForSingleObject(h, 3000) == 0
        finally:
            self._k.CloseHandle(h)

    # -- windows ------------------------------------------------------------
    def _text(self, fn, hwnd) -> str:
        buf = ctypes.create_unicode_buffer(512)
        fn(hwnd, buf, len(buf))
        return buf.value

    def _pid_of(self, hwnd) -> int:
        pid = wintypes.DWORD()
        self._u.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        return pid.value

    def _child_pids(self, hwnd) -> tuple:
        found: set[int] = set()

        @self._enum_proc
        def cb(child, _lp):
            found.add(self._pid_of(child))
            return True

        self._u.EnumChildWindows(hwnd, cb, 0)
        return tuple(sorted(found))

    def list_windows(self) -> list[WindowInfo]:
        wins: list[WindowInfo] = []
        u = self._u

        @self._enum_proc
        def cb(hwnd, _lp):
            if not u.IsWindowVisible(hwnd) or u.GetWindow(hwnd, GW_OWNER):
                return True
            if u.GetWindowLongW(hwnd, GWL_EXSTYLE) & WS_EX_TOOLWINDOW:
                return True
            cls = self._text(u.GetClassNameW, hwnd)
            title = self._text(u.GetWindowTextW, hwnd)
            frame = self._child_pids(hwnd) if cls == "ApplicationFrameWindow" else ()
            wins.append(WindowInfo(int(hwnd), self._pid_of(hwnd), title, cls, frame))
            return True

        u.EnumWindows(cb, 0)
        return wins

    def post_close(self, hwnd: int) -> bool:
        return bool(self._u.PostMessageW(hwnd, WM_CLOSE, 0, 0))
