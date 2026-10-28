"""Hands-free behaviour: follow-up conversation, echo guard, mic recovery, pause, saved settings."""

import json
import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from tests.fake_tray import FakeTray
from tests.fakes import FakeMic, speech, wait_until
from tests.test_engine import Harness
from tests.test_gui_smoke import FakeStartup, app, build  # noqa: F401 (fixture import)
from zana.settings import UserSettings
from zana.voice.engine import VoiceEngine, VoiceState
from zana.voice.mic import MicError


@pytest.fixture()
def make():
    made = []

    def _make(*a, **kw):
        h = Harness(*a, **kw)
        made.append(h)
        return h

    yield _make
    for h in made:
        h.engine.stop()


def wake_up(h):
    h.engine.start()
    assert wait_until(lambda: h.state() is VoiceState.WAITING)


# -- follow-up conversation (no "Hey Zana" for every sentence) ---------------------
def test_conversation_continues_without_wake_phrase_then_ends(make):
    h = make("hey zana", "what is two plus two", "and times three", "thanks", "random chatter",
             follow_up_seconds=5, resume_guard_s=0.0)
    wake_up(h)
    h.mic.push(speech(0.8))
    assert wait_until(lambda: h.state() is VoiceState.LISTENING)
    h.mic.push(speech(1.2))
    assert wait_until(lambda: h.commands == ["what is two plus two"])
    h.engine.resume()                                   # reply finished
    assert wait_until(lambda: h.state() is VoiceState.LISTENING)   # follow-up window open
    h.mic.push(speech(1.2))                              # no wake phrase this time
    assert wait_until(lambda: h.commands[-1:] == ["and times three"])
    h.engine.resume()
    assert wait_until(lambda: h.state() is VoiceState.LISTENING)
    h.mic.push(speech(1.0))                              # "thanks" ends the conversation
    assert wait_until(lambda: h.state() is VoiceState.WAITING)
    assert h.commands == ["what is two plus two", "and times three"]
    h.mic.push(speech(1.0))                              # chatter now needs the wake phrase
    assert wait_until(lambda: h.engine._transcriber.calls == 4)
    assert len(h.commands) == 2 and h.state() is VoiceState.WAITING


def test_follow_up_window_times_out_back_to_wake_phrase(make):
    h = make("hey zana weather", "background chatter", follow_up_seconds=0.3, resume_guard_s=0.0)
    wake_up(h)
    h.mic.push(speech(1.5))
    assert wait_until(lambda: h.commands == ["weather"])
    h.engine.resume()
    assert wait_until(lambda: h.state() is VoiceState.LISTENING)
    assert wait_until(lambda: h.state() is VoiceState.WAITING)       # inactivity timeout
    h.mic.push(speech(1.0))                                           # needs "Hey Zana" again
    assert wait_until(lambda: h.engine._transcriber.calls == 2)
    assert h.commands == ["weather"]


def test_follow_up_can_be_disabled(make):
    h = make("hey zana weather", "what about paris", follow_up_seconds=0, resume_guard_s=0.0)
    wake_up(h)
    h.mic.push(speech(1.5))
    assert wait_until(lambda: h.commands == ["weather"])
    h.engine.resume()
    assert wait_until(lambda: h.state() is VoiceState.WAITING)
    h.mic.push(speech(1.0))
    assert wait_until(lambda: h.engine._transcriber.calls == 2)
    assert h.commands == ["weather"]


def test_wake_phrase_inside_a_conversation_is_stripped(make):
    h = make("hey zana weather", "hey zana what about paris", follow_up_seconds=5, resume_guard_s=0.0)
    wake_up(h)
    h.mic.push(speech(1.5))
    assert wait_until(lambda: h.commands == ["weather"])
    h.engine.resume()
    assert wait_until(lambda: h.state() is VoiceState.LISTENING)
    h.mic.push(speech(1.5))
    assert wait_until(lambda: h.commands == ["weather", "what about paris"])


def test_push_to_talk_never_opens_a_follow_up_window(make):
    h = make("open the calculator", wake=False, follow_up_seconds=5, resume_guard_s=0.0)
    h.engine.request_command()
    assert wait_until(lambda: h.state() is VoiceState.LISTENING)
    h.mic.push(speech(1.0))
    assert wait_until(lambda: h.commands == ["open the calculator"])
    h.engine.resume()
    assert wait_until(lambda: not h.engine.running)
    assert h.state() is VoiceState.OFF


# -- not hearing itself -----------------------------------------------------------
def test_ignores_audio_while_processing_and_speaking(make):
    h = make("hey zana weather", "hey zana time", follow_up_seconds=0, resume_guard_s=0.0)
    wake_up(h)
    h.mic.push(speech(1.5))
    assert wait_until(lambda: h.commands == ["weather"])
    assert h.state() is VoiceState.BUSY
    h.mic.push(speech(1.5))              # Zana's own voice while the reply plays
    time.sleep(0.3)
    assert h.engine._transcriber.calls == 1        # never even transcribed
    h.engine.resume()
    assert wait_until(lambda: h.state() is VoiceState.WAITING)
    time.sleep(0.2)
    assert h.engine._transcriber.calls == 1 and h.commands == ["weather"]   # old audio was discarded
    h.mic.push(speech(1.5))              # a real new command is still heard
    assert wait_until(lambda: h.commands == ["weather", "time"])


def test_echo_guard_drops_the_tail_of_the_reply(make):
    h = make("hey zana weather", "hey zana time", follow_up_seconds=0, resume_guard_s=0.5)
    wake_up(h)
    h.mic.push(speech(1.5))
    assert wait_until(lambda: h.commands == ["weather"])
    h.engine.resume()
    h.mic.push(speech(1.0))              # reverb right after the reply: inside the guard
    time.sleep(0.2)
    assert h.engine._transcriber.calls == 1
    time.sleep(0.6)                       # guard over
    h.mic.push(speech(1.5))
    assert wait_until(lambda: h.commands == ["weather", "time"])


# -- listener recovery -------------------------------------------------------------
def test_recovers_when_the_microphone_disappears(make):
    first, second = FakeMic(die_after=40), FakeMic()
    mics = [first, second]
    h = make("hey zana weather", mic_factory=lambda: mics.pop(0), no_frame_timeout_s=0.15,
             recover_delay_s=0.02, resume_guard_s=0.0)
    seen = []
    h.engine._on_state = lambda s, d: (seen.append(s), h.states.append(s))
    wake_up(h)
    assert wait_until(lambda: VoiceState.STARTING in seen[1:])        # noticed and reconnecting
    assert wait_until(lambda: h.state() is VoiceState.WAITING and first.stopped)
    second.push(speech(1.5))                                          # the new device works
    assert wait_until(lambda: h.commands == ["weather"])


def test_gives_up_with_a_clear_error_when_the_device_never_returns(make):
    calls = []

    def factory():
        calls.append(1)
        if len(calls) == 1:
            return FakeMic(die_after=30)
        raise MicError("device unplugged")

    h = make(mic_factory=factory, no_frame_timeout_s=0.1, recover_attempts=2, recover_delay_s=0.01)
    h.engine.start()
    assert wait_until(lambda: h.state() is VoiceState.ERROR)
    assert len(calls) == 3                      # 1 original + 2 recovery attempts
    assert not h.engine.running


def test_never_runs_two_listeners_at_once(make):
    opened = []

    def factory():
        opened.append(1)
        return FakeMic()

    h = make(mic_factory=factory)
    for _ in range(5):
        h.engine.start()
    assert wait_until(lambda: h.state() is VoiceState.WAITING)
    assert len(opened) == 1
    h.engine.stop()
    h.engine.start()
    assert wait_until(lambda: h.state() is VoiceState.WAITING)
    assert len(opened) == 2


# -- settings ---------------------------------------------------------------------
def test_settings_roundtrip_and_validation(tmp_path):
    p = tmp_path / "s.json"
    UserSettings(wake_enabled=True, launch_at_startup=True, close_to_tray=True, follow_up_seconds=12,
                 onboarding_done=True).save(p)
    s = UserSettings.load(p)
    assert (s.wake_enabled, s.launch_at_startup, s.close_to_tray, s.follow_up_seconds,
            s.onboarding_done) == (True, True, True, 12, True)
    p.write_text(json.dumps({"follow_up_seconds": 999, "wake_enabled": True}))
    assert UserSettings.load(p).follow_up_seconds == 60 and UserSettings.load(p).wake_enabled
    for bad in ({"follow_up_seconds": "5"}, {"follow_up_seconds": True}, {"wake_enabled": 1},
                {"follow_up_seconds": -3}, ["x"], 5):
        p.write_text(json.dumps(bad))
        loaded = UserSettings.load(p)
        assert loaded.wake_enabled is False and loaded.follow_up_seconds in (0, 8)
    p.write_text("not json")
    assert UserSettings.load(p) == UserSettings()


def test_defaults_are_conservative():
    s = UserSettings()
    assert not s.wake_enabled and not s.launch_at_startup and not s.close_to_tray
    assert s.follow_up_seconds == 8 and not s.onboarding_done


def test_one_click_hands_free_turns_everything_on_and_persists(app, tmp_path):
    startup = FakeStartup()
    w = build(app, tmp_path, tray=FakeTray(), startup_api=startup)
    try:
        w.settings_page.hands_free_button.click()
        assert wait_until(lambda: w.sidebar.status_pill.state is VoiceState.WAITING, app=app)
        assert startup.calls == ["enable"]
        saved = UserSettings.load(tmp_path / "s.json")
        assert saved.wake_enabled and saved.launch_at_startup and saved.close_to_tray
        assert saved.onboarding_done
    finally:
        w.quit_app()


def test_saved_preferences_are_respected_after_restart(app, tmp_path):
    w = build(app, tmp_path, tray=FakeTray())
    w.settings_page.hands_free_button.click()
    w.settings_page.follow_up_spin.setValue(15)
    assert wait_until(lambda: w.sidebar.status_pill.state is VoiceState.WAITING, app=app)
    w.quit_app()
    # "Restart": a brand-new window that only knows what was saved on disk.
    saved = UserSettings.load(tmp_path / "s.json")
    w2 = build(app, tmp_path, tray=FakeTray(), settings=saved)
    try:
        assert wait_until(lambda: w2.sidebar.status_pill.state is VoiceState.WAITING, app=app)
        page = w2.settings_page
        assert page.wake_check.isChecked() and page.startup_check.isChecked()
        assert page.tray_check.isChecked() and page.follow_up_spin.value() == 15
        assert w2.voice.engine._follow_up_s == 15
    finally:
        w2.quit_app()


def test_first_run_offer_asks_once(app, tmp_path):
    w = build(app, tmp_path, tray=FakeTray())
    asked = []
    w.confirm_hands_free = lambda: asked.append(1) or True
    try:
        w.maybe_offer_hands_free()
        assert asked == [1]
        assert w.settings_page.wake_check.isChecked() and w.settings_page.tray_check.isChecked()
        w.maybe_offer_hands_free()
        assert asked == [1]                              # never nags again
    finally:
        w.quit_app()


def test_declining_the_offer_changes_nothing_and_is_remembered(app, tmp_path):
    w = build(app, tmp_path, tray=FakeTray())
    w.confirm_hands_free = lambda: False
    try:
        w.maybe_offer_hands_free()
        assert not w.settings.wake_enabled and not w.settings.launch_at_startup
        assert UserSettings.load(tmp_path / "s.json").onboarding_done is True
        assert w.voice.engine.running is False
    finally:
        w.quit_app()


def test_no_offer_when_already_fully_enabled(app, tmp_path):
    s = UserSettings(wake_enabled=True, launch_at_startup=True, close_to_tray=True, follow_up_seconds=0)
    w = build(app, tmp_path, tray=FakeTray(), settings=s)

    def must_not_ask():
        raise AssertionError("should not ask")

    w.confirm_hands_free = must_not_ask
    try:
        w.maybe_offer_hands_free()
        assert w.settings.onboarding_done
    finally:
        w.quit_app()


# -- pause / resume / tray / status -----------------------------------------------
def test_tray_pause_resume_closes_and_reopens_the_microphone(app, tmp_path):
    tray = FakeTray()
    w = build(app, tmp_path, tray=tray, settings=UserSettings(wake_enabled=True, follow_up_seconds=0))
    try:
        assert wait_until(lambda: w.sidebar.status_pill.state is VoiceState.WAITING, app=app)
        assert tray.pause_available and not tray.paused
        first_mic = w.mic
        tray.pause_toggled.emit()
        assert wait_until(lambda: w.sidebar.status_pill.state is VoiceState.PAUSED, app=app)
        assert w.sidebar.status_pill.text() == "Paused"
        assert tray.paused and first_mic.stopped and not w.voice.engine.running   # not listening
        tray.pause_toggled.emit()                                                  # resume
        assert wait_until(lambda: w.sidebar.status_pill.state is VoiceState.WAITING, app=app)
        assert not tray.paused and w.voice.engine.running
        assert "Hey Zana" in w.sidebar.status_pill.text()
    finally:
        w.quit_app()


def test_pause_is_unavailable_when_listening_is_off(app, tmp_path):
    tray = FakeTray()
    w = build(app, tmp_path, tray=tray)
    try:
        assert not tray.pause_available
        tray.pause_toggled.emit()                       # ignored
        assert not w.voice.user_paused and w.sidebar.status_pill.state is VoiceState.OFF
    finally:
        w.quit_app()


def test_a_reply_finishing_while_paused_does_not_reopen_the_mic(app, tmp_path):
    tray = FakeTray()
    w = build(app, tmp_path, "hey zana weather", tray=tray,
              settings=UserSettings(wake_enabled=True, follow_up_seconds=0))
    try:
        assert wait_until(lambda: w.sidebar.status_pill.state is VoiceState.WAITING, app=app)
        w.voice.pause_listening()
        w.voice.resume()                                 # e.g. speech_finished arriving late
        time.sleep(0.2)
        assert not w.voice.engine.running and w.voice.user_paused
    finally:
        w.quit_app()


def test_status_labels_cover_listening_processing_speaking_paused(app, tmp_path):
    from zana.ui.status_pill import StatusPill
    pill = StatusPill()
    texts = {}
    for st in (VoiceState.WAITING, VoiceState.LISTENING, VoiceState.TRANSCRIBING, VoiceState.BUSY,
               VoiceState.SPEAKING, VoiceState.PAUSED):
        pill.set_state(st)
        texts[st] = pill.text()
    assert "Listening" in texts[VoiceState.WAITING] and "Listening" in texts[VoiceState.LISTENING]
    assert texts[VoiceState.TRANSCRIBING] == texts[VoiceState.BUSY] == "Processing…"
    assert texts[VoiceState.SPEAKING] == "Speaking…" and texts[VoiceState.PAUSED] == "Paused"


def test_exiting_stops_listening_completely(app, tmp_path):
    tray = FakeTray()
    w = build(app, tmp_path, tray=tray, settings=UserSettings(wake_enabled=True, follow_up_seconds=0))
    assert wait_until(lambda: w.sidebar.status_pill.state is VoiceState.WAITING, app=app)
    mic = w.mic
    tray.exit_requested.emit()
    assert not w.voice.engine.running and mic.stopped


# -- the whole loop through the window ---------------------------------------------
def test_follow_up_conversation_through_the_window_and_no_self_hearing(app, tmp_path):
    w = build(app, tmp_path, "hey zana what is two plus two", "and times three",
              tray=FakeTray(), settings=UserSettings(wake_enabled=True, follow_up_seconds=5))
    w.voice.engine._resume_guard_s = 0.0
    # Zana "hears herself" while speaking each reply; that must never be treated as a command.
    w.speaker.on_speak = lambda: w.mic.push(speech(1.0))
    try:
        assert wait_until(lambda: w.sidebar.status_pill.state is VoiceState.WAITING, app=app)
        w.mic.push(speech(1.5))
        assert wait_until(lambda: w.speaker.spoken == ["Hi friend"], app=app)
        assert wait_until(lambda: w.sidebar.status_pill.state is VoiceState.LISTENING, app=app)
        w.mic.push(speech(1.2))                          # second question, no wake phrase
        assert wait_until(lambda: len(w.speaker.spoken) == 2, app=app)
        assert w.fake.prompts == ["what is two plus two", "and times three"]
        assert w.voice.engine._transcriber.calls == 2    # her own two replies were never transcribed
    finally:
        w.quit_app()


def test_listener_recovers_in_the_window_and_keeps_the_saved_preference(app, tmp_path):
    seq = [FakeMic(die_after=25), None, FakeMic()]       # dies; first reopen fails; UI retry works
    created = []

    def factory():
        created.append(1)
        nxt = seq[len(created) - 1]
        if nxt is None:
            raise MicError("audio device busy")
        return nxt

    tray = FakeTray()
    w = build(app, tmp_path, tray=tray, mic_factory=factory, settings=UserSettings(wake_enabled=True),
              startup_retry_ms=30, runtime_retries=5, runtime_retry_ms=30)
    w.voice.engine._no_frame_timeout = 0.1
    w.voice.engine._recover_attempts = 1
    w.voice.engine._recover_delay = 0.01
    try:
        assert wait_until(lambda: len(created) == 3 and w.sidebar.status_pill.state is VoiceState.WAITING,
                          timeout=15, app=app)
        assert w.settings.wake_enabled and w.settings_page.wake_check.isChecked()
        assert not [t for t in tray.notes if "unavailable" in t[0]]
    finally:
        w.quit_app()


def test_nothing_reopens_the_microphone_after_exit(app, tmp_path):
    # A pending "retry the microphone" timer must not revive the listener after Zana exits.
    mics = []

    def factory():
        mics.append(1)
        return FakeMic(fail_on_start=MicError("device busy"))

    w = build(app, tmp_path, tray=FakeTray(), mic_factory=factory, settings=UserSettings(wake_enabled=True),
              startup_retries=5, startup_retry_ms=150)
    assert wait_until(lambda: len(mics) >= 1, app=app)
    w.quit_app()                                   # user exits while a retry is pending
    attempts = len(mics)
    deadline = time.monotonic() + 0.8
    while time.monotonic() < deadline:             # let the pending timer fire
        app.processEvents()
        time.sleep(0.02)
    assert len(mics) == attempts and not w.voice.engine.running
    w.voice.set_wake_enabled(True)                 # even a direct request is refused after shutdown
    w.voice.push_to_talk()
    assert not w.voice.engine.running and len(mics) == attempts
