# Helio Frontend Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the dark top-nav Next.js UI with a warm-stone sidebar app that mirrors the Streamlit UX — collapsible sidebar, pipeline controls always visible, Streamlit-style Folium map.

**Architecture:** New `<AppShell>` wraps all pages with a collapsible sidebar (`<Sidebar>` + `<SidebarPipelineCard>`). Design tokens in `globals.css` switch to warm stone palette. All page business logic is unchanged — only layout shell and Tailwind classes are updated. Two new pages (`/map`, `/map/[runId]`) replace the Analyze page as the post-run landing view.

**Tech Stack:** Next.js 14, React 18, Tailwind CSS 3, react-leaflet 4, SWR, TypeScript 5, @tailwindcss/typography (to install), FastAPI (lat/lon fix only).

---

## File Map

### Create
| File | Purpose |
|---|---|
| `components/app-shell.tsx` | Client component managing sidebar collapsed state (localStorage) |
| `components/sidebar.tsx` | Nav links, collapse toggle, last-run badge |
| `components/sidebar-pipeline-card.tsx` | Province dropdown + municipality checklist + Analyze button |
| `components/run-map-view.tsx` | Folium-style map for pipeline run results (Positron + green/orange/red) |
| `lib/score-color.ts` | Shared score → color + radius utilities |
| `app/map/page.tsx` | Redirect to latest run's map or empty state |
| `app/map/[runId]/page.tsx` | Map & Scores page: stat cards + RunMapView + top targets list |

### Modify
| File | Change |
|---|---|
| `api/routers/runs.py` | Add `m.lat, m.lon` to run results JOIN query |
| `frontend/lib/types.ts` | Add `lat`, `lon` to `RunResult` |
| `frontend/package.json` | Add `@tailwindcss/typography` |
| `frontend/tailwind.config.ts` | Register typography plugin |
| `frontend/app/globals.css` | Warm stone design tokens, remove dark tokens |
| `frontend/app/layout.tsx` | Remove `dark` class, mount `<AppShell>` |
| `frontend/components/map-view.tsx` | Positron tile layer + Streamlit color/radius scheme |
| `frontend/components/tier-badge.tsx` | Warm stone colours (A/B/C/D → stone/amber/green/red) |
| `frontend/components/run-progress.tsx` | Warm stone colours |
| `frontend/components/stat-card.tsx` | Warm stone colours |
| `frontend/components/score-bar.tsx` | Amber gradient |
| `frontend/components/municipality-table.tsx` | Warm stone colours |
| `frontend/components/run-list.tsx` | Warm stone colours |
| `frontend/components/chat-panel.tsx` | Warm stone colours |
| `frontend/app/analyze/[runId]/page.tsx` | Redirect to `/map/${runId}` on complete; restyle |
| `frontend/app/explore/page.tsx` | Warm stone restyle |
| `frontend/app/reports/page.tsx` | Warm stone restyle |
| `frontend/app/reports/[runId]/page.tsx` | Warm stone restyle + warm prose config |
| `frontend/app/chat/page.tsx` | Warm stone restyle |
| `frontend/app/admin/page.tsx` | Warm stone restyle |

### Delete
| File | Reason |
|---|---|
| `frontend/components/nav.tsx` | Replaced by `<Sidebar>` |
| `frontend/app/analyze/page.tsx` | Controls move to sidebar |

---

## Task 1: Add lat/lon to run results

**Files:**
- Modify: `api/routers/runs.py:101-107`
- Modify: `frontend/lib/types.ts:31-41`

- [ ] **Step 1: Update the run results query to include coordinates**

In `api/routers/runs.py`, change the results query to select lat and lon:

```python
results = conn.execute(
    """SELECT rr.*, m.name AS municipality_name, m.province,
              m.lat, m.lon
       FROM   run_results rr
       LEFT JOIN municipalities m ON rr.municipality_id = m.id
       WHERE  rr.run_id=? ORDER BY rr.final_score DESC""",
    (run_id,),
).fetchall()
```

- [ ] **Step 2: Add lat/lon to the RunResult TypeScript type**

In `frontend/lib/types.ts`, update `RunResult`:

```typescript
export interface RunResult {
  municipality_id: number;
  municipality_name: string;
  province: string;
  lat: number | null;
  lon: number | null;
  geo_score: number;
  web_score: number;
  final_score: number;
  tier: string;
  assessment: string;
  opportunities: string[];
  risks: string[];
}
```

- [ ] **Step 3: Verify with lint**

```bash
cd frontend && npm run lint
```
Expected: no new errors.

- [ ] **Step 4: Commit**

```bash
git add api/routers/runs.py frontend/lib/types.ts
git commit -m "feat: add lat/lon to run results for map rendering"
```

---

## Task 2: Install typography plugin + update Tailwind config

**Files:**
- Modify: `frontend/package.json`
- Modify: `frontend/tailwind.config.ts`

- [ ] **Step 1: Install @tailwindcss/typography**

```bash
cd frontend && npm install @tailwindcss/typography
```

- [ ] **Step 2: Register the plugin in tailwind.config.ts**

```typescript
import type { Config } from "tailwindcss";

const config: Config = {
  darkMode: ["class"],
  content: [
    "./pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}",
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    container: {
      center: true,
      padding: "2rem",
      screens: { "2xl": "1400px" },
    },
    extend: {
      colors: {
        border: "hsl(var(--border))",
        input: "hsl(var(--input))",
        ring: "hsl(var(--ring))",
        background: "hsl(var(--background))",
        foreground: "hsl(var(--foreground))",
        primary: {
          DEFAULT: "hsl(var(--primary))",
          foreground: "hsl(var(--primary-foreground))",
        },
        secondary: {
          DEFAULT: "hsl(var(--secondary))",
          foreground: "hsl(var(--secondary-foreground))",
        },
        destructive: {
          DEFAULT: "hsl(var(--destructive))",
          foreground: "hsl(var(--destructive-foreground))",
        },
        muted: {
          DEFAULT: "hsl(var(--muted))",
          foreground: "hsl(var(--muted-foreground))",
        },
        accent: {
          DEFAULT: "hsl(var(--accent))",
          foreground: "hsl(var(--accent-foreground))",
        },
        popover: {
          DEFAULT: "hsl(var(--popover))",
          foreground: "hsl(var(--popover-foreground))",
        },
        card: {
          DEFAULT: "hsl(var(--card))",
          foreground: "hsl(var(--card-foreground))",
        },
      },
      borderRadius: {
        lg: "var(--radius)",
        md: "calc(var(--radius) - 2px)",
        sm: "calc(var(--radius) - 4px)",
      },
      typography: {
        DEFAULT: {
          css: {
            "--tw-prose-body": "#44403c",
            "--tw-prose-headings": "#1c1917",
            "--tw-prose-links": "#d97706",
            "--tw-prose-bold": "#1c1917",
            "--tw-prose-counters": "#78716c",
            "--tw-prose-bullets": "#a8a29e",
            "--tw-prose-hr": "#ede9e0",
            "--tw-prose-quotes": "#44403c",
            "--tw-prose-quote-borders": "#fcd34d",
            "--tw-prose-captions": "#78716c",
            "--tw-prose-code": "#1c1917",
            "--tw-prose-pre-code": "#1c1917",
            "--tw-prose-pre-bg": "#f3f1eb",
            "--tw-prose-th-borders": "#ede9e0",
            "--tw-prose-td-borders": "#ede9e0",
          },
        },
      },
    },
  },
  plugins: [require("@tailwindcss/typography")],
};

export default config;
```

- [ ] **Step 3: Verify build succeeds**

```bash
cd frontend && npm run build 2>&1 | tail -20
```
Expected: `✓ Compiled successfully` (or similar).

- [ ] **Step 4: Commit**

```bash
git add frontend/package.json frontend/package-lock.json frontend/tailwind.config.ts
git commit -m "feat: add tailwindcss/typography plugin with warm stone prose config"
```

---

## Task 3: Warm stone design tokens

**Files:**
- Modify: `frontend/app/globals.css`

- [ ] **Step 1: Replace globals.css with warm stone tokens**

```css
@tailwind base;
@tailwind components;
@tailwind utilities;

@layer base {
  :root {
    --background: 0 0% 98%;
    --foreground: 20 14% 11%;
    --card: 0 0% 100%;
    --card-foreground: 20 14% 11%;
    --popover: 0 0% 100%;
    --popover-foreground: 20 14% 11%;
    --primary: 32 95% 44%;
    --primary-foreground: 0 0% 100%;
    --secondary: 30 20% 94%;
    --secondary-foreground: 20 14% 11%;
    --muted: 30 20% 94%;
    --muted-foreground: 20 6% 48%;
    --accent: 30 20% 94%;
    --accent-foreground: 20 14% 11%;
    --destructive: 0 84% 60%;
    --destructive-foreground: 0 0% 100%;
    --border: 30 18% 91%;
    --input: 30 18% 91%;
    --ring: 32 95% 44%;
    --radius: 0.5rem;
  }
}

@layer base {
  * {
    @apply border-border;
  }
  body {
    background-color: #faf9f6;
    color: #1c1917;
  }
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/app/globals.css
git commit -m "feat: warm stone design tokens in globals.css"
```

---

## Task 4: Shared score-color utility

**Files:**
- Create: `frontend/lib/score-color.ts`

- [ ] **Step 1: Create the shared utility**

```typescript
// Returns Streamlit-matching color for a geo/final score
export function scoreColor(score: number | null): string {
  if (score === null) return "#a8a29e";
  if (score >= 0.65) return "#2ecc71";
  if (score >= 0.35) return "#f39c12";
  return "#e74c3c";
}

// Returns Streamlit-matching circle radius: 6 + score * 14
export function scoreRadius(score: number | null): number {
  if (score === null) return 6;
  return 6 + score * 14;
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/lib/score-color.ts
git commit -m "feat: shared score-color utility (Streamlit-matching)"
```

---

## Task 5: Update ExploreMapView to Streamlit style

**Files:**
- Modify: `frontend/components/map-view.tsx`

- [ ] **Step 1: Update map-view.tsx**

```typescript
"use client";
import { useEffect } from "react";
import { MapContainer, TileLayer, CircleMarker, Tooltip, Popup } from "react-leaflet";
import type { Municipality } from "@/lib/types";
import { scoreColor, scoreRadius } from "@/lib/score-color";
import "leaflet/dist/leaflet.css";

interface Props {
  municipalities: Municipality[];
  selectedId: number | null;
  onSelect: (id: number) => void;
}

export default function MapView({ municipalities, selectedId, onSelect }: Props) {
  useEffect(() => {
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const L = require("leaflet");
    delete (L.Icon.Default.prototype as { _getIconUrl?: unknown })._getIconUrl;
    L.Icon.Default.mergeOptions({
      iconRetinaUrl: "/leaflet/marker-icon-2x.png",
      iconUrl: "/leaflet/marker-icon.png",
      shadowUrl: "/leaflet/marker-shadow.png",
    });
  }, []);

  const withCoords = municipalities.filter((m) => m.lat !== null && m.lon !== null);

  return (
    <MapContainer
      center={[12.8797, 121.774]}
      zoom={6}
      className="w-full h-full"
    >
      <TileLayer
        url="https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png"
        attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> &copy; <a href="https://carto.com/">CARTO</a>'
      />
      {withCoords.map((m) => {
        const color = selectedId === m.id ? "#d97706" : scoreColor(m.geo_score);
        const radius = selectedId === m.id ? 10 : scoreRadius(m.geo_score);
        return (
          <CircleMarker
            key={m.id}
            center={[m.lat!, m.lon!]}
            radius={radius}
            pathOptions={{ color, fillColor: color, fillOpacity: 0.75, weight: 1.5 }}
            eventHandlers={{ click: () => onSelect(m.id) }}
          >
            <Popup>
              <b>{m.name}</b><br />Score: {m.geo_score?.toFixed(3) ?? "—"}
            </Popup>
            <Tooltip>{m.name}: {m.geo_score?.toFixed(3) ?? "—"}</Tooltip>
          </CircleMarker>
        );
      })}
    </MapContainer>
  );
}
```

- [ ] **Step 2: Verify lint**

```bash
cd frontend && npm run lint
```
Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/components/map-view.tsx
git commit -m "feat: update ExploreMapView to Positron tile + Streamlit color/radius scheme"
```

---

## Task 6: RunMapView component

**Files:**
- Create: `frontend/components/run-map-view.tsx`

This component renders pipeline run results on the map using the same Streamlit visual style, reading from `RunResult[]` (which now includes lat/lon after Task 1).

- [ ] **Step 1: Create run-map-view.tsx**

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
      iconUrl: "/leaflet/marker-icon.png",
      shadowUrl: "/leaflet/marker-shadow.png",
    });
  }, []);

  const withCoords = results.filter((r) => r.lat !== null && r.lon !== null);

  return (
    <MapContainer center={center} zoom={10} className="w-full h-full">
      <TileLayer
        url="https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png"
        attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> &copy; <a href="https://carto.com/">CARTO</a>'
      />
      {withCoords.map((r) => {
        const color = scoreColor(r.final_score);
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

- [ ] **Step 2: Verify lint**

```bash
cd frontend && npm run lint
```
Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/components/run-map-view.tsx
git commit -m "feat: RunMapView — Folium-style pipeline results map"
```

---

## Task 7: AppShell component + layout.tsx update

**Files:**
- Create: `frontend/components/app-shell.tsx`
- Modify: `frontend/app/layout.tsx`

- [ ] **Step 1: Create app-shell.tsx**

```typescript
"use client";
import { useState, useEffect } from "react";
import Sidebar from "./sidebar";

export default function AppShell({ children }: { children: React.ReactNode }) {
  const [collapsed, setCollapsed] = useState(false);

  useEffect(() => {
    const stored = localStorage.getItem("helio-sidebar-collapsed");
    if (stored !== null) setCollapsed(stored === "true");
  }, []);

  function toggle() {
    setCollapsed((prev) => {
      localStorage.setItem("helio-sidebar-collapsed", String(!prev));
      return !prev;
    });
  }

  return (
    <div className="flex h-screen overflow-hidden">
      <Sidebar collapsed={collapsed} onToggle={toggle} />
      <main className="flex-1 overflow-hidden flex flex-col min-w-0">
        {children}
      </main>
    </div>
  );
}
```

- [ ] **Step 2: Update layout.tsx**

```typescript
import type { Metadata } from "next";
import { Inter } from "next/font/google";
import "./globals.css";
import AppShell from "@/components/app-shell";

const inter = Inter({ subsets: ["latin"] });

export const metadata: Metadata = {
  title: "Helio — Solar Opportunity Intelligence",
  description: "Identify solar installation targets in the Philippines",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className={`${inter.className} min-h-screen`}>
        <AppShell>{children}</AppShell>
      </body>
    </html>
  );
}
```

- [ ] **Step 3: Verify lint**

```bash
cd frontend && npm run lint
```
Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/components/app-shell.tsx frontend/app/layout.tsx
git commit -m "feat: AppShell component with collapsible sidebar state"
```

---

## Task 8: Sidebar component

**Files:**
- Create: `frontend/components/sidebar.tsx`

- [ ] **Step 1: Create sidebar.tsx**

```typescript
"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import useSWR from "swr";
import type { Run } from "@/lib/types";
import { getRuns } from "@/lib/api";
import SidebarPipelineCard from "./sidebar-pipeline-card";

const NAV_LINKS = [
  { href: "/map",     icon: "🗺",  label: "Map & Scores" },
  { href: "/explore", icon: "🔍",  label: "Explore"      },
  { href: "/reports", icon: "📄",  label: "Reports"      },
  { href: "/chat",    icon: "💬",  label: "Chat"         },
  { href: "/admin",   icon: "⚙️",  label: "Admin"        },
];

interface Props {
  collapsed: boolean;
  onToggle: () => void;
}

export default function Sidebar({ collapsed, onToggle }: Props) {
  const pathname = usePathname();
  const { data: runs = [] } = useSWR<Run[]>("runs-1", () => getRuns(1));
  const lastRun = runs[0] ?? null;

  return (
    <aside
      className="flex flex-col shrink-0 border-r border-stone-200 bg-stone-100 transition-all duration-200 overflow-hidden"
      style={{ width: collapsed ? 56 : 228 }}
    >
      {/* Logo */}
      <div className="flex items-center gap-2.5 px-3.5 py-4 border-b border-stone-200 shrink-0">
        <span className="text-lg shrink-0">☀️</span>
        {!collapsed && (
          <span className="text-xs font-black tracking-[0.2em] text-stone-900 whitespace-nowrap">
            HELIO
          </span>
        )}
      </div>

      {/* Collapse toggle */}
      <div className="px-2 pt-2 shrink-0">
        <button
          onClick={onToggle}
          className="w-full flex items-center justify-center gap-1.5 border border-stone-300 rounded-md py-1.5 text-xs text-stone-500 hover:bg-stone-200 transition-colors"
        >
          <span>{collapsed ? "▶" : "◀"}</span>
          {!collapsed && <span>Collapse</span>}
        </button>
      </div>

      {/* Nav links */}
      <nav className="flex flex-col gap-0.5 px-2 py-2 shrink-0">
        {NAV_LINKS.map(({ href, icon, label }) => {
          const active = pathname === href || pathname.startsWith(href + "/");
          return (
            <Link
              key={href}
              href={href}
              className={`flex items-center gap-2.5 px-2.5 py-1.5 rounded-md text-sm transition-colors ${
                active
                  ? "bg-amber-50 border border-amber-200/70 text-amber-800 font-semibold"
                  : "text-stone-600 hover:bg-stone-200"
              }`}
            >
              <span className="text-sm shrink-0">{icon}</span>
              {!collapsed && <span className="whitespace-nowrap">{label}</span>}
            </Link>
          );
        })}
      </nav>

      {/* Scrollable bottom area: last-run badge + pipeline card */}
      <div className="flex-1 overflow-y-auto flex flex-col gap-2 px-2 pb-3 min-h-0">
        {!collapsed && lastRun && (
          <div className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 shrink-0">
            <p className="text-[10px] text-stone-400 uppercase tracking-wide mb-0.5">Last run</p>
            <p className="text-xs font-semibold text-amber-900 truncate">{lastRun.location}</p>
            <p className="text-[10px] text-amber-700 mt-0.5">
              {lastRun.status === "done" ? "✓ Completed" : lastRun.status}
            </p>
          </div>
        )}

        {!collapsed && <SidebarPipelineCard />}
      </div>
    </aside>
  );
}
```

- [ ] **Step 2: Verify lint**

```bash
cd frontend && npm run lint
```
Expected: no errors (SidebarPipelineCard doesn't exist yet — may show import error; that's fine, will be fixed in next task).

- [ ] **Step 3: Commit**

```bash
git add frontend/components/sidebar.tsx
git commit -m "feat: Sidebar component — nav, collapse toggle, last-run badge"
```

---

## Task 9: SidebarPipelineCard component

**Files:**
- Create: `frontend/components/sidebar-pipeline-card.tsx`

- [ ] **Step 1: Create sidebar-pipeline-card.tsx**

```typescript
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
```

- [ ] **Step 2: Verify lint**

```bash
cd frontend && npm run lint
```
Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/components/sidebar-pipeline-card.tsx
git commit -m "feat: SidebarPipelineCard — province dropdown + municipality multiselect"
```

---

## Task 10: Map & Scores pages

**Files:**
- Create: `frontend/app/map/page.tsx`
- Create: `frontend/app/map/[runId]/page.tsx`

- [ ] **Step 1: Create app/map/page.tsx (redirect or empty state)**

```typescript
import { redirect } from "next/navigation";
import { getRuns } from "@/lib/api";
import Link from "next/link";

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
```

- [ ] **Step 2: Create app/map/[runId]/page.tsx**

```typescript
"use client";
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

  if (isLoading) {
    return <div className="flex items-center justify-center flex-1 text-stone-400 text-sm">Loading…</div>;
  }
  if (!run) {
    return <div className="flex items-center justify-center flex-1 text-stone-400 text-sm">Run not found.</div>;
  }

  const results = run.results ?? [];
  const top = results[0];

  // Compute average irradiance from geo_score proxy
  const avgSolar = results.length
    ? (results.reduce((s, r) => s + (r.geo_score ?? 0), 0) / results.length).toFixed(3)
    : "—";

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
      <div className="flex-1 grid overflow-hidden" style={{ gridTemplateColumns: "1fr 240px" }}>
        {/* Map */}
        <div className="overflow-hidden">
          {results.length > 0 ? (
            <RunMapView results={results} />
          ) : (
            <div className="flex items-center justify-center h-full text-stone-400 text-sm">
              No map data available.
            </div>
          )}
        </div>

        {/* Top targets list */}
        <div className="border-l border-stone-200 overflow-y-auto bg-stone-50 flex flex-col">
          <div className="px-3 py-2.5 border-b border-stone-200 shrink-0">
            <p className="text-[10px] font-bold tracking-widest uppercase text-stone-400">Top Targets</p>
          </div>
          <div className="flex flex-col gap-1.5 p-2.5">
            {results.slice(0, 15).map((r) => (
              <div key={r.municipality_id} className="bg-white border border-stone-200 rounded-lg px-3 py-2 shadow-sm">
                <div className="flex items-center gap-1.5">
                  <span className="flex-1 text-xs font-semibold text-stone-900 truncate">{r.municipality_name}</span>
                  <TierBadge tier={r.tier} />
                  <span className="text-xs font-bold text-amber-600 tabular-nums shrink-0">
                    {r.final_score.toFixed(3)}
                  </span>
                </div>
                <ScoreBar score={r.final_score} />
                {r.assessment && (
                  <p className="text-[10px] text-stone-500 mt-1.5 line-clamp-2 leading-relaxed">
                    {r.assessment}
                  </p>
                )}
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 3: Verify lint + build**

```bash
cd frontend && npm run lint && npm run build 2>&1 | tail -20
```
Expected: clean lint, successful build.

- [ ] **Step 4: Commit**

```bash
git add frontend/app/map/
git commit -m "feat: Map & Scores pages (/map + /map/[runId])"
```

---

## Task 11: Update analyze/[runId] redirect + restyle

**Files:**
- Modify: `frontend/app/analyze/[runId]/page.tsx`

- [ ] **Step 1: Update redirect and restyle**

```typescript
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
```

- [ ] **Step 2: Commit**

```bash
git add frontend/app/analyze/[runId]/page.tsx
git commit -m "feat: redirect analyze complete to /map, warm stone restyle"
```

---

## Task 12: Restyle shared components

**Files:**
- Modify: `frontend/components/run-progress.tsx`
- Modify: `frontend/components/tier-badge.tsx`
- Modify: `frontend/components/stat-card.tsx`
- Modify: `frontend/components/score-bar.tsx`
- Modify: `frontend/components/run-list.tsx`
- Modify: `frontend/components/municipality-table.tsx`
- Modify: `frontend/components/chat-panel.tsx`

- [ ] **Step 1: Restyle run-progress.tsx**

```typescript
"use client";
import { useEffect, useState } from "react";
import type { StepEvent } from "@/lib/types";
import { openRunStream } from "@/lib/api";

const PIPELINE_STEPS = [
  { key: "geo_scoring",  label: "Geo Scoring",      description: "Loading pre-computed scores" },
  { key: "web_intel",    label: "Web Intelligence",  description: "Fetching business & market data" },
  { key: "synthesis",    label: "Synthesis",         description: "Combining geo + web intelligence" },
  { key: "report_gen",   label: "Report Generation", description: "Writing detailed markdown report" },
  { key: "update_kb",    label: "Knowledge Base",    description: "Indexing report into RAG store" },
];

type StepStatus = "waiting" | "running" | "done" | "failed";

interface Props {
  runId: string;
  onComplete?: (runId: string) => void;
  onFailed?: (error: string | null) => void;
}

export default function RunProgress({ runId, onComplete, onFailed }: Props) {
  const [stepStates, setStepStates] = useState<Record<string, StepStatus>>({});
  const [elapsedMs, setElapsedMs] = useState<Record<string, number>>({});
  const [terminated, setTerminated] = useState(false);

  useEffect(() => {
    if (!runId) return;
    const es = openRunStream(runId);
    es.onmessage = (e) => {
      let event: StepEvent;
      try { event = JSON.parse(e.data); } catch { return; }
      if (event.step === "complete") {
        setTerminated(true); es.close(); onComplete?.(runId); return;
      }
      if (event.step === "failed") {
        setStepStates((prev) => ({ ...prev, [event.step]: "failed" }));
        setTerminated(true); es.close(); onFailed?.(event.error ?? null); return;
      }
      setStepStates((prev) => ({ ...prev, [event.step]: event.status as StepStatus }));
      if (event.elapsed_ms) setElapsedMs((prev) => ({ ...prev, [event.step]: event.elapsed_ms }));
    };
    es.onerror = () => { if (!terminated) es.close(); };
    return () => es.close();
  }, [runId]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className="space-y-3">
      {PIPELINE_STEPS.map((step) => {
        const status: StepStatus = stepStates[step.key] ?? "waiting";
        const ms = elapsedMs[step.key];
        return (
          <div key={step.key} className="flex items-start gap-3">
            <div className="mt-0.5 shrink-0">
              {status === "done"    && <div className="w-5 h-5 rounded-full bg-emerald-500 flex items-center justify-center text-white text-xs">✓</div>}
              {status === "running" && <div className="w-5 h-5 rounded-full border-2 border-amber-500 border-t-transparent animate-spin" />}
              {status === "failed"  && <div className="w-5 h-5 rounded-full bg-red-500 flex items-center justify-center text-white text-xs">✕</div>}
              {status === "waiting" && <div className="w-5 h-5 rounded-full border border-stone-300 bg-stone-100" />}
            </div>
            <div>
              <p className={`text-sm font-medium ${
                status === "running" ? "text-amber-600" :
                status === "done"    ? "text-stone-700" :
                status === "failed"  ? "text-red-500"   : "text-stone-400"
              }`}>
                {step.label}
                {status === "done" && ms && (
                  <span className="ml-2 text-xs text-stone-400 font-normal">{(ms / 1000).toFixed(1)}s</span>
                )}
              </p>
              {status === "running" && <p className="text-xs text-stone-400">{step.description}</p>}
            </div>
          </div>
        );
      })}
    </div>
  );
}
```

- [ ] **Step 2: Restyle tier-badge.tsx**

```typescript
import type { Tier } from "@/lib/types";

const TIER_STYLES: Record<Tier, string> = {
  A: "bg-amber-100 text-amber-800 border border-amber-200",
  B: "bg-emerald-100 text-emerald-800 border border-emerald-200",
  C: "bg-blue-100 text-blue-700 border border-blue-200",
  D: "bg-stone-100 text-stone-500 border border-stone-200",
};

export default function TierBadge({ tier }: { tier: Tier | null }) {
  if (!tier) return <span className="text-stone-400 text-xs">—</span>;
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-semibold ${TIER_STYLES[tier]}`}>
      {tier}
    </span>
  );
}
```

- [ ] **Step 3: Restyle stat-card.tsx**

```typescript
interface Props {
  label: string;
  value: string | number;
}

export default function StatCard({ label, value }: Props) {
  return (
    <div className="bg-white border border-stone-200 rounded-lg px-4 py-3 shadow-sm">
      <p className="text-lg font-bold text-stone-900">{value}</p>
      <p className="text-[10px] text-stone-400 mt-0.5">{label}</p>
    </div>
  );
}
```

- [ ] **Step 4: Restyle score-bar.tsx**

Check the current interface then write:

```typescript
interface Props {
  score: number;
  max?: number;
}

export default function ScoreBar({ score, max = 1 }: Props) {
  const pct = Math.min((score / max) * 100, 100).toFixed(1);
  return (
    <div className="h-1.5 bg-stone-100 rounded-full overflow-hidden">
      <div
        className="h-full rounded-full bg-gradient-to-r from-amber-500 to-amber-400 transition-all"
        style={{ width: `${pct}%` }}
      />
    </div>
  );
}
```

- [ ] **Step 5: Restyle run-list.tsx**

Read `frontend/components/run-list.tsx` first, then replace all `slate-*` classes with their warm stone equivalents:
- `bg-slate-950` → `bg-stone-50`
- `bg-slate-900` → `bg-stone-100`
- `border-slate-800` → `border-stone-200`
- `text-slate-300` / `text-slate-200` → `text-stone-700`
- `text-slate-400` / `text-slate-500` / `text-slate-600` → `text-stone-400` / `text-stone-500`
- `border-amber-500` active indicator stays amber

- [ ] **Step 6: Restyle municipality-table.tsx**

Read `frontend/components/municipality-table.tsx` first, then replace all `slate-*` classes:
- `bg-slate-950` / `bg-slate-900` → `bg-white` / `bg-stone-50`
- `border-slate-800` / `border-slate-700` → `border-stone-200`
- `text-slate-*` → `text-stone-*` equivalents
- `hover:bg-slate-800` → `hover:bg-amber-50`
- `text-amber-400` score color → `text-amber-600`

- [ ] **Step 7: Restyle chat-panel.tsx**

```typescript
"use client";
import { useState, useEffect, useRef } from "react";
import type { ChatMessage } from "@/lib/types";
import { getChatHistory, streamChat } from "@/lib/api";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

interface Props {
  runId: string | null;
  placeholder?: string;
}

export default function ChatPanel({ runId, placeholder = "Ask anything about solar opportunities…" }: Props) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const bufferRef = useRef("");
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    setMessages([]);
    if (!runId) return;
    getChatHistory(runId).then(setMessages).catch(() => {});
  }, [runId]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  async function sendMessage() {
    const text = input.trim();
    if (!text || streaming) return;
    setInput("");
    setStreaming(true);
    bufferRef.current = "";
    const userMsg: ChatMessage = { role: "user", content: text, created_at: new Date().toISOString() };
    const assistantMsg: ChatMessage = { role: "assistant", content: "", created_at: new Date().toISOString() };
    setMessages((prev) => [...prev, userMsg, assistantMsg]);
    try {
      for await (const chunk of streamChat(text, runId)) {
        bufferRef.current += chunk;
        setMessages((prev) => [...prev.slice(0, -1), { ...prev[prev.length - 1], content: bufferRef.current }]);
      }
    } finally {
      setStreaming(false);
    }
  }

  return (
    <div className="flex flex-col h-full bg-white">
      <div className="flex-1 overflow-y-auto p-4 space-y-3 min-h-0">
        {messages.length === 0 && (
          <p className="text-stone-400 text-sm text-center mt-8">{placeholder}</p>
        )}
        {messages.map((msg, i) => (
          <div key={i} className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}>
            <div className={`max-w-[85%] rounded-lg px-3 py-2 text-sm ${
              msg.role === "user"
                ? "bg-amber-600 text-white"
                : "bg-stone-100 text-stone-700 border border-stone-200"
            }`}>
              {msg.role === "assistant" ? (
                <div className="prose prose-sm max-w-none prose-p:my-1">
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>
                    {msg.content || (streaming && i === messages.length - 1 ? "▌" : "")}
                  </ReactMarkdown>
                </div>
              ) : (
                <p>{msg.content}</p>
              )}
            </div>
          </div>
        ))}
        <div ref={bottomRef} />
      </div>
      <div className="border-t border-stone-200 p-3 flex gap-2 shrink-0 bg-white">
        <input
          type="text"
          className="flex-1 bg-stone-50 border border-stone-200 text-stone-700 text-sm rounded-md px-3 py-2 focus:outline-none focus:border-amber-400"
          placeholder={placeholder}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && !e.shiftKey && sendMessage()}
          disabled={streaming}
        />
        <button
          className="px-4 py-2 bg-amber-600 hover:bg-amber-700 disabled:opacity-40 text-white text-sm font-semibold rounded-md transition-colors"
          onClick={sendMessage}
          disabled={streaming || !input.trim()}
        >
          {streaming ? "…" : "Send"}
        </button>
      </div>
    </div>
  );
}
```

- [ ] **Step 8: Verify lint**

```bash
cd frontend && npm run lint
```
Expected: no errors.

- [ ] **Step 9: Commit**

```bash
git add frontend/components/run-progress.tsx frontend/components/tier-badge.tsx \
        frontend/components/stat-card.tsx frontend/components/score-bar.tsx \
        frontend/components/run-list.tsx frontend/components/municipality-table.tsx \
        frontend/components/chat-panel.tsx
git commit -m "feat: restyle shared components to warm stone palette"
```

---

## Task 13: Restyle page files

**Files:**
- Modify: `frontend/app/explore/page.tsx`
- Modify: `frontend/app/reports/page.tsx`
- Modify: `frontend/app/reports/[runId]/page.tsx`
- Modify: `frontend/app/chat/page.tsx`
- Modify: `frontend/app/admin/page.tsx`

- [ ] **Step 1: Restyle explore/page.tsx**

Replace all `slate-*` classes with warm stone equivalents. Key mappings:
- Container bg: remove `bg-slate-950`, body bg covers it
- Filter bar: `border-b border-stone-200 bg-white px-4 py-3`
- `select`, `input`: `bg-stone-50 border border-stone-200 text-stone-700 rounded-md px-2 py-1.5 focus:outline-none focus:border-amber-400`
- Range input: `accent-amber-500`
- Score value: `text-amber-600`
- Map toggle button active: `border-amber-500 text-amber-600 bg-amber-50`
- Map toggle button inactive: `border-stone-300 text-stone-500 hover:border-stone-400`
- Result count: `text-stone-400`

- [ ] **Step 2: Restyle reports/page.tsx**

```typescript
import Link from "next/link";

export default async function ReportsIndexPage() {
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
```

(Remove the `getRuns` redirect — that belongs in `/reports/[runId]` which already handles empty state.)

- [ ] **Step 3: Restyle reports/[runId]/page.tsx**

Key changes:
- Outer grid: `border-r border-stone-200` sidebar, `bg-stone-50` panel
- Run list aside: `bg-stone-50 border-r border-stone-200`
- Run list header: `text-[10px] font-bold tracking-widest uppercase text-stone-400`
- Report area: `bg-white`
- Report header: `border-b border-stone-200 px-8 py-5`
- `h1`: `text-xl font-bold text-stone-900`
- Date meta: `text-xs text-stone-400`
- Download button: `px-3 py-1.5 text-xs border border-stone-300 text-stone-500 rounded-md hover:border-stone-400 bg-white`
- Markdown prose: `prose max-w-none` (no `prose-invert`, uses warm typography config from Task 2)
- Bottom chat: `border-t border-stone-200`

- [ ] **Step 4: Restyle chat/page.tsx**

Key changes:
- Outer grid background: remove dark bg, uses body bg
- Chat panel border: `border-r border-stone-200`
- Context aside: `bg-stone-50 border-l border-stone-200`
- Context header: `text-[10px] font-bold tracking-widest uppercase text-stone-400 px-3 py-2.5 border-b border-stone-200`
- "Global KB" active: `bg-amber-50 border-l-2 border-amber-500 text-amber-800`
- Run items: `border-b border-stone-100`, active: `bg-amber-50 border-l-2 border-amber-500`
- Run name: `text-xs font-semibold text-stone-700`
- Run date: `text-[10px] text-stone-400`

- [ ] **Step 5: Restyle admin/page.tsx**

Read the current file, then:
- All `bg-slate-*` → `bg-white` or `bg-stone-50`
- All `border-slate-*` → `border-stone-200`
- All `text-slate-*` → `text-stone-*`
- Primary action buttons: `bg-amber-600 hover:bg-amber-700 text-white`
- Secondary/border buttons: `border border-stone-300 text-stone-600 hover:bg-stone-100`
- Stat values: `text-stone-900` for numbers, `text-amber-600` for key metrics

- [ ] **Step 6: Verify lint + build**

```bash
cd frontend && npm run lint && npm run build 2>&1 | tail -30
```
Expected: clean lint, successful build.

- [ ] **Step 7: Commit**

```bash
git add frontend/app/explore/page.tsx frontend/app/reports/ \
        frontend/app/chat/page.tsx frontend/app/admin/page.tsx
git commit -m "feat: restyle all pages to warm stone palette"
```

---

## Task 14: Delete removed files + final cleanup

**Files:**
- Delete: `frontend/components/nav.tsx`
- Delete: `frontend/app/analyze/page.tsx`

- [ ] **Step 1: Delete nav.tsx**

```bash
rm frontend/components/nav.tsx
```

- [ ] **Step 2: Delete analyze/page.tsx**

```bash
rm frontend/app/analyze/page.tsx
```

- [ ] **Step 3: Final lint + build**

```bash
cd frontend && npm run lint && npm run build 2>&1 | tail -30
```
Expected: clean lint, `✓ Compiled successfully`.

- [ ] **Step 4: Smoke-test the dev server**

```bash
cd frontend && npm run dev &
# Open http://localhost:3000 — verify:
# - Warm stone background, sidebar visible
# - Collapse toggle works
# - /map shows empty state or latest run
# - /explore shows filterable table with light map
# - /reports shows reports
# - /chat shows chat interface
# - /admin shows stats
```

- [ ] **Step 5: Final commit**

```bash
git add -A
git commit -m "feat: remove nav.tsx and analyze/page.tsx — controls moved to sidebar"
```

---

## Self-Review Checklist

- [x] Design tokens (globals.css) — Task 3
- [x] AppShell + layout update — Task 7
- [x] Sidebar (nav, collapse, last-run) — Task 8
- [x] SidebarPipelineCard (province + muni multiselect + Analyze) — Task 9
- [x] RunMapView (Positron, Streamlit colors) — Task 6
- [x] ExploreMapView updated — Task 5
- [x] Map & Scores pages (/map, /map/[runId]) — Task 10
- [x] analyze/[runId] redirects to /map — Task 11
- [x] All pages restyled — Tasks 12–13
- [x] nav.tsx + analyze/page.tsx deleted — Task 14
- [x] lat/lon in run results (prerequisite) — Task 1
- [x] @tailwindcss/typography installed + configured — Task 2
