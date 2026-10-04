from app.agent import create_marvel_agent
from app.config import Settings


def test_groq_provider_uses_openai_compatible_endpoint(monkeypatch):
    from app import agent

    captured = {}

    class FakeChatOpenAI:
        def __init__(self, **options):
            captured.update(options)

    monkeypatch.setattr(agent, "ChatOpenAI", FakeChatOpenAI)
    monkeypatch.setattr(agent, "create_agent", lambda **options: options)

    settings = Settings(ai_provider="groq", ai_model="model-id", ai_api_key="test-key")
    result = create_marvel_agent(settings, comic_vine=object(), spoiler_level="NONE")

    assert captured["base_url"] == "https://api.groq.com/openai/v1"
    assert captured["model"] == "model-id"
    assert isinstance(result["model"], FakeChatOpenAI)


def test_groq_provider_keeps_custom_base_url(monkeypatch):
    from app import agent

    captured = {}

    class FakeChatOpenAI:
        def __init__(self, **options):
            captured.update(options)

    monkeypatch.setattr(agent, "ChatOpenAI", FakeChatOpenAI)
    monkeypatch.setattr(agent, "create_agent", lambda **options: options)

    settings = Settings(
        ai_provider="groq", ai_model="model-id", ai_api_key="test-key",
        ai_base_url="https://gateway.example/v1",
    )
    create_marvel_agent(settings, comic_vine=object(), spoiler_level="NONE")

    assert captured["base_url"] == "https://gateway.example/v1"
