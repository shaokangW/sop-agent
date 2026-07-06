import { create } from "zustand";
import type { BaseEvent, MeowState } from "./types";

interface MeowStore {
  events: BaseEvent[];
  state: MeowState | null;
  runId: string | null;
  connected: boolean;
  paused: boolean; // catnip global pause (Phase 5)
  start: (runId: string) => void;
  addEvent: (e: BaseEvent) => void;
  setState: (s: MeowState) => void;
  setConnected: (v: boolean) => void;
  togglePause: () => void;
  reset: () => void;
}

export const useMeowStore = create<MeowStore>((set) => ({
  events: [],
  state: null,
  runId: null,
  connected: false,
  paused: false,
  start: (runId) => set({ runId, events: [], state: null, connected: false }),
  addEvent: (e) => set((s) => ({ events: [...s.events, e] })),
  setState: (st) => set({ state: st }),
  setConnected: (v) => set({ connected: v }),
  togglePause: () => set((s) => ({ paused: !s.paused })),
  reset: () => set({ events: [], state: null, runId: null, connected: false }),
}));
