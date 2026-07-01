"""CLI entrypoint: SOP mode (`run`) and autonomous mode (`task`).

Both modes drive the engine/agent event stream. With --interactive, approval
requests prompt the user (y/N); otherwise they are auto-approved.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from .config import Settings
from .harness import (
    ApprovalPolicy,
    ApprovalRequest,
    ArtifactStore,
    AutonomousAgent,
    DoneEvent,
    Engine,
    InteractiveSession,
    ToolExecutedEvent,
    Tracer,
)
from .llm import LLMRouter, ProviderRegistry
from .sop.loader import load_sop
from .sop.schema import LlmConfig
from .tools import BUILTIN_TOOLS, ToolExecutor, ToolRegistry
from .tools.mcp_client import register_mcp_servers

app = typer.Typer(add_completion=False, help="SOP + harness agent prototype")
console = Console()


# -- construction ---------------------------------------------------------
def build_engine_from_sop(sop, settings: Settings) -> Engine:
    providers = ProviderRegistry.from_settings(settings)
    router = LLMRouter(providers)
    tool_registry = ToolRegistry()
    for tool in BUILTIN_TOOLS:
        tool_registry.register(tool)
    register_mcp_servers(sop, tool_registry)
    return Engine(
        sop=sop,
        router=router,
        tool_registry=tool_registry,
        tool_executor=ToolExecutor(tool_registry),
        artifacts=ArtifactStore(settings.artifacts_dir),
        tracer=Tracer(sop.metadata.name),
    )


def build_engine(sop_path: Path, settings: Settings) -> Engine:
    return build_engine_from_sop(load_sop(sop_path), settings)


def build_agent(task: str, settings: Settings) -> AutonomousAgent:
    providers = ProviderRegistry.from_settings(settings)
    router = LLMRouter(providers)
    tool_registry = ToolRegistry()
    for tool in BUILTIN_TOOLS:
        tool_registry.register(tool)
    return AutonomousAgent(
        task=task,
        router=router,
        tool_registry=tool_registry,
        tool_executor=ToolExecutor(tool_registry),
        artifacts=ArtifactStore(settings.artifacts_dir),
        llm_config=LlmConfig(provider="bailian", model="glm-5.2"),
        tracer=Tracer("autonomous"),
    )


def _apply_stream(stream: bool) -> None:
    if stream:
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        except (AttributeError, ValueError):
            pass


# -- event-stream driving with interactive approval ----------------------
def _ask_approval(req: ApprovalRequest) -> str:
    body = f"{req.reason}\n\n" + json.dumps(req.payload, ensure_ascii=False, indent=2)
    console.print(Panel(body, title="Approval required", border_style="yellow"))
    ans = input("Approve? [y/N]: ").strip().lower()
    return "approve" if ans in ("y", "yes") else "reject"


def _drive(gen, interactive: bool) -> Any:
    trace: Any = None
    ev = next(gen)
    try:
        while True:
            if isinstance(ev, ApprovalRequest):
                decision = _ask_approval(ev) if interactive else "approve"
                ev = gen.send(decision)
            elif isinstance(ev, DoneEvent):
                trace = ev.trace
                break
            else:
                ev = next(gen)
    except StopIteration:
        pass
    return trace


def _render_trace(trace) -> None:
    table = Table(title=f"Trace: {trace.sop_name}  ({'OK' if trace.success else 'FAIL'})")
    table.add_column("step")
    table.add_column("status")
    table.add_column("attempts")
    table.add_column("turns")
    table.add_column("dur(s)")
    for s in trace.steps:
        table.add_row(
            s.step_id,
            s.status,
            str(s.attempts),
            str(s.turns),
            f"{s.duration:.2f}" if s.duration else "-",
        )
    console.print(table)


# -- SOP mode -------------------------------------------------------------
@app.command()
def run(
    sop: Path = typer.Argument(..., help="Path to the SOP YAML file"),
    artifacts_dir: str = typer.Option(".artifacts", help="Where to save artifacts"),
    stream: bool = typer.Option(False, "--stream", help="Stream tokens to stdout"),
    interactive: bool = typer.Option(False, "-i", "--interactive", help="Prompt for approvals"),
) -> None:
    """Run a SOP end-to-end (SOP mode)."""
    settings = Settings.from_env()
    settings.artifacts_dir = artifacts_dir

    engine = build_engine(sop, settings)
    if interactive:
        engine.approval_policy = ApprovalPolicy(approve_all_tools=True, approve_steps=True)
    if stream:
        _apply_stream(True)
        engine.on_token = lambda step_id, delta: (sys.stdout.write(delta), sys.stdout.flush())
    console.print(f"[bold]Running SOP:[/bold] {engine.sop.metadata.name}")

    trace = _drive(engine.run_events(), interactive)
    _render_trace(trace)
    if not trace.success:
        raise typer.Exit(code=1)


# -- autonomous mode ------------------------------------------------------
@app.command()
def task(
    task_text: str = typer.Argument(..., help="Natural-language task"),
    artifacts_dir: str = typer.Option(".artifacts", help="Where to save artifacts"),
    stream: bool = typer.Option(False, "--stream", help="Stream tokens to stdout"),
    interactive: bool = typer.Option(False, "-i", "--interactive", help="Prompt for approvals"),
    max_turns: int = typer.Option(20, "--max-turns", help="Max agent turns"),
) -> None:
    """Run an autonomous agent on a free-form task (autonomous mode)."""
    settings = Settings.from_env()
    settings.artifacts_dir = artifacts_dir

    agent = build_agent(task_text, settings)
    agent.max_turns = max_turns
    if interactive:
        agent.approval_policy = ApprovalPolicy(approve_all_tools=True, approve_subgoals=True)
    if stream:
        _apply_stream(True)
        agent.on_token = lambda step_id, delta: (sys.stdout.write(delta), sys.stdout.flush())
    console.print(f"[bold]Autonomous task:[/bold] {task_text}")

    trace = _drive(agent.run_events(), interactive)
    _render_trace(trace)
    if getattr(agent, "summary", None):
        console.print(f"[bold]Summary:[/bold] {agent.summary}")
    if not trace.success:
        raise typer.Exit(code=1)


# -- interactive REPL mode (claude-code style) ---------------------------
def _build_session(approve_all: bool, max_turns: int) -> InteractiveSession:
    settings = Settings.from_env()
    providers = ProviderRegistry.from_settings(settings)
    router = LLMRouter(providers)
    tool_registry = ToolRegistry()
    for tool in BUILTIN_TOOLS:
        tool_registry.register(tool)
    executor = ToolExecutor(tool_registry)
    return InteractiveSession(
        router=router,
        tool_registry=tool_registry,
        tool_executor=executor,
        llm_config=LlmConfig(provider="bailian", model="glm-5.2"),
        on_token=lambda sid, delta: (sys.stdout.write(delta), sys.stdout.flush()),
        approval_policy=ApprovalPolicy(approve_all_tools=approve_all),
        max_turns=max_turns,
    )


@app.command()
def chat(
    max_turns: int = typer.Option(15, "--max-turns", help="Max tool turns per user message"),
    approve_all: bool = typer.Option(False, "--approve", help="Require approval on every tool call"),
) -> None:
    """Interactive chat (claude-code style TUI: output above, input box below)."""
    session = _build_session(approve_all, max_turns)
    try:
        from .harness.tui import ChatTUI

        ChatTUI(session).run()
        return
    except Exception:
        import traceback

        Path("tui_err.log").write_text(traceback.format_exc(), encoding="utf-8")
        console.print("[dim]TUI 不可用，回退行输入；详见 tui_err.log[/dim]")

    # fallback: line-based REPL
    console.print("[bold]sop-agent chat[/bold] — 输入任务回车发送；/exit 退出；/clear 清空")
    while True:
        try:
            user = input("\n>>> ").strip()
        except (EOFError, KeyboardInterrupt):
            console.print()
            break
        if not user:
            continue
        if user in ("/exit", "/quit", ":q"):
            break
        if user == "/clear":
            session.reset()
            console.print("[dim](已清空对话历史)[/dim]")
            continue
        if user == "/tools":
            console.print(", ".join(session.tool_names()))
            continue
        gen = session.ask(user)
        try:
            ev = next(gen)
            while True:
                if isinstance(ev, ApprovalRequest):
                    body = f"{ev.reason}\n" + json.dumps(ev.payload, ensure_ascii=False, indent=2)
                    console.print(Panel(body, title="Approval", border_style="yellow"))
                    ans = input("Approve? [y/N]: ").strip().lower()
                    ev = gen.send("approve" if ans in ("y", "yes") else "reject")
                elif isinstance(ev, ToolExecutedEvent):
                    mark = "[green]ok[/green]" if ev.ok else "[red]FAIL[/red]"
                    console.print(f"\n[dim]tool {ev.name} {mark}[/dim]")
                    ev = next(gen)
                else:
                    ev = next(gen)
        except StopIteration:
            pass


if __name__ == "__main__":
    app()
