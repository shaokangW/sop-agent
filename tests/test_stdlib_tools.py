"""Tests for the standard built-in tools."""
from __future__ import annotations

from pathlib import Path

from sopagent.tools.builtin.stdlib import (
    BashTool,
    EditFileTool,
    GrepTool,
    ListDirTool,
    ReadFileTool,
    TodoWriteTool,
    WebFetchTool,
    WriteFileTool,
)


def test_read_write_edit_cycle(tmp_path: Path) -> None:
    p = tmp_path / "f.txt"
    assert "wrote" in WriteFileTool().run({"path": str(p), "content": "hello world"})
    assert "hello" in ReadFileTool().run({"path": str(p)})
    assert EditFileTool().run({"path": str(p), "old_string": "hello", "new_string": "hi"}) == "edited ok"
    assert "hi world" in ReadFileTool().run({"path": str(p)})


def test_edit_not_found(tmp_path: Path) -> None:
    p = tmp_path / "f.txt"
    p.write_text("abc", encoding="utf-8")
    assert "not found" in EditFileTool().run({"path": str(p), "old_string": "zzz", "new_string": "y"})


def test_edit_not_unique(tmp_path: Path) -> None:
    p = tmp_path / "f.txt"
    p.write_text("x x x", encoding="utf-8")
    assert "matches" in EditFileTool().run({"path": str(p), "old_string": "x", "new_string": "y"})


def test_list_dir(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("x", encoding="utf-8")
    (tmp_path / "b").mkdir()
    out = ListDirTool().run({"path": str(tmp_path)})
    assert "a.txt" in out and "b/" in out


def test_grep(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("def foo():\n    pass\n", encoding="utf-8")
    (tmp_path / "b.py").write_text("def bar():\n    pass\n", encoding="utf-8")
    out = GrepTool().run({"pattern": "foo", "path": str(tmp_path)})
    assert "foo" in out and "a.py" in out
    assert "bar" not in out


def test_bash() -> None:
    out = BashTool().run({"command": "echo hello_opencode"})
    assert "hello_opencode" in out


def test_todo_write(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    out = TodoWriteTool().run({"todos": [{"content": "task a", "status": "pending"}]})
    assert "[pending] task a" in out
    assert (tmp_path / ".todos.json").exists()


def test_dangerous_tools_require_approval() -> None:
    assert getattr(WriteFileTool(), "requires_approval", False) is True
    assert getattr(EditFileTool(), "requires_approval", False) is True
    assert getattr(BashTool(), "requires_approval", False) is True
    assert getattr(ReadFileTool(), "requires_approval", False) is False
    assert getattr(ListDirTool(), "requires_approval", False) is False
    assert getattr(GrepTool(), "requires_approval", False) is False
    assert getattr(WebFetchTool(), "requires_approval", False) is False
    assert getattr(TodoWriteTool(), "requires_approval", False) is False
