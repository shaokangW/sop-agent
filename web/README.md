# MeowWork Web (赛博喵工坊)

Next.js 前端:四工作台多智能体协作监控看板。

## 启动

```bash
cd web
npm install
npm run dev
# 打开 http://localhost:3000(后端需先跑在 8000:python -m uvicorn sopagent.server:app --port 8000)
```

## 布局

- **左 · 布偶猫(总管)**:阶段推进 + 任务树(🐾完成/●进行/○未开始)+ 讨论日志
- **中上 · 橘猫(执行者)**:CoT 思考流 + 工具调用 + 子 agent(逻辑 PID)
- **中下 · 狸花猫(审查)**:审查结论(通过/打回)+ 反馈 + 打回计数
- **右 · 玄猫(安全网关)**:零信任拦截瀑布(黑底矩阵绿,拦截时炸毛 + ACCESS DENIED)

顶部任务输入启动 `POST /meowwork/run`,WebSocket 订阅 `/ws/meowwork/{id}` 实时推送事件。

## 配置

- 后端代理:`next.config.mjs` 的 `rewrites` 把 `/api/*` 转发到 FastAPI(默认 `http://127.0.0.1:8000`,用 `BACKEND_URL` 覆盖)
- WS 直连后端(Next 不代理 WS):默认 `ws://127.0.0.1:8000`,用 `NEXT_PUBLIC_WS_BASE` 覆盖
