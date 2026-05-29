# Helio Frontend Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix 7 reported bugs and collapse the nav from 5 pages to 3 (Map & Scores, Reports, Chat), matching the Streamlit version's structure.

**Architecture:** Backend fix in `api/routers/runs.py` + backfill script to populate lat/lon for all municipalities. Frontend fixes across sidebar, reports index, map page, and chat page. No new API endpoints needed.

**Tech Stack:** Python/FastAPI (backend), Next.js 14 App Router, React, Leaflet (map), useSWR (data fetching), Tailwind CSS.

---

## File Map

| File | Change |
|------|--------|
| `api/routers/runs.py` | Parse `geo_geojson` in `_persist_run_results`, backfill `municipalities.lat/lon` |
| `scripts/backfill_coords.py` | New — one-time script to populate lat/lon for all 1,622 municipalities |
| `frontend/components/sidebar.tsx` | Remove Explore + Admin from `NAV_LINKS` |
| `frontend/app/reports/page.tsx` | Replace hardcoded "No reports yet." with a live run list |
| `frontend/app/map/[runId]/page.tsx` | Add click-to-expand town cards showing assessment/opportunity/risk |
| `frontend/components/run-map-view.tsx` | Change zoom to 7, accept `center` prop computed from results |

---

## Task 1: Backfill lat/lon into municipalities table

**Files:**
- Modify: `api/routers/runs.py` (`_persist_run_results` function, lines 26–64)
- Create: `scripts/backfill_coords.py`

### Why this is broken
All 1,622 municipalities have `lat=NULL, lon=NULL` in `data/helio.db`. The pipeline computes coordinates in `geo_scoring.py` via `_municipality_coord(name, province)` and embeds them in `geo_geojson`, but `_persist_run_results` never writes them back to the DB. The map's `withCoords` filter (`r.lat !== null && r.lon !== null`) then drops every marker.

- [ ] **Step 1: Update `_persist_run_results` to save coords from geo_geojson**

Open `api/routers/runs.py`. Find `_persist_run_results`. Add the geo_geojson backfill block **after** the run_results loop (before the report insert):

```python
def _persist_run_results(run_id: str, result: dict) -> None:
    with get_db() as conn:
        error  = "; ".join(result.get("errors", [])) or None
        status = "failed" if error and not result.get("top_targets") else "done"
        conn.execute(
            "UPDATE runs SET status=?, completed_at=?, error=? WHERE id=?",
            (status, datetime.now(timezone.utc).isoformat(), error, run_id),
        )
        for t in result.get("top_targets", []):
            muni = conn.execute(
                "SELECT id FROM municipalities WHERE name=? AND province=?",
                (t.get("municipality", ""), t.get("province", "")),
            ).fetchone()
            conn.execute(
                """INSERT INTO run_results
                   (run_id, municipality_id, geo_score, web_score, final_score,
                    tier, assessment, opportunities, risks)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (run_id, muni["id"] if muni else None,
                 t.get("geo_score"), t.get("web_score"), t.get("final_score"),
                 t.get("tier"), t.get("assessment"),
                 json.dumps(t.get("opportunities", [])),
                 json.dumps(t.get("risks", []))),
            )

        # Backfill lat/lon into municipalities from geo_geojson
        if result.get("geo_geojson"):
            try:
                geo_data = json.loads(result["geo_geojson"])
                for feature in geo_data.get("features", []):
                    props = feature.get("properties", {})
                    geom  = feature.get("geometry", {})
                    if geom.get("type") != "Point":
                        continue
                    lon, lat = geom["coordinates"]
                    conn.execute(
                        """UPDATE municipalities SET lat=?, lon=?
                           WHERE name=? AND province=? AND lat IS NULL""",
                        (lat, lon, props.get("name", ""), props.get("province", "")),
                    )
            except Exception:
                pass  # coord backfill is best-effort; never fail a run over it

        if result.get("report_markdown"):
            loc  = (result.get("location", "unknown")
                    .lower().replace(", ", "_").replace(" ", "-").replace("|", "_"))
            slug = f"{loc}_{run_id[:6]}"
            conn.execute(
                """INSERT OR IGNORE INTO reports
                   (run_id, province, slug, markdown, file_path)
                   VALUES (?,?,?,?,?)""",
                (run_id, result.get("location"), slug,
                 result["report_markdown"], result.get("report_path", "")),
            )
```

- [ ] **Step 2: Create the one-time backfill script**

Create `scripts/backfill_coords.py`:

```python
"""One-time script: populate municipalities.lat/lon using the same deterministic
coord function used by the geo_scoring agent."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from agents.geo_scoring import _municipality_coord
from api.db import get_db

def main():
    with get_db() as conn:
        rows = conn.execute(
            "SELECT id, name, province FROM municipalities WHERE lat IS NULL"
        ).fetchall()
        if not rows:
            print("All municipalities already have coordinates.")
            return
        for r in rows:
            lat, lon = _municipality_coord(r["name"], r["province"])
            conn.execute(
                "UPDATE municipalities SET lat=?, lon=? WHERE id=?",
                (lat, lon, r["id"]),
            )
        print(f"Backfilled {len(rows)} municipalities.")

if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Run the backfill script**

```bash
cd /Users/aireesm4/Python_Projects/helio
source .venv_helios/bin/activate
python scripts/backfill_coords.py
```

Expected output:
```
Backfilled 1622 municipalities.
```

- [ ] **Step 4: Verify coords in DB**

```bash
python3 -c "
import sqlite3
conn = sqlite3.connect('data/helio.db')
conn.row_factory = sqlite3.Row
r = conn.execute('SELECT COUNT(*) as total, COUNT(lat) as with_lat FROM municipalities').fetchone()
print(f'Total: {r[\"total\"]}, With lat: {r[\"with_lat\"]}')
# also spot-check a run result
results = conn.execute('''
    SELECT m.lat, m.lon, rr.final_score
    FROM run_results rr
    LEFT JOIN municipalities m ON rr.municipality_id = m.id
    LIMIT 3
''').fetchall()
for res in results:
    print(dict(res))
"
```

Expected:
```
Total: 1622, With lat: 1622
{'lat': <float>, 'lon': <float>, 'final_score': <float>}
```

- [ ] **Step 5: Commit**

```bash
git add api/routers/runs.py scripts/backfill_coords.py
git commit -m "fix: backfill municipalities lat/lon — map markers were all NULL"
```

---

## Task 2: Remove Explore + Admin from sidebar nav

**Files:**
- Modify: `frontend/components/sidebar.tsx` (lines 9–15)

- [ ] **Step 1: Update NAV_LINKS**

In `frontend/components/sidebar.tsx`, replace the `NAV_LINKS` array:

```typescript
const NAV_LINKS = [
  { href: "/map",     icon: "🗺",  label: "Map & Scores" },
  { href: "/reports", icon: "📄",  label: "Reports"      },
  { href: "/chat",    icon: "💬",  label: "Chat"         },
];
```

- [ ] **Step 2: Verify visually**

Start the dev server if not already running:
```bash
cd /Users/aireesm4/Python_Projects/helio/frontend
npm run dev
```
Open http://localhost:3000 — confirm sidebar shows exactly 3 nav items: Map & Scores, Reports, Chat.

- [ ] **Step 3: Commit**

```bash
git add frontend/components/sidebar.tsx
git commit -m "feat: collapse nav to 3 pages (Map, Reports, Chat)"
```

---

## Task 3: Fix Reports index page

**Files:**
- Modify: `frontend/app/reports/page.tsx`

The current page ignores the DB entirely and always shows "No reports yet." regardless of how many runs exist.

- [ ] **Step 1: Replace the entire file**

Replace `frontend/app/reports/page.tsx` with:

```typescript
"use client";
import Link from "next/link";
import useSWR from "swr";
import type { Run } from "@/lib/types";
import { getRuns } from "@/lib/api";

export default function ReportsIndexPage() {
  const { data: runs = [], isLoading } = useSWR<Run[]>("runs-reports", () => getRuns(50));
  const doneRuns = runs.filter((r) => r.status === "done" && !r.location.startsWith("admin:"));

  if (isLoading) {
    return (
      <div className="flex items-center justify-center flex-1 text-stone-400 text-sm">
        Loading…
      </div>
    );
  }

  if (doneRuns.length === 0) {
    return (
      <div className="flex items-center justify-center flex-1">
        <div className="text-center">
          <p className="text-stone-400 mb-4 text-sm">No reports yet.</p>
          <Link
            href="/map"
            className="px-4 py-2 bg-amber-600 text-white text-sm font-semibold rounded-md hover:bg-amber-700 transition-colors"
          >
            Run your first analysis
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div className="max-w-2xl mx-auto px-6 py-8">
      <h1 className="text-lg font-bold text-stone-900 mb-6">Reports</h1>
      <div className="flex flex-col gap-3">
        {doneRuns.map((run) => (
          <Link
            key={run.id}
            href={`/reports/${run.id}`}
            className="block bg-white border border-stone-200 rounded-lg px-5 py-4 shadow-sm hover:border-amber-300 hover:shadow-md transition-all"
          >
            <div className="flex items-center justify-between">
              <div>
                <p className="font-semibold text-stone-900">{run.location}</p>
                <p className="text-xs text-stone-400 mt-0.5">
                  {new Date(run.created_at).toLocaleDateString("en-PH", {
                    month: "long",
                    day: "numeric",
                    year: "numeric",
                  })}
                </p>
              </div>
              <span className="text-xs font-semibold text-emerald-600 bg-emerald-50 border border-emerald-200 rounded-full px-2.5 py-0.5">
                ✓ Done
              </span>
            </div>
          </Link>
        ))}
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Verify in browser**

Navigate to http://localhost:3000/reports — should see a list of past runs (Laguna, Batangas, Cavite, Rizal). Clicking one should open the full report at `/reports/[runId]`.

- [ ] **Step 3: Commit**

```bash
git add frontend/app/reports/page.tsx
git commit -m "fix: reports index now lists past runs instead of hardcoded empty state"
```

---

## Task 4: Fix Map & Scores — expandable town cards

**Files:**
- Modify: `frontend/app/map/[runId]/page.tsx`

The right-sidebar cards currently show a 2-line-clamped assessment snippet but have no expand mechanic. Clicking does nothing.

- [ ] **Step 1: Add expand state and rewrite the card list in `MapScoresPage`**

Replace the entire file `frontend/app/map/[runId]/page.tsx` with:

```typescript
"use client";
import { useState } from "react";
import { useParams } from "next/navigation";
import useSWR from "swr";
import dynamic from "next/dynamic";
import type { RunDetail } from "@/lib/types";
import { getRun } from "@/lib/api";

const RunMapView = dynamic(() => import("@/components/run-map-view"), { ssr: false });

function TierBadge({ tier }: { tier: string }) {
  const styles: Record<string, string> = {
    HIGH:   "bg-emerald-100 text-emerald-800",
    MEDIUM: "bg-amber-100 text-amber-800",
    LOW:    "bg-red-100 text-red-700",
  };
  return (
    <span className={`inline-block text-[10px] font-bold px-1.5 py-0.5 rounded ${styles[tier] ?? "bg-stone-100 text-stone-600"}`}>
      {tier}
    </span>
  );
}

function ScoreBar({ score }: { score: number }) {
  return (
    <div className="h-1 bg-stone-100 rounded-full overflow-hidden mt-1.5">
      <div
        className="h-full rounded-full bg-gradient-to-r from-amber-500 to-amber-400"
        style={{ width: `${(score * 100).toFixed(1)}%` }}
      />
    </div>
  );
}

export default function MapScoresPage() {
  const { runId } = useParams<{ runId: string }>();
  const { data: run, isLoading } = useSWR<RunDetail>(
    runId ? `run/${runId}` : null,
    () => getRun(runId)
  );
  const [expandedId, setExpandedId] = useState<number | null>(null);

  if (isLoading) {
    return <div className="flex items-center justify-center flex-1 text-stone-400 text-sm">Loading…</div>;
  }
  if (!run) {
    return <div className="flex items-center justify-center flex-1 text-stone-400 text-sm">Run not found.</div>;
  }

  const results = run.results ?? [];
  const top = results[0];

  const avgSolar = results.length
    ? (results.reduce((s, r) => s + (r.geo_score ?? 0), 0) / results.length).toFixed(3)
    : "—";

  // Derive map center from result coordinates
  const withCoords = results.filter((r) => r.lat != null && r.lon != null);
  const mapCenter: [number, number] = withCoords.length > 0
    ? [
        withCoords.reduce((s, r) => s + r.lat!, 0) / withCoords.length,
        withCoords.reduce((s, r) => s + r.lon!, 0) / withCoords.length,
      ]
    : [12.8797, 121.774];

  return (
    <div className="flex flex-col h-full overflow-hidden">
      {/* Page header */}
      <div className="px-6 pt-5 pb-3 border-b border-stone-200 shrink-0">
        <h1 className="text-base font-bold text-stone-900">Map & Scores</h1>
        <p className="text-xs text-stone-500 mt-0.5">
          {run.location} · {results.length} municipalities ·{" "}
          {new Date(run.created_at).toLocaleDateString("en-PH", { month: "short", day: "numeric", year: "numeric" })}
        </p>
      </div>

      {/* Stat cards */}
      <div className="flex gap-3 px-6 py-3 border-b border-stone-200 shrink-0">
        {[
          { label: "Top Score",      value: top ? top.final_score.toFixed(3) : "—",  color: "text-amber-600" },
          { label: "Top Tier",       value: top?.tier ?? "—",                          color: "text-emerald-600" },
          { label: "Municipalities", value: String(results.length),                    color: "text-blue-600"   },
          { label: "Avg Geo Score",  value: avgSolar,                                  color: "text-stone-700"  },
        ].map(({ label, value, color }) => (
          <div key={label} className="flex-1 bg-white border border-stone-200 rounded-lg px-4 py-2.5 shadow-sm">
            <p className={`text-lg font-bold ${color}`}>{value}</p>
            <p className="text-[10px] text-stone-400 mt-0.5">{label}</p>
          </div>
        ))}
      </div>

      {/* Map + targets */}
      <div className="flex-1 grid overflow-hidden" style={{ gridTemplateColumns: "1fr 260px" }}>
        {/* Map */}
        <div className="overflow-hidden">
          {results.length > 0 ? (
            <RunMapView results={results} center={mapCenter} />
          ) : (
            <div className="flex items-center justify-center h-full text-stone-400 text-sm">
              No map data available.
            </div>
          )}
        </div>

        {/* Top targets list — expandable cards */}
        <div className="border-l border-stone-200 overflow-y-auto bg-stone-50 flex flex-col">
          <div className="px-3 py-2.5 border-b border-stone-200 shrink-0">
            <p className="text-[10px] font-bold tracking-widest uppercase text-stone-400">
              Top Targets — click to expand
            </p>
          </div>
          <div className="flex flex-col gap-1.5 p-2.5">
            {results.slice(0, 15).map((r) => {
              const expanded = expandedId === r.municipality_id;
              return (
                <div
                  key={r.municipality_id}
                  className={`border rounded-lg px-3 py-2 shadow-sm cursor-pointer transition-colors ${
                    expanded
                      ? "bg-amber-50 border-amber-300"
                      : "bg-white border-stone-200 hover:border-amber-200"
                  }`}
                  onClick={() => setExpandedId(expanded ? null : r.municipality_id)}
                >
                  <div className="flex items-center gap-1.5">
                    <span className="flex-1 text-xs font-semibold text-stone-900 truncate">
                      {r.municipality_name}
                    </span>
                    <TierBadge tier={r.tier} />
                    <span className="text-xs font-bold text-amber-600 tabular-nums shrink-0">
                      {r.final_score.toFixed(3)}
                    </span>
                  </div>
                  <ScoreBar score={r.final_score} />

                  {expanded && (
                    <div className="mt-2.5 pt-2.5 border-t border-amber-200 space-y-2">
                      {r.assessment && (
                        <div>
                          <p className="text-[9px] font-bold text-stone-400 uppercase tracking-widest mb-0.5">
                            Assessment
                          </p>
                          <p className="text-[11px] text-stone-600 leading-relaxed">
                            {r.assessment}
                          </p>
                        </div>
                      )}
                      {r.opportunities?.length > 0 && (
                        <div>
                          <p className="text-[9px] font-bold text-emerald-600 uppercase tracking-widest mb-0.5">
                            Opportunity
                          </p>
                          <p className="text-[11px] text-stone-600 leading-relaxed">
                            {r.opportunities[0]}
                          </p>
                        </div>
                      )}
                      {r.risks?.length > 0 && (
                        <div>
                          <p className="text-[9px] font-bold text-red-500 uppercase tracking-widest mb-0.5">
                            Risk
                          </p>
                          <p className="text-[11px] text-stone-600 leading-relaxed">
                            {r.risks[0]}
                          </p>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Verify in browser**

Navigate to http://localhost:3000/map — should redirect to the last run. Click any town card in the right sidebar — it should expand to show Assessment, Opportunity, Risk sections. Click again to collapse.

- [ ] **Step 3: Commit**

```bash
git add frontend/app/map/[runId]/page.tsx
git commit -m "feat: expandable town cards on Map & Scores page"
```

---

## Task 5: Fix map zoom and center

**Files:**
- Modify: `frontend/components/run-map-view.tsx`

Currently `zoom=10` and center is hardcoded to `[12.8797, 121.774]`. The `center` prop already exists but zoom is always 10, which is way too close — the Streamlit version used zoom 7.

- [ ] **Step 1: Change default zoom to 7 in RunMapView**

Replace `frontend/components/run-map-view.tsx` with:

```typescript
"use client";
import { useEffect } from "react";
import { MapContainer, TileLayer, CircleMarker, Popup, Tooltip } from "react-leaflet";
import type { RunResult } from "@/lib/types";
import { scoreColor, scoreRadius } from "@/lib/score-color";
import "leaflet/dist/leaflet.css";

interface Props {
  results: RunResult[];
  center?: [number, number];
}

export default function RunMapView({ results, center = [12.8797, 121.774] }: Props) {
  useEffect(() => {
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const L = require("leaflet");
    delete (L.Icon.Default.prototype as { _getIconUrl?: unknown })._getIconUrl;
    L.Icon.Default.mergeOptions({
      iconRetinaUrl: "/leaflet/marker-icon-2x.png",
      iconUrl:        "/leaflet/marker-icon.png",
      shadowUrl:      "/leaflet/marker-shadow.png",
    });
  }, []);

  const withCoords = results.filter((r) => r.lat !== null && r.lon !== null);

  return (
    <MapContainer center={center} zoom={7} className="w-full h-full">
      <TileLayer
        url="https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png"
        attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> &copy; <a href="https://carto.com/">CARTO</a>'
      />
      {withCoords.map((r) => {
        const color  = scoreColor(r.final_score);
        const radius = scoreRadius(r.final_score);
        return (
          <CircleMarker
            key={r.municipality_id}
            center={[r.lat!, r.lon!]}
            radius={radius}
            pathOptions={{ color, fillColor: color, fillOpacity: 0.75, weight: 1.5 }}
          >
            <Popup>
              <b>{r.municipality_name}</b><br />Score: {r.final_score.toFixed(3)}
            </Popup>
            <Tooltip>{r.municipality_name}: {r.final_score.toFixed(3)}</Tooltip>
          </CircleMarker>
        );
      })}
    </MapContainer>
  );
}
```

- [ ] **Step 2: Verify in browser**

Navigate to http://localhost:3000/map — the map should open at zoom 7 showing the Philippines region, with colored circle markers for each municipality in the run. Hovering a circle should show name + score.

- [ ] **Step 3: Commit**

```bash
git add frontend/components/run-map-view.tsx
git commit -m "fix: map zoom 7 + center on run results"
```

---

## Task 6: Fix Chat default context

**Files:**
- Modify: `frontend/app/chat/page.tsx`

Currently defaults to `null` ("Global KB"). Should default to the most recent completed run so the chat is immediately useful after running an analysis.

- [ ] **Step 1: Replace `frontend/app/chat/page.tsx`**

```typescript
"use client";
import { useState, useEffect } from "react";
import useSWR from "swr";
import type { Run } from "@/lib/types";
import { getRuns } from "@/lib/api";
import ChatPanel from "@/components/chat-panel";

export default function ChatPage() {
  const { data: runs = [] } = useSWR<Run[]>("runs", () => getRuns(50));
  const [contextRunId, setContextRunId] = useState<string | null>(null);
  const [initialized, setInitialized] = useState(false);

  // Auto-select the most recent completed run on first load
  useEffect(() => {
    if (!initialized && runs.length > 0) {
      const doneRun = runs.find((r) => r.status === "done" && !r.location.startsWith("admin:"));
      if (doneRun) setContextRunId(doneRun.id);
      setInitialized(true);
    }
  }, [runs, initialized]);

  const selectedRun = runs.find((r) => r.id === contextRunId) ?? null;

  return (
    <div
      className="h-full grid"
      style={{ gridTemplateColumns: "1fr 220px" }}
    >
      {/* Chat panel */}
      <div className="border-r border-stone-200 overflow-hidden">
        <ChatPanel
          runId={contextRunId}
          placeholder={
            selectedRun
              ? `Ask about ${selectedRun.location}…`
              : "Ask about any solar opportunity across all analyzed locations…"
          }
        />
      </div>

      {/* Run context switcher */}
      <aside className="overflow-y-auto bg-stone-50">
        <div className="px-3 py-3 border-b border-stone-200">
          <p className="text-xs font-bold tracking-widest uppercase text-stone-400">Context</p>
        </div>
        <button
          className={`w-full text-left px-3 py-3 text-sm border-b border-stone-200 transition-colors ${
            contextRunId === null
              ? "bg-amber-50 border-l-2 border-amber-500 text-amber-800 font-semibold"
              : "text-stone-600 hover:bg-stone-100"
          }`}
          onClick={() => setContextRunId(null)}
        >
          Global KB
          <p className="text-xs text-stone-400 mt-0.5">All analyzed locations</p>
        </button>
        {runs
          .filter((r) => r.status === "done" && !r.location.startsWith("admin:"))
          .map((run) => (
            <button
              key={run.id}
              className={`w-full text-left px-3 py-3 border-b border-stone-200 transition-colors hover:bg-stone-100 ${
                contextRunId === run.id ? "bg-amber-50 border-l-2 border-amber-500" : ""
              }`}
              onClick={() => setContextRunId(run.id)}
            >
              <p className="text-xs font-semibold text-stone-700 line-clamp-2">{run.location}</p>
              <p className="text-xs text-stone-400 mt-0.5">
                {new Date(run.created_at).toLocaleDateString("en-PH", {
                  month: "short",
                  day: "numeric",
                })}
              </p>
            </button>
          ))}
      </aside>
    </div>
  );
}
```

- [ ] **Step 2: Verify in browser**

Navigate to http://localhost:3000/chat — the right sidebar should auto-highlight the most recent completed run. The chat placeholder should say "Ask about [location]…". Clicking "Global KB" should switch context back.

Also confirm admin-tagged runs (`admin:refresh-scores`) are filtered out of the list.

- [ ] **Step 3: Commit**

```bash
git add frontend/app/chat/page.tsx
git commit -m "fix: chat defaults to most recent run context, hides admin runs"
```

---

## Self-Review

**Spec coverage check:**
- ✅ Nav collapsed to 3 pages → Task 2
- ✅ lat/lon backfill (map markers) → Task 1
- ✅ Expandable town cards → Task 4
- ✅ Map zoom 7 + center → Task 5
- ✅ Reports index page → Task 3
- ✅ Chat default context → Task 6
- ✅ "Maps & Scores nav does nothing" — this was caused by coords being null (no markers visible), which Task 1 + 5 fix. The nav routing itself is correct.

**Gaps addressed:**
- Admin page removed from nav (Task 2) but kept at `/admin` URL
- `admin:refresh-scores` runs filtered out of Reports + Chat lists (Tasks 3 + 6)

**Type consistency:**
- `r.municipality_id` used as React key in Task 4 — matches `RunResult.municipality_id: number` in `lib/types.ts` ✅
- `r.opportunities` is `string[]` per `RunResult` type — Task 4 uses `r.opportunities[0]` ✅
- `center` prop on `RunMapView` is `[number, number]` — Task 4 passes `mapCenter: [number, number]` ✅
- `_municipality_coord` imported from `agents/geo_scoring` in Task 1 backfill script ✅
