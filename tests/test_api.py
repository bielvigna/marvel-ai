from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app


def test_health_reports_configuration_without_revealing_secrets(monkeypatch):
    monkeypatch.setenv("COMIC_VINE_API_KEY", "")
    monkeypatch.setenv("AI_API_KEY", "")
    monkeypatch.setenv("AI_MODEL", "")
    get_settings.cache_clear()
    try:
        response = TestClient(app).get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok", "comic_vine_configured": False, "ai_configured": False}
        assert "api_key" not in response.text.lower()
    finally:
        get_settings.cache_clear()


def test_character_endpoint_returns_clear_setup_error_without_key(monkeypatch):
    monkeypatch.setenv("COMIC_VINE_API_KEY", "")
    get_settings.cache_clear()
    try:
        response = TestClient(app).get("/api/characters")
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "comic_vine_not_configured"
    finally:
        get_settings.cache_clear()


def test_chat_language_contract_and_response_shape(monkeypatch):
    from app import main

    class FakeClient:
        def close(self):
            pass

    class FakeAgent:
        async def ainvoke(self, payload):
            return {"messages": [SimpleNamespace(content="**Olá**", type="ai")]}

    languages = []
    monkeypatch.setattr(main, "comic_vine_client", FakeClient)
    monkeypatch.setattr(main, "create_marvel_agent", lambda settings, client, level, language: (
        languages.append(language) or FakeAgent()
    ))

    client = TestClient(app)
    default_response = client.post("/api/chat", json={"message": "Oi"})
    english_response = client.post("/api/chat", json={"message": "Hi", "language": "en"})
    invalid_response = client.post("/api/chat", json={"message": "Salut", "language": "fr"})

    assert default_response.status_code == 200
    assert default_response.json() == {"answer": "**Olá**", "sources": []}
    assert english_response.status_code == 200
    assert english_response.json() == {"answer": "**Olá**", "sources": []}
    assert set(default_response.json()) == {"answer", "sources"}
    assert invalid_response.status_code == 422
    assert languages == ["pt-BR", "en"]


def test_chat_logs_provider_failure_without_logging_user_message(monkeypatch):
    from app import main

    class FakeClient:
        def close(self):
            pass

    class FakeAgent:
        async def ainvoke(self, payload):
            raise RuntimeError("provider rejected model request")

    logs = []
    monkeypatch.setattr(main, "comic_vine_client", FakeClient)
    monkeypatch.setattr(main, "create_marvel_agent", lambda *args: FakeAgent())
    monkeypatch.setattr(main.logger, "warning", lambda *args: logs.append(args))

    prompt = "PRIVATE_PROMPT_MUST_NOT_BE_LOGGED"
    response = TestClient(app).post("/api/chat", json={"message": prompt})

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "ai_request_failed"
    assert len(logs) == 1
    assert "RuntimeError" in str(logs[0])
    assert prompt not in str(logs[0])


def test_chat_restores_and_saves_recent_history_for_the_same_conversation(monkeypatch):
    from app import main

    class FakeClient:
        def close(self):
            pass

    class FakeMemory:
        def __init__(self):
            self.messages = {}

        async def load(self, conversation_id):
            return list(self.messages.get(conversation_id, []))

        async def save(self, conversation_id, messages):
            self.messages[conversation_id] = list(messages)

    class FakeAgent:
        def __init__(self, captured, answer):
            self.captured = captured
            self.answer = answer

        async def ainvoke(self, payload):
            self.captured.append(payload["messages"])
            return {"messages": [SimpleNamespace(content=self.answer, type="ai")]}

    memory = FakeMemory()
    captured = []
    answers = iter(["resposta 1", "resposta 2"])
    monkeypatch.setattr(main, "comic_vine_client", FakeClient)
    monkeypatch.setattr(main, "create_marvel_agent", lambda *args: FakeAgent(captured, next(answers)))

    with TestClient(app) as client:
        app.state.chat_memory = memory
        first = client.post("/api/chat", json={
            "message": "Quem é o Homem-Aranha?",
            "conversation_id": "7c9e6679-7425-40de-944b-e07fc1f90ae7",
        })
        second = client.post("/api/chat", json={
            "message": "E qual é o nome dele?",
            "conversation_id": "7c9e6679-7425-40de-944b-e07fc1f90ae7",
        })

    assert first.status_code == 200
    assert second.status_code == 200
    assert captured[1] == [
        {"role": "user", "content": "Quem é o Homem-Aranha?"},
        {"role": "assistant", "content": "resposta 1"},
        {"role": "user", "content": "E qual é o nome dele?"},
    ]
    assert memory.messages["7c9e6679-7425-40de-944b-e07fc1f90ae7"][-1] == {
        "role": "assistant", "content": "resposta 2"
    }
