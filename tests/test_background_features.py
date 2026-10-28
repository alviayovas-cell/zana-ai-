"""Startup, tray, ready/retry and app-approval behaviour of the main window."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from tests.fake_tray import FakeTray
from tests.fakes import FakeMic, speech, wait_until
from tests.test_gui_smoke import FakeStartup, app, build, send  # noqa: F401 (fixture import)
from zana.apps.discovery import find_candidates
from zana.settings import UserSettings
from zana.startup import StartupError
from zana.voice.engine import VoiceState
from zana.voice.mic import MicError

WHATSAPP = "5319275A.WhatsAppDesktop_cv1g1gvanyjgm!App"
FAKE_START_APPS = [("WhatsApp", WHATSAPP), ("Windows PowerShell", "Microsoft.PowerShell_8wekyb3d8bbwe!App")]


def finder(q):
    return find_candidates(q, lambda: FAKE_START_APPS)


def pill(w):
    return w.sidebar.status_pill.state


# -- start with Windows ------------------------------------------------------
def test_startup_toggle_is_off_by_default_and_persists(app, tmp_path):
    w = build(app, tmp_path)
    try:
        assert not w.settings_page.startup_check.isChecked()
        assert w.startup_api.calls == []
        w.settings_page.startup_check.setChecked(True)
        assert w.startup_api.calls == ["enable"]
        assert UserSettings.load(tmp_path / "s.json").launch_at_startup is True
        assert "sign in" in w.settings_page.background_message.text()
        w.settings_page.startup_check.setChecked(False)
        assert w.startup_api.calls == ["enable", "disable"]
        assert UserSettings.load(tmp_path / "s.json").launch_at_startup is False
    finally:
        w.close()


def test_startup_toggle_failure_reverts_and_explains(app, tmp_path):
    w = build(app, tmp_path, startup_api=FakeStartup(fail=StartupError("Windows refused")))
    try:
        w.settings_page.startup_check.setChecked(True)
        assert not w.settings_page.startup_check.isChecked()
        assert "Windows refused" in w.settings_page.background_message.text()
        assert UserSettings.load(tmp_path / "s.json").launch_at_startup is False
    finally:
        w.close()


# -- tray / background ---------------------------------------------------------
def test_close_without_tray_setting_exits(app, tmp_path):
    tray = FakeTray()
    w = build(app, tmp_path, tray=tray)
    w.close()
    assert not w.isVisible() and not tray.shown


def test_close_to_tray_keeps_running_and_listening(app, tmp_path):
    tray = FakeTray()
    w = build(app, tmp_path, "hey zana tell me a joke", tray=tray)
    try:
        w.settings_page.tray_check.setChecked(True)
        assert UserSettings.load(tmp_path / "s.json").close_to_tray is True
        w.settings_page.wake_check.setChecked(True)
        assert wait_until(lambda: pill(w) is VoiceState.WAITING, app=app)
        w.close()                                    # user closes the window
        assert not w.isVisible() and tray.shown      # hidden, tray icon remains
        assert any("still running" in t[0] for t in tray.notes)
        assert w.voice.engine.running                # listener keeps running
        w.mic.push(speech(1.5))                      # ...and still hears the wake phrase
        assert wait_until(lambda: w.speaker.spoken == ["Hi friend"], app=app)
        tray.open_requested.emit()                   # tray > Open Zana
        assert w.isVisible()
        tray.exit_requested.emit()                   # tray > Exit Zana
        assert not w.isVisible() and not tray.shown
        assert not w.voice.engine.running and w.mic.stopped
    finally:
        w.quit_app()


def test_tray_status_follows_listening_state(app, tmp_path):
    tray = FakeTray()
    w = build(app, tmp_path, tray=tray)
    try:
        w.settings_page.wake_check.setChecked(True)
        assert wait_until(lambda: "Hey Zana" in tray.status, app=app)
    finally:
        w.close()


def test_tray_setting_warns_when_tray_unavailable(app, tmp_path):
    w = build(app, tmp_path)  # tray=None
    try:
        w.settings_page.tray_check.setChecked(True)
        assert "isn't available" in w.settings_page.background_message.text()
    finally:
        w.close()


# -- startup reliability ---------------------------------------------------------
def test_ready_reported_only_after_microphone_is_listening(app, tmp_path):
    tray = FakeTray()
    w = build(app, tmp_path, tray=tray, settings=UserSettings(wake_enabled=True))
    w.background_start = True
    try:
        assert not w.ready  # nothing is reported before the mic is up
        assert wait_until(lambda: w.ready, app=app)
        assert pill(w) is VoiceState.WAITING
        assert [t for t in tray.notes if t[0] == "Zana is ready"]
    finally:
        w.close()


def test_ready_immediately_when_listening_disabled(app, tmp_path):
    w = build(app, tmp_path)
    try:
        assert wait_until(lambda: w.ready, app=app)
        assert pill(w) is VoiceState.OFF
    finally:
        w.close()


def test_wake_listener_autostarts_from_saved_setting(app, tmp_path):
    w = build(app, tmp_path, settings=UserSettings(wake_enabled=True))
    try:
        assert wait_until(lambda: pill(w) is VoiceState.WAITING, app=app)
        assert w.settings_page.wake_check.isChecked()
    finally:
        w.close()


def test_startup_retries_until_microphone_is_available(app, tmp_path):
    attempts = []

    def flaky():
        attempts.append(1)
        return FakeMic(fail_on_start=MicError("audio service not ready")) if len(attempts) < 3 else FakeMic()

    tray = FakeTray()
    w = build(app, tmp_path, tray=tray, mic_factory=flaky, startup_retry_ms=30,
              settings=UserSettings(wake_enabled=True))
    w.background_start = True
    try:
        assert wait_until(lambda: pill(w) is VoiceState.WAITING, app=app)
        assert len(attempts) == 3
        assert w.settings.wake_enabled and w.settings_page.wake_check.isChecked()
        assert [t for t in tray.notes if t[0] == "Zana is ready"]
        assert not [t for t in tray.notes if "unavailable" in t[0]]
    finally:
        w.close()


def test_startup_gives_up_safely_but_remembers_choice(app, tmp_path):
    tray = FakeTray()

    def broken():
        return FakeMic(fail_on_start=MicError("no microphone"))

    UserSettings(wake_enabled=True).save(tmp_path / "s.json")
    w = build(app, tmp_path, tray=tray, mic_factory=broken, startup_retries=2, startup_retry_ms=20,
              settings=UserSettings(wake_enabled=True))
    try:
        assert wait_until(lambda: pill(w) is VoiceState.ERROR, app=app)
        assert "no microphone" in w.settings_page.status_label.text()
        assert not w.settings_page.wake_check.isChecked()   # UI shows reality
        assert w.ready                                       # app is still usable
        assert [t for t in tray.notes if "unavailable" in t[0]]
        assert UserSettings.load(tmp_path / "s.json").wake_enabled is True  # choice kept
    finally:
        w.close()


# -- approving apps (WhatsApp etc.) -----------------------------------------------
def test_unapproved_app_asks_approval_then_adds_and_launches(app, tmp_path):
    w = build(app, tmp_path, app_finder=finder)
    asked = []
    w.confirm_app = lambda e: asked.append(e.name) or True
    try:
        send(w, "open whatsapp")
        assert asked == ["WhatsApp"]
        assert w.launched == ["whatsapp"] and w.fake.prompts == []
        assert w.app_registry.find("whatsapp") is not None
        assert "whatsapp" in w.apps_page.launch_buttons
        msgs = w.assistant.store.get_messages(w.assistant.conversation_id)
        assert msgs[-1]["content"] == "Opening WhatsApp."
        send(w, "open whatsapp")  # now approved: no second question
        assert asked == ["WhatsApp"] and w.launched == ["whatsapp", "whatsapp"]
    finally:
        w.close()


def test_declined_app_is_not_added_or_launched(app, tmp_path):
    w = build(app, tmp_path, app_finder=finder)
    w.confirm_app = lambda e: False
    try:
        send(w, "open whatsapp")
        assert w.launched == [] and w.app_registry.find("whatsapp") is None
        msgs = w.assistant.store.get_messages(w.assistant.conversation_id)
        assert "won't add WhatsApp" in msgs[-1]["content"]
    finally:
        w.close()


def test_blocked_app_never_even_asks(app, tmp_path):
    w = build(app, tmp_path, app_finder=finder)

    def must_not_ask(entry):
        raise AssertionError("must not ask about PowerShell")

    w.confirm_app = must_not_ask
    try:
        send(w, "open powershell")
        assert w.launched == [] and w.fake.prompts == []   # the model is never asked to improvise
        msgs = w.assistant.store.get_messages(w.assistant.conversation_id)
        assert "couldn't find an app" in msgs[-1]["content"]
    finally:
        w.close()


def test_voice_open_whatsapp_asks_then_speaks(app, tmp_path):
    w = build(app, tmp_path, "hey zana open whatsapp", app_finder=finder)
    w.confirm_app = lambda e: True
    try:
        w.settings_page.wake_check.setChecked(True)
        assert wait_until(lambda: pill(w) is VoiceState.WAITING, app=app)
        w.mic.push(speech(1.5))
        assert wait_until(lambda: w.speaker.spoken == ["Opening WhatsApp."], app=app)
        assert w.launched == ["whatsapp"]
        assert wait_until(lambda: pill(w) is VoiceState.WAITING, app=app)
    finally:
        w.close()


def test_applications_page_find_and_approve(app, tmp_path):
    w = build(app, tmp_path, app_finder=finder)
    try:
        found = w.apps_page.suggest("whatsapp")
        assert [e.name for e in found] == ["WhatsApp"]
        assert not w.apps_page.approve(found[0], lambda e: False)
        assert w.app_registry.find("whatsapp") is None
        assert w.apps_page.approve(found[0], lambda e: True)
        assert "whatsapp" in w.apps_page.launch_buttons
        assert w.apps_page.suggest("whatsapp") == []  # already approved
    finally:
        w.close()
