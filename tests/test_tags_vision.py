"""Direct descriptions and native vision remain isolated from official Caption."""

import asyncio
import base64
import io
import json
from unittest.mock import AsyncMock

import pytest
from PIL import Image
from test_skill_planner import make_planner

from moss.commands import HELP, ImageRequest, parse_command
from moss.config import MossConfig, Planning, Vision
from moss.media import MetadataReader
from moss.tag_output import clean_tag_output
from moss.vision import VisionError, reverse_image


@pytest.mark.parametrize(
    "body",
    [
        '{"caption":"A cup."}',
        "best quality, highres",
        "",
        "I cannot help with that request.",
    ],
)
def test_direct_body_is_not_interpreted_as_an_llm_completion(body):
    if not body:
        body = "中文短句也可以"
    planner, ctx, _ = make_planner([])
    plan = asyncio.run(
        planner.plan(
            ImageRequest(body, 1024, 1024, "generate"), Planning(danbooru_enabled=False)
        )
    )
    assert plan.prompt == plan.content_prompt == body
    ctx.llm.generate.assert_not_awaited()


def test_direct_prefix_dedup_never_cleans_body_or_adds_white_background():
    planner, ctx, _ = make_planner([])
    body = "highres, 红外套，红外套\n牌子写“hello, 世界！”"
    plan = asyncio.run(
        planner.plan(
            ImageRequest(
                body,
                1024,
                1024,
                "generate",
                positive_prefix="best quality, highres, BEST QUALITY,",
                style_prompt="@artist,",
            ),
            Planning(danbooru_enabled=False),
        )
    )
    assert plan.content_prompt == body
    assert plan.prompt == "best quality\n@artist\n" + body
    assert plan.prompt.count("@artist") == 1
    assert "white background" not in plan.prompt
    ctx.llm.generate.assert_not_awaited()


def test_tag_cleaner_preserves_quoted_lettering_and_character_parentheses():
    assert (
        clean_tag_output('tags: 1girl, text "hello, 世界！", pandora_(re:zero), 1GIRL')
        == '1girl, text "hello, 世界！", pandora_(re:zero)'
    )
    for text in (
        '{"caption":"test"}',
        'text "broken',
        "A picture of a cup.",
        "(broken",
        "纯中文",
    ):
        with pytest.raises(ValueError):
            clean_tag_output(text)


def test_help_explains_modes_and_reverse_does_not_accept_generation_arguments():
    assert "原文直出" in HELP and "官方扩写＋布局规划生图" in HELP
    assert "非原词" in HELP
    assert "宽×高像素" in HELP
    assert "\n\n" not in HELP and len(HELP.splitlines()) == 7 and len(HELP) < 320
    with pytest.raises(ValueError):
        parse_command("/moss 反推 顺便生图", MossConfig().rendering)


def test_native_vision_uses_separate_route_and_sanitized_pixels(plugin, png_bytes):
    plugin.ctx.llm.generate.return_value = {
        "success": True,
        "response": "white rectangle, plain background",
    }
    capture = AsyncMock()
    tags = asyncio.run(
        reverse_image(
            plugin.ctx,
            Vision(model_task="vlm", model_name="test-vision"),
            png_bytes,
            capture,
        )
    )
    assert tags == "white rectangle, plain background"
    args, kwargs = plugin.ctx.llm.generate.call_args
    assert kwargs == {
        "task_name": "vlm",
        "model_name": "test-vision",
        "max_tokens": 2048,
    }
    assert len(args[0]) == 2
    url = args[0][1]["content"][1]["image_url"]["url"]
    assert url.startswith("data:image/jpeg;base64,")
    with Image.open(io.BytesIO(base64.b64decode(url.split(",", 1)[1]))) as image:
        assert image.size == (16, 24) and image.format == "JPEG"
        assert not image.getexif()
    capture.assert_awaited_once()


@pytest.mark.parametrize(
    "result,reason",
    [
        ({"success": True, "response": "I cannot describe this image."}, "blocked"),
        ({"success": False, "error": "private provider error"}, "unavailable"),
        (
            {"success": True, "response": "cat, standing", "finish_reason": "length"},
            "truncated",
        ),
        ({"success": True, "response": '{"caption":"A cat."}'}, "invalid_tags"),
        ({"success": True, "response": ""}, "unavailable"),
    ],
)
def test_vision_failure_never_retries(plugin, png_bytes, result, reason):
    plugin.ctx.llm.generate.return_value = result
    with pytest.raises(VisionError, match=reason):
        asyncio.run(reverse_image(plugin.ctx, Vision(), png_bytes))
    assert plugin.ctx.llm.generate.await_count == 1


def test_vision_provider_exception_and_cancellation(plugin, png_bytes):
    plugin.ctx.llm.generate.side_effect = RuntimeError("private endpoint")
    with pytest.raises(VisionError, match="unavailable"):
        asyncio.run(reverse_image(plugin.ctx, Vision(), png_bytes))
    plugin.ctx.llm.generate.side_effect = asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(reverse_image(plugin.ctx, Vision(), png_bytes))


@pytest.mark.parametrize("long", [False, True])
def test_reverse_runtime_returns_only_tags_without_comfy_or_styles(
    plugin, command, png_bytes, comfy_transport, monkeypatch, long
):
    command["text"] = "/moss 反推"
    tags = (
        ", ".join(f"detail {i}" for i in range(130)) if long else "white cat, sitting"
    )
    plugin.ctx.llm.generate.return_value = {"success": True, "response": tags}
    message = {
        "group_id": "group",
        "message": [{"type": "image", "data": {"url": "https://qpic.cn/test.png"}}],
    }
    plugin.ctx.api.call.side_effect = lambda method, **kw: (
        {"user_id": "bot", "nickname": "MOSS"}
        if kw.get("action_name") == "get_login_info"
        else message
    )
    monkeypatch.setattr(MetadataReader, "read_bytes", AsyncMock(return_value=png_bytes))

    async def run():
        await plugin.on_load()
        await plugin.handle_moss(**command)
        await asyncio.gather(*list(plugin.jobs.values()))
        record = json.loads(
            next(plugin.store.records.glob("*.json")).read_text(encoding="utf-8")
        )
        directory = plugin.store.runtime / record["task_id"]
        assert record["status"] == "completed" and record["action"] == "reverse"
        assert (directory / "prompt.txt").read_text(encoding="utf-8") == tags
        assert not (directory / "workflow.json").exists() and not comfy_transport
        plugin.ctx.send.image.assert_not_awaited()
        sender = plugin.ctx.send.forward if long else plugin.ctx.send.text
        sender.assert_awaited_once()
        other = plugin.ctx.send.text if long else plugin.ctx.send.forward
        other.assert_not_awaited()
        diagnostic = json.loads(
            (plugin.store.data / "last_llm_response.json").read_text(encoding="utf-8")
        )
        assert diagnostic["calls"][0]["stage"] == "vision"
        assert plugin.ctx.llm.generate.call_args.kwargs["task_name"] == "vlm"
        await plugin.on_unload()

    asyncio.run(run())


@pytest.mark.parametrize(
    "kind", ["missing", "multiple", "cross_group", "bad_quote", "refusal"]
)
def test_reverse_runtime_failure_has_no_generation_or_raw_reply(
    plugin, command, png_bytes, comfy_transport, kind
):
    command["text"] = "/moss 反推"
    data = "base64://" + base64.b64encode(png_bytes).decode()
    images = [{"type": "image", "data": {"url": data}}]
    message = {"group_id": "group", "message": images}
    if kind == "missing":
        message["message"] = []
    if kind == "multiple":
        message["message"] = images * 2
    if kind == "cross_group":
        message["group_id"] = "other"
    if kind == "bad_quote":
        message["message"] = [{"type": "reply", "data": {"id": "unreadable"}}, *images]
        plugin.ctx.api.call.side_effect = [message, None]
    else:
        plugin.ctx.api.call.return_value = message
    plugin.ctx.llm.generate.return_value = {
        "success": True,
        "blocked": True,
        "response": "private refusal",
    }

    async def run():
        await plugin.on_load()
        await plugin.handle_moss(**command)
        await asyncio.gather(*list(plugin.jobs.values()))
        assert not comfy_transport
        plugin.ctx.send.image.assert_not_awaited()
        if kind != "refusal":
            plugin.ctx.llm.generate.assert_not_awaited()
        else:
            plugin.ctx.llm.generate.assert_awaited_once()
        notice = plugin.ctx.send.text.call_args.args[0]
        assert "private refusal" not in notice and "生图" not in notice
        await plugin.on_unload()

    asyncio.run(run())
