"use client";
import { useState, useMemo } from "react";
import type { Municipality } from "@/lib/types";
import { getTier } from "@/lib/types";
import ScoreBar from "./score-bar";
import TierBadge from "./tier-badge";

const PAGE_SIZE = 50;

type SortKey = "geo_score" | "solar_norm" | "income_score" | "pop_density_norm" | "name";

interface Props {
  municipalities: Municipality[];
  selectedId: number | null;
  onSelect: (id: number) => void;
}

export default function MunicipalityTable({ municipalities, selectedId, onSelect }: Props) {
  const [sortKey, setSortKey] = useState<SortKey>("geo_score");
  const [sortAsc, setSortAsc] = useState(false);
  const [page, setPage] = useState(0);

  const sorted = useMemo(() => {
    return [...municipalities].sort((a, b) => {
      const av = a[sortKey] ?? -1;
      const bv = b[sortKey] ?? -1;
      if (typeof av === "string") return sortAsc ? av.localeCompare(bv as string) : (bv as string).localeCompare(av);
      return sortAsc ? (av as number) - (bv as number) : (bv as number) - (av as number);
    });
  }, [municipalities, sortKey, sortAsc]);

  const totalPages = Math.ceil(sorted.length / PAGE_SIZE);
  const page_items = sorted.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);

  function toggleSort(key: SortKey) {
    if (sortKey === key) setSortAsc((a) => !a);
    else { setSortKey(key); setSortAsc(false); }
    setPage(0);
  }

  function ColHead({ k, label }: { k: SortKey; label: string }) {
    const active = sortKey === k;
    return (
      <th
        className="px-3 py-2 text-left text-xs text-stone-500 font-medium uppercase tracking-wider cursor-pointer select-none hover:text-stone-700"
        onClick={() => toggleSort(k)}
      >
        {label} {active ? (sortAsc ? "↑" : "↓") : ""}
      </th>
    );
  }

  return (
    <div className="flex flex-col gap-0">
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="border-b border-stone-200 sticky top-0 bg-stone-50">
            <tr>
              <th className="px-3 py-2 text-left text-xs text-stone-500 font-medium uppercase tracking-wider w-10">#</th>
              <ColHead k="name" label="Municipality" />
              <th className="px-3 py-2 text-left text-xs text-stone-500 font-medium uppercase tracking-wider">Province</th>
              <ColHead k="solar_norm" label="Solar" />
              <ColHead k="income_score" label="Income" />
              <ColHead k="pop_density_norm" label="Pop" />
              <ColHead k="geo_score" label="Geo Score" />
              <th className="px-3 py-2 text-left text-xs text-stone-500 font-medium uppercase tracking-wider">Tier</th>
            </tr>
          </thead>
          <tbody>
            {page_items.map((m, idx) => {
              const rank = page * PAGE_SIZE + idx + 1;
              const expanded = selectedId === m.id;
              return (
                <>
                  <tr
                    key={m.id}
                    className={`border-b border-stone-100 cursor-pointer transition-colors ${
                      expanded ? "bg-amber-50 border-amber-200" : "hover:bg-amber-50"
                    }`}
                    onClick={() => onSelect(expanded ? -1 : m.id)}
                  >
                    <td className="px-3 py-2.5 text-stone-400 tabular-nums">{rank}</td>
                    <td className="px-3 py-2.5 text-stone-800 font-medium">{m.name}</td>
                    <td className="px-3 py-2.5 text-stone-500">{m.province}</td>
                    <td className="px-3 py-2.5 text-amber-600 tabular-nums">{m.solar_norm?.toFixed(2) ?? "—"}</td>
                    <td className="px-3 py-2.5 text-emerald-600 tabular-nums">{m.income_score?.toFixed(2) ?? "—"}</td>
                    <td className="px-3 py-2.5 text-violet-600 tabular-nums">{m.pop_density_norm?.toFixed(2) ?? "—"}</td>
                    <td className="px-3 py-2.5 text-amber-600 font-semibold tabular-nums">
                      {m.geo_score?.toFixed(3) ?? "—"}
                    </td>
                    <td className="px-3 py-2.5">
                      <TierBadge tier={getTier(m.geo_score)} />
                    </td>
                  </tr>
                  {expanded && (
                    <tr key={`${m.id}-expanded`} className="bg-amber-50 border-b border-amber-200">
                      <td colSpan={8} className="px-6 py-3">
                        <div className="max-w-sm">
                          <p className="text-xs text-stone-400 mb-2">Score breakdown — {m.name}, {m.province}</p>
                          <ScoreBar
                            solar={m.solar_norm}
                            income={m.income_score}
                            popDensity={m.pop_density_norm}
                            showLabels
                          />
                        </div>
                      </td>
                    </tr>
                  )}
                </>
              );
            })}
          </tbody>
        </table>
      </div>

      {/* Pagination */}
      <div className="flex items-center justify-between px-4 py-3 border-t border-stone-200 text-xs text-stone-500">
        <span>{sorted.length.toLocaleString()} municipalities</span>
        <div className="flex items-center gap-2">
          <button
            className="px-2 py-1 rounded bg-stone-100 hover:bg-stone-200 disabled:opacity-30 disabled:cursor-not-allowed"
            onClick={() => setPage((p) => Math.max(0, p - 1))}
            disabled={page === 0}
          >
            ←
          </button>
          <span>Page {page + 1} / {totalPages}</span>
          <button
            className="px-2 py-1 rounded bg-stone-100 hover:bg-stone-200 disabled:opacity-30 disabled:cursor-not-allowed"
            onClick={() => setPage((p) => Math.min(totalPages - 1, p + 1))}
            disabled={page >= totalPages - 1}
          >
            →
          </button>
        </div>
      </div>
    </div>
  );
}
