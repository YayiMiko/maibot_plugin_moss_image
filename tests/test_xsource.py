"""Offline X discovery and association boundaries."""

import io
import json
from urllib.parse import urlsplit

import pytest
from PIL import Image

from moss.aesthetics import BUILTIN_SOURCES, SourceRule
from moss.config import MossConfig
from moss.discovery import DiscoveryRouter
from moss.references import (
    ReferenceClient,
    ReferenceError,
    canonical_page_key,
)
from moss.xsource import XReferenceClient, content_flags

HISTORICAL_PROMPT_POSTS = [
    "How to create your baroque style portrait: use the tool, add this prompt, preserve the face.",
    "Baroque candlelight oil painting prompt: preserve identity and create a portrait.",
    "Prompt: a masterly chiaroscuro oil painting portrait of a young woman.",
    "Prompt: a classical oil painting portrait of a young woman.",
]


def png_bytes():
    output = io.BytesIO()
    Image.new("RGB", (512, 768), "white").save(output, "PNG")
    return output.getvalue()


class FakeHTTP:
    def __init__(self, search_results, page, syndication, image=None):
        self.search_results = search_results
        self.page = page
        self.syndication = syndication
        self.image = image or png_bytes()
        self.page_url = "https://x.com/i/status/123"
        self.calls = []

    def __call__(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if url == "https://api.tavily.com/search":
            return (
                url,
                "application/json",
                json.dumps({"results": self.search_results}).encode(),
            )
        if url == self.page_url:
            return url, "text/html", self.page.encode()
        if url.startswith("https://cdn.syndication.twimg.com/tweet-result"):
            return url, "application/json", json.dumps(self.syndication).encode()
        if url.startswith("https://pbs.twimg.com/media/"):
            return url, "image/png", self.image
        raise AssertionError(f"Unexpected URL: {url}")


def page_html(og="https://pbs.twimg.com/media/AAA?format=jpg&amp;name=large"):
    return (
        '<meta property="og:title" content="X post">'
        f'<meta property="og:image" content="{og}">'
    )


def syndication_data(
    *, text="A complete character poster", photos=None, tweet_id="123"
):
    if photos is None:
        photos = [
            {"type": "photo", "media_url_https": "https://pbs.twimg.com/media/AAA.jpg"},
            {"type": "photo", "media_url_https": "https://pbs.twimg.com/media/BBB.jpg"},
        ]
    return {
        "id_str": tweet_id,
        "text": text,
        "created_at": "2026-10-01T12:00:00.000Z",
        "user": {"screen_name": "artist"},
        "mediaDetails": [
            {
                **item,
                "sizes": {"large": {"w": 1024, "h": 1536}},
            }
            for item in photos
        ],
    }


def run_client(monkeypatch, http, config=None):
    monkeypatch.setattr("moss.references.safe_http", http)
    return XReferenceClient(config or MossConfig().draw)


def test_search_returns_only_canonical_status_urls_and_counts_duplicates(monkeypatch):
    results = [
        {"url": "https://x.com/artist/status/123/photo/1"},
        {"url": "https://x.com/artist/status/123?s=20"},
        {"url": "https://x.com/i/trending/999"},
        {"url": "https://x.com/profile"},
        {"url": "https://x.com/other/status/456"},
    ]
    http = FakeHTTP(results, page_html(), syndication_data())
    client = run_client(monkeypatch, http)

    async def run():
        pages = await client.search("game character poster")
        assert pages == [
            "https://x.com/i/status/123",
            "https://x.com/i/status/456",
        ]
        assert client.calls == 1
        trace = client.searches[0]
        assert trace["returned"] == 5 and trace["accepted"] == 2
        assert {item["reason"] for item in trace["filtered"]} == {
            "duplicate_result",
            "not_a_post",
        }
        payload = http.calls[0][1]["payload"]
        assert payload["include_domains"] == ["x.com"]
        assert payload["include_images"] is False

    __import__("asyncio").run(run())


def test_candidate_confirms_same_post_and_prefers_og_media(monkeypatch):
    http = FakeHTTP([], page_html(), syndication_data())
    client = run_client(monkeypatch, http)

    async def run():
        record, content = await client.candidate("https://x.com/artist/status/123", 1)
        assert content and record["id"] == "candidate-1"
        assert record["association"]["syndication_id_match"] is True
        assert record["association"]["photo_count"] == 2
        assert record["image_origin"] == "x_og"
        assert record["image"] == "https://pbs.twimg.com/media/AAA.jpg"
        assert record["source_route"] == "x"
        assert record["author"] == "artist"
        assert record["content_flags"] == []
        assert record["width"] == 512 and record["height"] == 768
        assert client.pages == 1

    __import__("asyncio").run(run())


@pytest.mark.parametrize(
    ("text", "expected_flags"),
    [
        ("Prompt: create a retro anime poster", ["tutorial_or_template"]),
        ("Buy now. Link in bio.", ["sales_mention"]),
        ("A product shot of a manhole cover", ["product_mention"]),
        ("Pre-order the new character figure", ["sales_mention"]),
    ],
)
def test_candidate_keeps_prompt_or_sales_text_for_image_review(
    monkeypatch, text, expected_flags
):
    http = FakeHTTP([], page_html(), syndication_data(text=text))
    client = run_client(monkeypatch, http)

    async def run():
        record, _ = await client.candidate("https://x.com/artist/status/123", 1)
        assert record["content_flags"] == expected_flags
        assert record["image_decoded"] is True

    __import__("asyncio").run(run())


@pytest.mark.parametrize(
    "text",
    [
        "How to Train Your Dragon character poster",
        "A complete character poster made with Midjourney.",
    ],
)
def test_candidate_keeps_artwork_despite_title_or_ai_tool_mention(monkeypatch, text):
    http = FakeHTTP([], page_html(), syndication_data(text=text))
    client = run_client(monkeypatch, http)

    async def run():
        record, _ = await client.candidate("https://x.com/artist/status/123", 1)
        assert record["content_flags"] == (
            ["ai_tool_mention"] if "Midjourney" in text else []
        )

    __import__("asyncio").run(run())


@pytest.mark.parametrize("text", HISTORICAL_PROMPT_POSTS)
def test_historical_prompt_posts_reach_image_review(monkeypatch, text):
    http = FakeHTTP([], page_html(), syndication_data(text=text))
    client = run_client(monkeypatch, http)

    async def run():
        record, _ = await client.candidate("https://x.com/artist/status/123", 1)
        assert "tutorial_or_template" in record["content_flags"]
        assert record["image_decoded"] is True
        assert record["association"]["syndication_id_match"] is True

    __import__("asyncio").run(run())


def test_candidate_rejects_no_media_video_and_id_mismatch(monkeypatch):
    cases = [
        (syndication_data(photos=[]), "no_media"),
        (
            syndication_data(
                photos=[
                    {
                        "type": "video",
                        "media_url_https": "https://pbs.twimg.com/media/AAA.mp4",
                    }
                ]
            ),
            "no_media",
        ),
        (syndication_data(tweet_id="999"), "association_unavailable"),
    ]
    for data, code in cases:
        http = FakeHTTP([], page_html(), data)
        client = run_client(monkeypatch, http)

        async def run():
            with pytest.raises(ReferenceError) as failure:
                await client.candidate("https://x.com/artist/status/123", 1)
            assert failure.value.details["code"] == code

        __import__("asyncio").run(run())


def test_candidate_propagates_page_failure(monkeypatch):
    def http(url, **kwargs):
        if url == "https://x.com/i/status/123":
            raise ReferenceError("http_status", stage="page", url=url, status=404)
        raise AssertionError(url)

    client = run_client(monkeypatch, http)

    async def run():
        with pytest.raises(ReferenceError) as failure:
            await client.candidate("https://x.com/i/status/123", 1)
        assert failure.value.details["http_status"] == 404

    __import__("asyncio").run(run())


def test_content_flags_are_hints_only():
    assert content_flags("A finished poster made with DALL-E") == ["ai_tool_mention"]
    assert "tutorial_or_template" in content_flags("Prompt: use this template")
    assert content_flags("How to Train Your Dragon character poster") == []


def test_canonical_page_keys_collapse_locale_and_author_subdomains():
    assert (
        canonical_page_key(
            "https://www.behance.net/gallery/204988273/Grid-poster?locale=ru_RU"
        )
        == "behance.net/gallery/204988273"
    )
    assert (
        canonical_page_key(
            "https://www.behance.net/gallery/204988273/Grid-poster/modules/1"
        )
        == "behance.net/gallery/204988273"
    )
    assert (
        canonical_page_key("https://joelcodina.artstation.com/projects/bg3dxo")
        == "artstation.com/bg3dxo"
    )
    assert (
        canonical_page_key("https://www.artstation.com/artwork/3q5eVD")
        == "artstation.com/3q5eVD"
    )
    assert (
        canonical_page_key("https://www.pentagram.com/work/poster-house/story")
        == "pentagram.com/work/poster-house"
    )
    assert (
        canonical_page_key("https://www.abduzeedo.com/poster-a?utm_source=test")
        == "abduzeedo.com/poster-a"
    )


def test_default_sources_are_abduzeedo_only():
    assert {source.domain for source in BUILTIN_SOURCES} == {"www.abduzeedo.com"}
    assert [source.path_prefix for source in BUILTIN_SOURCES] == ["/"]
    assert not any(source.domain == "www.behance.net" for source in BUILTIN_SOURCES)


def test_artstation_author_subdomain_parser_remains_reusable():
    rule = SourceRule(
        domain="artstation.com",
        path_prefix="/projects/",
        evidence="Reusable ArtStation project parser kept for explicit sources.",
        allow_subdomains=True,
    )
    assert rule.matches(urlsplit("https://joelcodina.artstation.com/projects/bg3dxo"))
    assert not rule.matches(urlsplit("https://example.com/projects/bg3dxo"))


def test_reference_client_collapses_canonical_duplicates(monkeypatch):
    results = [
        {"url": "https://abduzeedo.com/poster-a"},
        {"url": "https://www.abduzeedo.com/poster-a?utm_source=test"},
    ]

    def http(url, **kwargs):
        if kwargs.get("payload") is not None:
            return (
                url,
                "application/json",
                json.dumps({"results": results}).encode(),
            )
        raise AssertionError(url)

    monkeypatch.setattr("moss.references.safe_http", http)
    client = ReferenceClient(MossConfig().draw, BUILTIN_SOURCES)

    async def run():
        pages = await client.search("graphic design")
        assert pages == ["https://abduzeedo.com/poster-a"]
        assert {item["reason"] for item in client.searches[0]["filtered"]} == {
            "duplicate_result"
        }

    __import__("asyncio").run(run())


def test_first_search_request_is_abduzeedo_only_even_with_mixed_sources(monkeypatch):
    sources = (
        SourceRule(
            domain="www.abduzeedo.com",
            path_prefix="/",
            evidence="Default Abduzeedo article source.",
        ),
        SourceRule(
            domain="www.artstation.com",
            path_prefix="/artwork/",
            evidence="Reusable but not default ArtStation source.",
        ),
    )
    payloads = []

    def http(url, **kwargs):
        payloads.append(kwargs.get("payload"))
        return url, "application/json", json.dumps({"results": []}).encode()

    monkeypatch.setattr("moss.references.safe_http", http)
    client = ReferenceClient(MossConfig().draw, sources)

    async def run():
        assert await client.search("poster design") == []
        assert payloads[0]["include_domains"] == ["www.abduzeedo.com"]
        assert client.searches[0]["domains"] == ["www.abduzeedo.com"]

    __import__("asyncio").run(run())


def test_reference_client_accepts_artstation_with_explicit_source(monkeypatch):
    sources = (
        SourceRule(
            domain="artstation.com",
            path_prefix="/projects/",
            evidence="Reusable ArtStation project parser kept for explicit sources.",
            allow_subdomains=True,
        ),
    )

    def http(url, **kwargs):
        if kwargs.get("payload") is not None:
            return (
                url,
                "application/json",
                json.dumps(
                    {
                        "results": [
                            {"url": "https://joelcodina.artstation.com/projects/bg3dxo"}
                        ]
                    }
                ).encode(),
            )
        raise AssertionError(url)

    monkeypatch.setattr("moss.references.safe_http", http)
    client = ReferenceClient(MossConfig().draw, sources)

    async def run():
        pages = await client.search("graphic design")
        assert pages == ["https://joelcodina.artstation.com/projects/bg3dxo"]

    __import__("asyncio").run(run())


def test_obsolete_draw_routing_config_is_ignored_without_reset():
    config = MossConfig.model_validate(
        {
            "draw": {
                "enabled": True,
                "tavily_api_key": "offline-test-key",
                "profile": {"legacy": True},
                "sources": ["https://www.artstation.com/artwork/"],
                "publisher_sources": ["artstation"],
                "limits": {"search_budget": 2, "prepare_timeout": 180},
            }
        }
    )
    assert config.draw.enabled is True
    assert config.draw.tavily_api_key == "offline-test-key"
    assert config.draw.limits.search_budget == 2
    assert not hasattr(config.draw, "sources")
    assert not hasattr(config.draw, "profile")


def test_discovery_router_uses_publisher_then_x_with_shared_budget(monkeypatch):
    created = []

    class Stub:
        def __init__(self, name, config, *args):
            self.name = name
            self.calls = 0
            self.pages = 0
            self.searches = []
            self.page_priorities = {}
            created.append(self)

        async def search(self, query, *, sources=None):
            self.calls += 1
            self.searches.append({"route": self.name, "query": query})
            return [f"https://{self.name}.example/{len(self.searches)}"]

        async def candidate(self, page_url, number):
            self.pages += 1
            return {"page": page_url, "id": f"candidate-{number}"}, b"image"

    def x_client(config):
        return Stub("x", config)

    def publisher_client(config, sources):
        return Stub("publisher", config, sources)

    monkeypatch.setattr("moss.discovery.XReferenceClient", x_client)
    monkeypatch.setattr("moss.discovery.ReferenceClient", publisher_client)
    monkeypatch.setattr("moss.xsource.X_ENABLED", True)
    router = DiscoveryRouter(MossConfig().draw, [])

    async def run():
        first = await router.search("first")
        second = await router.search("second")
        third = await router.search("third")
        assert first == [("https://publisher.example/1", "publisher")]
        assert second == [("https://x.example/1", "x")]
        assert third == []
        assert router.calls == 2
        record, _ = await router.candidate(first[0][0], 1, "publisher")
        assert record["page"] == "https://publisher.example/1"

    __import__("asyncio").run(run())
    assert router.order == ["publisher", "x"]
    assert {item.name for item in created} == {"x", "publisher"}
