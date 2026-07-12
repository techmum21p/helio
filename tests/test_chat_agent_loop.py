import json


class _Block:
    def __init__(self, type, **kw):
        self.type = type
        for k, v in kw.items():
            setattr(self, k, v)


class _Resp:
    def __init__(self, blocks):
        self.content = blocks


class _FakeMessages:
    """Feed a queue of responses; records every create() kwargs."""
    def __init__(self, queue):
        self.queue = list(queue)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if isinstance(self.queue[0], Exception):
            raise self.queue.pop(0)
        return self.queue.pop(0)


def _wire(monkeypatch, queue):
    import agents.chatbot as chatbot_mod
    fake = _FakeMessages(queue)
    monkeypatch.setattr(chatbot_mod.client, "messages", fake)
    monkeypatch.setattr(chatbot_mod, "execute_tool",
                        lambda name, tool_input: json.dumps({"echo": name, "input": tool_input}))
    monkeypatch.setattr(chatbot_mod, "retrieve_context",
                        lambda query, n_results=10, province=None: "fallback-context")
    return fake, chatbot_mod


def test_loop_executes_tool_then_returns_text(monkeypatch):
    fake, chatbot_mod = _wire(monkeypatch, [
        _Resp([_Block("tool_use", id="t1", name="get_top_municipalities",
                      input={"metric": "final_score", "province": "Sulu"})]),
        _Resp([_Block("text", text="Jolo leads with 0.84.")]),
    ])
    reply, history = chatbot_mod.chat("top 5 in sulu", [], run_id="")
    assert reply == "Jolo leads with 0.84."
    # second call carried the tool_result back
    second = fake.calls[1]["messages"]
    assert second[-1]["role"] == "user"
    assert second[-1]["content"][0]["type"] == "tool_result"
    assert second[-1]["content"][0]["tool_use_id"] == "t1"
    # tools offered on every round
    assert fake.calls[0]["tools"] and fake.calls[1]["tools"]


def test_history_gets_only_text_turns(monkeypatch):
    _, chatbot_mod = _wire(monkeypatch, [
        _Resp([_Block("tool_use", id="t1", name="search_kb", input={"query": "x"})]),
        _Resp([_Block("text", text="answer")]),
    ])
    reply, history = chatbot_mod.chat("question", [{"role": "user", "content": "old"},
                                                   {"role": "assistant", "content": "old reply"}], run_id="")
    assert history == [
        {"role": "user", "content": "old"},
        {"role": "assistant", "content": "old reply"},
        {"role": "user", "content": "question"},
        {"role": "assistant", "content": "answer"},
    ]


def test_prior_history_sent_to_model(monkeypatch):
    fake, chatbot_mod = _wire(monkeypatch, [_Resp([_Block("text", text="hi")])])
    chatbot_mod.chat("follow-up", [{"role": "user", "content": "earlier q"},
                                   {"role": "assistant", "content": "earlier a"}], run_id="")
    sent = fake.calls[0]["messages"]
    assert sent[0]["content"] == "earlier q" and sent[1]["content"] == "earlier a"


def test_round_cap_forces_final_answer(monkeypatch):
    tool_resp = lambda: _Resp([_Block("tool_use", id="t", name="search_kb", input={"query": "x"})])
    fake, chatbot_mod = _wire(monkeypatch, [
        tool_resp(), tool_resp(), tool_resp(), tool_resp(), tool_resp(),   # 5 rounds of tool_use
        _Resp([_Block("text", text="best effort answer")]),                # forced final
    ])
    reply, _ = chatbot_mod.chat("q", [], run_id="")
    assert reply == "best effort answer"
    assert len(fake.calls) == 6
    # forced final-answer call must not offer tools, so the model can't dodge with another tool_use
    assert "tools" not in fake.calls[5]
    # Regression: the round-cap path must not produce two consecutive
    # same-role messages. Most Anthropic-compatible gateways (including the
    # MiMo gateway this project targets) require strict user/assistant
    # alternation and will reject a request otherwise. A mock like this one
    # accepts anything, so this assertion must check roles explicitly rather
    # than relying on the fake gateway to reject a malformed sequence.
    final_messages = fake.calls[5]["messages"]
    for i in range(len(final_messages) - 1):
        assert final_messages[i]["role"] != final_messages[i + 1]["role"], (
            f"consecutive same-role messages at index {i}: "
            f"{final_messages[i]['role']!r} followed by {final_messages[i + 1]['role']!r}"
        )
    # The round-cap instruction must be folded into the existing trailing
    # user message (as an extra content block), not appended as a new one.
    assert final_messages[-1]["role"] == "user"
    assert any(
        block.get("type") == "text" and "Answer now" in block.get("text", "")
        for block in final_messages[-1]["content"]
    )
    assert any(
        block.get("type") == "tool_result" for block in final_messages[-1]["content"]
    )


def test_gateway_failure_falls_back_to_rag(monkeypatch):
    fake, chatbot_mod = _wire(monkeypatch, [
        RuntimeError("gateway down"),
        _Resp([_Block("text", text="rag answer")]),
    ])
    reply, history = chatbot_mod.chat("q", [], run_id="")
    assert reply == "rag answer"
    # fallback call is toolless and context-stuffed
    assert "tools" not in fake.calls[1]
    assert "fallback-context" in fake.calls[1]["messages"][-1]["content"]


def test_total_failure_returns_apology_not_exception(monkeypatch):
    _, chatbot_mod = _wire(monkeypatch, [RuntimeError("down"), RuntimeError("still down")])
    reply, history = chatbot_mod.chat("q", [], run_id="")
    assert "couldn't generate a response" in reply
    assert history == []
