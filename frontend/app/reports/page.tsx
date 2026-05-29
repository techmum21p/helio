import { redirect } from "next/navigation";
import { getRuns } from "@/lib/api";
import type { Run } from "@/lib/types";
import Link from "next/link";

export default async function ReportsIndexPage() {
  let runs: Run[];
  try { runs = await getRuns(1); } catch { runs = []; }

  if (runs.length > 0) redirect(`/reports/${runs[0].id}`);

  return (
    <div className="flex items-center justify-center h-[calc(100vh-56px)]">
      <div className="text-center">
        <p className="text-slate-400 mb-4">No reports yet.</p>
        <Link href="/analyze" className="px-4 py-2 bg-amber-500 text-slate-950 font-semibold rounded hover:bg-amber-400 transition-colors">
          Run your first analysis
        </Link>
      </div>
    </div>
  );
}
