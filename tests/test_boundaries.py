"""Failure boundaries, parallel scopes and conservative persisted state."""

import asyncio
import base64
import copy
import json
import logging
import os
import threading
import time
from types import SimpleNamespace

import httpx
import pytest

from moss.characters import CharacterResolver
from moss.config import MossConfig
from moss.media import MetadataReader
from moss.retention import clean_history
from moss.skill import ROOT, OfficialSkill
from moss.storage import TaskStore, atomic_write


def test_vendor_actual_lookup_and_ttl_cache(monkeypatch):
    resolver = CharacterResolver(logging.getLogger("lookup"))
    module = resolver.module
    calls = []

    def get(url, **kwargs):
        calls.append(url)
        if "/tags.json" in url:
            return SimpleNamespace(
                status_code=200,
                headers={"content-type": "application/json"},
                json=lambda: [
                    {
                        "name": "lumine_(genshin_impact)",
                        "category": 4,
                        "post_count": 100,
                    }
                ],
            )
        return SimpleNamespace(status_code=503)

    monkeypatch.setattr(module.requests, "get", get)
    characters = [{"source_name": "荧", "candidates": ["lumine_(genshin_impact)"]}]
    first = resolver._lookup(characters)
    count = len(calls)
    second = resolver._lookup(characters)
    assert first[0]["status"] == second[0]["status"] == "verified"
    assert second[0]["canonical_tag"] == "lumine_(genshin_impact)"
    assert len(calls) == count


@pytest.mark.parametrize(
    "category,deprecated,expected",
    [(0, False, "degraded"), (4, True, "unresolved"), (4, False, "verified")],
)
def test_lookup_evidence_categories(monkeypatch, category, deprecated, expected):
    resolver = CharacterResolver(logging.getLogger("lookup"))
    module = resolver.module
    monkeypatch.setattr(
        module,
        "_resolve_evidence_candidates",
        lambda *a, **kw: (
            module.TagRecord(
                "lumine_(genshin_impact)", category, 100, deprecated, "test"
            ),
            ("test",),
        ),
    )
    monkeypatch.setattr(
        module, "_fetch_stable_identity_tags", lambda *a, **kw: ("blonde_hair",)
    )
    result = resolver._lookup(
        [{"source_name": "荧", "candidates": ["lumine_(genshin_impact)"]}]
    )[0]
    assert result["status"] == expected
    assert ("appearance_anchors" in result) == (expected == "verified")


def test_lookup_rejects_popular_namesake_from_other_work(monkeypatch):
    resolver = CharacterResolver(logging.getLogger("lookup"))
    module = resolver.module
    monkeypatch.setattr(
        module,
        "_resolve_evidence_candidates",
        lambda *a, **kw: (
            module.TagRecord("pandora_(unrelated_game)", 4, 999999),
            ("wrong work",),
        ),
    )
    result = resolver._lookup(
        [{"source_name": "潘多拉", "candidates": ["pandora_(re:zero)"]}]
    )[0]
    assert result["status"] == "unresolved"
    assert "canonical_tag" not in result


def test_lookup_budget_keeps_slot_until_blocking_work_really_finishes(monkeypatch):
    resolver = CharacterResolver(logging.getLogger("lookup"))
    release = threading.Event()

    def blocking(characters):
        release.wait(timeout=2)
        return []

    monkeypatch.setattr(resolver, "_lookup", blocking)

    async def run():
        try:
            answer = await resolver.resolve(
                [{"source_name": "角色", "candidates": ["name_(work)"]}], 0.01
            )
            assert answer[0]["status"] == "source_unavailable"
            assert resolver.slots._value == 1 and len(resolver.pending) == 1
        finally:
            release.set()
            await asyncio.gather(*list(resolver.pending))
            await asyncio.sleep(0)
        assert resolver.slots._value == 2

    asyncio.run(run())


def test_config_snapshot_and_two_conversations_are_isolated(
    plugin, command, comfy_transport
):
    async def run():
        await plugin.on_load()
        first = copy.deepcopy(command)
        first["text"] = "/moss 规划 FIRST --尺寸 1024x1024"
        plugin.ctx.llm.generate.side_effect = lambda messages, **kw: {
            "success": True,
            "response": json.dumps(
                {"caption": json.loads(messages[1]["content"])["request"]}
            ),
        }
        await plugin.handle_moss(**first)
        plugin.config.rendering.negative_prompt = "NEW NEGATIVE"
        second = copy.deepcopy(first)
        second.update(
            stream_id="another-stream",
            user_id="another-user",
            text="/moss 规划 SECOND --比例 16:9",
        )
        await plugin.handle_moss(**second)
        await asyncio.gather(*list(plugin.jobs.values()))
        graphs = [
            json.loads(r.content)["prompt"]
            for r in comfy_transport
            if r.url.path == "/prompt"
        ]
        assert len(graphs) == 2
        assert graphs[0]["5"]["inputs"]["text"] != "NEW NEGATIVE"
        assert graphs[1]["5"]["inputs"]["text"] == "NEW NEGATIVE"
        assert graphs[0]["4"]["inputs"]["text"] == "FIRST"
        assert graphs[1]["4"]["inputs"]["text"] == "SECOND"
        records = [
            json.loads(p.read_text(encoding="utf-8"))
            for p in plugin.store.records.glob("*.json")
        ]
        assert len({r["scope"] for r in records}) == 2
        assert len({r["output"] for r in records}) == 2
        assert {call.args[1] for call in plugin.ctx.send.image.await_args_list} == {
            "stream",
            "another-stream",
        }
        await plugin.on_unload()

    asyncio.run(run())


def test_leading_bot_mention_requires_real_components(plugin, command, comfy_transport):
    async def run():
        await plugin.on_load()
        command["text"] = "@renamed-bot /moss 规划 cup"
        command["message"]["raw_message"] = [
            {"type": "at", "data": {"target_user_id": "bot"}},
            {"type": "text", "data": "/moss 规划 cup"},
        ]
        assert await plugin.handle_moss(**command) == (True, None, 2)
        await asyncio.gather(*list(plugin.jobs.values()))
        plugin.ctx.send.image.assert_awaited_once()
        command["message"]["raw_message"][0]["data"]["target_user_id"] = "another-user"
        assert await plugin.handle_moss(**command) == (False, None, 0)
        await plugin.on_unload()

    asyncio.run(run())


def test_metadata_command_uses_original_only_and_no_llm(plugin, command, png_bytes):
    command["text"] = "/moss 解析法术"
    plugin.ctx.api.call.return_value = {
        "group_id": "group",
        "message": [
            {
                "type": "image",
                "data": {"url": "base64://" + base64.b64encode(png_bytes).decode()},
            }
        ],
    }

    async def run():
        await plugin.on_load()
        await plugin.handle_moss(**command)
        await asyncio.gather(*list(plugin.jobs.values()))
        plugin.ctx.llm.generate.assert_not_awaited()
        plugin.ctx.send.image.assert_not_awaited()
        assert "不会自动反推" in plugin.ctx.send.text.call_args.args[0]
        await plugin.on_unload()

    asyncio.run(run())


def test_cache_root_is_explicit_and_file_uri_works(plugin, tmp_path, png_bytes):
    image = tmp_path / "cache" / "original.png"
    image.parent.mkdir()
    image.write_bytes(png_bytes)
    reader = MetadataReader(plugin.ctx, [str(image.parent)])
    assert asyncio.run(reader.read_bytes(image.as_uri())) == png_bytes
    with pytest.raises(ValueError):
        asyncio.run(MetadataReader(plugin.ctx, []).read_bytes(str(image)))


@pytest.mark.parametrize(
    "status,submitted,delivery,remote,expected",
    [
        ("queued", False, False, "", "interrupted"),
        ("submitting", True, False, "", "remote_unknown"),
        ("generating", True, False, "", "remote_unknown"),
        ("sending", True, True, "completed", "delivery_unknown"),
        ("generated", True, False, "completed", "interrupted"),
        ("sent", True, True, "completed", "sent"),
    ],
)
def test_reload_classifies_without_recovery(
    tmp_path, status, submitted, delivery, remote, expected
):
    data, runtime = tmp_path / "data", tmp_path / "runtime"
    path = data / "tasks" / ("a" * 24 + ".json")
    atomic_write(
        path,
        {
            "task_id": "a" * 24,
            "status": status,
            "submission_started": submitted,
            "delivery_started": delivery,
            "remote_state": remote,
        },
    )
    store = TaskStore(data, runtime, logging.getLogger("reload"))
    asyncio.run(store.initialize())
    assert json.loads(path.read_text(encoding="utf-8"))["status"] == expected


@pytest.mark.parametrize(
    "state,active,expected",
    [
        ("sent", False, True),
        ("completed", True, False),
        ("remote_unknown", False, False),
        ("generating", False, False),
        ("delivery_unknown", False, True),
    ],
)
def test_retention_only_deletes_expired_terminal_owned_data(
    tmp_path, state, active, expected
):
    records, runtime = tmp_path / "records", tmp_path / "runtime"
    task_id = "a" * 24
    path, directory = records / f"{task_id}.json", runtime / task_id
    old = time.time() - 3 * 86400
    atomic_write(
        path,
        {
            "task_id": task_id,
            "created_at": old,
            "status": state,
            "outputs": [str(tmp_path / "unrelated")],
        },
    )
    output = directory / "outputs" / "image.png"
    output.parent.mkdir(parents=True)
    output.write_bytes(b"test")
    unrelated = tmp_path / "unrelated"
    unrelated.write_text("keep", encoding="utf-8")
    for target in (path, output, output.parent, directory):
        os.utime(target, (old, old))
    removed = clean_history(
        records,
        runtime,
        1,
        {task_id} if active else set(),
        logging.getLogger("retention"),
    )
    assert removed == int(expected)
    assert path.exists() != expected and directory.exists() != expected
    assert unrelated.read_text(encoding="utf-8") == "keep"


def test_required_sdk_lifecycle_callbacks_are_explicit():
    from maibot_sdk import MaiBotPlugin

    from plugin import MossPlugin

    for name in ("on_load", "on_unload", "on_config_update"):
        assert getattr(MossPlugin, name) is not getattr(MaiBotPlugin, name)


def test_config_update_does_not_restart_tasks_or_call_services(plugin):
    async def run():
        await plugin.on_load()
        runner, store, jobs = plugin.runner, plugin.store, plugin.jobs
        await plugin.on_config_update("plugin", {"planning": {}}, "updated")
        assert plugin.runner is runner and plugin.store is store
        assert plugin.jobs is jobs
        plugin.ctx.llm.generate.assert_not_awaited()
        plugin.ctx.send.image.assert_not_awaited()
        plugin.ctx.send.text.assert_not_awaited()
        await plugin.on_unload()

    asyncio.run(run())


def test_manifest_ci_and_skill_integrity_agree():
    manifest = json.loads((ROOT / "_manifest.json").read_text(encoding="utf-8"))
    assert manifest["sdk"]["min_version"] == "2.8.2"
    assert manifest["sdk"]["max_version"] == "2.13.99"
    package = __import__("tomllib").loads(
        (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    )
    assert manifest["version"] == package["project"]["version"] == "0.2.0"
    assert set(manifest["capabilities"]) == {
        "llm.generate",
        "send.text",
        "send.image",
        "send.forward",
        "api.call",
    }
    ci = (ROOT / ".github/workflows/checks.yml").read_text(encoding="utf-8")
    assert "2.8.2" not in ci and "maibot-plugin-sdk==2.13.0" in ci
    config = MossConfig.model_validate(
        __import__("tomllib").loads(
            (ROOT / "docs/config.example.toml").read_text(encoding="utf-8")
        )
    )
    assert config.rendering.clip_name == "qwen3.5_9b_int8_convrot.safetensors"
    assert OfficialSkill().revision == "c1355e6b1986dfe8fba3c0455783a05899212342"


def test_http_400_is_known_failure_not_unknown(plugin, command, monkeypatch):
    original = httpx.AsyncClient
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(400, json={"error": "missing node"})

    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kw: original(transport=httpx.MockTransport(handler), **kw),
    )

    async def run():
        await plugin.on_load()
        await plugin.handle_moss(**command)
        await asyncio.gather(*list(plugin.jobs.values()))
        record = json.loads(
            next(plugin.store.records.glob("*.json")).read_text(encoding="utf-8")
        )
        assert record["status"] == "generation_failed" and len(calls) == 1
        plugin.ctx.send.image.assert_not_awaited()
        await plugin.on_unload()

    asyncio.run(run())
