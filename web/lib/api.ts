// HTTP API client. /api/* is proxied to the FastAPI backend via next.config rewrites.
export interface RunResponse {
  run_id: string;
  task: string;
  roles: string[];
  model: { provider: string; model: string };
}

export async function startRun(task: string, provider?: string, model?: string): Promise<RunResponse> {
  const r = await fetch("/api/meowwork/run", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ task, provider, model }),
  });
  if (!r.ok) throw new Error(`start failed: ${r.status}`);
  return r.json();
}

export interface ConfigResponse {
  providers: Array<{ name: string; base_url: string | null; configured: boolean }>;
}

export async function fetchConfig(): Promise<ConfigResponse> {
  const r = await fetch("/api/config");
  return r.json();
}
