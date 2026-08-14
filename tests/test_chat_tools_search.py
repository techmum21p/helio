def test_search_kb_requires_resolvable_province(monkeypatch):
    import agents.chat_tools as ct
    monkeypatch.setattr(ct, "get_latest_scored_municipalities",
                        lambda: [{"municipality_id": 1, "name": "Jolo", "province": "Sulu"}])
    out = ct.search_kb(province="nowhere")
    assert "error" in out


def test_search_kb_ambiguous_province(monkeypatch):
    import agents.chat_tools as ct
    monkeypatch.setattr(ct, "get_latest_scored_municipalities",
                        lambda: [{"municipality_id": 1, "name": "A", "province": "Davao del Sur"},
                                 {"municipality_id": 2, "name": "B", "province": "Davao Oriental"}])
    out = ct.search_kb(province="davao")
    assert "error" in out and len(out["candidates"]) == 2


def test_search_kb_loads_province_report_and_all_current_intel_docs(monkeypatch, tmp_path):
    import agents.chat_tools as ct
    monkeypatch.setattr(ct, "get_latest_scored_municipalities",
                        lambda: [{"municipality_id": 1, "name": "Jolo", "province": "Sulu"},
                                 {"municipality_id": 2, "name": "Patikul", "province": "Sulu"}])
    monkeypatch.setattr(ct, "get_latest_report_for_province",
                        lambda province: {"markdown": "# Sulu report"} if province == "Sulu" else None)

    jolo_doc = tmp_path / "jolo.md"
    jolo_doc.write_text("Jolo intel body")
    patikul_doc = tmp_path / "patikul.md"
    patikul_doc.write_text("Patikul intel body")
    monkeypatch.setattr(ct, "get_current_kb_docs", lambda province=None, municipality_id=None: [
        {"file_path": str(jolo_doc), "municipality_id": 1},
        {"file_path": str(patikul_doc), "municipality_id": 2},
    ])

    out = ct.search_kb(province="sulu")
    assert "# Sulu report" in out["results"]
    assert "Jolo intel body" in out["results"]
    assert "Patikul intel body" in out["results"]


def test_search_kb_narrows_to_one_municipality(monkeypatch, tmp_path):
    import agents.chat_tools as ct
    monkeypatch.setattr(ct, "get_latest_scored_municipalities",
                        lambda: [{"municipality_id": 1, "name": "Jolo", "province": "Sulu"},
                                 {"municipality_id": 2, "name": "Patikul", "province": "Sulu"}])
    monkeypatch.setattr(ct, "get_latest_report_for_province", lambda province: None)

    jolo_doc = tmp_path / "jolo.md"
    jolo_doc.write_text("Jolo intel body")
    captured = {}

    def fake_get_current_kb_docs(province=None, municipality_id=None):
        captured["municipality_id"] = municipality_id
        return [{"file_path": str(jolo_doc), "municipality_id": 1}] if municipality_id == 1 else []

    monkeypatch.setattr(ct, "get_current_kb_docs", fake_get_current_kb_docs)

    out = ct.search_kb(province="sulu", municipality="Jolo")
    assert captured["municipality_id"] == 1
    assert "Jolo intel body" in out["results"]


def test_search_kb_unresolvable_municipality_returns_error(monkeypatch):
    import agents.chat_tools as ct
    monkeypatch.setattr(ct, "get_latest_scored_municipalities",
                        lambda: [{"municipality_id": 1, "name": "Jolo", "province": "Sulu"}])
    out = ct.search_kb(province="sulu", municipality="Nonexistent Town")
    assert "error" in out


def test_search_kb_no_docs_yet_returns_informative_message(monkeypatch):
    import agents.chat_tools as ct
    monkeypatch.setattr(ct, "get_latest_scored_municipalities",
                        lambda: [{"municipality_id": 1, "name": "Jolo", "province": "Sulu"}])
    monkeypatch.setattr(ct, "get_latest_report_for_province", lambda province: None)
    monkeypatch.setattr(ct, "get_current_kb_docs", lambda province=None, municipality_id=None: [])

    out = ct.search_kb(province="sulu")
    assert "results" in out
    assert "no" in out["results"].lower() or "not" in out["results"].lower()
