import httpx
import pytest

from app.comic_vine import ComicVineClient, ComicVineError, map_character


def test_map_character_handles_missing_optional_fields():
    character = map_character({"id": 1, "name": "Spider-Man", "image": {"medium_url": "https://img.test/a.jpg"}})
    assert character["name"] == "Spider-Man"
    assert character["real_name"] is None
    assert character["powers"] == []
    assert character["image_url"] == "https://img.test/a.jpg"


def test_map_character_ignores_invalid_rows():
    assert map_character({"name": "Missing ID"}) is None
    assert map_character({"id": 10}) is None


def test_search_clamps_limit_and_maps_api_page():
    def handler(request):
        assert request.url.params["limit"] == "50"
        assert request.url.params["offset"] == "0"
        return httpx.Response(200, json={"status_code": 1, "number_of_total_results": 2,
                                         "results": [{"id": 1, "name": "Hero"}]})

    client = ComicVineClient("secret", httpx.Client(transport=httpx.MockTransport(handler)))
    page = client.search_characters(limit=99, offset=-2)
    assert page["limit"] == 50
    assert page["offset"] == 0
    assert page["has_more"] is True


def test_api_key_is_never_in_normalized_response():
    def handler(request):
        assert request.url.params["api_key"] == "private-key"
        return httpx.Response(200, json={"status_code": 1, "number_of_total_results": 1,
                                         "results": [{"id": 2, "name": "Hero"}]})

    client = ComicVineClient("private-key", httpx.Client(transport=httpx.MockTransport(handler)))
    assert "private-key" not in str(client.search_characters())


def test_invalid_api_key_maps_to_authorization_error():
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={"status_code": 100, "error": "Invalid API Key"}))
    client = ComicVineClient("bad-key", httpx.Client(transport=transport))
    with pytest.raises(ComicVineError) as error:
        client.search_characters()
    assert error.value.status_code == 401


def test_rate_limit_and_timeout_have_typed_errors():
    rate_limited = ComicVineClient("key", httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(429))))
    with pytest.raises(ComicVineError) as rate_error:
        rate_limited.search_characters()
    assert rate_error.value.status_code == 429
    timeout_client = httpx.Client(transport=httpx.MockTransport(lambda request: (_ for _ in ()).throw(httpx.ReadTimeout("timeout"))))
    timed_out = ComicVineClient("key", timeout_client)
    with pytest.raises(ComicVineError) as timeout_error:
        timed_out.search_characters()
    assert timeout_error.value.code == "comic_vine_timeout"


def test_character_detail_uses_comic_vine_character_key():
    def handler(request):
        assert request.url.path.endswith("/character/4005-77/")
        return httpx.Response(200, json={"status_code": 1, "results": {
            "id": 77, "name": "Hero", "powers": [{"id": 1, "name": "Flight"}],
            "teams": [{"id": 2, "name": "Avengers"}],
        }})

    client = ComicVineClient("secret", httpx.Client(transport=httpx.MockTransport(handler)))
    character = client.get_character(77)
    assert character["powers"] == [{"id": 1, "name": "Flight", "api_detail_url": None}]
    assert character["teams"] == [{"id": 2, "name": "Avengers", "api_detail_url": None}]


def test_relationship_enrichment_is_opt_in_for_paged_search():
    paths = []

    def handler(request):
        paths.append(request.url.path)
        if request.url.path.endswith("/characters/"):
            return httpx.Response(200, json={"status_code": 1, "number_of_total_results": 1,
                "results": [{"id": 77, "name": "Hero", "powers": [], "teams": []}]})
        return httpx.Response(200, json={"status_code": 1, "results": {
            "id": 77, "name": "Hero", "powers": [{"id": 1, "name": "Flight"}],
            "teams": [{"id": 2, "name": "Avengers"}],
        }})

    client = ComicVineClient("secret", httpx.Client(transport=httpx.MockTransport(handler)))
    page = client.search_characters(limit=1, include_relations=True)
    assert len(paths) == 2
    assert page["results"][0]["powers"][0]["name"] == "Flight"
    assert page["results"][0]["teams"][0]["name"] == "Avengers"
    assert page["relations_complete"] is True


def test_relationship_enrichment_never_exceeds_five_cache_misses_per_page():
    detail_calls = []

    def handler(request):
        if request.url.path.endswith("/characters/"):
            assert request.url.params["limit"] == "5"
            return httpx.Response(200, json={"status_code": 1, "number_of_total_results": 100,
                "results": [{"id": 9000 + index, "name": f"Hero {index}"} for index in range(5)]})
        detail_calls.append(request.url.path)
        character_id = int(request.url.path.rsplit("-", 1)[1].strip("/"))
        return httpx.Response(200, json={"status_code": 1, "results": {
            "id": character_id, "name": f"Hero {character_id}", "powers": [{"id": 1, "name": "Flight"}],
        }})

    client = ComicVineClient("bounded-test-key", httpx.Client(transport=httpx.MockTransport(handler)))
    page = client.search_characters(limit=8, offset=10, include_relations=True)
    assert len(page["results"]) == 5
    assert len(detail_calls) == 5
    assert page["relations_complete"] is True
    assert page["offset"] == 10
    assert page["next_offset"] == 15
    assert page["has_more"] is True


def test_relationship_enrichment_reuses_cached_details():
    detail_calls = []

    def handler(request):
        if request.url.path.endswith("/characters/"):
            return httpx.Response(200, json={"status_code": 1, "number_of_total_results": 1,
                "results": [{"id": 987654, "name": "Cached Hero"}]})
        detail_calls.append(request.url.path)
        return httpx.Response(200, json={"status_code": 1, "results": {
            "id": 987654, "name": "Cached Hero", "teams": [{"id": 2, "name": "Avengers"}],
        }})

    client = ComicVineClient("cache-test-key", httpx.Client(transport=httpx.MockTransport(handler)))
    first = client.search_characters(limit=1, include_relations=True)
    second = client.search_characters(limit=1, include_relations=True)
    assert len(detail_calls) == 1
    assert first["results"][0]["teams"] == second["results"][0]["teams"]
