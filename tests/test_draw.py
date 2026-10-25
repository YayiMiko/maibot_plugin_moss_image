"""Curation boundaries against real orchestration and completely offline services."""

import asyncio
import io
import json
import socket
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from PIL import Image, ImageDraw

from moss.aesthetics import Aesthetics, SourceRule
from moss.commands import parse_command
from moss.config import MossConfig
from moss.draw import _second_search_plan, reference_failure_reason
from moss.draw_models import DrawError
from moss.references import ReferenceError, cache_reference, normalize_image, safe_http


@pytest.fixture
def draw_setup(plugin, command, monkeypatch):
    """Distinct offline works and deterministic request-local models."""
    plugin.config.draw.enabled = True
    plugin.config.draw.tavily_api_key = "private-test-search-key"
    monkeypatch.setattr("moss.draw.secrets.randbits", lambda _: 0)
    artworks = []
    for index in range(4):
        buffer = io.BytesIO()
        image = Image.new("RGB", (768, 512), (50 + index * 40, 80, 120))
        pen = ImageDraw.Draw(image)
        for x in range(9):
            for y in range(8):
                pen.rectangle(
                    (x * 85, y * 64, x * 85 + 60, y * 64 + 45),
                    fill=(255 if (x * (index + 1) + y) % 3 else 0, 180, 20),
                )
        image.save(buffer, "PNG")
        artworks.append(buffer.getvalue())
    sources = [
        SourceRule(
            domain=name, path_prefix="/works/", evidence="Offline publisher fixture"
        )
        for name in ["art.example.com", "design.example.com"]
    ]
    monkeypatch.setattr("moss.aesthetics.BUILTIN_SOURCES", tuple(sources))
    monkeypatch.setattr("moss.xsource.X_ENABLED", False)
    command["text"] = "/moss 抽卡 少女，单人，不要文字"
    state = {
        "downloads": [],
        "searches": 0,
        "reviews": 0,
        "reject": 0,
        "blocked": False,
        "broken": False,
        "requests": [],
        "repair": False,
        "brief_calls": 0,
        "brief_bad": 0,
    }

    def http(url, **kwargs):
        if "payload" in kwargs:
            state["searches"] += 1
            state.setdefault("queries", []).append(kwargs["payload"])
            if state.get("search_error") == state["searches"]:
                raise ReferenceError("timeout", stage="search", url=url)
            assert kwargs["key"] == "private-test-search-key"
            return (
                url,
                "application/json",
                json.dumps(
                    {
                        "results": state["result_sets"][state["searches"] - 1]
                        if "result_sets" in state
                        else []
                        if state.get("empty_results")
                        else [
                            {"url": f"https://art.example.com/works/{i}"}
                            for i in range(3)
                        ],
                        "images": ["https://unrelated.example.com/false.jpg"],
                    }
                ).encode(),
            )
        if "/works/" in url:
            state.setdefault("page_reads", []).append(url)
            if url in state.get("page_failures", []):
                raise ReferenceError("http_status", stage="page", url=url, status=403)
            return (
                url,
                "text/html",
                f'<meta property="og:title" content="A complete artwork"><meta property="og:image" content="https://art.example.com/image{url[-1]}.png">'.encode(),
            )
        state["downloads"].append(url)
        if state["broken"]:
            raise ReferenceError(
                "http_status",
                stage="image",
                url=url + "?token=private-signed-token",
                status=403,
            )
        return url, "image/png", artworks[int(url[-5]) % len(artworks)]

    async def generate(messages, **kwargs):
        state["requests"].append(messages)
        assert "private-test-search-key" not in json.dumps(messages)
        system = messages[0]["content"]
        if system.startswith("Prepare a discovery"):
            state["brief_calls"] += 1
            brief_input = json.loads(messages[1]["content"])
            original = brief_input["request"]
            response = {
                "constraints": [
                    {"source": source, "requirement": requirement}
                    for source, requirement in [
                        ("单人", "one person"),
                        ("不要文字", "no lettering"),
                        ("水彩画", "watercolor treatment"),
                    ]
                    if source in original
                ],
                "creative_freedom": "setting and framing",
                "reference_requirements": [
                    {"source": "海报", "requirement": "poster design"}
                ]
                if state.get("poster")
                else [],
                "query": "curated editorial artwork",
                "design_intent": "Editorial portrait poster exploration",
                "alternatives": [
                    {
                        "query": "geometric expressive design",
                        "design_intent": "Geometric poster exploration",
                    },
                    {
                        "design_intent": "Cinematic poster exploration",
                        "query": "expressive cinematic poster design"
                        if state.get("poster")
                        else "expressive editorial color composition",
                    },
                ],
            }
            if state.get("identity_locked") and state["brief_calls"] == 1:
                response["query"] = (
                    "Wuthering Waves Cartethyia official character art illustration"
                )
            if state["brief_calls"] <= state["brief_bad"]:
                response["constraints"].append(
                    {
                        "source": "@yuasa akira",
                        "requirement": "Wrongly imported common preset",
                    }
                )
        elif system.startswith("You are a visual design editor"):
            state["reviews"] += 1
            if state["blocked"]:
                return {
                    "success": True,
                    "blocked": True,
                    "response": "Private provider refusal",
                }
            parts = messages[1]["content"]
            assert sum(item["type"] == "image_url" for item in parts) == 1
            current = json.loads(parts[0]["text"])
            state.setdefault("review_briefs", []).append(
                {
                    **current["exploration"],
                    "constraints": current["target_requirements"],
                    "reference_requirements": current["reference_requirements"],
                }
            )
            rejected = state["reviews"] <= state["reject"]
            response = {
                "candidate_id": current["candidate_id"],
                "template_usable": not rejected,
                "usable_relationships": []
                if rejected
                else [
                    "Central silhouette",
                    "Large negative space",
                    "Warm-cool contrast",
                ],
                "blocking_issues": []
                if not rejected
                else ["The composition would require a full redraw."],
                "required_replacements": ["Original subject identity"],
                "has_target_subject": True,
                "evidence": ["Clear silhouette and light-dark organization"],
                "blueprint": None
                if rejected
                else {
                    "composition": "Wide open space around a central subject",
                    "subjects": "One figure",
                    "light_palette": "Blue and cream",
                    "typography": "No text",
                    "medium_texture": "Flat brushwork",
                    "design_relationships": [
                        "Central silhouette",
                        "Large negative space",
                        "Warm-cool contrast",
                    ],
                    "remove_source_content": "Original subject identity",
                    "uncertainty": "",
                },
            }
        elif system.startswith("Identify only"):
            response = {
                "characters": [
                    {
                        "source_name": "卡缇希娅",
                        "copyright": "鸣潮",
                        "candidates": [],
                        "depicted": True,
                    }
                ]
            }
        else:
            assert "DRAW ADAPTATION" in system
            payload = json.loads(messages[1]["content"].split("\nRepair only")[0])
            response = {
                "keep": ["Negative space and color relationships"],
                "replace": ["Target character"],
                "remove": ["Source identity"],
                "recompose": [],
                "bindings": [
                    {"name": names[0], "item_index": None}
                    for names in payload["identity_groups"].values()
                ],
                "visible_texts": [],
                "mode": "caption",
                "draft": {
                    "caption": "A single girl in a blue and cream composition with negative space. No lettering."
                },
            }
            if "水彩画" in payload["request"]:
                response["draft"]["caption"] += " Watercolor illustration."
            if state.get("poster") or "海报" in payload["request"]:
                summary = response["draft"]["caption"]
                response.update(mode="layout", visible_texts=payload["fixed_texts"])
                for binding in response["bindings"]:
                    binding["item_index"] = 0
                response["draft"] = {
                    "width": payload["width"],
                    "height": payload["height"],
                    "bbox_coord_space": "abs",
                    "bbox_format": "xyxy",
                    "summary": {"caption": summary},
                    "items": [
                        {
                            "label": "character",
                            "caption": "A single girl",
                            "bbox": [0, 0, 300, 400],
                        },
                        *[
                            {
                                "label": "text",
                                "caption": "Clear headline",
                                "text": text,
                                "bbox": [300, 0, 600, 200],
                            }
                            for text in payload["fixed_texts"]
                        ],
                    ],
                }
            if state.get("export_bad"):
                response["visible_texts"] = ["wrong"]
            elif state["repair"] and "\nRepair only" not in messages[1]["content"]:
                response["visible_texts"] = ["wrong"]
        return {"success": True, "response": json.dumps(response)}

    monkeypatch.setattr("moss.references.safe_http", http)
    plugin.ctx.llm.generate.side_effect = generate
    return state, sources, None


HISTORICAL_MIXED_REFERENCES = [
    *[{"outcome": "unsuitable"} for _ in range(4)],
    *[{"outcome": "unreadable"} for _ in range(2)],
]


def test_reference_failure_reason_distinguishes_mixed_failures():
    assert reference_failure_reason([]) == "no_reference_results"
    assert reference_failure_reason([], True) == "search_unavailable"
    assert (
        reference_failure_reason([{"outcome": "unreadable"}, {"outcome": "unreadable"}])
        == "reference_unreadable"
    )
    assert (
        reference_failure_reason(
            [{"outcome": "duplicate"}, {"outcome": "incompatible_canvas"}]
        )
        == "no_compatible_reference"
    )
    assert (
        reference_failure_reason(HISTORICAL_MIXED_REFERENCES)
        == "mixed_reference_failure"
    )
    assert (
        reference_failure_reason([{"outcome": "duplicate"}, {"outcome": "unreadable"}])
        == "mixed_reference_failure"
    )


def test_second_search_plan_uses_failure_cause():
    assert _second_search_plan("x", True, False, 0, 0, True) == (
        "publisher",
        "source",
        "source_read_failure",
    )
    assert _second_search_plan("x", False, False, 2, 0, True) == (
        "publisher",
        "source",
        "source_read_failure",
    )
    assert _second_search_plan("x", False, False, 2, 1, True) == (
        "x",
        "query",
        "template_unusable_change_direction",
    )
    assert _second_search_plan("x", False, True, 0, 0, True) == (
        "x",
        "query",
        "empty_results_change_query",
    )
    assert _second_search_plan("publisher", True, False, 0, 0, False) == (
        "publisher",
        "query",
        "publisher_search_failure_change_query",
    )


def test_draw_brief_prompt_is_discovery_first(
    plugin, command, draw_setup, comfy_transport
):
    state, _, _ = draw_setup

    async def run():
        await plugin.on_load()
        await plugin.handle_moss(**command)
        await asyncio.gather(*list(plugin.jobs.values()))
        system = state["requests"][0][0]["content"]
        assert "Queries must discover existing works" in system
        assert "must not prescribe the final composition" in system
        assert "design_intent is only a short exploration angle" in system
        assert "game poster and anime poster are examples" in system
        adaptation = next(
            messages[0]["content"]
            for messages in state["requests"]
            if "DRAW ADAPTATION" in messages[0]["content"]
        )
        assert "Do not invent release dates" in adaptation
        assert "do not blank all poster text" in adaptation
        assert "not a copy of the schema" in adaptation
        await plugin.on_unload()

    asyncio.run(run())


def patterned_png(seed: int = 0) -> bytes:
    output = io.BytesIO()
    image = Image.new("RGB", (768, 512), (50 + seed * 40, 80, 120))
    pen = ImageDraw.Draw(image)
    for x in range(9):
        for y in range(8):
            pen.rectangle(
                (x * 85, y * 64, x * 85 + 60, y * 64 + 45),
                fill=(255 if (x * (seed + 1) + y) % 3 else 0, 180, 20),
            )
    image.save(output, "PNG")
    return output.getvalue()


def x_page_html(media_id: str) -> bytes:
    return (
        '<meta property="og:title" content="X artwork">'
        f'<meta property="og:image" content="https://pbs.twimg.com/media/{media_id}?format=jpg&amp;name=large">'
    ).encode()


def x_syndication(tweet_id: str, media_id: str) -> bytes:
    return json.dumps(
        {
            "id_str": tweet_id,
            "text": "Prompt: a complete character poster",
            "user": {"screen_name": "artist"},
            "mediaDetails": [
                {
                    "type": "photo",
                    "media_url_https": f"https://pbs.twimg.com/media/{media_id}.jpg",
                    "sizes": {"large": {"w": 768, "h": 512}},
                }
            ],
        }
    ).encode()


def test_draw_second_search_changes_query_after_template_unusable(
    plugin, command, draw_setup, comfy_transport, monkeypatch
):
    state, _, _ = draw_setup
    monkeypatch.setattr("moss.xsource.X_ENABLED", True)
    state["reject"] = 1
    images = {"AAA": patterned_png(0), "BBB": patterned_png(1)}
    search_calls = {"count": 0}

    def http(url, **kwargs):
        if "payload" in kwargs:
            assert kwargs["payload"]["include_domains"] == ["x.com"]
            search_calls["count"] += 1
            tweet_id = "123" if search_calls["count"] == 1 else "456"
            return (
                url,
                "application/json",
                json.dumps(
                    {"results": [{"url": f"https://x.com/artist/status/{tweet_id}"}]}
                ).encode(),
            )
        if url == "https://x.com/i/status/123":
            return url, "text/html", x_page_html("AAA")
        if url == "https://x.com/i/status/456":
            return url, "text/html", x_page_html("BBB")
        if url.startswith("https://cdn.syndication.twimg.com/tweet-result"):
            return (
                url,
                "application/json",
                x_syndication("123", "AAA")
                if "id=123" in url
                else x_syndication("456", "BBB"),
            )
        if "pbs.twimg.com/media/AAA" in url:
            return url, "image/png", images["AAA"]
        if "pbs.twimg.com/media/BBB" in url:
            return url, "image/png", images["BBB"]
        raise AssertionError(url)

    monkeypatch.setattr("moss.references.safe_http", http)

    async def run():
        await plugin.on_load()
        await plugin.handle_moss(**command)
        await asyncio.gather(*list(plugin.jobs.values()))
        record = json.loads(
            next(plugin.store.records.glob("*.json")).read_text(encoding="utf-8")
        )
        assert record["status"] == "sent", record
        discovery = json.loads(
            (
                plugin.store.runtime / record["task_id"] / "draw/discovery.json"
            ).read_text(encoding="utf-8")
        )
        searches = discovery["searches"]
        assert [item["route"] for item in searches] == ["x", "x"]
        assert searches[0]["query"] != searches[1]["query"]
        assert searches[1]["change"] == "query"
        assert searches[1]["reason"] == "template_unusable_change_direction"
        reviews = json.loads(
            (plugin.store.runtime / record["task_id"] / "draw/reviews.json").read_text(
                encoding="utf-8"
            )
        )
        assert [item["outcome"] for item in reviews] == ["unusable", "usable"]
        assert sum(call.url.path == "/prompt" for call in comfy_transport) == 1
        await plugin.on_unload()

    asyncio.run(run())


def test_draw_second_search_switches_source_after_x_read_failure(
    plugin, command, draw_setup, comfy_transport, monkeypatch
):
    state, _, _ = draw_setup
    monkeypatch.setattr("moss.xsource.X_ENABLED", True)
    output = io.BytesIO()
    Image.new("RGB", (768, 512), "white").save(output, "PNG")
    image = output.getvalue()
    queries = []

    def http(url, **kwargs):
        if "payload" in kwargs:
            payload = kwargs["payload"]
            queries.append(payload)
            if payload["include_domains"] == ["x.com"]:
                return (
                    url,
                    "application/json",
                    json.dumps(
                        {"results": [{"url": "https://x.com/artist/status/123"}]}
                    ).encode(),
                )
            return (
                url,
                "application/json",
                json.dumps(
                    {"results": [{"url": "https://art.example.com/works/0"}]}
                ).encode(),
            )
        if url == "https://x.com/i/status/123":
            raise ReferenceError("http_status", stage="page", url=url, status=404)
        if url == "https://art.example.com/works/0":
            return (
                url,
                "text/html",
                b'<meta property="og:title" content="Art">'
                b'<meta property="og:image" content="https://art.example.com/image0.png">',
            )
        if url == "https://art.example.com/image0.png":
            return url, "image/png", image
        raise AssertionError(url)

    monkeypatch.setattr("moss.references.safe_http", http)

    async def run():
        await plugin.on_load()
        await plugin.handle_moss(**command)
        await asyncio.gather(*list(plugin.jobs.values()))
        record = json.loads(
            next(plugin.store.records.glob("*.json")).read_text(encoding="utf-8")
        )
        assert record["status"] == "sent", record
        discovery = json.loads(
            (
                plugin.store.runtime / record["task_id"] / "draw/discovery.json"
            ).read_text(encoding="utf-8")
        )
        searches = discovery["searches"]
        assert [item["route"] for item in searches] == ["x", "publisher"]
        assert searches[0]["query"] == searches[1]["query"]
        assert searches[1]["change"] == "source"
        assert searches[1]["reason"] == "source_read_failure"
        assert queries[0]["query"] == queries[1]["query"]
        assert "art.example.com" in queries[1]["include_domains"]
        await plugin.on_unload()

    asyncio.run(run())


def test_draw_second_search_changes_query_after_empty_x_search(
    plugin, command, draw_setup, comfy_transport, monkeypatch
):
    state, _, _ = draw_setup
    monkeypatch.setattr("moss.xsource.X_ENABLED", True)
    output = io.BytesIO()
    Image.new("RGB", (768, 512), "white").save(output, "PNG")
    image = output.getvalue()
    search_calls = {"count": 0}

    def http(url, **kwargs):
        if "payload" in kwargs:
            assert kwargs["payload"]["include_domains"] == ["x.com"]
            search_calls["count"] += 1
            results = (
                []
                if search_calls["count"] == 1
                else [{"url": "https://x.com/artist/status/456"}]
            )
            return url, "application/json", json.dumps({"results": results}).encode()
        if url == "https://x.com/i/status/456":
            return url, "text/html", x_page_html("BBB")
        if url.startswith("https://cdn.syndication.twimg.com/tweet-result"):
            return url, "application/json", x_syndication("456", "BBB")
        if "pbs.twimg.com/media/" in url:
            return url, "image/png", image
        raise AssertionError(url)

    monkeypatch.setattr("moss.references.safe_http", http)

    async def run():
        await plugin.on_load()
        await plugin.handle_moss(**command)
        await asyncio.gather(*list(plugin.jobs.values()))
        record = json.loads(
            next(plugin.store.records.glob("*.json")).read_text(encoding="utf-8")
        )
        assert record["status"] == "sent", record
        discovery = json.loads(
            (
                plugin.store.runtime / record["task_id"] / "draw/discovery.json"
            ).read_text(encoding="utf-8")
        )
        searches = discovery["searches"]
        assert [item["route"] for item in searches] == ["x", "x"]
        assert searches[0]["query"] != searches[1]["query"]
        assert searches[1]["change"] == "query"
        assert searches[1]["reason"] == "empty_results_change_query"
        assert searches[0]["accepted"] == 0
        await plugin.on_unload()

    asyncio.run(run())


def test_draw_first_eligible_submits_exactly_once_and_redacts_config(
    plugin, command, draw_setup, comfy_transport
):
    state, _, _ = draw_setup

    async def run():
        await plugin.on_load()
        await plugin.handle_moss(**command)
        await asyncio.gather(*list(plugin.jobs.values()))
        await plugin.handle_moss(**command)
        record = json.loads(
            next(plugin.store.records.glob("*.json")).read_text(encoding="utf-8")
        )
        assert record["status"] == "sent", record
        assert record["width"] > record["height"]
        assert (
            state["searches"] == 1
            and len(state["downloads"]) == 1
            and state["reviews"] == 1
        )
        assert plugin.ctx.llm.generate.await_count == 3
        assert sum(call.url.path == "/prompt" for call in comfy_transport) == 1
        plugin.ctx.send.image.assert_awaited_once()
        plugin.ctx.send.text.assert_not_awaited()
        directory = plugin.store.runtime / record["task_id"]
        prompt = (directory / "prompt.txt").read_text(encoding="utf-8")
        assert plugin.config.styles.presets[0].split("=", 1)[1] not in prompt
        assert all(
            "@yuasa akira" not in json.dumps(messages, ensure_ascii=False)
            for messages in state["requests"]
        )
        prefixes = json.loads((directory / "prefixes.json").read_text(encoding="utf-8"))
        assert prefixes["style_name"] == prefixes["style_prompt"] == ""
        assert "best quality" not in prompt
        snapshot = json.loads((directory / "config.json").read_text(encoding="utf-8"))
        assert "tavily_api_key" not in snapshot["draw"]
        assert all(
            "private-test-search-key" not in path.read_text(encoding="utf-8")
            for path in directory.rglob("*.json")
        )
        await plugin.on_unload()

    asyncio.run(run())


def test_draw_uses_x_first_and_submits_one_association(
    plugin, command, draw_setup, comfy_transport, monkeypatch
):
    state, _, _ = draw_setup
    monkeypatch.setattr("moss.xsource.X_ENABLED", True)
    output = io.BytesIO()
    Image.new("RGB", (768, 512), "white").save(output, "PNG")
    image = output.getvalue()

    def http(url, **kwargs):
        if "payload" in kwargs:
            assert kwargs["payload"]["include_domains"] == ["x.com"]
            return (
                url,
                "application/json",
                json.dumps(
                    {"results": [{"url": "https://x.com/artist/status/123"}]}
                ).encode(),
            )
        if url == "https://x.com/i/status/123":
            return (
                url,
                "text/html",
                b'<meta property="og:image" content="https://pbs.twimg.com/media/AAA?format=jpg&amp;name=large">',
            )
        if url.startswith("https://cdn.syndication.twimg.com/tweet-result"):
            return (
                url,
                "application/json",
                json.dumps(
                    {
                        "id_str": "123",
                        "text": "Prompt: a complete character poster",
                        "user": {"screen_name": "artist"},
                        "mediaDetails": [
                            {
                                "type": "photo",
                                "media_url_https": "https://pbs.twimg.com/media/AAA.jpg",
                                "sizes": {"large": {"w": 768, "h": 512}},
                            }
                        ],
                    }
                ).encode(),
            )
        if url.startswith("https://pbs.twimg.com/media/AAA.jpg"):
            return url, "image/png", image
        raise AssertionError(f"Unexpected URL: {url}")

    monkeypatch.setattr("moss.references.safe_http", http)

    async def run():
        await plugin.on_load()
        await plugin.handle_moss(**command)
        await asyncio.gather(*list(plugin.jobs.values()))
        record = json.loads(
            next(plugin.store.records.glob("*.json")).read_text(encoding="utf-8")
        )
        assert record["status"] == "sent", record
        directory = plugin.store.runtime / record["task_id"] / "draw"
        discovery = json.loads(
            (directory / "discovery.json").read_text(encoding="utf-8")
        )
        assert discovery["searches"][0]["route"] == "x"
        references = json.loads(
            (directory / "references.json").read_text(encoding="utf-8")
        )
        assert references[0]["source_route"] == "x"
        assert references[0]["content_flags"] == ["tutorial_or_template"]
        assert references[0]["image_decoded"] is True
        reviews = json.loads((directory / "reviews.json").read_text(encoding="utf-8"))
        assert [item["outcome"] for item in reviews] == ["usable"]
        assert sum(call.url.path == "/prompt" for call in comfy_transport) == 1
        assert state["searches"] == 0
        await plugin.on_unload()

    asyncio.run(run())


def test_draw_rejects_then_stops_at_second_and_preserves_explicit_canvas(
    plugin, command, draw_setup, comfy_transport
):
    state, _, _ = draw_setup
    state["reject"] = 1
    command["text"] += "，比例3：4"

    async def run():
        await plugin.on_load()
        await plugin.handle_moss(**command)
        await asyncio.gather(*list(plugin.jobs.values()))
        record = json.loads(
            next(plugin.store.records.glob("*.json")).read_text(encoding="utf-8")
        )
        assert record["status"] == "sent", record
        assert record["width"] < record["height"]
        assert len(state["downloads"]) == 2 and state["reviews"] == 2
        assert plugin.ctx.llm.generate.await_count == 4
        assert len(comfy_transport) == 3
        await plugin.on_unload()

    asyncio.run(run())


@pytest.mark.parametrize("first_output", ["fenced_rejection", "malformed"])
def test_draw_review_format_failure_recovers_pending_candidate(
    plugin, command, draw_setup, comfy_transport, monkeypatch, first_output
):
    state, _, _ = draw_setup
    state.update(
        reject=1,
        result_sets=[
            [{"url": f"https://art.example.com/works/{i}"} for i in range(2)],
            [],
        ],
    )
    monkeypatch.setattr("moss.draw.random.Random.shuffle", lambda self, items: None)
    generate = plugin.ctx.llm.generate.side_effect

    async def wrapped(messages, **kwargs):
        result = await generate(messages, **kwargs)
        if (
            messages[0]["content"].startswith("You are a visual design editor")
            and state["reviews"] == 1
        ):
            result["response"] = (
                "```json\n" + result["response"] + "\n```"
                if first_output == "fenced_rejection"
                else "{invalid JSON"
            )
        return result

    plugin.ctx.llm.generate.side_effect = wrapped

    async def run():
        await plugin.on_load()
        await plugin.handle_moss(**command)
        await asyncio.gather(*list(plugin.jobs.values()))
        record = json.loads(
            next(plugin.store.records.glob("*.json")).read_text(encoding="utf-8")
        )
        assert record["status"] == "sent", record
        directory = plugin.store.runtime / record["task_id"] / "draw"
        reviews = json.loads((directory / "reviews.json").read_text(encoding="utf-8"))
        assert [item["candidate_id"] for item in reviews] == [
            "candidate-1",
            "candidate-2",
        ]
        assert reviews[0]["outcome"] == (
            "unusable" if first_output == "fenced_rejection" else "invalid_review"
        )
        assert (
            json.loads((directory / "validation.json").read_text(encoding="utf-8"))[
                "review_calls"
            ]
            == 2
        )
        assert state["review_briefs"][0] == state["review_briefs"][1]
        assert (
            state["reviews"] == 2
            and sum(call.url.path == "/prompt" for call in comfy_transport) == 1
        )
        await plugin.on_unload()

    asyncio.run(run())


@pytest.mark.parametrize(
    "failure",
    ["invalid_review", "mixed_review_failure", "vision_unavailable", "transport_error"],
)
def test_draw_counts_failed_reviews_and_reports_actual_failure(
    plugin, command, draw_setup, comfy_transport, failure
):
    state, _, _ = draw_setup
    state["reject"] = 1 if failure == "mixed_review_failure" else 0
    generate = plugin.ctx.llm.generate.side_effect

    async def wrapped(messages, **kwargs):
        result = await generate(messages, **kwargs)
        if messages[0]["content"].startswith("You are a visual design editor"):
            if failure == "transport_error":
                raise OSError("Private provider transport error")
            if failure == "vision_unavailable":
                return {"success": False, "response": ""}
            if failure != "mixed_review_failure" or state["reviews"] > 1:
                result["response"] = '{"candidate_id":"candidate-999"}'
        return result

    plugin.ctx.llm.generate.side_effect = wrapped

    async def run():
        await plugin.on_load()
        await plugin.handle_moss(**command)
        await asyncio.gather(*list(plugin.jobs.values()))
        record = json.loads(
            next(plugin.store.records.glob("*.json")).read_text(encoding="utf-8")
        )
        assert record["error_kind"] == (
            "vision_unavailable" if failure == "transport_error" else failure
        ), record
        directory = plugin.store.runtime / record["task_id"] / "draw"
        validation = json.loads(
            (directory / "validation.json").read_text(encoding="utf-8")
        )
        assert (
            validation["review_calls"]
            == state["reviews"]
            == (1 if failure in {"vision_unavailable", "transport_error"} else 3)
        )
        assert validation["brief_repair_used"] is False
        assert validation["export_repair_used"] is False
        assert not comfy_transport
        if failure == "mixed_review_failure":
            assert "部分候选" in plugin.ctx.send.text.call_args.args[0]
        await plugin.on_unload()

    asyncio.run(run())


@pytest.mark.parametrize("failure", ["reject", "broken", "blocked"])
def test_draw_never_lowers_quality_or_resubmits_after_failure(
    plugin, command, draw_setup, comfy_transport, failure
):
    state, _, _ = draw_setup
    state[failure] = 3 if failure == "reject" else True

    async def run():
        await plugin.on_load()
        await plugin.handle_moss(**command)
        await asyncio.gather(*list(plugin.jobs.values()))
        assert not comfy_transport
        record = json.loads(
            next(plugin.store.records.glob("*.json")).read_text(encoding="utf-8")
        )
        assert (
            record["error_kind"]
            == {
                "reject": "no_usable_template",
                "broken": "reference_unreadable",
                "blocked": "vision_blocked",
            }[failure]
        )
        if failure == "broken":
            records = json.loads(
                (
                    plugin.store.runtime / record["task_id"] / "draw/references.json"
                ).read_text(encoding="utf-8")
            )
            assert all(
                item["failure"]["http_status"] == 403
                and item["failure"]["stage"] == "image"
                for item in records
            )
            assert "private-signed-token" not in json.dumps(records)
        plugin.ctx.send.image.assert_not_awaited()
        plugin.ctx.send.text.assert_awaited_once()
        assert len(state["downloads"]) == (1 if failure == "blocked" else 3)
        if failure == "blocked":
            assert (
                "Private provider refusal" not in plugin.ctx.send.text.call_args.args[0]
            )
        await plugin.on_unload()

    asyncio.run(run())


def test_draw_verified_identity_is_in_final_prompt_without_expansion(
    plugin, command, draw_setup, comfy_transport
):
    state, _, _ = draw_setup
    state["identity_locked"] = True
    plugin.config.planning.danbooru_enabled = True
    command["text"] = command["text"].replace("少女", "卡缇希娅")

    async def run():
        await plugin.on_load()
        plugin.runner.planner.resolver.resolve = AsyncMock(
            return_value=[
                {
                    "source_name": "卡缇希娅",
                    "status": "verified",
                    "canonical_tag": "cartethyia_(wuthering_waves)",
                }
            ]
        )
        await plugin.handle_moss(**command)
        await asyncio.gather(*list(plugin.jobs.values()))
        record = json.loads(
            next(plugin.store.records.glob("*.json")).read_text(encoding="utf-8")
        )
        assert record["status"] == "sent", record
        submitted = json.loads(
            next(call for call in comfy_transport if call.url.path == "/prompt").content
        )
        prompt = submitted["prompt"]["4"]["inputs"]["text"]
        assert "卡缇希娅 = cartethyia_(wuthering_waves)" in prompt
        assert prompt.count("cartethyia_(wuthering_waves)") == 1
        assert plugin.ctx.llm.generate.await_count == 5 and state["brief_calls"] == 2
        discovery = json.loads(
            (
                plugin.store.runtime / record["task_id"] / "draw/discovery.json"
            ).read_text(encoding="utf-8")
        )
        assert all(
            "cartethyia" not in search["query"].casefold()
            and "wuthering" not in search["query"].casefold()
            for search in discovery["searches"]
        )
        await plugin.on_unload()

    asyncio.run(run())


def test_removed_profile_settings_are_ignored_and_absent_from_schema():
    config = MossConfig.model_validate(
        {"draw": {"use_profile": True, "profile": "old"}}
    )
    assert config.draw.model_dump() == MossConfig().draw.model_dump()
    assert "use_profile" not in config.draw.model_json_schema()["properties"]
    assert Aesthetics().version == "template-v1"


def test_draw_disabled_attachment_and_style_scope_boundaries(plugin, command):
    async def run():
        await plugin.on_load()
        command["text"] = "/moss 抽卡 白猫"
        await plugin.handle_moss(**command)
        assert not plugin.jobs
        plugin.config.draw.enabled = True
        command["text"] = "[image] /moss 抽卡 白猫"
        await plugin.handle_moss(**command)
        assert not plugin.jobs
        plugin.ctx.llm.generate.assert_not_awaited()
        plugin.config.styles.default_application = "generate"
        assert await plugin.styles.snapshot("a" * 64, plugin.config.styles, "draw") == (
            "",
            "",
        )
        plugin.config.styles.default_application = "all"
        assert await plugin.styles.snapshot("a" * 64, plugin.config.styles, "draw") == (
            "",
            "",
        )
        await plugin.on_unload()

    asyncio.run(run())
    action, request = parse_command("/moss 抽卡 白猫，比例4：3", MossConfig().rendering)
    assert (
        action == "draw" and request.canvas_explicit and request.width > request.height
    )
    _, request = parse_command("/moss 抽卡 白猫", MossConfig().rendering)
    assert not request.canvas_explicit


def test_public_http_rejects_private_dns_and_credential_redirects(monkeypatch):
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *args, **kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("100.103.203.109", 443))
        ],
    )
    with pytest.raises(DrawError):
        safe_http("https://public.example.com/image.jpg")
    with pytest.raises(DrawError):
        safe_http("https://public.example.com/upload", payload={}, key="secret")
    with pytest.raises(DrawError):
        safe_http("https://user:password@public.example.com/image.jpg")


def test_reference_normalization_and_cache_never_follow_links(tmp_path):
    output = io.BytesIO()
    Image.new("RGB", (4000, 4000)).save(output, "PNG")
    with pytest.raises(DrawError):
        normalize_image(output.getvalue())
    good = io.BytesIO()
    Image.new("RGB", (512, 768), "white").save(good, "PNG")
    content = normalize_image(good.getvalue())[0]
    root = tmp_path / "cache"
    digest = cache_reference(root, content, 1024 * 1024)
    assert (root / (digest + ".jpg")).is_file()
    unknown = root / "keep.txt"
    unknown.write_text("untouched")
    with pytest.raises(DrawError):
        cache_reference(root, content, 1024 * 1024)
    assert unknown.read_text() == "untouched"


def test_draw_poster_compiles_real_layout_and_keeps_exact_copy(
    plugin, command, draw_setup, comfy_transport
):
    state, _, _ = draw_setup
    state["poster"] = True
    command["text"] = "/moss 抽卡 少女，单人，海报标题“风起！”"

    async def run():
        await plugin.on_load()
        await plugin.handle_moss(**command)
        await asyncio.gather(*list(plugin.jobs.values()))
        record = json.loads(
            next(plugin.store.records.glob("*.json")).read_text(encoding="utf-8")
        )
        assert record["status"] == "sent", record
        directory = plugin.store.runtime / record["task_id"]
        compiled = json.loads((directory / "prompt.txt").read_text(encoding="utf-8"))
        assert compiled["bbox_format"] == "yxyx"
        assert compiled["bbox_coord_space"] == "abs_centralized"
        assert [
            item["text"] for item in compiled["items"] if item["label"] == "text"
        ] == ["风起！"]
        assert "constraint_sources" not in compiled and "width" not in compiled
        assert (
            plugin.config.styles.presets[0].split("=", 1)[1]
            not in compiled["summary"]["caption"]
        )
        assert plugin.ctx.llm.generate.await_count == 3
        await plugin.on_unload()

    asyncio.run(run())


def test_draw_repairs_contaminated_brief_once_and_keeps_explicit_user_style(
    plugin, command, draw_setup, comfy_transport
):
    state, _, _ = draw_setup
    state["brief_bad"] = 1
    command["text"] += "，水彩画"

    async def run():
        await plugin.on_load()
        await plugin.handle_moss(**command)
        await asyncio.gather(*list(plugin.jobs.values()))
        record = json.loads(
            next(plugin.store.records.glob("*.json")).read_text(encoding="utf-8")
        )
        assert record["status"] == "sent", record
        directory = plugin.store.runtime / record["task_id"]
        brief = json.loads((directory / "draw/brief.json").read_text(encoding="utf-8"))
        assert "水彩画" in {item["source"] for item in brief["constraints"]}
        assert all(
            item["source"] in "少女，单人，不要文字，水彩画"
            for item in brief["constraints"]
        )
        assert "style_compatible" not in brief
        prompt = (directory / "prompt.txt").read_text(encoding="utf-8")
        assert "Watercolor illustration" in prompt and "@yuasa akira" not in prompt
        assert state["brief_calls"] == 2 and plugin.ctx.llm.generate.await_count == 4
        assert sum(call.url.path == "/prompt" for call in comfy_transport) == 1
        await plugin.on_unload()

    asyncio.run(run())


def test_draw_invalid_brief_stops_after_one_correction_before_search(
    plugin, command, draw_setup, comfy_transport
):
    state, _, _ = draw_setup
    state["brief_bad"] = 2

    async def run():
        await plugin.on_load()
        await plugin.handle_moss(**command)
        await asyncio.gather(*list(plugin.jobs.values()))
        record = json.loads(
            next(plugin.store.records.glob("*.json")).read_text(encoding="utf-8")
        )
        assert record["error_kind"] == "invalid_brief"
        assert (
            state["brief_calls"] == 2 and state["searches"] == 0 and not comfy_transport
        )
        assert "简报" in plugin.ctx.send.text.call_args.args[0]
        plugin.ctx.send.image.assert_not_awaited()
        await plugin.on_unload()

    asyncio.run(run())


def test_draw_export_failure_records_category_and_repair_attempt(
    plugin, command, draw_setup, comfy_transport
):
    state, _, _ = draw_setup
    state["export_bad"] = True

    async def run():
        await plugin.on_load()
        await plugin.handle_moss(**command)
        await asyncio.gather(*list(plugin.jobs.values()))
        record = json.loads(
            next(plugin.store.records.glob("*.json")).read_text(encoding="utf-8")
        )
        assert record["error_kind"] == "invalid_export"
        failure = record["export_failure"]
        assert failure["category"] == "explicit_text_mismatch"
        assert failure["repair_attempted"] is True
        assert failure["repair_skipped"] == ""
        validation = json.loads(
            (
                plugin.store.runtime / record["task_id"] / "draw/validation.json"
            ).read_text(encoding="utf-8")
        )
        assert validation["export_repair_used"] is True
        assert validation["export_repair_skipped"] == ""
        assert validation["export_failure"]["category"] == "explicit_text_mismatch"
        assert not comfy_transport
        await plugin.on_unload()

    asyncio.run(run())


def test_draw_brief_and_export_repairs_are_separate(
    plugin, command, draw_setup, comfy_transport
):
    state, _, _ = draw_setup
    state.update(brief_bad=1, repair=True)

    async def run():
        await plugin.on_load()
        await plugin.handle_moss(**command)
        await asyncio.gather(*list(plugin.jobs.values()))
        record = json.loads(
            next(plugin.store.records.glob("*.json")).read_text(encoding="utf-8")
        )
        assert record["status"] == "sent", record
        validation = json.loads(
            (
                plugin.store.runtime / record["task_id"] / "draw/validation.json"
            ).read_text(encoding="utf-8")
        )
        assert validation["brief_repair_used"] is True
        assert validation["export_repair_used"] is True
        assert validation["export_repair_skipped"] == ""
        assert validation["model_calls"] <= 8
        diagnostic = json.loads(
            (plugin.store.data / "last_llm_response.json").read_text(encoding="utf-8")
        )
        stages = [call["stage"] for call in diagnostic["calls"]]
        assert {
            "draw_brief_repair",
            "draw_review",
            "draw_adapt",
            "draw_repair",
        }.issubset(stages)
        assert sum(call.url.path == "/prompt" for call in comfy_transport) == 1
        await plugin.on_unload()

    asyncio.run(run())


def test_draw_preparation_deadline_stops_before_gpu(
    plugin, command, draw_setup, comfy_transport, monkeypatch
):
    native_timeout = asyncio.timeout
    monkeypatch.setattr(
        "moss.draw.asyncio.timeout",
        lambda delay: native_timeout(0.02 if delay == 180 else delay),
    )

    async def unavailable(*args, **kwargs):
        await asyncio.sleep(10)

    plugin.ctx.llm.generate.side_effect = unavailable

    async def run():
        await plugin.on_load()
        await plugin.handle_moss(**command)
        await asyncio.wait_for(asyncio.gather(*list(plugin.jobs.values())), timeout=2)
        record = json.loads(
            next(plugin.store.records.glob("*.json")).read_text(encoding="utf-8")
        )
        assert record["error_kind"] == "budget_exhausted"
        assert not comfy_transport and not record.get("submission_started")
        await plugin.on_unload()

    asyncio.run(run())


def test_open_draw_randomizes_design_direction_before_search(
    plugin, command, draw_setup, comfy_transport, monkeypatch
):
    state, _, _ = draw_setup
    seeds = iter([1, 4])
    monkeypatch.setattr("moss.draw.secrets.randbits", lambda _: next(seeds))
    command["text"] = "/moss 抽卡 卡缇希娅"

    async def run():
        await plugin.on_load()
        for index in range(2):
            command["message"]["message_id"] = f"draw-direction-{index}"
            await plugin.handle_moss(**command)
            await asyncio.gather(*list(plugin.jobs.values()))
        briefs = []
        for path in plugin.store.records.glob("*.json"):
            record = json.loads(path.read_text(encoding="utf-8"))
            assert record["status"] == "sent", record
            directory = plugin.store.runtime / record["task_id"] / "draw"
            briefs.append(
                json.loads((directory / "brief.json").read_text(encoding="utf-8"))
            )
        assert all(
            brief["reference_requirements"] == [] and "卡缇希娅" not in brief["query"]
            for brief in briefs
        )
        assert len({brief["query"] for brief in briefs}) >= 1
        assert state["searches"] == 2 and len(state["downloads"]) == 2
        assert sum(call.url.path == "/prompt" for call in comfy_transport) == 2
        await plugin.on_unload()

    asyncio.run(run())


def test_draw_empty_search_is_not_reported_as_aesthetic_failure(
    plugin, command, draw_setup, comfy_transport
):
    state, _, _ = draw_setup
    state["empty_results"] = True

    async def run():
        await plugin.on_load()
        await plugin.handle_moss(**command)
        await asyncio.gather(*list(plugin.jobs.values()))
        record = json.loads(
            next(plugin.store.records.glob("*.json")).read_text(encoding="utf-8")
        )
        assert record["error_kind"] == "no_reference_results"
        assert state["searches"] == 2 and state["reviews"] == 0 and not comfy_transport
        discovery = json.loads(
            (
                plugin.store.runtime / record["task_id"] / "draw/discovery.json"
            ).read_text(encoding="utf-8")
        )
        assert all(
            search["returned"] == search["accepted"] == 0
            for search in discovery["searches"]
        )
        await plugin.on_unload()

    asyncio.run(run())


def test_draw_uses_pending_page_before_supplement_search(
    plugin, command, draw_setup, comfy_transport, monkeypatch
):
    state, _, _ = draw_setup
    monkeypatch.setattr("moss.draw.random.Random.shuffle", lambda self, items: None)
    state["result_sets"] = [
        [{"url": f"https://art.example.com/works/{i}"} for i in range(2)]
    ]
    state["page_failures"] = ["https://art.example.com/works/0"]

    async def run():
        await plugin.on_load()
        await plugin.handle_moss(**command)
        await asyncio.gather(*list(plugin.jobs.values()))
        record = json.loads(
            next(plugin.store.records.glob("*.json")).read_text(encoding="utf-8")
        )
        assert record["status"] == "sent", record
        assert state["page_reads"] == [
            f"https://art.example.com/works/{i}" for i in range(2)
        ]
        assert state["searches"] == 1 and state["reviews"] == 1
        assert sum(call.url.path == "/prompt" for call in comfy_transport) == 1
        await plugin.on_unload()

    asyncio.run(run())


def test_draw_keeps_pending_direction_after_template_rejection(
    plugin, command, draw_setup, comfy_transport, monkeypatch
):
    state, _, _ = draw_setup
    monkeypatch.setattr("moss.draw.random.Random.shuffle", lambda self, items: None)
    state["result_sets"] = [
        [{"url": f"https://art.example.com/works/{i}"} for i in range(2)]
    ]
    state["reject"] = 1

    async def run():
        await plugin.on_load()
        await plugin.handle_moss(**command)
        await asyncio.gather(*list(plugin.jobs.values()))
        record = json.loads(
            next(plugin.store.records.glob("*.json")).read_text(encoding="utf-8")
        )
        assert record["status"] == "sent", record
        assert state["searches"] == 1 and state["reviews"] == 2
        assert state["review_briefs"][0] == state["review_briefs"][1]
        assert sum(call.url.path == "/prompt" for call in comfy_transport) == 1
        await plugin.on_unload()

    asyncio.run(run())


def test_draw_search_outage_after_template_rejection_keeps_evidence(
    plugin, command, draw_setup, comfy_transport, monkeypatch
):
    state, _, _ = draw_setup
    monkeypatch.setattr("moss.draw.random.Random.shuffle", lambda self, items: None)
    state["result_sets"] = [[{"url": "https://art.example.com/works/0"}]]
    state["reject"] = 1
    state["search_error"] = 2

    async def run():
        await plugin.on_load()
        await plugin.handle_moss(**command)
        await asyncio.gather(*list(plugin.jobs.values()))
        record = json.loads(
            next(plugin.store.records.glob("*.json")).read_text(encoding="utf-8")
        )
        assert record["error_kind"] == "no_usable_template"
        assert state["searches"] == 2 and state["reviews"] == 1
        assert not comfy_transport
        reviews = json.loads(
            (plugin.store.runtime / record["task_id"] / "draw/reviews.json").read_text(
                encoding="utf-8"
            )
        )
        assert [item["outcome"] for item in reviews] == ["unusable"]
        await plugin.on_unload()

    asyncio.run(run())


@pytest.mark.parametrize("all_fail", [False, True])
def test_draw_page_budget_is_independent_of_visual_review_budget(
    plugin, command, draw_setup, comfy_transport, monkeypatch, all_fail
):
    state, _, _ = draw_setup
    monkeypatch.setattr("moss.draw.random.Random.shuffle", lambda self, items: None)
    urls = [
        f"https://{host}.example.com/works/{i}"
        for i, host in enumerate(["art"] * 3 + ["design"] * 3)
    ]
    state["result_sets"] = [
        [{"url": url} for url in urls[:3]],
        [{"url": url} for url in urls[3:]],
    ]
    state["page_failures"] = urls if all_fail else urls[:4]

    async def run():
        await plugin.on_load()
        await plugin.handle_moss(**command)
        await asyncio.gather(*list(plugin.jobs.values()))
        record = json.loads(
            next(plugin.store.records.glob("*.json")).read_text(encoding="utf-8")
        )
        assert len(state["page_reads"]) <= 6 and state["searches"] == 2
        if all_fail:
            assert len(state["page_reads"]) == 6 and state["reviews"] == 0
            assert (
                record["error_kind"] == "reference_unreadable" and not comfy_transport
            )
        else:
            assert record["status"] == "sent", record
            assert state["reviews"] == 1
            assert sum(call.url.path == "/prompt" for call in comfy_transport) == 1
        await plugin.on_unload()

    asyncio.run(run())


def test_reference_filters_report_reasons_and_retry_page_associated_images(monkeypatch):
    from urllib.parse import urlsplit

    from moss.aesthetics import BUILTIN_SOURCES
    from moss.references import ReferenceClient

    assert any(
        source.matches(urlsplit("https://itsnicethat.com/features/a-real-work"))
        for source in BUILTIN_SOURCES
    )
    assert not any(
        source.matches(urlsplit("https://www.itsnicethat.com/features/"))
        for source in BUILTIN_SOURCES
    )
    assert not any(
        source.matches(
            urlsplit("https://www.itsnicethat.com.evil.example/features/art")
        )
        for source in BUILTIN_SOURCES
    )
    image = io.BytesIO()
    Image.new("RGB", (512, 768)).save(image, "PNG")
    calls = []

    def http(url, **kwargs):
        calls.append(url)
        if kwargs.get("payload") is not None:
            return (
                url,
                "application/json",
                json.dumps(
                    {
                        "results": [
                            {"url": "https://www.itsnicethat.com"},
                            {"url": "https://www.itsnicethat.com/features/a-real-work"},
                            {"url": "http://private.example/a"},
                        ]
                    }
                ).encode(),
            )
        if "/features/" in url:
            return (
                url,
                "text/html",
                b'<meta property="og:title" content="Art"><meta property="og:image" content="/broken.png"><meta name="twitter:image" content="/art.png">',
            )
        if "broken" in url:
            raise ReferenceError(
                "http_status", stage="image", url=url + "?token=secret", status=404
            )
        return url, "image/png", image.getvalue()

    monkeypatch.setattr("moss.references.safe_http", http)

    async def run():
        client = ReferenceClient(MossConfig().draw, BUILTIN_SOURCES)
        pages = await client.search("graphic design")
        assert len(pages) == 1
        assert {item["reason"] for item in client.searches[0]["filtered"]} == {
            "source_or_path_not_allowed",
            "unsafe_url",
        }
        record, content = await client.candidate(pages[0], 1)
        assert record["width"] == 512 and content
        assert len(record["image_failures"]) == 1 and "secret" not in json.dumps(record)
        assert len(calls) == 4

    asyncio.run(run())


@pytest.mark.parametrize("publisher", ["pentagram", "itsnicethat"])
@pytest.mark.parametrize("broken_body", [False, True])
def test_reference_prefers_scoped_body_art_and_retains_metadata_fallback(
    monkeypatch, publisher, broken_body
):
    from moss.aesthetics import BUILTIN_SOURCES
    from moss.references import ReferenceClient

    if publisher == "pentagram":
        page_url = "https://www.pentagram.com/work/40-years-of-storefront-for-art-and-architecture/story"
        artwork = "https://pentagram-production.imgix.net/art/5A.png"
        element = f'<figure class="workMedia"><picture><img class="workMedia__img" data-src="{artwork}?w=640"></picture></figure>'
    else:
        page_url = "https://www.itsnicethat.com/articles/a-work"
        artwork = "https://m.itsnicethat.com/original_images/art.jpg"
        element = f'<div><img src="{artwork}?class=w828"><img src="{artwork}?class=w1080"></div>'
    metadata = "https://images.example.com/social.jpg"
    html = (
        f'<meta property="og:title" content="Art"><meta property="og:image" content="{metadata}">'
        f'<header>{element}</header><article><aside>{element}</aside><img src="https://unrelated.example.com/not-art.png">{element}</article><footer>{element}</footer>'
    )
    image = io.BytesIO()
    Image.new("RGB", (512, 768)).save(image, "PNG")
    calls = []

    def http(url, **kwargs):
        calls.append(url)
        if url == page_url:
            return url, "text/html", html.encode()
        if broken_body and url.startswith(artwork):
            raise ReferenceError("http_status", stage="image", url=url, status=404)
        return url, "image/png", image.getvalue()

    monkeypatch.setattr("moss.references.safe_http", http)

    async def run():
        client = ReferenceClient(MossConfig().draw, BUILTIN_SOURCES)
        record, content = await client.candidate(page_url, 1)
        assert content and calls[1].startswith(artwork)
        assert record["image_origin"] == (
            "social_metadata" if broken_body else "article_artwork"
        )
        assert record["image"] == (metadata if broken_body else artwork)
        assert len(calls) == (3 if broken_body else 2)
        assert len(record["image_failures"]) == int(broken_body)

    asyncio.run(run())


def test_draw_prioritizes_single_work_before_trend_collection(
    plugin, command, draw_setup, comfy_transport, monkeypatch
):
    state, _, _ = draw_setup
    monkeypatch.setattr("moss.draw.random.Random.shuffle", lambda self, items: None)
    state["result_sets"] = [
        [
            {
                "url": "https://art.example.com/works/0",
                "title": "Graphic design trends 2026",
            },
            {
                "url": "https://art.example.com/works/1",
                "title": "A new poster by a design studio",
            },
        ]
    ]

    async def run():
        await plugin.on_load()
        await plugin.handle_moss(**command)
        await asyncio.gather(*list(plugin.jobs.values()))
        record = json.loads(
            next(plugin.store.records.glob("*.json")).read_text(encoding="utf-8")
        )
        assert record["status"] == "sent", record
        assert state["page_reads"] == ["https://art.example.com/works/1"]
        assert sum(call.url.path == "/prompt" for call in comfy_transport) == 1
        await plugin.on_unload()

    asyncio.run(run())


def test_http_pins_peer_checks_redirect_and_never_forwards_search_key(monkeypatch):
    from moss import references

    calls, connects = [], []
    raw = SimpleNamespace(
        getpeername=lambda: ("93.184.216.34", 443),
        close=lambda: None,
        settimeout=lambda value: None,
    )
    responses = []

    class Connection:
        def __init__(self, host, **kwargs):
            self.host, self.sock = host, None

        def request(self, method, target, **kwargs):
            calls.append((self.host, method, kwargs["headers"]))

        def getresponse(self):
            self.sock = None  # Exercise Connection: close response handling.
            return responses.pop(0)

        def close(self):
            pass

    def response(status=200, location=""):
        chunks = [b"bytes", b""]
        return SimpleNamespace(
            status=status,
            getheader=lambda name, default=None: {
                "Content-Type": "image/jpeg",
                "Location": location,
            }.get(name, default),
            read1=lambda size: chunks.pop(0),
        )

    def resolve(host, *args, **kwargs):
        address = "127.0.0.1" if host == "private.example.com" else "93.184.216.34"
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 443))]

    def connect(target, **kwargs):
        connects.append(target)
        return raw

    monkeypatch.setattr(socket, "getaddrinfo", resolve)
    monkeypatch.setattr(socket, "create_connection", connect)
    monkeypatch.setattr(references.http.client, "HTTPSConnection", Connection)
    monkeypatch.setattr(
        references.ssl,
        "create_default_context",
        lambda: SimpleNamespace(wrap_socket=lambda raw, server_hostname: raw),
    )
    responses.append(response())
    assert safe_http("https://public.example.com/image.jpg")[2] == b"bytes"
    assert connects == [("93.184.216.34", 443)]
    responses.append(response(302, "https://private.example.com/image.jpg"))
    with pytest.raises(DrawError):
        safe_http("https://public.example.com/image.jpg")
    assert len(connects) == 2
    responses.append(response(302, "https://public.example.com/steal"))
    with pytest.raises(DrawError):
        safe_http(
            "https://api.tavily.com/search", payload={"query": "art"}, key="private-key"
        )
    assert len(calls) == 3
    assert [host for host, _, headers in calls if headers.get("Authorization")] == [
        "api.tavily.com"
    ]
    responses.append(response(403))
    with pytest.raises(ReferenceError) as failure:
        safe_http(
            "https://public.example.com/image.jpg?token=private-signed-token",
            stage="image",
        )
    assert (
        failure.value.details["http_status"] == 403
        and failure.value.details["stage"] == "image"
    )
    assert failure.value.details["url"] == "https://public.example.com/image.jpg"
