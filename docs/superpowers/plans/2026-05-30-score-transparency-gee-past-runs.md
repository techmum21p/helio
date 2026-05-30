# Score Transparency, GEE Precompute & Past Runs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Surface per-municipality score components (irradiance, income, pop density, annual yield) on the map/sidebar/reports, replace synthetic solar estimates with real GEE data in the precompute script, and add a dedicated paginated Past Runs page.

**Architecture:** Three additive features share a DB foundation (new `run_results` columns). Feature 1 threads component data from synthesis → DB write → UI. Feature 2 updates the standalone precompute script only. Feature 3 adds a new Streamlit page backed by a `list_runs()` change.

**Tech Stack:** SQLite (ALTER TABLE migrations), LangGraph agents (synthesis.py), Streamlit + Folium (app.py), Google Earth Engine Python SDK (precompute script), pytest.

---

## File Map

| File | Change |
|---|---|
| `agents/db_store.py` | `_migrate()`: add 3 columns; `complete_run()`: write them; `load_run()`: read with fallback JOIN; `list_runs()`: INNER JOIN reports, default limit=1000 |
| `agents/synthesis.py` | Add `solar_irradiance`, `solar_yield_kwh`, `pop_density` to each `top_targets` entry |
| `agents/report_gen.py` | Add Score Breakdown table section to `REPORT_PROMPT` |
| `app.py` | Rich map popup; 4-col metrics sidebar; `📚 Past Runs` nav + page |
| `scripts/precompute_geo_scores.py` | `fetch_gee_irradiance_batch`; `_init_gee`; resume logic; replace synthetic solar; batch commit |
| `tests/test_db_store.py` | New tests for 3 new columns in migrate/complete_run/load_run; list_runs INNER JOIN |
| `tests/test_synthesis_weights.py` | New test: top_targets entries contain solar_irradiance, solar_yield_kwh, pop_density |
| `tests/test_precompute.py` | New tests: `_get_all_municipalities` solar=None; `fetch_gee_irradiance_batch` mock; `_load_existing_solar` |

---

## Task 1: DB Migration — add 3 columns to `run_results`

**Files:**
- Modify: `agents/db_store.py:106-116` (`_migrate`)
- Modify: `agents/db_store.py:140-182` (`complete_run`)
- Modify: `agents/db_store.py:280-332` (`load_run`)
- Modify: `tests/test_db_store.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_db_store.py` (after the last test):

```python
def test_migrate_adds_score_component_columns(fresh_db):
    from agents import db_store as ds
    conn = sqlite3.connect(str(fresh_db))
    cols = [r[1] for r in conn.execute("PRAGMA table_info(run_results)").fetchall()]
    conn.close()
    assert "solar_irradiance" in cols
    assert "solar_yield_kwh" in cols
    assert "pop_density" in cols


def test_complete_run_writes_component_fields(fresh_db):
    from agents.db_store import create_run, complete_run
    create_run("run_comp", "Laguna", "Laguna")
    targets = [{
        "municipality": "Biñan", "province": "Laguna", "region": "IV-A",
        "geo_score": 0.7, "web_score": 0.4, "final_score": 0.61,
        "tier": "HIGH", "assessment": "Good", "opportunity": "Solar", "risk": "Rain",
        "solar_irradiance": 5.42,
        "solar_yield_kwh": 1587.0,
        "pop_density": 850.3,
    }]
    complete_run("run_comp", targets)
    conn = sqlite3.connect(str(fresh_db))
    row = conn.execute(
        "SELECT solar_irradiance, solar_yield_kwh, pop_density FROM run_results WHERE run_id='run_comp'"
    ).fetchone()
    conn.close()
    assert row[0] == pytest.approx(5.42)
    assert row[1] == pytest.approx(1587.0)
    assert row[2] == pytest.approx(850.3)


def test_load_run_returns_component_fields(fresh_db):
    from agents.db_store import create_run, complete_run, save_report, load_run
    create_run("run_load", "Laguna", "Laguna")
    targets = [{
        "municipality": "Biñan", "province": "Laguna", "region": "IV-A",
        "income_class": "2nd", "population": 80000,
        "geo_score": 0.7, "web_score": 0.4, "final_score": 0.61,
        "tier": "HIGH", "assessment": "Good", "opportunity": "Solar", "risk": "Rain",
        "solar_irradiance": 5.42,
        "solar_yield_kwh": 1587.0,
        "pop_density": 850.3,
    }]
    complete_run("run_load", targets)
    save_report("run_load", "Laguna", None, "# Report", "/reports/r.md")
    result = load_run("run_load")
    t = result["top_targets"][0]
    assert t["solar_irradiance"] == pytest.approx(5.42)
    assert t["solar_yield_kwh"] == pytest.approx(1587.0)
    assert t["pop_density"] == pytest.approx(850.3)


def test_load_run_fallback_join_for_old_rows(fresh_db):
    """Rows with NULL solar_irradiance in run_results fall back to geo_scores JOIN."""
    import sqlite3 as _sq
    from agents.db_store import create_run, load_run
    conn = _sq.connect(str(fresh_db))
    # Insert municipality
    conn.execute(
        "INSERT INTO municipalities (name, province, region) VALUES ('OldTown', 'OldProv', 'R')"
    )
    muni_id = conn.execute("SELECT id FROM municipalities WHERE name='OldTown'").fetchone()[0]
    # Insert geo_scores with solar data
    conn.execute(
        """INSERT INTO geo_scores (municipality_id, solar_irradiance, pop_density)
           VALUES (?, 5.1, 300.0)""",
        (muni_id,),
    )
    # Insert run + run_results WITHOUT solar_irradiance (simulates old row)
    conn.execute(
        "INSERT INTO runs (id, location, status) VALUES ('old_run', 'OldProv', 'done')"
    )
    conn.execute(
        """INSERT INTO run_results (run_id, municipality_id, geo_score, web_score,
           final_score, tier)
           VALUES ('old_run', ?, 0.5, 0.3, 0.46, 'MEDIUM')""",
        (muni_id,),
    )
    conn.execute(
        """INSERT INTO reports (run_id, province, slug, markdown, file_path)
           VALUES ('old_run', 'OldProv', 'oldprov_old_run', '# R', '/r.md')"""
    )
    conn.commit()
    conn.close()

    result = load_run("old_run")
    assert result is not None
    t = result["top_targets"][0]
    assert t["solar_irradiance"] == pytest.approx(5.1)
    assert t["pop_density"] == pytest.approx(300.0)
    assert t["solar_yield_kwh"] == pytest.approx(5.1 * 365 * 0.80, abs=1.0)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/aireesm4/Python_Projects/helio && source .venv_helios/bin/activate
pytest tests/test_db_store.py::test_migrate_adds_score_component_columns \
       tests/test_db_store.py::test_complete_run_writes_component_fields \
       tests/test_db_store.py::test_load_run_returns_component_fields \
       tests/test_db_store.py::test_load_run_fallback_join_for_old_rows -v
```

Expected: FAIL (columns don't exist yet)

- [ ] **Step 3: Implement `_migrate()` — add 3 new columns**

Replace the current `_migrate()` function in `agents/db_store.py` (lines 106–116):

```python
def _migrate() -> None:
    """Add missing columns to tables if not present (idempotent)."""
    conn = _get_conn()
    try:
        conn.execute("ALTER TABLE web_intel_cache ADD COLUMN web_score REAL")
        conn.commit()
        logger.info("db_store: added web_score column to web_intel_cache")
    except Exception:
        pass
    for col, typedef in [
        ("solar_irradiance", "REAL"),
        ("solar_yield_kwh",  "REAL"),
        ("pop_density",      "REAL"),
    ]:
        try:
            conn.execute(f"ALTER TABLE run_results ADD COLUMN {col} {typedef}")
            conn.commit()
            logger.info(f"db_store: added {col} column to run_results")
        except Exception:
            pass
    conn.close()
```

- [ ] **Step 4: Implement `complete_run()` — write 3 new columns**

Replace the `conn.execute("""INSERT INTO run_results ...` block inside `complete_run()` (currently at lines ~165–178). The full updated `complete_run` function:

```python
def complete_run(run_id: str, top_targets: list) -> None:
    conn = _get_conn()
    try:
        conn.execute(
            "UPDATE runs SET status='done', completed_at=? WHERE id=?",
            (datetime.now(timezone.utc).isoformat(), run_id),
        )
        for t in top_targets:
            muni_name = t.get("municipality", "")
            province = t.get("province", "")
            region = t.get("region", "")
            if muni_name:
                conn.execute(
                    """INSERT OR IGNORE INTO municipalities
                       (name, province, region, lat, lon, area_km2, population, income_class)
                       VALUES (?, ?, ?, NULL, NULL, NULL, ?, ?)""",
                    (muni_name, province, region,
                     t.get("population"), t.get("income_class")),
                )
            row = conn.execute(
                "SELECT id FROM municipalities WHERE name=? AND province=?",
                (muni_name, province),
            ).fetchone()
            muni_id = row["id"] if row else None
            conn.execute(
                """INSERT INTO run_results
                   (run_id, municipality_id, geo_score, web_score, final_score,
                    tier, assessment, opportunities, risks,
                    solar_irradiance, solar_yield_kwh, pop_density)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    run_id, muni_id,
                    t.get("geo_score"), t.get("web_score"), t.get("final_score"),
                    t.get("tier"), t.get("assessment"),
                    json.dumps([t.get("opportunity", "")]),
                    json.dumps([t.get("risk", "")]),
                    t.get("solar_irradiance"),
                    t.get("solar_yield_kwh"),
                    t.get("pop_density"),
                ),
            )
        conn.commit()
    except Exception as e:
        logger.error(f"db_store.complete_run failed: {e}")
    finally:
        conn.close()
```

- [ ] **Step 5: Implement `load_run()` — read columns with fallback JOIN**

Replace the `result_rows = conn.execute(...)` SELECT and the `top_targets.append(...)` block inside `load_run()` (currently at lines ~286–314):

```python
        result_rows = conn.execute(
            """SELECT rr.geo_score, rr.web_score, rr.final_score, rr.tier,
                      rr.assessment, rr.opportunities, rr.risks,
                      rr.solar_irradiance, rr.solar_yield_kwh, rr.pop_density,
                      COALESCE(m.name, '')     AS municipality_name,
                      COALESCE(m.province, '') AS province,
                      COALESCE(m.region, '')   AS region,
                      m.income_class, m.population,
                      g.solar_irradiance AS gs_solar_irradiance,
                      g.pop_density      AS gs_pop_density
               FROM run_results rr
               LEFT JOIN municipalities m ON m.id = rr.municipality_id
               LEFT JOIN geo_scores g    ON g.municipality_id = rr.municipality_id
               WHERE rr.run_id = ?
               ORDER BY rr.final_score DESC""",
            (run_id,),
        ).fetchall()
        top_targets = []
        for r in result_rows:
            solar_irr   = r["solar_irradiance"] or r["gs_solar_irradiance"] or 5.0
            pop_dens    = r["pop_density"]       or r["gs_pop_density"]       or 0.0
            solar_yield = r["solar_yield_kwh"]   or round(solar_irr * 365 * 0.80, 0)
            top_targets.append({
                "municipality":    r["municipality_name"] or "",
                "province":        r["province"] or "",
                "region":          r["region"] or "",
                "income_class":    r["income_class"] or "",
                "population":      r["population"] or 0,
                "geo_score":       r["geo_score"],
                "web_score":       r["web_score"],
                "final_score":     r["final_score"],
                "tier":            r["tier"],
                "assessment":      r["assessment"] or "",
                "opportunity":     (json.loads(r["opportunities"] or "[]") or [""])[0],
                "risk":            (json.loads(r["risks"] or "[]") or [""])[0],
                "solar_irradiance": solar_irr,
                "solar_yield_kwh":  solar_yield,
                "pop_density":      pop_dens,
            })
```

- [ ] **Step 6: Run tests to verify they pass**

```bash
pytest tests/test_db_store.py -v
```

Expected: All pass (including 4 new tests).

- [ ] **Step 7: Commit**

```bash
git add agents/db_store.py tests/test_db_store.py
git commit -m "feat: add solar_irradiance, solar_yield_kwh, pop_density to run_results; fallback JOIN in load_run"
```

---

## Task 2: Synthesis — add component fields to `top_targets`

**Files:**
- Modify: `agents/synthesis.py:152-196` (`synthesis_agent`)
- Modify: `tests/test_synthesis_weights.py`

- [ ] **Step 1: Write the failing test**

Open `tests/test_synthesis_weights.py` and add at the end:

```python
def test_synthesis_agent_top_targets_have_component_fields():
    """synthesis_agent must include solar_irradiance, solar_yield_kwh, pop_density in top_targets."""
    from graph.state import SolarLeadState
    from agents.synthesis import synthesis_agent
    from unittest.mock import patch

    geo_scores = {
        "Biñan": {
            "geo_score": 0.7, "solar_norm": 0.8, "pop_norm": 0.6, "income_norm": 0.9,
            "solar_raw": 5.42, "solar_yield_kwh": 1587.0, "population_raw": 80000,
            "income_class": "2nd", "province": "Laguna", "region": "IV-A",
            "is_urban": True,
        },
    }

    fake_narrative = {
        "assessment": "Good area.", "confidence": "HIGH",
        "opportunity": "Malls", "risk": "Flooding",
    }

    state = SolarLeadState(
        location="Laguna", run_id="t01",
        geo_scores=geo_scores, geo_geojson=None,
        web_intel={}, final_scores=None, top_targets=None,
        report_markdown=None, report_path=None,
        chat_history=[], kb_updated=False, errors=[], status="running",
    )

    with patch("agents.synthesis.synthesize_municipality", return_value=fake_narrative):
        result = synthesis_agent(state)

    t = result["top_targets"][0]
    assert "solar_irradiance" in t, "solar_irradiance missing from top_targets entry"
    assert "solar_yield_kwh"  in t, "solar_yield_kwh missing from top_targets entry"
    assert "pop_density"      in t, "pop_density missing from top_targets entry"
    assert t["solar_irradiance"] == pytest.approx(5.42)
    assert t["solar_yield_kwh"]  == pytest.approx(round(5.42 * 365 * 0.80, 0))
    assert t["pop_density"]      == pytest.approx(80000 / 500)  # fallback: population_raw / 500
```

Also add `import pytest` to the top of `tests/test_synthesis_weights.py` if not present.

- [ ] **Step 2: Run the test to verify it fails**

```bash
pytest tests/test_synthesis_weights.py::test_synthesis_agent_top_targets_have_component_fields -v
```

Expected: FAIL (keys not present)

- [ ] **Step 3: Implement — add 3 fields to `final_scores[municipality]` dict**

In `agents/synthesis.py`, in the `synthesis_agent` function, update the `final_scores[municipality] = {...}` assignment (currently at lines ~166–180) to add the 3 new fields:

```python
        final_scores[municipality] = {
            "geo_score":        geo.get("geo_score", 0),
            "web_score":        web_score,
            "final_score":      final_score,
            "solar_kwh_estimate": round(geo.get("solar_raw", 5.0) * 365 * 0.8, 0),
            "solar_irradiance": geo.get("solar_raw", 5.0),
            "solar_yield_kwh":  round(geo.get("solar_raw", 5.0) * 365 * 0.80, 0),
            "pop_density":      geo.get("pop_density",
                                        round(geo.get("population_raw", 0) / 500, 1)),
            "tier":             narrative["confidence"],
            "assessment":       narrative["assessment"],
            "opportunity":      narrative["opportunity"],
            "risk":             narrative["risk"],
            "province":         geo.get("province", ""),
            "region":           geo.get("region", ""),
            "income_class":     geo.get("income_class", ""),
            "population":       int(geo.get("population_raw", 0)),
            "is_urban":         geo.get("is_urban", False),
        }
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
pytest tests/test_synthesis_weights.py -v
```

Expected: All pass.

- [ ] **Step 5: Commit**

```bash
git add agents/synthesis.py tests/test_synthesis_weights.py
git commit -m "feat: add solar_irradiance, solar_yield_kwh, pop_density to synthesis top_targets"
```

---

## Task 3: Report Prompt — add Score Breakdown section

**Files:**
- Modify: `agents/report_gen.py:19-47` (`REPORT_PROMPT`)

No new test needed — the prompt is a string constant; integration is covered by existing report gen tests.

- [ ] **Step 1: Add Score Breakdown section to `REPORT_PROMPT`**

In `agents/report_gen.py`, update `REPORT_PROMPT` to add the Score Breakdown section after `## Top Target Areas`:

```python
REPORT_PROMPT = """You are writing a solar installation market intelligence report for a small business owner in the Philippines.

Location analyzed: {location}
Date: {date}
Top {n} target municipalities identified.

Full ranked data:
{targets_json}

Write a professional but readable markdown report with these sections:

# Solar Installation Opportunity Report: {location}
## Executive Summary
(3-4 sentences. Total opportunity, top region, key recommendation.)

## Top Target Areas
(Table with columns: Rank | Municipality | Score | Tier | Key Opportunity)

## Score Breakdown
(Table with columns: Municipality | Irradiance (kWh/m²/day) | Income Class | Pop Density (ppl/km²) | Annual Yield (kWh/kWp) | Final Score)

## Detailed Profiles
(For each of the top 5 targets, one paragraph with assessment, opportunity, and risk.)

## Recommended Action Plan
(3 concrete next steps for the sales team.)

## Methodology Note
(Brief 2-3 sentence note on data sources used.)

Keep it grounded and factual. Do not invent statistics not present in the data.
"""
```

- [ ] **Step 2: Verify existing tests still pass**

```bash
pytest tests/ -v -k "report"
```

Expected: Pass (no report gen unit tests that check prompt content).

- [ ] **Step 3: Commit**

```bash
git add agents/report_gen.py
git commit -m "feat: add Score Breakdown table section to REPORT_PROMPT"
```

---

## Task 4: App — rich map popup + sidebar metrics grid

**Files:**
- Modify: `app.py:173-234` (Map & Scores page)

- [ ] **Step 1: Update map popup and tooltip**

In `app.py`, inside the `if page == "🗺️ Map & Scores":` block, replace the map-building section. The change: (1) add `target_map` lookup dict, (2) enrich popup HTML, (3) update tooltip.

Replace from `score_map = {t["municipality"]: ...` through the `st_folium(...)` call:

```python
        score_map  = {t["municipality"]: t["final_score"]  for t in top_targets}
        target_map = {t["municipality"]: t                  for t in top_targets}

        m = folium.Map(location=[12.5, 122.5], zoom_start=7, tiles="CartoDB positron")

        if geo_geojson:
            geo_data = json.loads(geo_geojson)
            for feature in geo_data.get("features", []):
                props = feature.get("properties", {})
                name  = props.get("name", "")
                geom  = feature.get("geometry", {})

                if geom.get("type") != "Point":
                    continue

                lon, lat = geom["coordinates"]
                score    = score_map.get(name, props.get("geo_score", 0))
                target   = target_map.get(name, {})

                if score >= 0.65:
                    color = "#2ecc71"
                elif score >= 0.35:
                    color = "#f39c12"
                else:
                    color = "#e74c3c"

                radius    = 6 + score * 14
                irr       = target.get("solar_irradiance", 0)
                income    = target.get("income_class", "N/A")
                pop       = target.get("population", 0)
                yield_kwp = target.get("solar_yield_kwh", 0)
                yield_5kwp = int(yield_kwp * 5)
                tier      = target.get("tier", "")
                province  = target.get("province", props.get("province", ""))

                popup_html = (
                    f"<b>{name}</b> ({province})<br>"
                    f"────────────────────<br>"
                    f"Final Score: {score:.3f} &nbsp;|&nbsp; Tier: {tier}<br>"
                    f"&#9728; Irradiance: {irr:.2f} kWh/m&#178;/day<br>"
                    f"&#128200; Income: {income} class<br>"
                    f"&#128101; Population: {pop:,}<br>"
                    f"&#9889; Yield: {yield_kwp:,.0f} kWh/kWp/yr "
                    f"(~{yield_5kwp:,} kWh/yr for 5 kWp)"
                )

                folium.CircleMarker(
                    location=[lat, lon],
                    radius=radius,
                    color=color,
                    fill=True,
                    fill_color=color,
                    fill_opacity=0.75,
                    weight=1.5,
                    popup=folium.Popup(popup_html, max_width=260),
                    tooltip=f"{name}: {score:.3f} | {irr:.1f} kWh/m²/day",
                ).add_to(m)

        st_folium(m, width=700, height=500)
```

- [ ] **Step 2: Replace sidebar score expander with 4-column metrics grid**

In `app.py`, inside the `with col2:` block, replace the `for i, t in enumerate(top_targets[:10], 1):` loop:

```python
            st.subheader(f"Top {min(10, len(top_targets))} Targets")
            for i, t in enumerate(top_targets[:10], 1):
                tier_color = {"HIGH": "🟢", "MEDIUM": "🟡", "LOW": "🔴"}.get(t["tier"], "⚪")
                with st.expander(f"{i}. {t['municipality']} {tier_color} — `{t['final_score']:.3f}`"):
                    c1, c2, c3, c4 = st.columns(4)
                    c1.metric("☀ Irradiance",  f"{t.get('solar_irradiance', 0):.2f} kWh/m²/day")
                    c2.metric("📈 Income",      f"{t.get('income_class', 'N/A')} class")
                    c3.metric("👥 Population",  f"{t.get('population', 0):,}")
                    c4.metric("⚡ Yield",       f"{t.get('solar_yield_kwh', 0):,.0f} kWh/kWp/yr")
                    st.write(f"**Assessment:** {t.get('assessment', 'N/A')}")
                    st.write(f"**Opportunity:** {t.get('opportunity', 'N/A')}")
                    st.write(f"**Risk:** {t.get('risk', 'N/A')}")
```

- [ ] **Step 3: Verify app starts without error**

```bash
cd /Users/aireesm4/Python_Projects/helio && source .venv_helios/bin/activate
python -c "import app" 2>&1 | head -20
```

Expected: No import errors.

- [ ] **Step 4: Commit**

```bash
git add app.py
git commit -m "feat: rich map popup with score components; 4-col metrics grid in sidebar expander"
```

---

## Task 5: DB + App — `list_runs` filter & Past Runs page

**Files:**
- Modify: `agents/db_store.py:253-277` (`list_runs`)
- Modify: `app.py:55-58` (nav radio), `app.py` (new page section)
- Modify: `tests/test_db_store.py`

- [ ] **Step 1: Write failing test for `list_runs` INNER JOIN**

Add to `tests/test_db_store.py`:

```python
def test_list_runs_excludes_runs_without_reports(fresh_db):
    from agents.db_store import create_run, complete_run, save_report, list_runs
    # run_with_report: has a report
    create_run("r_report", "Cebu", "Cebu")
    complete_run("r_report", [])
    save_report("r_report", "Cebu", None, "# Cebu", "/r.md")
    # run_no_report: completed but no report
    create_run("r_noreport", "Davao", "Davao")
    complete_run("r_noreport", [])

    runs = list_runs()
    ids = [r["id"] for r in runs]
    assert "r_report"   in ids
    assert "r_noreport" not in ids


def test_list_runs_default_limit_is_1000(fresh_db):
    from agents import db_store as ds
    import inspect
    sig = inspect.signature(ds.list_runs)
    assert sig.parameters["limit"].default == 1000
```

- [ ] **Step 2: Run failing tests**

```bash
pytest tests/test_db_store.py::test_list_runs_excludes_runs_without_reports \
       tests/test_db_store.py::test_list_runs_default_limit_is_1000 -v
```

Expected: FAIL

- [ ] **Step 3: Update `list_runs()` in `agents/db_store.py`**

Replace `list_runs` (lines 253–277) with:

```python
def list_runs(limit: int = 1000) -> list[dict]:
    conn = _get_conn()
    try:
        rows = conn.execute(
            """
            SELECT r.id, r.location, r.province, r.status, r.created_at,
                   COUNT(rr.id) AS target_count,
                   MAX(rr.final_score) AS top_score,
                   (SELECT tier FROM run_results
                    WHERE run_id = r.id ORDER BY final_score DESC LIMIT 1) AS top_tier
            FROM runs r
            INNER JOIN reports rep ON rep.run_id = r.id
            LEFT JOIN run_results rr ON rr.run_id = r.id
            WHERE r.status IN ('done', 'failed')
            GROUP BY r.id
            ORDER BY r.created_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]
    except Exception as e:
        logger.error(f"db_store.list_runs failed: {e}")
        return []
    finally:
        conn.close()
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_db_store.py -v
```

Expected: All pass (including the 2 new tests). Note: `test_list_runs_returns_done_runs_newest_first` calls `list_runs()` with no args — it uses `complete_run` but never calls `save_report`, so with the new INNER JOIN it will return 0 rows. Update that test to also call `save_report`:

```python
def test_list_runs_returns_done_runs_newest_first(fresh_db):
    import time
    from agents.db_store import create_run, complete_run, save_report, list_runs
    create_run("r1", "Laguna", "Laguna")
    complete_run("r1", [])
    save_report("r1", "Laguna", None, "# R1", "/r1.md")
    time.sleep(1.05)
    create_run("r2", "Cebu", "Cebu")
    complete_run("r2", [])
    save_report("r2", "Cebu", None, "# R2", "/r2.md")
    runs = list_runs()
    assert len(runs) >= 2
    locations = [r["location"] for r in runs]
    assert locations.index("Cebu") < locations.index("Laguna")
```

- [ ] **Step 5: Add Past Runs page to `app.py`**

In `app.py`, update the nav radio (line ~58):

```python
    page = st.radio("Navigate", ["🗺️ Map & Scores", "📄 Report", "💬 Chatbot", "⚙️ Admin", "📚 Past Runs"])
```

Add the Past Runs page section at the end of `app.py` (after the Admin `elif` block):

```python
# ── Page: Past Runs ────────────────────────────────────────────────────────────
elif page == "📚 Past Runs":
    st.title("📚 Past Runs")

    if "runs_page" not in st.session_state:
        st.session_state.runs_page = 0

    all_runs = db_store.list_runs(limit=1000)

    if not all_runs:
        st.info("No completed runs with reports yet.")
    else:
        page_size = 20
        total_pages = max(1, (len(all_runs) + page_size - 1) // page_size)
        current_page = min(st.session_state.runs_page, total_pages - 1)
        st.session_state.runs_page = current_page
        page_runs = all_runs[current_page * page_size : (current_page + 1) * page_size]

        for run in page_runs:
            try:
                dt = datetime.fromisoformat(run["created_at"])
                date_str = dt.strftime("%b %d, %Y")
            except Exception:
                date_str = str(run["created_at"])[:10]

            top_score = run.get("top_score")
            score_str = f"{top_score:.2f}" if top_score else "—"
            tier_icon = {"HIGH": "🟢", "MEDIUM": "🟡", "LOW": "🔴"}.get(
                run.get("top_tier", ""), "⚪"
            )
            header = (
                f"{run['location']}  ·  {date_str}  ·  "
                f"{run.get('target_count', 0)} targets  ·  top {score_str} {tier_icon}"
            )

            with st.expander(header):
                loaded = db_store.load_run(run["id"])
                if loaded:
                    md = loaded.get("report_markdown", "")
                    if md:
                        st.markdown(md)
                    report_path = loaded.get("report_path")
                    if report_path:
                        try:
                            with open(report_path, "r", encoding="utf-8") as f:
                                st.download_button(
                                    "⬇️ Download Report (.md)",
                                    data=f.read(),
                                    file_name=f"solar_report_{run['id']}.md",
                                    mime="text/markdown",
                                    key=f"dl_{run['id']}",
                                )
                        except FileNotFoundError:
                            pass

        col_prev, col_mid, col_next = st.columns([1, 2, 1])
        with col_prev:
            if st.button("← Previous", disabled=(current_page == 0), key="runs_prev"):
                st.session_state.runs_page -= 1
                st.rerun()
        with col_mid:
            st.markdown(
                f"<div style='text-align:center'>Page {current_page + 1} of {total_pages}</div>",
                unsafe_allow_html=True,
            )
        with col_next:
            if st.button("Next →", disabled=(current_page >= total_pages - 1), key="runs_next"):
                st.session_state.runs_page += 1
                st.rerun()
```

- [ ] **Step 6: Verify app imports cleanly**

```bash
python -c "import app" 2>&1 | head -20
```

Expected: No errors.

- [ ] **Step 7: Run all db_store tests**

```bash
pytest tests/test_db_store.py -v
```

Expected: All pass.

- [ ] **Step 8: Commit**

```bash
git add agents/db_store.py app.py tests/test_db_store.py
git commit -m "feat: list_runs INNER JOIN reports; add Past Runs page with pagination"
```

---

## Task 6: Precompute Script — real GEE irradiance

**Files:**
- Modify: `scripts/precompute_geo_scores.py`
- Modify: `tests/test_precompute.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_precompute.py`:

```python
def test_get_all_municipalities_solar_is_none():
    """After Task 6 change, _get_all_municipalities returns solar=None (to be filled by GEE)."""
    from precompute_geo_scores import _get_all_municipalities
    units = _get_all_municipalities()
    # All solar values should be None (placeholder for GEE)
    assert all(u["solar"] is None for u in units[:20]), \
        "Expected solar=None for all units; GEE fill hasn't happened yet"


def test_fetch_gee_irradiance_batch_uses_reduceRegions(monkeypatch):
    """fetch_gee_irradiance_batch calls ee.FeatureCollection().reduceRegions()."""
    from precompute_geo_scores import fetch_gee_irradiance_batch

    # Minimal mock of the GEE ee module
    class MockReduceResult:
        def getInfo(self):
            return {
                "features": [
                    {"properties": {"name": "Town0", "province": "P",
                                    "surface_solar_radiation_downwards_sum": 18_000_000.0}},
                    {"properties": {"name": "Town1", "province": "P",
                                    "surface_solar_radiation_downwards_sum": None}},
                ]
            }

    class MockDataset:
        def reduceRegions(self, **kwargs):
            return MockReduceResult()
        def filterDate(self, *a): return self
        def select(self, *a): return self
        def mean(self): return self

    class MockImageCollection:
        def __init__(self, *a): pass
        def filterDate(self, *a): return MockDataset()
        def select(self, *a): return self
        def mean(self): return self

    class MockFC:
        def __init__(self, *a): pass

    class MockGeometry:
        def buffer(self, *a): return self

    class MockGeometryPoint:
        def __call__(self, *a): return MockGeometry()

    class MockReducer:
        @staticmethod
        def mean(): return "mean"

    class MockEE:
        Geometry = type("G", (), {"Point": staticmethod(lambda c: MockGeometry())})()
        FeatureCollection = MockFC
        Feature = lambda *a, **kw: {"geometry": None, "properties": kw.get("properties", {})}
        Reducer = MockReducer
        def ImageCollection(self, *a): return MockDataset()

    ee = MockEE()
    units = [
        {"name": "Town0", "province": "P", "lat": 14.0, "lon": 121.0},
        {"name": "Town1", "province": "P", "lat": 14.1, "lon": 121.1},
    ]
    result = fetch_gee_irradiance_batch(ee, units)
    assert "P:Town0" in result
    assert result["P:Town0"] == pytest.approx(18_000_000.0 / 3_600_000)
    assert result["P:Town1"] is None  # GEE returned null → None


def test_load_existing_solar_returns_dict(temp_db):
    """_load_existing_solar returns {province:name -> float} for rows with solar set."""
    import sqlite3 as _sq
    from precompute_geo_scores import _load_existing_solar

    conn = _sq.connect(str(temp_db))
    conn.execute(
        "INSERT INTO municipalities (name, province, region) VALUES ('A', 'PA', 'R')"
    )
    mid = conn.execute("SELECT id FROM municipalities WHERE name='A'").fetchone()[0]
    conn.execute(
        "INSERT INTO geo_scores (municipality_id, solar_irradiance) VALUES (?, 5.3)",
        (mid,),
    )
    conn.commit()
    conn.close()

    result = _load_existing_solar()
    assert result.get("PA:A") == pytest.approx(5.3)
```

- [ ] **Step 2: Run failing tests**

```bash
pytest tests/test_precompute.py::test_get_all_municipalities_solar_is_none \
       tests/test_precompute.py::test_fetch_gee_irradiance_batch_uses_reduceRegions \
       tests/test_precompute.py::test_load_existing_solar_returns_dict -v
```

Expected: FAIL (functions don't exist yet)

- [ ] **Step 3: Add `_init_gee` (copy from `agents/geo_scoring.py`)**

Add after the existing `INCOME_CLASS_MAP` dict in `scripts/precompute_geo_scores.py` (around line 96), before the `_stable_float` section:

```python
# ── GEE initialization ──────────────────────────────────────────────────────────

def _init_gee():
    """Initialize Google Earth Engine. Returns ee module or None."""
    try:
        import ee
        try:
            ee.Initialize(project=config.GEE_PROJECT_ID)
        except Exception:
            ee.Authenticate()
            ee.Initialize(project=config.GEE_PROJECT_ID)
        print("GEE initialized.")
        return ee
    except ImportError:
        return None
    except Exception as e:
        return None
```

- [ ] **Step 4: Add `fetch_gee_irradiance_batch`**

Add after `_init_gee` (before the `_stable_float` section):

```python
def fetch_gee_irradiance_batch(ee, units: list[dict]) -> dict[str, float | None]:
    """
    Fetch mean annual solar irradiance for a batch of municipalities via GEE reduceRegions.

    Returns {"{province}:{name}": kwh_per_day_or_None} for all units in the batch.
    A None value means GEE returned null for that feature (caller should fall back).
    """
    features = []
    for u in units:
        pt = ee.Geometry.Point([u["lon"], u["lat"]]).buffer(11000)
        features.append(
            ee.Feature(pt, {"name": u["name"], "province": u["province"]})
        )

    fc = ee.FeatureCollection(features)
    dataset = (
        ee.ImageCollection("ECMWF/ERA5_LAND/DAILY_AGGR")
        .filterDate("2023-01-01", "2023-12-31")
        .select("surface_solar_radiation_downwards_sum")
        .mean()
    )

    result_fc = dataset.reduceRegions(
        collection=fc,
        reducer=ee.Reducer.mean(),
        scale=11132,
    ).getInfo()

    result: dict[str, float | None] = {}
    for feat in result_fc.get("features", []):
        props = feat.get("properties", {})
        name     = props.get("name", "")
        province = props.get("province", "")
        raw      = props.get("surface_solar_radiation_downwards_sum")
        kwh      = float(raw) / 3_600_000 if raw is not None else None
        result[f"{province}:{name}"] = kwh

    return result
```

- [ ] **Step 5: Add `_load_existing_solar`**

Add after `fetch_gee_irradiance_batch`:

```python
def _load_existing_solar() -> dict[str, float]:
    """
    Return {"{province}:{name}" -> solar_irradiance} for rows where
    geo_scores.solar_irradiance IS NOT NULL, enabling resume of interrupted runs.
    """
    conn = sqlite3.connect(str(config.HELIO_DB))
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """SELECT m.name, m.province, g.solar_irradiance
               FROM geo_scores g
               JOIN municipalities m ON m.id = g.municipality_id
               WHERE g.solar_irradiance IS NOT NULL"""
        ).fetchall()
        return {f"{r['province']}:{r['name']}": r["solar_irradiance"] for r in rows}
    except Exception:
        return {}
    finally:
        conn.close()
```

- [ ] **Step 6: Add `_upsert_solar_batch` (batch commit helper)**

Add after `_load_existing_solar`:

```python
def _upsert_solar_batch(conn: sqlite3.Connection, units: list[dict]) -> None:
    """Write solar_irradiance to geo_scores for a batch; commits immediately."""
    for u in units:
        if u.get("solar") is None:
            continue
        row = conn.execute(
            "SELECT id FROM municipalities WHERE name=? AND province=?",
            (u["name"], u["province"]),
        ).fetchone()
        if row is None:
            continue
        muni_id = row[0]
        conn.execute(
            """INSERT INTO geo_scores (municipality_id, solar_irradiance, computed_at)
               VALUES (?, ?, CURRENT_TIMESTAMP)
               ON CONFLICT(municipality_id) DO UPDATE SET
                   solar_irradiance = excluded.solar_irradiance,
                   computed_at      = excluded.computed_at""",
            (muni_id, u["solar"]),
        )
    conn.commit()
```

- [ ] **Step 7: Update `_get_all_municipalities()` — `solar=None`**

In `_get_all_municipalities()`, replace the line:
```python
                solar = _stable_float(f"{muni_name}:solar", 4.5, 6.0)
```
with:
```python
                solar = None  # filled by GEE in precompute_geo_scores()
```

- [ ] **Step 8: Update `precompute_geo_scores()` — full GEE flow**

Replace the current `precompute_geo_scores()` function:

```python
def precompute_geo_scores(progress_callback=None) -> None:
    """
    Full pipeline: enumerate municipalities → fetch real GEE irradiance in batches
    → normalize → upsert to DB.

    Exits with error if GEE is not authenticated (never silently uses synthetic values
    during a deliberate precompute run).
    Resumes interrupted runs: skips municipalities that already have solar_irradiance
    in the DB.
    """
    import time

    ee = _init_gee()
    if ee is None:
        print("ERROR: GEE initialization failed.")
        print("Run: earthengine authenticate && earthengine set_project <project-id>")
        sys.exit(1)

    units = _get_all_municipalities()  # solar=None for all

    # Resume: fill in already-fetched solar values
    existing = _load_existing_solar()
    for u in units:
        key = f"{u['province']}:{u['name']}"
        if key in existing:
            u["solar"] = existing[key]

    to_fetch = [u for u in units if u["solar"] is None]
    total_batches = (len(to_fetch) + 199) // 200

    if to_fetch:
        db_conn = sqlite3.connect(str(config.HELIO_DB))
        db_conn.row_factory = sqlite3.Row
        try:
            for batch_idx in range(0, len(to_fetch), 200):
                batch      = to_fetch[batch_idx : batch_idx + 200]
                batch_num  = batch_idx // 200 + 1
                range_str  = f"{batch[0]['name']} … {batch[-1]['name']}"
                t0 = time.time()
                print(f"  Batch {batch_num}/{total_batches}: {len(batch)} munis ({range_str})")

                try:
                    gee_results = fetch_gee_irradiance_batch(ee, batch)
                except Exception as exc:
                    print(f"    WARNING: batch {batch_num} GEE call failed ({exc}); using synthetic fallback")
                    gee_results = {}

                for u in batch:
                    key = f"{u['province']}:{u['name']}"
                    val = gee_results.get(key)
                    if val is not None and val > 0:
                        u["solar"] = val
                    else:
                        if val is None:
                            print(f"    WARNING: GEE returned null for {key}; using synthetic fallback")
                        u["solar"] = _stable_float(f"{u['name']}:solar", 4.5, 6.0)

                _upsert_solar_batch(db_conn, batch)
                elapsed = time.time() - t0
                print(f"    Done in {elapsed:.1f}s")
                time.sleep(1)
        finally:
            db_conn.close()
    else:
        print("All municipalities already have GEE solar data. Skipping fetch.")

    # Fill any remaining None (shouldn't happen, but guard)
    for u in units:
        if u["solar"] is None:
            u["solar"] = _stable_float(f"{u['name']}:solar", 4.5, 6.0)

    units = normalize_and_score(units)
    upsert_to_db(units, progress_callback=progress_callback)
```

- [ ] **Step 9: Run the failing tests to verify they now pass**

```bash
pytest tests/test_precompute.py -v
```

Expected: All pass (including 3 new tests). The `test_fetch_gee_irradiance_batch_uses_reduceRegions` test uses a mock `ee` object so no real GEE call is made.

The `test_get_all_municipalities_each_has_required_fields` test checks `required.issubset(u.keys())` — `solar=None` still satisfies "solar key is present", so it passes.

The `test_normalize_and_score_*` tests pass `solar` as numeric values via `_make_units()`, unchanged.

- [ ] **Step 10: Commit**

```bash
git add scripts/precompute_geo_scores.py tests/test_precompute.py
git commit -m "feat: precompute script uses real GEE irradiance via batched reduceRegions; resume support"
```

---

## Final: Run full test suite

- [ ] **Step 1: Run all tests**

```bash
cd /Users/aireesm4/Python_Projects/helio && source .venv_helios/bin/activate
pytest tests/ -v 2>&1 | tail -30
```

Expected: All tests pass.

- [ ] **Step 2: Verify app imports cleanly**

```bash
python -c "
import app
print('app import OK')
"
```

Expected: `app import OK`
