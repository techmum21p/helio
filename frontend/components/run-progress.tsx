"use client";
import { useEffect, useState } from "react";
import type { StepEvent } from "@/lib/types";
import { openRunStream } from "@/lib/api";

const PIPELINE_STEPS = [
  { key: "geo_scoring",  label: "Geo Scoring",      description: "Loading pre-computed scores" },
  { key: "web_intel",    label: "Web Intelligence",  description: "Fetching business & market data" },
  { key: "synthesis",    label: "Synthesis",         description: "Combining geo + web intelligence" },
  { key: "report_gen",   label: "Report Generation", description: "Writing detailed markdown report" },
  { key: "update_kb",    label: "Knowledge Base",    description: "Indexing report into RAG store" },
];

type StepStatus = "waiting" | "running" | "done" | "failed";

interface Props {
  runId: string;
  onComplete?: (runId: string) => void;
  onFailed?: (error: string | null) => void;
}

export default function RunProgress({ runId, onComplete, onFailed }: Props) {
  const [stepStates, setStepStates] = useState<Record<string, StepStatus>>({});
  const [elapsedMs, setElapsedMs] = useState<Record<string, number>>({});
  const [terminated, setTerminated] = useState(false);

  useEffect(() => {
    if (!runId) return;
    const es = openRunStream(runId);
    es.onmessage = (e) => {
      let event: StepEvent;
      try { event = JSON.parse(e.data); } catch { return; }
      if (event.step === "complete") {
        setTerminated(true); es.close(); onComplete?.(runId); return;
      }
      if (event.step === "failed") {
        setStepStates((prev) => ({ ...prev, [event.step]: "failed" }));
        setTerminated(true); es.close(); onFailed?.(event.error ?? null); return;
      }
      setStepStates((prev) => ({ ...prev, [event.step]: event.status as StepStatus }));
      if (event.elapsed_ms) setElapsedMs((prev) => ({ ...prev, [event.step]: event.elapsed_ms }));
    };
    es.onerror = () => { if (!terminated) es.close(); };
    return () => es.close();
  }, [runId]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className="space-y-3">
      {PIPELINE_STEPS.map((step) => {
        const status: StepStatus = stepStates[step.key] ?? "waiting";
        const ms = elapsedMs[step.key];
        return (
          <div key={step.key} className="flex items-start gap-3">
            <div className="mt-0.5 shrink-0">
              {status === "done"    && <div className="w-5 h-5 rounded-full bg-emerald-500 flex items-center justify-center text-white text-xs">✓</div>}
              {status === "running" && <div className="w-5 h-5 rounded-full border-2 border-amber-500 border-t-transparent animate-spin" />}
              {status === "failed"  && <div className="w-5 h-5 rounded-full bg-red-500 flex items-center justify-center text-white text-xs">✕</div>}
              {status === "waiting" && <div className="w-5 h-5 rounded-full border border-stone-300 bg-stone-100" />}
            </div>
            <div>
              <p className={`text-sm font-medium ${
                status === "running" ? "text-amber-600" :
                status === "done"    ? "text-stone-700" :
                status === "failed"  ? "text-red-500"   : "text-stone-400"
              }`}>
                {step.label}
                {status === "done" && ms && (
                  <span className="ml-2 text-xs text-stone-400 font-normal">{(ms / 1000).toFixed(1)}s</span>
                )}
              </p>
              {status === "running" && <p className="text-xs text-stone-400">{step.description}</p>}
            </div>
          </div>
        );
      })}
    </div>
  );
}
