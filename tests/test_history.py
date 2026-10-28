from zana.storage.history import HistoryStore


def test_roundtrip_and_order(tmp_path):
    s = HistoryStore(tmp_path / "h.db")
    cid = s.create_conversation("t")
    s.add_message(cid, "user", "a")
    s.add_message(cid, "assistant", "b")
    s.add_message(cid, "user", "c")
    assert [m["content"] for m in s.get_messages(cid)] == ["a", "b", "c"]
    assert [m["content"] for m in s.get_messages(cid, limit=2)] == ["b", "c"]


def test_delete_cascades_and_clear(tmp_path):
    s = HistoryStore(tmp_path / "h.db")
    a, b = s.create_conversation("a"), s.create_conversation("b")
    s.add_message(a, "user", "x")
    s.delete_conversation(a)
    assert s.get_messages(a) == []
    assert [c["id"] for c in s.list_conversations()] == [b]
    s.clear_all()
    assert s.list_conversations() == []


def test_persists_across_instances(tmp_path):
    p = tmp_path / "sub" / "h.db"
    cid = HistoryStore(p).create_conversation("keep")
    assert HistoryStore(p).list_conversations()[0]["id"] == cid
