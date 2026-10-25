"""Curation boundaries against real orchestration and completely offline services."""

import asyncio
import hashlib
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
from moss.draw_models import DrawError
from moss.references import cache_reference, normalize_image, safe_http


@pytest.fixture
def draw_setup(plugin, command, monkeypatch):
    """One calibrated profile, three distinct work pages, deterministic fake models."""
    plugin.config.draw.enabled = True
    plugin.config.draw.use_profile = True
    plugin.config.draw.tavily_api_key = "private-test-search-key"
    root = plugin.ctx.paths.data_dir / "draw_profiles/default"
    root.mkdir(parents=True)
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
    anchors = []
    for index in range(4):
        content = artworks[index]
        name = f"anchor{index}.png"
        (root / name).write_bytes(content)
        anchors.append(
            {
                "file": name,
                "sha256": hashlib.sha256(content).hexdigest(),
                "reason": "Coherent hierarchy" if index < 2 else "Confused hierarchy",
            }
        )
    profile = {
        "version": "offline-fixture",
        "rules_version": "draw-v1",
        "vision_model_task": plugin.config.vision.model_task,
        "vision_model_name": plugin.config.vision.model_name,
        "planning_model_task": plugin.config.planning.model_task,
        "planning_model_name": plugin.config.planning.model_name,
        "multimodal_verified": True,
        "sources_verified": True,
        "sources": [
            {
                "domain": name,
                "path_prefix": "/works/",
                "kind": "creator_verified",
                "evidence": "Offline original publisher fixture",
            }
            for name in ["art.example.com", "design.example.com"]
        ],
        "categories": {
            "illustration": {
                "calibrated": True,
                "positive": anchors[:2],
                "negative": anchors[2:],
            }
        },
    }
    manifest = root / "manifest.json"
    manifest.write_text(json.dumps(profile), encoding="utf-8")
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
    }

    def http(url, **kwargs):
        if "payload" in kwargs:
            state["searches"] += 1
            assert kwargs["key"] == "private-test-search-key"
            return (
                url,
                "application/json",
                json.dumps(
                    {
                        "results": [
                            {"url": f"https://art.example.com/works/{i}"}
                            for i in range(3)
                        ],
                        "images": ["https://unrelated.example.com/false.jpg"],
                    }
                ).encode(),
            )
        if "/works/" in url:
            return (
                url,
                "text/html",
                f'<meta property="og:title" content="A complete artwork"><meta property="og:image" content="https://art.example.com/image{url[-1]}.png">'.encode(),
            )
        state["downloads"].append(url)
        if state["broken"]:
            raise DrawError("reference_unreadable")
        return url, "image/png", artworks[int(url[-5])]

    async def generate(messages, **kwargs):
        state["requests"].append(messages)
        assert "private-test-search-key" not in json.dumps(messages)
        system = messages[0]["content"]
        if system.startswith("Prepare an image"):
            original = json.loads(messages[1]["content"])["request"]
            response = {
                "category": "poster" if state.get("poster") else "illustration",
                "constraints": [
                    {"source": source, "requirement": requirement}
                    for source, requirement in [
                        ("单人", "one person"),
                        ("不要文字", "no lettering"),
                    ]
                    if source in original
                ],
                "creative_freedom": "setting and framing",
                "query": "curated editorial artwork",
                "fallback_query": "excellent visual composition",
                "style_compatible": True,
            }
        elif system.startswith("You are a visual art editor"):
            state["reviews"] += 1
            if state["blocked"]:
                return {
                    "success": True,
                    "blocked": True,
                    "response": "Private provider refusal",
                }
            parts = messages[1]["content"]
            assert sum(item["type"] == "image_url" for item in parts) == (
                3 if plugin.config.draw.use_profile else 1
            )
            current = json.loads(parts[0]["text"])
            rejected = state["reviews"] <= state["reject"]
            response = {
                "candidate_id": current["candidate_id"],
                "rating": "weak" if rejected else "strong",
                "positive_comparison": ("worse" if rejected else "comparable")
                if plugin.config.draw.use_profile
                else None,
                "negative_comparison": "better"
                if plugin.config.draw.use_profile
                else None,
                "evidence": ["Clear silhouette and light-dark organization"],
                "critical_flaws": [],
                "fits_request": True,
                "adaptable": True,
                "complete_artwork": True,
                "style_compatible": True,
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
                "constraint_sources": [
                    item["source"] for item in payload["brief"]["constraints"]
                ],
                "constraint_renderings": [
                    "single girl" if item["source"] == "单人" else "No lettering"
                    for item in payload["brief"]["constraints"]
                ],
                "design_coverage": [0, 1, 2],
                "design_renderings": [
                    "single girl",
                    "negative space",
                    "blue and cream",
                ],
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
            if state.get("poster"):
                response.update(mode="layout", visible_texts=payload["fixed_texts"])
                response["draft"] = {
                    "width": payload["width"],
                    "height": payload["height"],
                    "bbox_coord_space": "abs",
                    "bbox_format": "xyxy",
                    "summary": {
                        "caption": "A single girl in a blue and cream composition with negative space."
                    },
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
            if state["repair"] and "\nRepair only" not in messages[1]["content"]:
                response["constraint_sources"] = []
        return {"success": True, "response": json.dumps(response)}

    monkeypatch.setattr("moss.references.safe_http", http)
    plugin.ctx.llm.generate.side_effect = generate
    return state, profile, manifest


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
        assert prompt.startswith(plugin.config.styles.presets[0].split("=", 1)[1])
        assert "best quality" not in prompt
        snapshot = json.loads((directory / "config.json").read_text(encoding="utf-8"))
        assert "tavily_api_key" not in snapshot["draw"]
        assert all(
            "private-test-search-key" not in path.read_text(encoding="utf-8")
            for path in directory.rglob("*.json")
        )
        await plugin.on_unload()

    asyncio.run(run())


def test_draw_rejects_then_stops_at_second_and_preserves_explicit_canvas(
    plugin, command, draw_setup, comfy_transport
):
    state, _, _ = draw_setup
    state.update(reject=1, repair=True)
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
        assert plugin.ctx.llm.generate.await_count == 5
        assert len(comfy_transport) == 3
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
        assert plugin.ctx.llm.generate.await_count == 4
        await plugin.on_unload()

    asyncio.run(run())


def test_draw_unverified_or_changed_profile_fails_without_network_or_llm(
    plugin, command, draw_setup, comfy_transport
):
    state, profile, manifest = draw_setup
    profile["multimodal_verified"] = False
    manifest.write_text(json.dumps(profile), encoding="utf-8")

    async def run():
        await plugin.on_load()
        await plugin.handle_moss(**command)
        await asyncio.gather(*list(plugin.jobs.values()))
        assert not state["downloads"] and not state["searches"] and not comfy_transport
        plugin.ctx.llm.generate.assert_not_awaited()
        profile["multimodal_verified"] = True
        profile["vision_model_name"] = "changed-route"
        manifest.write_text(json.dumps(profile), encoding="utf-8")
        with pytest.raises(DrawError, match="uncalibrated"):
            Aesthetics(plugin.store.data, plugin.config)
        await plugin.on_unload()

    asyncio.run(run())


def test_draw_defaults_to_builtin_review_without_reading_personal_profile(
    plugin, command, draw_setup, comfy_transport, monkeypatch
):
    state, profile, manifest = draw_setup
    assert MossConfig().draw.use_profile is False
    plugin.config.draw.use_profile = False
    manifest.write_text(
        "invalid personal profile that must be ignored", encoding="utf-8"
    )
    fallback_sources = tuple(
        SourceRule.model_validate({**item, "kind": "publisher_page"})
        for item in profile["sources"]
    )
    monkeypatch.setattr("moss.aesthetics.BUILTIN_SOURCES", fallback_sources)
    engine = Aesthetics(plugin.ctx.paths.data_dir, plugin.config)
    assert engine.profile is None and set(engine.categories) == {
        "poster",
        "illustration",
    }
    manifest.unlink()

    async def run():
        await plugin.on_load()
        await plugin.handle_moss(**command)
        await asyncio.gather(*list(plugin.jobs.values()))
        record = json.loads(
            next(plugin.store.records.glob("*.json")).read_text(encoding="utf-8")
        )
        assert record["status"] == "sent", record
        directory = plugin.store.runtime / record["task_id"] / "draw"
        selection = json.loads(
            (directory / "selection.json").read_text(encoding="utf-8")
        )
        assert (
            selection["profile"] == "builtin-v1"
            and not selection["personal_profile_enabled"]
        )
        reviews = json.loads((directory / "reviews.json").read_text(encoding="utf-8"))
        assert (
            reviews[0]["positive_comparison"] is None
            and reviews[0]["negative_comparison"] is None
        )
        references = json.loads(
            (directory / "references.json").read_text(encoding="utf-8")
        )
        assert references[0]["source_kind"] == "publisher_page"
        assert plugin.ctx.llm.generate.await_count == 3 and len(state["downloads"]) == 1
        assert sum(call.url.path == "/prompt" for call in comfy_transport) == 1
        await plugin.on_unload()

    asyncio.run(run())


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
        assert (await plugin.styles.snapshot("a" * 64, plugin.config.styles, "draw"))[
            0
        ] == "千代风格"
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
    state, profile, manifest = draw_setup
    state["poster"] = True
    profile["categories"]["poster"] = profile["categories"].pop("illustration")
    manifest.write_text(json.dumps(profile), encoding="utf-8")
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
        assert compiled["summary"]["caption"].startswith(
            plugin.config.styles.presets[0].split("=", 1)[1]
        )
        assert plugin.ctx.llm.generate.await_count == 3
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
