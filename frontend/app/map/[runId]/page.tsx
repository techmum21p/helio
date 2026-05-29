"use client";
import { useState } from "react";
import { useParams } from "next/navigation";
import useSWR from "swr";
import dynamic from "next/dynamic";
import type { RunDetail } from "@/lib/types";
import { getRun } from "@/lib/api";

const RunMapView = dynamic(() => import("@/components/run-map-view"), { ssr: false });

function TierBadge({ tier }: { tier: string }) {
  const styles: Record<string, string> = {
    HIGH:   "bg-emerald-100 text-emerald-800",
    MEDIUM: "bg-amber-100 text-amber-800",
    LOW:    "bg-red-100 text-red-700",
  };
  return (
    <span className={`inline-block text-[10px] font-bold px-1.5 py-0.5 rounded ${styles[tier] ?? "bg-stone-100 text-stone-600"}`}>
      {tier}
    </span>
  );
}

function ScoreBar({ score }: { score: number }) {
  return (
    <div className="h-1 bg-stone-100 rounded-full overflow-hidden mt-1.5">
      <div
        className="h-full rounded-full bg-gradient-to-r from-amber-500 to-amber-400"
        style={{ width: `${(score * 100).toFixed(1)}%` }}
      />
    </div>
  );
}

export default function MapScoresPage() {
  const { runId } = useParams<{ runId: string }>();
  const { data: run, isLoading } = useSWR<RunDetail>(
    runId ? `run/${runId}` : null,
    () => getRun(runId)
  );
  const [expandedId, setExpandedId] = useState<number | null>(null);

  if (isLoading) {
    return <div className="flex items-center justify-center flex-1 text-stone-400 text-sm">Loading…</div>;
  }
  if (!run) {
    return <div className="flex items-center justify-center flex-1 text-stone-400 text-sm">Run not found.</div>;
  }

  const results = run.results ?? [];
  const top = results[0];

  const avgSolar = results.length
    ? (results.reduce((s, r) => s + (r.geo_score ?? 0), 0) / results.length).toFixed(3)
    : "—";

  // Derive map center from result coordinates
  const withCoords = results.filter((r) => r.lat != null && r.lon != null);
  const mapCenter: [number, number] = withCoords.length > 0
    ? [
        withCoords.reduce((s, r) => s + r.lat!, 0) / withCoords.length,
        withCoords.reduce((s, r) => s + r.lon!, 0) / withCoords.length,
      ]
    : [12.8797, 121.774];

  return (
    <div className="flex flex-col h-full overflow-hidden">
      {/* Page header */}
      <div className="px-6 pt-5 pb-3 border-b border-stone-200 shrink-0">
        <h1 className="text-base font-bold text-stone-900">Map & Scores</h1>
        <p className="text-xs text-stone-500 mt-0.5">
          {run.location} · {results.length} municipalities ·{" "}
          {new Date(run.created_at).toLocaleDateString("en-PH", { month: "short", day: "numeric", year: "numeric" })}
        </p>
      </div>

      {/* Stat cards */}
      <div className="flex gap-3 px-6 py-3 border-b border-stone-200 shrink-0">
        {[
          { label: "Top Score",      value: top ? top.final_score.toFixed(3) : "—",  color: "text-amber-600" },
          { label: "Top Tier",       value: top?.tier ?? "—",                          color: "text-emerald-600" },
          { label: "Municipalities", value: String(results.length),                    color: "text-blue-600"   },
          { label: "Avg Geo Score",  value: avgSolar,                                  color: "text-stone-700"  },
        ].map(({ label, value, color }) => (
          <div key={label} className="flex-1 bg-white border border-stone-200 rounded-lg px-4 py-2.5 shadow-sm">
            <p className={`text-lg font-bold ${color}`}>{value}</p>
            <p className="text-[10px] text-stone-400 mt-0.5">{label}</p>
          </div>
        ))}
      </div>

      {/* Map + targets */}
      <div className="flex-1 grid overflow-hidden" style={{ gridTemplateColumns: "1fr 260px" }}>
        {/* Map */}
        <div className="overflow-hidden">
          {results.length > 0 ? (
            <RunMapView results={results} center={mapCenter} />
          ) : (
            <div className="flex items-center justify-center h-full text-stone-400 text-sm">
              No map data available.
            </div>
          )}
        </div>

        {/* Top targets list — expandable cards */}
        <div className="border-l border-stone-200 overflow-y-auto bg-stone-50 flex flex-col">
          <div className="px-3 py-2.5 border-b border-stone-200 shrink-0">
            <p className="text-[10px] font-bold tracking-widest uppercase text-stone-400">
              Top Targets — click to expand
            </p>
          </div>
          <div className="flex flex-col gap-1.5 p-2.5">
            {results.slice(0, 15).map((r) => {
              const expanded = r.municipality_id !== null && expandedId === r.municipality_id;
              return (
                <div
                  key={r.municipality_id ?? r.municipality_name}
                  className={`border rounded-lg px-3 py-2 shadow-sm cursor-pointer transition-colors ${
                    expanded
                      ? "bg-amber-50 border-amber-300"
                      : "bg-white border-stone-200 hover:border-amber-200"
                  }`}
                  onClick={() => setExpandedId(expanded ? null : (r.municipality_id ?? null))}
                >
                  <div className="flex items-center gap-1.5">
                    <span className="flex-1 text-xs font-semibold text-stone-900 truncate">
                      {r.municipality_name}
                    </span>
                    <TierBadge tier={r.tier} />
                    <span className="text-xs font-bold text-amber-600 tabular-nums shrink-0">
                      {r.final_score.toFixed(3)}
                    </span>
                  </div>
                  <ScoreBar score={r.final_score} />

                  {expanded && (
                    <div className="mt-2.5 pt-2.5 border-t border-amber-200 space-y-2">
                      {r.assessment && (
                        <div>
                          <p className="text-[9px] font-bold text-stone-400 uppercase tracking-widest mb-0.5">
                            Assessment
                          </p>
                          <p className="text-[11px] text-stone-600 leading-relaxed">
                            {r.assessment}
                          </p>
                        </div>
                      )}
                      {r.opportunities?.length > 0 && (
                        <div>
                          <p className="text-[9px] font-bold text-emerald-600 uppercase tracking-widest mb-0.5">
                            Opportunity
                          </p>
                          <p className="text-[11px] text-stone-600 leading-relaxed">
                            {r.opportunities[0]}
                          </p>
                        </div>
                      )}
                      {r.risks?.length > 0 && (
                        <div>
                          <p className="text-[9px] font-bold text-red-500 uppercase tracking-widest mb-0.5">
                            Risk
                          </p>
                          <p className="text-[11px] text-stone-600 leading-relaxed">
                            {r.risks[0]}
                          </p>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
}
