"use client";
import { useState } from "react";
import { useRouter } from "next/navigation";
import useSWR from "swr";
import type { Province, Municipality } from "@/lib/types";
import { getProvinces, getMunicipalities, createRun } from "@/lib/api";

export default function SidebarPipelineCard() {
  const router = useRouter();
  const [province, setProvince] = useState("");
  const [selected, setSelected] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const { data: provinces = [] } = useSWR<Province[]>("provinces", getProvinces);
  const { data: municipalities = [] } = useSWR<Municipality[]>(
    province ? `municipalities/${province}` : null,
    () => getMunicipalities({ province, limit: 2000 })
  );

  function toggleMuni(name: string) {
    setSelected((prev) =>
      prev.includes(name) ? prev.filter((n) => n !== name) : [...prev, name]
    );
  }

  async function handleAnalyze() {
    if (!province) { setError("Select a province first."); return; }
    setError("");
    setLoading(true);
    try {
      let location: string;
      if (selected.length === 1) {
        location = `${selected[0]}, ${province}`;
      } else if (selected.length > 1) {
        location = `${selected.join("|")}, ${province}`;
      } else {
        location = province;
      }
      const { run_id } = await createRun(location);
      router.push(`/analyze/${run_id}`);
    } catch {
      setError("Failed to start analysis.");
      setLoading(false);
    }
  }

  return (
    <div className="rounded-lg border border-stone-200 bg-white shadow-sm px-3 py-3 shrink-0">
      <p className="text-[10px] font-bold tracking-widest uppercase text-stone-400 mb-2.5">
        Run Pipeline
      </p>

      {/* Province */}
      <label className="block text-[10px] font-semibold text-stone-500 uppercase tracking-wide mb-1">
        Province
      </label>
      <select
        className="w-full bg-stone-50 border border-stone-200 rounded-md px-2 py-1.5 text-xs text-stone-700 mb-2.5 focus:outline-none focus:border-amber-400 appearance-none"
        value={province}
        onChange={(e) => { setProvince(e.target.value); setSelected([]); }}
      >
        <option value="">Select province…</option>
        {provinces.map((p) => (
          <option key={p.name} value={p.name}>{p.name}</option>
        ))}
      </select>

      {/* Municipality checklist */}
      {province && municipalities.length > 0 && (
        <>
          <label className="block text-[10px] font-semibold text-stone-500 uppercase tracking-wide mb-1">
            Municipalities <span className="normal-case font-normal text-stone-400">(optional)</span>
          </label>
          <div className="border border-stone-200 rounded-md max-h-28 overflow-y-auto mb-1.5 bg-stone-50">
            {municipalities.map((m) => (
              <label
                key={m.id}
                className={`flex items-center gap-2 px-2.5 py-1.5 border-b border-stone-100 last:border-0 cursor-pointer text-xs hover:bg-stone-100 ${
                  selected.includes(m.name) ? "bg-amber-50" : ""
                }`}
              >
                <input
                  type="checkbox"
                  checked={selected.includes(m.name)}
                  onChange={() => toggleMuni(m.name)}
                  className="accent-amber-500 shrink-0"
                />
                <span className="flex-1 text-stone-700 truncate">{m.name}</span>
                {m.geo_score !== null && (
                  <span className="text-amber-600 font-semibold tabular-nums">
                    {m.geo_score.toFixed(2)}
                  </span>
                )}
              </label>
            ))}
          </div>
          <p className="text-[10px] text-stone-400 mb-2">
            {selected.length === 0
              ? "Whole province"
              : `${selected.length} selected`}
          </p>
        </>
      )}

      {error && <p className="text-[10px] text-red-500 mb-2">{error}</p>}

      <button
        onClick={handleAnalyze}
        disabled={loading || !province}
        className="w-full bg-amber-600 hover:bg-amber-700 disabled:opacity-40 disabled:cursor-not-allowed text-white text-xs font-bold py-2 rounded-md transition-colors tracking-wide"
      >
        {loading ? "Starting…" : "▶ Analyze"}
      </button>
    </div>
  );
}
