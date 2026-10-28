"""Request-local selector boundaries and legacy library migration."""

import asyncio
import json

import pytest

from moss.commands import parse_command
from moss.config import MossConfig, Styles
from moss.styles import StyleStore


@pytest.mark.parametrize("route", ["生成", "规划", "布局", "漫画", "表情包", "抽卡"])
def test_selectors_and_boundaries(route):
    _, request = parse_command(
        f'/moss {route} 邮件 a@b.com、https://host/@path，C++，1 + 2，"@文本" @"水墨 风" +"狐 莉" @"水墨 风"',
        MossConfig().rendering,
    )
    assert request.style_names == ("水墨 风",)
    assert request.oc_names == ("狐 莉",)
    assert all(
        x in request.prompt
        for x in ("a@b.com", "https://host/@path", "C++", "1 + 2", '"@文本"')
    )


def test_escaped_quote_in_saved_name_reaches_generation(
    plugin, command, comfy_transport
):
    _, request = parse_command(r'''/moss 生成 猫 +"狐\"'莉"''', MossConfig().rendering)
    assert request.oc_names == ("狐\"'莉",)

    async def run():
        plugin.config.styles.presets = ["墨\"'色=INK"]
        await plugin.on_load()
        command["text"] = r'''/moss 生成 猫 @"墨\"'色"'''
        try:
            await plugin.handle_moss(**command)
            await asyncio.gather(*list(plugin.jobs.values()))
            payload = json.loads(
                next(
                    call.content
                    for call in comfy_transport
                    if call.url.path == "/prompt"
                )
            )
            assert "INK" in payload["prompt"]["4"]["inputs"]["text"]
        finally:
            await plugin.on_unload()

    asyncio.run(run())


@pytest.mark.parametrize(
    "text", ["/moss 生成 @墨色", "/moss 规划 +狐莉", "/moss 漫画 猫 --角色 狐莉"]
)
def test_empty_body_or_removed_syntax_is_rejected(text):
    with pytest.raises(ValueError):
        parse_command(text, MossConfig().rendering)


def test_legacy_style_state_is_preserved_but_not_selected(tmp_path):
    state = {
        "library": {"旧风": "ink"},
        "selections": {"a" * 64: "旧风"},
        "applications": {"a" * 64: "all"},
        "processed": [],
    }
    path = tmp_path / "styles.json"
    path.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    before = path.read_bytes()

    async def run():
        store = StyleStore(tmp_path)
        await store.initialize()
        assert await store.snapshot((), Styles()) == ("", "")
        assert await store.snapshot(("旧风",), Styles()) == ("旧风", "ink")

    asyncio.run(run())
    assert path.read_bytes() == before


def test_inline_platform_mention_is_not_style(plugin, command, comfy_transport):
    async def run():
        await plugin.on_load()
        command["text"] = "/moss 生成 猫 @bot"
        command["message"]["raw_message"] = [
            {"type": "text", "data": "/moss 生成 猫 "},
            {"type": "at", "data": {"target_user_id": "bot"}},
        ]
        await plugin.handle_moss(**command)
        await asyncio.gather(*list(plugin.jobs.values()))
        payload = json.loads(
            next(call.content for call in comfy_transport if call.url.path == "/prompt")
        )
        assert "猫" in payload["prompt"]["4"]["inputs"]["text"]
        await plugin.on_unload()

    asyncio.run(run())


def test_missing_style_rejected_before_admission(plugin, command, comfy_transport):
    async def run():
        await plugin.on_load()
        command["text"] = "/moss 生成 猫 @不存在"
        await plugin.handle_moss(**command)
        assert not plugin.jobs and not comfy_transport
        assert "没有找到风格" in plugin.ctx.send.text.call_args.args[0]
        await plugin.on_unload()

    asyncio.run(run())


def test_parallel_requests_keep_separate_snapshots(plugin, command, comfy_transport):
    import copy

    async def run():
        plugin.config.styles.presets = ["A=STYLE_A", "B=STYLE_B"]
        await plugin.on_load()
        first = copy.deepcopy(command)
        second = copy.deepcopy(command)
        first["text"] = "/moss 生成 cat @A"
        second["text"] = "/moss 生成 dog @B"
        second["message"]["message_id"] = "second"
        await asyncio.gather(plugin.handle_moss(**first), plugin.handle_moss(**second))
        plugin.config.styles.presets = ["A=CHANGED", "B=CHANGED"]
        await asyncio.gather(*list(plugin.jobs.values()))
        prompts = [
            json.loads(call.content)["prompt"]["4"]["inputs"]["text"]
            for call in comfy_transport
            if call.url.path == "/prompt"
        ]
        assert len(prompts) == 2
        assert any(
            "STYLE_A" in item and "cat" in item and "STYLE_B" not in item
            for item in prompts
        )
        assert any(
            "STYLE_B" in item and "dog" in item and "STYLE_A" not in item
            for item in prompts
        )
        assert all("CHANGED" not in item for item in prompts)
        await plugin.on_unload()

    asyncio.run(run())
