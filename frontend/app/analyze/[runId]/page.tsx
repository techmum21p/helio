"use client";
import { useRouter, useParams } from "next/navigation";
import RunProgress from "@/components/run-progress";

export default function AnalyzeRunPage() {
  const { runId } = useParams<{ runId: string }>();
  const router = useRouter();

  function handleComplete(id: string) {
    setTimeout(() => router.push(`/map/${id}`), 1200);
  }

  function handleFailed(error: string | null) {
    console.error("Pipeline failed:", error);
  }

  return (
    <div className="flex items-center justify-center flex-1">
      <div className="w-full max-w-sm px-6 py-12">
        <h1 className="text-base font-semibold text-stone-700 mb-1">Running analysis…</h1>
        <p className="text-xs text-stone-400 mb-8 font-mono">{runId}</p>
        <RunProgress runId={runId} onComplete={handleComplete} onFailed={handleFailed} />
      </div>
    </div>
  );
}
