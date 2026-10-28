"""Spoken responses with Piper TTS, played through sounddevice."""

import queue
import re
import threading
from pathlib import Path
from typing import Protocol

import numpy as np


class Speaker(Protocol):
    def load(self) -> None: ...
    def speak(self, text: str) -> None: ...
    def stop(self) -> None: ...
    def chime(self) -> None: ...


def clean_for_speech(text: str) -> str:
    """Strip markdown, URLs and emoji so the voice doesn't read symbols aloud."""
    text = re.sub(r"```.*?```", " ", text, flags=re.S)
    text = re.sub(r"https?://\S+", " link ", text)
    text = re.sub(r"[*_`#>|~]+", "", text)
    text = re.sub(r"^\s*[-•]\s+", "", text, flags=re.M)
    text = re.sub(r"[\U00010000-\U0010FFFF☀-➿️]", "", text)
    return re.sub(r"\s+", " ", text).strip()


class PiperSpeaker:
    def __init__(self, model_path: Path | str):
        self.model_path = str(model_path)
        self._voice = None
        self._stop = threading.Event()
        self._speaking = threading.Event()

    @property
    def speaking(self) -> bool:
        return self._speaking.is_set()

    def load(self) -> None:
        if self._voice is not None:
            return
        if not Path(self.model_path).exists():
            raise FileNotFoundError(f"Piper voice not found at {self.model_path}")
        from piper import PiperVoice

        self._voice = PiperVoice.load(self.model_path)

    def speak(self, text: str) -> None:
        """Blocking. Synthesises sentence by sentence while the previous one plays."""
        import sounddevice as sd

        text = clean_for_speech(text)
        if not text:
            return
        self.load()
        self._stop.clear()
        self._speaking.set()
        chunks: queue.Queue = queue.Queue(maxsize=3)

        def produce() -> None:
            try:
                for c in self._voice.synthesize(text):
                    if self._stop.is_set():
                        break
                    chunks.put((c.audio_float_array, c.sample_rate))
            finally:
                chunks.put(None)

        threading.Thread(target=produce, daemon=True).start()
        try:
            while True:
                item = chunks.get()
                if item is None or self._stop.is_set():
                    break
                audio, rate = item
                sd.play(audio, rate)
                sd.wait()
        finally:
            if self._stop.is_set():
                sd.stop()
                while not chunks.empty():  # unblock the producer
                    chunks.get_nowait()
            self._speaking.clear()

    def stop(self) -> None:
        self._stop.set()
        try:
            import sounddevice as sd
            sd.stop()
        except Exception:
            pass

    def chime(self) -> None:
        """Short rising two-tone beep confirming the wake phrase was heard."""
        import sounddevice as sd

        rate = 22050
        t = np.linspace(0, 0.09, int(rate * 0.09), endpoint=False)
        env = np.hanning(t.size)
        tone = np.concatenate([np.sin(2 * np.pi * 660 * t) * env, np.sin(2 * np.pi * 880 * t) * env])
        sd.play((tone * 0.25).astype(np.float32), rate)
        sd.wait()
