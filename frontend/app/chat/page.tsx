"use client";
import { useState } from "react";
import useSWR from "swr";
import type { Run } from "@/lib/types";
import { getRuns } from "@/lib/api";
import ChatPanel from "@/components/chat-panel";

export default function ChatPage() {
  const [contextRunId, setContextRunId] = useState<string | null>(null);
  const { data: runs = [] } = useSWR<Run[]>("runs", () => getRuns(50));

  return (
    <div
      className="h-[calc(100vh-56px)] grid"
      style={{ gridTemplateColumns: "1fr 220px" }}
    >
      {/* Chat panel */}
      <div className="border-r border-slate-800 overflow-hidden">
        <ChatPanel
          runId={contextRunId}
          placeholder={
            contextRunId
              ? "Ask about this run's municipalities…"
              : "Ask about any solar opportunity across all analyzed locations…"
          }
        />
      </div>

      {/* Run context switcher */}
      <aside className="overflow-y-auto bg-slate-950">
        <div className="px-3 py-3 border-b border-slate-800">
          <p className="text-xs text-slate-500 uppercase tracking-wider">Context</p>
        </div>
        <button
          className={`w-full text-left px-3 py-3 text-sm border-b border-slate-800 transition-colors hover:bg-slate-900 ${
            contextRunId === null ? "text-amber-400 bg-slate-900 border-l-2 border-amber-500" : "text-slate-400"
          }`}
          onClick={() => setContextRunId(null)}
        >
          Global KB
          <p className="text-xs text-slate-600 mt-0.5">All analyzed locations</p>
        </button>
        {runs.map((run) => (
          <button
            key={run.id}
            className={`w-full text-left px-3 py-3 border-b border-slate-800 transition-colors hover:bg-slate-900 ${
              contextRunId === run.id ? "bg-slate-900 border-l-2 border-amber-500" : ""
            }`}
            onClick={() => setContextRunId(run.id)}
          >
            <p className="text-xs text-slate-300 font-medium line-clamp-2">{run.location}</p>
            <p className="text-xs text-slate-600 mt-0.5">
              {new Date(run.created_at).toLocaleDateString("en-PH", { month: "short", day: "numeric" })}
            </p>
          </button>
        ))}
      </aside>
    </div>
  );
}
