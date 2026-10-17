"""Read explicit same-conversation QQ images, preserving their original metadata."""

import asyncio
import base64
import io
import json
import os
import re
from pathlib import Path
from urllib.parse import unquote, urlparse

import httpx
from PIL import Image

from .comfy import validate_image

MAX_BYTES = 32 * 1024 * 1024


class MultipleImagesError(ValueError):
    """Require an explicit single-image target instead of silently picking one."""


class MetadataReader:
    """Resolve only this message and its explicit quote, never a latest image."""

    def __init__(self, ctx, roots: list[str]):
        self.ctx = ctx
        self.roots = [Path(root).resolve() for root in roots]
        if any(len(root.parts) <= 1 for root in self.roots):
            raise ValueError("QQ cache roots cannot be filesystem roots")

    async def read_bytes(self, reference: str) -> bytes:
        """Download a bounded QQ HTTPS resource or an explicitly allowed cache file.

        Args:
            reference: An adapter-provided image URL, cache path or original bytes.

        Returns:
            Verified original image bytes, without metadata-destroying reencoding.

        Raises:
            ValueError: The resource, path, container or size is not permitted.
        """
        if reference.startswith("base64://"):
            if len(reference) > MAX_BYTES * 4 // 3 + 32:
                raise ValueError("Image too large")
            content = await asyncio.to_thread(
                base64.b64decode, reference[9:], validate=True
            )
        elif reference.startswith("https://"):
            url = urlparse(reference)
            host = url.hostname or ""
            if (
                url.username
                or url.password
                or url.port not in {None, 443}
                or not any(
                    host == suffix or host.endswith("." + suffix)
                    for suffix in ("qpic.cn", "qq.com", "qq.com.cn")
                )
            ):
                raise ValueError("Not an allowed QQ image URL")
            async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
                chunks, count = [], 0
                async with client.stream("GET", reference) as response:
                    response.raise_for_status()
                    async for chunk in response.aiter_bytes():
                        count += len(chunk)
                        if count > MAX_BYTES:
                            raise ValueError("Image too large")
                        chunks.append(chunk)
                content = b"".join(chunks)
        else:
            if reference.startswith("file://"):
                uri = urlparse(reference)
                if uri.netloc not in {"", "localhost"}:
                    raise ValueError("Remote file URIs are not allowed")
                reference = unquote(uri.path)
                if os.name == "nt" and re.match(r"^/[a-zA-Z]:/", reference):
                    reference = reference[1:]
            path = Path(reference)
            if not path.is_absolute() or any(
                p.is_symlink() or p.is_junction() for p in (path, *path.parents)
            ):
                raise ValueError("Invalid cache path")
            path = path.resolve(strict=True)
            if (
                not any(path.is_relative_to(root) for root in self.roots)
                or path.stat().st_size > MAX_BYTES
            ):
                raise ValueError("Cache path outside allowed roots")
            content = await asyncio.to_thread(path.read_bytes)
        if len(content) > MAX_BYTES:
            raise ValueError("Image too large")
        await asyncio.to_thread(validate_image, content)
        return content

    async def resolve(self, request: dict, *, single_only: bool = False) -> bytes:
        """Authorize current/quoted messages before reading any image bytes.

        Args:
            request: Current message ID, group/user IDs and optional explicit reply.
            single_only: Reject multiple pictures in the selected source message.

        Returns:
            Original bytes of the first quoted image, or the attached image.

        Raises:
            ValueError: Missing image, cross-conversation quote or unreadable input.
        """
        current = await self.ctx.api.call(
            "adapter.napcat.message.get_msg",
            version="1",
            message_id=request["message_id"],
        )
        messages = [current]
        if not isinstance(current, dict):
            raise ValueError("Message unavailable")
        segments = current.get("message") or []
        if not isinstance(segments, list):
            raise ValueError("Invalid message segments")
        reply = next(
            (
                str(s.get("data", {}).get("id"))
                for s in segments
                if isinstance(s, dict)
                and s.get("type") == "reply"
                and isinstance(s.get("data"), dict)
                and s["data"].get("id")
            ),
            None,
        ) or request.get("reply_to")
        if reply:
            quoted = await self.ctx.api.call(
                "adapter.napcat.message.get_msg", version="1", message_id=str(reply)
            )
            if not isinstance(quoted, dict):
                raise ValueError("Quoted message unavailable")
            messages.insert(0, quoted)
        bot_id = ""
        if not request["group_id"]:
            login = await self.ctx.api.call(
                "adapter.napcat.action.call_data",
                version="1",
                action_name="get_login_info",
                params={},
            )
            bot_id = str((login or {}).get("user_id") or "")
        for message in messages:
            if request["group_id"]:
                if str(message.get("group_id") or "") != request["group_id"]:
                    raise ValueError("Image message belongs to another group")
            else:
                sender = str(message.get("sender", {}).get("user_id") or "")
                if (
                    message.get("message_type") != "private"
                    or sender not in {request["user_id"], bot_id}
                    or (
                        sender == bot_id
                        and str(message.get("user_id") or "") != request["user_id"]
                    )
                ):
                    raise ValueError(
                        "Image message belongs to another private conversation"
                    )
        for message in messages:
            if (
                single_only
                and sum(
                    isinstance(segment, dict) and segment.get("type") == "image"
                    for segment in message.get("message", [])
                )
                > 1
            ):
                raise MultipleImagesError("Multiple explicit images")
            for segment in message.get("message", []):
                if (
                    not isinstance(segment, dict)
                    or segment.get("type") != "image"
                    or not isinstance(segment.get("data"), dict)
                ):
                    continue
                data = segment["data"]
                detail = {}
                if data.get("file"):
                    try:
                        result = await self.ctx.api.call(
                            "adapter.napcat.file.get_image",
                            version="1",
                            params={"file": data["file"]},
                        )
                        if isinstance(result, dict):
                            detail = result.get("data", result) or {}
                    except Exception:
                        self.ctx.logger.debug("MOSS original cache lookup unavailable")
                for candidate in (
                    detail.get("file"),
                    detail.get("url"),
                    data.get("url"),
                    data.get("file"),
                ):
                    if not isinstance(candidate, str) or not candidate:
                        continue
                    try:
                        return await self.read_bytes(candidate)
                    except (ValueError, OSError, httpx.HTTPError):
                        continue
                # An unreadable explicit quote must not be substituted by another image.
                raise ValueError("Explicit image unavailable")
        raise ValueError("No explicit image")


def extract_metadata(content: bytes) -> list[str]:
    """Extract only prompts and canvas, never model paths or a full workflow."""
    with Image.open(io.BytesIO(content)) as image:
        width, height = image.size
        info = dict(image.info)
    positive, negative, kind = "", "", "未识别到生成信息"
    for key in ("prompt", "workflow"):
        try:
            graph = json.loads(info.get(key, ""))
        except (ValueError, TypeError):
            continue
        if not isinstance(graph, dict):
            continue
        sampler = next(
            (
                node
                for node in graph.values()
                if isinstance(node, dict)
                and node.get("class_type") in {"KSampler", "KSamplerAdvanced"}
            ),
            None,
        )
        if not sampler:
            continue
        values = []
        for branch in ("positive", "negative"):
            pending, seen, texts = [sampler.get("inputs", {}).get(branch)], set(), []
            while pending:
                link = pending.pop()
                if not isinstance(link, list) or len(link) != 2 or str(link[0]) in seen:
                    continue
                seen.add(str(link[0]))
                node = graph.get(str(link[0]), {})
                inputs = node.get("inputs", {})
                if "TextEncode" in str(node.get("class_type", "")) and isinstance(
                    inputs.get("text"), str
                ):
                    texts.append(inputs["text"])
                else:
                    pending.extend(
                        value
                        for value in inputs.values()
                        if isinstance(value, list) and len(value) == 2
                    )
            values.append("\n".join(texts))
        positive, negative, kind = *values, "ComfyUI"
        break
    if not positive:
        parameters = info.get("parameters", info.get("Parameters"))
        if isinstance(parameters, str) and parameters.strip():
            before_steps = re.split(r"\nSteps:\s*", parameters, maxsplit=1, flags=re.I)[
                0
            ]
            pieces = re.split(
                r"\nNegative prompt:\s*", before_steps, maxsplit=1, flags=re.I
            )
            positive, negative, kind = (
                pieces[0],
                pieces[1] if len(pieces) > 1 else "",
                "WebUI",
            )
    if not positive:
        for key in ("Comment", "comment", "Description", "description"):
            try:
                data = json.loads(info.get(key, ""))
            except (ValueError, TypeError):
                continue
            if isinstance(data, dict) and isinstance(data.get("prompt"), str):
                positive, negative, kind = (
                    data["prompt"],
                    str(data.get("uc") or ""),
                    "JSON",
                )
                break
    return [
        f"法术解析结果：\n格式：{kind}\n尺寸：{width}x{height}",
        "正面提示词：\n" + (positive or "图片未包含可读取的提示词；不会自动反推。"),
        "负面提示词：\n" + (negative or "无"),
    ]
