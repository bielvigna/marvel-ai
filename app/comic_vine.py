import hashlib
import json
import threading
import time
from collections import OrderedDict
from typing import Any
from urllib.parse import quote

import httpx


BASE_URL = "https://comicvine.gamespot.com/api/"
CHARACTER_FIELDS = "id,name,real_name,deck,description,image,publisher,origin,powers,teams,first_appeared_in_issue,count_of_issue_appearances,api_detail_url"
LIST_FIELDS = "id,name,real_name,deck,image,publisher,origin,powers,teams,first_appeared_in_issue,count_of_issue_appearances,api_detail_url"
ALLOWED_RESOURCES = {"characters", "character", "teams", "team", "issues", "issue", "story_arcs", "story_arc", "powers", "power", "movies", "movie", "locations", "location", "publishers", "publisher"}
MAX_RELATION_LOOKUPS_PER_PAGE = 5
RELATION_CACHE_TTL_SECONDS = 6 * 60 * 60
RELATION_CACHE_MAX_ITEMS = 2048
MAX_CONCURRENT_RELATION_LOOKUPS = 2
_relation_cache: OrderedDict[tuple[str, int], tuple[float, dict[str, Any]]] = OrderedDict()
_relation_cache_lock = threading.Lock()
_relation_lookup_slots = threading.BoundedSemaphore(MAX_CONCURRENT_RELATION_LOOKUPS)


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
        # Comic Vine's character detail endpoint requires the resource key (4005-<id>),
        # while list responses expose only the numeric id.
        detail_key = f"4005-{resource_id}" if resource == "character" and resource_id is not None else resource_id
        path = f"{resource}/{detail_key}/" if detail_key is not None else f"{resource}/"
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

    def search_characters(self, query: str = "", limit: int = 20, offset: int = 0,
                          include_relations: bool = False) -> dict[str, Any]:
        safe_limit = min(max(limit, 1), 50)
        if include_relations:
            safe_limit = min(safe_limit, MAX_RELATION_LOOKUPS_PER_PAGE)
        payload = self._get("characters", filter_value=f"name:{query}" if query else None,
                            fields=LIST_FIELDS, limit=safe_limit, offset=offset)
        results = [mapped for raw in payload.get("results", []) if (mapped := map_character(raw))]
        relation_complete = True
        if include_relations:
            for index, character in enumerate(results):
                details = self._cached_character_details(character["id"])
                if details is not None:
                    results[index] = details
                else:
                    relation_complete = False
        total = int(payload.get("number_of_total_results", len(results)) or 0)
        safe_offset = max(offset, 0)
        next_offset = safe_offset + len(results)
        return {"results": results, "offset": safe_offset, "limit": safe_limit, "total": total,
                "has_more": next_offset < total, "relations_complete": relation_complete,
                "next_offset": next_offset}

    def _cached_character_details(self, character_id: int) -> dict[str, Any] | None:
        cache_key = (hashlib.sha256(self.api_key.encode("utf-8")).hexdigest(), character_id)
        now = time.monotonic()
        with _relation_cache_lock:
            cached = _relation_cache.get(cache_key)
            if cached is not None and now - cached[0] < RELATION_CACHE_TTL_SECONDS:
                _relation_cache.move_to_end(cache_key)
                return cached[1]
            if cached is not None:
                del _relation_cache[cache_key]
        try:
            with _relation_lookup_slots:
                details = self.get_character(character_id)
        except ComicVineError:
            return None
        with _relation_cache_lock:
            _relation_cache[cache_key] = (now, details)
            _relation_cache.move_to_end(cache_key)
            while len(_relation_cache) > RELATION_CACHE_MAX_ITEMS:
                _relation_cache.popitem(last=False)
        return details

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
