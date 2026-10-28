"""Local style editing, immutable snapshots and command separation."""

import asyncio
import copy
import json
import threading

import pytest
from pydantic import ValidationError

from moss.commands import HELP, StyleRequest, parse_command
from moss.config import MossConfig, Styles
from moss.styles import StyleStore, parse_style_definition


def test_style_help_is_only_in_the_submenu():
    assert "/moss 风格" in HELP
    assert "/moss 风格 <名称>" not in HELP
    assert "/moss 风格 新建" not in HELP and "/moss 风格 编辑" not in HELP
    assert "关闭" not in HELP


@pytest.mark.parametrize("operation", ["新建", "编辑"])
def test_style_edit_preserves_raw_artist_notation_and_prose(operation):
    text = "@artist name, flat colors，中文说明, A=B"
    action, request = parse_command(
        f"/moss 风格 {operation}\t测试={text}", MossConfig().rendering
    )
    assert action == "style" and request.name == "测试" and request.content == text


@pytest.mark.parametrize(
    "text",
    ["/moss 风格 A=B", "/moss 风格 编辑 A=", "/moss 风格 新建 =B"],
)
def test_invalid_or_removed_style_commands_never_generate(text):
    with pytest.raises(ValueError):
        parse_command(text, MossConfig().rendering)


@pytest.mark.parametrize(
    "value", ["A=", "=B", "A", "bad,name=B", "A=" + "x" * 4097, "A=\x00"]
)
def test_style_definition_limits(value):
    with pytest.raises(ValueError):
        parse_style_definition(value)


def test_configuration_has_no_artist_library_or_age_or_count_defaults():
    config = MossConfig()
    assert config.styles.positive_prefix == "best quality, highres,"
    text = json.dumps(config.styles.model_dump(), ensure_ascii=False)
    assert "12 years old" not in text and "solo" not in text
    assert "artist_presets" not in text
    assert "@yuasa akira" in text
    with pytest.raises(ValidationError):
        Styles(presets=["A=flat", "A=other"])


def test_style_store_preserves_library_and_freezes_snapshots(tmp_path):
    async def run():
        store = StyleStore(tmp_path)
        await store.initialize()
        config = Styles()
        await store.handle(
            StyleRequest("create", "测试", "ink"), "a" * 64, "a" * 24, config
        )
        frozen = await store.snapshot(("测试",), config)
        await store.handle(
            StyleRequest("edit", "测试", "new"), "a" * 64, "b" * 24, config
        )
        assert frozen == ("测试", "ink")
        assert await store.snapshot(("测试",), config) == ("测试", "new")
        assert await store.snapshot((), config) == ("", "")
        reloaded = StyleStore(tmp_path)
        await reloaded.initialize()
        assert await reloaded.snapshot(("测试",), config) == ("测试", "new")

    asyncio.run(run())


def test_style_store_rejects_damage_without_overwriting(tmp_path):
    path = tmp_path / "styles.json"
    path.write_text('{"unknown":1}', encoding="utf-8")
    with pytest.raises(ValueError):
        asyncio.run(StyleStore(tmp_path).initialize())
    assert path.read_text(encoding="utf-8") == '{"unknown":1}'


def test_style_commands_do_not_call_models_or_clear_latest_diagnostic(plugin, command):
    async def run():
        await plugin.on_load()
        diagnostic = plugin.store.data / "last_llm_response.json"
        diagnostic.write_text('{"sentinel":"previous generation"}', encoding="utf-8")
        for index, text in enumerate(
            (
                "/moss 风格",
                "/moss 风格 新建 测试=flat, @artist",
                "/moss 风格 编辑 测试=ink",
            )
        ):
            request = copy.deepcopy(command)
            request["text"] = text
            request["message"]["message_id"] = str(index)
            await plugin.handle_moss(**request)
            await asyncio.gather(*list(plugin.jobs.values()))
        plugin.ctx.llm.generate.assert_not_awaited()
        plugin.ctx.send.image.assert_not_awaited()
        assert (
            diagnostic.read_text(encoding="utf-8")
            == '{"sentinel":"previous generation"}'
        )
        assert await plugin.styles.snapshot(("测试",), plugin.config.styles) == (
            "测试",
            "ink",
        )
        await plugin.on_unload()

    asyncio.run(run())


def test_long_style_list_uses_one_forward_card(plugin, command):
    plugin.config.styles.presets = ["千代风格=" + "visual detail, " * 200]
    command["text"] = "/moss 风格"

    async def run():
        await plugin.on_load()
        await plugin.handle_moss(**command)
        await asyncio.gather(*list(plugin.jobs.values()))
        plugin.ctx.send.forward.assert_awaited_once()
        assert (
            plugin.ctx.send.forward.call_args.kwargs["processed_plain_text"]
            == "[MOSS 风格菜单]"
        )
        plugin.ctx.send.text.assert_not_awaited()
        plugin.ctx.llm.generate.assert_not_awaited()
        await plugin.on_unload()

    asyncio.run(run())


def test_cancelled_style_write_finishes_before_releasing_the_lock(
    tmp_path, monkeypatch
):
    import moss.styles as module

    entered, release = threading.Event(), threading.Event()
    original = module.atomic_write

    def slow_write(*args):
        entered.set()
        assert release.wait(5)
        original(*args)

    monkeypatch.setattr(module, "atomic_write", slow_write)

    async def run():
        store = StyleStore(tmp_path)
        await store.initialize()
        operation = asyncio.create_task(
            store.handle(
                StyleRequest("create", "测试", "ink"), "a" * 64, "a" * 24, Styles()
            )
        )
        try:
            assert await asyncio.to_thread(entered.wait, 5)
            operation.cancel()
            await asyncio.sleep(0)
            assert store.lock.locked()
        finally:
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await operation
        assert store.state["library"]["测试"] == "ink"
        assert (
            json.loads(store.path.read_text(encoding="utf-8"))["library"]["测试"]
            == "ink"
        )

    asyncio.run(run())
