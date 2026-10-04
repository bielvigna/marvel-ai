import json

import httpx

from app.ai_tools import build_tools
from app.comic_vine import ComicVineClient


def test_team_search_tool_queries_comic_vine_and_returns_a_source():
    def handler(request):
        assert request.url.path.endswith("/teams/")
        assert request.url.params["filter"] == "name:Avengers"
        return httpx.Response(200, json={"status_code": 1, "results": [{"id": 1, "name": "Avengers"}]})

    client = ComicVineClient("private", httpx.Client(transport=httpx.MockTransport(handler)))
    tools = {item.name: item for item in build_tools(client)}
    result = json.loads(tools["search_team"].invoke({"name": "Avengers"}))
    assert result["results"][0]["name"] == "Avengers"
    assert result["source"] == "Comic Vine"
    assert "private" not in json.dumps(result)


def test_character_power_tool_returns_only_listed_powers():
    def handler(request):
        return httpx.Response(200, json={"status_code": 1, "results": {
            "id": 42, "name": "Spider-Man", "powers": [{"name": "Agility"}, {"name": "Danger Sense"}]
        }})

    client = ComicVineClient("private", httpx.Client(transport=httpx.MockTransport(handler)))
    tools = {item.name: item for item in build_tools(client)}
    result = json.loads(tools["get_character_powers"].invoke({"character_id": 42}))
    assert result["character"] == "Spider-Man"
    assert [power["name"] for power in result["powers"]] == ["Agility", "Danger Sense"]
