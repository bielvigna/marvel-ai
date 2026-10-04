import json
from typing import Any
from urllib.parse import quote

import httpx


BASE_URL = "https://comicvine.gamespot.com/api/"
CHARACTER_FIELDS = "id,name,real_name,deck,description,image,publisher,origin,powers,teams,first_appeared_in_issue,count_of_issue_appearances,api_detail_url"
LIST_FIELDS = "id,name,real_name,deck,image,publisher,origin,powers,teams,first_appeared_in_issue,count_of_issue_appearances,api_detail_url"
ALLOWED_RESOURCES = {"characters", "character", "teams", "team", "issues", "issue", "story_arcs", "story_arc", "powers", "power", "movies", "movie", "locations", "location", "publishers", "publisher"}


class ComicVineError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 502):
        self.code = code
        self.message = message
        self.status_code = status_code
        super().__init__(message)


def _item(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    name = value.get("name")
    if not name:
        return None
    return {"id": value.get("id"), "name": name, "api_detail_url": value.get("api_detail_url")}


def map_character(raw: dict[str, Any]) -> dict[str, Any] | None:
    if not raw.get("id") or not raw.get("name"):
        return None
    image = raw.get("image") or {}
    powers = [_item(item) for item in (raw.get("powers") or [])]
    teams = [_item(item) for item in (raw.get("teams") or [])]
    first_issue = _item(raw.get("first_appeared_in_issue"))
    description = raw.get("description")
    return {
        "id": raw["id"],
        "name": raw["name"],
        "real_name": raw.get("real_name") or None,
        "deck": raw.get("deck") or None,
        "description": description if isinstance(description, str) else None,
        "image_url": image.get("medium_url") or image.get("small_url") or image.get("thumb_url") or image.get("original_url"),
        "publisher": _item(raw.get("publisher")),
        "origin": _item(raw.get("origin")),
        "powers": [item for item in powers if item],
        "teams": [item for item in teams if item],
        "first_appeared_in_issue": first_issue,
        "count_of_issue_appearances": raw.get("count_of_issue_appearances"),
        "api_detail_url": raw.get("api_detail_url"),
    }


class ComicVineClient:
    def __init__(self, api_key: str, client: httpx.Client | None = None):
        self.api_key = api_key
        self.client = client or httpx.Client(
            timeout=httpx.Timeout(12.0),
            headers={"User-Agent": "HeroNexus/1.0 (Comic Vine powered character companion)"},
        )
        self._owns_client = client is None

    def close(self) -> None:
        if self._owns_client:
            self.client.close()

    def _get(self, resource: str, *, filter_value: str | None = None, resource_id: int | None = None,
             fields: str = LIST_FIELDS, limit: int = 20, offset: int = 0) -> dict[str, Any]:
        if resource not in ALLOWED_RESOURCES:
            raise ComicVineError("invalid_resource", "Unsupported Comic Vine resource.", 400)
        if not self.api_key:
            raise ComicVineError("comic_vine_not_configured", "Configure COMIC_VINE_API_KEY no arquivo .env do backend.", 503)
        limit = min(max(limit, 1), 50)
        offset = max(offset, 0)
        path = f"{resource}/{resource_id}/" if resource_id is not None else f"{resource}/"
        params: dict[str, Any] = {"api_key": self.api_key, "format": "json", "field_list": fields}
        if resource_id is None:
            params.update(limit=limit, offset=offset)
        if filter_value:
            params["filter"] = filter_value
        try:
            response = self.client.get(BASE_URL + path, params=params)
        except httpx.TimeoutException as exc:
            raise ComicVineError("comic_vine_timeout", "Comic Vine did not respond in time.", 504) from exc
        except httpx.HTTPError as exc:
            raise ComicVineError("comic_vine_unavailable", "Could not reach Comic Vine.", 502) from exc
        if response.status_code == 429:
            raise ComicVineError("comic_vine_rate_limited", "Comic Vine rate limit reached. Try again shortly.", 429)
        if response.status_code >= 500:
            raise ComicVineError("comic_vine_unavailable", "Comic Vine is temporarily unavailable.", 502)
        try:
            payload = response.json()
        except (ValueError, json.JSONDecodeError) as exc:
            raise ComicVineError("comic_vine_invalid_response", "Comic Vine returned invalid data.", 502) from exc
        if payload.get("status_code") != 1:
            error = str(payload.get("error", "Comic Vine request failed"))
            code = "comic_vine_invalid_key" if "api key" in error.lower() or "access" in error.lower() else "comic_vine_error"
            status = 401 if code == "comic_vine_invalid_key" else 502
            message = "A chave da Comic Vine no backend é inválida." if status == 401 else "A consulta à Comic Vine falhou."
            raise ComicVineError(code, message, status)
        return payload

    def search_characters(self, query: str = "", limit: int = 20, offset: int = 0) -> dict[str, Any]:
        payload = self._get("characters", filter_value=f"name:{query}" if query else None,
                            fields=LIST_FIELDS, limit=limit, offset=offset)
        results = [mapped for raw in payload.get("results", []) if (mapped := map_character(raw))]
        total = int(payload.get("number_of_total_results", len(results)) or 0)
        safe_limit = min(max(limit, 1), 50)
        safe_offset = max(offset, 0)
        return {"results": results, "offset": safe_offset, "limit": safe_limit, "total": total,
                "has_more": safe_offset + len(results) < total}

    def get_character(self, character_id: int) -> dict[str, Any]:
        payload = self._get("character", resource_id=character_id, fields=CHARACTER_FIELDS)
        result = payload.get("results") or {}
        mapped = map_character(result)
        if mapped is None:
            raise ComicVineError("character_not_found", "Character not found.", 404)
        return mapped

    def search_resource(self, resource: str, query: str, limit: int = 10) -> list[dict[str, Any]]:
        payload = self._get(resource, filter_value=f"name:{query}", fields="id,name,deck,description,image,api_detail_url", limit=limit)
        return payload.get("results", [])[:min(max(limit, 1), 20)]

    def get_resource(self, resource: str, resource_id: int) -> dict[str, Any]:
        payload = self._get(resource.rstrip("s"), resource_id=resource_id,
                            fields="id,name,deck,description,image,publisher,characters,issues,first_appeared_in_issue,api_detail_url")
        return payload.get("results", {})
