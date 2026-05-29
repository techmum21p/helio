"use client";
import { useState } from "react";
import useSWR from "swr";
import type { AdminStats } from "@/lib/types";
import { getAdminStats, postAdminReindexKB, postAdminRefreshScores } from "@/lib/api";
import StatCard from "@/components/stat-card";
import RunProgress from "@/components/run-progress";

export default function AdminPage() {
  const { data: stats, mutate } = useSWR<AdminStats>("admin/stats", getAdminStats, {
    refreshInterval: 30000,
  });
  const [reindexing, setReindexing] = useState(false);
  const [reindexMsg, setReindexMsg] = useState("");
  const [refreshRunId, setRefreshRunId] = useState<string | null>(null);
  const [refreshMsg, setRefreshMsg] = useState("");

  async function handleReindex() {
    setReindexing(true);
    setReindexMsg("");
    try {
      await postAdminReindexKB();
      setReindexMsg("Re-index started.");
      setTimeout(() => mutate(), 3000);
    } catch (e) {
      setReindexMsg(`Error: ${e}`);
    } finally {
      setReindexing(false);
    }
  }

  async function handleRefresh() {
    setRefreshMsg("");
    try {
      const { run_id } = await postAdminRefreshScores();
      setRefreshRunId(run_id);
    } catch (e) {
      setRefreshMsg(`Error: ${e}`);
    }
  }

  const lastPrecompute = stats?.last_precompute
    ? new Date(stats.last_precompute).toLocaleString("en-PH")
    : "Never";

  return (
    <div className="max-w-3xl mx-auto px-6 py-10">
      <h1 className="text-xl font-bold text-stone-900 mb-6">Admin</h1>

      {/* Stats grid */}
      {stats && (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-10">
          <StatCard label="Municipalities" value={stats.municipalities} />
          <StatCard label="Geo Scores" value={stats.geo_scores} sub={`Last: ${lastPrecompute}`} />
          <StatCard label="Runs" value={stats.runs} />
          <StatCard label="Reports" value={stats.reports} />
          <StatCard label="Run Results" value={stats.run_results} />
          <StatCard label="Chat Messages" value={stats.chat_messages} />
          <StatCard label="Web Intel Cache" value={stats.web_intel_cache} />
          <StatCard label="KB Chunks" value={null} sub="ChromaDB (see logs)" />
        </div>
      )}

      {/* Actions */}
      <div className="space-y-6">
        <div className="bg-white border border-stone-200 rounded-lg shadow-sm p-5">
          <h2 className="text-sm font-semibold text-stone-900 mb-1">Refresh Geo Scores</h2>
          <p className="text-xs text-stone-400 mb-4">Re-run precompute_geo_scores.py for all 1,622 municipalities. Implemented in Plan 2.</p>
          {refreshRunId ? (
            <RunProgress
              runId={refreshRunId}
              onComplete={() => { setRefreshRunId(null); setRefreshMsg("Done."); mutate(); }}
              onFailed={(e) => { setRefreshRunId(null); setRefreshMsg(`Failed: ${e}`); }}
            />
          ) : (
            <button
              className="px-4 py-2 bg-amber-600 hover:bg-amber-700 text-white text-sm font-semibold rounded-md transition-colors"
              onClick={handleRefresh}
            >
              Refresh Geo Scores
            </button>
          )}
          {refreshMsg && <p className="mt-2 text-xs text-stone-500">{refreshMsg}</p>}
        </div>

        <div className="bg-white border border-stone-200 rounded-lg shadow-sm p-5">
          <h2 className="text-sm font-semibold text-stone-900 mb-1">Re-index Knowledge Base</h2>
          <p className="text-xs text-stone-400 mb-4">Scan kb/reports/ and kb/intel/ for new markdown files and add to ChromaDB.</p>
          <button
            className="px-4 py-2 bg-amber-600 hover:bg-amber-700 disabled:opacity-40 text-white text-sm font-semibold rounded-md transition-colors"
            onClick={handleReindex}
            disabled={reindexing}
          >
            {reindexing ? "Re-indexing…" : "Re-index KB"}
          </button>
          {reindexMsg && <p className="mt-2 text-xs text-stone-500">{reindexMsg}</p>}
        </div>
      </div>
    </div>
  );
}
