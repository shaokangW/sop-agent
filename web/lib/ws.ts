import { useEffect } from "react";
import { useMeowStore } from "./store";
import type { BaseEvent, MeowState } from "./types";

/** Connect to the backend group WS; streams events across multiple sends. */
export function useMeowWorkWS(groupId: string | null) {
  const addEvent = useMeowStore((s) => s.addEvent);
  const appendStream = useMeowStore((s) => s.appendStream);
  const clearStream = useMeowStore((s) => s.clearStream);
  const setState = useMeowStore((s) => s.setState);
  const setConnected = useMeowStore((s) => s.setConnected);
  const setRoundActive = useMeowStore((s) => s.setRoundActive);

  useEffect(() => {
    if (!groupId) return;
    const base = process.env.NEXT_PUBLIC_WS_BASE || "ws://127.0.0.1:8000";
    const ws = new WebSocket(`${base}/ws/meowwork/group/${groupId}`);

    ws.onopen = () => setConnected(true);
    ws.onclose = () => setConnected(false);
    ws.onerror = () => setConnected(false);
    ws.onmessage = (e) => {
      try {
        const ev = JSON.parse(e.data) as BaseEvent;
        if (ev.type === "round_done") {
          setRoundActive(false);
          setState((ev as unknown as { state: MeowState }).state);
          return;
        }
        if (ev.type === "token") {
          const t = ev as { type: "token"; step_id: string; delta: string };
          appendStream(t.step_id, t.delta);
        } else {
          if (ev.type === "message") {
            const m = ev as { type: "message"; from: string };
            clearStream(m.from);
          }
          addEvent(ev);
        }
      } catch {
        /* ignore */
      }
    };
    return () => ws.close();
  }, [groupId, addEvent, appendStream, clearStream, setState, setConnected, setRoundActive]);
}
