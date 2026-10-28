import pytest

from tests.fakes import FakeMic, FakeTranscriber, speech, wait_until
from zana.voice.engine import VoiceEngine, VoiceState
from zana.voice.mic import MicError


class Harness:
    def __init__(self, *texts, wake=True, mic=None, mic_factory=None, **kw):
        self.mic = mic or FakeMic()
        self.states: list[VoiceState] = []
        self.commands: list[str] = []
        self.wakes = 0
        self.engine = VoiceEngine(
            mic_factory=mic_factory or (lambda: self.mic),
            transcriber=FakeTranscriber(*texts),
            on_state=lambda s, d: self.states.append(s),
            on_command=self.commands.append,
            on_wake=self._wake,
            wake_enabled=wake,
            **kw,
        )

    def _wake(self):
        self.wakes += 1

    def state(self):
        return self.engine.state


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


def test_wake_then_separate_command(make):
    h = make("hey zana", "what is two plus two")
    h.engine.start()
    assert wait_until(lambda: h.state() is VoiceState.WAITING)
    h.mic.push(speech(0.8))
    assert wait_until(lambda: h.state() is VoiceState.LISTENING)
    assert h.wakes == 1
    h.mic.push(speech(1.2))
    assert wait_until(lambda: h.commands == ["what is two plus two"])
    assert h.state() is VoiceState.BUSY
    h.engine.resume()
    assert wait_until(lambda: h.state() is VoiceState.WAITING)


def test_wake_and_command_in_one_utterance(make):
    h = make("Hey Zana, what is the weather")
    h.engine.start()
    assert wait_until(lambda: h.state() is VoiceState.WAITING)
    h.mic.push(speech(1.5))
    assert wait_until(lambda: h.commands == ["what is the weather"])


def test_speech_without_wake_phrase_is_ignored(make):
    h = make("what a lovely day", "hey siri")
    h.engine.start()
    assert wait_until(lambda: h.state() is VoiceState.WAITING)
    h.mic.push(speech(1.0))
    assert wait_until(lambda: h.engine._transcriber.calls == 1)
    h.mic.push(speech(1.0))
    assert wait_until(lambda: h.engine._transcriber.calls == 2)
    assert h.commands == [] and h.wakes == 0 and h.state() is VoiceState.WAITING


def test_command_timeout_returns_to_waiting(make):
    h = make("hey zana", command_start_timeout=0.3)
    h.engine.start()
    assert wait_until(lambda: h.state() is VoiceState.WAITING)
    h.mic.push(speech(0.8))
    assert wait_until(lambda: h.state() is VoiceState.LISTENING)
    assert wait_until(lambda: h.state() is VoiceState.WAITING)
    assert h.commands == []


def test_push_to_talk_without_wake_listener_is_one_shot(make):
    h = make("open the calculator", wake=False)
    h.engine.request_command()
    assert wait_until(lambda: h.state() is VoiceState.LISTENING)
    h.mic.push(speech(1.0))
    assert wait_until(lambda: h.commands == ["open the calculator"])
    h.engine.resume()
    assert wait_until(lambda: not h.engine.running)
    assert h.state() is VoiceState.OFF and h.mic.stopped


def test_cancel_push_to_talk(make):
    h = make(wake=False)
    h.engine.request_command()
    assert wait_until(lambda: h.state() is VoiceState.LISTENING)
    h.engine.cancel_command()
    assert wait_until(lambda: not h.engine.running)
    assert h.state() is VoiceState.OFF


def test_mic_open_failure_reports_error(make):
    h = make(mic=FakeMic(fail_on_start=MicError("Could not open the microphone (denied).")))
    h.engine.start()
    assert wait_until(lambda: h.state() is VoiceState.ERROR)
    assert not h.engine.running


def test_silent_microphone_is_reported(make):
    h = make(mic=FakeMic(zeros=True), silence_watchdog_s=0.2)
    h.engine.start()
    assert wait_until(lambda: h.state() is VoiceState.ERROR)
    assert h.mic.stopped


def test_missing_model_reports_error():
    class Missing:
        def load(self):
            raise FileNotFoundError("Whisper model not found at X")

    states = []
    e = VoiceEngine(lambda: FakeMic(), Missing(), lambda s, d: states.append((s, d)), lambda t: None)
    e.start()
    assert wait_until(lambda: any(s is VoiceState.ERROR for s, _ in states))
    assert "not found" in states[-1][1]


def test_stop_releases_microphone(make):
    h = make()
    h.engine.start()
    assert wait_until(lambda: h.state() is VoiceState.WAITING)
    h.engine.stop()
    assert h.mic.stopped and h.state() is VoiceState.OFF
