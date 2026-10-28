"""Energy-based utterance segmentation with an adaptive noise floor."""

from collections import deque
from typing import Optional

import numpy as np

SAMPLE_RATE = 16000
FRAME_LEN = 512  # 32 ms at 16 kHz


class UtteranceSegmenter:
    """Feed fixed-size frames; ``feed`` returns audio when an utterance ends.

    The speech threshold follows the measured background level, so it works on
    quiet laptop microphones as well as noisy rooms.
    """

    def __init__(
        self,
        sample_rate: int = SAMPLE_RATE,
        frame_len: int = FRAME_LEN,
        min_speech_s: float = 0.3,
        end_silence_s: float = 0.8,
        max_len_s: float = 8.0,
        preroll_s: float = 0.3,
        min_threshold: float = 0.0015,
        ratio: float = 4.0,
    ):
        self.frame_dur = frame_len / sample_rate
        self.min_speech_frames = max(1, int(min_speech_s / self.frame_dur))
        self.end_silence_frames = max(1, int(end_silence_s / self.frame_dur))
        self.max_frames = int(max_len_s / self.frame_dur)
        self.min_threshold = min_threshold
        self.ratio = ratio
        self._preroll: deque = deque(maxlen=max(1, int(preroll_s / self.frame_dur)))
        self.reset()

    def reset(self) -> None:
        self._floor: Optional[float] = None
        self._in_speech = False
        self._voiced_run = 0
        self._silence = 0
        self._voiced_total = 0
        self._buf: list = []
        self._preroll.clear()

    @property
    def in_speech(self) -> bool:
        return self._in_speech

    @property
    def threshold(self) -> float:
        floor = self._floor if self._floor is not None else 0.0
        return max(self.min_threshold, floor * self.ratio)

    def feed(self, frame: np.ndarray) -> Optional[np.ndarray]:
        rms = float(np.sqrt(np.mean(np.square(frame))))
        if self._floor is None:
            self._floor = rms
        voiced = rms > self.threshold

        if not self._in_speech:
            if not voiced:
                self._floor = self._floor * 0.95 + rms * 0.05
                self._voiced_run = 0
                self._preroll.append(frame)
                return None
            self._voiced_run += 1
            self._preroll.append(frame)
            if self._voiced_run >= 2:
                self._in_speech = True
                self._buf = list(self._preroll)
                self._voiced_total = self._voiced_run
                self._silence = 0
            return None

        self._buf.append(frame)
        if voiced:
            self._silence = 0
            self._voiced_total += 1
        else:
            self._silence += 1

        if self._silence >= self.end_silence_frames or len(self._buf) >= self.max_frames:
            audio = np.concatenate(self._buf).astype(np.float32)
            enough = self._voiced_total >= self.min_speech_frames
            self._in_speech = False
            self._voiced_run = 0
            self._buf = []
            self._preroll.clear()
            return audio if enough else None
        return None
