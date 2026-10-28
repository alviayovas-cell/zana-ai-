"""Qt adapter around the voice engine and speaker (thread-safe signals)."""

import threading
from typing import Callable, Optional

from PySide6.QtCore import QObject, Signal

from ..config import CONFIG
from ..voice.engine import VoiceEngine, VoiceState
from ..voice.mic import MicStream
from ..voice.stt import WhisperTranscriber
from ..voice.tts import PiperSpeaker


class VoiceBridge(QObject):
    state_changed = Signal(str, str)   # VoiceState value, detail
    command_heard = Signal(str)
    level = Signal(float)
    speech_finished = Signal()
    speech_failed = Signal(str)

    def __init__(
        self,
        mic_factory: Optional[Callable] = None,
        transcriber=None,
        speaker=None,
        parent=None,
    ):
        super().__init__(parent)
        self.speaker = speaker or PiperSpeaker(CONFIG.piper_model_path)
        self.engine = VoiceEngine(
            mic_factory=mic_factory or MicStream,
            transcriber=transcriber or WhisperTranscriber(CONFIG.whisper_dir),
            on_state=self._on_engine_state,
            on_command=self.command_heard.emit,
            on_level=self.level.emit,
            on_wake=self._chime,
            wake_enabled=False,
        )
        self._speech_thread: Optional[threading.Thread] = None
        self._user_paused = False
        self._shut_down = False

    @property
    def user_paused(self) -> bool:
        return self._user_paused

    def _on_engine_state(self, state: VoiceState, detail: str) -> None:
        if self._user_paused and state is VoiceState.OFF:
            state, detail = VoiceState.PAUSED, "Listening paused"  # mic closed on purpose
        self.state_changed.emit(state.value, detail)

    def _chime(self) -> None:
        try:
            self.speaker.chime()
        except Exception:
            pass  # a missing audio output must not break wake detection

    # -- control ------------------------------------------------------------
    def _preload_voice(self) -> None:
        """Load the TTS voice in the background so the first reply isn't delayed."""
        def run() -> None:
            try:
                self.speaker.load()
            except Exception:
                pass  # reported when a reply is actually spoken
        threading.Thread(target=run, name="zana-tts-load", daemon=True).start()

    def set_wake_enabled(self, enabled: bool) -> None:
        if self._shut_down and enabled:
            return  # Zana has exited: nothing may reopen the microphone
        self._user_paused = False  # turning the feature on/off always ends a pause
        self.engine.set_wake_enabled(enabled)
        if enabled:
            self._preload_voice()
            self.engine.start()
        else:
            self.engine.stop()
            self.state_changed.emit(VoiceState.OFF.value, "Microphone off")

    def set_follow_up_seconds(self, seconds: float) -> None:
        self.engine.set_follow_up_seconds(seconds)

    def pause_listening(self) -> None:
        """Close the microphone completely until resume_listening()."""
        self._user_paused = True
        self.speaker.stop()
        self.engine.stop()
        self.state_changed.emit(VoiceState.PAUSED.value, "Listening paused")

    def resume_listening(self) -> None:
        if not self._user_paused or self._shut_down:
            return
        self._user_paused = False
        self._preload_voice()
        self.engine.set_wake_enabled(True)
        self.engine.start()

    def push_to_talk(self) -> None:
        if self._shut_down:
            return
        self._preload_voice()
        self.engine.request_command()

    def cancel_command(self) -> None:
        self.engine.cancel_command()

    def resume(self) -> None:
        if self._user_paused:
            return  # a reply finished after the user paused: stay deaf
        self.engine.resume()

    # -- speech -------------------------------------------------------------
    def speak(self, text: str) -> None:
        """Speak on a background thread; emits speech_finished/speech_failed."""
        self.engine.set_speaking()

        def run() -> None:
            try:
                self.speaker.speak(text)
            except Exception as e:
                self.speech_failed.emit(f"Could not speak the reply: {e}")
            finally:
                self.speech_finished.emit()

        self._speech_thread = threading.Thread(target=run, name="zana-tts", daemon=True)
        self._speech_thread.start()

    def stop_speaking(self) -> None:
        self.speaker.stop()

    def shutdown(self) -> None:
        """Final: stop listening and refuse to ever reopen the microphone."""
        self._shut_down = True
        self.speaker.stop()
        self.engine.stop()
        if self._speech_thread is not None:
            self._speech_thread.join(3.0)
