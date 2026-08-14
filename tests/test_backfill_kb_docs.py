def test_slug_matches_lowercases_and_strips_punctuation():
    from scripts.backfill_kb_docs import _slug
    assert _slug("City of Isabela, Rizal") == "city_of_isabela_rizal"


def test_match_municipality_by_province_slug():
    from scripts.backfill_kb_docs import match_municipality
    munis = [{"municipality_id": 1, "name": "Daraga", "province": "Albay"}]
    assert match_municipality("albay__daraga__abc123", munis) == 1


def test_match_municipality_no_match_returns_none():
    from scripts.backfill_kb_docs import match_municipality
    munis = [{"municipality_id": 1, "name": "Daraga", "province": "Albay"}]
    assert match_municipality("sulu__jolo__def456", munis) is None


def test_match_municipality_matches_city_of_prefix_alias():
    """A doc filed under the bare name ('biñan') must still match a
    municipality whose DB canonical name carries a 'City of' prefix
    ('City of Biñan'), and vice versa — some kb/intel docs predate a
    municipality being reclassified as a city in the DB."""
    from scripts.backfill_kb_docs import match_municipality
    munis = [{"municipality_id": 1, "name": "City of Biñan", "province": "Laguna"}]
    assert match_municipality("laguna__biñan__abc123", munis) == 1


def test_match_municipality_avoids_cross_province_collision():
    from scripts.backfill_kb_docs import match_municipality
    munis = [
        {"municipality_id": 1, "name": "San Isidro", "province": "Nueva Ecija"},
        {"municipality_id": 2, "name": "San Isidro", "province": "Davao del Sur"},
    ]
    assert match_municipality("davao_del_sur__san_isidro__xyz", munis) == 2


def test_pick_current_returns_newest_mtime(tmp_path):
    from scripts.backfill_kb_docs import pick_current
    old = tmp_path / "old.md"
    old.write_text("old")
    new = tmp_path / "new.md"
    new.write_text("new")
    import os, time
    now = time.time()
    os.utime(old, (now - 100, now - 100))
    os.utime(new, (now, now))
    assert pick_current([old, new]) == new


def test_main_registers_current_and_deletes_duplicates(tmp_path, monkeypatch):
    import sqlite3
    import config
    from scripts.backfill_kb_docs import main
    from agents import db_store

    db_path = tmp_path / "t.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "CREATE TABLE municipalities (id INTEGER PRIMARY KEY, name TEXT, province TEXT, region TEXT)"
    )
    conn.execute("INSERT INTO municipalities (id, name, province, region) VALUES (1, 'Daraga', 'Albay', 'Region V')")
    conn.commit()
    conn.close()
    monkeypatch.setattr(config, "HELIO_DB", db_path)
    import importlib
    importlib.reload(db_store)

    kb_intel_dir = tmp_path / "kb_intel"
    kb_intel_dir.mkdir()
    old_file = kb_intel_dir / "albay__daraga__old.md"
    old_file.write_text("old")
    new_file = kb_intel_dir / "albay__daraga__new.md"
    new_file.write_text("new")
    import os, time
    now = time.time()
    os.utime(old_file, (now - 100, now - 100))
    os.utime(new_file, (now, now))
    monkeypatch.setattr(config, "KB_INTEL", kb_intel_dir)

    main(dry_run=False)

    assert not old_file.exists()
    assert new_file.exists()
    docs = db_store.get_current_kb_docs(municipality_id=1)
    assert len(docs) == 1
    assert docs[0]["file_path"] == str(new_file)
