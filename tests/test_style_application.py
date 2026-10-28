"""Style applicability is scoped, frozen and independent of official routes."""

import asyncio
import json

import pytest
from test_media_planner import envelope, story
from test_skill_planner import layout, make_planner

from moss.commands import ImageRequest
from moss.config import Planning
from moss.planner import PlanningError


@pytest.mark.parametrize(
    "route", ["生成", "规划", "布局", "漫画", "表情包", "配字表情包"]
)
@pytest.mark.parametrize("enabled", [False, True])
def test_route_matrix_explicit_style(plugin, command, comfy_transport, route, enabled):
    style = "@artist name, 简洁平涂，"
    plugin.config.styles.presets = ["千代风格=" + style]
    keyword = "表情包" if route == "配字表情包" else route
    command["text"] = (
        f"/moss {keyword} 猫困了"
        + (" @千代风格 @千代风格" if enabled else "")
        + " --尺寸 1024x1024"
    )
    if route == "配字表情包":
        command["text"] += "，配字“原文”"
    if route in {"漫画", "表情包", "配字表情包"}:
        board = story(
            2 if route == "漫画" else 1, "原文" if route == "配字表情包" else None
        )
        draft = (
            {"caption": "A cat looking sleepy."}
            if route == "表情包"
            else envelope(board, comic=route == "漫画")
        )
        replies = [json.dumps(board), json.dumps(draft)]
    elif route == "布局":
        replies = [json.dumps(layout())]
    else:
        replies = ['{"caption":"A cat looking sleepy."}']
    plugin.ctx.llm.generate.side_effect = [
        {"success": True, "response": reply} for reply in replies
    ]

    async def run():
        await plugin.on_load()
        await plugin.handle_moss(**command)
        plugin.config.styles.presets = ["千代风格=LATER STYLE"]
        await asyncio.gather(*list(plugin.jobs.values()))
        record = json.loads(
            next(plugin.store.records.glob("*.json")).read_text(encoding="utf-8")
        )
        assert record["status"] == "sent", record
        directory = plugin.store.runtime / record["task_id"]
        frozen = json.loads((directory / "request.json").read_text(encoding="utf-8"))
        submitted = json.loads(
            next(call.content for call in comfy_transport if call.url.path == "/prompt")
        )["prompt"]["4"]["inputs"]["text"]
        assert bool(frozen["style_prompt"]) == enabled
        effective = style.rstrip(",，") if route == "生成" else style
        assert submitted.count(effective) == int(enabled)
        assert "LATER STYLE" not in submitted
        assert ("best quality" in submitted) == (route == "生成")
        await plugin.on_unload()

    asyncio.run(run())


@pytest.mark.parametrize("use_layout", [True, False])
def test_style_cannot_mask_an_invalid_media_draft(use_layout):
    board = story(2 if use_layout else 1)
    draft = envelope(board) if use_layout else {"caption": ""}
    if use_layout:
        draft["draft"]["items"][0]["bbox"][2] = 5000
    planner, ctx, _ = make_planner(
        [
            {"success": True, "response": json.dumps(board)},
            *[{"success": True, "response": json.dumps(draft)}] * 2,
        ]
    )
    with pytest.raises(PlanningError, match="invalid_media_draft"):
        asyncio.run(
            planner.plan(
                ImageRequest(
                    "猫困了",
                    1024,
                    1024,
                    "layout" if use_layout else "caption",
                    task_type="comic_page" if use_layout else "meme",
                    style_prompt="ink",
                ),
                Planning(danbooru_enabled=False),
            )
        )
    assert ctx.llm.generate.await_count == 3


def test_style_echo_does_not_get_appended_twice():
    style = "@artist, 平涂，"
    board = story(1)
    planner, _, _ = make_planner(
        [
            {"success": True, "response": json.dumps(board)},
            {
                "success": True,
                "response": json.dumps({"caption": "A sleepy cat. " + style}),
            },
        ]
    )
    plan = asyncio.run(
        planner.plan(
            ImageRequest(
                "猫困了", 1024, 1024, "caption", task_type="meme", style_prompt=style
            ),
            Planning(danbooru_enabled=False),
        )
    )
    assert plan.prompt.startswith(style) and plan.prompt.count(style) == 1
