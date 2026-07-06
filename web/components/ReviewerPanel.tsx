"use client";
import { useMeowStore } from "@/lib/store";
import type { StateUpdateEv } from "@/lib/types";

export default function ReviewerPanel() {
  const { events, state } = useMeowStore();
  const reviewUpdates = events.filter((e): e is StateUpdateEv => e.type === "state_update" && (e.key === "review_pass" || e.key === "review_feedback"));
  const pass = state?.review_pass;
  const feedback = state?.review_feedback;
  const retryCount = reviewUpdates.filter((e) => e.key === "review_pass" && e.new === false).length;

  return (
    <div className="flex flex-col h-full bg-panel border-b border-border">
      <div className="px-3 py-2 border-b border-border bg-reviewer/10">
        <div className="text-reviewer font-bold text-sm">👓 狸花猫 · 审查</div>
        <div className="text-[10px] text-muted">Diff + 测试 + 打回计数</div>
      </div>
      <div className="flex-1 overflow-y-auto cat-scroll p-3">
        <div className="flex items-center gap-3 mb-3">
          <div className={`px-2 py-1 rounded text-xs font-bold ${pass === true ? "bg-executor/20 text-executor" : pass === false ? "bg-danger/20 text-danger" : "text-muted"}`}>
            {pass === true ? "✓ 通过" : pass === false ? "✗ 打回" : "— 待审"}
          </div>
          <div className="text-xs text-muted">打回次数: <span className="text-warn">{retryCount}</span></div>
        </div>
        <div className="text-[10px] text-muted uppercase mb-1">审查反馈</div>
        {feedback ? (
          <pre className="text-xs text-reviewer/90 font-mono whitespace-pre-wrap bg-bg p-2 rounded border border-border">
            {feedback}
          </pre>
        ) : (
          <div className="text-xs text-muted">（待 Reviewer 审查）</div>
        )}
        {reviewUpdates.length > 0 && (
          <div className="mt-3 text-[10px] text-muted uppercase mb-1">审查历史</div>
        )}
        {reviewUpdates.map((u, i) => (
          <div key={i} className="text-[10px] text-muted">
            {u.key}: {String(u.old)} → <span className={u.key === "review_pass" ? (u.new ? "text-executor" : "text-danger") : "text-text"}>{String(u.new)}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
