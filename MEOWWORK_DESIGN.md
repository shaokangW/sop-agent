# MeowWork 技术设计文档(v1)

> 多智能体协作与监控系统。基于 sop-agent 内核,新增 GroupChat 协作层。SOP 编排暂不接入,先做多 Agent 自主协同。
>
> 决策:① 自研 transitions(不引 LangGraph)② Next.js 前端 ③ 逻辑 PID 子 agent ④ Validator 用 LLM 判定(+规则预筛)⑤ 全做。
>
> 协作模式:LLM 路由兜底 + 自主交棒优先;共享讨论历史;Planner 阶段框架 + 阶段内自由讨论。

---

## 1. 架构总览

```
┌─────────────────────────────────────────────────────────┐
│  GroupOrchestrator(对话循环 + 路由 + 全局 state)         │
│  ├─ roles: {planner, executor, reviewer, validator}     │
│  ├─ state: GroupState(单事实来源,WS 订阅)               │
│  ├─ shared messages(所有猫可见的讨论历史)                │
│  └─ run_events() → yield Event(复用 sop-agent 事件流)   │
├─────────────────────────────────────────────────────────┤
│  四猫(AgentRole,各带 persona + 工具白名单)              │
│   planner  → 拆任务/推进 phase/汇总                      │
│   executor → 写代码/调工具/delegate 子 agent             │
│   reviewer → 审查/pass/打回                              │
│   validator → 工具执行前 hook(不占讨论轮)                │
├─────────────────────────────────────────────────────────┤
│  对话工具(send_message/broadcast/delegate/              │
│           update_state/finish_task)                     │
├─────────────────────────────────────────────────────────┤
│  sop-agent 内核(复用):LLMRouter/ToolExecutor/           │
│    ToolRegistry/ApprovalPolicy/Tracer/事件流/MCP/        │
│    TaskTool 委派机制                                     │
└─────────────────────────────────────────────────────────┘
```

四猫不是对等节点,是**层级路由 + 中间件拦截**:Planner 是大脑(路由 + phase 推进),Executor/Reviewer 在阶段内自由讨论,Validator 是工具执行前的硬拦截卡点(不在讨论环路)。

---

## 2. 数据结构

### 2.1 AgentRole(`meowwork/roles.py`)

```python
@dataclass
class AgentRole:
    name: str            # planner|executor|reviewer|validator
    persona: str         # 布偶猫|橘猫|狸花猫|玄猫
    system_prompt: str   # 职责 + 何时发言/交棒 + 可见 state 字段
    tools: list[str]     # 工具白名单(对话工具 + 业务工具)
    can_delegate: bool   # 是否能 delegate 子 agent(planner/executor)
    can_update_state: bool
    llm: LlmConfig       # 各猫可不同模型(如 validator 用便宜模型)
```

### 2.2 GroupState(`meowwork/state.py`)— 单事实来源

```python
@dataclass
class GroupState:
    task: str                              # 原始任务
    phase: str                             # analyze|execute|review|validate|done
    plan_tree: dict                        # {step_1: {desc,status,assignee,artifact}}
    current_artifact: str | None           # 当前主产出(代码/文档)
    review_feedback: str | None            # 审查反馈
    review_pass: bool | None               # 审查结论
    security_alerts: list[dict]            # [{tool, reason, blocked, ts}]
    sub_agents: list[dict]                 # 逻辑 PID [{pid, role, task, status}]
    turn: int                              # 发言轮次
    finished: bool
    summary: str | None
    # messages 不存 state(存 Orchestrator 的共享历史,避免双写)
```

`to_dict()` 供 WS 推送 + 前端订阅。`update(key, value, by)` 带权限校验 + 产出 `StateUpdateEvent`。

### 2.3 讨论消息

复用 sop-agent `Message`(dict)。讨论历史每条:
```python
{"role": "assistant", "name": "executor", "content": "...", "to": "reviewer"|None}
```
`name`=发言者,`to`=定向目标(None=广播)。所有猫的 system prompt 注入"讨论历史"作为 context。

---

## 3. 事件协议(WS / 轮询)

复用 sop-agent 事件流,新增 5 种:

| Event | 字段 | 触发 |
|---|---|---|
| `MessageEvent` | from, to, content | agent 发言 |
| `StateUpdateEvent` | key, old, new, by | update_state 工具 |
| `PhaseEvent` | from, to, by | phase 变化 |
| `SubAgentEvent` | pid, role, task, status | delegate 子 agent 启停 |
| `SecurityAlertEvent` | tool, args, reason, blocked | Validator 拦截 |

原有 `TokenEvent`/`TurnEvent`/`ToolExecutedEvent`/`ApprovalRequest`/`DoneEvent` 保留。WS 端点广播全量事件 + state 快照。

---

## 4. 对话工具(`meowwork/tools.py`)

给 agent 调用的工具(注册到各猫的 ToolRegistry):

| 工具 | 参数 | 行为 | 权限 |
|---|---|---|---|
| `send_message` | to, content | 追加讨论消息(定向),触发自主交棒 | 全猫 |
| `broadcast` | content | 追加讨论消息(广播) | 全猫 |
| `delegate` | role, task | 拉起某角色子 agent(逻辑 PID),返回结果 | planner/executor |
| `update_state` | key, value | 改 state(权限校验) | 按字段(见下) |
| `finish_task` | summary | 标记 finished | planner |

`update_state` 权限矩阵:
- `plan_tree` / `phase` / `summary` / `finished` → planner
- `current_artifact` → executor
- `review_feedback` / `review_pass` → reviewer
- `security_alerts` → validator(自动)

---

## 5. GroupOrchestrator(`meowwork/orchestrator.py`)

### 5.1 对话循环(核心)

```python
class GroupOrchestrator:
    def __init__(self, task, roles, router, llm_router, ...):
        self.state = GroupState(task=task, phase="analyze", ...)
        self.messages: list[Message] = []   # 共享讨论历史
        self.roles = roles
        self.router = router               # 下一发言者路由

    def run_events(self) -> Iterator[Event]:
        # phase 推进 + 对话轮
        while not self.state.finished and self.state.turn < max_turns:
            speaker = self.router.next(self.state, self.messages)
            yield from self._run_agent_turn(speaker)
            self.state.turn += 1
        yield DoneEvent(trace=...)

    def _run_agent_turn(self, role) -> Iterator[Event]:
        # 给该猫 build messages = [system(persona), ...shared discussion, state snapshot]
        # 该猫自主多轮 tool_calls 直到产出文本回复(含 send_message/broadcast/delegate/...)
        # 复用 AutonomousAgent 的内层循环逻辑
        ...
```

### 5.2 下一发言者路由(`LLMRouter` + 自主交棒)

```python
class SpeakerRouter:
    def next(self, state, messages) -> str:
        last = messages[-1] if messages else None
        # 1) 自主交棒优先:上一条 send_message(to=X) → 下一发言者=X
        if last and last.get("to"):
            return last["to"]
        # 2) Planner 兜底裁决:LLM 看 state+历史 → 输出 agent name
        return self._llm_decide(state, messages)
```

防死循环:连续 N 轮无 phase 推进 → 强制 Planner;重复发言节流;总轮次上限。

### 5.3 阶段框架(Planner 推进)

phase 流转(Planner 调 `update_state(phase=...)`):
```
analyze → execute → review → (pass?) → validate → done
                       │
                       └ no → execute(打回)
```
- `analyze`:Planner 拆 `plan_tree`,推进 `phase=execute`
- `execute`:Executor 做 step,产出 `current_artifact`,完成推进 `phase=review`
- `review`:Reviewer 审,`pass`→推进 `phase=validate`;`fail`→`send_message(executor, 打回)`+ phase 留 review(Executor 接到继续做)
- `validate`:Planner 汇总 `security_alerts`,无问题→`finish_task`;有问题→回 execute 修
- Validator 不占讨论轮,是工具执行前 hook(见 §6)

阶段内**自由讨论**:不是固定"Planner 说一句→Executor 说一句",而是路由 + 自主交棒,允许 Executor 和 Reviewer 在 review 阶段来回讨论。

### 5.4 单 agent 内层循环(复用)

每只猫的发言 = 一个 mini AutonomousAgent:build messages(system+讨论+state)→ LLM tool_calls 循环 → 直到文本回复(或 send_message)。复用 sop-agent 的 `router.chat` + `tool_executor` + 事件 yield。各猫的 tools = 对话工具 + 业务工具白名单(Executor 有 bash/read_file/write_file;Planner 无业务工具只路由;Reviewer 有 read_file/grep;Validator 是 hook 无业务工具)。

---

## 6. Validator LLM 拦截(`meowwork/validator.py`)

`tool_executor` 加 `pre_execution_hooks` 列表(不改原签名,在 `_run_one` 前调)。ValidatorHook:

```python
class ValidatorHook:
    def __init__(self, llm_router, llm_config, rules):
        ...
    def check(self, tool_name, args) -> "Verdict":
        # 仅对危险工具(bash/write_file/edit_file)触发;只读工具放行
        if tool_name not in DANGEROUS: return Verdict(allow=True)
        # 1) 规则预筛(正则黑名单:rm -rf / rm -rf / / 密钥路径 / :(){ ... })
        for rule in self.rules:
            if rule.match(tool_name, args):
                return Verdict(allow=False, reason=rule.reason, source="rule")
        # 2) LLM 判定(玄猫 persona:沉稳警觉,看命令+上下文)
        prompt = VALIDATOR_PROMPT.format(cmd=args)
        resp = llm.chat([{system}, {user: cmd + state context}])
        data = parse_json(resp)  # {dangerous: bool, reason: str}
        return Verdict(allow=not data["dangerous"], reason=data["reason"], source="llm")
```

拦截 → `SecurityAlertEvent` + 工具结果返回 `"BLOCKED by validator: <reason>"` 给 agent(让 agent 知道被拦,换方案)。放行 → 正常执行。

规则配置:`meowwork/validator_rules.yaml`(黑名单正则 + 危险路径)。

---

## 7. 逻辑 PID 子 agent

`delegate(role, task)` 复用 sop-agent TaskTool 机制:
- 分配逻辑 PID(自增计数器)
- 子 agent 用目标 role 的 persona + 全新 context(不继承讨论历史,只收 task)
- 同步驱动(在工具调用内),事件经 `on_event` 透传为 `SubAgentEvent`
- `state.sub_agents` 追加 `{pid, role, task, status: running|done|failed}`
- 深度限制(继承 TaskTool 的 max_depth,默认 2,防递归)

---

## 8. WebSocket

`/ws` 端点:客户端订阅 run_id,服务端在事件 yield 时广播(复用 `_serialize_event` + 新事件序列化)。同时每次 state 变化推 state 快照。前端 WS 客户端替代轮询。

---

## 9. Next.js 前端(Phase 4)

- App Router + Tailwind + Zustand(全局 state)+ Framer Motion(动效)
- 四工作台:
  - 左(布偶):毛玻璃 + 任务树(绿爪印完成/灰未开始/呼吸灯进行中)+ phase 指示
  - 中上(橘):实时 CoT 流 + 子 agent 折叠(逻辑 PID/任务/健康度)
  - 中下(狸):Diff 对比 + 测试通过率 + 打回计数
  - 右/底(玄):黑底矩阵绿 Shell/IO 瀑布,拦截时炸毛+Access Denied
- 动效:毛线球传送带(Executor→Reviewer)/ 炸毛(Validator 拦截)/ 猫薄荷 Global Pause(冻结 state + 人工改)
- WS 订阅 + Zustand state 渲染

---

## 10. 仓库结构

```
src/sopagent/
  meowwork/
    __init__.py
    state.py            # GroupState
    roles.py            # AgentRole + 四猫定义
    orchestrator.py     # GroupOrchestrator + SpeakerRouter
    tools.py            # send_message/broadcast/delegate/update_state/finish_task
    validator.py        # ValidatorHook
    validator_rules.yaml
    prompts/
      planner.md  executor.md  reviewer.md  validator.md
  harness/              # 复用(tool_executor 加 hooks 入口)
  ...
tests/
  test_meowwork_state.py
  test_meowwork_roles.py
  test_meowwork_orchestrator.py
  test_meowwork_validator.py
  ...
```

---

## 11. 分阶段计划

| Phase | 内容 | 工作量 |
|---|---|---|
| **0** | meowwork/ 包 + GroupState + AgentRole + 四猫 persona prompts + 测试 | 0.5-1d |
| **1** | GroupOrchestrator(对话循环+路由)+ 5 对话工具 + 事件流 + 逻辑 PID + 四猫 system prompt 细化 + 测试 | 3-4d |
| **2** | ValidatorHook(规则预筛+LLM 判定)+ security_alert 事件 + tool_executor hooks 入口 + 规则配置 + 测试 | 2d |
| **3** | WebSocket 端点 + 前端 WS 客户端 | 1d |
| **4** | Next.js 前端(四工作台 + 动效 + WS 订阅) | 4-5d |
| **5** | 猫薄荷 Pause + 子 agent 健康度 + 真实任务("分析漏洞+写修复脚本")端到端 + persona 打磨 | 1-2d |

总约 11-14 人日。Phase 0-2(后端闭环)约 6-7 天。
