"use client";
import { useEffect, useState } from "react";
import { useMeowStore } from "@/lib/store";
import { createGroup, sendGroupMessage, fetchConfig, type ConfigResponse } from "@/lib/api";

export default function TaskInput() {
  const [msg, setMsg] = useState("");
  const [provider, setProvider] = useState("");
  const [model, setModel] = useState("");
  const [cfg, setCfg] = useState<ConfigResponse | null>(null);
  const { start, groupId, state, roundActive, events, addEvent, paused, togglePause } = useMeowStore();

  useEffect(() => { fetchConfig().then(setCfg).catch(() => {}); }, []);

  async function send() {
    const text = msg.trim();
    if (!text || roundActive) return;
    setMsg("");
    // slash commands
    if (text === "/new") {
      useMeowStore.getState().reset();
      return;
    }
    // @mention routing: user can direct with @executor/@reviewer/@planner
    if (!groupId) {
      // first message → create group, then add optimistic user message
      try {
        const r = await createGroup(text, provider || undefined, model || undefined);
        start(r.group_id);          // clears events, sets groupId
        addEvent({ type: "message", from: "user", to: null, content: text } as never);
        await sendGroupMessage(r.group_id, text);
        useMeowStore.setState({ roundActive: true });
      } catch (e) { console.error(e); }
    } else {
      addEvent({ type: "message", from: "user", to: null, content: text } as never);
      try { await sendGroupMessage(groupId, text); } catch (e) { console.error(e); }
      useMeowStore.setState({ roundActive: true });
    }
  }

  async function togglePauseBtn() {
    const next = !paused;
    togglePause();
    if (groupId) {
      try { await fetch(`/api/meowwork/run/${groupId}/pause`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ paused: next }) }); } catch {}
    }
  }

  return (
    <div className="border-b border-border bg-panel">
      <div className="max-w-5xl mx-auto px-6 py-3">
        <div className="flex items-center justify-between mb-2">
          <div>
            <h1 className="text-lg font-serif text-text">MeowWork</h1>
            <p className="text-[10px] text-muted">多智能体群组协作 · 持续对话 · 有记忆</p>
          </div>
          <div className="flex items-center gap-3 text-xs text-muted">
            <span>阶段 <span className="text-accent font-medium">{state?.phase ?? "—"}</span></span>
            <span>轮次 <span className="text-text">{state?.turn ?? 0}</span></span>
            {state?.finished && <span className="text-validator">✓ 完成</span>}
            <button onClick={togglePauseBtn} disabled={!groupId}
              className={`px-2.5 py-1 rounded border text-xs disabled:opacity-30 ${paused ? "bg-warn text-white border-warn" : "border-border text-muted"}`}>
              🌿 {paused ? "已冻结" : "Pause"}
            </button>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <input value={msg} onChange={(e) => setMsg(e.target.value)} onKeyDown={(e) => e.key === "Enter" && send()}
            placeholder={roundActive ? "四猫协作中,完成后可发下一个需求…" : "发消息(可 @executor/@reviewer/@planner 定向,或 /new 重置)"}
            disabled={roundActive}
            className="flex-1 bg-bg border border-border rounded-lg px-4 py-2 text-sm focus:outline-none focus:border-accent disabled:opacity-50" />
          <select value={provider} onChange={(e) => setProvider(e.target.value)} className="bg-bg border border-border rounded-lg px-2 py-2 text-xs">
            <option value="">默认</option>
            {cfg?.providers.map((p) => <option key={p.name} value={p.name} disabled={!p.configured && p.name !== "ollama"}>{p.name}</option>)}
          </select>
          <input value={model} onChange={(e) => setModel(e.target.value)} placeholder="模型" className="bg-bg border border-border rounded-lg px-2 py-2 text-xs w-24" />
          <button onClick={send} disabled={roundActive || !msg.trim()}
            className="bg-accent text-white rounded-lg px-5 py-2 text-sm font-medium disabled:opacity-40">
            {roundActive ? "协作中…" : "发送"}
          </button>
        </div>
      </div>
    </div>
  );
}
