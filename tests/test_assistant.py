import threading

import pytest

from zana.core.assistant import Assistant
from zana.core.ollama_client import OllamaError
from zana.storage.history import HistoryStore


class FakeClient:
    def __init__(self, chunks=("Hel", "lo"), error=None):
        self.chunks, self.error, self.seen = chunks, error, []

    def stream_chat(self, messages, cancel=None):
        self.seen.append(messages)
        for c in self.chunks:
            yield c
        if self.error:
            raise self.error


def make(tmp_path, **kw):
    return Assistant(FakeClient(**kw), HistoryStore(tmp_path / "a.db"), system_prompt="SYS")


def test_streams_and_saves_both_turns(tmp_path):
    a = make(tmp_path)
    assert "".join(a.reply_stream("hi there")) == "Hello"
    msgs = a.store.get_messages(a.conversation_id)
    assert [(m["role"], m["content"]) for m in msgs] == [("user", "hi there"), ("assistant", "Hello")]
    assert a.store.list_conversations()[0]["title"] == "hi there"


def test_prompt_includes_system_and_history(tmp_path):
    a = make(tmp_path)
    list(a.reply_stream("one"))
    list(a.reply_stream("two"))
    sent = a.client.seen[-1]
    assert sent[0] == {"role": "system", "content": "SYS"}
    assert [m["content"] for m in sent[1:]] == ["one", "Hello", "two"]


def test_error_does_not_save_partial_reply(tmp_path):
    a = make(tmp_path, error=OllamaError("boom"))
    with pytest.raises(OllamaError):
        list(a.reply_stream("hi"))
    assert [m["role"] for m in a.store.get_messages(a.conversation_id)] == ["user"]


def test_cancel_does_not_save_reply(tmp_path):
    a = make(tmp_path)
    ev = threading.Event()
    ev.set()
    list(a.reply_stream("hi", ev))
    assert [m["role"] for m in a.store.get_messages(a.conversation_id)] == ["user"]


def test_new_conversation_starts_fresh(tmp_path):
    a = make(tmp_path)
    list(a.reply_stream("one"))
    first = a.conversation_id
    a.new_conversation()
    list(a.reply_stream("two"))
    assert a.conversation_id != first
    assert len(a.client.seen[-1]) == 2  # system + the new user message only


def test_spoken_mode_asks_for_short_plain_reply(tmp_path):
    a = make(tmp_path)
    list(a.reply_stream("hi", spoken=True))
    list(a.reply_stream("typed", spoken=False))
    assert "read aloud" in a.client.seen[0][0]["content"]
    assert "read aloud" not in a.client.seen[1][0]["content"]
