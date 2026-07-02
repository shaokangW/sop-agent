"""Tests for the artifacts + traces browser endpoints (path-traversal safe)."""
from __future__ import annotations

from fastapi.testclient import TestClient

from sopagent import server
from sopagent.config import Settings
from sopagent.harness import Tracer


def _patch_settings(monkeypatch, artifacts_dir, traces_dir) -> Settings:
    s = Settings(providers={}, artifacts_dir=str(artifacts_dir), traces_dir=str(traces_dir))
    monkeypatch.setattr(server.Settings, "from_env", classmethod(lambda cls: s))
    return s


def test_list_and_get_artifact(tmp_path, monkeypatch) -> None:
    art = tmp_path / "art"
    (art / "sub").mkdir(parents=True)
    (art / "a.txt").write_text("hello", encoding="utf-8")
    (art / "sub" / "b.md").write_text("# hi", encoding="utf-8")
    _patch_settings(monkeypatch, art, tmp_path / "traces")

    client = TestClient(server.app)
    r = client.get("/artifacts").json()
    paths = sorted(a["path"] for a in r["artifacts"])
    assert paths == ["a.txt", "sub/b.md"]
    assert r["artifacts"][0]["size"] == len("hello")

    body = client.get("/artifacts/sub/b.md").json()
    assert body["content"] == "# hi"


def test_get_artifact_missing_404(tmp_path, monkeypatch) -> None:
    _patch_settings(monkeypatch, tmp_path / "art", tmp_path / "traces")
    assert TestClient(server.app).get("/artifacts/nope.txt").status_code == 404


def test_artifact_path_traversal_403(tmp_path, monkeypatch) -> None:
    art = tmp_path / "art"
    art.mkdir()
    (art / "ok.txt").write_text("x", encoding="utf-8")
    secret = tmp_path / "secret.txt"
    secret.write_text("pw", encoding="utf-8")
    _patch_settings(monkeypatch, art, tmp_path / "traces")
    client = TestClient(server.app)
    # /artifacts/../secret.txt -> FastAPI collapses .. ; use an absolute-ish escape via .. segments
    assert client.get("/artifacts/%2e%2e/secret.txt").status_code in (403, 404)


def test_list_and_get_trace(tmp_path, monkeypatch) -> None:
    traces = tmp_path / "traces"
    traces.mkdir()
    t = Tracer("demo")
    t.turn("s", 0, "assistant", "hi", [], usage={"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5})
    t.finalize(True)
    t.dump_jsonl(traces / "demo.jsonl")
    _patch_settings(monkeypatch, tmp_path / "art", traces)

    client = TestClient(server.app)
    r = client.get("/traces").json()
    assert [x["name"] for x in r["traces"]] == ["demo.jsonl"]

    body = client.get("/traces/demo.jsonl").json()
    kinds = [rec["kind"] for rec in body["records"]]
    assert "turn" in kinds and "summary" in kinds


def test_get_trace_missing_and_bad_name(tmp_path, monkeypatch) -> None:
    _patch_settings(monkeypatch, tmp_path / "art", tmp_path / "traces")
    client = TestClient(server.app)
    assert client.get("/traces/nope.jsonl").status_code == 404
    assert client.get("/traces/%2e%2esecret").status_code == 400 or client.get("/traces/x%2fy").status_code == 400
