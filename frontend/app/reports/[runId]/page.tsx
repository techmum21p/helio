"use client";
import { useParams } from "next/navigation";
import useSWR from "swr";
import type { Run, RunDetail } from "@/lib/types";
import { getRuns, getRun } from "@/lib/api";
import RunList from "@/components/run-list";
import ChatPanel from "@/components/chat-panel";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

export default function ReportPage() {
  const { runId } = useParams<{ runId: string }>();
  const { data: runs = [] } = useSWR<Run[]>("runs", () => getRuns(50));
  const { data: run, isLoading } = useSWR<RunDetail>(
    runId ? `run/${runId}` : null,
    () => getRun(runId)
  );

  function downloadMarkdown() {
    if (!run?.report?.markdown) return;
    const blob = new Blob([run.report.markdown], { type: "text/markdown" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${run.report.slug}.md`;
    a.click();
    URL.revokeObjectURL(url);
  }

  return (
    <div
      className="grid h-[calc(100vh-56px)]"
      style={{ gridTemplateColumns: "180px 1fr" }}
    >
      {/* Left sidebar — run list */}
      <aside className="border-r border-slate-800 overflow-y-auto bg-slate-950">
        <div className="px-3 py-3 border-b border-slate-800">
          <p className="text-xs text-slate-500 uppercase tracking-wider">Past Runs</p>
        </div>
        <RunList runs={runs} />
      </aside>

      {/* Right — report + chat */}
      <div className="flex flex-col overflow-hidden">
        {/* Report scroll area */}
        <div className="flex-1 overflow-y-auto min-h-0">
          {isLoading && (
            <div className="flex items-center justify-center h-32 text-slate-500">Loading…</div>
          )}
          {run && !run.report && (
            <div className="p-8 text-slate-500">
              {run.status === "running" || run.status === "pending"
                ? "Analysis still running…"
                : "No report available for this run."}
            </div>
          )}
          {run?.report && (
            <div className="p-8">
              <div className="flex items-center justify-between mb-6">
                <div>
                  <h1 className="text-xl font-semibold text-slate-100">{run.location}</h1>
                  <p className="text-xs text-slate-500 mt-1">
                    {new Date(run.created_at).toLocaleString("en-PH")}
                  </p>
                </div>
                <button
                  onClick={downloadMarkdown}
                  className="px-3 py-1.5 text-xs border border-slate-700 text-slate-400 rounded hover:border-slate-500 transition-colors"
                >
                  ↓ Download .md
                </button>
              </div>
              <div className="prose prose-invert max-w-none prose-headings:text-amber-400 prose-a:text-amber-400 prose-strong:text-slate-200 prose-code:text-emerald-400 prose-pre:bg-slate-900 prose-table:text-sm">
                <ReactMarkdown remarkPlugins={[remarkGfm]}>
                  {run.report.markdown}
                </ReactMarkdown>
              </div>
            </div>
          )}
        </div>

        {/* Bottom-pinned chat */}
        <div className="h-72 border-t border-slate-800 shrink-0">
          <ChatPanel
            runId={runId}
            placeholder={`Ask about ${run?.location ?? "this report"}…`}
          />
        </div>
      </div>
    </div>
  );
}
