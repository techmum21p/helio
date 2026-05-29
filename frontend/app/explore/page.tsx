"use client";
import { useState, useMemo } from "react";
import useSWR from "swr";
import dynamic from "next/dynamic";
import type { Municipality, Province } from "@/lib/types";
import { getMunicipalities, getProvinces } from "@/lib/api";
import MunicipalityTable from "@/components/municipality-table";

const MapView = dynamic(() => import("@/components/map-view"), { ssr: false });

export default function ExplorePage() {
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [showMap, setShowMap] = useState(false);
  const [provinceFilter, setProvinceFilter] = useState("");
  const [searchFilter, setSearchFilter] = useState("");
  const [minScore, setMinScore] = useState(0);

  const { data: municipalities = [], isLoading } = useSWR<Municipality[]>(
    "municipalities",
    () => getMunicipalities({ limit: 2000 })
  );
  const { data: provinces = [] } = useSWR<Province[]>("provinces", getProvinces);

  const filtered = useMemo(() => {
    return municipalities.filter((m) => {
      if (provinceFilter && m.province !== provinceFilter) return false;
      if (searchFilter && !m.name.toLowerCase().includes(searchFilter.toLowerCase())) return false;
      if (minScore > 0 && (m.geo_score ?? 0) < minScore) return false;
      return true;
    });
  }, [municipalities, provinceFilter, searchFilter, minScore]);

  function handleSelect(id: number) {
    setSelectedId((prev) => (prev === id ? null : id));
  }

  return (
    <div className="flex flex-col h-[calc(100vh-56px)]">
      {/* Filter bar */}
      <div className="flex items-center gap-3 px-4 py-3 border-b border-slate-800 bg-slate-950 shrink-0">
        <select
          className="bg-slate-900 border border-slate-700 text-slate-300 text-sm rounded px-2 py-1.5 focus:outline-none focus:border-amber-500"
          value={provinceFilter}
          onChange={(e) => { setProvinceFilter(e.target.value); setSelectedId(null); }}
        >
          <option value="">All provinces</option>
          {provinces.map((p) => (
            <option key={p.name} value={p.name}>{p.name}</option>
          ))}
        </select>
        <input
          type="text"
          placeholder="Search municipality…"
          className="bg-slate-900 border border-slate-700 text-slate-300 text-sm rounded px-2 py-1.5 focus:outline-none focus:border-amber-500 w-48"
          value={searchFilter}
          onChange={(e) => { setSearchFilter(e.target.value); setSelectedId(null); }}
        />
        <label className="flex items-center gap-1.5 text-sm text-slate-400 cursor-pointer">
          <span>Min score</span>
          <input
            type="range" min={0} max={1} step={0.05}
            value={minScore}
            onChange={(e) => setMinScore(Number(e.target.value))}
            className="w-24 accent-amber-400"
          />
          <span className="text-amber-400 tabular-nums w-8">{minScore.toFixed(2)}</span>
        </label>
        <div className="ml-auto flex items-center gap-2">
          <span className="text-slate-500 text-xs">{filtered.length.toLocaleString()} results</span>
          <button
            className={`px-3 py-1.5 text-xs rounded border transition-colors ${
              showMap
                ? "border-amber-500 text-amber-400 bg-amber-500/10"
                : "border-slate-700 text-slate-400 hover:border-slate-500"
            }`}
            onClick={() => setShowMap((v) => !v)}
          >
            {showMap ? "Hide Map" : "Show Map"}
          </button>
        </div>
      </div>

      {/* Map panel */}
      {showMap && (
        <div className="h-64 shrink-0 border-b border-slate-800">
          <MapView
            municipalities={filtered}
            selectedId={selectedId}
            onSelect={handleSelect}
          />
        </div>
      )}

      {/* Table */}
      <div className="flex-1 overflow-y-auto">
        {isLoading ? (
          <div className="flex items-center justify-center h-32 text-slate-500">Loading…</div>
        ) : (
          <MunicipalityTable
            municipalities={filtered}
            selectedId={selectedId}
            onSelect={handleSelect}
          />
        )}
      </div>
    </div>
  );
}
