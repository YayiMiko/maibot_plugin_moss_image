"""Natural canvas clauses are tolerant without modifying quoted image wording."""

import asyncio
import json

import pytest

from moss.commands import parse_command
from moss.config import MossConfig


@pytest.mark.parametrize("mode", ["生成", "规划", "布局"])
@pytest.mark.parametrize(
    "suffix",
    [
        "，比例4：3",
        ",比例4:3",
        "， 比例 4 : 3。",
        " 比例：4：3",
        "\n比例4:\n3",
        "，--比例 4:3",
        "，--比例4：3。",
        " --比例 4:3",
        "；比例 ４：３！",
    ],
)
def test_natural_and_legacy_ratios_select_landscape(mode, suffix):
    _, request = parse_command(
        f"/moss {mode} 夕阳洒在她身上" + suffix, MossConfig().rendering
    )
    assert request.prompt == "夕阳洒在她身上"
    assert (request.width, request.height) == (1184, 880)


@pytest.mark.parametrize(
    "text,body",
    [
        ("比例4:3，夕阳洒在她身上", "夕阳洒在她身上"),
        ("夕阳洒在她身上，比例4:3，远处有雾", "夕阳洒在她身上，远处有雾"),
        ("夕阳洒在她身上，比例4:3，比例8:6", "夕阳洒在她身上"),
        ("夕阳洒在她身上 --比例4:3，比例4：3。", "夕阳洒在她身上"),
        ("夕阳，夕阳\n柔和的光。\n比例4：3", "夕阳，夕阳\n柔和的光。"),
    ],
)
def test_only_canvas_clauses_and_their_separators_are_removed(text, body):
    _, request = parse_command("/moss 生成 " + text, MossConfig().rendering)
    assert request.prompt == body and request.width > request.height


@pytest.mark.parametrize(
    "quote",
    [
        '"比例4:3"',
        "“比例4：3”",
        "‘比例4:3’",
        "'--比例 4:3'",
        "「比例4：3」",
        "『--比例 4:3』",
    ],
)
def test_quoted_ratio_is_literal_not_a_canvas_instruction(quote):
    body = "牌子写着" + quote
    _, request = parse_command("/moss 生成 " + body, MossConfig().rendering)
    assert request.prompt == body and (request.width, request.height) == (880, 1184)
    _, request = parse_command(
        "/moss 生成 " + body + "，比例4：3", MossConfig().rendering
    )
    assert request.prompt == body and request.width > request.height


def test_canvas_pattern_cannot_consume_quoted_content_as_whitespace():
    body = "比例“这行文字不能删掉”4:3，夕阳"
    _, request = parse_command("/moss 生成 " + body, MossConfig().rendering)
    assert request.prompt == body and request.width < request.height
    with pytest.raises(ValueError):
        parse_command("/moss 生成 夕阳 --比例 “不要删” 4:3", MossConfig().rendering)


@pytest.mark.parametrize(
    "body",
    [
        "比例协调的少女",
        "身材比例4:3的角色",
        "一张比例4:3的卡片",
        "It's sunset, a girl's silhouette",
    ],
)
def test_description_and_english_apostrophes_remain_unchanged(body):
    _, request = parse_command("/moss 生成 " + body, MossConfig().rendering)
    assert request.prompt == body and request.width < request.height
    _, request = parse_command(
        "/moss 生成 " + body + "，比例4:3", MossConfig().rendering
    )
    assert request.prompt == body and request.width > request.height


@pytest.mark.parametrize(
    "suffix",
    [
        "，比例4:3，比例3:4",
        " --比例4:3 --比例16:9",
        " --比例4:3 --比例bad",
        " --尺寸1024x1024",
        "，--尺寸 1024x1024，比例4:3",
        "，比例4/3",
        "，比例4:3.5",
        "，比例4.0:3",
        "，比例4:3x",
        "，比例4:3:2",
        "，比例0:3",
        "，比例0:0",
        "，比例4:0",
        "，比例-4:3",
        "，比例100:1",
        "，比例101:100",
        "，比例+4:3",
    ],
)
def test_conflicting_or_invalid_parameters_do_not_silently_use_defaults(suffix):
    with pytest.raises(ValueError):
        parse_command("/moss 生成 夕阳洒在她身上" + suffix, MossConfig().rendering)


def test_punctuation_adjacent_explicit_size_and_missing_description():
    _, request = parse_command(
        "/moss 生成 猫，--尺寸 1024x1024。", MossConfig().rendering
    )
    assert request.prompt == "猫" and request.width == request.height == 1024
    with pytest.raises(ValueError, match="绘图要求"):
        parse_command("/moss 生成 比例4：3。", MossConfig().rendering)


def test_direct_runtime_submits_landscape_and_original_description(
    plugin, command, comfy_transport
):
    command["text"] = "/moss 生成 夕阳洒在她身上，比例4：3"

    async def run():
        await plugin.on_load()
        await plugin.handle_moss(**command)
        await asyncio.gather(*list(plugin.jobs.values()))
        record = json.loads(
            next(plugin.store.records.glob("*.json")).read_text(encoding="utf-8")
        )
        assert record["status"] == "sent"
        graph = json.loads(
            next(call.content for call in comfy_transport if call.url.path == "/prompt")
        )["prompt"]
        assert (
            graph["6"]["inputs"]["width"] == 1184
            and graph["6"]["inputs"]["height"] == 880
        )
        assert graph["4"]["inputs"]["text"].endswith("\n夕阳洒在她身上")
        assert "比例4" not in graph["4"]["inputs"]["text"]
        body = (
            plugin.store.runtime / record["task_id"] / "content_prompt.txt"
        ).read_text(encoding="utf-8")
        assert body == "夕阳洒在她身上"
        plugin.ctx.llm.generate.assert_not_awaited()
        await plugin.on_unload()

    asyncio.run(run())
