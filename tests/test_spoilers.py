from app.agent import SPOILER_POLICY, normalize_spoiler_level


def test_spoiler_level_normalization_defaults_to_none():
    assert normalize_spoiler_level("high") == "HIGH"
    assert normalize_spoiler_level("unknown") == "NONE"


def test_spoiler_levels_have_distinct_policies():
    assert "Do not reveal" in SPOILER_POLICY["NONE"]
    assert "preserve the main twists" in SPOILER_POLICY["MEDIUM"]
    assert "Answer fully" in SPOILER_POLICY["HIGH"]


def test_chat_request_bounds_history_and_content():
    from pydantic import ValidationError
    from app.schemas import ChatRequest

    assert ChatRequest(message="hello", spoiler_level="LOW").spoiler_level == "LOW"
    try:
        ChatRequest(message="x", history=[{"role": "user", "content": "x"}] * 21)
    except ValidationError:
        return
    raise AssertionError("history longer than 20 messages should be rejected")


def test_chat_request_defaults_language_to_brazilian_portuguese():
    from app.schemas import ChatRequest

    assert ChatRequest(message="hello").language == "pt-BR"


def test_chat_request_accepts_english():
    from app.schemas import ChatRequest

    assert ChatRequest(message="hello", language="en").language == "en"


def test_chat_request_rejects_unsupported_language():
    from pydantic import ValidationError
    from app.schemas import ChatRequest

    try:
        ChatRequest(message="hello", language="fr")
    except ValidationError:
        return
    raise AssertionError("unsupported chat language should be rejected")


def test_chat_request_accepts_a_uuid_conversation_id():
    from app.schemas import ChatRequest

    request = ChatRequest(message="oi", conversation_id="7c9e6679-7425-40de-944b-e07fc1f90ae7")
    assert str(request.conversation_id) == "7c9e6679-7425-40de-944b-e07fc1f90ae7"


def test_chat_request_rejects_an_invalid_conversation_id():
    from pydantic import ValidationError
    from app.schemas import ChatRequest

    try:
        ChatRequest(message="oi", conversation_id="conversation-1")
    except ValidationError as error:
        assert "conversation_id" in str(error)
        return
    raise AssertionError("invalid conversation IDs must be rejected")


def test_settings_loads_mongodb_uri_from_environment(monkeypatch):
    from app.config import Settings

    settings = Settings(_env_file=None, mongodb_uri="mongodb://example.test/chat")
    assert settings.mongodb_uri == "mongodb://example.test/chat"


def test_agent_prompt_sets_language_without_weakening_research_or_spoiler_rules(monkeypatch):
    import app.agent as agent_module
    from app.config import Settings

    captured = {}
    monkeypatch.setattr(agent_module, "ChatOpenAI", lambda **kwargs: object())
    monkeypatch.setattr(agent_module, "build_tools", lambda client: [])

    def capture_agent(**kwargs):
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(agent_module, "create_agent", capture_agent)
    agent_module.create_marvel_agent(Settings(ai_api_key="key", ai_model="model"), object(), "NONE", "en")

    prompt = captured["system_prompt"]
    assert "English" in prompt
    assert "Preserve Marvel character names and source URLs" in prompt
    assert "Use Comic Vine tools before stating verifiable facts" in prompt
    assert agent_module.SPOILER_POLICY["NONE"] in prompt
