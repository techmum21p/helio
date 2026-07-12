def test_detect_municipality_id_matches_exact_name():
    from agents.chatbot import detect_municipality_id
    munis = [
        {"municipality_id": 1, "name": "Biñan"},
        {"municipality_id": 2, "name": "Manila"},
    ]
    assert detect_municipality_id("Tell me about Biñan's solar potential", munis) == 1


def test_detect_municipality_id_prefers_longest_match():
    from agents.chatbot import detect_municipality_id
    munis = [
        {"municipality_id": 1, "name": "Isabela"},
        {"municipality_id": 2, "name": "City of Isabela"},
    ]
    assert detect_municipality_id("What about City of Isabela?", munis) == 2


def test_detect_municipality_id_returns_none_when_no_match():
    from agents.chatbot import detect_municipality_id
    munis = [{"municipality_id": 1, "name": "Biñan"}]
    assert detect_municipality_id("What's the weather like today?", munis) is None


def test_chat_calls_refresh_when_municipality_named(monkeypatch):
    import agents.chatbot as chatbot_mod

    monkeypatch.setattr(
        chatbot_mod, "get_latest_scored_municipalities",
        lambda: [{"municipality_id": 1, "name": "Biñan", "province": "Laguna"}],
    )
    called = {}
    monkeypatch.setattr(
        chatbot_mod, "maybe_refresh_assessment",
        lambda mid: called.setdefault("municipality_id", mid),
    )
    monkeypatch.setattr(chatbot_mod, "retrieve_context", lambda query, n_results=10: "context")

    class _FakeResponse:
        content = [type("Block", (), {"text": "reply"})()]

    monkeypatch.setattr(chatbot_mod.client.messages, "create", lambda **kwargs: _FakeResponse())

    chatbot_mod.chat("Tell me about Biñan", [], run_id="")
    assert called["municipality_id"] == 1
