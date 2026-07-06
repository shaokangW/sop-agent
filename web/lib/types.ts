// MeowWork event types (matches backend _serialize_event shapes)
export type EventType =
  | "message" | "state_update" | "phase" | "subagent" | "security_alert"
  | "token" | "turn" | "tool" | "done" | "final_state" | "error";

export interface BaseEvent { type: EventType; [k: string]: unknown }

export interface MessageEv extends BaseEvent { type: "message"; from: string; to: string | null; content: string }
export interface StateUpdateEv extends BaseEvent { type: "state_update"; key: string; old: unknown; new: unknown; by: string }
export interface PhaseEv extends BaseEvent { type: "phase"; from: string; to: string; by: string }
export interface SubAgentEv extends BaseEvent { type: "subagent"; pid: number; role: string; task: string; status: string }
export interface SecurityAlertEv extends BaseEvent { type: "security_alert"; tool: string; args: Record<string, unknown>; reason: string; blocked: boolean }
export interface ToolEv extends BaseEvent { type: "tool"; name: string; ok: boolean; result: string }
export interface TurnEv extends BaseEvent { type: "turn"; step_id: string; turn: number; content: string | null; tool_calls: unknown[] }
export interface DoneEv extends BaseEvent { type: "done" }
export interface FinalStateEv extends BaseEvent { type: "final_state"; state: MeowState }

export interface MeowState {
  task: string;
  phase: string;
  plan_tree: Record<string, { desc?: string; status?: string; assignee?: string; artifact?: string }>;
  current_artifact: string | null;
  review_feedback: string | null;
  review_pass: boolean | null;
  security_alerts: Array<Record<string, unknown>>;
  sub_agents: Array<{ pid: number; role: string; task: string; status: string; started_at?: number; duration?: number }>;
  turn: number;
  finished: boolean;
  summary: string | null;
}

export const ROLE_PERSONA: Record<string, string> = {
  planner: "布偶猫",
  executor: "橘猫",
  reviewer: "狸花猫",
  validator: "玄猫",
};
