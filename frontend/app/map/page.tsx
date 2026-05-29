import { redirect } from "next/navigation";
import { getRuns } from "@/lib/api";

export default async function MapIndexPage() {
  let runs;
  try { runs = await getRuns(1); } catch { runs = []; }

  if (runs.length > 0) redirect(`/map/${runs[0].id}`);

  return (
    <div className="flex items-center justify-center flex-1">
      <div className="text-center">
        <p className="text-stone-400 mb-4 text-sm">No analyses yet.</p>
        <p className="text-stone-500 text-xs">Select a province in the sidebar and click ▶ Analyze.</p>
      </div>
    </div>
  );
}
