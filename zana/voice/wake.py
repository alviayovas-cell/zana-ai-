"""Wake-phrase matching on transcribed text ("Hey Zana")."""

import re
from difflib import SequenceMatcher
from typing import Optional

_GREETINGS = {"hey", "hay", "hei", "hi", "hello", "okay", "ok", "ay"}
_NAME = "zana"
_NAME_ALIASES = {"zanna", "zaana", "zahna", "xana", "zanah", "zannah", "sana", "zaina"}
_STRICT_NAMES = {"zana", "zanna", "zaana", "zahna", "xana"}
_MAX_LEAD_WORDS = 2  # tolerate e.g. "um hey zana"


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9']+", text.lower())


def _is_name(word: str) -> bool:
    return (
        word == _NAME
        or word in _NAME_ALIASES
        or SequenceMatcher(None, word, _NAME).ratio() >= 0.8
    )


def match_wake_phrase(text: str) -> Optional[str]:
    """Return the text spoken after "Hey Zana" (may be empty), or None if absent."""
    words = _words(text)
    # A bare name ("Zana.") is accepted only when it is (almost) the whole utterance,
    # so ordinary sentences that merely mention the name don't wake her.
    if 1 <= len(words) <= 2 and words[0] in _STRICT_NAMES:
        return " ".join(words[1:])
    for i in range(min(len(words), _MAX_LEAD_WORDS + 1)):
        # "heyzana" as one token
        if re.fullmatch(r"(hey|hay|hi|ok|okay)" + _NAME, words[i]):
            return " ".join(words[i + 1:])
        if i + 1 < len(words) and words[i] in _GREETINGS and _is_name(words[i + 1]):
            return " ".join(words[i + 2:])
    return None
