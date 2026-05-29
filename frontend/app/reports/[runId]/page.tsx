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
      className="grid h-full"
      style={{ gridTemplateColumns: "180px 1fr" }}
    >
      {/* Left sidebar — run list */}
      <aside className="border-r border-stone-200 overflow-y-auto bg-stone-50">
        <div className="px-3 py-3 border-b border-stone-200">
          <p className="text-xs font-bold tracking-widest uppercase text-stone-400">Past Runs</p>
        </div>
        <RunList runs={runs} />
      </aside>

      {/* Right — report + chat */}
      <div className="flex flex-col overflow-hidden bg-white">
        {/* Report scroll area */}
        <div className="flex-1 overflow-y-auto min-h-0">
          {isLoading && (
            <div className="flex items-center justify-center h-32 text-stone-400">Loading…</div>
          )}
          {run && !run.report && (
            <div className="p-8 text-stone-500">
              {run.status === "running" || run.status === "pending"
                ? "Analysis still running…"
                : "No report available for this run."}
            </div>
          )}
          {run?.report && (
            <div className="p-8">
              <div className="border-b border-stone-200 px-8 py-5 -mx-8 -mt-8 mb-6 flex items-center justify-between">
                <div>
                  <h1 className="text-xl font-bold text-stone-900">{run.location}</h1>
                  <p className="text-xs text-stone-400 mt-1">
                    {new Date(run.created_at).toLocaleString("en-PH")}
                  </p>
                </div>
                <button
                  onClick={downloadMarkdown}
                  className="px-3 py-1.5 text-xs border border-stone-300 text-stone-500 rounded-md hover:border-stone-400 bg-white transition-colors"
                >
                  ↓ Download .md
                </button>
              </div>
              <div className="prose max-w-none">
                <ReactMarkdown remarkPlugins={[remarkGfm]}>
                  {run.report.markdown}
                </ReactMarkdown>
              </div>
            </div>
          )}
        </div>

        {/* Bottom-pinned chat */}
        <div className="h-72 border-t border-stone-200 shrink-0">
          <ChatPanel
            runId={runId}
            placeholder={`Ask about ${run?.location ?? "this report"}…`}
          />
        </div>
      </div>
    </div>
  );
}
