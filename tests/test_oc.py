"""Explicit OC selection, owner authorization, atomic persistence and isolation."""

import asyncio
import json

import pytest
from test_skill_planner import make_planner

from moss.commands import ImageRequest, parse_command
from moss.config import MossConfig, Planning
from moss.oc import OCStore, parse_role


def test_role_submenu_and_optional_fields_are_parsed():
    assert parse_role("").operation == "list"
    assert parse_role("狐莉").operation == "show"
    assert (
        parse_role("新建 狐莉=white hair, fox ears").content == "white hair, fox ears"
    )
    assert parse_role("编辑 狐莉=蓝眼睛").operation == "edit"
    assert parse_role("服装 狐莉=").content == ""
    assert parse_role("别名 狐莉=小狐,狐狸娘").operation == "aliases"
    assert parse_role("删除 狐莉").operation == "delete"


@pytest.mark.parametrize(
    "arguments",
    [
        "新建 A=",
        "新建 =B",
        "删除 ../A",
        "新建 --角色=x",
        "编辑 A=B\x00",
    ],
)
def test_invalid_role_subcommands_fail_before_storage(arguments):
    with pytest.raises(ValueError):
        parse_role(arguments)


def test_role_library_preserves_owner_aliases_and_existing_snapshots(tmp_path):
    async def run():
        store = OCStore(tmp_path)
        await store.initialize()
        assert await store.snapshot(()) is None
        await store.handle(
            parse_role("新建 狐莉=white hair, fox ears"), "owner", [], "a" * 24
        )
        await store.handle(parse_role("服装 狐莉=white dress"), "owner", [], "b" * 24)
        await store.handle(parse_role("别名 狐莉=小狐,狐狸娘"), "owner", [], "c" * 24)
        snapshot = await store.snapshot(("小狐", "狐莉"))
        assert len(snapshot["characters"]) == 1
        assert snapshot["characters"][0]["default_outfit"] == "white dress"
        assert "owner" not in snapshot["characters"][0]
        denied = await store.handle(
            parse_role("编辑 小狐=WRONG"), "other", [], "d" * 24
        )
        assert "创建者" in denied[0]
        await store.handle(
            parse_role("编辑 狐莉=blue eyes, fox ears"), "admin", ["admin"], "e" * 24
        )
        assert snapshot["characters"][0]["description"] == "white hair, fox ears"
        reloaded = OCStore(tmp_path)
        await reloaded.initialize()
        current = await reloaded.snapshot(("小狐",))
        assert current["characters"][0]["description"] == "blue eyes, fox ears"
        assert reloaded.state["library"]["狐莉"]["owner"] == "owner"
        duplicate = await reloaded.handle(
            parse_role("删除 狐莉"), "owner", [], "e" * 24
        )
        assert "重复" in duplicate[0]
        await reloaded.handle(parse_role("删除 小狐"), "owner", [], "f" * 24)
        assert not reloaded.state["library"]
        assert snapshot["characters"][0]["name"] == "狐莉"
        with pytest.raises(ValueError):
            await reloaded.snapshot(("狐莉",))

    asyncio.run(run())


def test_alias_conflicts_never_overwrite_other_roles(tmp_path):
    async def run():
        store = OCStore(tmp_path)
        await store.initialize()
        await store.handle(parse_role("新建 A=red hair"), "a", [], "a" * 24)
        await store.handle(parse_role("新建 B=blue hair"), "b", [], "b" * 24)
        refused = await store.handle(parse_role("别名 A=B"), "a", [], "c" * 24)
        assert "冲突" in refused[0]
        assert (await store.snapshot(("B",)))["characters"][0][
            "description"
        ] == "blue hair"

    asyncio.run(run())


def test_corrupt_oc_data_is_not_silently_replaced(tmp_path):
    (tmp_path / "characters.json").write_text(
        '{"library":[],"processed":[]}', encoding="utf-8"
    )
    with pytest.raises(ValueError):
        asyncio.run(OCStore(tmp_path).initialize())
    assert json.loads((tmp_path / "characters.json").read_text())["library"] == []


@pytest.mark.parametrize(
    "suffix",
    ["+狐莉 +小狐", "+狐莉，比例4：3", "+狐莉 --格数 3"],
)
def test_role_controls_do_not_enter_media_description(suffix):
    _, request = parse_command("/moss 漫画 抢包子 " + suffix, MossConfig().rendering)
    assert request.prompt == "抢包子" and request.task_type == "comic_page"
    assert request.oc_names[0] == "狐莉"
    if "格数" in suffix:
        assert request.panel_count == 3


@pytest.mark.parametrize(
    "command",
    [
        "/moss 生成 猫 --格数 3",
        "/moss 漫画 猫 --格数 5",
        "/moss 漫画 猫 --角色",
        "/moss 漫画 猫 --格数 2 --格数 3",
    ],
)
def test_invalid_controls_never_become_image_text(command):
    with pytest.raises(ValueError):
        parse_command(command, MossConfig().rendering)


def test_oc_never_goes_to_danbooru_or_changes_direct_body():
    planner, ctx, resolver = make_planner(
        [
            {
                "success": True,
                "response": '{"characters":[{"source_name":"小狐","depicted":true,"candidates":["wrong_tag"]}]}',
            }
        ]
    )
    oc = {
        "characters": [
            {
                "name": "狐莉",
                "description": "white hair, blue eyes, fox ears",
                "aliases": ["小狐"],
                "default_outfit": "white dress",
            }
        ]
    }
    plan = asyncio.run(
        planner.plan(
            ImageRequest(
                "小狐穿雨衣", 1024, 1024, "generate", oc_context=oc, oc_names=("小狐",)
            ),
            Planning(),
        )
    )
    assert plan.content_prompt == "小狐穿雨衣"
    assert '"狐莉" / "小狐"' in plan.prompt
    assert "white dress" not in plan.prompt and "wrong_tag" not in plan.prompt
    assert plan.prompt.endswith("小狐穿雨衣")
    resolver.resolve.assert_not_awaited()
    assert ctx.llm.generate.await_count == 1


def test_role_commands_do_not_use_llm_and_snapshots_are_request_local(
    plugin, command, comfy_transport
):
    async def run():
        await plugin.on_load()
        command["text"] = "/moss 角色 新建 狐莉=white hair, fox ears"
        await plugin.handle_moss(**command)
        await asyncio.gather(*list(plugin.jobs.values()))
        plugin.ctx.llm.generate.assert_not_awaited()
        assert not comfy_transport
        command["message"]["message_id"] = "next"
        command["text"] = "/moss 生成 狐莉穿雨衣 +狐莉"
        await plugin.handle_moss(**command)
        await plugin.characters.handle(
            parse_role("编辑 狐莉=NEW APPEARANCE"), "user", [], "d" * 24
        )
        await asyncio.gather(*list(plugin.jobs.values()))
        generation = next(
            json.loads(p.read_text(encoding="utf-8"))
            for p in plugin.store.records.glob("*.json")
            if json.loads(p.read_text())["action"] == "generate"
        )
        prompt = (
            plugin.store.runtime / generation["task_id"] / "prompt.txt"
        ).read_text(encoding="utf-8")
        assert "white hair, fox ears" in prompt and "NEW APPEARANCE" not in prompt
        assert generation["status"] == "sent"
        plugin.ctx.llm.generate.assert_not_awaited()
        await plugin.on_unload()

    asyncio.run(run())


def test_missing_oc_does_not_submit_any_generation(plugin, command, comfy_transport):
    command["text"] = "/moss 生成 狐莉 +不存在"

    async def run():
        await plugin.on_load()
        await plugin.handle_moss(**command)
        assert not plugin.jobs and not comfy_transport
        plugin.ctx.llm.generate.assert_not_awaited()
        assert "没有找到角色" in plugin.ctx.send.text.call_args.args[0]
        await plugin.on_unload()

    asyncio.run(run())


def test_missing_oc_blocks_draw_before_discovery(plugin, command, comfy_transport):
    command["text"] = "/moss 抽卡 狐莉 +不存在"

    async def run():
        await plugin.on_load()
        plugin.config.draw.enabled = True
        plugin.config.draw.tavily_api_key = "offline-test-key"
        await plugin.handle_moss(**command)
        assert not plugin.jobs and not comfy_transport
        plugin.ctx.llm.generate.assert_not_awaited()
        assert "没有找到角色" in plugin.ctx.send.text.call_args.args[0]
        await plugin.on_unload()

    asyncio.run(run())


@pytest.mark.parametrize(
    "body,count",
    [
        ("三格漫画，抢包子", 3),
        ("画两格漫画", 2),
        ("第一格相遇，第二格抢包子", None),
        ("牌子写着“三格”，抢包子", None),
        ("1～4格漫画，抢包子", None),
    ],
)
def test_panel_count_does_not_read_dialogue_or_panel_ordinals(body, count):
    _, request = parse_command("/moss 漫画 " + body, MossConfig().rendering)
    assert request.panel_count == count and request.prompt == body


@pytest.mark.parametrize("body", ["五格漫画", "三格漫画 --格数 2", "12格漫画"])
def test_invalid_natural_panel_counts_are_explained(body):
    with pytest.raises(ValueError, match="格"):
        parse_command("/moss 漫画 " + body, MossConfig().rendering)


def test_role_alias_is_not_mistaken_for_a_canvas_control():
    _, request = parse_command('/moss 漫画 抢包子 +"比例4:3"', MossConfig().rendering)
    assert request.oc_names == ("比例4:3",) and request.prompt == "抢包子"
    assert request.width < request.height
