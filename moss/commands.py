"""Explicit command grammar, readable help and preplanning canvas resolution."""

import math
import re
from dataclasses import dataclass
from typing import Literal

from .styles import parse_style_definition

COMMAND_PATTERN = r"(?i)^\s*(?:(?:\[image\]|@[^\r\n]+?)\s*)*(?P<command>/moss(?:\s|$))"
HELP = (
    "/moss 生成 <要求>：原文直出＋前缀、风格、角色校正\n"
    "/moss 规划 <要求>：官方 Caption 扩写生图\n"
    "/moss 布局 <要求>：官方扩写＋布局规划生图\n"
    "/moss 风格：查看、选择、新建或编辑风格\n"
    "/moss 解析法术：附图/引用，读取原始提示词\n"
    "/moss 反推：附图/引用单图，视觉推测提示词，非原词\n"
    "生图画幅：--尺寸 1024x1024（宽×高像素）或 --比例 3:4"
)
REMOVED = {
    "描述",
    "状态",
    "诊断",
    "调试",
    "调试状态",
    "查看角色",
    "添加角色",
    "删除角色",
    "查看风格",
    "核对任务",
    "恢复任务",
    "漫画",
    "表情包",
    "帮助",
    "help",
    "无优化",
}


@dataclass(frozen=True)
class ImageRequest:
    """Stable input boundary for future comic/meme planning adapters."""

    prompt: str
    width: int
    height: int
    mode: Literal["generate", "caption", "layout"] = "caption"
    task_type: Literal["illustration", "comic_page", "meme"] = "illustration"
    positive_prefix: str = ""
    style_name: str = ""
    style_prompt: str = ""
    oc_context: dict | None = None


@dataclass(frozen=True)
class StyleRequest:
    """A local preset operation, never an image-generation request."""

    operation: Literal["list", "select", "edit", "create"]
    name: str = ""
    content: str = ""


def parse_command(
    text: str, rendering
) -> tuple[str, ImageRequest | StyleRequest | None]:
    """Parse explicit modes and resolve dimensions before any LLM call.

    Args:
        text: Command text starting with /moss, with image placeholders allowed.
        rendering: Detached rendering configuration.

    Returns:
        Action and an optional immutable image request.

    Raises:
        ValueError: The command or its explicit canvas cannot be honored.
    """
    body = re.sub(r"(?i)^\s*(?:\[image\]\s*)*/moss(?=\s|$)", "", text).strip()
    if body == text.strip():
        raise ValueError("不是有效的 /moss 指令。")
    if not body:
        return "help", None
    keyword = body.split(maxsplit=1)[0]
    if keyword == "风格":
        arguments = body[len(keyword) :].strip()
        if not arguments:
            return "style", StyleRequest("list")
        parts = arguments.split(maxsplit=1)
        operation = parts[0]
        value = parts[1] if len(parts) > 1 else ""
        if operation in {"编辑", "新建"}:
            name, content = parse_style_definition(value.strip())
            return "style", StyleRequest(
                "edit" if operation == "编辑" else "create", name, content
            )
        if arguments == "关闭":
            raise ValueError("没有风格关闭指令，请使用 /moss 风格 查看已有风格。")
        if "=" in arguments:
            raise ValueError("修改风格请使用 /moss 风格 编辑 名称=完整内容。")
        name, _ = parse_style_definition(arguments + "=selection")
        return "style", StyleRequest("select", name)
    if keyword in REMOVED:
        raise ValueError("该指令已移除或未开放，请使用 /moss 查看可用写法。")
    if keyword == "反推":
        if body != "反推":
            raise ValueError("反推不接受文字参数，请附图或引用单张图片。")
        return "reverse", None
    if body == "解析法术":
        return "metadata", None
    if keyword == "解析法术":
        raise ValueError("解析法术不接受文字参数，请附图或引用图片。")
    modes = {"生成": "generate", "规划": "caption", "布局": "layout"}
    if keyword not in modes:
        raise ValueError("请使用 /moss 生成 <要求> 或 /moss 规划 <要求>。")
    mode = modes[keyword]
    body = body[len(keyword) :].strip()
    # Mask literal text without changing offsets into the original input.
    masked = list(body)
    quote, escaped = "", False
    for index, character in enumerate(body):
        if quote:
            masked[index] = " "
            if escaped:
                escaped = False
            elif character == "\\" and quote == '"':
                escaped = True
            elif character == quote:
                quote = ""
        elif character in {'"', "“", "「", "『"}:
            quote = {'"': '"', "“": "”", "「": "」", "『": "』"}[character]
            masked[index] = " "
    flags_text = "".join(masked)
    size_matches = list(
        re.finditer(r"(?<!\S)--尺寸\s+(\d+)\s*[xX×]\s*(\d+)(?=\s|$)", flags_text)
    )
    ratio_matches = list(
        re.finditer(r"(?<!\S)--比例\s+(\d+):(\d+)(?=\s|$)", flags_text)
    )
    if len(size_matches) + len(ratio_matches) > 1:
        raise ValueError("每次只能指定一个尺寸或比例。")
    if ("--尺寸" in flags_text and not size_matches) or (
        "--比例" in flags_text and not ratio_matches
    ):
        raise ValueError("尺寸写法为 --尺寸 1024x1024，比例写法为 --比例 3:4。")
    if size_matches:
        match = size_matches[0]
        width, height = map(int, match.groups())
        if (
            min(width, height) < 256
            or max(width, height) > 8192
            or width % 16
            or height % 16
        ):
            raise ValueError("宽高须为 256～8192 内的 16 倍数；不会自动修改明确尺寸。")
    else:
        a, b = map(
            int,
            ratio_matches[0].groups()
            if ratio_matches
            else rendering.aspect_ratio.split(":"),
        )
        if min(a, b) < 1 or max(a, b) > 100 or not 1 / 8 <= a / b <= 8:
            raise ValueError("比例无效或过于极端。")
        width = max(
            256, round(math.sqrt(rendering.megapixels * 1024 * 1024 * a / b) / 16) * 16
        )
        height = max(
            256, round(math.sqrt(rendering.megapixels * 1024 * 1024 * b / a) / 16) * 16
        )
        match = ratio_matches[0] if ratio_matches else None
        while width * height > rendering.max_megapixels * 1024 * 1024:
            if width >= height:
                width -= 16
            else:
                height -= 16
    if width * height > rendering.max_megapixels * 1024 * 1024:
        raise ValueError("画幅超过配置的像素上限，请减小尺寸或调整插件配置。")
    if match:
        body = (body[: match.start()] + body[match.end() :]).strip()
    if not body:
        raise ValueError("请填写绘图要求。")
    return "generate", ImageRequest(body, width, height, mode)
