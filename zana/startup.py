"""Launch Zana when the user signs in to Windows.

Uses the per-user ``HKCU\\...\\Run`` key, so no administrator rights are needed,
only the current user is affected, and Windows starts it *after* sign-in (it
cannot bypass the sign-in screen). The user can also turn it off in
Task Manager > Startup apps.
"""

import sys
from pathlib import Path

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "Zana"
BACKGROUND_FLAG = "--background"


class StartupError(Exception):
    pass


def launch_command() -> str:
    """Command line Windows should run at sign-in (always absolute, quoted)."""
    if getattr(sys, "frozen", False):
        return f'"{Path(sys.executable).resolve()}" {BACKGROUND_FLAG}'
    # Running from source: use the venv's windowless interpreter if present.
    exe = Path(sys.executable).resolve()
    pythonw = exe.with_name("pythonw.exe")
    interpreter = pythonw if pythonw.exists() else exe
    main = Path(__file__).resolve().parent.parent / "main.py"
    return f'"{interpreter}" "{main}" {BACKGROUND_FLAG}'


def _open(key_path: str, access):
    import winreg
    return winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, access)


def is_enabled(key_path: str = RUN_KEY) -> bool:
    import winreg
    try:
        with _open(key_path, winreg.KEY_READ) as key:
            winreg.QueryValueEx(key, VALUE_NAME)
        return True
    except OSError:
        return False


def current_command(key_path: str = RUN_KEY):
    import winreg
    try:
        with _open(key_path, winreg.KEY_READ) as key:
            return winreg.QueryValueEx(key, VALUE_NAME)[0]
    except OSError:
        return None


def enable(key_path: str = RUN_KEY, command: str | None = None) -> None:
    import winreg
    try:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path) as key:
            winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_SZ, command or launch_command())
    except OSError as e:
        raise StartupError(f"Windows refused to save the startup entry: {e.strerror or e}") from e


def disable(key_path: str = RUN_KEY) -> None:
    import winreg
    try:
        with _open(key_path, winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, VALUE_NAME)
    except FileNotFoundError:
        return  # already off
    except OSError as e:
        raise StartupError(f"Could not remove the startup entry: {e.strerror or e}") from e


def sync(enabled: bool, key_path: str = RUN_KEY) -> None:
    """Make the registry match the saved preference (also repairs a moved exe)."""
    if enabled:
        if current_command(key_path) != launch_command():
            enable(key_path)
    # When disabled we deliberately leave the key alone: the user may manage it
    # in Task Manager, and the checkbox only removes it when they untick it.
