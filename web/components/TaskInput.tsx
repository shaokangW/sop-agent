"use client";
import { useEffect, useState } from "react";
import { useMeowStore } from "@/lib/store";
import { startRun, fetchConfig, type ConfigResponse } from "@/lib/api";

export default function TaskInput() {
  const [task, setTask] = useState("");
  const [provider, setProvider] = useState("");
  const [model, setModel] = useState("");
  const [cfg, setCfg] = useState<ConfigResponse | null>(null);
  const [busy, setBusy] = useState(false);
  const start = useMeowStore((s) => s.start);

  useEffect(() => { fetchConfig().then(setCfg).catch(() => {}); }, []);

  async function go() {
    if (!task.trim() || busy) return;
    setBusy(true);
    try {
      const r = await startRun(task.trim(), provider || undefined, model || undefined);
      start(r.run_id);
      setTask("");
    } catch (e) { console.error(e); }
    setBusy(false);
  }

  return (
    <div className="flex items-center gap-2 p-3 bg-panel border-b border-border">
      <span className="text-planner font-bold text-sm whitespace-nowrap">🐾 MeowWork</span>
      <input
        value={task}
        onChange={(e) => setTask(e.target.value)}
        onKeyDown={(e) => e.key === "Enter" && go()}
        placeholder="输入任务:如 分析漏洞并编写修复脚本"
        className="flex-1 bg-bg border border-border rounded px-3 py-1.5 text-sm focus:outline-none focus:border-executor"
      />
      <select value={provider} onChange={(e) => setProvider(e.target.value)}
        className="bg-bg border border-border rounded px-2 py-1.5 text-xs">
        <option value="">默认 provider</option>
        {cfg?.providers.map((p) => (
          <option key={p.name} value={p.name} disabled={!p.configured && p.name !== "ollama"}>
            {p.name}{p.configured ? "" : " (未配置)"}
          </option>
        ))}
      </select>
      <input value={model} onChange={(e) => setModel(e.target.value)} placeholder="模型(可选)"
        className="bg-bg border border-border rounded px-2 py-1.5 text-xs w-32" />
      <button onClick={go} disabled={busy || !task.trim()}
        className="bg-executor text-bg font-bold rounded px-4 py-1.5 text-sm disabled:opacity-50">
        {busy ? "启动中…" : "启动协作"}
      </button>
    </div>
  );
}
