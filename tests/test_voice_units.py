import numpy as np
import pytest

from tests.fakes import frames, silence, speech
from zana.settings import UserSettings
from zana.voice.segmenter import UtteranceSegmenter
from zana.voice.tts import clean_for_speech
from zana.voice.wake import match_wake_phrase


def run(seg, audio):
    return [u for f in frames(audio) if (u := seg.feed(f)) is not None]


def test_segmenter_returns_one_utterance():
    seg = UtteranceSegmenter()
    out = run(seg, np.concatenate([silence(1.0), speech(1.0), silence(1.5)]))
    assert len(out) == 1
    assert 1.0 <= len(out[0]) / 16000 <= 2.2


def test_segmenter_ignores_noise_and_short_blips():
    seg = UtteranceSegmenter()
    assert run(seg, silence(3.0)) == []
    assert run(seg, np.concatenate([silence(1.0), speech(0.08), silence(1.5)])) == []


def test_segmenter_adapts_to_very_quiet_speech():
    seg = UtteranceSegmenter()
    out = run(seg, np.concatenate([silence(1.0), speech(1.0, amp=0.01), silence(1.5)]))
    assert len(out) == 1


def test_segmenter_caps_length():
    seg = UtteranceSegmenter(max_len_s=2.0)
    out = run(seg, np.concatenate([silence(0.5), speech(5.0)]))
    assert out and all(len(u) / 16000 <= 2.2 for u in out)


@pytest.mark.parametrize("text,expected", [
    ("Hey Zana", ""),
    ("Hey, Zana.", ""),
    ("hey zana what time is it", "what time is it"),
    ("Hey Zanna, open notepad", "open notepad"),
    ("hey sana tell me a joke", "tell me a joke"),
    ("um hey zana weather", "weather"),
    ("Heyzana stop", "stop"),
    ("Hi Zana", ""),
    ("Zana.", ""),
    ("Zana stop", "stop"),
])
def test_wake_phrase_matches(text, expected):
    assert match_wake_phrase(text) == expected


@pytest.mark.parametrize("text", [
    "", "what time is it", "hey siri", "hey anna how are you", "zana is a nice name hey",
    "thank you", "hey there", "sana is my friend from school today",
])
def test_wake_phrase_rejects(text):
    assert match_wake_phrase(text) is None


def test_clean_for_speech():
    assert clean_for_speech("**Paris!** \U0001F1EB\U0001F1F7 See https://x.org `code`") == "Paris! See link code"
    assert clean_for_speech("```\nprint(1)\n```") == ""


def test_settings_roundtrip_and_defaults(tmp_path):
    p = tmp_path / "s.json"
    assert UserSettings.load(p).wake_enabled is False  # opt-in only
    UserSettings(wake_enabled=True, speak_replies=False).save(p)
    s = UserSettings.load(p)
    assert s.wake_enabled and not s.speak_replies
    p.write_text("not json")
    assert UserSettings.load(p) == UserSettings()
