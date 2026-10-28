"""Microphone capture via sounddevice, with user-presentable errors."""

import queue
from typing import Optional

import numpy as np

from .segmenter import FRAME_LEN, SAMPLE_RATE

MIC_PRIVACY_HINT = (
    "Check that a microphone is connected and that Windows allows desktop apps to use it "
    "(Settings > Privacy & security > Microphone)."
)


class MicError(Exception):
    """Microphone problem; the message is safe to show to the user."""


class MicStream:
    def __init__(self, device=None, sample_rate: int = SAMPLE_RATE,
                 frame_len: int = FRAME_LEN, max_queued: int = 1500):
        self.device = device
        self.sample_rate = sample_rate
        self.frame_len = frame_len
        self._q: queue.Queue = queue.Queue(maxsize=max_queued)
        self._stream = None
        self.device_name = ""

    def _callback(self, indata, _frames, _time, _status) -> None:
        frame = indata[:, 0].copy()
        try:
            self._q.put_nowait(frame)
        except queue.Full:
            try:
                self._q.get_nowait()
                self._q.put_nowait(frame)
            except (queue.Empty, queue.Full):
                pass

    def start(self) -> None:
        import sounddevice as sd

        try:
            info = sd.query_devices(self.device, "input")
            self.device_name = str(info.get("name", ""))
            self._stream = sd.InputStream(
                device=self.device, samplerate=self.sample_rate, channels=1,
                dtype="float32", blocksize=self.frame_len, callback=self._callback,
            )
            self._stream.start()
        except sd.PortAudioError as e:
            raise MicError(f"Could not open the microphone ({e}). {MIC_PRIVACY_HINT}") from e
        except (ValueError, OSError) as e:
            raise MicError(f"No usable microphone found ({e}). {MIC_PRIVACY_HINT}") from e

    def read(self, timeout: float = 0.2) -> Optional[np.ndarray]:
        try:
            return self._q.get(timeout=timeout)
        except queue.Empty:
            return None

    def drain(self) -> None:
        while True:
            try:
                self._q.get_nowait()
            except queue.Empty:
                return

    def stop(self) -> None:
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            finally:
                self._stream = None


def measure_input_level(seconds: float = 1.5) -> tuple[float, bool]:
    """Record briefly; return (rms, all_zero). Raises MicError if it cannot open."""
    mic = MicStream()
    mic.start()
    try:
        import time
        end = time.monotonic() + seconds
        frames = []
        while time.monotonic() < end:
            f = mic.read(0.2)
            if f is not None:
                frames.append(f)
    finally:
        mic.stop()
    if not frames:
        raise MicError("The microphone produced no audio.")
    x = np.concatenate(frames)
    return float(np.sqrt(np.mean(x ** 2))), not x.any()
