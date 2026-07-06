import { create } from "zustand";
import type { BaseEvent, MeowState } from "./types";

interface MeowStore {
  events: BaseEvent[];
  state: MeowState | null;
  groupId: string | null;
  streaming: Record<string, string>;
  connected: boolean;
  roundActive: boolean; // a discussion round is in progress (disable input)
  paused: boolean;
  start: (groupId: string) => void;
  addEvent: (e: BaseEvent) => void;
  appendStream: (role: string, delta: string) => void;
  clearStream: (role: string) => void;
  setState: (s: MeowState) => void;
  setConnected: (v: boolean) => void;
  setRoundActive: (v: boolean) => void;
  togglePause: () => void;
  reset: () => void;
}

export const useMeowStore = create<MeowStore>((set) => ({
  events: [],
  state: null,
  groupId: null,
  streaming: {},
  connected: false,
  roundActive: false,
  paused: false,
  start: (groupId) => set({ groupId, events: [], state: null, streaming: {}, connected: false }),
  addEvent: (e) => set((s) => ({ events: [...s.events, e] })),
  appendStream: (role, delta) => set((s) => ({ streaming: { ...s.streaming, [role]: (s.streaming[role] || "") + delta } })),
  clearStream: (role) => set((s) => {
    const next = { ...s.streaming };
    delete next[role];
    return { streaming: next };
  }),
  setState: (st) => set({ state: st }),
  setConnected: (v) => set({ connected: v }),
  setRoundActive: (v) => set({ roundActive: v }),
  togglePause: () => set((s) => ({ paused: !s.paused })),
  reset: () => set({ events: [], state: null, groupId: null, streaming: {}, connected: false }),
}));
