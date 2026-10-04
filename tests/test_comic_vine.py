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
