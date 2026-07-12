def test_search_kb_passes_province_filter(monkeypatch):
    import agents.chat_tools as ct
    import agents.chatbot as chatbot_mod
    monkeypatch.setattr(ct, "get_latest_scored_municipalities",
                        lambda: [{"municipality_id": 1, "name": "Jolo", "province": "Sulu"}])
    seen = {}

    def fake_retrieve(query, n_results=10, province=None):
        seen.update(query=query, province=province)
        return "chunks"

    monkeypatch.setattr(chatbot_mod, "retrieve_context", fake_retrieve)
    out = ct.search_kb("poverty conditions", province="sulu")
    assert out == {"results": "chunks"}
    assert seen["province"] == "Sulu"          # canonicalized, not raw fragment


def test_search_kb_without_province(monkeypatch):
    import agents.chat_tools as ct
    import agents.chatbot as chatbot_mod
    monkeypatch.setattr(chatbot_mod, "retrieve_context",
                        lambda query, n_results=10, province=None: f"p={province}")
    assert ct.search_kb("solar trends") == {"results": "p=None"}


def test_search_kb_ambiguous_province(monkeypatch):
    import agents.chat_tools as ct
    monkeypatch.setattr(ct, "get_latest_scored_municipalities",
                        lambda: [{"municipality_id": 1, "name": "A", "province": "Davao del Sur"},
                                 {"municipality_id": 2, "name": "B", "province": "Davao Oriental"}])
    out = ct.search_kb("anything", province="davao")
    assert "error" in out and len(out["candidates"]) == 2


def test_retrieve_context_builds_where_clause(monkeypatch):
    import agents.chatbot as chatbot_mod
    captured = {}

    class FakeCollection:
        def query(self, **kwargs):
            captured.update(kwargs)
            return {"documents": [["doc1"]], "metadatas": [[{"source": "kb/intel/x.md"}]]}

    monkeypatch.setattr(chatbot_mod, "_get_collection", lambda: FakeCollection())
    chatbot_mod.retrieve_context("q", province="Sulu")
    assert captured["where"] == {"province": "Sulu"}


def test_retrieve_context_no_filter_omits_where(monkeypatch):
    import agents.chatbot as chatbot_mod
    calls = []

    class FakeCollection:
        def query(self, **kwargs):
            calls.append(kwargs)
            return {"documents": [["doc1"]], "metadatas": [[{"source": "kb/intel/x.md"}]]}

    monkeypatch.setattr(chatbot_mod, "_get_collection", lambda: FakeCollection())
    chatbot_mod.retrieve_context("q")
    assert "where" not in calls[0]
