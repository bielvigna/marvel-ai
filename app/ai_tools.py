import json
from typing import Any

from langchain.tools import tool

from .comic_vine import ComicVineClient


def build_tools(client: ComicVineClient):
    def search(resource: str, query: str, detail_name: str):
        @tool(name_or_callable=f"search_{resource.rstrip('s')}")
        def search_tool(name: str) -> str:
            """Search Comic Vine for a named entity. Use this before making factual claims."""
            results = client.search_resource(resource, name)
            return json.dumps({"source": "Comic Vine", "source_url": "https://comicvine.gamespot.com/", "results": results}, ensure_ascii=False)
        return search_tool

    def detail(resource: str):
        singular = resource.rstrip("s")

        @tool(name_or_callable=f"get_{singular}_details")
        def detail_tool(entity_id: int) -> str:
            """Get verified Comic Vine details for an entity using its Comic Vine ID."""
            result = client.get_resource(resource, entity_id)
            return json.dumps({"source": "Comic Vine", "source_url": result.get("api_detail_url") or "https://comicvine.gamespot.com/", "result": result}, ensure_ascii=False)
        return detail_tool

    @tool
    def search_character(name: str) -> str:
        """Find Marvel and comic characters by name in Comic Vine."""
        return json.dumps({"source": "Comic Vine", "source_url": "https://comicvine.gamespot.com/", "results": client.search_characters(name, 10, 0)["results"]}, ensure_ascii=False)

    @tool
    def get_character_details(character_id: int) -> str:
        """Get a character profile from Comic Vine by its numeric character ID."""
        result = client.get_character(character_id)
        return json.dumps({"source": "Comic Vine", "source_url": result.get("api_detail_url") or "https://comicvine.gamespot.com/", "result": result}, ensure_ascii=False)

    @tool
    def get_character_powers(character_id: int) -> str:
        """Get the listed powers for a Comic Vine character ID."""
        result = client.get_character(character_id)
        return json.dumps({"source": "Comic Vine", "source_url": result.get("api_detail_url") or "https://comicvine.gamespot.com/", "character": result["name"], "powers": result["powers"]}, ensure_ascii=False)

    return [search_character, get_character_details, get_character_powers,
            search("teams", "", "team"), detail("teams"),
            search("story_arcs", "", "story_arc"), detail("story_arcs"),
            search("issues", "", "issue"), detail("issues"),
            search("movies", "", "movie")]
