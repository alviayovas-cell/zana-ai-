"""GUI tests; run headless with the Qt offscreen platform and fake audio."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from tests.fakes import FakeMic, FakeSpeaker, FakeTranscriber, speech, wait_until
from zana.core.assistant import Assistant
from zana.core.ollama_client import OllamaError
from zana.settings import UserSettings
from zana.storage.history import HistoryStore
from zana.ui.main_window import MainWindow
from zana.ui.sidebar import PAGES
from zana.ui.theme import STYLESHEET
from zana.ui.visualizer import VisualizerState
from zana.ui.voice_bridge import VoiceBridge
from zana.voice.engine import VoiceState
from zana.voice.mic import MicError


class FakeClient:
    def __init__(self):
        self.error = None
        self.prompts = []

    def stream_chat(self, messages, cancel=None):
        self.prompts.append(messages[-1]["content"])
        if self.error:
            raise self.error
        yield "Hi "
        yield "friend"


@pytest.fixture(scope="module")
def app():
    a = QApplication.instance() or QApplication([])
    a.setStyleSheet(STYLESHEET)
    return a


def _forbid_launch(entry):
    raise AssertionError(f"test tried to launch a real app: {entry.name}")


def build(app, tmp_path, *texts, mic=None, mic_factory=None, settings=None, **window_kw):
    client, speaker = FakeClient(), FakeSpeaker()
    fake_mic = mic or FakeMic()
    voice = VoiceBridge(mic_factory=mic_factory or (lambda: fake_mic),
                        transcriber=FakeTranscriber(*texts), speaker=speaker)
    # Never use the real launcher, discovery or registry in tests.
    from zana.apps.registry import AppRegistry
    launched = []
    reg = AppRegistry(tmp_path / "apps.json", builtins=[], launcher=lambda e: launched.append(e.id))
    window_kw.setdefault("app_finder", lambda q: [])
    window_kw.setdefault("tray", None)
    window_kw.setdefault("startup_api", FakeStartup())
    from tests.fake_closer import FakeCloser   # no test may ever touch a real process
    window_kw.setdefault("app_closer", FakeCloser())
    w = MainWindow(
        Assistant(client, HistoryStore(tmp_path / "t.db")),
        voice=voice, settings=settings or UserSettings(follow_up_seconds=0),
        settings_path=tmp_path / "s.json",
        app_registry=reg, **window_kw,
    )
    w.fake, w.speaker, w.mic, w.launched = client, speaker, fake_mic, launched
    w.show()
    return w


class FakeStartup:
    def __init__(self, fail=None):
        self.calls, self.fail = [], fail

    def enable(self):
        if self.fail:
            raise self.fail
        self.calls.append("enable")

    def disable(self):
        if self.fail:
            raise self.fail
        self.calls.append("disable")


@pytest.fixture()
def window(app, tmp_path):
    w = build(app, tmp_path, "tell me a joke")
    yield w
    w.close()


def send(w, text):
    w.chat.input.setText(text)
    w.chat.send_button.click()
    assert wait_until(lambda: not w._busy, timeout=20, app=QApplication.instance())
    assert w.wait_for_chat()
    QApplication.processEvents()


def test_sidebar_has_required_pages(window):
    assert PAGES == ("Home", "Chat", "Applications", "Memory", "Settings")
    assert window.stack.count() == len(PAGES)


def test_sidebar_switches_pages(window):
    for i in range(len(PAGES)):
        window.sidebar.select(i)
        window.sidebar.page_selected.emit(i)
        assert window.stack.currentIndex() == i


def test_chat_streams_reply_and_saves_history(window):
    before = window.chat.message_count()
    send(window, "hello")
    assert window.chat.message_count() == before + 2
    assert window.chat.input.isEnabled()
    msgs = window.assistant.store.get_messages(window.assistant.conversation_id)
    assert [m["content"] for m in msgs] == ["hello", "Hi friend"]
    assert window.speaker.spoken == []  # typed chat is not spoken


def test_chat_error_shows_notice_and_recovers(window):
    window.fake.error = OllamaError("Cannot reach Ollama")
    before = window.chat.message_count()
    send(window, "hello")
    assert window.chat.message_count() == before + 3
    assert window.chat.input.isEnabled()
    assert window.home.visualizer.state is VisualizerState.IDLE


def test_empty_message_ignored(window):
    before = window.chat.message_count()
    window.chat.input.setText("   ")
    window.chat.send_button.click()
    assert window.chat.message_count() == before


def test_new_chat_clears_panel_and_conversation(window):
    send(window, "hello")
    window.new_chat_button.click()
    assert window.assistant.conversation_id is None
    assert window.chat.message_count() == 1


def test_memory_page_lists_conversations(window):
    send(window, "remember me")
    window.sidebar.page_selected.emit(3)
    assert window.memory_page.list.count() == 1
    window.memory_page.list.setCurrentRow(0)
    assert "remember me" in window.memory_page.view.toPlainText()


def test_visualizer_renders_all_states(window):
    viz = window.home.visualizer
    for state in VisualizerState:
        viz.set_state(state)
        viz._tick()
        assert not viz.grab().isNull()


# -- voice ---------------------------------------------------------------------
def test_wake_listening_is_off_by_default(window):
    assert not window.settings_page.wake_check.isChecked()
    assert not window.voice.engine.running
    assert window.sidebar.status_pill.state is VoiceState.OFF


def test_settings_toggle_starts_and_stops_listener_and_persists(app, tmp_path):
    w = build(app, tmp_path)
    try:
        w.settings_page.wake_check.setChecked(True)
        assert wait_until(lambda: w.sidebar.status_pill.state is VoiceState.WAITING, app=app)
        assert "Hey Zana" in w.sidebar.status_pill.text()
        assert UserSettings.load(tmp_path / "s.json").wake_enabled is True
        w.settings_page.wake_check.setChecked(False)
        assert wait_until(lambda: w.sidebar.status_pill.state is VoiceState.OFF, app=app)
        assert not w.voice.engine.running and w.mic.stopped
        assert UserSettings.load(tmp_path / "s.json").wake_enabled is False
    finally:
        w.close()


def test_hands_free_flow_through_ollama_chat_and_speech(app, tmp_path):
    w = build(app, tmp_path, "Hey Zana", "what is two plus two")
    try:
        w.settings_page.wake_check.setChecked(True)
        assert wait_until(lambda: w.sidebar.status_pill.state is VoiceState.WAITING, app=app)
        w.mic.push(speech(0.8))
        assert wait_until(lambda: w.sidebar.status_pill.state is VoiceState.LISTENING, app=app)
        assert w.speaker.chimes == 1
        w.mic.push(speech(1.2))
        assert wait_until(lambda: w.speaker.spoken == ["Hi friend"], app=app)
        assert w.fake.prompts == ["what is two plus two"]
        msgs = w.assistant.store.get_messages(w.assistant.conversation_id)
        assert [m["role"] for m in msgs] == ["user", "assistant"]
        # after speaking, the listener returns to waiting for the wake phrase
        assert wait_until(lambda: w.sidebar.status_pill.state is VoiceState.WAITING, app=app)
    finally:
        w.close()


def test_hands_free_works_while_minimized(app, tmp_path):
    w = build(app, tmp_path, "hey zana tell me a joke")
    try:
        w.settings_page.wake_check.setChecked(True)
        assert wait_until(lambda: w.sidebar.status_pill.state is VoiceState.WAITING, app=app)
        w.showMinimized()
        app.processEvents()
        w.mic.push(speech(1.5))
        assert wait_until(lambda: w.speaker.spoken == ["Hi friend"], app=app)
        assert w.fake.prompts == ["tell me a joke"]
    finally:
        w.close()


def test_spoken_replies_can_be_disabled(app, tmp_path):
    w = build(app, tmp_path, "hey zana hello there")
    try:
        w.settings_page.speak_check.setChecked(False)
        w.settings_page.wake_check.setChecked(True)
        assert wait_until(lambda: w.sidebar.status_pill.state is VoiceState.WAITING, app=app)
        w.mic.push(speech(1.5))
        assert wait_until(lambda: w.fake.prompts == ["hello there"], app=app)
        assert wait_until(lambda: w.sidebar.status_pill.state is VoiceState.WAITING, app=app)
        assert w.speaker.spoken == []
        assert UserSettings.load(tmp_path / "s.json").speak_replies is False
    finally:
        w.close()


def test_ollama_failure_during_voice_command_is_spoken_and_recovers(app, tmp_path):
    w = build(app, tmp_path, "hey zana hello there")
    try:
        w.fake.error = OllamaError("Cannot reach Ollama")
        w.settings_page.wake_check.setChecked(True)
        assert wait_until(lambda: w.sidebar.status_pill.state is VoiceState.WAITING, app=app)
        w.mic.push(speech(1.5))
        assert wait_until(lambda: len(w.speaker.spoken) == 1, app=app)
        assert "couldn't" in w.speaker.spoken[0]
        assert wait_until(lambda: w.sidebar.status_pill.state is VoiceState.WAITING, app=app)
    finally:
        w.close()


def test_microphone_error_is_shown_and_toggle_resets(app, tmp_path):
    w = build(app, tmp_path, mic=FakeMic(fail_on_start=MicError("Could not open the microphone (denied).")))
    try:
        w.settings_page.wake_check.setChecked(True)
        assert wait_until(lambda: w.sidebar.status_pill.state is VoiceState.ERROR, app=app)
        assert "Could not open" in w.settings_page.status_label.text()
        assert not w.settings_page.wake_check.isChecked()
        assert UserSettings.load(tmp_path / "s.json").wake_enabled is False
        assert "error" in w.home.status.text().lower()
    finally:
        w.close()


def test_mic_button_push_to_talk(app, tmp_path):
    w = build(app, tmp_path, "tell me a joke")
    try:
        w.home.mic.click()
        assert wait_until(lambda: w.sidebar.status_pill.state is VoiceState.LISTENING, app=app)
        assert w.chat.mic.isChecked()
        w.mic.push(speech(1.2))
        assert wait_until(lambda: w.fake.prompts == ["tell me a joke"], app=app)
        assert wait_until(lambda: w.speaker.spoken == ["Hi friend"], app=app)
        assert wait_until(lambda: not w.voice.engine.running, app=app)  # one-shot ended
        assert not w.home.mic.isChecked()
    finally:
        w.close()


# -- applications ----------------------------------------------------------------
def build_with_apps(app, tmp_path, *texts):
    from zana.apps.registry import AppEntry
    w = build(app, tmp_path, *texts)
    notepad = AppEntry("notepad", "Notepad", "C:/Windows/System32/notepad.exe", builtin=True)
    w.app_registry._builtins = [notepad]
    w.apps_page.refresh()
    return w


def test_applications_page_lists_and_launches(app, tmp_path):
    w = build_with_apps(app, tmp_path)
    try:
        assert list(w.apps_page.launch_buttons) == ["notepad"]
        w.apps_page.launch_buttons["notepad"].click()
        assert w.launched == ["notepad"]
        assert "Opened Notepad" in w.apps_page.status.text()
    finally:
        w.close()


def test_applications_page_refuses_blocked_exe(app, tmp_path):
    w = build_with_apps(app, tmp_path)
    try:
        assert not w.apps_page.add_app(r"C:\Windows\System32\cmd.exe")
        assert "not allowed" in w.apps_page.status.text()
        assert list(w.apps_page.launch_buttons) == ["notepad"]
    finally:
        w.close()


def test_typed_open_command_launches_without_model(app, tmp_path):
    w = build_with_apps(app, tmp_path)
    try:
        send(w, "open notepad")
        assert w.launched == ["notepad"] and w.fake.prompts == []
        msgs = w.assistant.store.get_messages(w.assistant.conversation_id)
        assert [m["content"] for m in msgs] == ["open notepad", "Opening Notepad."]
        send(w, "open powershell")  # not approved and not offerable: honest reply, nothing launched
        assert w.launched == ["notepad"] and w.fake.prompts == []
        send(w, "open a new account")  # not an app request: ordinary conversation
        assert w.fake.prompts == ["open a new account"]
    finally:
        w.close()


def test_voice_open_command_launches_and_speaks(app, tmp_path):
    w = build_with_apps(app, tmp_path, "hey zana open notepad")
    try:
        w.settings_page.wake_check.setChecked(True)
        assert wait_until(lambda: w.sidebar.status_pill.state is VoiceState.WAITING, app=app)
        w.mic.push(speech(1.5))
        assert wait_until(lambda: w.speaker.spoken == ["Opening Notepad."], app=app)
        assert w.launched == ["notepad"] and w.fake.prompts == []
        assert wait_until(lambda: w.sidebar.status_pill.state is VoiceState.WAITING, app=app)
    finally:
        w.close()
