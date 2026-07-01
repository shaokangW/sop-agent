# sop-agent

一只**工作严谨的三花猫**（也是资深工程师）驱动的 agent 框架：**SOP（声明式流程）+ harness（运行时引擎）**，把"做什么"（流程）和"怎么执行"（agent 自主）解耦。支持 SOP 编排、自主 agent、多轮对话三种模式，带工具调用、MCP 协议、人在回路审批、流式输出（含思考过程）、可配置 system prompt 和 Web/TUI 双前端。

默认接入**百炼 GLM-5.2**（OpenAI 兼容），凭证自动从本地 opencode 配置读取，开箱即用。

## 架构

### 两层嵌套循环（核心）

```
外层（编排）  按 SOP 顺序/transition 推进，或 agent 自决 finish，或用户多轮驱动
内层（agent） 单步内 LLM 用原生 tool_calls 自主多轮，直到产出最终答案
```

- **SOP 模式**：人写 YAML 流程，engine 按阶段/步骤推进（确定性骨架 + 条件 transition）
- **自主模式**：给任务，agent 自选工具、自判复杂度（复杂调 `plan` 分解子目标）、`finish` 完成
- **对话模式**：多轮 chat，agent 每轮用工具到给出文本回复即交还用户

### 分层

```
运行层      cli.py (chat/task/run)  |  server.py (FastAPI + Web UI)
harness     engine / autonomous / interactive / approval / events / transitions / tui / markdown_render
LLM 抽象    base(Protocol) / openai_provider / registry / router  (多 provider + 流式 + reasoning)
工具层      base / registry / executor / builtin(9 工具) / mcp_client
SOP 模型    schema(Pydantic) / loader(YAML 解析 + 变量插值)
配置        config.py (env + opencode.json 读取百炼凭证 + 全局 MCP 配置)
Prompt      prompt_builder.py (openclaw 风格: 分层文档 + mode 门控 + cache boundary)
自研 TUI    tui/ (OpenTUI 移植: buffer/cell-grid diff / renderable+flexbox / widgets+stickyScroll)
```

### 事件流执行器

执行器是 generator，`yield` 事件：`TokenEvent` / `ReasoningEvent` / `TurnEvent` / `ToolExecutedEvent` / `ApprovalRequest`（暂停，`.send(decision)` 恢复）/ `DoneEvent`。统一流式 + 审批 + 完成判定。CLI 同步消费，Web 后台线程 + 轮询。

### System Prompt 架构（参照 openclaw）

```
stable prefix（三模式共享）    base.md(身份+安全) agents.md(规则) soul.md(三花猫人格) tools.md(工具笔记)
mode 门控                      chat.md / autonomous.md / sop.md
<!-- SOP_AGENT_CACHE_BOUNDARY -->
dynamic suffix（每轮变化）     autonomous: Plan+子目标 / sop: step goal+JSON提示 / runtime 元信息
```

- **分层加载**（高覆盖低）：`~/.sop-agent/prompts/` > 项目 `.sop-agent/prompts/` > `<cwd>/prompts/` > 内置默认
- **命令式拼接**（无模板变量）+ **mode 门控**每 section + **cache boundary** 切稳定/易变
- **截断保护**：per-doc 12000 字符 / total 60000 字符
- 用户在 `~/.sop-agent/prompts/` 放同名 `.md` 即可覆盖

## 特性

- **三种模式**：SOP（预编排）/ 自主（agent 自决 + plan + finish）/ 对话（多轮）
- **工具集**（参照 opencode/claude-code）：`read_file` `write_file` `edit_file` `list_dir` `grep` `bash` `web_fetch` `todo_write` `echo`；危险工具（write/edit/bash）自动需审批
- **MCP 协议**：支持自写 / 社区现成 / 复用 opencode 配置的 MCP server（stdio + SSE），三模式全局加载
- **人在回路审批**：动作级（tool call）+ 阶段级（step/subgoal）；三选项「本次允许 / 对话允许 / 拒绝」
- **流式 + 思考过程**：原生 tool_calls 循环 + `reasoning_content` 流式（GLM-5.2 思考链，Web 灰色 `think` 块显示）
- **多 provider**：OpenAI 兼容（百炼/DeepSeek/Qwen...），按 step 配置路由；默认百炼 GLM-5.2
- **条件流转**：SOP `transitions` + `when` 表达式（显式图，无匹配则结束）
- **变量插值**：`${env.X}` / `${var}` / 跨步 `${stages.s.step.output.field}`
- **输出校验**：JSON schema 校验 + 代码块提取（模型把 JSON 包 ```json 也能解析）
- **可配置人格**：三花猫工程师（严谨 + 傲娇 + 漫画化），prompt 文档可编辑覆盖
- **Web UI**：消息分块（user/assistant 配色）+ markdown 渲染 + 思考块 + 工具调用两级折叠 + 侧边栏（模型/使用情况/工具汇总/已加载工具/MCP 服务）+ session 管理（新建/历史/继续）+ 三模式切换 + 审批三选项
- **TUI**：prompt_toolkit + 自研 ScrollBox（stickyScroll 1:1 移植自 OpenTUI：自动跟随/上翻脱粘/回底重粘）
- **自研 TUI 框架**：`tui/`（OpenTUI Python 移植：CellGrid 行 diff / Renderable+flexbox / ScrollBox stickyScroll 状态机）

## 安装

```bash
cd sop-agent
pip install -e .
# 或手动装核心依赖
pip install pydantic pyyaml openai jsonschema typer rich fastapi uvicorn prompt_toolkit
# MCP 支持（可选）
pip install mcp
```

### 百炼 GLM-5.2 凭证

若本地装了 opencode 并 `/connect` 过百炼，sop-agent 自动从 `~/.config/opencode/opencode.json` 读取 `bailian` provider 的 apiKey + baseURL。也可用环境变量覆盖：

```powershell
$env:BAILIAN_API_KEY="sk-..."
$env:BAILIAN_BASE_URL="https://dashscope.aliyuncs.com/compatible-mode/v1"
```

### MCP 配置（可选）

在 `~/.sop-agent/mcp.json` 配置 MCP server（三模式自动加载）：

```json
{
  "mcp_servers": {
    "fs":     {"command": "npx", "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"]},
    "memory": {"command": "npx", "args": ["-y", "@modelcontextprotocol/server-memory"]},
    "custom": {"command": "python", "args": ["my_mcp_server.py"]}
  }
}
```

也自动复用 opencode 的 mcp 配置。SOP 模式还可在 YAML 里额外配 `mcp_servers`。

## 使用

### Web UI（推荐体验）

```powershell
cd sop-agent
$env:PYTHONPATH="src"
python -m uvicorn sopagent.server:app --port 8000
# 浏览器打开 http://127.0.0.1:8000
```

顶部切模式：💬 对话（多轮）/ 🎯 任务（自主）/ 📋 SOP（粘 YAML 运行）。侧边栏显示模型、使用情况、已加载工具、MCP 服务。

### CLI

```powershell
$env:PYTHONPATH="src"

# 对话模式（多轮 chat，TUI）
python -m sopagent.cli chat

# 自主模式（单任务，agent 自决工具 + plan + finish）
python -m sopagent.cli task "读取 src/sopagent/cli.py 并总结"

# SOP 模式（跑预编排 YAML）
python -m sopagent.cli run sops\research.yaml
```

### 写自己的 SOP

```yaml
metadata: {name: my-flow}
llm_defaults: {provider: bailian, model: glm-5.2, temperature: 0.2}
variables: {topic: "${env.TOPIC}"}
stages:
  - id: gather
    steps:
      - id: read
        goal: "读取目标文件"
        prompt: "用 read_file 读取 ${topic} 并总结"
        tools: [read_file]
  - id: write
    steps:
      - id: draft
        goal: "写总结到 out.md"
        prompt: "把 ${stages.gather.read.output} 用 write_file 写到 out.md"
        require_approval: true
```

## 目录结构

```
src/sopagent/
├── cli.py                  CLI: chat / task / run
├── server.py               FastAPI + Web UI (/chat /task /run /approve /config)
├── config.py               Settings（百炼凭证从 opencode 读 + 全局 MCP 配置）
├── prompt_builder.py       System prompt 拼接（分层文档 + mode 门控 + cache boundary）
├── prompts/                内置 prompt 文档（base/agents/soul/tools/chat/autonomous/sop .md）
├── sop/                    SOP 模型 + loader
├── llm/                    LLM 抽象（provider/router/stream/reasoning）
├── tools/                  工具层（builtin 9 工具 + MCP + executor）
├── harness/                引擎（engine/autonomous/interactive/approval/events/transitions/tui/markdown_render）
└── tui/                    自研 TUI 框架（OpenTUI 移植：buffer/renderable/widgets）
sops/                       SOP 示例（research.yaml + mcp_test.yaml）
tests/                      测试（62，覆盖 loader/engine/transitions/approval/autonomous/tools/server/tui/config/stream）
```

## 测试

```bash
python -m pytest -q
```

## 致谢

- TUI 滚动的 stickyScroll 状态机移植自 [opencode/OpenTUI](https://github.com/anomalyco/opentui)
- System prompt 架构（分层文档 + mode 门控 + cache boundary）参照 [openclaw](https://github.com/openclaw/openclaw)
- 工具集设计参照 opencode / claude-code
