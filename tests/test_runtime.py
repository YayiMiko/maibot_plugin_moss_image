"""Real plugin orchestration against only mocked LLM/ComfyUI/QQ transports."""

import asyncio
import base64
import io
import json
from pathlib import Path

import httpx
import pytest
from PIL import Image
from PIL.PngImagePlugin import PngInfo

from moss.comfy import ComfyClient
from moss.delivery import send_result
from moss.media import MetadataReader, extract_metadata
from moss.storage import atomic_write


def test_complete_generation_and_request_dedup(plugin, command, comfy_transport):
    async def run():
        await plugin.on_load()
        assert await plugin.handle_moss(**command) == (True, None, 2)
        await asyncio.gather(*list(plugin.jobs.values()))
        await plugin.handle_moss(**command)
        await asyncio.sleep(0)
        assert sum(r.url.path == "/prompt" for r in comfy_transport) == 1
        plugin.ctx.send.image.assert_awaited_once()
        plugin.ctx.send.text.assert_not_awaited()
        plugin.ctx.api.call.assert_not_awaited()
        record = json.loads(
            next(plugin.store.records.glob("*.json")).read_text(encoding="utf-8")
        )
        assert record["status"] == "sent"
        assert record["delivery"]["message_id"] == "image"
        directory = plugin.store.runtime / record["task_id"]
        assert (directory / "draft.json").exists()
        assert (
            (directory / "prompt.txt")
            .read_text(encoding="utf-8")
            .startswith("A white cat")
        )
        assert (directory / "workflow.json").exists()
        assert Path(record["output"]).is_file()
        await plugin.on_unload()

    asyncio.run(run())


@pytest.mark.parametrize(
    "receipt",
    [
        True,
        False,
        {"sent": True},
        {"sent": True, "message_id": None},
        {"sent": True, "message_id": " "},
        {"sent": True, "message_id": True},
        {"sent": True, "message_id": {"not": "a platform ID"}},
        {"sent": False, "message_id": "bad"},
    ],
)
def test_image_requires_platform_receipt_without_resend(
    plugin, command, comfy_transport, receipt
):
    plugin.ctx.send.image.return_value = receipt

    async def run():
        await plugin.on_load()
        await plugin.handle_moss(**command)
        await asyncio.gather(*list(plugin.jobs.values()))
        record = json.loads(
            next(plugin.store.records.glob("*.json")).read_text(encoding="utf-8")
        )
        assert record["status"] == "delivery_unknown"
        plugin.ctx.send.image.assert_awaited_once()
        plugin.ctx.send.text.assert_awaited_once()
        assert "没有自动重发" in plugin.ctx.send.text.call_args.args[0]
        await plugin.on_unload()

    asyncio.run(run())


def test_raw_with_bad_attached_image_never_reads_it(plugin, command, comfy_transport):
    command["text"] = "[image] /moss 无优化 A cup."
    command["message"]["reply_to"] = "expired-image"
    plugin.ctx.api.call.side_effect = AssertionError(
        "Raw generation must not read images"
    )

    async def run():
        await plugin.on_load()
        await plugin.handle_moss(**command)
        await asyncio.gather(*list(plugin.jobs.values()))
        plugin.ctx.llm.generate.assert_not_awaited()
        plugin.ctx.api.call.assert_not_awaited()
        payload = json.loads(
            next(r.content for r in comfy_transport if r.url.path == "/prompt")
        )
        assert payload["prompt"]["4"]["inputs"]["text"] == "A cup."
        diagnostic = json.loads(
            (plugin.store.data / "last_llm_response.json").read_text(encoding="utf-8")
        )
        assert diagnostic["calls"] == []
        await plugin.on_unload()

    asyncio.run(run())


def test_refusal_does_not_submit_or_expose_raw_provider_reply(
    plugin, command, comfy_transport
):
    plugin.ctx.llm.generate.return_value = {
        "success": True,
        "blocked": True,
        "response": "private refusal text",
    }

    async def run():
        await plugin.on_load()
        await plugin.handle_moss(**command)
        await asyncio.gather(*list(plugin.jobs.values()))
        assert not comfy_transport
        plugin.ctx.send.image.assert_not_awaited()
        assert "private refusal" not in plugin.ctx.send.text.call_args.args[0]
        diagnostic = json.loads(
            (plugin.store.data / "last_llm_response.json").read_text(encoding="utf-8")
        )
        assert diagnostic["calls"][0]["response"] == "private refusal text"
        await plugin.on_unload()

    asyncio.run(run())


def test_submission_ack_timeout_is_unknown_and_never_retried(
    plugin, command, monkeypatch
):
    calls = []

    def handler(request):
        calls.append(request)
        raise httpx.ReadTimeout("private address", request=request)

    original = httpx.AsyncClient
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
        assert record["status"] == "remote_unknown" and len(calls) == 1
        assert "private address" not in plugin.ctx.send.text.call_args.args[0]
        await plugin.on_unload()

    asyncio.run(run())


def test_cancel_does_not_interrupt_shared_comfyui(plugin, command, monkeypatch):
    entered = None

    async def generate(self, graph, record, store, directory):
        record.update(
            status="generating", submission_started=True, prompt_id="already-submitted"
        )
        await store.save(record)
        entered.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(ComfyClient, "generate", generate)

    async def run():
        nonlocal entered
        entered = asyncio.Event()
        await plugin.on_load()
        await plugin.handle_moss(**command)
        await entered.wait()
        await plugin.on_unload()
        record = json.loads(
            next(plugin.store.records.glob("*.json")).read_text(encoding="utf-8")
        )
        assert record["status"] == "remote_unknown"
        plugin.ctx.send.image.assert_not_awaited()
        plugin.ctx.api.call.assert_not_awaited()

    asyncio.run(run())


def test_platform_permissions_help_and_removed_commands(plugin, command):
    async def run():
        await plugin.on_load()
        for text in ("请用 /moss cup", "/mossx cup", "@someone /moss cup"):
            command["text"] = text
            assert await plugin.handle_moss(**command) == (False, None, 0)
        command["text"] = "/moss 状态"
        await plugin.handle_moss(**command)
        assert "首版不提供" in plugin.ctx.send.text.call_args.args[0]
        command["text"] = "/moss"
        await plugin.handle_moss(**command)
        help_text = plugin.ctx.send.text.call_args.args[0]
        assert "/moss 布局" in help_text and "查看角色" not in help_text
        command["text"] = "/moss cup"
        plugin.config.connection.allowed_sender_ids = ["other-user"]
        await plugin.handle_moss(**command)
        assert not plugin.jobs
        plugin.ctx.llm.generate.assert_not_awaited()
        await plugin.on_unload()

    asyncio.run(run())


def test_metadata_follows_sampler_links_and_keeps_layout_text():
    output = io.BytesIO()
    info = PngInfo()
    info.add_text(
        "prompt",
        json.dumps(
            {
                "neg": {"class_type": "CLIPTextEncode", "inputs": {"text": "bad"}},
                "pos": {
                    "class_type": "CLIPTextEncode",
                    "inputs": {"text": '{"items":[{"text":"你好"}]}'},
                },
                "sample": {
                    "class_type": "KSampler",
                    "inputs": {"positive": ["pos", 0], "negative": ["neg", 0]},
                },
            },
            ensure_ascii=False,
        ),
    )
    Image.new("RGB", (16, 24)).save(output, format="PNG", pnginfo=info)
    parts = extract_metadata(output.getvalue())
    assert "你好" in parts[1] and "bad" in parts[2]
    assert "16x24" in parts[0]


@pytest.mark.parametrize("cross_group", [True, False])
def test_cross_conversation_quotes_are_rejected(plugin, png_bytes, cross_group):
    current = {
        "group_id": "group",
        "message_type": "private",
        "sender": {"user_id": "user"},
        "message": [{"type": "reply", "data": {"id": "quote"}}],
    }
    quoted = {
        "group_id": "other",
        "message_type": "private",
        "user_id": "someone-else",
        "sender": {"user_id": "bot"},
        "message": [
            {
                "type": "image",
                "data": {"url": "base64://" + base64.b64encode(png_bytes).decode()},
            }
        ],
    }
    plugin.ctx.api.call.side_effect = [current, quoted, {"user_id": "bot"}]
    request = {
        "message_id": "message",
        "user_id": "user",
        "group_id": "group" if cross_group else "",
    }
    with pytest.raises(ValueError):
        asyncio.run(MetadataReader(plugin.ctx, []).resolve(request))


@pytest.mark.parametrize(
    "reference",
    [
        "https://example.com/a.png",
        "http://127.0.0.1/a.png",
        "https://qpic.cn.evil.invalid/a.png",
        "https://qpic.cn:8188/a.png",
        "relative.png",
    ],
)
def test_metadata_resource_boundaries(plugin, reference):
    with pytest.raises((ValueError, OSError)):
        asyncio.run(MetadataReader(plugin.ctx, []).read_bytes(reference))


@pytest.mark.parametrize("format", ["PNG", "JPEG", "WEBP", "GIF"])
def test_metadata_keeps_original_bytes(plugin, format):
    buffer = io.BytesIO()
    Image.new("RGB", (16, 24)).save(buffer, format=format)
    original = buffer.getvalue()
    result = asyncio.run(
        MetadataReader(plugin.ctx, []).read_bytes(
            "base64://" + base64.b64encode(original).decode()
        )
    )
    assert result == original


def test_long_group_metadata_uses_one_forward_card(plugin):
    async def run():
        await plugin.on_load()
        record = await plugin.store.create("a" * 24, "scope", "metadata")
        assert await send_result(
            plugin.ctx,
            "stream",
            "group",
            record,
            plugin.store,
            plugin.config.delivery,
            parts=["原文" * 3000],
        )
        plugin.ctx.send.forward.assert_awaited_once()
        plugin.ctx.send.text.assert_not_awaited()
        nodes = plugin.ctx.send.forward.call_args.args[0]
        assert "".join(n["segments"][0]["content"] for n in nodes) == "原文" * 3000
        assert all(n["user_id"] == "bot" for n in nodes)
        await plugin.on_unload()

    asyncio.run(run())


def test_latest_llm_ignores_late_old_task_and_raw_clears_it(plugin):
    async def run():
        await plugin.on_load()
        first = await plugin.store.create("a" * 24, "a-scope", "generate")
        second = await plugin.store.create("b" * 24, "b-scope", "generate")
        await plugin.store.begin_llm(first)
        await plugin.store.append_llm(first["task_id"], "draft", {"response": "old"})
        await plugin.store.begin_llm(second)
        await plugin.store.append_llm(first["task_id"], "draft", {"response": "late"})
        saved = json.loads(
            (plugin.store.data / "last_llm_response.json").read_text(encoding="utf-8")
        )
        assert saved["task_id"] == second["task_id"] and saved["calls"] == []
        await plugin.on_unload()

    asyncio.run(run())


def test_atomic_storage_replaces_without_leftover_temp(tmp_path):
    path = tmp_path / "record.json"
    atomic_write(path, {"text": "你好"})
    atomic_write(path, {"text": "再见"})
    assert json.loads(path.read_text(encoding="utf-8")) == {"text": "再见"}
    assert list(tmp_path.iterdir()) == [path]
