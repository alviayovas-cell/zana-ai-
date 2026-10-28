"""Integration tests with the real Whisper and Piper models.

Audio is synthesised by Piper (not a human voice) and fed through the real
recogniser, so this checks the model stack and wake-phrase logic, not the
acoustic path from a real microphone. Skipped when models are not downloaded.
"""

import numpy as np
import pytest

from zana.config import CONFIG
from zana.voice.stt import WhisperTranscriber
from zana.voice.wake import match_wake_phrase

pytestmark = pytest.mark.skipif(
    not (CONFIG.whisper_dir.exists() and CONFIG.piper_model_path.exists()),
    reason="voice models not downloaded",
)


def to_16k(audio: np.ndarray, rate: int) -> np.ndarray:
    n = int(len(audio) * 16000 / rate)
    return np.interp(np.linspace(0, len(audio) - 1, n), np.arange(len(audio)), audio).astype(np.float32)


@pytest.fixture(scope="module")
def tts():
    from piper import PiperVoice
    voice = PiperVoice.load(str(CONFIG.piper_model_path))

    def say(text: str, gain: float = 0.02) -> np.ndarray:
        chunks = list(voice.synthesize(text))
        audio = np.concatenate([c.audio_float_array for c in chunks])
        return to_16k(audio, chunks[0].sample_rate) * gain  # quiet, like a laptop mic

    return say


@pytest.fixture(scope="module")
def stt():
    t = WhisperTranscriber(CONFIG.whisper_dir)
    t.load()
    return t


@pytest.mark.parametrize("phrase", ["Hey Zana.", "Hey, Zana!"])
def test_wake_phrase_recognised(tts, stt, phrase):
    # Piper output varies run to run, so require a high hit rate over several clips.
    misses = [t for t in (stt.transcribe(tts(phrase), check_wake=True) for _ in range(10))
              if match_wake_phrase(t) is None]
    assert len(misses) <= 3, f"misheard: {misses}"  # measured ~80% for a bare phrase


def test_wake_phrase_with_command(tts, stt):
    text = stt.transcribe(tts("Hey Zana, what is two plus two?"))
    rem = match_wake_phrase(text)
    assert rem is not None and "two" in rem.replace("2", "two"), f"transcribed as {text!r}"


def test_ordinary_speech_does_not_wake(tts, stt):
    for phrase in ("What a lovely day today.", "Please turn off the lights."):
        assert match_wake_phrase(stt.transcribe(tts(phrase))) is None


def test_silence_transcribes_to_nothing(stt):
    assert stt.transcribe(np.zeros(16000, dtype=np.float32)) == ""
