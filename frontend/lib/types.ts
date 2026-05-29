export interface Province {
  name: string;
}

export interface Municipality {
  id: number;
  name: string;
  province: string;
  region: string;
  lat: number | null;
  lon: number | null;
  geo_score: number | null;
  solar_norm: number | null;
  income_score: number | null;
  pop_density_norm: number | null;
}

export type RunStatus = "pending" | "running" | "done" | "failed";

export interface Run {
  id: string;
  location: string;
  province: string | null;
  status: RunStatus;
  created_at: string;
  completed_at: string | null;
  error: string | null;
}

export interface RunResult {
  municipality_id: number;
  municipality_name: string;
  province: string;
  lat: number | null;
  lon: number | null;
  geo_score: number;
  web_score: number;
  final_score: number;
  tier: string;
  assessment: string;
  opportunities: string[];
  risks: string[];
}

export interface Report {
  slug: string;
  markdown: string;
  file_path: string;
  created_at: string;
}

export interface RunDetail extends Run {
  results: RunResult[];
  report: Report | null;
}

export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
  created_at: string;
}

export interface AdminStats {
  municipalities: number;
  geo_scores: number;
  runs: number;
  run_results: number;
  chat_messages: number;
  reports: number;
  web_intel_cache: number;
  last_precompute: string | null;
}

export interface StepEvent {
  step: string;
  status: "running" | "done" | "failed" | "complete";
  elapsed_ms: number;
  run_id?: string;
  error?: string | null;
}

export type Tier = "A" | "B" | "C" | "D";

export function getTier(score: number | null): Tier | null {
  if (score === null) return null;
  if (score >= 0.8) return "A";
  if (score >= 0.65) return "B";
  if (score >= 0.5) return "C";
  return "D";
}
