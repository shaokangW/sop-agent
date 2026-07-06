// HTTP API client. /api/* is proxied to the FastAPI backend via next.config rewrites.

export interface GroupCreateResponse {
  group_id: string;
  title: string;
  model: { provider: string; model: string };
}

export async function createGroup(task: string, provider?: string, model?: string): Promise<GroupCreateResponse> {
  const r = await fetch("/api/meowwork/group", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ task, provider, model }),
  });
  if (!r.ok) throw new Error(`create group failed: ${r.status}`);
  return r.json();
}

export async function sendGroupMessage(gid: string, message: string): Promise<{ ok: boolean }> {
  const r = await fetch(`/api/meowwork/group/${gid}/send`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message }),
  });
  if (!r.ok) throw new Error(`send failed: ${r.status}`);
  return r.json();
}

export async function fetchGroupHistory(gid: string): Promise<{ messages: Array<{ role: string; content: string; to: string | null }>; state: unknown }> {
  const r = await fetch(`/api/meowwork/group/${gid}/history`);
  return r.json();
}

export interface ConfigResponse {
  providers: Array<{ name: string; base_url: string | null; configured: boolean }>;
}

export async function fetchConfig(): Promise<ConfigResponse> {
  const r = await fetch("/api/config");
  return r.json();
}
