# Helio — Solar Opportunity Intelligence

Helio is a multi-agent AI system that identifies the best municipalities in the Philippines for
solar panel sales and installation targeting. Point it at a province and it comes back with a
ranked, AI-narrated shortlist of towns — grounded in real satellite solar data, real government
income and population statistics, and real local commercial activity — instead of a sales team
guessing from a map.

It currently covers the entire country: **1,655 municipalities and cities across all 118
province/highly-urbanized-city groupings**, with a full AI-written assessment for the top 20 in
every one of them.

## Why this exists

The Philippines gets strong solar irradiance almost everywhere, so sun isn't the deciding factor
for an installer — the economics are: which of ~1,600 municipalities combine that sun with enough
income and commercial density to actually buy and finance solar. Ranking that by hand is tedious
and easy to get subtly wrong (see [The data-integrity journey](#the-data-integrity-journey) for a
case study). Helio automates the ranking, sources every number, and hands a salesperson a short,
readable report per town instead of a spreadsheet.

## How it works

```
START → geo_scoring → web_intel → synthesis → report_gen → update_kb → END
```

Five agents, run as a sequential [LangGraph](https://github.com/langchain-ai/langgraph) pipeline,
each reading and returning a shared state object:

| # | Agent | Does |
|---|-------|------|
| 1 | **geo_scoring** | Pulls solar irradiance, income class, and population density for every municipality in the target province; computes `geo_score` |
| 2 | **web_intel** | Pulls local commercial signals (business density, price levels, ratings) via Google Places for the top 20 by `geo_score` |
| 3 | **synthesis** | Blends `geo_score` + web signals into `final_score`; has an LLM write a grounded assessment, confidence tier, one opportunity, and one risk per town |
| 4 | **report_gen** | Writes a markdown report for the province, saved for download and for the knowledge base |
| 5 | **chatbot** | Indexes the new report into a vector store for RAG chat over any town Helio has scored |

**Scoring, precisely:**

```
geo_score   = 0.35 × solar_norm + 0.45 × income_score_norm + 0.20 × pop_density_norm
final_score = 0.70 × geo_score + 0.30 × web_score
```

`geo_score` is computed once nationally and cached; it only changes if the underlying inputs are
recomputed. Only the top 20 per province get a `web_score` and full AI writeup — the rest have
`geo_score` alone (see [Dataset catalog](#dataset-catalog)).

Agents never raise: failures append to an `errors` list in shared state, and the pipeline degrades
gracefully (synthetic fallbacks for solar/demographic data if GEE or PSA is unreachable) rather
than crashing a batch run.

## The data-integrity journey

Helio didn't start with real data. Getting it there was most of the actual engineering work, and
it's worth telling honestly — this is the part that would fool a casual reviewer:

- **Solar irradiance was 100% fabricated for months and looked fine.** The code read the wrong
  output field from Google Earth Engine (`reduceRegions` names its output after the *reducer*, not
  the band), so every query silently returned null and a hash-based fallback quietly covered for
  all 1,622 municipalities — plausible range, plausible geographic variation, and an earlier
  session's notes wrongly declared it done. Caught by tracing values back through an MD5
  reproduction test.
- **Income and population were name-hashes, not census data**, from the first prototype through
  session 7. Replaced with the Philippine Statistics Authority's real PSGC income classification
  and 2024 population (PSA's site blocks programmatic downloads; sourced from a GitHub mirror of
  the same publication, `yng-me/psgc`).
- **33 major cities were silently missing** — Quezon City, Makati, Cebu City, Davao City among
  them — because Highly Urbanized Cities sit differently in the admin-boundary package and every
  province loader skipped them. Fixing this exposed a second bug: the geocoder's queries for these
  cities were malformed and fell back to fabricated coordinates, caught only because one city
  landed 1,100 km from where it should have been.
- **"Top 20" selection was alphabetical, not score-based**, for the platform's entire life until
  caught: truncating a dict in database insertion order instead of sorting by score meant a
  province's real best prospects could be silently excluded in favor of towns that sorted early.
  Worst case: a province's two *worst* municipalities got a paid Places lookup and AI writeup while
  its true #13 and #14 never did. Fixed by sorting on `geo_score` before truncating, then
  re-running every affected province.
- **Land area has no authoritative government source at all** — PSA doesn't publish one. Helio
  computes it from [geoBoundaries](https://www.geoboundaries.org) municipal polygons via true
  geodesic area on the WGS84 ellipsoid, matched by point-in-polygon against real coordinates.
  Disclosed as a GIS-derived estimate (~5–20% deviation from official cadastral figures, worst in
  mountainous terrain), not an authoritative legal area.

**What's still honestly fabricated:** 22 municipalities (Manila's 14 historic districts plus 8
BARMM Special Geographic Area barangays) have no PSA income/population record at any level Helio
can reach, and fall back to a name-hash; 9 of the same group have jittered rather than geocoded
coordinates. These are structural gaps in the source data, not fetch failures — every affected row
is flagged in `exports/helio_dataset_data_dictionary.csv`, which recommends treating them as
`NULL`/not-applicable rather than trusting the fabricated value.

## Dataset catalog

Two committed files are the canonical snapshot of everything Helio knows:

- **`exports/helio_full_dataset.csv`** — one row per municipality (1,655 rows, 20 columns):
  identifiers, geo inputs and their normalized scores, AI outputs (`final_score`, `web_score`,
  `tier`, `assessment`, `opportunities`, `risks`) for the 1,487 municipalities that reached a
  province's top 20, and coordinates throughout.
- **`exports/helio_dataset_data_dictionary.csv`** — field-by-field definition, formula, and source
  for all 20 columns, with every caveat above and its row count. Read this before trusting any
  individual number.

Underlying both: `data/helio.db` (SQLite) — runs, 30-day-cached web intelligence, and the
`geo_scores` table the exports are generated from — and `kb/index/`, the ChromaDB store the
chatbot queries at runtime.

## Current results

- **1,655 municipalities and cities** scored, across **118 of 118** province/HUC groupings —
  full national coverage.
- **1,487 (90%)** have a complete AI assessment, tier, opportunity, and risk; the remaining 168
  have `geo_score` only, by design — they ranked below their province's top 20, and the pipeline
  intentionally skips the paid Places lookup + LLM call on them (see [Roadmap](#roadmap)).
- **98.1%** of solar values and **~98.6%** of income/population values are real, not synthetic
  fallback — the residual gaps are the structurally-unresolvable rows documented above.
- Confidence tiers across the 1,487 assessed: 144 HIGH, 1,311 MEDIUM (incl. 7 MEDIUM-HIGH), 25 LOW.

## The explorer app

`app.py` (Streamlit) is a **dataset-first explorer**, not a pipeline runner — it reads exclusively
from `data/helio.db` and makes zero live Google Places/Tavily calls. It gives a salesperson three
ways into the data:

- **National map** — every scored municipality as a color-coded marker (green/orange/red by
  `final_score` tier, gray for geo-only); legend swatches are generated from the exact same color
  values as the markers, so they can never visually drift apart. Hovering a marker shows a
  labeled, small-font tooltip — Geo Score, Web Score, and Solar Opportunity Score each called out
  by name, not a single unlabeled number. Drilling into a municipality rings it on the map and
  shows a **"🧮 Score breakdown"** expander with every raw and normalized input behind its
  `geo_score` and `web_score` — not just the final numbers, the full formula.
- **Persistent chat** — RAG over the knowledge base, grounded per-question in a DB-sourced fact
  block for whichever municipality the question actually names (not pure semantic search alone,
  which doesn't reliably rank one exact-name match among ~29k similarly-worded profile chunks).
- **Self-healing province reports** — a municipality's assessment can be lazily re-synthesized
  on drill-down (LLM-only, zero new Places/Tavily calls) whenever it predates a data fix, which
  used to leave the province's downloadable report quietly frozen at old numbers. The report now
  regenerates itself from live data the moment it's shown stale, listing any still-unassessed
  municipalities in the province honestly rather than omitting or fabricating them.

## Roadmap

One direction remains open:

- **Full below-top-20 coverage** — the 168 geo-only municipalities could get a full AI writeup
  for an estimated ~$2.80 in Google Places calls (most already have cached web intel from the
  earlier, since-fixed selection bug). Cheap, but not run without an explicit ask.
