# sop-agent 建设路线图

基线:62 测试。三模式(SOP/自主/对话)+ 9 内置工具 + MCP + 审批 + 流式 + Web UI + 自研 TUI 均已就绪。以下 6 项已**全部完成**(117 测试),并补齐「交互层」让每项能力用户可感知可操作、经真实 LLM e2e 验证。

---

## #1 子 agent / 委派机制 [high] ✅ 已完成

主 agent 通过 `task` 工具派生子 agent 处理独立子任务,子 agent 拥有**全新上下文**(不继承父对话历史,省 token),完成后向父返回摘要。参照 opencode/claude-code 的 subagent 模式。

- ✅ 新增 `tools/builtin/task.py`:`TaskTool` + `SubAgentContext`(dataclass 持有 router/registry/llm_config/artifacts/policy/depth)
- ✅ 子 agent 复用 `AutonomousAgent`,传入独立 sub-registry(父工具集 minus `task`)+ 全新 messages
- ✅ 子 agent 的 `finish` summary 作为工具结果回传父 agent(含 tool 调用日志)
- ✅ 递归保护:`max_depth`(默认 2),边界子 agent 不注册 `task` 工具 + depth 守卫双重保险
- ✅ `on_event` 钩子:子 agent 事件可转发给父(供 #4 可观测性 / Web UI 接)
- ✅ 三模式接入:`cli.py` 的 `build_agent` / `build_engine_from_sop` / `_build_session`
- ✅ `prompts/tools.md` 加委派笔记;`README` 更新
- ✅ 测试 7 个:委派返回摘要 / 子 agent 工具执行 / 缺 description / 递归守卫 / 边界无 task 工具 / 事件转发 / 失败上报

**v1 已知限制**:子 agent 内部危险工具自动审批(委派本身即闸门);真正的审批再上抛(暂停父 agent 重新询问用户)留待 #4/#6。

## #2 上下文压缩 / 窗口管理 [medium] ✅ 已完成

长对话自动摘要 + 截断,避免 token 爆掉。

- ✅ `harness/context_window.py`:`ContextWindowManager`(router + llm_config + max_tokens + keep_recent + on_compress)
- ✅ token 估算:chars/4 启发式(content + tool_calls.arguments)
- ✅ 压缩策略:保留 system[0] + 最近 N 条,中间用 LLM 摘成一条 `system` 消息(避免与 user/assistant 角色冲撞)
- ✅ 安全切点:cut 不落在 `tool` 消息上(回退包含其父 assistant),杜绝 orphan tool_call_id
- ✅ 失败回退:摘要 LLM 异常时硬截断中间 + `[earlier context truncated]` 标记,保证对话继续
- ✅ `InteractiveSession` 接入(ask 开头压缩),CLI `_build_session` 默认启用,server 经 `_build_session` 自动获得
- ✅ `on_compress` 回调:回传 before/after tokens、middle/kept 计数(供 #4 观测)
- ✅ 测试 8 个:预算内不压缩 / 禁用 noop / 摘要+保留最近 / 无 orphan tool / LLM 失败回退 / 回调 / 消息过少 / session 跨轮集成

**后续**:`AutonomousAgent` 长任务内的压缩(每 turn 前调用)留待后续;engine 每步 messages 重建,无需压缩。

## #3 记忆与 session 持久化 [medium] ✅ 已完成

`.chat_history` 原为 TUI 输入日志(简单 `+text` 追加);server 的 session 全在内存 `_chat_sessions`,重启即丢。现已补齐真正的持久化与跨重启恢复。

- ✅ `harness/session_store.py`:`SessionStore`(create/save/load/list_sessions/delete),每会话一个 JSON(`.sop-agent/sessions/<id>.json`)
- ✅ 格式:`{id,title,created_at,updated_at,messages}`,list 按 updated_at 倒序、带 message_count、跳过损坏文件
- ✅ `Settings.sessions_dir` 配置项 + `.gitignore` 加 `.sop-agent/`
- ✅ server 接入:`chat_start` 创建落盘;`_run_chat` 每轮结束 persist(在发出 done 事件前 save,杜绝 resume 竞态);`chat_sessions` 从磁盘列并合并运行态;`chat_history` 内存缺失则从磁盘读;`chat_send` 经 `_ensure_session` 跨重启重建 session(重灌 messages)
- ✅ 新增 `DELETE /chat/{id}` 删除端点
- ✅ 测试 11 个:store 7 个(create/load/list 排序/missing/delete/title 更新/损坏跳过/save 无 create) + server 4 个(start/send/persist/list/history、模拟重启 resume、delete、unknown 404)

**后续**:长期「事实/偏好」记忆库(memory.json,可萃取关键信息)留待后续;TUI chat 的跨进程 resume 未做(目前仅 Web)。

## #4 可观测性 / trace 导出 [medium] ✅ 已完成

trace 落盘 + token 统计 + 回放。

- ✅ `LLMResponse` 加 `usage` 字段;`OpenAIProvider` 非流式从 `resp.usage` 提取,流式开 `stream_options={"include_usage": True}` 从末尾 usage-only chunk 提取
- ✅ `Tracer`:per-turn `usage` 入 `TurnRecord`;`turn(usage=...)` 累加到 `Tracer.usage`;`Trace.usage` 汇总(finalize 透传)
- ✅ `Tracer.dump_jsonl(path)`:每轮一行(`kind=turn`,含 role/content_preview/tool_calls/usage)+ 汇总行(`kind=summary`,含 sop_name/时间/usage/计数);自动建父目录
- ✅ `replay_jsonl(path)`:回放成 record 列表(供 #6 Web 时间线)
- ✅ engine / autonomous 把 `resp.usage` 传入 assistant turn 的 tracer 调用
- ✅ CLI `run` / `task` 加 `--trace` 选项,导出到 `Settings.traces_dir`(默认 `.traces/`)
- ✅ server `trace_to_dict` 经 `asdict` 自动透传 usage(侧栏「使用情况」现已有真实数据)
- ✅ `.gitignore` 加 `.traces/`
- ✅ 测试 6 个:usage 累加 / 无 usage 为 None / dump+replay 往返 / 自动建目录 / engine 记录 usage / autonomous 记录 usage

**后续**:Web UI 时间线视图(消费 replay_jsonl)并入 #6;子 agent trace 接入父 `on_event`(#1 已留钩子)。

## #5 更多 provider [low] ✅ 已完成

接 Ollama(本地)/ Anthropic 原生(非 OpenAI 兼容)+ 路由测试。

- ✅ `llm/anthropic_provider.py`:`AnthropicProvider` 原生 Messages API,惰性导入 `anthropic` SDK(可选依赖,`pyproject` 加 `anthropic` extra),`client` 可注入便测
- ✅ 翻译层:`_translate_request`(system 提取为顶层参数;assistant `tool_calls`→`tool_use` 块;`tool` role→user 消息里的 `tool_result` 块,JSON 字符串参数自动解析);`_translate_response`(text 块→content,thinking 块→reasoning,tool_use 块→ToolCall,usage input/output→prompt/completion/total)
- ✅ `_to_anthropic_tool`(OpenAI function schema → name/description/input_schema)
- ✅ `chat()` 调 `messages.create`;`chat_stream()` v1 经非流式解析后一次性 emit delta(正确但非增量,原生 SSE 流式留后续)
- ✅ `config.py` 加 `anthropic`(ANTHROPIC_API_KEY/BASE_URL)+ `ollama`(OLLAMA_BASE_URL,默认 localhost:11434/v1,dummy key)
- ✅ `ProviderRegistry.from_settings`:`anthropic` 注册 `AnthropicProvider`,`_OPENAI_COMPATIBLE`(openai/bailian/deepseek/qwen/ollama)注册 `OpenAIProvider`,无 key 跳过
- ✅ 测试 9 个:request 翻译(system 提取+tool_result 折叠+tool_use 参数解析)/ tool schema 翻译 / response 翻译(text+tool_use) / thinking→reasoning / chat 调 SDK / tools 透传 / stream emit delta / router 路由 / from_settings 注册+跳过

**后续**:Anthropic 原生 SSE 增量流式(thinking/text/tool_use delta 事件解析);reasoning 字段在 OpenAI 兼容 provider 间统一(Anthropic thinking vs GLM reasoning_content)。

## #6 Web UI / TUI 打磨 [low] ✅ 已完成

- ✅ 后端:产物浏览器 `GET /artifacts`(rglob 列表+大小)、`GET /artifacts/{path:path}`(内容预览,`_safe_child` 防 traversal,越界 403)
- ✅ 后端:trace 时间线 `GET /traces`(列 `.traces/*.jsonl`)、`GET /traces/{name}`(调 `replay_jsonl` 回放记录,名称校验防 traversal)
- ✅ 后端:`POST /sop/validate`(只解析不执行,返回 ok/metadata/stages/steps 或 error;pydantic ValidationError 是 ValueError 子类,已被 `(ValueError, yaml.YAMLError)` 捕获)
- ✅ 前端:`📦 产物` tab(fetch + 列表 + 点击预览);侧栏 `Tokens` 行(消费 #4 trace.usage);`校验` 按钮 + 内联消息;会话 `×` 删除按钮(消费 #3 `DELETE /chat/{id}`);SOP 完成/任务 done 显示 token 用量
- ✅ TUI:`ChatTUI._run_turn` 接入 `session.on_reasoning`,缓冲思考链 delta,在 `_flush_markdown` 时以 `class:dim` `💭 ` 块输出(此前思考链完全不显示)
- ✅ 测试 7 个:artifacts list+get / 404 / traversal 403 / traces list+get / trace 404+bad-name / sop validate ok / sop validate bad

**后续**:SOP 编辑器上 monaco-lite;审批队列侧栏面板(目前内联);TUI 工具调用展开/收起键绑定;Web trace 时间线可视化消费 `/traces/{name}`。

---

## 交互层:用户可感知可操作 [完成]

6 项能力建成后,补齐各能力的用户交互入口。**117 测试 + 真实 LLM(百炼 GLM-5.2)e2e 验证通过**。

- ✅ A provider/model 可选:CLI `task`/`chat` 加 `--provider`/`--model`;Web 侧栏 provider 下拉 + 模型输入;`/config` 列出 providers(bailian/openai/anthropic/ollama + configured 标记);`ChatStartRequest`/`TaskRequest` 接受 provider/model 透传到 `build_agent`/`_build_session`
- ✅ B trace 可查看:CLI `traces list` / `traces show <name>`(回放每轮 + tool_calls + usage + summary 面板);Web 📊 Trace tab(列 trace + 点击看时间线);`_render_trace` 末尾显示 token 用量
- ✅ C CLI 实时事件:`_drive` 经 `_print_event` 默认打印工具调用(`▸ tool ok: 预览`),`task` 工具结果(子 agent 摘要 + 工具日志)逐行展开输出
- ✅ D 压缩可见性:server `_run_chat` 接 `on_compress` → 事件流 `compress` 事件;Web 渲染消息提示 + 侧栏 `压缩 N 次` 计数;TUI / CLI 回退模式打印 `✦ 上下文已压缩(省 N tokens)`
- ✅ E 子 agent 事件透传:`_wire_subagent_events` 把 TaskTool 的 `on_event` 接到 server 事件流,子 agent turn/tool 实时上抛为 `subagent_turn`/`subagent_tool`,Web 渲染为 `🐾` 嵌套项(点击展开结果)
- ✅ 真实 e2e 验证:chat 真实回复 + 跨重启磁盘恢复;`task --trace` 导出 + usage(7246 tokens);`task` 委派(GLM 调 task → 子 agent echo → 回传摘要 → 父 finish,14706 tokens);uvicorn 8000 服务 /health + /
- ✅ 修复 bug:`traces show` 对扁平 `asdict(ToolCall)` 格式 tool_calls 显示 `None(None)`(原假设 OpenAI 嵌套 `function.name`),改为兼容两种格式 + 回归断言

测试:+7(provider 透传 / config providers / wire_subagent 透传+容错 / CLI traces list+show+missing),共 117。
