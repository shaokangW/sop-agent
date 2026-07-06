"""Validator: zero-trust pre-execution hook (玄猫).

Runs before any dangerous tool (bash/write_file/edit_file) executes. Two-stage:
1. Rule pre-filter (regex blacklist from validator_rules.yaml) — instant block.
2. LLM judge (玄猫 persona) — asks the model whether the operation is dangerous,
   parses JSON {dangerous, reason}.

Blocked calls emit a SecurityAlertEvent (via the injected on_alert callback) and
return a Verdict that makes ToolExecutor short-circuit with "BLOCKED by validator".
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import yaml

from ..llm.base import Message
from ..llm.router import LLMRouter
from ..tools.base import Verdict
from .events import SecurityAlertEvent

_RULES_FILE = Path(__file__).parent / "validator_rules.yaml"
_DANGEROUS = {"bash", "write_file", "edit_file"}

_VALIDATOR_SYSTEM = (
    "你是玄猫,MeowWork 的零信任安全网关。判定一条工具操作是否危险。"
    "危险=系统级删除/破坏、密钥凭据读取、权限提升/持久化、敏感数据外传、沙箱逃逸。"
    "正常开发命令(git/pytest/ls 项目内/读项目文件)放行。"
    "只返回严格 JSON:{\"dangerous\": true|false, \"reason\": \"...\"}。"
)


@dataclass
class Rule:
    tools: list[str]
    field: str  # argument key to inspect (bash: command; write/edit: path)
    pattern: re.Pattern
    reason: str

    def match(self, tool_name: str, args: dict) -> bool:
        if tool_name not in self.tools:
            return False
        val = str(args.get(self.field, ""))
        return bool(self.pattern.search(val))


def load_rules(path: Path = _RULES_FILE) -> list[Rule]:
    if not path.exists():
        return []
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    out: list[Rule] = []
    for r in data.get("rules", []):
        try:
            out.append(Rule(
                tools=list(r.get("tools", [])),
                field=r.get("field", "command"),
                pattern=re.compile(r["pattern"]),
                reason=r.get("reason", "命中黑名单规则"),
            ))
        except (KeyError, re.error):
            continue
    return out


class ValidatorHook:
    """Pre-execution hook: rule blacklist + LLM judge."""

    def __init__(
        self,
        llm_router: LLMRouter,
        llm_config: Any,
        rules: list[Rule] | None = None,
        on_alert: Callable[[SecurityAlertEvent], None] | None = None,
    ) -> None:
        self._router = llm_router
        self._llm_config = llm_config
        self._rules = rules if rules is not None else load_rules()
        self._on_alert = on_alert

    def check(self, tool_name: str, arguments: dict[str, Any]) -> Verdict:
        if tool_name not in _DANGEROUS:
            return Verdict(allow=True)  # read-only / safe tools pass
        # 1) rule pre-filter
        for rule in self._rules:
            if rule.match(tool_name, arguments):
                return self._block(tool_name, arguments, rule.reason, source="rule")
        # 2) LLM judge
        return self._llm_check(tool_name, arguments)

    def _block(self, tool_name: str, args: dict, reason: str, *, source: str) -> Verdict:
        if self._on_alert:
            self._on_alert(SecurityAlertEvent(tool=tool_name, args=args, reason=reason, blocked=True))
        return Verdict(allow=False, reason=f"[{source}] {reason}", source=source)

    def _llm_check(self, tool_name: str, args: dict[str, Any]) -> Verdict:
        payload = json.dumps({k: str(v)[:500] for k, v in args.items()}, ensure_ascii=False)
        prompt = f"工具:{tool_name}\n参数:{payload}\n\n判定此操作是否危险,返回 JSON。"
        try:
            resp = self._router.chat(
                [{"role": "system", "content": _VALIDATOR_SYSTEM},
                 {"role": "user", "content": prompt}],
                [], self._llm_config,
            )
            data = _parse_json(resp.content or "")
        except Exception:
            return Verdict(allow=True)  # fail-open on LLM error (don't block legit ops)
        if not isinstance(data, dict) or data.get("dangerous") is not True:
            return Verdict(allow=True)
        reason = str(data.get("reason") or "玄猫判定危险")
        return self._block(tool_name, args, reason, source="llm")


def _parse_json(text: str) -> Any:
    """Extract JSON from a model response (handles ```json fences)."""
    t = text.strip()
    if t.startswith("```"):
        # strip fenced block
        t = re.sub(r"^```(?:json)?\s*", "", t)
        t = re.sub(r"\s*```$", "", t)
        t = t.strip()
    # find first {...}
    m = re.search(r"\{.*\}", t, re.DOTALL)
    if m:
        t = m.group(0)
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        return None
