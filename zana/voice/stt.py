"""Speech-to-text with Faster-Whisper (CPU, int8)."""

from pathlib import Path
from typing import Protocol

import re

import numpy as np

from .wake import match_wake_phrase

SHORT_CLIP_S = 2.5

# Primes the decoder with the assistant's name; without it, small models hear
# a short "Hey Zana." as "Hey sauna" or "He's on a...".
VOCAB_PROMPT = "Zana is a voice assistant. Hey Zana, what is the weather?"


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", text.lower()).strip()


class Transcriber(Protocol):
    def load(self) -> None: ...
    def transcribe(self, audio: np.ndarray, check_wake: bool = False) -> str: ...


class WhisperTranscriber:
    def __init__(self, model_dir: Path | str, cpu_threads: int = 4):
        self.model_dir = str(model_dir)
        self.cpu_threads = cpu_threads
        self._model = None

    def load(self) -> None:
        if self._model is not None:
            return
        if not Path(self.model_dir).exists():
            raise FileNotFoundError(f"Whisper model not found at {self.model_dir}")
        from faster_whisper import WhisperModel

        self._model = WhisperModel(
            self.model_dir, device="cpu", compute_type="int8", cpu_threads=self.cpu_threads
        )

    def transcribe(self, audio: np.ndarray, check_wake: bool = False) -> str:
        """Transcribe one utterance.

        With ``check_wake``, a short clip that doesn't contain the wake phrase is
        decoded a second time with a wider beam: greedy decoding misheard a bare
        "Hey Zana." about a third of the time, beam search did not.
        """
        self.load()
        audio = np.asarray(audio, dtype=np.float32)
        peak = float(np.abs(audio).max()) if audio.size else 0.0
        if peak < 1e-4:
            return ""
        audio = audio / peak * 0.9  # laptop mics are often very quiet
        text = self._decode(audio, beam_size=1)
        if check_wake and len(audio) < SHORT_CLIP_S * 16000 and match_wake_phrase(text) is None:
            retry = self._decode(audio, beam_size=5)
            if match_wake_phrase(retry) is not None:
                return retry
        return text

    def _decode(self, audio: np.ndarray, beam_size: int) -> str:
        pad = np.zeros(int(0.2 * 16000), dtype=np.float32)
        segments, _ = self._model.transcribe(
            np.concatenate([pad, audio, pad]),
            language="en",
            beam_size=beam_size,
            condition_on_previous_text=False,
            vad_filter=False,
            initial_prompt=VOCAB_PROMPT,
        )
        kept = [
            s.text.strip() for s in segments
            if not (s.no_speech_prob > 0.6 and s.avg_logprob < -1.0)  # likely not speech
        ]
        text = " ".join(kept).strip()
        # Whisper sometimes parrots the prompt on noise; never treat that as speech.
        if _norm(text) == _norm(VOCAB_PROMPT):
            return ""
        return text
