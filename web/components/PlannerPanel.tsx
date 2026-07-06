"use client";
import { motion } from "framer-motion";
import { useMeowStore } from "@/lib/store";
import type { MessageEv, PhaseEv, StateUpdateEv } from "@/lib/types";

const PHASES = ["analyze", "execute", "review", "validate", "done"];

export default function PlannerPanel() {
  const { events, state } = useMeowStore();
  const planTree = state?.plan_tree ?? {};
  const phase = state?.phase ?? "analyze";
  const phaseEv = events.filter((e): e is PhaseEv => e.type === "phase");
  const messages = events.filter((e): e is MessageEv => e.type === "message");
  const planUpdates = events.filter((e): e is StateUpdateEv => e.type === "state_update" && e.key === "plan_tree");

  return (
    <div className="flex flex-col h-full bg-panel/60 backdrop-blur border-r border-border">
      <div className="px-3 py-2 border-b border-border bg-planner/10">
        <div className="text-planner font-bold text-sm">🐱 布偶猫 · 总管</div>
        <div className="text-[10px] text-muted">任务树 + 讨论</div>
      </div>
      <div className="p-3 border-b border-border">
        <div className="text-[10px] text-muted uppercase mb-1">阶段推进</div>
        <div className="flex items-center gap-1">
          {PHASES.map((p) => {
            const active = phase === p;
            const passed = PHASES.indexOf(phase) > PHASES.indexOf(p);
            return (
              <div key={p} className={`flex-1 text-center text-[10px] py-1 rounded ${active ? "bg-planner text-bg animate-pulse-slow" : passed ? "text-executor" : "text-muted"}`}>
                {passed ? "🐾" : active ? "●" : "○"} {p}
              </div>
            );
          })}
        </div>
      </div>
      <div className="p-3 border-b border-border">
        <div className="text-[10px] text-muted uppercase mb-1">任务树</div>
        {Object.keys(planTree).length === 0 ? (
          <div className="text-xs text-muted">（待 Planner 拆解）</div>
        ) : (
          <div className="space-y-1">
            {Object.entries(planTree).map(([id, step]) => (
              <div key={id} className="text-xs flex items-center gap-2">
                <span className={step.status === "done" ? "text-executor" : step.status === "running" ? "text-planner animate-pulse-slow" : "text-muted"}>
                  {step.status === "done" ? "🐾" : step.status === "running" ? "●" : "○"}
                </span>
                <span className="text-text">{id}</span>
                <span className="text-muted">→ {step.assignee || "?"}</span>
              </div>
            ))}
          </div>
        )}
      </div>
      <div className="flex-1 overflow-y-auto cat-scroll p-3">
        <div className="text-[10px] text-muted uppercase mb-1">讨论日志</div>
        {messages.map((m, i) => (
          <motion.div key={i} initial={{ opacity: 0, x: -10 }} animate={{ opacity: 1, x: 0 }}
            className="text-xs mb-1.5">
            <span className="text-planner font-bold">[{m.from}]</span>
            <span className="text-muted">→{m.to || "all"}: </span>
            <span className="text-text">{m.content}</span>
          </motion.div>
        ))}
        {phaseEv.length > 0 && (
          <div className="text-[10px] text-warn mt-2">↻ phase: {phaseEv.at(-1)?.from} → {phaseEv.at(-1)?.to}</div>
        )}
      </div>
    </div>
  );
}
