"use client";
import { useEffect, useRef } from "react";
import { motion } from "framer-motion";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { useMeowStore } from "@/lib/store";
import type {
  BaseEvent, MessageEv, PhaseEv, SecurityAlertEv,
  SubAgentEv, ToolEv,
} from "@/lib/types";

const AVATAR: Record<string, string> = { planner: "🐱", executor: "🧡", reviewer: "👓", validator: "🐈‍⬛" };

export default function ChatStream() {
  const { events, state, streaming } = useMeowStore();
  const endRef = useRef<HTMLDivElement>(null);
  useEffect(() => { endRef.current?.scrollIntoView({ behavior: "smooth" }); }, [events.length, streaming]);

  const shown = events.filter((e) =>
    ["message", "tool", "subagent", "security_alert", "phase", "done"].includes(e.type)
  );
  const streams = Object.entries(streaming).filter(([, v]) => v);

  return (
    <main className="flex-1 flex flex-col bg-bg overflow-hidden">
      <div className="flex-1 overflow-y-auto cat-scroll px-6 py-4">
        <div className="max-w-5xl mx-auto space-y-2">
          {shown.length === 0 && (
            <div className="text-center text-muted text-sm py-20">
              <div className="text-3xl mb-2">🐾</div>
              在下方发消息,四只猫将在这里群聊讨论…
            </div>
          )}
          {shown.map((ev, i) => <ChatLine key={i} ev={ev} />)}
          {streams.map(([role, text]) => <StreamBubble key={role} role={role} text={text} />)}
          {state?.finished && (
            <div className="text-center text-validator text-sm py-2 border-t border-border">
              ✓ 任务完成{state.summary ? `:${state.summary}` : ""}
            </div>
          )}
          <div ref={endRef} />
        </div>
      </div>
    </main>
  );
}

function StreamBubble({ role, text }: { role: string; text: string }) {
  return (
    <motion.div initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} className="flex gap-2.5">
      <span className="text-lg leading-tight animate-pulse-slow">{AVATAR[role] ?? "·"}</span>
      <div className="flex-1 min-w-0">
        <div className="flex items-baseline gap-1.5">
          <span className={`text-xs font-medium text-${role}`}>{roleName(role)}</span>
          <ThinkingDots />
        </div>
        <div className="text-sm text-text bg-panel border border-border rounded-lg rounded-tl-sm px-3 py-1.5 inline-block max-w-[900px]">
          {text}<span className="inline-block w-1.5 h-3.5 bg-accent ml-0.5 align-text-bottom animate-pulse" />
        </div>
      </div>
    </motion.div>
  );
}

function ThinkingDots() {
  return (
    <span className="inline-flex items-center gap-0.5 text-muted">
      <span className="text-[10px]">思考中</span>
      <span className="inline-flex gap-0.5">
        <span className="w-1 h-1 rounded-full bg-muted animate-pulse" />
        <span className="w-1 h-1 rounded-full bg-muted animate-pulse" style={{ animationDelay: "0.2s" }} />
        <span className="w-1 h-1 rounded-full bg-muted animate-pulse" style={{ animationDelay: "0.4s" }} />
      </span>
    </span>
  );
}

function ChatLine({ ev }: { ev: BaseEvent }) {
  if (ev.type === "message") {
    const m = ev as MessageEv;
    if (m.from === "user") {
      return (
        <motion.div initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} className="flex justify-end">
          <div className="max-w-[800px]">
            <div className="flex items-baseline gap-1.5 justify-end mb-0.5">
              <span className="text-[10px] text-muted">你</span>
            </div>
            <div className="text-sm bg-accent/10 border border-accent/40 text-text rounded-lg rounded-tr-sm px-3 py-1.5">
              {m.content}
            </div>
          </div>
        </motion.div>
      );
    }
    return (
      <motion.div initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} className="flex gap-2.5">
        <span className="text-lg leading-tight">{AVATAR[m.from] ?? "·"}</span>
        <div className="flex-1 min-w-0">
          <div className="flex items-baseline gap-1.5">
            <span className={`text-xs font-medium text-${m.from}`}>{roleName(m.from)}</span>
            {m.to && <span className="text-[10px] text-muted">→ {roleName(m.to)}</span>}
            <span className="text-[10px] text-muted">· {m.to ? "私聊" : "广播"}</span>
          </div>
          <div className="text-sm text-text bg-panel border border-border rounded-lg rounded-tl-sm px-3 py-1.5 inline-block max-w-[900px]">
            <div className="markdown">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{m.content}</ReactMarkdown>
            </div>
          </div>
        </div>
      </motion.div>
    );
  }
  if (ev.type === "tool") {
    const t = ev as ToolEv;
    return (
      <SystemLine>
        <span className={t.ok ? "text-validator" : "text-danger"}>{t.ok ? "✓" : "✗"}</span>
        <span className="text-muted">工具</span>
        <span className="font-mono text-executor">{t.name}</span>
        <span className="text-muted truncate flex-1">{(t.result || "").slice(0, 100)}</span>
      </SystemLine>
    );
  }
  if (ev.type === "subagent") {
    const s = ev as SubAgentEv;
    return (
      <SystemLine>
        <span>🐾</span><span className="text-muted">子agent #{s.pid}</span>
        <span className="text-executor">{s.role}</span>
        <span className="text-muted truncate flex-1">{s.task}</span>
        <span className={s.status === "done" ? "text-validator" : s.status === "running" ? "text-planner" : "text-danger"}>{s.status}</span>
      </SystemLine>
    );
  }
  if (ev.type === "security_alert") {
    const a = ev as SecurityAlertEv;
    return (
      <div className="flex gap-2.5 items-start border border-danger/40 bg-danger/5 rounded-lg px-3 py-1.5">
        <span>⛔</span>
        <div className="text-xs flex-1 min-w-0">
          <span className="text-danger font-medium">玄猫拦截 · {a.tool}</span>
          <span className="text-muted ml-2 break-all">{JSON.stringify(a.args).slice(0, 120)}</span>
          <div className="text-warn">{a.reason}</div>
        </div>
      </div>
    );
  }
  if (ev.type === "phase") {
    const p = ev as PhaseEv;
    return (
      <SystemLine>
        <span className="text-accent">↻</span>
        <span className="text-muted">阶段推进</span>
        <span className="text-text">{p.from} → {p.to}</span>
        <span className="text-muted">by {roleName(p.by)}</span>
      </SystemLine>
    );
  }
  return null;
}

function SystemLine({ children }: { children: React.ReactNode }) {
  return (
    <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }}
      className="flex items-center gap-2 text-[11px] pl-8 text-muted">
      {children}
    </motion.div>
  );
}

function roleName(r: string): string {
  return ({ planner: "布偶猫", executor: "橘猫", reviewer: "狸花猫", validator: "玄猫" } as Record<string, string>)[r] ?? r;
}
