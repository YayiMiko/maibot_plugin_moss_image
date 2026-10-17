"""Offline-only tests; real HTTP and model calls are forbidden."""

import io
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
import requests
from PIL import Image

from moss.config import MossConfig
from plugin import MossPlugin


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Live HTTP is forbidden in offline tests")

    original_send = httpx.AsyncClient.send

    async def offline_send(self, *args, **kwargs):
        if not isinstance(self._transport, httpx.MockTransport):
            forbidden()
        return await original_send(self, *args, **kwargs)

    monkeypatch.setattr(requests, "get", forbidden)
    monkeypatch.setattr(requests, "post", forbidden)
    monkeypatch.setattr(httpx.AsyncClient, "send", offline_send)


@pytest.fixture
def png_bytes():
    output = io.BytesIO()
    Image.new("RGB", (16, 24), "white").save(output, format="PNG")
    return output.getvalue()


@pytest.fixture
def plugin(tmp_path):
    p = MossPlugin()
    p._plugin_config_instance = MossConfig()
    p.config.planning.danbooru_enabled = False
    p._ctx = SimpleNamespace(
        paths=SimpleNamespace(
            data_dir=tmp_path / "data", runtime_dir=tmp_path / "runtime"
        ),
        logger=logging.getLogger("test-moss"),
        llm=SimpleNamespace(
            generate=AsyncMock(
                return_value={
                    "success": True,
                    "response": '{"caption":"A white cat sleeping on a windowsill."}',
                }
            )
        ),
        api=SimpleNamespace(
            call=AsyncMock(return_value={"user_id": "bot", "nickname": "MOSS"})
        ),
        send=SimpleNamespace(
            text=AsyncMock(return_value={"sent": True, "message_id": "text"}),
            image=AsyncMock(return_value={"sent": True, "message_id": "image"}),
            forward=AsyncMock(return_value={"sent": True, "message_id": "forward"}),
        ),
    )
    return p


@pytest.fixture
def command():
    return {
        "platform": "qq",
        "stream_id": "stream",
        "group_id": "group",
        "user_id": "user",
        "text": "/moss 白猫睡在窗边",
        "message": {"message_id": "message"},
    }


@pytest.fixture
def comfy_transport(monkeypatch, png_bytes):
    calls = []

    def handler(request):
        calls.append(request)
        path = request.url.path
        if path == "/prompt":
            return httpx.Response(200, json={"prompt_id": "known-id"})
        if path == "/history/known-id":
            return httpx.Response(
                200,
                json={
                    "known-id": {
                        "status": {"status_str": "success"},
                        "outputs": {
                            "18": {
                                "images": [
                                    {
                                        "filename": "image.png",
                                        "type": "output",
                                        "subfolder": "",
                                    }
                                ]
                            }
                        },
                    }
                },
            )
        if path == "/view":
            return httpx.Response(200, content=png_bytes)
        raise AssertionError(f"Unexpected mocked API path: {path}")

    original = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs),
    )
    return calls
