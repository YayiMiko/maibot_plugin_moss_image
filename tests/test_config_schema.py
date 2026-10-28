"""Human-readable config schema and live read-only runtime status."""

import asyncio
import json

from maibot_sdk.config import build_plugin_default_config, generate_plugin_config_schema

from moss.config import MossConfig, Styles
from moss.config_ui import EMPTY_LIBRARY, NOT_LOADED
from moss.oc import OCStore
from moss.styles import StyleStore
from plugin import MossPlugin


def test_sections_use_chinese_titles_and_recommended_order():
    schema = generate_plugin_config_schema(MossConfig)
    sections = schema["sections"]
    assert [
        (name, section["order"])
        for name, section in sections.items()
        if name != "plugin"
    ] == [
        ("connection", 10),
        ("draw", 20),
        ("rendering", 30),
        ("planning", 40),
        ("vision", 50),
        ("styles", 60),
        ("characters", 70),
        ("delivery", 80),
    ]
    assert sections["connection"]["title"] == "连接与权限"
    assert sections["draw"]["title"] == "模板抽卡"
    assert sections["rendering"]["title"] == "生图模型与画幅"
    assert sections["characters"]["title"] == "OC 权限"
    assert sections["delivery"]["title"] == "发送与维护"


def test_every_field_has_chinese_label_description_and_example():
    schema = generate_plugin_config_schema(MossConfig)
    for section_name, section in schema["sections"].items():
        for field_name, field in section["fields"].items():
            assert field["label"] != field_name, (section_name, field_name)
            assert field["description"], (section_name, field_name)
            assert field["example"] is not None, (section_name, field_name)


def test_host_hints_expose_descriptions_and_examples():
    plugin = MossPlugin()
    plugin._plugin_config_instance = MossConfig()
    schema = plugin.get_webui_config_schema()
    for section_name, section in schema["sections"].items():
        for field_name, field in section["fields"].items():
            assert field["hint"], (section_name, field_name)
            assert "示例：" in field["hint"], (section_name, field_name)
            assert field["placeholder"] is not None, (section_name, field_name)


def test_common_fields_are_visible_and_rare_fields_are_hidden():
    schema = generate_plugin_config_schema(MossConfig)["sections"]

    def hidden(section, field):
        return schema[section]["fields"][field]["hidden"]

    assert not hidden("connection", "enabled")
    assert not hidden("connection", "comfyui_base_url")
    assert hidden("connection", "max_pending")
    assert hidden("connection", "generation_timeout")
    assert not hidden("draw", "enabled")
    assert not hidden("draw", "tavily_api_key")
    assert schema["draw"]["fields"]["tavily_api_key"]["ui_type"] == "password"
    assert hidden("draw", "limits")
    assert hidden("rendering", "unet_name")
    assert hidden("rendering", "clip_name")
    assert hidden("rendering", "sampler")
    assert not hidden("rendering", "aspect_ratio")
    assert hidden("planning", "danbooru_enabled")
    assert hidden("styles", "presets")
    assert not hidden("characters", "admin_user_ids")
    assert hidden("delivery", "group_forward_threshold")


def test_legacy_style_presets_are_hidden_and_default_is_empty():
    config = MossConfig()
    assert config.styles.presets == []
    assert config.plugin.config_version == "0.2.0"
    schema = generate_plugin_config_schema(MossConfig)["sections"]
    assert schema["styles"]["fields"]["presets"]["hidden"] is True
    assert schema["plugin"]["fields"]["config_version"]["hidden"] is True


def _loaded_plugin(tmp_path):
    plugin = MossPlugin()
    plugin._plugin_config_instance = MossConfig()
    plugin.styles = StyleStore(tmp_path)
    asyncio.run(plugin.styles.initialize())
    plugin.characters = OCStore(tmp_path)
    asyncio.run(plugin.characters.initialize())
    plugin.jobs = {}
    return plugin


def test_runtime_status_is_live_and_read_only(tmp_path):
    plugin = _loaded_plugin(tmp_path)
    plugin.config.styles.presets = ["千代风格=@artist, flat color"]
    plugin.styles.state["library"]["测试"] = "ink"
    plugin.characters.state["library"]["狐莉"] = {"name": "狐莉"}
    plugin.jobs["task"] = object()

    schema = plugin.get_webui_config_schema()
    assert "plugin" not in schema["sections"]
    section = schema["sections"]["runtime_status"]
    assert section["order"] == 90
    assert section["fields"]["style_library"]["default"] == "千代风格\n测试"
    assert section["fields"]["style_library"]["label"] == "当前风格库（2）"
    assert section["fields"]["character_library"]["default"] == "狐莉"
    assert section["fields"]["active_tasks"]["default"] == 1
    assert section["fields"]["config_version"]["default"] == "0.2.0"
    assert all(field["disabled"] for field in section["fields"].values())

    plugin.styles.state["library"]["新风格"] = "watercolor"
    refreshed = plugin.get_webui_config_schema()["sections"]["runtime_status"]
    assert "新风格" in refreshed["fields"]["style_library"]["default"]


def test_runtime_status_is_safe_before_plugin_load():
    plugin = MossPlugin()
    plugin._plugin_config_instance = MossConfig()
    section = plugin.get_webui_config_schema()["sections"]["runtime_status"]
    assert section["fields"]["style_library"]["default"] == NOT_LOADED
    assert section["fields"]["character_library"]["default"] == NOT_LOADED
    assert section["fields"]["active_tasks"]["default"] == 0


def test_empty_runtime_libraries_are_clear(tmp_path):
    plugin = _loaded_plugin(tmp_path)
    section = plugin.get_webui_config_schema()["sections"]["runtime_status"]
    assert section["fields"]["style_library"]["default"] == EMPTY_LIBRARY
    assert section["fields"]["character_library"]["default"] == EMPTY_LIBRARY


def test_runtime_status_fields_are_not_configuration():
    assert "runtime_status" not in MossConfig.model_fields
    defaults = build_plugin_default_config(MossConfig)
    assert "runtime_status" not in defaults
    config = MossConfig.model_validate(
        {"runtime_status": {"style_library": "not saved", "active_tasks": 3}}
    )
    assert "runtime_status" not in config.model_dump()
    assert json.dumps(config.model_dump()) == json.dumps(MossConfig().model_dump())


def test_legacy_style_import_is_idempotent_and_preserves_live_entries(tmp_path):
    async def run():
        store = StyleStore(tmp_path)
        await store.initialize()
        store.state["library"]["同名"] = "live"
        config = Styles(presets=["同名=legacy", "旧版=legacy"])
        assert await store.import_legacy(config) == 1
        assert store.state["library"] == {"同名": "live", "旧版": "legacy"}
        assert await store.import_legacy(config) == 0
        reloaded = StyleStore(tmp_path)
        await reloaded.initialize()
        assert reloaded.state["library"] == store.state["library"]

    asyncio.run(run())


def test_plugin_load_imports_old_presets_once(plugin):
    plugin.config.styles.presets = ["旧版=legacy"]

    async def run():
        await plugin.on_load()
        assert plugin.styles.state["library"]["旧版"] == "legacy"
        assert plugin.styles.path.is_file()
        await plugin.on_unload()

    asyncio.run(run())
