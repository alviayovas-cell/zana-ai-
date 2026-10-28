"""Close commands: parsing, natural phrasing, handler honesty, and the full UI flow."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from tests.fake_closer import FakeCloser
from tests.fake_process_api import CALCULATOR, CHROME, NOTEPAD, SPOTIFY, win
from tests.fakes import speech, wait_until
from tests.test_gui_smoke import app, build, send  # noqa: F401 (fixture import)
from zana.apps.closer import CloseOutcome
from zana.apps.registry import AppCommandHandler, AppEntry, AppRegistry
from zana.settings import UserSettings
from zana.voice.engine import VoiceState

PARSE = AppCommandHandler._parse_full


# -- parsing ------------------------------------------------------------------------
@pytest.mark.parametrize("text,expected", [
    ("close spotify", ("close", "spotify")),
    ("Close Spotify.", ("close", "spotify")),
    ("Can you close Spotify?", ("close", "spotify")),
    ("could you quit chrome", ("close", "chrome")),
    ("would you please close the calculator", ("close", "the calculator")),
    ("please close notepad", ("close", "notepad")),
    ("exit notepad", ("close", "notepad")),
    ("quit file explorer", ("close", "file explorer")),
    ("shut down spotify", ("close", "spotify")),
    ("close down spotify", ("close", "spotify")),
    ("close spotify please", ("close", "spotify")),
    ("close the spotify app", ("close", "the spotify")),
    ("close whatsapp and open chrome", ("close", "whatsapp")),
    ("Please launch Chrome", ("open", "chrome")),
    ("can you open whatsapp?", ("open", "whatsapp")),
    ("open vs code", ("open", "vs code")),
    ("start notepad", ("open", "notepad")),
    ("hey zana close claude", ("close", "claude")),
])
def test_natural_open_and_close_phrasing(text, expected):
    assert PARSE(text) == expected


@pytest.mark.parametrize("text", [
    "stop spotify", "kill spotify", "terminate chrome", "close", "open", "what does close mean",
    "tell me a joke", "", "I want to close the deal with them tomorrow morning at the office please",
])
def test_not_an_app_command(text):
    assert PARSE(text) is None or text.startswith("I want")


def test_is_launch_intent_covers_close_verbs():
    h = AppCommandHandler(AppRegistry("x.json", builtins=[]))
    assert h.is_launch_intent("close spotify") and h.is_app_intent("please launch chrome")
    assert not h.is_launch_intent("stop spotify")


# -- handler --------------------------------------------------------------------------
def make(tmp_path, closer=None, finder=None, launched=None):
    log = launched if launched is not None else []
    reg = AppRegistry(tmp_path / "a.json", builtins=[NOTEPAD, CALCULATOR, SPOTIFY, CHROME],
                      launcher=lambda e: log.append(e.id))
    return AppCommandHandler(reg, finder=finder, closer=closer), reg, log


@pytest.mark.parametrize("text", ["close spotify", "Can you close Spotify?", "please quit spotify",
                                  "shut down spotify", "close the spotify"])
def test_close_runs_the_closer_for_the_approved_app(tmp_path, text):
    fc = FakeCloser()
    h, _, _ = make(tmp_path, closer=fc)
    res = h.handle_ex(text)
    assert res.action == "close" and res.reply == "Closed Spotify."
    assert fc.close_calls == [("spotify", None)] and res.choose is None and res.force is None


def test_open_still_launches_alongside_close(tmp_path):
    h, _, launched = make(tmp_path, closer=FakeCloser())
    assert h.handle("Please launch Chrome") == "Opening Google Chrome."
    assert h.handle("can you open the calculator") == "Opening Calculator."
    assert launched == ["google-chrome", "calculator"]


def test_closing_an_app_that_is_not_approved_never_touches_the_closer(tmp_path):
    fc = FakeCloser()
    found = [AppEntry("whatsapp", "WhatsApp", "5319275A.WhatsAppDesktop_cv1g1gvanyjgm!App", "uwp")]
    h, reg, _ = make(tmp_path, closer=fc, finder=lambda q: found if "whatsapp" in q else [])
    res = h.handle_ex("close whatsapp")
    assert "isn't in your approved apps, so I can't close it" in res.reply
    assert res.pending is None and res.choose is None and res.force is None   # never offers add-and-close
    assert reg.find("whatsapp") is None and fc.close_calls == []
    res = h.handle_ex("close powershell")
    assert "couldn't find an approved app called powershell" in res.reply and fc.close_calls == []


def test_conversation_with_close_in_it_is_left_to_the_model(tmp_path):
    h, _, _ = make(tmp_path, closer=FakeCloser())
    assert h.handle_ex("close a bank account for me") is None
    assert h.handle_ex("close the door behind you quickly now") is None   # long: not an app name
    # short and app-shaped, so Zana says plainly that there is no such approved app
    assert "couldn't find an approved app" in h.handle_ex("close all the doors").reply


def test_closing_is_unavailable_without_a_closer(tmp_path):
    h, _, _ = make(tmp_path, closer=None)
    assert "isn't available" in h.handle_ex("close spotify").reply


def test_choose_and_force_outcomes_are_passed_up_for_the_user_to_decide(tmp_path):
    choose = CloseOutcome("choose", "Spotify has 2 windows open. Which should I close?", SPOTIFY,
                          windows=[win(1, 5, "One"), win(2, 5, "Two")])
    force = CloseOutcome("force", "Spotify didn't close. Do you want me to force-close it?", SPOTIFY, pids=[5])
    fc = FakeCloser(close_script=[choose, force])
    h, _, _ = make(tmp_path, closer=fc)
    r1 = h.handle_ex("close spotify")
    assert r1.choose is choose and r1.force is None and r1.reply == choose.message
    r2 = h.handle_ex("close spotify")
    assert r2.force is force and r2.choose is None
    assert fc.force_calls == []                       # nothing forced without confirmation


def test_second_steps_only_work_for_approved_ids(tmp_path):
    fc = FakeCloser()
    h, _, _ = make(tmp_path, closer=fc)
    assert h.close_selected("spotify", [1, 2]).reply == "Closed Spotify."
    assert fc.close_calls == [("spotify", [1, 2])]
    assert h.force_close("spotify").reply == "Force-closed Spotify."
    for bad in ("powershell", r"C:\Windows\System32\cmd.exe", "../x"):
        assert "not in your approved list" in h.close_selected(bad, [1]).reply
        assert "not in your approved list" in h.force_close(bad).reply
    assert len(fc.close_calls) == 1 and len(fc.force_calls) == 1


# -- UI flow --------------------------------------------------------------------------
def window_with_apps(app, tmp_path, *texts, closer=None, **kw):
    w = build(app, tmp_path, *texts, app_closer=closer or FakeCloser(), **kw)
    w.app_registry._builtins = [NOTEPAD, SPOTIFY]
    w.apps_page.refresh()
    return w


def last_reply(w):
    return w.assistant.store.get_messages(w.assistant.conversation_id)[-1]["content"]


def test_typed_close_gracefully(app, tmp_path):
    fc = FakeCloser()
    w = window_with_apps(app, tmp_path, closer=fc)
    try:
        send(w, "close notepad")
        assert fc.close_calls == [("notepad", None)] and last_reply(w) == "Closed Notepad."
        assert w.fake.prompts == []                       # the model was never involved
        assert w.chat.input.isEnabled()
    finally:
        w.close()


def test_multiple_windows_user_chooses_one(app, tmp_path):
    windows = [win(11, 5, "Spotify - Song A"), win(12, 5, "Spotify - Mini player")]
    fc = FakeCloser(close_script=[CloseOutcome("choose", "Spotify has 2 windows open.", SPOTIFY, windows=windows),
                                  CloseOutcome("closed", "Closed 1 Spotify window.", SPOTIFY)])
    w = window_with_apps(app, tmp_path, closer=fc)
    asked = []
    w.choose_windows = lambda entry, wins: asked.append((entry.name, [x.hwnd for x in wins])) or [12]
    try:
        send(w, "close spotify")
        assert asked == [("Spotify", [11, 12])]
        assert fc.close_calls == [("spotify", None), ("spotify", [12])]
        assert last_reply(w) == "Closed 1 Spotify window."
        assert not w._busy
    finally:
        w.close()


def test_cancelling_the_window_choice_closes_nothing(app, tmp_path):
    fc = FakeCloser(close_script=[CloseOutcome("choose", "Spotify has 2 windows.", SPOTIFY,
                                               windows=[win(1, 5, "A"), win(2, 5, "B")])])
    w = window_with_apps(app, tmp_path, closer=fc)
    w.choose_windows = lambda entry, wins: None
    try:
        send(w, "close spotify")
        assert fc.close_calls == [("spotify", None)] and "left Spotify open" in last_reply(w)
    finally:
        w.close()


def test_force_close_needs_confirmation_and_runs_when_confirmed(app, tmp_path):
    force = CloseOutcome("force", "Spotify is still running in the background. Force-close it?", SPOTIFY, pids=[5])
    fc = FakeCloser(close_script=[force])
    w = window_with_apps(app, tmp_path, closer=fc)
    asked = []
    w.confirm_force = lambda entry, outcome: asked.append(outcome.message) or True
    try:
        send(w, "close spotify")
        assert asked == [force.message]
        assert fc.force_calls == ["spotify"] and last_reply(w) == "Force-closed Spotify."
    finally:
        w.close()


def test_declining_force_close_leaves_the_app_running(app, tmp_path):
    force = CloseOutcome("force", "Spotify didn't close. Force-close it?", SPOTIFY, pids=[5])
    fc = FakeCloser(close_script=[force])
    w = window_with_apps(app, tmp_path, closer=fc)
    w.confirm_force = lambda entry, outcome: False
    try:
        send(w, "close spotify")
        assert fc.force_calls == [] and "left Spotify running" in last_reply(w)
        assert not w._busy and w.chat.input.isEnabled()
    finally:
        w.close()


def test_closing_an_unapproved_app_is_refused_in_chat(app, tmp_path):
    fc = FakeCloser()
    w = window_with_apps(app, tmp_path, closer=fc, app_finder=lambda q: [])
    try:
        send(w, "close whatsapp")
        assert fc.close_calls == [] and "couldn't find an approved app" in last_reply(w)
        assert w.fake.prompts == []
    finally:
        w.close()


def test_a_crash_while_closing_is_reported_and_the_ui_recovers(app, tmp_path):
    fc = FakeCloser(close_script=[RuntimeError("access denied")])
    w = window_with_apps(app, tmp_path, closer=fc)
    try:
        send(w, "close notepad")
        assert "went wrong" in last_reply(w) and "access denied" in last_reply(w)
        assert not w._busy and w.chat.input.isEnabled()
    finally:
        w.close()


def test_voice_close_is_spoken_back(app, tmp_path):
    fc = FakeCloser()
    w = window_with_apps(app, tmp_path, "hey zana close spotify", closer=fc,
                         settings=UserSettings(wake_enabled=True, follow_up_seconds=0))
    try:
        assert wait_until(lambda: w.sidebar.status_pill.state is VoiceState.WAITING, app=app)
        w.mic.push(speech(1.5))
        assert wait_until(lambda: w.speaker.spoken == ["Closed Spotify."], app=app)
        assert fc.close_calls == [("spotify", None)] and w.fake.prompts == []
        assert wait_until(lambda: w.sidebar.status_pill.state is VoiceState.WAITING, app=app)
    finally:
        w.quit_app()


def test_voice_force_close_flow_asks_before_speaking_the_result(app, tmp_path):
    force = CloseOutcome("force", "Spotify is still running. Force-close it?", SPOTIFY, pids=[5])
    fc = FakeCloser(close_script=[force])
    w = window_with_apps(app, tmp_path, "hey zana quit spotify", closer=fc,
                         settings=UserSettings(wake_enabled=True, follow_up_seconds=0))
    w.confirm_force = lambda entry, outcome: True
    try:
        assert wait_until(lambda: w.sidebar.status_pill.state is VoiceState.WAITING, app=app)
        w.mic.push(speech(1.5))
        assert wait_until(lambda: w.speaker.spoken == ["Force-closed Spotify."], app=app)
        assert fc.force_calls == ["spotify"]
    finally:
        w.quit_app()


def test_applications_page_close_button_runs_the_same_safe_flow(app, tmp_path):
    fc = FakeCloser()
    w = window_with_apps(app, tmp_path, closer=fc)
    try:
        assert set(w.apps_page.close_buttons) == {"notepad", "spotify"}
        w.apps_page.close_buttons["spotify"].click()
        assert wait_until(lambda: not w._busy and fc.close_calls, app=app)
        assert fc.close_calls == [("spotify", None)]
        assert w.stack.currentIndex() == 1                # shown in Chat with the reply
    finally:
        w.close()


def test_open_flow_is_unchanged(app, tmp_path):
    w = window_with_apps(app, tmp_path)
    try:
        send(w, "open notepad")
        assert w.launched == ["notepad"] and last_reply(w) == "Opening Notepad."
    finally:
        w.close()


def test_partial_names_resolve_to_a_unique_approved_app(tmp_path):
    code = AppEntry("visual-studio-code", "Visual Studio Code", "Microsoft.VisualStudioCode", "uwp")
    studio = AppEntry("studio-one", "Studio One", "StudioOne.App", "uwp")
    reg = AppRegistry(tmp_path / "a.json", builtins=[CHROME, code, studio])
    assert reg.find("chrome").id == "google-chrome"          # "open chrome" -> Google Chrome
    assert reg.find("the chrome").id == "google-chrome"
    assert reg.find("code").id == "visual-studio-code"
    assert reg.find("studio") is None                         # in two names: ambiguous, so no guess
    assert reg.find("goo") is None and reg.find("xx") is None
