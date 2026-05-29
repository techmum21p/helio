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
    <div className="flex flex-col h-full">
      {/* Filter bar */}
      <div className="flex items-center gap-3 border-b border-stone-200 bg-white px-4 py-3 shrink-0">
        <select
          className="bg-stone-50 border border-stone-200 text-stone-700 rounded-md text-sm px-2 py-1.5 focus:outline-none focus:border-amber-400"
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
          className="bg-stone-50 border border-stone-200 text-stone-700 rounded-md text-sm px-2 py-1.5 focus:outline-none focus:border-amber-400 w-48"
          value={searchFilter}
          onChange={(e) => { setSearchFilter(e.target.value); setSelectedId(null); }}
        />
        <label className="flex items-center gap-1.5 text-sm text-stone-500 cursor-pointer">
          <span>Min score</span>
          <input
            type="range" min={0} max={1} step={0.05}
            value={minScore}
            onChange={(e) => setMinScore(Number(e.target.value))}
            className="w-24 accent-amber-500"
          />
          <span className="text-amber-600 tabular-nums w-8">{minScore.toFixed(2)}</span>
        </label>
        <div className="ml-auto flex items-center gap-2">
          <span className="text-stone-400 text-xs">{filtered.length.toLocaleString()} results</span>
          <button
            className={`px-3 py-1.5 text-xs rounded border transition-colors ${
              showMap
                ? "border-amber-500 text-amber-600 bg-amber-50"
                : "border-stone-300 text-stone-500 hover:border-stone-400"
            }`}
            onClick={() => setShowMap((v) => !v)}
          >
            {showMap ? "Hide Map" : "Show Map"}
          </button>
        </div>
      </div>

      {/* Map panel */}
      {showMap && (
        <div className="h-64 shrink-0 border-b border-stone-200">
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
          <div className="flex items-center justify-center h-32 text-stone-400">Loading…</div>
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
