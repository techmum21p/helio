import pytest


@pytest.fixture
def scores_and_intel():
    final_scores = {
        "Jolo": {
            "province": "Sulu", "region": "Region IX", "final_score": 0.8,
            "tier": "high", "geo_score": 0.7, "solar_kwh_estimate": 1500,
            "assessment": "Strong market.", "opportunity": "Growing retail.",
            "risk": "Limited grid capacity.", "population": 100000, "is_urban": True,
        }
    }
    web_intel = {"Jolo": {"business_count": 12, "avg_rating": 4.1, "total_reviews": 50,
                          "commercial_anchors": 2, "avg_price_level": 2}}
    return final_scores, web_intel


def test_save_municipality_docs_registers_kb_doc(monkeypatch, tmp_path, scores_and_intel):
    import config
    from agents import kb_builder, db_store

    monkeypatch.setattr(config, "KB_INTEL", tmp_path)
    monkeypatch.setattr(db_store, "get_municipality_id", lambda name, province: 42)
    registered = []
    monkeypatch.setattr(
        db_store, "register_kb_doc",
        lambda municipality_id, province, file_path, run_id: registered.append(
            (municipality_id, province, file_path, run_id)
        ) or [],
    )

    final_scores, web_intel = scores_and_intel
    saved = kb_builder.save_municipality_docs("Sulu", final_scores, web_intel, "run1")

    assert len(saved) == 1
    assert len(registered) == 1
    muni_id, province, file_path, run_id = registered[0]
    assert muni_id == 42
    assert province == "Sulu"
    assert file_path == str(saved[0])
    assert run_id == "run1"


def test_save_municipality_docs_deletes_superseded_file(monkeypatch, tmp_path, scores_and_intel):
    import config
    from agents import kb_builder, db_store

    monkeypatch.setattr(config, "KB_INTEL", tmp_path)
    monkeypatch.setattr(db_store, "get_municipality_id", lambda name, province: 42)

    old_file = tmp_path / "old_doc.md"
    old_file.write_text("stale")
    monkeypatch.setattr(db_store, "register_kb_doc", lambda *a, **k: [str(old_file)])

    final_scores, web_intel = scores_and_intel
    kb_builder.save_municipality_docs("Sulu", final_scores, web_intel, "run1")

    assert not old_file.exists()


def test_save_municipality_docs_skips_registration_when_municipality_unknown(monkeypatch, tmp_path, scores_and_intel):
    import config
    from agents import kb_builder, db_store

    monkeypatch.setattr(config, "KB_INTEL", tmp_path)
    monkeypatch.setattr(db_store, "get_municipality_id", lambda name, province: None)
    called = []
    monkeypatch.setattr(db_store, "register_kb_doc", lambda *a, **k: called.append(1) or [])

    final_scores, web_intel = scores_and_intel
    saved = kb_builder.save_municipality_docs("Sulu", final_scores, web_intel, "run1")

    assert len(saved) == 1  # file still written
    assert called == []     # but no kb_doc registered
