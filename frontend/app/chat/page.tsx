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
      className="h-full grid"
      style={{ gridTemplateColumns: "1fr 220px" }}
    >
      {/* Chat panel */}
      <div className="border-r border-stone-200 overflow-hidden">
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
      <aside className="overflow-y-auto bg-stone-50">
        <div className="px-3 py-3 border-b border-stone-200">
          <p className="text-xs font-bold tracking-widest uppercase text-stone-400">Context</p>
        </div>
        <button
          className={`w-full text-left px-3 py-3 text-sm border-b border-stone-200 transition-colors ${
            contextRunId === null
              ? "bg-amber-50 border-l-2 border-amber-500 text-amber-800 font-semibold"
              : "text-stone-600 hover:bg-stone-100"
          }`}
          onClick={() => setContextRunId(null)}
        >
          Global KB
          <p className="text-xs text-stone-400 mt-0.5">All analyzed locations</p>
        </button>
        {runs.map((run) => (
          <button
            key={run.id}
            className={`w-full text-left px-3 py-3 border-b border-stone-200 transition-colors hover:bg-stone-100 ${
              contextRunId === run.id ? "bg-amber-50 border-l-2 border-amber-500" : ""
            }`}
            onClick={() => setContextRunId(run.id)}
          >
            <p className="text-xs font-semibold text-stone-700 line-clamp-2">{run.location}</p>
            <p className="text-xs text-stone-400 mt-0.5">
              {new Date(run.created_at).toLocaleDateString("en-PH", { month: "short", day: "numeric" })}
            </p>
          </button>
        ))}
      </aside>
    </div>
  );
}
