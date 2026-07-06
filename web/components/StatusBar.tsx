"use client";
import { useMeowStore } from "@/lib/store";

export default function StatusBar() {
  const { runId, connected, state, paused, togglePause } = useMeowStore();
  const phase = state?.phase ?? "—";
  const turn = state?.turn ?? 0;
  const finished = state?.finished;

  return (
    <div className="flex items-center gap-4 px-4 py-1.5 bg-panel border-b border-border text-xs">
      <span className={connected ? "text-executor" : "text-muted"}>
        {connected ? "● 已连接" : runId ? "○ 连接中" : "○ 空闲"}
      </span>
      <span className="text-muted">run: <span className="text-text font-mono">{runId ? runId.slice(0, 8) : "—"}</span></span>
      <span className="text-muted">阶段: <span className="text-planner">{phase}</span></span>
      <span className="text-muted">轮次: <span className="text-text">{turn}</span></span>
      <span className={finished ? "text-executor" : "text-muted"}>{finished ? "✓ 完成" : ""}</span>
      <div className="flex-1" />
      <button onClick={togglePause}
        className={`px-3 py-0.5 rounded border ${paused ? "bg-warn text-bg border-warn" : "border-border text-muted"}`}>
        🌿 猫薄荷 {paused ? "已冻结" : "Pause"}
      </button>
    </div>
  );
}
