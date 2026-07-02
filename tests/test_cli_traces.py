"""Tests for the `sopagent traces` CLI subcommand (list/show replay)."""
from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from sopagent.cli import app
from sopagent.harness import Tracer

runner = CliRunner()


def _dump(tmp_path: Path) -> Path:
    t = Tracer("demo")
    t.turn("s0", 0, "assistant", "hello world", [{"id": "c1", "name": "echo"}], usage={"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5})
    t.turn("s0", 0, "tool", "echoed")
    t.finalize(True)
    p = tmp_path / "demo.jsonl"
    t.dump_jsonl(p)
    return p


def test_traces_list_empty(tmp_path: Path) -> None:
    r = runner.invoke(app, ["traces", "list", "--traces-dir", str(tmp_path)])
    assert r.exit_code == 0
    assert "无 trace" in r.output


def test_traces_list_and_show(tmp_path: Path) -> None:
    _dump(tmp_path)
    r = runner.invoke(app, ["traces", "list", "--traces-dir", str(tmp_path)])
    assert r.exit_code == 0
    assert "demo.jsonl" in r.output

    r2 = runner.invoke(app, ["traces", "show", "demo.jsonl", "--traces-dir", str(tmp_path)])
    assert r2.exit_code == 0
    assert "assistant" in r2.output
    assert "summary" in r2.output
    assert "tokens" in r2.output  # usage shown
    assert "echo" in r2.output  # tool_call name rendered (flat asdict shape)


def test_traces_show_missing(tmp_path: Path) -> None:
    r = runner.invoke(app, ["traces", "show", "nope.jsonl", "--traces-dir", str(tmp_path)])
    assert r.exit_code == 1
    assert "not found" in r.output
