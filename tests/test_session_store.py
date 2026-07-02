"""Tests for SessionStore: durable per-session JSON persistence."""
from __future__ import annotations

from sopagent.harness.session_store import SessionStore


def _msgs():
    return [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello"},
    ]


def test_create_and_load(tmp_path) -> None:
    store = SessionStore(tmp_path)
    sid = store.create()
    assert store.load(sid)["messages"] == []

    store.save(sid, _msgs(), title="first chat")
    rec = store.load(sid)
    assert rec["title"] == "first chat"
    assert [m["role"] for m in rec["messages"]] == ["system", "user", "assistant"]
    assert rec["updated_at"] >= rec["created_at"]


def test_list_sorted_by_updated(tmp_path) -> None:
    store = SessionStore(tmp_path)
    a = store.create()
    b = store.create()
    store.save(a, [{"role": "user", "content": "x"}], title="A")
    store.save(b, [{"role": "user", "content": "y"}], title="B")  # newer
    items = store.list_sessions()
    assert [i["title"] for i in items] == ["B", "A"]
    assert all("message_count" in i for i in items)


def test_load_missing_returns_none(tmp_path) -> None:
    assert SessionStore(tmp_path).load("nope") is None


def test_delete(tmp_path) -> None:
    store = SessionStore(tmp_path)
    sid = store.create()
    assert store.delete(sid) is True
    assert store.delete(sid) is False
    assert store.load(sid) is None


def test_save_updates_title_and_messages(tmp_path) -> None:
    store = SessionStore(tmp_path)
    sid = store.create(title="t0")
    store.save(sid, [{"role": "user", "content": "m1"}])
    store.save(sid, [{"role": "user", "content": "m2"}], title="t1")
    rec = store.load(sid)
    assert rec["title"] == "t1"
    assert rec["messages"] == [{"role": "user", "content": "m2"}]


def test_corrupt_file_skipped_in_list(tmp_path) -> None:
    store = SessionStore(tmp_path)
    store.create()
    (tmp_path / "bad.json").write_text("{not json", encoding="utf-8")
    items = store.list_sessions()
    assert all(i["id"] != "bad" for i in items)


def test_save_without_create_persists(tmp_path) -> None:
    # save() on an unknown id creates the record on the fly
    store = SessionStore(tmp_path)
    store.save("custom-id", [{"role": "system", "content": "s"}], title="custom")
    rec = store.load("custom-id")
    assert rec is not None and rec["title"] == "custom"
