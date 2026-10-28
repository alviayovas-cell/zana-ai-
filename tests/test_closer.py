"""AppCloser: identification, graceful close, force-close, and every safety restriction.

All tests use FakeProcessApi - nothing here can touch a real process or window.
"""

import pytest

from tests.fake_process_api import (
    CALCULATOR, CHROME, CHROME_EXE, EXPLORER, MYTOOL, NOTEPAD, SPOTIFY, SPOTIFY_EXE, WHATSAPP,
    WHATSAPP_EXE, WIN, WINAPPS, FakeClock, FakeProcessApi, proc, win,
)
from zana.apps.closer import AppCloser
from zana.apps.registry import AppEntry


@pytest.fixture(autouse=True)
def windows_dir(monkeypatch):
    monkeypatch.setenv("SystemRoot", WIN)


def closer(api, resolver=lambda e: None):
    return AppCloser(api, target_resolver=resolver, wait_s=2.0, poll_s=0.1,
                     sleep=lambda s: None, clock=FakeClock())


def spotify_running(n_windows=1, behaviour="exit"):
    procs = [proc(100, "Spotify.exe", SPOTIFY_EXE), proc(101, "Spotify.exe", SPOTIFY_EXE, ppid=100)]
    wins = [win(10 + i, 100, f"Spotify window {i}") for i in range(n_windows)]
    return FakeProcessApi(procs, wins, behaviours={w.hwnd: behaviour for w in wins})


# ----------------------------------------------------------------------------------
# identification
# ----------------------------------------------------------------------------------
def test_store_app_is_matched_by_package_folder_and_publisher():
    api = FakeProcessApi([
        proc(1, "Spotify.exe", SPOTIFY_EXE),
        proc(2, "Spotify.exe", WINAPPS + r"\SpotifyAB.SpotifyMusic_1.0.0.0_x64__otherpublisher\Spotify.exe"),
        proc(3, "Spotify.exe", r"C:\Users\me\Downloads\Spotify.exe"),
        proc(4, "Other.exe", WINAPPS + r"\SpotifyAB.SpotifyMusicEvil_1.0_x64__zpdnekdrzrea0\Other.exe"),
    ], [])
    assert [p.pid for p in closer(api).instances(SPOTIFY).procs] == [1]


def test_exe_app_matches_only_its_exact_path():
    api = FakeProcessApi([
        proc(1, "mytool.exe", r"C:\Tools\mytool.exe"),
        proc(2, "mytool.exe", r"C:\Other\mytool.exe"),
        proc(3, "mytool.exe", r"C:\Tools\sub\mytool.exe"),
    ], [])
    assert [p.pid for p in closer(api).instances(MYTOOL).procs] == [1]


def test_plain_appid_uses_the_exe_behind_the_start_menu_shortcut():
    api = FakeProcessApi([
        proc(1, "chrome.exe", CHROME_EXE), proc(2, "chrome.exe", CHROME_EXE, ppid=1),
        proc(3, "chrome.exe", r"C:\Users\me\AppData\Local\Temp\chrome.exe"),
    ], [])
    asked = []

    def resolver(entry):
        asked.append(entry.name)
        return CHROME_EXE

    c = closer(api, resolver)
    assert [p.pid for p in c.instances(CHROME).procs] == [1, 2]
    c.instances(CHROME)
    assert asked == ["Google Chrome"]                    # resolved once, then cached


def test_plain_appid_without_a_shortcut_is_never_guessed_by_name():
    api = FakeProcessApi([proc(1, "chrome.exe", CHROME_EXE)], [win(5, 1, "Chrome")])
    out = closer(api, lambda e: None).close(CHROME)
    assert out.status == "not_running" and api.posted == [] and api.terminated == []


def test_builtin_image_names_only_count_from_windows_or_store_locations():
    api = FakeProcessApi([
        proc(1, "notepad.exe", WIN + r"\System32\notepad.exe"),
        proc(2, "notepad.exe", WINAPPS + r"\Microsoft.WindowsNotepad_11.2.0_x64__8wekyb3d8bbwe\Notepad\Notepad.exe"),
        proc(3, "notepad.exe", r"C:\Users\me\Desktop\notepad.exe"),          # lookalike: ignored
        proc(4, "notepad.exe", r"C:\Temp\evil\notepad.exe"),
    ], [])
    assert sorted(p.pid for p in closer(api).instances(NOTEPAD).procs) == [1, 2]


def test_calculator_store_app_matches_by_package():
    api = FakeProcessApi([
        proc(1, "CalculatorApp.exe", WINAPPS + r"\Microsoft.WindowsCalculator_11.0_x64__8wekyb3d8bbwe\CalculatorApp.exe"),
        proc(2, "CalculatorApp.exe", r"C:\Elsewhere\CalculatorApp.exe"),
    ], [])
    assert [p.pid for p in closer(api).instances(CALCULATOR).procs] == [1]


def test_unreadable_path_is_never_matched_and_is_reported():
    api = FakeProcessApi([proc(7, "mytool.exe", "")], [])          # elevated: Windows hides the path
    out = closer(api).close(MYTOOL)
    assert out.status == "failed" and "administrator" in out.message
    assert api.posted == [] and api.terminated == []


def test_zana_itself_is_never_matched_and_its_parents_are_never_killed():
    zana_exe = AppEntry("zana", "Zana", r"C:\Users\me\Zana\Zana.exe", "exe")
    api = FakeProcessApi([
        proc(50, "Zana.exe", r"C:\Users\me\Zana\Zana.exe", ppid=40),      # us
        proc(40, "Zana.exe", r"C:\Users\me\Zana\Zana.exe", ppid=1),       # launcher parent
    ], [win(1, 50, "Zana"), win(2, 40, "Zana launcher")], own_pid=50, behaviours={2: "stuck"})
    c = closer(api)
    assert [p.pid for p in c.instances(zana_exe).procs] == [40]          # we are invisible to ourselves
    out = c.close(zana_exe)
    assert api.posted == [2] and 1 not in api.posted                     # our own window is never closed
    assert out.status == "failed" and "started Zana" in out.message      # parent: polite only
    assert c.force(zana_exe).status == "failed" and api.terminated == []


def test_file_explorer_is_found_even_when_zana_was_started_from_it():
    # Zana launched from the desktop shortcut has explorer.exe as its parent process.
    api = FakeProcessApi([
        proc(500, "explorer.exe", WIN + r"\explorer.exe", ppid=1),
        proc(900, "Zana.exe", r"C:\Zana\Zana.exe", ppid=500),
    ], [win(30, 500, "Documents", "CabinetWClass")], own_pid=900)
    out = closer(api).close(EXPLORER)
    assert out.status == "closed" and api.posted == [30] and api.terminated == []


def test_entry_that_cannot_be_identified_is_refused_politely():
    settings = AppEntry("windows-settings", "Windows Settings", "ms-settings:", "uri", builtin=True)
    out = closer(FakeProcessApi([], [])).close(settings)
    assert out.status == "failed" and "close it yourself" in out.message


# ----------------------------------------------------------------------------------
# windows
# ----------------------------------------------------------------------------------
def test_hidden_untitled_and_foreign_windows_are_ignored():
    api = FakeProcessApi(
        [proc(100, "Spotify.exe", SPOTIFY_EXE), proc(200, "Other.exe", r"C:\x\Other.exe")],
        [win(10, 100, "Spotify"), win(11, 100, ""), win(12, 200, "Other app")])
    inst = closer(api).instances(SPOTIFY)
    assert [w.hwnd for w in inst.windows] == [10]


def test_store_apps_in_a_frame_window_are_found_through_the_frame_pids():
    calc_exe = WINAPPS + r"\Microsoft.WindowsCalculator_11.0_x64__8wekyb3d8bbwe\CalculatorApp.exe"
    api = FakeProcessApi(
        [proc(300, "CalculatorApp.exe", calc_exe), proc(400, "ApplicationFrameHost.exe", WIN + r"\System32\ApplicationFrameHost.exe")],
        [win(20, 400, "Calculator", "ApplicationFrameWindow", frame_pids=(400, 300)),
         win(21, 300, "Calculator", "Windows.UI.Core.CoreWindow"),        # duplicate of the frame
         win(22, 400, "Settings", "ApplicationFrameWindow", frame_pids=(400, 999))])   # someone else's frame
    inst = closer(api).instances(CALCULATOR)
    assert [p.pid for p in inst.procs] == [300]          # the frame host itself is not "the app"
    assert [w.hwnd for w in inst.windows] == [20]


def test_file_explorer_only_counts_folder_windows():
    api = FakeProcessApi(
        [proc(500, "explorer.exe", WIN + r"\explorer.exe")],
        [win(30, 500, "Documents", "CabinetWClass"), win(31, 500, "", "Shell_TrayWnd"),
         win(32, 500, "Program Manager", "Progman"), win(33, 500, "Downloads", "CabinetWClass")])
    assert [w.hwnd for w in closer(api).instances(EXPLORER).windows] == [30, 33]


# ----------------------------------------------------------------------------------
# graceful closing
# ----------------------------------------------------------------------------------
def test_not_running():
    out = closer(FakeProcessApi([], [])).close(SPOTIFY)
    assert (out.status, out.message) == ("not_running", "Spotify isn't running.")


def test_single_window_closes_gracefully_and_nothing_is_killed():
    api = spotify_running(1)
    out = closer(api).close(SPOTIFY)
    assert out.status == "closed" and out.message == "Closed Spotify."
    assert api.posted == [10] and api.terminated == [] and api.procs == []


def test_multiple_windows_ask_which_one_and_post_nothing_yet():
    api = spotify_running(3)
    out = closer(api).close(SPOTIFY)
    assert out.status == "choose" and [w.hwnd for w in out.windows] == [10, 11, 12]
    assert "3 windows" in out.message and api.posted == []


def test_closing_one_selected_window_leaves_the_others_open():
    api = spotify_running(3)
    out = closer(api).close(SPOTIFY, hwnds=[11])
    assert out.status == "closed" and "1 Spotify window" in out.message
    assert api.posted == [11] and [w.hwnd for w in api.windows] == [10, 12]
    assert api.terminated == [] and api.procs            # app still running with its other windows


def test_choosing_every_window_quits_the_app():
    api = spotify_running(2)
    out = closer(api).close(SPOTIFY, hwnds=[10, 11])
    assert out.status == "closed" and out.message == "Closed Spotify."
    assert api.posted == [10, 11] and api.procs == []


def test_a_stale_selection_is_reported():
    out = closer(spotify_running(1)).close(SPOTIFY, hwnds=[999])
    assert out.status == "failed" and "already gone" in out.message


def test_background_app_with_no_window_offers_force_quit_not_silent_kill():
    api = FakeProcessApi([proc(100, "Spotify.exe", SPOTIFY_EXE)], [])
    out = closer(api).close(SPOTIFY)
    assert out.status == "force" and out.background and out.pids == [100]
    assert "unsaved" in out.message and api.terminated == []


def test_tray_app_keeps_running_after_its_window_closes_then_asks_before_force():
    api = spotify_running(1, behaviour="hide")
    out = closer(api).close(SPOTIFY)
    assert out.status == "force" and out.background
    assert "still running in the background" in out.message
    assert api.posted == [10] and api.terminated == []   # asked, did not kill


def test_stuck_window_asks_before_force_and_mentions_unsaved_work():
    api = spotify_running(1, behaviour="stuck")
    out = closer(api).close(SPOTIFY)
    assert out.status == "force" and not out.background
    assert "asking you to save" in out.message and "unsaved" in out.message
    assert api.terminated == []


# ----------------------------------------------------------------------------------
# force closing (only ever called after the user said yes)
# ----------------------------------------------------------------------------------
def test_force_terminates_only_the_matched_processes():
    api = spotify_running(1, behaviour="stuck")
    api.procs.append(proc(777, "Unrelated.exe", r"C:\Apps\Unrelated.exe"))
    out = closer(api).force(SPOTIFY)
    assert out.status == "closed" and "Force-closed Spotify" in out.message
    assert sorted(api.terminated) == [100, 101]
    assert [p.pid for p in api.procs] == [777]


def test_force_reports_failure_when_a_process_will_not_die():
    api = spotify_running(1, behaviour="stuck")
    api.terminate_fails = {100}
    out = closer(api).force(SPOTIFY)
    assert out.status == "failed" and "couldn't force-close" in out.message


def test_force_rematches_instead_of_trusting_old_pids_and_survives_pid_reuse():
    api = spotify_running(1, behaviour="stuck")
    # between listing and terminating, pid 100 exits and the number is reused by another program
    api.reuse_pid_after_call = (1, 100)
    out = closer(api).force(SPOTIFY)
    assert 100 not in api.terminated                      # never kills the recycled pid
    assert out.status in ("closed", "failed")


def test_force_when_already_gone_is_a_success_message():
    out = closer(FakeProcessApi([], [])).force(SPOTIFY)
    assert out.status == "closed" and "isn't running any more" in out.message


# ----------------------------------------------------------------------------------
# SAFETY: what must never be force-closed
# ----------------------------------------------------------------------------------
@pytest.mark.parametrize("name", [
    "svchost.exe", "csrss.exe", "winlogon.exe", "lsass.exe", "services.exe", "dwm.exe",
    "explorer.exe", "sihost.exe", "ApplicationFrameHost.exe", "RuntimeBroker.exe", "MsMpEng.exe",
    "SecurityHealthService.exe", "NisSrv.exe", "ShellExperienceHost.exe", "wininit.exe",
])
def test_system_processes_are_never_force_closed_even_if_an_entry_points_at_them(name):
    entry = AppEntry("sys", "Sys", rf"C:\Program Files\Odd\{name}", "exe")   # outside Windows folder
    api = FakeProcessApi([proc(5, name, rf"C:\Program Files\Odd\{name}")], [win(1, 5, "Sys")],
                         behaviours={1: "stuck"})
    out = closer(api).close(entry)
    assert out.status == "failed" and "close it yourself" in out.message
    assert closer(api).force(entry).status == "failed"
    assert api.terminated == []


def test_anything_inside_the_windows_folder_is_closed_politely_only():
    entry = AppEntry("tool", "Tool", WIN + r"\System32\sometool.exe", "exe")
    api = FakeProcessApi([proc(5, "sometool.exe", WIN + r"\System32\sometool.exe")],
                         [win(1, 5, "Tool")], behaviours={1: "stuck"})
    out = closer(api).close(entry)
    assert out.status == "failed" and api.posted == [1]    # it was asked nicely
    assert closer(api).force(entry).status == "failed"
    assert api.terminated == []


@pytest.mark.parametrize("path", [
    r"C:\Program Files\Windows Defender\mpcmdrun.exe",
    r"C:\Program Files\Avast Software\Avast\AvastUI.exe",
    r"C:\Program Files\Malwarebytes\Anti-Malware\mbam.exe",
    r"C:\Program Files\McAfee\Agent\macmnsvc.exe",
    r"C:\Program Files\Kaspersky Lab\kav.exe",
])
def test_security_software_is_never_force_closed(path):
    entry = AppEntry("av", "Antivirus", path, "exe")
    name = path.split("\\")[-1]
    api = FakeProcessApi([proc(5, name, path)], [win(1, 5, "AV")], behaviours={1: "stuck"})
    assert closer(api).close(entry).status == "failed"
    assert closer(api).force(entry).status == "failed"
    assert api.terminated == []


def test_file_explorer_closes_folder_windows_but_the_shell_is_never_killed():
    api = FakeProcessApi(
        [proc(500, "explorer.exe", WIN + r"\explorer.exe")],
        [win(30, 500, "Documents", "CabinetWClass"), win(32, 500, "Program Manager", "Progman")])
    out = closer(api).close(EXPLORER)
    assert out.status == "closed" and "1 File Explorer window" in out.message
    assert api.posted == [30]                              # not the desktop (Progman)
    assert api.terminated == [] and [p.pid for p in api.procs] == [500]   # explorer.exe still alive
    forced = closer(api).force(EXPLORER)
    assert forced.status == "failed" and "politely" in forced.message and api.terminated == []


def test_file_explorer_with_several_windows_asks_which():
    api = FakeProcessApi([proc(500, "explorer.exe", WIN + r"\explorer.exe")],
                         [win(30, 500, "A", "CabinetWClass"), win(31, 500, "B", "CabinetWClass")])
    assert closer(api).close(EXPLORER).status == "choose"


def test_file_explorer_with_no_folder_windows():
    api = FakeProcessApi([proc(500, "explorer.exe", WIN + r"\explorer.exe")],
                         [win(32, 500, "Program Manager", "Progman")])
    out = closer(api).close(EXPLORER)
    assert out.status == "not_running" and "no open windows" in out.message and api.posted == []


def test_a_stuck_explorer_window_is_not_force_killed():
    api = FakeProcessApi([proc(500, "explorer.exe", WIN + r"\explorer.exe")],
                         [win(30, 500, "Docs", "CabinetWClass")], behaviours={30: "stuck"})
    out = closer(api).close(EXPLORER)
    assert out.status == "failed" and api.terminated == []


def test_unmatched_processes_are_never_touched_by_close_or_force():
    api = spotify_running(1, behaviour="stuck")
    api.procs += [proc(900, "chrome.exe", CHROME_EXE), proc(901, "notepad.exe", WIN + r"\System32\notepad.exe")]
    api.windows += [win(90, 900, "Chrome"), win(91, 901, "Untitled - Notepad")]
    c = closer(api)
    c.close(SPOTIFY)
    c.force(SPOTIFY)
    assert 90 not in api.posted and 91 not in api.posted
    assert 900 not in api.terminated and 901 not in api.terminated


def test_close_never_matches_apps_by_a_similar_name():
    api = FakeProcessApi([proc(1, "SpotifyHelper.exe", r"C:\Users\me\SpotifyHelper.exe"),
                          proc(2, "Spotify.exe", r"C:\Users\me\Desktop\Spotify.exe")], [])
    assert closer(api).instances(SPOTIFY).procs == []


def test_task_manager_style_never_terminate_entries_refuse_force():
    tm = AppEntry("task-manager", "Task Manager", WIN + r"\System32\Taskmgr.exe", "exe", builtin=True,
                  match_images=("taskmgr.exe",), never_terminate=True)
    api = FakeProcessApi([proc(8, "Taskmgr.exe", WIN + r"\System32\Taskmgr.exe")],
                         [win(1, 8, "Task Manager")], behaviours={1: "stuck"})
    assert closer(api).force(tm).status == "failed" and api.terminated == []
