"use client";
import Link from "next/link";
import useSWR from "swr";
import type { Run } from "@/lib/types";
import { getRuns } from "@/lib/api";

export default function ReportsIndexPage() {
  const { data: runs = [], isLoading } = useSWR<Run[]>("runs", () => getRuns(50));
  const doneRuns = runs.filter((r) => r.status === "done" && !r.location.startsWith("admin:"));

  if (isLoading) {
    return (
      <div className="flex items-center justify-center flex-1 text-stone-400 text-sm">
        Loading…
      </div>
    );
  }

  if (doneRuns.length === 0) {
    return (
      <div className="flex items-center justify-center flex-1">
        <div className="text-center">
          <p className="text-stone-400 mb-4 text-sm">No reports yet.</p>
          <Link
            href="/map"
            className="px-4 py-2 bg-amber-600 text-white text-sm font-semibold rounded-md hover:bg-amber-700 transition-colors"
          >
            Run your first analysis
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div className="max-w-2xl mx-auto px-6 py-8">
      <h1 className="text-lg font-bold text-stone-900 mb-6">Reports</h1>
      <div className="flex flex-col gap-3">
        {doneRuns.map((run) => (
          <Link
            key={run.id}
            href={`/reports/${run.id}`}
            className="block bg-white border border-stone-200 rounded-lg px-5 py-4 shadow-sm hover:border-amber-300 hover:shadow-md transition-all"
          >
            <div className="flex items-center justify-between">
              <div>
                <p className="font-semibold text-stone-900">{run.location}</p>
                <p className="text-xs text-stone-400 mt-0.5">
                  {new Date(run.created_at).toLocaleDateString("en-PH", {
                    month: "long",
                    day: "numeric",
                    year: "numeric",
                  })}
                </p>
              </div>
              <span className="text-xs font-semibold text-emerald-600 bg-emerald-50 border border-emerald-200 rounded-full px-2.5 py-0.5">
                ✓ Done
              </span>
            </div>
          </Link>
        ))}
      </div>
    </div>
  );
}
