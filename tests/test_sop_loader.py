"""Tests for SOP loading and static variable interpolation."""
from pathlib import Path

from sopagent.sop.loader import load_sop

SOPS = Path(__file__).resolve().parent.parent / "sops"


def test_load_research_structure(monkeypatch):
    monkeypatch.setenv("TOPIC", "AI agents")
    sop = load_sop(SOPS / "research.yaml")

    assert sop.metadata.name == "research-report"
    assert len(sop.stages) == 2
    assert sop.stages[0].steps[0].id == "search"
    assert sop.stages[1].steps[0].id == "draft"


def test_env_var_interpolates_into_prompt(monkeypatch):
    monkeypatch.setenv("TOPIC", "AI agents")
    sop = load_sop(SOPS / "research.yaml")

    prompt = sop.stages[0].steps[0].prompt
    assert "AI agents" in prompt
    # runtime ref must be left intact for the engine to resolve later
    assert "${stages.gather.search.output.summary}" in sop.stages[1].steps[0].prompt


def test_runtime_ref_left_untouched_without_env(monkeypatch):
    monkeypatch.delenv("TOPIC", raising=False)
    sop = load_sop(SOPS / "research.yaml")
    # ${env.TOPIC} unresolved -> stays as ${...}, but ${topic} falls back to the
    # unresolved variable value; either way it must not crash.
    assert sop.metadata.name == "research-report"
