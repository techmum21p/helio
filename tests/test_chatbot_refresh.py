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
