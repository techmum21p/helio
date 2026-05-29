# Helio Frontend Redesign — Spec
**Date:** 2026-05-29
**Branch:** feat-helio-v2

## Summary

Redesign the Next.js frontend from a top-nav dark theme to a warm-light sidebar app that mirrors the Streamlit UX elegantly. Approach B: layout restructure + full restyle. All page business logic stays intact; only layout shell and styling change.

---

## Design Decisions

| Decision | Choice |
|---|---|
| Layout | Wide collapsible sidebar (~228px expanded, ~56px collapsed) |
| Color palette | Warm Stone — cream base `#faf9f6`, amber accent `#d97706` |
| Pipeline controls | In sidebar (province dropdown + municipality multiselect + Analyze button) |
| Navigation | Map & Scores, Explore, Reports, Chat, Admin (no separate /analyze page) |
| Sidebar behavior | Collapsible, state persisted to localStorage |
| Map style | Keep Streamlit's Folium style via react-leaflet (Positron tile, green/orange/red dots) |

---

## Design Tokens (globals.css)

Replace all dark slate variables with:

```css
/* Surfaces */
--bg-base:    #faf9f6;   /* page background */
--bg-sidebar: #f3f1eb;   /* sidebar background */
--bg-card:    #ffffff;   /* card / panel surface */
--border:     #ede9e0;   /* dividers, card borders */
--border-sub: #e7e3da;   /* input borders, subtle dividers */

/* Accent — Amber */
--accent:        #d97706;   /* primary buttons, active nav */
--accent-hover:  #b45309;   /* button hover */
--accent-subtle: #fef3c7;   /* active nav bg, selected items */
--accent-border: #fcd34d;   /* subtle accent border */
--accent-dark:   #92400e;   /* text on accent-subtle bg */
--accent-deep:   #78350f;   /* darker amber text */

/* Typography — warm stone scale */
--text-heading: #1c1917;
--text-body:    #44403c;
--text-muted:   #78716c;
--text-subtle:  #a8a29e;

/* Status / tier */
--tier-high:   #059669;   /* green */
--tier-med:    #d97706;   /* amber */
--tier-low:    #dc2626;   /* red */

/* Tier badge backgrounds */
--tier-high-bg: #d1fae5;
--tier-med-bg:  #fef3c7;
--tier-low-bg:  #fee2e2;
```

Tailwind body classes: `bg-stone-50 text-stone-900` (or inline `#faf9f6`).

---

## Architecture

```
app/layout.tsx
  └─ <AppShell>                   ← NEW: manages collapsed state (localStorage)
       ├─ <Sidebar>               ← NEW: nav + pipeline card
       │    ├─ logo + wordmark
       │    ├─ collapse toggle button
       │    ├─ nav links (5 items)
       │    ├─ last-run badge
       │    └─ <SidebarPipelineCard>  ← NEW: province select + muni multiselect + Analyze
       └─ <main>{children}</main
```

### New / changed files

| File | Action | Notes |
|---|---|---|
| `app/layout.tsx` | Replace | Swap `<Nav>` for `<AppShell>` |
| `app/globals.css` | Replace | New warm stone token set |
| `components/app-shell.tsx` | Create | `collapsed` state + localStorage persistence |
| `components/sidebar.tsx` | Create | Nav links, collapse toggle, pipeline card |
| `components/sidebar-pipeline-card.tsx` | Create | Province dropdown → municipality multiselect → Analyze button |
| `components/nav.tsx` | Delete | Replaced by sidebar |
| `app/analyze/page.tsx` | Delete | Controls move to sidebar |
| `app/analyze/[runId]/page.tsx` | Update | Run progress view — on complete, redirect to `/map/${runId}` (was `/reports/${runId}`) |
| `app/map/page.tsx` | Create | Redirects to `/map/[latestRunId]`; shows empty state if no runs |
| `app/map/[runId]/page.tsx` | Create | Map & Scores view: stat cards + `<RunMapView>` + top targets list |
| All existing page `.tsx` files | Restyle | Update Tailwind classes to warm stone palette only |

---

## Component Specs

### `<AppShell>`
- Client component
- State: `collapsed: boolean`, default `false`
- Persists to `localStorage` key `helio-sidebar-collapsed`
- Renders: `<div class="flex h-screen"> <Sidebar collapsed={collapsed} onToggle={...} /> <main class="flex-1 overflow-hidden">{children}</main> </div>`

### `<Sidebar>`
Props: `collapsed: boolean`, `onToggle: () => void`

Sections (top to bottom):
1. **Logo row** — sun icon + "HELIO" wordmark (hidden when collapsed)
2. **Collapse toggle** — `◀` / `▶` button, full-width, border style
3. **Nav links** — 5 items: Map & Scores (`/map`), Explore (`/explore`), Reports (`/reports`), Chat (`/chat`), Admin (`/admin`). Active state: `bg-amber-50 border border-amber-200 text-amber-800 font-semibold`. Collapsed: icon only.
4. **Last-run badge** — shows location + municipality count from most recent completed run (hidden when collapsed). Fetched via `useLastRun()` hook (wraps `getRuns(1)`).
5. **`<SidebarPipelineCard>`** — hidden when collapsed

### `<SidebarPipelineCard>`
- Province `<select>` — fetches from `getProvinces()`
- Municipality scrollable checklist — fetches `getMunicipalities({ province })` when province selected. Max-height `~112px`, scrollable. Each row: checkbox + name + geo_score. Selecting zero = analyze whole province.
- Selected count badge: "N selected" or "Whole province" when none checked.
- `▶ Analyze` button — calls `createRun(location)`, redirects to `/analyze/${run_id}` (run progress page)

### Map components (two variants)

**`<RunMapView>`** (Map & Scores page — pipeline run results)
- Input: `geo_geojson: string` from `RunDetail`
- Parses GeoJSON, reads Point features
- Tile layer: CartoDB Positron (`https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png`)
- Circle color: `#2ecc71` if score ≥ 0.65, `#f39c12` if ≥ 0.35, `#e74c3c` otherwise
- Radius: `6 + score × 14`
- Popup: `<b>{name}</b><br>Score: {score.toFixed(3)}`
- Tooltip: `{name}: {score.toFixed(3)}`

**`<ExploreMapView>`** (Explore page — all municipalities)
- Existing `map-view.tsx` updated: switch to Positron tile layer, apply same color/radius scheme as above.

---

## Page-by-page Restyling

### Map & Scores (`app/map/[runId]/page.tsx`)
- Stat cards row (Top Score, Tier, Municipality count, Avg Irradiance)
- Two-column content: `<RunMapView>` (flex-1) + top targets list (230px)
- Target list items: name, tier badge, score, score bar, one-line assessment

### Explore (`app/explore/page.tsx`)
- Filter bar: warm stone inputs, amber focus ring
- `<ExploreMapView>` toggle (collapsible, warm style)
- Table: white card bg, stone borders, amber hover highlight

### Reports (`app/reports/[runId]/page.tsx`)
- Layout: sidebar stub (collapsed icon-only sidebar shows naturally) + run list (150px) + report main
- Run list items: active = amber left border + `#fef9ee` bg
- Report header: title + meta + download button
- Markdown prose: `prose` Tailwind plugin with warm overrides (headings `#92400e`, code `#1c1917 bg-stone-100`)
- Bottom chat: 90px pinned ChatPanel, warm styled

### Chat (`app/chat/page.tsx`)
- Full-height message thread (warm bubbles: user = amber, bot = stone-100)
- Context switcher panel (right, 170px): "Global KB" + per-run items
- Input row: stone bg, amber send button

### Admin (`app/admin/page.tsx`)
- Stat cards (warm stone)
- Action buttons: `Re-index KB`, `Refresh Geo Scores` — amber primary style

---

## Removed

- `components/nav.tsx` — deleted
- `app/analyze/page.tsx` — deleted (controls move to sidebar)
- Dark theme classes throughout (`bg-slate-950`, `text-slate-100`, `border-slate-800`, etc.)
- `html.dark` class on `<html>` tag

---

## Out of Scope

- Page content logic (data fetching, state management)
- API changes
- New features
- Mobile/responsive layout (sidebar always visible for now)
