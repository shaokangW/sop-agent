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

from .config import Settings, load_mcp_servers
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
    replay_jsonl,
)
from .llm import LLMRouter, ProviderRegistry
from .sop.loader import load_sop
from .sop.schema import LlmConfig
from .skills import SkillRegistry
from .tools import BUILTIN_TOOLS, ToolExecutor, ToolRegistry
from .tools.builtin import SkillTool, SubAgentContext, TaskTool
from .tools.mcp_client import register_mcp_servers

app = typer.Typer(add_completion=False, help="SOP + harness agent prototype")
console = Console()


def _register_task_tool(
    router: LLMRouter,
    tool_registry: ToolRegistry,
    llm_config: LlmConfig,
    settings: Settings,
    max_turns: int = 15,
) -> None:
    """Register the contextual `task` (sub-agent delegation) tool."""
    ctx = SubAgentContext(
        router=router,
        tool_registry=tool_registry,
        llm_config=llm_config,
        artifacts=ArtifactStore(settings.artifacts_dir),
        approval_policy=ApprovalPolicy(),
        max_turns=max_turns,
    )
    tool_registry.register(TaskTool(ctx))


# -- construction ---------------------------------------------------------
def build_engine_from_sop(sop, settings: Settings) -> Engine:
    providers = ProviderRegistry.from_settings(settings)
    router = LLMRouter(providers)
    tool_registry = ToolRegistry()
    for tool in BUILTIN_TOOLS:
        tool_registry.register(tool)
    register_mcp_servers(load_mcp_servers(), tool_registry)
    register_mcp_servers(sop, tool_registry)
    _register_task_tool(router, tool_registry, sop.llm_defaults, settings)
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


def build_agent(task: str, settings: Settings, provider: str | None = None, model: str | None = None) -> AutonomousAgent:
    providers = ProviderRegistry.from_settings(settings)
    router = LLMRouter(providers)
    tool_registry = ToolRegistry()
    for tool in BUILTIN_TOOLS:
        tool_registry.register(tool)
    register_mcp_servers(load_mcp_servers(), tool_registry)
    llm_config = LlmConfig(provider=provider or "bailian", model=model or "glm-5.2")
    skill_registry = SkillRegistry.load_default()
    tool_registry.register(SkillTool(skill_registry))
    _register_task_tool(router, tool_registry, llm_config, settings)
    return AutonomousAgent(
        task=task,
        router=router,
        tool_registry=tool_registry,
        tool_executor=ToolExecutor(tool_registry),
        artifacts=ArtifactStore(settings.artifacts_dir),
        llm_config=llm_config,
        tracer=Tracer("autonomous"),
        available_skills=skill_registry.available("autonomous"),
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
                _print_event(ev)
                ev = next(gen)
    except StopIteration:
        pass
    return trace


def _print_event(ev) -> None:
    """Echo agent activity so CLI users can follow what the agent is doing."""
    if isinstance(ev, ToolExecutedEvent):
        mark = "[green]ok[/green]" if ev.ok else "[red]FAIL[/red]"
        if ev.name == "task":
            # sub-agent delegation: result is a multi-line summary + tool log
            console.print(f"\n[dim]▸ task {mark}[/dim]")
            for line in (ev.result or "").splitlines():
                console.print(f"[dim]  {line}[/dim]")
        else:
            preview = (ev.result or "").strip().replace("\n", " ")[:160]
            console.print(f"[dim]▸ {ev.name} {mark}: {preview}[/dim]")
    # TurnEvent content is omitted: with --stream tokens already show; otherwise
    # the final summary (finish) is printed after the run.


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
    u = getattr(trace, "usage", None)
    if u and u.get("total_tokens"):
        console.print(
            f"[dim]tokens: {u['total_tokens']} total "
            f"(prompt {u['prompt_tokens']} / completion {u['completion_tokens']})[/dim]"
        )


# -- SOP mode -------------------------------------------------------------
@app.command()
def run(
    sop: Path = typer.Argument(..., help="Path to the SOP YAML file"),
    artifacts_dir: str = typer.Option(".artifacts", help="Where to save artifacts"),
    stream: bool = typer.Option(False, "--stream", help="Stream tokens to stdout"),
    interactive: bool = typer.Option(False, "-i", "--interactive", help="Prompt for approvals"),
    trace: bool = typer.Option(False, "--trace", help="Dump a JSONL trace to .traces/"),
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

    tr = _drive(engine.run_events(), interactive)
    _render_trace(tr)
    if trace:
        _dump_trace(engine.tracer, engine.sop.metadata.name, settings.traces_dir)
    if not tr.success:
        raise typer.Exit(code=1)


# -- autonomous mode ------------------------------------------------------
@app.command()
def task(
    task_text: str = typer.Argument(..., help="Natural-language task"),
    artifacts_dir: str = typer.Option(".artifacts", help="Where to save artifacts"),
    stream: bool = typer.Option(False, "--stream", help="Stream tokens to stdout"),
    interactive: bool = typer.Option(False, "-i", "--interactive", help="Prompt for approvals"),
    max_turns: int = typer.Option(20, "--max-turns", help="Max agent turns"),
    trace: bool = typer.Option(False, "--trace", help="Dump a JSONL trace to .traces/"),
    provider: str = typer.Option(None, "--provider", help="LLM provider (bailian/openai/anthropic/ollama)"),
    model: str = typer.Option(None, "--model", help="Model name"),
) -> None:
    """Run an autonomous agent on a free-form task (autonomous mode)."""
    settings = Settings.from_env()
    settings.artifacts_dir = artifacts_dir

    agent = build_agent(task_text, settings, provider=provider, model=model)
    agent.max_turns = max_turns
    if interactive:
        agent.approval_policy = ApprovalPolicy(approve_all_tools=True, approve_subgoals=True)
    if stream:
        _apply_stream(True)
        agent.on_token = lambda step_id, delta: (sys.stdout.write(delta), sys.stdout.flush())
    console.print(f"[bold]Autonomous task:[/bold] {task_text}")

    tr = _drive(agent.run_events(), interactive)
    _render_trace(tr)
    if trace:
        _dump_trace(agent.tracer, "autonomous", settings.traces_dir)
    if getattr(agent, "summary", None):
        console.print(f"[bold]Summary:[/bold] {agent.summary}")
    if not tr.success:
        raise typer.Exit(code=1)


def _dump_trace(tracer, name: str, traces_dir: str) -> None:
    import time as _t
    from pathlib import Path as _P

    path = _P(traces_dir) / f"{name}-{int(_t.time())}.jsonl"
    tracer.dump_jsonl(path)
    console.print(f"[dim]trace -> {path}[/dim]")


# -- interactive REPL mode (claude-code style) ---------------------------
def _build_session(approve_all: bool, max_turns: int, provider: str | None = None, model: str | None = None) -> InteractiveSession:
    settings = Settings.from_env()
    providers = ProviderRegistry.from_settings(settings)
    router = LLMRouter(providers)
    tool_registry = ToolRegistry()
    for tool in BUILTIN_TOOLS:
        tool_registry.register(tool)
    register_mcp_servers(load_mcp_servers(), tool_registry)
    llm_config = LlmConfig(provider=provider or "bailian", model=model or "glm-5.2")
    skill_registry = SkillRegistry.load_default()
    tool_registry.register(SkillTool(skill_registry))
    _register_task_tool(router, tool_registry, llm_config, settings, max_turns=max_turns)
    executor = ToolExecutor(tool_registry)
    from .harness.context_window import ContextWindowManager

    return InteractiveSession(
        router=router,
        tool_registry=tool_registry,
        tool_executor=executor,
        llm_config=llm_config,
        on_token=lambda sid, delta: (sys.stdout.write(delta), sys.stdout.flush()),
        approval_policy=ApprovalPolicy(approve_all_tools=approve_all),
        max_turns=max_turns,
        context_manager=ContextWindowManager(router=router, llm_config=llm_config),
        available_skills=skill_registry.available("chat"),
    )


@app.command()
def chat(
    max_turns: int = typer.Option(15, "--max-turns", help="Max tool turns per user message"),
    approve_all: bool = typer.Option(False, "--approve", help="Require approval on every tool call"),
    provider: str = typer.Option(None, "--provider", help="LLM provider (bailian/openai/anthropic/ollama)"),
    model: str = typer.Option(None, "--model", help="Model name"),
) -> None:
    """Interactive chat (claude-code style TUI: output above, input box below)."""
    session = _build_session(approve_all, max_turns, provider=provider, model=model)
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
    cm = getattr(session, "context_manager", None)
    if cm is not None:
        cm.on_compress = lambda stats: console.print(
            f"[dim]✦ 上下文已压缩(省 ~{(stats.get('before_tokens',0)-stats.get('after_tokens',0))} tokens)[/dim]"
        )
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


# -- trace inspection -----------------------------------------------------
traces_app = typer.Typer(help="Inspect dumped JSONL traces (from --trace)")
app.add_typer(traces_app, name="traces")


@traces_app.command("list")
def traces_list(
    traces_dir: str = typer.Option(".traces", help="traces directory"),
) -> None:
    """List dumped JSONL traces."""
    base = Path(traces_dir)
    if not base.is_dir():
        console.print("[dim]无 trace 目录[/dim]")
        return
    files = sorted(base.glob("*.jsonl"), key=lambda f: f.stat().st_mtime, reverse=True)
    if not files:
        console.print("[dim]无 trace(用 `sopagent task ... --trace` 或 `run ... --trace` 生成)[/dim]")
        return
    table = Table(title=f"traces in {base}")
    table.add_column("name")
    table.add_column("size")
    table.add_column("mtime")
    for f in files:
        import datetime

        mt = datetime.datetime.fromtimestamp(f.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
        table.add_row(f.name, f"{f.stat().st_size} B", mt)
    console.print(table)


@traces_app.command("show")
def traces_show(
    name: str = typer.Argument(..., help="trace file name (in traces dir)"),
    traces_dir: str = typer.Option(".traces", help="traces directory"),
) -> None:
    """Replay a dumped trace: print each turn + summary."""
    p = Path(traces_dir) / name
    if not p.exists():
        console.print(f"[red]not found: {p}[/red]")
        raise typer.Exit(code=1)
    for rec in replay_jsonl(p):
        if rec.get("kind") == "turn":
            role = rec.get("role", "?")
            sid = rec.get("step_id", "")
            tn = rec.get("turn", "")
            preview = rec.get("content_preview", "")
            console.print(f"[cyan]{role}[/cyan] [dim][{sid}#{tn}][/dim] {preview}")
            for tc in rec.get("tool_calls") or []:
                # tolerate both nested (OpenAI) and flat (asdict(ToolCall)) shapes
                fn = (tc or {}).get("function") or {}
                name = fn.get("name") or (tc or {}).get("name")
                args = fn.get("arguments") if "function" in (tc or {}) else (tc or {}).get("arguments")
                console.print(f"  [dim]tool: {name}({args})[/dim]")
            u = rec.get("usage")
            if u:
                console.print(f"  [dim]tokens: {u.get('total_tokens', 0)}[/dim]")
        elif rec.get("kind") == "summary":
            u = rec.get("usage", {})
            console.print(
                Panel(
                    f"{rec.get('sop_name','')} | turns {rec.get('turns',0)} | steps {rec.get('steps',0)} | "
                    f"tokens {u.get('total_tokens',0)} (p{u.get('prompt_tokens',0)}/c{u.get('completion_tokens',0)})",
                    title="summary",
                    border_style="cyan",
                )
            )


if __name__ == "__main__":
    app()
