"""Test doubles for the voice stack (no audio hardware or models needed)."""

import queue
import time

import numpy as np

from zana.voice.segmenter import FRAME_LEN, SAMPLE_RATE

_rng = np.random.default_rng(0)


def speech(seconds: float = 1.0, amp: float = 0.1) -> np.ndarray:
    t = np.arange(int(seconds * SAMPLE_RATE)) / SAMPLE_RATE
    return (amp * np.sin(2 * np.pi * 220 * t) * (0.6 + 0.4 * np.sin(2 * np.pi * 3 * t))).astype(np.float32)


def silence(seconds: float, noise: float = 0.0002) -> np.ndarray:
    return (_rng.standard_normal(int(seconds * SAMPLE_RATE)) * noise).astype(np.float32)


def frames(audio: np.ndarray):
    n = len(audio) // FRAME_LEN
    return [audio[i * FRAME_LEN:(i + 1) * FRAME_LEN] for i in range(n)]


class FakeMic:
    """Endless quiet microphone; tests inject speech with ``push``."""

    def __init__(self, zeros: bool = False, fail_on_start=None, die_after=None):
        self._q: queue.Queue = queue.Queue()
        self.zeros = zeros
        self.fail_on_start = fail_on_start
        self.started = False
        self.stopped = False
        self.die_after = die_after   # after N frames the device 'disappears' (read -> None)
        self.reads = 0

    def start(self):
        if self.fail_on_start:
            raise self.fail_on_start
        self.started = True

    def push(self, audio: np.ndarray, trailing_silence: float = 1.0):
        for f in frames(np.concatenate([audio, silence(trailing_silence)])):
            self._q.put(f)

    def read(self, timeout=0.2):
        if self.die_after is not None and self.reads >= self.die_after:
            time.sleep(0.01)
            return None
        self.reads += 1
        try:
            return self._q.get_nowait()
        except queue.Empty:
            time.sleep(0.004)
            if self.zeros:
                return np.zeros(FRAME_LEN, dtype=np.float32)
            return silence(FRAME_LEN / SAMPLE_RATE)

    def drain(self):
        while not self._q.empty():
            try:
                self._q.get_nowait()
            except queue.Empty:
                break

    def stop(self):
        self.stopped = True


class FakeTranscriber:
    """Returns scripted transcripts in order."""

    def __init__(self, *texts: str):
        self.texts = list(texts)
        self.calls = 0

    def load(self):
        pass

    def transcribe(self, audio, check_wake=False):
        self.calls += 1
        return self.texts.pop(0) if self.texts else ""


class FakeSpeaker:
    def __init__(self, delay: float = 0.0, on_speak=None):
        self.on_speak = on_speak  # lets a test play 'Zana hears her own voice' into the mic
        self.spoken: list[str] = []
        self.chimes = 0
        self.delay = delay

    def load(self):
        pass

    def speak(self, text):
        self.spoken.append(text)
        if self.on_speak:
            self.on_speak()
        time.sleep(self.delay)

    def stop(self):
        pass

    def chime(self):
        self.chimes += 1


def wait_until(cond, timeout: float = 8.0, app=None) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if app is not None:
            app.processEvents()
        if cond():
            return True
        time.sleep(0.01)
    if app is not None:
        app.processEvents()
    return bool(cond())
