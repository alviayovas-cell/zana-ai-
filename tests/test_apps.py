import json
import shutil
import sys

import pytest

from zana.apps.registry import (
    AppCommandHandler, AppEntry, AppError, AppRegistry, builtin_apps, validate_executable,
)

NOTEPAD = AppEntry("notepad", "Notepad", r"C:\Windows\System32\notepad.exe", aliases=("text editor",), builtin=True)
CALC = AppEntry("calculator", "Calculator", r"C:\Windows\System32\calc.exe", aliases=("calc",), builtin=True)


@pytest.fixture()
def harmless_exe(tmp_path):
    """A real .exe file we can safely register (it is never executed)."""
    dst = tmp_path / "my_tool.exe"
    shutil.copy(sys.executable, dst)
    return dst


def make(tmp_path, launched=None):
    log = launched if launched is not None else []
    return AppRegistry(tmp_path / "apps.json", builtins=[NOTEPAD, CALC],
                       launcher=lambda e: log.append(e.id)), log


# -- validation (the security boundary) ------------------------------------
@pytest.mark.parametrize("bad", [
    "notepad.exe",                          # relative
    r"..\..\Windows\System32\cmd.exe",      # traversal / relative
    r"C:\Windows\System32\cmd.exe",         # blocked interpreter
    r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe",
    r"C:\Windows\System32\wscript.exe",
    r"C:\does\not\exist.exe",
    r"C:\Windows\win.ini",                  # not an exe
])
def test_validate_rejects(bad):
    with pytest.raises(AppError):
        validate_executable(bad)


def test_validate_accepts_real_exe(harmless_exe):
    assert validate_executable(str(harmless_exe)) == harmless_exe.resolve()


def test_cannot_add_blocked_interpreters(tmp_path):
    reg, _ = make(tmp_path)
    for exe in (r"C:\Windows\System32\cmd.exe", r"C:\Windows\System32\mshta.exe"):
        with pytest.raises(AppError):
            reg.add_user_app(exe)
    assert [a.id for a in reg.list()] == ["notepad", "calculator"]


def test_blocked_name_even_if_copied(tmp_path):
    fake = tmp_path / "cmd.exe"
    shutil.copy(sys.executable, fake)
    reg, _ = make(tmp_path)
    with pytest.raises(AppError):
        reg.add_user_app(str(fake))


# -- registry --------------------------------------------------------------
def test_list_find_and_launch_only_approved(tmp_path):
    reg, log = make(tmp_path)
    assert reg.find("the Notepad").id == "notepad"
    assert reg.find("text editor").id == "notepad"
    assert reg.find("powershell") is None
    reg.launch("calculator")
    assert log == ["calculator"]
    with pytest.raises(AppError):
        reg.launch("powershell")
    with pytest.raises(AppError):
        reg.launch(r"C:\Windows\System32\cmd.exe")  # a path is not an id
    assert log == ["calculator"]


def test_user_apps_persist_and_can_be_removed(tmp_path, harmless_exe):
    reg, log = make(tmp_path)
    entry = reg.add_user_app(str(harmless_exe), "My Tool")
    assert entry.id == "my-tool" and not entry.builtin
    reg2, _ = make(tmp_path)  # new instance reads the file
    assert reg2.find("my tool") is not None
    reg2.launch("my-tool")
    reg2.remove_user_app("my-tool")
    assert reg2.find("my tool") is None
    with pytest.raises(AppError):
        reg2.remove_user_app("notepad")  # built-ins are permanent


def test_duplicate_names_rejected(tmp_path, harmless_exe):
    reg, _ = make(tmp_path)
    with pytest.raises(AppError):
        reg.add_user_app(str(harmless_exe), "Notepad")


def test_tampered_apps_file_entries_are_ignored(tmp_path):
    (tmp_path / "apps.json").write_text(json.dumps([
        {"name": "Evil", "path": r"C:\Windows\System32\cmd.exe"},
        {"name": "Rel", "path": "tool.exe"},
        {"path": r"C:\x.exe"},
        "garbage",
    ]))
    reg, _ = make(tmp_path)
    assert [a.id for a in reg.list()] == ["notepad", "calculator"]
    (tmp_path / "apps.json").write_text("not json")
    assert len(reg.list()) == 2


def test_launch_revalidates_at_launch_time(tmp_path, harmless_exe):
    real = AppRegistry(tmp_path / "apps.json", builtins=[])
    real.add_user_app(str(harmless_exe), "My Tool")
    harmless_exe.unlink()  # file disappears after it was approved
    assert real.list() == []  # stale entry dropped, so it can't be launched
    with pytest.raises(AppError):
        real.launch("my-tool")


def test_builtin_list_contains_only_existing_things():
    for a in builtin_apps():
        if a.kind == "exe":
            assert validate_executable(a.path)
        else:
            assert a.path == "ms-settings:"


# -- command handler --------------------------------------------------------
@pytest.mark.parametrize("text,app", [
    ("open notepad", "notepad"), ("Open Notepad.", "notepad"), ("launch the calculator", "calculator"),
    ("please open calc", "calculator"), ("start text editor", "notepad"),
    ("can you open the notepad app", "notepad"),
])
def test_handler_launches_approved_apps(tmp_path, text, app):
    reg, log = make(tmp_path)
    reply = AppCommandHandler(reg).handle(text)
    assert reply.startswith("Opening") and log == [app]


@pytest.mark.parametrize("text", [
    "run rm -rf /", "start cmd /c calc", "what is notepad", "open notepad.exe && calc",
    "open c:\\windows\\system32\\cmd.exe", "tell me a joke", "", "open a new bank account",
])
def test_handler_ignores_everything_else(tmp_path, text):
    reg, log = make(tmp_path)
    assert AppCommandHandler(reg).handle(text) is None
    assert log == []


@pytest.mark.parametrize("text", ["open powershell", "run cmd", "open the door", "open brave"])
def test_unknown_app_gets_an_honest_reply_never_a_launch(tmp_path, text):
    reg, log = make(tmp_path)
    res = AppCommandHandler(reg, finder=lambda q: []).handle_ex(text)
    assert res.pending is None and "couldn't find an app called" in res.reply
    assert "Opening" not in res.reply and log == []


def test_trailing_chatter_is_ignored_but_nothing_else_runs(tmp_path):
    reg, log = make(tmp_path)
    reply = AppCommandHandler(reg).handle("open notepad and delete everything")
    assert reply == "Opening Notepad." and log == ["notepad"]  # only the approved app starts


def test_handler_reports_launch_failure(tmp_path):
    def boom(entry):
        raise AppError("It is not installed.")
    reg = AppRegistry(tmp_path / "a.json", builtins=[NOTEPAD], launcher=boom)
    assert "couldn't open Notepad" in AppCommandHandler(reg).handle("open notepad")


# -- Store apps, discovery and approval ------------------------------------------
from zana.apps.discovery import find_candidates
from zana.apps.registry import AppCommandResult, validate_aumid

WHATSAPP = "5319275A.WhatsAppDesktop_cv1g1gvanyjgm!App"
START_APPS = [
    ("WhatsApp", WHATSAPP),
    ("Spotify", "SpotifyAB.SpotifyMusic_zpdnekdrzrea0!Spotify"),
    ("Windows PowerShell", r"{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe"),
    ("Windows Terminal", "Microsoft.WindowsTerminal_8wekyb3d8bbwe!App"),
    ("Command Prompt", "Microsoft.WindowsCommandPrompt_8wekyb3d8bbwe!App"),
    ("Google Chrome", "Chrome"),
    ("VLC media player", r"{7C5A40EF-A0FB-4BFC-874A-C0F2E0B9FA8E}\VideoLAN\VLC\vlc.exe"),
]


def lister():
    return START_APPS


@pytest.mark.parametrize("bad", [
    "", "a b", "x&&y", "calc;calc", "evil!App", "x_cv1g1gvanyjgm!App; calc", "a_cv1g1gvanyjgm!App && cmd",
    r"..\..\x_cv1g1gvanyjgm!App", "a b_cv1g1gvanyjgm!App", "a_short!App",
    WHATSAPP + " /c calc",
])
def test_aumid_validation_rejects_injection(bad):
    with pytest.raises(AppError):
        validate_aumid(bad)


def test_aumid_accepts_real_identifier():
    assert validate_aumid(WHATSAPP) == WHATSAPP


def test_discovery_finds_store_apps_only_safe_ones():
    names = [e.name for e in find_candidates("whatsapp", lister)]
    assert names == ["WhatsApp"]
    assert find_candidates("whatsapp", lister)[0].kind == "uwp"
    for blocked in ("powershell", "terminal", "command prompt", "cmd"):
        assert find_candidates(blocked, lister) == []
    assert find_candidates("ab", lister) == []          # too short
    assert find_candidates("zzzz", lister) == []


def test_discovery_handles_plain_appids_and_known_folder_paths(tmp_path, monkeypatch):
    # Plain Start-menu AppIDs (Chrome, VS Code, Brave) are launchable by id
    apps = [("Google Chrome", "Chrome"), ("Visual Studio Code", "Microsoft.VisualStudioCode"),
            ("Brave", "Brave.FIQAOYDGO62UW32XB7OHJYLCZ4"),
            ("ChatGPT Classic", "OpenAI.ChatGPT-Desktop_2p2nqsd0c76g0!ChatGPT"),
            ("VLC media player", r"{7C5A40EF-A0FB-4BFC-874A-C0F2E0B9FA8E}\VideoLAN\VLC\vlc.exe"),
            ("Evil", "x && calc"), ("Spacey", "has space")]
    look = lambda q: find_candidates(q, lambda: apps)  # noqa: E731
    assert [e.path for e in look("chrome")] == ["Chrome"]
    assert [e.path for e in look("vs code")] == ["Microsoft.VisualStudioCode"]
    assert [e.name for e in look("brave browser")] == ["Brave"]          # trailing "browser" ignored
    assert [e.name for e in look("chat gpt classic")] == ["ChatGPT Classic"]  # spaces don't matter
    assert look("evil") == [] and look("spacey") == []                   # unsafe ids never offered
    # Known-folder GUID paths resolve to real executables (here: a stand-in under tmp_path)
    exe = tmp_path / "VideoLAN" / "VLC" / "vlc.exe"
    exe.parent.mkdir(parents=True)
    shutil.copy(sys.executable, exe)
    monkeypatch.setenv("ProgramFiles(x86)", str(tmp_path))
    vlc = look("vlc")
    assert [(e.kind, e.path) for e in vlc] == [("exe", str(exe.resolve()))]
    exe.unlink()
    assert look("vlc") == []                                              # missing file: not offered


def test_unapproved_app_is_pending_not_launched(tmp_path):
    reg, log = make(tmp_path)
    handler = AppCommandHandler(reg, finder=lambda q: find_candidates(q, lister))
    res = handler.handle_ex("Hey open WhatsApp".replace("Hey ", ""))
    assert isinstance(res, AppCommandResult) and res.pending.name == "WhatsApp"
    assert "approve" in res.reply and log == []
    assert reg.find("whatsapp") is None            # still not on the allowlist
    assert handler.handle("open whatsapp") is None  # legacy API never launches pending apps


def test_approving_adds_persists_and_launches(tmp_path):
    reg, log = make(tmp_path)
    handler = AppCommandHandler(reg, finder=lambda q: find_candidates(q, lister))
    pending = handler.handle_ex("open whatsapp").pending
    added = reg.add_entry(pending)                  # what the UI does after the user says yes
    assert added.kind == "uwp"
    reg2, log2 = make(tmp_path)                     # survives restart
    assert reg2.find("whatsapp").path == WHATSAPP
    assert AppCommandHandler(reg2, finder=lambda q: []).handle("open whatsapp") == "Opening WhatsApp."
    assert log2 == ["whatsapp"]


def test_add_entry_refuses_blocked_and_malformed(tmp_path):
    reg, _ = make(tmp_path)
    for bad in (
        AppEntry("x", "Windows Terminal", "Microsoft.WindowsTerminal_8wekyb3d8bbwe!App", "uwp"),
        AppEntry("x", "Evil", "x_cv1g1gvanyjgm!App && calc", "uwp"),
        AppEntry("x", "Cmd", r"C:\Windows\System32\cmd.exe", "exe"),
        AppEntry("x", "Link", "ms-settings:", "uri"),
    ):
        with pytest.raises(AppError):
            reg.add_entry(bad)
    assert [a.id for a in reg.list()] == ["notepad", "calculator"]


def test_tampered_uwp_entries_are_dropped(tmp_path):
    (tmp_path / "apps.json").write_text(json.dumps([
        {"name": "Ok", "path": WHATSAPP, "kind": "uwp"},
        {"name": "Bad", "path": "x && calc", "kind": "uwp"},
        {"name": "Terminal", "path": "Microsoft.WindowsTerminal_8wekyb3d8bbwe!App", "kind": "uwp"},
        {"name": "Weird", "path": WHATSAPP, "kind": "shell"},
    ]))
    reg, _ = make(tmp_path)
    assert [a.name for a in reg.list()] == ["Notepad", "Calculator", "Ok"]


def test_spoken_names_with_chatter_still_find_the_app(tmp_path):
    reg, log = make(tmp_path)
    apps = [("ChatGPT Classic", "OpenAI.ChatGPT-Desktop_2p2nqsd0c76g0!ChatGPT"),
            ("Visual Studio Code", "Microsoft.VisualStudioCode")]
    handler = AppCommandHandler(reg, finder=lambda q: find_candidates(q, lambda: apps))
    res = handler.handle_ex("open chat gpt classic which has the shortcut in windows")
    assert res.pending.name == "ChatGPT Classic"
    assert handler.handle_ex("open vs code").pending.name == "Visual Studio Code"
    assert log == []  # asking never launches


def test_unfindable_or_blocked_apps_get_honest_replies(tmp_path):
    reg, log = make(tmp_path)
    handler = AppCommandHandler(reg, finder=lambda q: find_candidates(q, lister))
    for text in ("open the door", "open powershell"):
        res = handler.handle_ex(text)
        assert res.pending is None and "couldn't find an app" in res.reply
    assert handler.handle_ex("open a new account") is None  # plain conversation
    assert log == []
