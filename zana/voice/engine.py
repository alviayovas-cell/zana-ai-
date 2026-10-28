"""Hands-free voice loop: wake phrase -> command -> (follow-ups) -> back to waiting.

Qt-free so it can be tested with fake microphones and transcribers. The loop
runs on its own thread, so it keeps working while the window is minimized/hidden.
"""

import re
import threading
import time
from enum import Enum
from typing import Callable, Optional

import numpy as np

from .mic import MIC_PRIVACY_HINT, MicError
from .segmenter import FRAME_LEN, SAMPLE_RATE, UtteranceSegmenter
from .wake import match_wake_phrase


class VoiceState(str, Enum):
    OFF = "off"
    STARTING = "starting"
    WAITING = "waiting"          # listening for the wake phrase
    LISTENING = "listening"      # capturing a command / follow-up
    TRANSCRIBING = "transcribing"
    BUSY = "busy"                # command handed off; engine paused
    SPEAKING = "speaking"
    PAUSED = "paused"            # user paused listening; microphone is closed
    ERROR = "error"


# Said during a follow-up window to end the conversation without asking the model.
END_PHRASES = frozenset({
    "stop", "thanks", "thank you", "thank you zana", "thanks zana", "that's all", "thats all",
    "that is all", "goodbye", "bye", "never mind", "nevermind", "cancel", "no thanks",
    "no thank you", "i'm done", "im done",
})


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z' ]", "", text.lower())).strip()


class VoiceEngine:
    def __init__(
        self,
        mic_factory: Callable[[], object],
        transcriber,
        on_state: Callable[[VoiceState, str], None],
        on_command: Callable[[str], None],
        on_level: Optional[Callable[[float], None]] = None,
        on_wake: Optional[Callable[[], None]] = None,
        wake_enabled: bool = True,
        command_start_timeout: float = 6.0,
        follow_up_seconds: float = 0.0,
        resume_guard_s: float = 0.6,
        silence_watchdog_s: float = 4.0,
        no_frame_timeout_s: float = 3.0,
        recover_attempts: int = 3,
        recover_delay_s: float = 1.0,
        segmenter_factory: Callable[[], UtteranceSegmenter] = UtteranceSegmenter,
    ):
        self._mic_factory = mic_factory
        self._transcriber = transcriber
        self._on_state = on_state
        self._on_command = on_command
        self._on_level = on_level
        self._on_wake = on_wake
        self._wake_enabled = wake_enabled
        self._command_timeout = command_start_timeout
        self._follow_up_s = follow_up_seconds
        self._resume_guard_s = resume_guard_s
        self._watchdog_frames = int(silence_watchdog_s * SAMPLE_RATE / FRAME_LEN)
        self._no_frame_timeout = no_frame_timeout_s
        self._recover_attempts = recover_attempts
        self._recover_delay = recover_delay_s
        self._segmenter_factory = segmenter_factory

        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._paused = threading.Event()
        self._reset_needed = threading.Event()
        self._follow_up_request = threading.Event()
        self._force_command = threading.Event()
        self._cancel = threading.Event()
        self._lock = threading.Lock()
        self.state = VoiceState.OFF

    # -- public API ---------------------------------------------------------
    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def set_wake_enabled(self, enabled: bool) -> None:
        self._wake_enabled = enabled

    def set_follow_up_seconds(self, seconds: float) -> None:
        """How long after a reply Zana keeps listening without the wake phrase (0 = off)."""
        self._follow_up_s = max(0.0, float(seconds))

    def start(self) -> None:
        with self._lock:
            if self.running:
                if not self._stop.is_set():
                    return  # never open a second microphone listener
                self._thread.join(2.0)  # previous session is shutting down
                if self.running:
                    return
            self._stop.clear()
            self._paused.clear()
            self._reset_needed.clear()
            self._follow_up_request.clear()  # stale requests from a previous session
            self._thread = threading.Thread(target=self._run, name="zana-voice", daemon=True)
            self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        t = self._thread
        if t is not None and t is not threading.current_thread():
            t.join(timeout)

    def request_command(self) -> None:
        """Push-to-talk: capture the next utterance as a command, no wake phrase."""
        self._force_command.set()
        self.start()

    def cancel_command(self) -> None:
        """Abort a pending push-to-talk capture."""
        self._force_command.clear()
        self._cancel.set()

    def resume(self) -> None:
        """Call when the reply is finished. Opens a follow-up window if enabled."""
        self._reset_needed.set()
        self._paused.clear()
        if not self._wake_enabled:
            self._stop.set()  # one-shot (push-to-talk) session is over
        elif self._follow_up_s > 0:
            self._follow_up_request.set()  # loop switches to "listening" after the echo guard
        # The loop announces the new state itself once it has discarded stale audio.

    def set_speaking(self) -> None:
        self._set(VoiceState.SPEAKING, "Speaking")

    # -- internals ----------------------------------------------------------
    def _set(self, state: VoiceState, detail: str = "") -> None:
        self.state = state
        self._on_state(state, detail)

    def _idle_state(self) -> None:
        if self._wake_enabled:
            self._set(VoiceState.WAITING, 'Listening for "Hey Zana"')
        else:
            self._set(VoiceState.OFF, "Microphone off")

    def _fail(self, message: str) -> None:
        self._set(VoiceState.ERROR, message)

    def _deliver(self, text: str) -> None:
        self._paused.set()  # stop hearing anything (including our own reply) until resume()
        self._set(VoiceState.BUSY, "Processing")
        self._on_command(text)

    def _recover_mic(self, mic, seg):
        """The stream went quiet (device unplugged/disabled). Reopen it with backoff."""
        self._set(VoiceState.STARTING, "Reconnecting to the microphone")
        try:
            mic.stop()
        except Exception:
            pass
        last = None
        for attempt in range(self._recover_attempts):
            if self._stop.wait(self._recover_delay * (2 ** attempt)):
                return None
            try:
                new = self._mic_factory()
                new.start()
            except Exception as e:  # MicError or anything the audio stack raises
                last = e
                continue
            seg.reset()
            self._idle_state()
            return new
        self._fail(f"The microphone stopped responding and could not be reopened ({last}). "
                   + MIC_PRIVACY_HINT)
        return None

    def _run(self) -> None:
        self._set(VoiceState.STARTING, "Loading speech model")
        mic = None
        try:
            self._transcriber.load()
            mic = self._mic_factory()
            mic.start()
        except MicError as e:
            self._fail(str(e))
            return
        except FileNotFoundError as e:
            self._fail(f"{e}. Download the model first (see README).")
            return
        except Exception as e:
            self._fail(f"Voice startup failed: {e}")
            return

        seg = self._segmenter_factory()
        awaiting = False
        follow_up = False
        awaiting_since = 0.0
        awaiting_timeout = self._command_timeout
        guard_until = 0.0
        last_frame = time.monotonic()
        zero_frames = 0
        errors = 0
        self._idle_state()
        try:
            while not self._stop.is_set():
                if self._paused.is_set():
                    mic.drain()          # whatever is heard now is Zana's own voice or noise
                    time.sleep(0.05)
                    last_frame = time.monotonic()
                    continue
                if self._reset_needed.is_set():
                    self._reset_needed.clear()
                    mic.drain()
                    seg.reset()
                    awaiting = follow_up = False
                    guard_until = time.monotonic() + self._resume_guard_s  # echo tail of our speech
                    if self._follow_up_request.is_set():
                        self._follow_up_request.clear()
                        if self._wake_enabled and self._follow_up_s > 0:
                            awaiting = follow_up = True
                            awaiting_since = guard_until
                            awaiting_timeout = self._follow_up_s
                            self._set(VoiceState.LISTENING, "Listening for your next question")
                    if not awaiting:
                        self._idle_state()
                if self._cancel.is_set():
                    self._cancel.clear()
                    seg.reset()
                    awaiting = follow_up = False
                    self._idle_state()
                    if not self._wake_enabled:
                        break  # push-to-talk session cancelled; release the mic
                frame = mic.read(0.2)
                now = time.monotonic()
                if frame is None:
                    if now - last_frame > self._no_frame_timeout:
                        mic = self._recover_mic(mic, seg)
                        if mic is None:
                            return
                        last_frame = time.monotonic()
                        awaiting = follow_up = False
                    continue
                last_frame = now

                if frame.any():
                    zero_frames = 0
                else:
                    zero_frames += 1
                    if zero_frames >= self._watchdog_frames:
                        self._fail("The microphone is returning silence - it may be muted or "
                                   "blocked. " + MIC_PRIVACY_HINT)
                        return
                if self._on_level is not None:
                    self._on_level(float(np.sqrt(np.mean(np.square(frame)))))
                if now < guard_until:
                    continue  # still inside the echo guard after we spoke

                if self._force_command.is_set():
                    self._force_command.clear()
                    awaiting, follow_up, awaiting_since = True, False, now
                    awaiting_timeout = self._command_timeout
                    seg.reset()
                    self._set(VoiceState.LISTENING, "Listening")
                if not awaiting and not self._wake_enabled:
                    continue
                if awaiting and not seg.in_speech and now - awaiting_since > awaiting_timeout:
                    awaiting = follow_up = False  # conversation ended: back to the wake phrase
                    self._idle_state()
                    continue

                utt = seg.feed(frame)
                if utt is None:
                    continue

                self._set(VoiceState.TRANSCRIBING, "Processing")
                try:
                    text = self._transcriber.transcribe(utt, check_wake=not awaiting)
                    errors = 0
                except Exception as e:
                    errors += 1
                    if errors >= 3:
                        self._fail(f"Speech recognition keeps failing: {e}")
                        return
                    self._idle_state()
                    continue

                if awaiting:
                    if follow_up:
                        rem = match_wake_phrase(text)
                        if rem is not None:
                            text = rem          # "Hey Zana, ..." inside a conversation still works
                        if _norm(text) in END_PHRASES:
                            awaiting = follow_up = False
                            self._idle_state()
                            continue
                    if text.strip():
                        awaiting = follow_up = False
                        self._deliver(text.strip())
                    elif follow_up:
                        self._set(VoiceState.LISTENING, "Listening for your next question")
                    else:
                        awaiting = False
                        self._idle_state()
                    continue

                remainder = match_wake_phrase(text)
                if remainder is None:
                    self._idle_state()
                    continue
                if self._on_wake is not None:
                    self._on_wake()
                    mic.drain()  # don't hear our own chime
                    seg.reset()
                if remainder.strip():
                    self._deliver(remainder.strip())
                else:
                    awaiting, follow_up, awaiting_since = True, False, time.monotonic()
                    awaiting_timeout = self._command_timeout
                    self._set(VoiceState.LISTENING, "Listening")
        finally:
            if mic is not None:
                try:
                    mic.stop()
                except Exception:
                    pass
            if self.state is not VoiceState.ERROR:
                self._set(VoiceState.OFF, "Microphone off")
