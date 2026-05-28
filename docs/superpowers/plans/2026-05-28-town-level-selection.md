# Town-Level Location Selection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the free-text location input with cascading Province → Municipality dropdowns backed by a persistent SQLite database, and enable single-municipality pipeline runs.

**Architecture:** A one-time build script (`scripts/build_location_db.py`) populates `data/ph_locations.db` from the `barangay` package. `agents/location_db.py` exposes query helpers. `app.py` renders cascading dropdowns and builds the `location` string (`"Laguna"` or `"Biñan, Laguna"`). `geo_scoring.py` routes on the comma: province mode keeps existing behaviour; municipality mode calls a new `load_single_municipality()` with a fixed-range normalizer for single-row scoring.

**Tech Stack:** Python `sqlite3` (stdlib), `barangay` package (real PH data), `rapidfuzz` (fuzzy matching, already installed), Streamlit session state.

---

## File Map

| Action | File | Responsibility |
|--------|------|----------------|
| Modify | `config.py` | Add `LOCATION_DB` path constant |
| Create | `scripts/build_location_db.py` | One-time DB population from barangay package |
| Create | `agents/location_db.py` | DB query helpers (`get_provinces`, `get_municipalities`, etc.) |
| Create | `tests/test_location_db.py` | Unit tests for location_db |
| Modify | `agents/geo_scoring.py` | `load_single_municipality`, fixed-range normalizer, agent routing |
| Create | `tests/test_geo_scoring_single.py` | Tests for single-municipality scoring |
| Modify | `app.py` | Replace text input with cascading dropdowns |

---

## Task 1: Add LOCATION_DB to config.py

**Files:**
- Modify: `config.py`

- [ ] **Step 1: Add LOCATION_DB path**

Open `config.py`. After the `SESSIONS_DIR` line (line 28), add:

```python
LOCATION_DB = ROOT_DIR / "data" / "ph_locations.db"
```

Do NOT add it to the `for d in [...]` loop — it is a file, not a directory.

The final relevant block should look like:

```python
REPORTS_DIR = ROOT_DIR / "reports"
SESSIONS_DIR = ROOT_DIR / "sessions"
LOCATION_DB = ROOT_DIR / "data" / "ph_locations.db"
```

- [ ] **Step 2: Verify**

```bash
source .venv_helios/bin/activate && python -c "import config; print(config.LOCATION_DB)"
```

Expected: `/path/to/helio/data/ph_locations.db`

- [ ] **Step 3: Commit**

```bash
git add config.py
git commit -m "feat: add LOCATION_DB path to config"
```

---

## Task 2: Create scripts/build_location_db.py

**Files:**
- Create: `scripts/build_location_db.py`

- [ ] **Step 1: Create scripts/ directory and build script**

```bash
mkdir -p /Users/aireesm4/Python_Projects/helio/scripts
```

Create `scripts/build_location_db.py`:

```python
#!/usr/bin/env python3
"""
One-time script to populate data/ph_locations.db from the barangay package.
Run once: python scripts/build_location_db.py
Idempotent — skips if municipalities table already has rows.
"""

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS regions (
    id   INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE
);
CREATE TABLE IF NOT EXISTS provinces (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    name      TEXT NOT NULL,
    region_id INTEGER NOT NULL REFERENCES regions(id)
);
CREATE TABLE IF NOT EXISTS municipalities (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    province_id INTEGER NOT NULL REFERENCES provinces(id)
);
CREATE TABLE IF NOT EXISTS barangays (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL,
    municipality_id INTEGER NOT NULL REFERENCES municipalities(id)
);
CREATE INDEX IF NOT EXISTS idx_provinces_region    ON provinces(region_id);
CREATE INDEX IF NOT EXISTS idx_municipalities_prov ON municipalities(province_id);
CREATE INDEX IF NOT EXISTS idx_barangays_muni      ON barangays(municipality_id);
"""


def build(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.executescript(SCHEMA)

    count = conn.execute("SELECT COUNT(*) FROM municipalities").fetchone()[0]
    if count > 0:
        print(f"Already built ({count} municipalities). Delete {db_path} to rebuild.")
        conn.close()
        return

    import barangay as br
    data = br.BARANGAY

    region_count = prov_count = muni_count = brgy_count = 0

    with conn:
        for region_name, region_data in data.items():
            if not isinstance(region_data, dict):
                continue
            cur = conn.execute("INSERT INTO regions (name) VALUES (?)", (region_name,))
            region_id = cur.lastrowid
            region_count += 1

            for prov_name, prov_data in region_data.items():
                if not isinstance(prov_data, dict):
                    continue
                cur = conn.execute(
                    "INSERT INTO provinces (name, region_id) VALUES (?, ?)",
                    (prov_name, region_id),
                )
                prov_id = cur.lastrowid
                prov_count += 1

                for muni_name, barangays in prov_data.items():
                    cur = conn.execute(
                        "INSERT INTO municipalities (name, province_id) VALUES (?, ?)",
                        (muni_name, prov_id),
                    )
                    muni_id = cur.lastrowid
                    muni_count += 1

                    if isinstance(barangays, list):
                        conn.executemany(
                            "INSERT INTO barangays (name, municipality_id) VALUES (?, ?)",
                            [(b, muni_id) for b in barangays],
                        )
                        brgy_count += len(barangays)

    print(
        f"Built: {region_count} regions, {prov_count} provinces, "
        f"{muni_count} municipalities, {brgy_count} barangays"
    )
    conn.close()


if __name__ == "__main__":
    build(config.LOCATION_DB)
```

- [ ] **Step 2: Run the build script**

```bash
source .venv_helios/bin/activate && python scripts/build_location_db.py
```

Expected output:
```
Built: 18 regions, 85 provinces, 1622 municipalities, 39883 barangays
```

- [ ] **Step 3: Verify idempotency**

```bash
python scripts/build_location_db.py
```

Expected: `Already built (1622 municipalities). Delete ... to rebuild.`

- [ ] **Step 4: Verify DB contents**

```bash
python -c "
import sqlite3, config
conn = sqlite3.connect(str(config.LOCATION_DB))
for table in ['regions', 'provinces', 'municipalities', 'barangays']:
    n = conn.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]
    print(f'{table}: {n}')
conn.close()
"
```

Expected:
```
regions: 18
provinces: 85
municipalities: 1622
barangays: 39883
```

- [ ] **Step 5: Commit**

```bash
git add scripts/build_location_db.py
git commit -m "feat: add location DB build script (regions/provinces/municipalities/barangays)"
```

---

## Task 3: Create agents/location_db.py (TDD)

**Files:**
- Create: `tests/test_location_db.py`
- Create: `agents/location_db.py`

- [ ] **Step 1: Create tests/test_location_db.py**

```python
import sqlite3
import pytest
import config

SCHEMA = """
CREATE TABLE regions (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE);
CREATE TABLE provinces (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, region_id INTEGER NOT NULL);
CREATE TABLE municipalities (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, province_id INTEGER NOT NULL);
CREATE TABLE barangays (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, municipality_id INTEGER NOT NULL);
"""


@pytest.fixture
def test_db(tmp_path, monkeypatch):
    db_path = tmp_path / "test_locations.db"
    monkeypatch.setattr(config, "LOCATION_DB", db_path)

    conn = sqlite3.connect(str(db_path))
    conn.executescript(SCHEMA)
    conn.execute("INSERT INTO regions (name) VALUES ('Region IV-A')")
    conn.execute("INSERT INTO provinces (name, region_id) VALUES ('Laguna', 1)")
    conn.execute("INSERT INTO provinces (name, region_id) VALUES ('Cavite', 1)")
    conn.execute("INSERT INTO municipalities (name, province_id) VALUES ('Biñan', 1)")
    conn.execute("INSERT INTO municipalities (name, province_id) VALUES ('Santa Rosa', 1)")
    conn.execute("INSERT INTO barangays (name, municipality_id) VALUES ('Poblacion', 1)")
    conn.execute("INSERT INTO barangays (name, municipality_id) VALUES ('San Antonio', 1)")
    conn.commit()
    conn.close()
    return db_path


def test_get_provinces_returns_all(test_db):
    from agents.location_db import get_provinces
    provinces = get_provinces()
    assert len(provinces) == 2
    names = [p["name"] for p in provinces]
    assert "Laguna" in names
    assert "Cavite" in names


def test_get_provinces_sorted_by_name(test_db):
    from agents.location_db import get_provinces
    provinces = get_provinces()
    names = [p["name"] for p in provinces]
    assert names == sorted(names)


def test_get_provinces_have_id_and_name_keys(test_db):
    from agents.location_db import get_provinces
    provinces = get_provinces()
    assert "id" in provinces[0]
    assert "name" in provinces[0]


def test_get_municipalities_filters_by_province(test_db):
    from agents.location_db import get_municipalities
    munis = get_municipalities(1)
    assert len(munis) == 2
    names = [m["name"] for m in munis]
    assert "Biñan" in names
    assert "Santa Rosa" in names


def test_get_municipalities_empty_for_unknown_province(test_db):
    from agents.location_db import get_municipalities
    assert get_municipalities(999) == []


def test_get_municipalities_have_id_and_name_keys(test_db):
    from agents.location_db import get_municipalities
    munis = get_municipalities(1)
    assert "id" in munis[0]
    assert "name" in munis[0]


def test_get_barangays_filters_by_municipality(test_db):
    from agents.location_db import get_barangays
    brgys = get_barangays(1)
    assert len(brgys) == 2
    names = [b["name"] for b in brgys]
    assert "Poblacion" in names


def test_get_barangays_empty_for_other_municipality(test_db):
    from agents.location_db import get_barangays
    assert get_barangays(2) == []


def test_get_province_name(test_db):
    from agents.location_db import get_province_name
    assert get_province_name(1) == "Laguna"
    assert get_province_name(2) == "Cavite"


def test_get_province_name_missing_returns_empty(test_db):
    from agents.location_db import get_province_name
    assert get_province_name(999) == ""


def test_get_municipality_name(test_db):
    from agents.location_db import get_municipality_name
    assert get_municipality_name(1) == "Biñan"


def test_get_municipality_name_missing_returns_empty(test_db):
    from agents.location_db import get_municipality_name
    assert get_municipality_name(999) == ""


def test_get_provinces_empty_when_db_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "LOCATION_DB", tmp_path / "nonexistent.db")
    from agents.location_db import get_provinces
    assert get_provinces() == []
```

- [ ] **Step 2: Run tests — verify they all fail**

```bash
source .venv_helios/bin/activate && python -m pytest tests/test_location_db.py -v 2>&1 | head -20
```

Expected: `ModuleNotFoundError: No module named 'agents.location_db'`

- [ ] **Step 3: Create agents/location_db.py**

```python
import sqlite3
import config


def _get_conn() -> sqlite3.Connection:
    if not config.LOCATION_DB.exists():
        return None
    conn = sqlite3.connect(str(config.LOCATION_DB), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def get_provinces() -> list[dict]:
    conn = _get_conn()
    if conn is None:
        return []
    try:
        rows = conn.execute(
            "SELECT id, name FROM provinces ORDER BY name"
        ).fetchall()
        return [{"id": r["id"], "name": r["name"]} for r in rows]
    except Exception:
        return []
    finally:
        conn.close()


def get_municipalities(province_id: int) -> list[dict]:
    conn = _get_conn()
    if conn is None:
        return []
    try:
        rows = conn.execute(
            "SELECT id, name FROM municipalities WHERE province_id = ? ORDER BY name",
            (province_id,),
        ).fetchall()
        return [{"id": r["id"], "name": r["name"]} for r in rows]
    except Exception:
        return []
    finally:
        conn.close()


def get_barangays(municipality_id: int) -> list[dict]:
    conn = _get_conn()
    if conn is None:
        return []
    try:
        rows = conn.execute(
            "SELECT id, name FROM barangays WHERE municipality_id = ? ORDER BY name",
            (municipality_id,),
        ).fetchall()
        return [{"id": r["id"], "name": r["name"]} for r in rows]
    except Exception:
        return []
    finally:
        conn.close()


def get_province_name(province_id: int) -> str:
    conn = _get_conn()
    if conn is None:
        return ""
    try:
        row = conn.execute(
            "SELECT name FROM provinces WHERE id = ?", (province_id,)
        ).fetchone()
        return row["name"] if row else ""
    except Exception:
        return ""
    finally:
        conn.close()


def get_municipality_name(municipality_id: int) -> str:
    conn = _get_conn()
    if conn is None:
        return ""
    try:
        row = conn.execute(
            "SELECT name FROM municipalities WHERE id = ?", (municipality_id,)
        ).fetchone()
        return row["name"] if row else ""
    except Exception:
        return ""
    finally:
        conn.close()
```

- [ ] **Step 4: Run tests — verify all pass**

```bash
python -m pytest tests/test_location_db.py -v
```

Expected: all 13 tests PASS

- [ ] **Step 5: Commit**

```bash
git add agents/location_db.py tests/test_location_db.py
git commit -m "feat: add location_db query helpers with tests"
```

---

## Task 4: Update agents/geo_scoring.py for single-municipality mode (TDD)

**Files:**
- Modify: `agents/geo_scoring.py`
- Create: `tests/test_geo_scoring_single.py`

- [ ] **Step 1: Create tests/test_geo_scoring_single.py**

```python
"""
Tests for single-municipality mode in geo_scoring.py.
Uses real barangay package data — no mocks.
"""
import pytest


def test_load_single_municipality_finds_known_town():
    from agents.geo_scoring import load_single_municipality
    units = load_single_municipality("Santa Rosa", "Laguna")
    assert len(units) == 1
    assert "Santa Rosa" in units[0]["name"]
    assert units[0]["province"] == "Laguna"
    assert units[0]["region"] == "Region IV-A (CALABARZON)"


def test_load_single_municipality_fuzzy_match():
    from agents.geo_scoring import load_single_municipality
    # Slightly misspelled municipality name — rapidfuzz should still match
    units = load_single_municipality("Alamenos", "Laguna")  # typo: Alamenos → Alaminos
    assert len(units) == 1
    assert "Alaminos" in units[0]["name"]


def test_load_single_municipality_returns_empty_for_unknown():
    from agents.geo_scoring import load_single_municipality
    units = load_single_municipality("NonexistentTownXYZ", "NonexistentProvinceXYZ")
    assert units == []


def test_load_single_municipality_unit_has_required_fields():
    from agents.geo_scoring import load_single_municipality
    units = load_single_municipality("Bay", "Laguna")
    assert len(units) == 1
    u = units[0]
    for field in ["name", "province", "region", "lat", "lon", "income_class", "income_score", "population", "is_urban"]:
        assert field in u, f"Missing field: {field}"


def test_normalize_fixed_midpoint():
    from agents.geo_scoring import _normalize_fixed
    # Midpoint of range should give 0.5
    assert _normalize_fixed(5.25, 4.5, 6.0) == pytest.approx(0.5, abs=0.01)


def test_normalize_fixed_clamps_below_zero():
    from agents.geo_scoring import _normalize_fixed
    assert _normalize_fixed(0.0, 4.5, 6.0) == 0.0


def test_normalize_fixed_clamps_above_one():
    from agents.geo_scoring import _normalize_fixed
    assert _normalize_fixed(100.0, 4.5, 6.0) == 1.0


def test_compute_geo_scores_single_row_no_all_zeros():
    """Single-row scoring must not produce all-zero normalized values."""
    import geopandas as gpd
    from shapely.geometry import Point
    from agents.geo_scoring import compute_geo_scores

    gdf = gpd.GeoDataFrame(
        [{
            "name": "TestTown",
            "province": "Laguna",
            "region": "Region IV-A (CALABARZON)",
            "is_urban": True,
            "income_class": "3rd",
            "income_score": 4,
            "population": 80000,
            "geometry": Point(121.0, 14.2),
        }],
        geometry="geometry",
        crs="EPSG:4326",
    )

    scores = compute_geo_scores(gdf, ee=None)
    assert len(scores) == 1
    muni_scores = scores["TestTown"]
    # With fixed ranges, a mid-range municipality should have non-zero scores
    assert muni_scores["geo_score"] > 0.0
    assert muni_scores["geo_score"] <= 1.0


def test_compute_geo_scores_multi_row_uses_relative_ranking():
    """Multi-row scoring: highest solar should get solar_norm=1.0."""
    import geopandas as gpd
    from shapely.geometry import Point
    from agents.geo_scoring import compute_geo_scores

    gdf = gpd.GeoDataFrame(
        [
            {
                "name": "LowTown",
                "province": "Laguna", "region": "R4A",
                "is_urban": False, "income_class": "4th", "income_score": 3,
                "population": 10000, "geometry": Point(121.0, 14.0),
            },
            {
                "name": "HighTown",
                "province": "Laguna", "region": "R4A",
                "is_urban": True, "income_class": "1st", "income_score": 6,
                "population": 120000, "geometry": Point(121.1, 14.1),
            },
        ],
        geometry="geometry",
        crs="EPSG:4326",
    )

    scores = compute_geo_scores(gdf, ee=None)
    assert scores["HighTown"]["geo_score"] > scores["LowTown"]["geo_score"]
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
source .venv_helios/bin/activate && python -m pytest tests/test_geo_scoring_single.py -v 2>&1 | head -25
```

Expected: `ImportError: cannot import name 'load_single_municipality' from 'agents.geo_scoring'` and `ImportError: cannot import name '_normalize_fixed'`

- [ ] **Step 3: Add `_normalize_fixed` and `PH_*_RANGE` constants to geo_scoring.py**

Open `agents/geo_scoring.py`. After the `INCOME_CLASSES` list (around line 95), add:

```python
# Fixed PH-wide ranges for single-municipality normalization
PH_SOLAR_RANGE  = (4.5, 6.0)      # kWh/m²/day
PH_POP_RANGE    = (5_000, 150_000)
PH_INCOME_RANGE = (1, 6)           # income_score scale


def _normalize_fixed(value: float, lo: float, hi: float) -> float:
    """Normalize value against a fixed range, clamped to [0, 1]."""
    return max(0.0, min(1.0, (value - lo) / (hi - lo)))
```

- [ ] **Step 4: Add `load_single_municipality` to geo_scoring.py**

After the `load_municipalities` function (around line 253), add:

```python
def load_single_municipality(town: str, province: str) -> list[dict]:
    """
    Find a single municipality by town + province name.
    Both names are fuzzy-matched. Returns a single-item list or [].
    """
    try:
        import barangay as br
        from rapidfuzz import process as rfprocess

        data = br.BARANGAY

        # Build province index: lowercase_name → (region_name, prov_name, prov_data)
        prov_index = {}
        for region_name, region_data in data.items():
            if not isinstance(region_data, dict):
                continue
            for prov_name, prov_data in region_data.items():
                if isinstance(prov_data, dict):
                    prov_index[prov_name.lower()] = (region_name, prov_name, prov_data)

        # Match province
        prov_key = province.lower().strip()
        if prov_key not in prov_index:
            result = rfprocess.extractOne(prov_key, list(prov_index.keys()), score_cutoff=60)
            if not result:
                logger.warning(f"load_single_municipality: province '{province}' not found")
                return []
            prov_key = result[0]

        region_name, prov_name, prov_data = prov_index[prov_key]
        muni_names = list(prov_data.keys())

        # Match municipality
        muni_match = None
        town_lower = town.lower().strip()
        for muni_name in muni_names:
            if muni_name.lower() == town_lower:
                muni_match = muni_name
                break

        if not muni_match:
            result = rfprocess.extractOne(
                town_lower,
                [m.lower() for m in muni_names],
                score_cutoff=60,
            )
            if result:
                matched_lower = result[0]
                for muni_name in muni_names:
                    if muni_name.lower() == matched_lower:
                        muni_match = muni_name
                        break

        if not muni_match:
            logger.warning(f"load_single_municipality: '{town}' not found in '{prov_name}'")
            return []

        logger.info(f"load_single_municipality: matched '{muni_match}', {prov_name}, {region_name}")
        return [_build_unit(muni_match, prov_name, region_name)]

    except Exception as e:
        logger.warning(f"load_single_municipality failed: {e}")
        return []
```

- [ ] **Step 5: Update `compute_geo_scores` for single-row case**

In `agents/geo_scoring.py`, find the MinMaxScaler block inside `compute_geo_scores` (around line 323):

```python
    scaler = MinMaxScaler()
    df[["solar_norm", "pop_norm", "income_norm"]] = scaler.fit_transform(
        df[["solar_raw", "population_raw", "income_raw"]]
    )
```

Replace with:

```python
    if len(df) == 1:
        df["solar_norm"]  = df["solar_raw"].apply(lambda v: _normalize_fixed(v, *PH_SOLAR_RANGE))
        df["pop_norm"]    = df["population_raw"].apply(lambda v: _normalize_fixed(v, *PH_POP_RANGE))
        df["income_norm"] = df["income_raw"].apply(lambda v: _normalize_fixed(v, *PH_INCOME_RANGE))
    else:
        scaler = MinMaxScaler()
        df[["solar_norm", "pop_norm", "income_norm"]] = scaler.fit_transform(
            df[["solar_raw", "population_raw", "income_raw"]]
        )
```

- [ ] **Step 6: Update `geo_scoring_agent` to route on comma**

In `agents/geo_scoring.py`, find the `geo_scoring_agent` function. Replace:

```python
        units = load_municipalities(state["location"])
        if not units:
            logger.warning("[Agent 1] No municipalities found. Using synthetic fallback.")
            units = _synthetic_fallback(state["location"])
```

With:

```python
        location = state["location"]
        if "," in location:
            parts = location.rsplit(",", 1)
            town, province = parts[0].strip(), parts[1].strip()
            logger.info(f"[Agent 1] Single-municipality mode: {town}, {province}")
            units = load_single_municipality(town, province)
        else:
            units = load_municipalities(location)

        if not units:
            logger.warning("[Agent 1] No municipalities found. Using synthetic fallback.")
            units = _synthetic_fallback(state["location"])
```

- [ ] **Step 7: Run all geo_scoring tests**

```bash
python -m pytest tests/test_geo_scoring_single.py -v
```

Expected: all 9 tests PASS

- [ ] **Step 8: Confirm existing tests still pass**

```bash
python -m pytest tests/ -v
```

Expected: all tests PASS (no regressions)

- [ ] **Step 9: Commit**

```bash
git add agents/geo_scoring.py tests/test_geo_scoring_single.py
git commit -m "feat: add single-municipality scoring with fixed-range normalizer"
```

---

## Task 5: Update app.py with cascading dropdowns

**Files:**
- Modify: `app.py`

- [ ] **Step 1: Add location_db import at top of app.py**

After the existing imports (around line 16), add:

```python
from agents.location_db import get_provinces, get_municipalities
```

- [ ] **Step 2: Replace text input block with cascading dropdowns**

Find and replace the entire "Run Pipeline" block in the `with st.sidebar:` section. The current block (lines 37–52) is:

```python
    st.markdown("---")
    st.subheader("Run Pipeline")
    location_input = st.text_input("Province / Region", placeholder="e.g. Laguna")

    if st.button("▶ Analyze", type="primary", use_container_width=True):
        if not location_input.strip():
            st.error("Enter a location first.")
        else:
            with st.spinner(f"Analyzing {location_input}... (this takes ~1-2 mins)"):
                result = run_pipeline(location_input.strip())
                st.session_state.pipeline_result = result
                st.session_state.chat_history = []
                save_session(result, [])
            if result.get("errors"):
                st.warning(f"Completed with {len(result['errors'])} warning(s).")
            else:
                st.success("Done!")
```

Replace with:

```python
    st.markdown("---")
    st.subheader("Run Pipeline")

    provinces = get_provinces()
    if not provinces:
        st.warning("⚠️ Location DB not built. Run: `python scripts/build_location_db.py`")
        location_str = None
    else:
        prov_options = {p["name"]: p["id"] for p in provinces}
        selected_prov_name = st.selectbox(
            "Province",
            options=["— Select province —"] + list(prov_options.keys()),
            label_visibility="visible",
        )

        selected_muni_name = None
        if selected_prov_name != "— Select province —":
            prov_id = prov_options[selected_prov_name]
            munis = get_municipalities(prov_id)
            muni_options = {m["name"]: m["id"] for m in munis}
            raw_muni = st.selectbox(
                "Municipality",
                options=["— All municipalities —"] + list(muni_options.keys()),
                label_visibility="visible",
            )
            if raw_muni != "— All municipalities —":
                selected_muni_name = raw_muni

        if selected_prov_name == "— Select province —":
            location_str = None
        elif selected_muni_name:
            location_str = f"{selected_muni_name}, {selected_prov_name}"
        else:
            location_str = selected_prov_name

    if st.button("▶ Analyze", type="primary", use_container_width=True):
        if not location_str:
            st.error("Select a province first.")
        else:
            with st.spinner(f"Analyzing {location_str}... (this takes ~1-2 mins)"):
                result = run_pipeline(location_str)
                st.session_state.pipeline_result = result
                st.session_state.chat_history = []
                save_session(result, [])
            if result.get("errors"):
                st.warning(f"Completed with {len(result['errors'])} warning(s).")
            else:
                st.success("Done!")
```

- [ ] **Step 3: Verify app imports cleanly**

```bash
source .venv_helios/bin/activate && python -c "import app" 2>&1 | grep -i error
```

Expected: no errors (only the usual Streamlit bare-mode warnings)

- [ ] **Step 4: Manual smoke test**

```bash
streamlit run app.py
```

Check:
1. Province dropdown populates with 85 alphabetically sorted provinces
2. Selecting "Laguna" populates Municipality dropdown with its municipalities
3. Selecting "— All municipalities —" → Analyze passes `"Laguna"` to pipeline
4. Selecting "City of Biñan" → Analyze passes `"City of Biñan, Laguna"` to pipeline
5. "⚠️ Location DB not built" warning does NOT appear (since DB was built in Task 2)

- [ ] **Step 5: Commit**

```bash
git add app.py
git commit -m "feat: replace text input with cascading province/municipality dropdowns"
```
