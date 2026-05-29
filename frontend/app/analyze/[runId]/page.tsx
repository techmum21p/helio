"use client";
import { useRouter, useParams } from "next/navigation";
import RunProgress from "@/components/run-progress";

export default function AnalyzeRunPage() {
  const { runId } = useParams<{ runId: string }>();
  const router = useRouter();

  function handleComplete(id: string) {
    setTimeout(() => router.push(`/reports/${id}`), 1500);
  }

  function handleFailed(error: string | null) {
    console.error("Pipeline failed:", error);
  }

  return (
    <div className="max-w-md mx-auto px-6 py-16">
      <h1 className="text-lg font-medium text-slate-300 mb-2">Running analysis…</h1>
      <p className="text-xs text-slate-500 mb-8 font-mono">{runId}</p>
      <RunProgress runId={runId} onComplete={handleComplete} onFailed={handleFailed} />
    </div>
  );
}
