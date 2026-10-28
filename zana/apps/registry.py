"""Allowlist of applications Zana may launch.

Safety model:
  * Only entries in the registry can ever be started. Text from the user, the
    model or a web page is matched against entry *names*; it never supplies a path
    or arguments.
  * Entries are plain executables launched without a shell and without arguments.
  * Interpreters, script hosts and admin tools (cmd, powershell, wscript, ...) are
    refused even if added by hand.
  * User-added entries can only be created through the Applications page, where
    the user picks the .exe and confirms it.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

BLOCKED_EXECUTABLES = frozenset({
    "cmd.exe", "powershell.exe", "pwsh.exe", "powershell_ise.exe", "wscript.exe",
    "cscript.exe", "mshta.exe", "regsvr32.exe", "rundll32.exe", "reg.exe", "regedit.exe",
    "msiexec.exe", "wsl.exe", "bash.exe", "certutil.exe", "bitsadmin.exe", "schtasks.exe",
    "sc.exe", "net.exe", "net1.exe", "taskkill.exe", "diskpart.exe", "format.com",
    "python.exe", "pythonw.exe", "py.exe", "node.exe", "curl.exe", "ssh.exe", "wmic.exe",
    "msbuild.exe", "installutil.exe", "cmstp.exe", "forfiles.exe", "runas.exe",
    "psexec.exe", "conhost.exe", "windowsterminal.exe", "wt.exe", "mmc.exe",
})
_ALLOWED_URIS = frozenset({"ms-settings:"})
# Package-family-name!AppId, e.g. 5319275A.WhatsAppDesktop_cv1g1gvanyjgm!App
_AUMID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.\-]{1,100}_[a-z0-9]{13}![A-Za-z0-9._\-]{1,64}$")
# Store apps whose purpose is running commands: never offered, even with approval.
BLOCKED_APP_NAME_PARTS = ("powershell", "command prompt", "cmd", "terminal", "registry",
                          "windows script", "wsl", "ubuntu", "debian", "kali", "python",
                          "developer command", "git bash", "task scheduler", "services")
_DETACHED = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP


class AppError(Exception):
    """Refused or failed app operation; message is safe to show to the user."""


@dataclass(frozen=True)
class AppEntry:
    id: str
    name: str
    path: str                      # absolute .exe path, allowed URI, or Store-app AUMID
    kind: str = "exe"              # "exe" | "uri" | "uwp"
    aliases: tuple = ()
    builtin: bool = False
    # How to recognise this app's running processes/windows when closing it (built-ins only;
    # user-added apps are matched by their exe path or Store package).
    match_images: tuple = ()       # image names accepted from Windows/WindowsApps locations
    package: str = ""              # Store package name, e.g. "Microsoft.WindowsCalculator"
    window_classes: tuple = ()     # if set, only windows of these classes are "the app"
    never_terminate: bool = False  # may be closed politely, but never force-killed

    @property
    def names(self) -> set[str]:
        base = {normalize(self.name), *(normalize(a) for a in self.aliases)}
        return base | {n.replace(" ", "") for n in base}


def normalize(text: str) -> str:
    text = re.sub(r"[^a-z0-9 ]", " ", text.lower())
    text = re.sub(r"^(the|my)\s+", "", text.strip())
    return re.sub(r"\s+", " ", text).strip()


_ALIASES = {
    "vs code": "visual studio code", "vscode": "visual studio code", "visual studio": "visual studio code",
    "chat gpt": "chatgpt", "word": "microsoft word", "excel": "microsoft excel",
    "powerpoint": "microsoft powerpoint", "teams": "microsoft teams", "edge": "microsoft edge",
}


def squash(text: str) -> str:
    """Normalized name without spaces, so "chat gpt classic" matches "ChatGPT Classic"."""
    return normalize(text).replace(" ", "")


def canonical(text: str) -> str:
    """Normalized name with common spoken abbreviations expanded."""
    n = re.sub(r"\s+browser$", "", normalize(text))  # "brave browser" -> "brave"
    return _ALIASES.get(n, n)


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "app"


def validate_executable(path: str) -> Path:
    """Return the resolved path of an acceptable .exe, or raise AppError."""
    p = Path(path)
    if not p.is_absolute():
        raise AppError("Only full paths to an .exe file are allowed.")
    try:
        p = p.resolve(strict=True)
    except (OSError, RuntimeError):
        raise AppError("That file does not exist.") from None
    if not p.is_file() or p.suffix.lower() != ".exe":
        raise AppError("Only .exe applications can be added.")
    if p.name.lower() in BLOCKED_EXECUTABLES:
        raise AppError(f"{p.name} is not allowed (it can run arbitrary commands).")
    return p


# Plain Start-menu AppIDs such as "Microsoft.VisualStudioCode" or "Chrome": letters, digits,
# dots, dashes only - no spaces, slashes or shell metacharacters.
_SIMPLE_APPID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9._-]{1,79}$")


def validate_aumid(aumid: str) -> str:
    """Accept a Store AUMID (Package!App) or a plain Start-menu AppID; reject anything else."""
    if not isinstance(aumid, str) or not (_AUMID_RE.match(aumid) or _SIMPLE_APPID_RE.match(aumid)):
        raise AppError("That is not a valid app identifier.")
    return aumid


def name_is_blocked(name: str) -> bool:
    n = normalize(name)
    return any(part in n.split() or part in n for part in BLOCKED_APP_NAME_PARTS)


def builtin_apps() -> list[AppEntry]:
    root = Path(os.environ.get("SystemRoot", r"C:\Windows"))
    # (name, path, aliases, extra matching hints used only when closing)
    candidates = [
        ("Notepad", root / "System32" / "notepad.exe", ("text editor",),
         dict(match_images=("notepad.exe",), package="Microsoft.WindowsNotepad")),
        ("Calculator", root / "System32" / "calc.exe", ("calc",),
         dict(match_images=("calculatorapp.exe", "calculator.exe", "calc.exe"),
              package="Microsoft.WindowsCalculator")),
        ("Task Manager", root / "System32" / "Taskmgr.exe", (),
         dict(match_images=("taskmgr.exe",), never_terminate=True)),
        # File Explorer is also the desktop shell: only its folder windows may be closed.
        ("File Explorer", root / "explorer.exe", ("explorer", "files"),
         dict(match_images=("explorer.exe",), window_classes=("CabinetWClass", "ExploreWClass"),
              never_terminate=True)),
        ("Paint", root / "System32" / "mspaint.exe", ("ms paint",),
         dict(match_images=("mspaint.exe",), package="Microsoft.Paint")),
        ("Snipping Tool", root / "System32" / "SnippingTool.exe", ("screenshot tool",),
         dict(match_images=("snippingtool.exe",), package="Microsoft.ScreenSketch")),
    ]
    apps = [
        AppEntry(_slug(n), n, str(p), "exe", aliases, builtin=True, **extra)
        for n, p, aliases, extra in candidates if p.is_file()
    ]
    apps.append(AppEntry("windows-settings", "Windows Settings", "ms-settings:", "uri",
                         ("windows settings", "system settings"), builtin=True, never_terminate=True,
                         match_images=("systemsettings.exe",), package="windows.immersivecontrolpanel"))
    return apps


def _default_launcher(entry: AppEntry) -> None:
    if entry.kind == "uri":
        if entry.path not in _ALLOWED_URIS:
            raise AppError("That link type is not allowed.")
        os.startfile(entry.path)  # noqa: S606 - fixed allowlisted URI only
        return
    if entry.kind == "uwp":
        os.startfile("shell:AppsFolder\\" + validate_aumid(entry.path))  # noqa: S606
        return
    exe = validate_executable(entry.path)
    subprocess.Popen(  # noqa: S603 - no shell, no arguments, validated absolute path
        [str(exe)], shell=False, cwd=str(exe.parent), close_fds=True,
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        creationflags=_DETACHED,
    )


class AppRegistry:
    def __init__(self, user_file: Path | str, builtins: Optional[list[AppEntry]] = None,
                 launcher: Callable[[AppEntry], None] = _default_launcher):
        self._file = Path(user_file)
        self._builtins = builtin_apps() if builtins is None else list(builtins)
        self._launcher = launcher

    # -- reading ------------------------------------------------------------
    def _load_user(self) -> list[AppEntry]:
        try:
            raw = json.loads(self._file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        out = []
        for item in raw if isinstance(raw, list) else []:
            try:
                name, path = str(item["name"]).strip(), str(item["path"])
                kind = item.get("kind", "exe")
                if kind == "uwp":
                    path = validate_aumid(path)
                    if name_is_blocked(name):
                        continue
                elif kind == "exe":
                    path = str(validate_executable(path))
                else:
                    continue
            except (KeyError, TypeError, AttributeError, AppError):
                continue  # silently drop tampered / stale entries
            if name:
                out.append(AppEntry(_slug(name), name, path, kind))
        return out

    def list(self) -> list[AppEntry]:
        taken = {a.id for a in self._builtins}
        return self._builtins + [a for a in self._load_user() if a.id not in taken]

    def find(self, text: str) -> Optional[AppEntry]:
        apps = self.list()
        keys = {canonical(text), squash(canonical(text))} - {""}
        exact = next((a for a in apps if keys & a.names), None)
        if exact is not None:
            return exact
        # "chrome" -> "Google Chrome", "code" -> "Visual Studio Code": a unique partial name
        # is enough, an ambiguous one (two apps contain it) is not.
        tokens = canonical(text).split()
        if tokens and all(len(t) >= 3 for t in tokens):
            hits = [a for a in apps if any(set(tokens) <= set(n.split()) for n in a.names if " " in n)]
            if len(hits) == 1:
                return hits[0]
        return None

    # -- changing -----------------------------------------------------------
    def add_user_app(self, path: str, name: Optional[str] = None) -> AppEntry:
        exe = validate_executable(path)
        name = (name or exe.stem.replace("_", " ").replace("-", " ").title()).strip()
        if not name or len(name) > 60:
            raise AppError("Please give the app a name of up to 60 characters.")
        entry = AppEntry(_slug(name), name, str(exe))
        if any(entry.names & a.names or a.id == entry.id for a in self.list()):
            raise AppError(f"An app named '{name}' already exists.")
        self._persist_with(entry)
        return entry

    def add_entry(self, entry: AppEntry) -> AppEntry:
        """Add an app found by discovery (Store app or exe). Caller must have asked the user."""
        if entry.kind == "uwp":
            validate_aumid(entry.path)
            if name_is_blocked(entry.name):
                raise AppError(f"{entry.name} is not allowed (it can run arbitrary commands).")
        elif entry.kind == "exe":
            validate_executable(entry.path)
        else:
            raise AppError("That kind of app can't be added.")
        entry = AppEntry(_slug(entry.name), entry.name, entry.path, entry.kind)
        if any(entry.names & a.names or a.id == entry.id for a in self.list()):
            raise AppError(f"An app named '{entry.name}' already exists.")
        self._persist_with(entry)
        return entry

    def _persist_with(self, entry: AppEntry) -> None:
        items = [{"name": a.name, "path": a.path, "kind": a.kind} for a in self._load_user()]
        items.append({"name": entry.name, "path": entry.path, "kind": entry.kind})
        self._write(items)

    def remove_user_app(self, app_id: str) -> None:
        users = self._load_user()
        if any(b.id == app_id for b in self._builtins):
            raise AppError("Built-in apps can't be removed.")
        kept = [{"name": a.name, "path": a.path, "kind": a.kind} for a in users if a.id != app_id]
        if len(kept) == len(users):
            raise AppError("No such app.")
        self._write(kept)

    def _write(self, items: list[dict]) -> None:
        self._file.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._file.with_suffix(".tmp")
        tmp.write_text(json.dumps(items, indent=2), encoding="utf-8")
        os.replace(tmp, self._file)

    # -- launching ----------------------------------------------------------
    def launch(self, app_id: str) -> AppEntry:
        """Launch an approved app by id. Re-reads the allowlist every time."""
        entry = next((a for a in self.list() if a.id == app_id), None)
        if entry is None:
            raise AppError("That app is not in your approved list.")
        try:
            self._launcher(entry)
        except AppError:
            raise
        except OSError as e:
            raise AppError(f"Could not start {entry.name}: {e.strerror or e}") from e
        return entry


_OPEN_VERBS = r"open|launch|start|run"
_CLOSE_VERBS = r"close|quit|exit|shut\s+down|shut"
_LAUNCH_RE = re.compile(
    r"^(?:(?:please|can you|could you|would you|will you|hey|zana)\s+)*"
    r"(?:(?P<open>" + _OPEN_VERBS + r")|(?P<close>" + _CLOSE_VERBS + r"))\s+(?:up\s+|down\s+)?"
    r"(?P<name>[a-z0-9 ]{1,100}?)(?:\s+(?:app|application|program|please))*$"
)


@dataclass
class AppCommandResult:
    reply: str
    pending: Optional[AppEntry] = None   # found on this PC but NOT approved yet
    choose: Optional[object] = None      # CloseOutcome(status="choose"): which window to close?
    force: Optional[object] = None       # CloseOutcome(status="force"): confirm a force-close
    action: str = "open"                 # "open" | "close"


class AppCommandHandler:
    """Turns "open notepad" into a launch of an *approved* app.

    An app that is installed but not approved is returned as ``pending`` so the UI
    can ask the user; it is never launched or added by this class. If the request looks
    like "open <app name>" but no such app exists, the reply says so plainly (the
    language model is never left to improvise that it opened something).
    """

    # Trailing chatter ("... which has the shortcut in windows") is not part of the name.
    _STOP = re.compile(r"\s+(?:which|that|because|in|on|from|using|with|for|and|so|then|please|"
                       r"app|application|program|has|is)\b.*$")

    def __init__(self, registry: AppRegistry, finder: Optional[Callable[[str], list]] = None,
                 closer=None):
        self.registry = registry
        self._finder = finder
        self._closer = closer   # zana.apps.closer.AppCloser (None = closing unavailable)

    @classmethod
    def _parse_full(cls, text: str) -> Optional[tuple[str, str]]:
        """("open"|"close", app name) for "open X" / "close X" style requests, else None."""
        m = _LAUNCH_RE.match(re.sub(r"[.!?,]+$", "", text.lower().strip()))
        if not m:
            return None
        name = cls._STOP.sub("", m.group("name")).strip()
        if not name:
            return None
        return ("close" if m.group("close") else "open"), name

    @classmethod
    def _parse(cls, text: str) -> Optional[str]:
        parsed = cls._parse_full(text)
        return parsed[1] if parsed else None

    def is_launch_intent(self, text: str) -> bool:
        """Cheap regex-only check (no I/O), safe on the UI thread. Covers open and close."""
        return self._parse_full(text) is not None

    is_app_intent = is_launch_intent

    # -- closing --------------------------------------------------------------
    def _entry_by_id(self, app_id: str) -> Optional[AppEntry]:
        return next((a for a in self.registry.list() if a.id == app_id), None)

    @staticmethod
    def _as_result(outcome) -> AppCommandResult:
        return AppCommandResult(
            outcome.message, action="close",
            choose=outcome if outcome.status == "choose" else None,
            force=outcome if outcome.status == "force" else None)

    def _handle_close(self, name: str) -> Optional[AppCommandResult]:
        entry = self.registry.find(name)
        if entry is None:
            # Only approved apps can be closed; never offer to add-and-close.
            candidates = self._finder(name) if self._finder is not None else []
            if candidates:
                return AppCommandResult(
                    f"{candidates[0].name} isn't in your approved apps, so I can't close it. "
                    "Approve it first (say \"open " + candidates[0].name + "\" or use the Applications page).",
                    action="close")
            words = name.split()
            if len(words) <= 3 and words[0] not in {"a", "an", "some", "any", "new"}:
                return AppCommandResult(
                    f"I couldn't find an approved app called {name}, so there is nothing for me to close.",
                    action="close")
            return None
        if self._closer is None:
            return AppCommandResult("Closing apps isn't available right now.", action="close")
        return self._as_result(self._closer.close(entry))

    def close_selected(self, app_id: str, hwnds: list) -> AppCommandResult:
        """Second step after the user picked which window(s) to close."""
        entry = self._entry_by_id(app_id)
        if entry is None or self._closer is None:
            return AppCommandResult("That app is not in your approved list.", action="close")
        return self._as_result(self._closer.close(entry, list(hwnds)))

    def force_close(self, app_id: str) -> AppCommandResult:
        """Final step, only after the user confirmed a force-close."""
        entry = self._entry_by_id(app_id)
        if entry is None or self._closer is None:
            return AppCommandResult("That app is not in your approved list.", action="close")
        return self._as_result(self._closer.force(entry))

    def handle_ex(self, text: str) -> Optional[AppCommandResult]:
        """None means "not an app command - treat as ordinary conversation"."""
        parsed = self._parse_full(text)
        if parsed is None:
            return None
        action, name = parsed
        if action == "close":
            return self._handle_close(name)
        entry = self.registry.find(name)
        if entry is not None:
            try:
                self.registry.launch(entry.id)
            except AppError as e:
                return AppCommandResult(f"I couldn't open {entry.name}. {e}")
            return AppCommandResult(f"Opening {entry.name}.")
        candidates = self._finder(name) if self._finder is not None else []
        if candidates:
            pending = candidates[0]
            return AppCommandResult(
                f"{pending.name} isn't in your approved apps yet. Please approve it on screen.", pending)
        words = name.split()
        if len(words) <= 3 and words[0] not in {"a", "an", "some", "any", "new"}:
            return AppCommandResult(
                f"I couldn't find an app called {name} in your approved apps or on this PC. "
                "You can add it from the Applications page.")
        return None  # long or article-led phrases ("open a new account") are just conversation

    def handle(self, text: str) -> Optional[str]:
        """Reply text if an approved app was handled, else None."""
        res = self.handle_ex(text)
        return None if res is None or res.pending is not None else res.reply
