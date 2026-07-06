"use client";
import { motion, AnimatePresence } from "framer-motion";
import { useMeowStore } from "@/lib/store";
import type { SecurityAlertEv } from "@/lib/types";

export default function ValidatorPanel() {
  const events = useMeowStore((s) => s.events);
  const alerts = events.filter((e): e is SecurityAlertEv => e.type === "security_alert");
  const hasAlert = alerts.length > 0;

  return (
    <div className={`flex flex-col h-full bg-black border-t border-border ${hasAlert ? "animate-shake" : ""}`}>
      <div className={`px-3 py-2 border-b border-border ${hasAlert ? "bg-danger/20" : "bg-validator/10"}`}>
        <div className={`font-bold text-sm ${hasAlert ? "text-danger" : "text-validator"}`}>
          🐈‍⬛ 玄猫 · 安全网关 {hasAlert && "💥 炸毛"}
        </div>
        <div className="text-[10px] text-muted">零信任 · Shell/IO 瀑布</div>
      </div>
      <div className="flex-1 overflow-y-auto cat-scroll p-3 bg-black">
        {alerts.length === 0 ? (
          <div className="text-xs text-validator/40 matrix-glow font-mono">≻ awaiting execution... (no alerts)</div>
        ) : (
          <AnimatePresence>
            {alerts.map((a, i) => (
              <motion.div key={i} initial={{ opacity: 0, x: 20 }} animate={{ opacity: 1, x: 0 }}
                className="text-xs font-mono mb-2 border border-danger/40 rounded p-2 bg-danger/5">
                <div className="text-danger font-bold">⛔ ACCESS DENIED</div>
                <div className="text-validator matrix-glow">tool: {a.tool}</div>
                <div className="text-validator/70 break-all">
                  args: {JSON.stringify(a.args).slice(0, 200)}
                </div>
                <div className="text-warn">reason: {a.reason}</div>
              </motion.div>
            ))}
          </AnimatePresence>
        )}
      </div>
      {hasAlert && (
        <div className="px-3 py-1 bg-danger text-bg text-center text-xs font-bold">
          ⛔ 检测到 {alerts.length} 次危险操作拦截
        </div>
      )}
    </div>
  );
}
