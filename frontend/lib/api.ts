import type {
  Province, Municipality, Run, RunDetail,
  ChatMessage, AdminStats,
} from "./types";

const API_URL =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

// ── REST helpers ───────────────────────────────────────────────────────────────

export async function getProvinces(): Promise<Province[]> {
  const res = await fetch(`${API_URL}/provinces`);
  if (!res.ok) throw new Error("Failed to fetch provinces");
  return res.json();
}

export async function getMunicipalities(opts?: {
  province?: string;
  search?: string;
  limit?: number;
}): Promise<Municipality[]> {
  const params = new URLSearchParams();
  if (opts?.province) params.set("province", opts.province);
  if (opts?.search) params.set("search", opts.search);
  params.set("limit", String(opts?.limit ?? 2000));
  const res = await fetch(`${API_URL}/municipalities?${params}`);
  if (!res.ok) throw new Error("Failed to fetch municipalities");
  return res.json();
}

export async function createRun(location: string): Promise<{ run_id: string }> {
  const res = await fetch(`${API_URL}/runs`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ location }),
  });
  if (!res.ok) throw new Error("Failed to create run");
  return res.json();
}

export async function getRuns(limit = 50): Promise<Run[]> {
  const res = await fetch(`${API_URL}/runs?limit=${limit}`);
  if (!res.ok) throw new Error("Failed to fetch runs");
  return res.json();
}

export async function getRun(runId: string): Promise<RunDetail> {
  const res = await fetch(`${API_URL}/runs/${runId}`);
  if (!res.ok) throw new Error("Failed to fetch run");
  return res.json();
}

export async function getChatHistory(runId: string): Promise<ChatMessage[]> {
  const res = await fetch(`${API_URL}/chat/${runId}/history`);
  if (!res.ok) throw new Error("Failed to fetch chat history");
  return res.json();
}

export async function getAdminStats(): Promise<AdminStats> {
  const res = await fetch(`${API_URL}/admin/stats`);
  if (!res.ok) throw new Error("Failed to fetch admin stats");
  return res.json();
}

export async function postAdminReindexKB(): Promise<void> {
  const res = await fetch(`${API_URL}/admin/reindex-kb`, { method: "POST" });
  if (!res.ok) throw new Error("Failed to trigger reindex");
}

export async function postAdminRefreshScores(): Promise<void> {
  const res = await fetch(`${API_URL}/admin/refresh-scores`, { method: "POST" });
  if (!res.ok) throw new Error("Failed to trigger refresh");
}

// ── EventSource helpers ────────────────────────────────────────────────────────

export function openRunStream(runId: string): EventSource {
  return new EventSource(`${API_URL}/runs/${runId}/stream`);
}

export function openRefreshStream(): EventSource {
  return new EventSource(`${API_URL}/admin/refresh-scores/stream`);
}

// ── Streaming chat ─────────────────────────────────────────────────────────────

export async function* streamChat(
  message: string,
  runId: string | null
): AsyncGenerator<string> {
  const res = await fetch(`${API_URL}/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message, run_id: runId }),
  });
  if (!res.ok) throw new Error("Chat request failed");

  if (!res.body) throw new Error("Response body is null — cannot stream chat");
  const reader = res.body.getReader();
  const decoder = new TextDecoder();

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    const text = decoder.decode(value, { stream: true });
    for (const line of text.split("\n")) {
      if (!line.startsWith("data: ")) continue;
      const data = line.slice(6);
      if (data === "[DONE]") return;
      if (data) yield data;
    }
  }
}
