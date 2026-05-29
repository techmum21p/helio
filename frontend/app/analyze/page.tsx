"use client";
import { useState } from "react";
import { useRouter } from "next/navigation";
import useSWR from "swr";
import type { Province, Municipality } from "@/lib/types";
import { getProvinces, getMunicipalities, createRun } from "@/lib/api";

export default function AnalyzePage() {
  const router = useRouter();
  const [selectedProvince, setSelectedProvince] = useState("");
  const [selectedMunicipalities, setSelectedMunicipalities] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const { data: provinces = [] } = useSWR<Province[]>("provinces", getProvinces);
  const { data: municipalities = [] } = useSWR<Municipality[]>(
    selectedProvince ? `municipalities/${selectedProvince}` : null,
    () => getMunicipalities({ province: selectedProvince, limit: 2000 })
  );

  function toggleMunicipality(name: string) {
    setSelectedMunicipalities((prev) =>
      prev.includes(name) ? prev.filter((m) => m !== name) : [...prev, name]
    );
  }

  async function handleAnalyze() {
    if (!selectedProvince && selectedMunicipalities.length === 0) {
      setError("Select a province or at least one municipality.");
      return;
    }
    setError("");
    setLoading(true);
    try {
      let location: string;
      if (selectedMunicipalities.length === 1) {
        location = `${selectedMunicipalities[0]}, ${selectedProvince}`;
      } else if (selectedMunicipalities.length > 1) {
        location = `${selectedMunicipalities.join("|")}, ${selectedProvince}`;
      } else {
        location = selectedProvince;
      }
      const { run_id } = await createRun(location);
      router.push(`/analyze/${run_id}`);
    } catch (e) {
      setError(String(e));
      setLoading(false);
    }
  }

  return (
    <div className="max-w-xl mx-auto px-6 py-12">
      <h1 className="text-2xl font-semibold text-slate-100 mb-2">Analyze Location</h1>
      <p className="text-slate-400 text-sm mb-8">Run the full 5-step pipeline for a province or specific municipalities.</p>

      <div className="space-y-6">
        <div>
          <label className="block text-xs text-slate-500 uppercase tracking-wider mb-2">Province</label>
          <select
            className="w-full bg-slate-900 border border-slate-700 text-slate-200 rounded px-3 py-2 focus:outline-none focus:border-amber-500"
            value={selectedProvince}
            onChange={(e) => { setSelectedProvince(e.target.value); setSelectedMunicipalities([]); }}
          >
            <option value="">Select province…</option>
            {provinces.map((p) => <option key={p.name} value={p.name}>{p.name}</option>)}
          </select>
        </div>

        {selectedProvince && municipalities.length > 0 && (
          <div>
            <label className="block text-xs text-slate-500 uppercase tracking-wider mb-2">
              Municipalities <span className="text-slate-600 normal-case">(optional — leave empty to analyze whole province)</span>
            </label>
            <div className="max-h-48 overflow-y-auto border border-slate-700 rounded divide-y divide-slate-800">
              {municipalities.map((m) => (
                <label key={m.id} className="flex items-center gap-3 px-3 py-2 hover:bg-slate-800 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={selectedMunicipalities.includes(m.name)}
                    onChange={() => toggleMunicipality(m.name)}
                    className="accent-amber-400"
                  />
                  <span className="text-slate-300 text-sm">{m.name}</span>
                  {m.geo_score !== null && (
                    <span className="ml-auto text-amber-400 text-xs tabular-nums">{m.geo_score.toFixed(3)}</span>
                  )}
                </label>
              ))}
            </div>
          </div>
        )}

        {error && <p className="text-red-400 text-sm">{error}</p>}

        <button
          className="w-full py-2.5 bg-amber-500 hover:bg-amber-400 disabled:opacity-40 disabled:cursor-not-allowed text-slate-950 font-semibold rounded transition-colors"
          onClick={handleAnalyze}
          disabled={loading || !selectedProvince}
        >
          {loading ? "Starting…" : "Analyze"}
        </button>
      </div>
    </div>
  );
}
