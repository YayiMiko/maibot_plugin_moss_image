"""Style applicability is scoped, frozen and independent of official routes."""

import asyncio
import hashlib
import json

import pytest
from test_media_planner import envelope, story
from test_skill_planner import layout, make_planner

from moss.commands import HELP, ImageRequest, StyleRequest, parse_command
from moss.config import MossConfig, Planning, Styles
from moss.planner import PlanningError
from moss.styles import StyleStore


@pytest.mark.parametrize(
    "suffix,operation,value",
    [
        ("", "settings", ""),
        (" 1", "application", "generate"),
        (" 2", "application", "all"),
    ],
)
def test_style_settings_grammar(suffix, operation, value):
    action, request = parse_command("/moss 风格 设置" + suffix, MossConfig().rendering)
    assert action == "style" and request.operation == operation
    assert request.content == value
    assert "设置" not in HELP


@pytest.mark.parametrize("value", ["0", "3", "1 2", "全部生图", "1=ink", "1.0"])
def test_invalid_style_settings_never_become_style_selection(value):
    with pytest.raises(ValueError, match="风格 设置"):
        parse_command("/moss 风格 设置 " + value, MossConfig().rendering)


def test_old_style_storage_inherits_default_without_rewriting_library(tmp_path):
    original = {
        "library": {"测试": "ink, @artist,"},
        "selections": {"a" * 64: "测试"},
        "processed": ["b" * 24],
    }
    path = tmp_path / "styles.json"
    path.write_text(json.dumps(original, ensure_ascii=False), encoding="utf-8")
    before = path.read_bytes()

    async def run():
        store = StyleStore(tmp_path)
        await store.initialize()
        assert await store.snapshot("a" * 64, Styles(), "comic_page") == (
            "测试",
            "ink, @artist,",
        )
        assert path.read_bytes() == before
        assert store.state == {**original, "applications": {}}
        menu = await store.handle(
            StyleRequest("settings"), "a" * 64, "c" * 24, Styles()
        )
        assert "（默认）" in "\n".join(menu)
        assert path.read_bytes() == before
        await store.handle(
            StyleRequest("application", content="generate"),
            "a" * 64,
            "c" * 24,
            Styles(),
        )
        saved = json.loads(path.read_text(encoding="utf-8"))
        assert saved["library"] == original["library"]
        assert saved["selections"] == original["selections"]
        assert saved["processed"][0] == "b" * 24
        assert saved["applications"] == {"a" * 64: "generate"}

    asyncio.run(run())


@pytest.mark.parametrize("application", [None, [], "invalid", 1])
def test_damaged_application_storage_is_not_reset(tmp_path, application):
    path = tmp_path / "styles.json"
    path.write_text(
        json.dumps(
            {
                "library": {},
                "selections": {},
                "processed": [],
                "applications": {"a" * 64: application},
            }
        ),
        encoding="utf-8",
    )
    before = path.read_bytes()
    with pytest.raises(ValueError, match="style application"):
        asyncio.run(StyleStore(tmp_path).initialize())
    assert path.read_bytes() == before


def test_application_selection_is_persistent_deduplicated_and_scope_local(tmp_path):
    async def run():
        config = Styles()
        store = StyleStore(tmp_path)
        await store.initialize()
        first, second = "a" * 64, "b" * 64
        await store.handle(
            StyleRequest("application", content="generate"), first, "a" * 24, config
        )
        assert await store.snapshot(first, config, "comic_page") == ("", "")
        assert (await store.snapshot(first, config))[0] == "千代风格"
        assert (await store.snapshot(second, config, "comic_page"))[0] == "千代风格"
        await store.handle(
            StyleRequest("application", content="all"), first, "b" * 24, config
        )
        await store.handle(
            StyleRequest("application", content="generate"), first, "a" * 24, config
        )
        reloaded = StyleStore(tmp_path)
        await reloaded.initialize()
        assert (await reloaded.snapshot(first, config, "comic_page"))[0] == "千代风格"
        assert reloaded.state["applications"][first] == "all"
        menu = "\n".join(
            await reloaded.handle(StyleRequest("settings"), first, "c" * 24, config)
        )
        assert "当前：「生成、漫画、表情包」" in menu

    asyncio.run(run())


@pytest.mark.parametrize("default", ["all", "generate"])
@pytest.mark.parametrize("override", [None, "all", "generate"])
@pytest.mark.parametrize(
    "route", ["生成", "规划", "布局", "漫画", "表情包", "配字表情包"]
)
def test_route_matrix_submits_style_only_where_enabled(
    plugin, command, comfy_transport, default, override, route
):
    style = "@artist name, 简洁平涂，"
    plugin.config.styles.presets = ["千代风格=" + style]
    plugin.config.styles.default_application = default
    keyword = "表情包" if route == "配字表情包" else route
    command["text"] = f"/moss {keyword} 猫困了 --尺寸 1024x1024"
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
        scope = hashlib.sha256(
            json.dumps(["qq", "stream", "user"]).encode()
        ).hexdigest()
        if override:
            await plugin.styles.handle(
                StyleRequest("application", content=override),
                scope,
                "a" * 24,
                plugin.config.styles,
            )
        await plugin.handle_moss(**command)
        # A later setting/preset edit cannot change this admitted task.
        plugin.styles.state["applications"][scope] = (
            "generate" if (override or default) == "all" else "all"
        )
        plugin.config.styles.presets = ["千代风格=LATER STYLE"]
        await asyncio.gather(*list(plugin.jobs.values()))
        record = json.loads(
            next(plugin.store.records.glob("*.json")).read_text(encoding="utf-8")
        )
        assert record["status"] == "sent"
        directory = plugin.store.runtime / record["task_id"]
        frozen = json.loads((directory / "request.json").read_text(encoding="utf-8"))
        submitted = json.loads(
            next(call.content for call in comfy_transport if call.url.path == "/prompt")
        )["prompt"]["4"]["inputs"]["text"]
        enabled = route == "生成" or (
            route not in {"规划", "布局"} and (override or default) == "all"
        )
        assert bool(frozen["style_prompt"]) == enabled
        effective = style.rstrip(",，") if route == "生成" else style
        assert (effective in submitted) == enabled
        assert "LATER STYLE" not in submitted
        assert submitted.count(effective) == int(enabled)
        assert ("best quality" in submitted) == (route == "生成")
        if route == "生成":
            plugin.ctx.llm.generate.assert_not_awaited()
        else:
            assert plugin.ctx.llm.generate.await_count == len(replies)
            for call in plugin.ctx.llm.generate.await_args_list:
                payload = json.loads(call.args[0][1]["content"])
                if route in {"规划", "布局"}:
                    assert "selected_style" not in payload
                else:
                    assert payload["request"] == frozen["prompt"]
                    assert payload["selected_style"] == (style if enabled else "")
            if route in {"布局", "漫画", "配字表情包"}:
                compiled = json.loads(submitted)
                assert set(compiled) == {
                    "summary",
                    "items",
                    "bbox_coord_space",
                    "bbox_format",
                }
                assert compiled["bbox_coord_space"] == "abs_centralized"
                if enabled:
                    assert style in compiled["summary"]["caption"]
                    assert all(
                        style not in item["caption"] for item in compiled["items"]
                    )
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
    assert plan.prompt.count(style) == 1
