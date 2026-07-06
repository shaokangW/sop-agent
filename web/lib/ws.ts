import { useEffect } from "react";
import { useMeowStore } from "./store";
import type { BaseEvent, MeowState } from "./types";

/** Connect to the backend WS for a MeowWork run; dispatch events into the store. */
export function useMeowWorkWS(runId: string | null) {
  const addEvent = useMeowStore((s) => s.addEvent);
  const setState = useMeowStore((s) => s.setState);
  const setConnected = useMeowStore((s) => s.setConnected);

  useEffect(() => {
    if (!runId) return;
    const base = process.env.NEXT_PUBLIC_WS_BASE || "ws://127.0.0.1:8000";
    const ws = new WebSocket(`${base}/ws/meowwork/${runId}`);

    ws.onopen = () => setConnected(true);
    ws.onclose = () => setConnected(false);
    ws.onerror = () => setConnected(false);
    ws.onmessage = (e) => {
      try {
        const ev = JSON.parse(e.data) as BaseEvent;
        if (ev.type === "final_state") {
          setState((ev as unknown as { state: MeowState }).state);
        } else {
          addEvent(ev);
        }
      } catch {
        /* ignore non-json */
      }
    };
    return () => ws.close();
  }, [runId, addEvent, setState, setConnected]);
}
