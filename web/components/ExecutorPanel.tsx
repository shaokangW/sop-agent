"use client";
import { motion } from "framer-motion";
import { useEffect, useState } from "react";
import { useMeowStore } from "@/lib/store";
import type { SubAgentEv, ToolEv, TurnEv } from "@/lib/types";

export default function ExecutorPanel() {
  const events = useMeowStore((s) => s.events);
  const state = useMeowStore((s) => s.state);
  const [now, setNow] = useState(Date.now() / 1000);
  useEffect(() => { const t = setInterval(() => setNow(Date.now() / 1000), 1000); return () => clearInterval(t); }, []);
  // CoT: turn events where the speaker is executor + tool calls
  const cot = events.filter((e) => e.type === "turn" && (e as TurnEv).step_id === "executor") as TurnEv[];
  const tools = events.filter((e): e is ToolEv => e.type === "tool");
  const subs = state?.sub_agents ?? [];

  return (
    <div className="flex flex-col h-full bg-panel border-b border-border">
      <div className="px-3 py-2 border-b border-border bg-executor/10">
        <div className="text-executor font-bold text-sm">🧡 橘猫 · 执行者</div>
        <div className="text-[10px] text-muted">CoT 思考流 + 子 agent</div>
      </div>
      <div className="flex-1 overflow-y-auto cat-scroll p-3">
        <div className="text-[10px] text-muted uppercase mb-1">思考流</div>
        {cot.length === 0 && <div className="text-xs text-muted">（待 Executor 接活）</div>}
        {cot.map((t, i) => (
          <motion.div key={i} initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="text-xs mb-1 text-text">
            <span className="text-executor/70">▸ </span>{t.content}
          </motion.div>
        ))}
        {tools.length > 0 && (
          <>
            <div className="text-[10px] text-muted uppercase mt-3 mb-1">工具调用</div>
            {tools.map((t, i) => (
              <div key={i} className="text-xs mb-0.5">
                <span className={t.ok ? "text-executor" : "text-danger"}>{t.ok ? "✓" : "✗"}</span>
                <span className="text-executor font-mono ml-1">{t.name}</span>
                <span className="text-muted ml-1">{(t.result || "").slice(0, 80)}</span>
              </div>
            ))}
          </>
        )}
      </div>
      {subs.length > 0 && (
        <div className="p-3 border-t border-border">
          <div className="text-[10px] text-muted uppercase mb-1">子 agent (逻辑 PID · 健康度)</div>
          {subs.map((s, i) => {
            const elapsed = s.status === "running" && s.started_at ? now - s.started_at : s.duration;
            return (
              <div key={i} className="text-xs flex items-center gap-2">
                <span className="text-muted">#{s.pid}</span>
                <span className="text-executor">{s.role}</span>
                <span className="text-text flex-1 truncate">{s.task}</span>
                <span className="text-muted">{elapsed != null ? `${elapsed.toFixed(1)}s` : ""}</span>
                <span className={s.status === "done" ? "text-executor" : s.status === "running" ? "text-planner animate-pulse-slow" : "text-danger"}>
                  {s.status}
                </span>
              </div>
            );
          })}
        </div>
      )}
      {state?.current_artifact && (
        <div className="p-3 border-t border-border bg-bg">
          <div className="text-[10px] text-muted uppercase mb-1">当前产出</div>
          <pre className="text-xs text-executor/80 font-mono whitespace-pre-wrap max-h-32 overflow-y-auto cat-scroll">
            {state.current_artifact.slice(0, 800)}
          </pre>
        </div>
      )}
    </div>
  );
}
