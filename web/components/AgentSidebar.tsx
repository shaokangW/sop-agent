"use client";
import { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { useMeowStore } from "@/lib/store";
import type { BaseEvent, PhaseEv, SecurityAlertEv, StateUpdateEv, SubAgentEv, ToolEv } from "@/lib/types";

const CATS = [
  { role: "planner", emoji: "🐱", name: "布偶猫", color: "planner", desc: "总管 · 拆任务/路由" },
  { role: "executor", emoji: "🧡", name: "橘猫", color: "executor", desc: "执行 · 写代码/委派" },
  { role: "reviewer", emoji: "👓", name: "狸花猫", color: "reviewer", desc: "审查 · 通过/打回" },
  { role: "validator", emoji: "🐈‍⬛", name: "玄猫", color: "validator", desc: "安全 · 零信任拦截" },
];

export default function AgentSidebar() {
  const { state, events, streaming } = useMeowStore();
  const [open, setOpen] = useState<string | null>(null);

  function statusOf(role: string): { label: string; color: string; dot: string } {
    // 1) currently streaming → thinking
    if (streaming[role]) return { label: "思考中", color: "text-accent", dot: "bg-accent animate-pulse" };
    // 2) finished
    if (state?.finished) return { label: "完成", color: "text-validator", dot: "bg-validator" };
    // 3) infer from recent events for this role
    const recent = [...events].reverse();
    const lastMsg = recent.find((e) => e.type === "message" && (e as { from: string }).from === role);
    const lastTool = recent.find((e) => e.type === "tool" && (e as { step_id: string }).step_id === role);
    const lastTurn = recent.find((e) => e.type === "turn" && (e as { step_id: string }).step_id === role);
    switch (role) {
      case "planner": {
        const ph = recent.find((e) => e.type === "phase");
        if (ph) return { label: `推进→${(ph as { to: string }).to}`, color: "text-accent", dot: "bg-accent" };
        if (lastMsg) return { label: "已发言", color: "text-planner", dot: "bg-planner" };
        return { label: state?.phase ? `阶段:${state.phase}` : "待命", color: "text-muted", dot: "bg-muted" };
      }
      case "executor": {
        const subRunning = state?.sub_agents?.some((s) => s.status === "running");
        if (subRunning) return { label: "委派中", color: "text-executor", dot: "bg-executor animate-pulse" };
        if (lastTool) return { label: `工具:${(lastTool as { name: string }).name}`, color: "text-executor", dot: "bg-executor animate-pulse" };
        if (state?.current_artifact) return { label: "已产出", color: "text-executor", dot: "bg-executor" };
        if (lastTurn) return { label: "待命", color: "text-muted", dot: "bg-muted" };
        return { label: "待命", color: "text-muted", dot: "bg-muted" };
      }
      case "reviewer": {
        const ru = recent.find((e) => e.type === "state_update" && (e as { key: string }).key === "review_pass");
        if (ru && (ru as { new: unknown }).new === true) return { label: "通过", color: "text-validator", dot: "bg-validator" };
        if (ru && (ru as { new: unknown }).new === false) return { label: "打回", color: "text-danger", dot: "bg-danger" };
        if (lastMsg) return { label: "审查中", color: "text-reviewer", dot: "bg-reviewer animate-pulse" };
        return { label: "待审", color: "text-muted", dot: "bg-muted" };
      }
      case "validator": {
        const n = state?.security_alerts?.length ?? 0;
        const lastAlert = recent.find((e) => e.type === "security_alert");
        if (lastAlert) return { label: `拦截(${n})`, color: "text-danger", dot: "bg-danger animate-pulse" };
        return { label: "监控中", color: "text-validator", dot: "bg-validator" };
      }
    }
    return { label: "—", color: "text-muted", dot: "bg-muted" };
  }

  return (
    <aside className="w-72 border-r border-border bg-panel flex flex-col overflow-hidden">
      <div className="px-4 py-3 border-b border-border">
        <h2 className="text-sm font-serif text-text">猫咪 Agent</h2>
        <p className="text-[10px] text-muted">点击查看详细状态</p>
      </div>
      <div className="flex-1 overflow-y-auto cat-scroll">
        {CATS.map((cat) => {
          const st = statusOf(cat.role);
          const isOpen = open === cat.role;
          return (
            <div key={cat.role} className="border-b border-border">
              <button onClick={() => setOpen(isOpen ? null : cat.role)}
                className={`w-full flex items-center gap-3 px-4 py-3 hover:bg-panel2 text-left border-l-2 ${streaming[cat.role] ? "border-accent bg-accent/5" : "border-transparent"}`}>
                <span className={`text-xl ${streaming[cat.role] ? "animate-pulse-slow" : ""}`}>{cat.emoji}</span>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span className={`text-sm font-medium text-${cat.color}`}>{cat.name}</span>
                    <span className={`w-1.5 h-1.5 rounded-full ${st.dot}`} />
                    <span className={`text-[10px] ${st.color}`}>{st.label}</span>
                  </div>
                  <div className="text-[10px] text-muted truncate">{cat.desc}</div>
                </div>
                <span className={`text-muted text-xs transition-transform ${isOpen ? "rotate-90" : ""}`}>›</span>
              </button>
              <AnimatePresence>
                {isOpen && (
                  <motion.div initial={{ height: 0, opacity: 0 }} animate={{ height: "auto", opacity: 1 }} exit={{ height: 0, opacity: 0 }}
                    className="overflow-hidden bg-bg">
                    <div className="px-4 py-2 text-xs"><CatDetail role={cat.role} /></div>
                  </motion.div>
                )}
              </AnimatePresence>
            </div>
          );
        })}
      </div>
    </aside>
  );
}

function CatDetail({ role }: { role: string }) {
  const { state, events } = useMeowStore();
  if (role === "planner") {
    const plan = state?.plan_tree ?? {};
    return (
      <div className="space-y-1">
        <Row k="阶段" v={state?.phase} />
        <div className="text-muted mt-1">任务树:</div>
        {Object.keys(plan).length === 0 ? <div className="text-muted">（待拆解）</div> :
          Object.entries(plan).map(([id, s]) => (
            <div key={id} className="flex gap-2">
              <span className={s.status === "done" ? "text-validator" : "text-muted"}>{s.status === "done" ? "🐾" : "○"}</span>
              <span className="text-text">{id}</span><span className="text-muted">→ {s.assignee}</span>
            </div>
          ))}
        {state?.summary && <Row k="汇总" v={state.summary} />}
      </div>
    );
  }
  if (role === "executor") {
    const tools = events.filter((e): e is ToolEv => e.type === "tool");
    const subs = state?.sub_agents ?? [];
    return (
      <div className="space-y-1">
        {state?.current_artifact && (
          <>
            <div className="text-muted">当前产出:</div>
            <pre className="text-[10px] text-executor bg-panel2 p-1.5 rounded font-mono whitespace-pre-wrap max-h-32 overflow-y-auto cat-scroll">{state.current_artifact.slice(0, 500)}</pre>
          </>
        )}
        <div className="text-muted mt-1">工具调用({tools.length}):</div>
        {tools.slice(-5).map((t, i) => (
          <div key={i} className="flex gap-1">
            <span className={t.ok ? "text-validator" : "text-danger"}>{t.ok ? "✓" : "✗"}</span>
            <span className="text-executor font-mono">{t.name}</span>
          </div>
        ))}
        {subs.length > 0 && <div className="text-muted mt-1">子 agent({subs.length}):</div>}
        {subs.map((s, i) => (
          <div key={i} className="flex gap-1 text-[10px]">
            <span className="text-muted">#{s.pid}</span><span className="text-executor">{s.role}</span>
            <span className="text-muted truncate flex-1">{s.task}</span>
            <span className={s.status === "done" ? "text-validator" : "text-planner"}>{s.status}</span>
          </div>
        ))}
      </div>
    );
  }
  if (role === "reviewer") {
    const retries = events.filter((e): e is StateUpdateEv => e.type === "state_update" && e.key === "review_pass" && e.new === false).length;
    return (
      <div className="space-y-1">
        <Row k="结论" v={state?.review_pass === true ? "通过" : state?.review_pass === false ? "打回" : "待审"} />
        <Row k="打回次数" v={String(retries)} />
        {state?.review_feedback && (
          <>
            <div className="text-muted mt-1">反馈:</div>
            <pre className="text-[10px] text-reviewer bg-panel2 p-1.5 rounded font-mono whitespace-pre-wrap">{state.review_feedback}</pre>
          </>
        )}
      </div>
    );
  }
  // validator
  const alerts = events.filter((e): e is SecurityAlertEv => e.type === "security_alert");
  return (
    <div className="space-y-1">
      <Row k="拦截次数" v={String(alerts.length)} />
      {alerts.length === 0 ? <div className="text-muted text-[10px]">无危险操作,监控中</div> :
        alerts.map((a, i) => (
          <div key={i} className="border border-danger/30 rounded p-1.5 bg-danger/5 text-[10px]">
            <div className="text-danger font-medium">⛔ {a.tool}</div>
            <div className="text-muted break-all">{JSON.stringify(a.args).slice(0, 120)}</div>
            <div className="text-warn">{a.reason}</div>
          </div>
        ))}
    </div>
  );
}

function Row({ k, v }: { k: string; v?: string | null }) {
  return <div className="flex justify-between"><span className="text-muted">{k}</span><span className="text-text">{v ?? "—"}</span></div>;
}
