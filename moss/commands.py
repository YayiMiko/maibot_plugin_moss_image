"""Explicit command grammar, readable help and preplanning canvas resolution."""

import math
import re
from dataclasses import dataclass
from typing import Literal

from .oc import RoleRequest, parse_role, role_name
from .styles import parse_style_definition

COMMAND_PATTERN = r"(?i)^\s*(?:(?:\[image\]|@[^\r\n]+?)\s*)*(?P<command>/moss(?:\s|$))"
HELP = (
    "/moss 生成 <要求>：原文直出＋前缀、风格、角色校正\n"
    "/moss 规划 <要求>：官方 Caption 扩写生图\n"
    "/moss 布局 <要求>：官方扩写＋布局规划生图\n"
    "/moss 漫画 <剧情/角色>：单页灵活分镜\n"
    "/moss 表情包 <要求>：单张静态表情包\n"
    "/moss 抽卡 <要求>：联网精选参考，改编生一张图\n"
    "/moss 角色：OC 查看、管理与调用方法\n"
    "/moss 风格：查看、选择、新建或编辑风格\n"
    "/moss 解析法术：附图/引用，读取原始提示词\n"
    "/moss 反推：附图/引用单图，视觉推测提示词，非原词\n"
    "生图画幅：末尾写 比例4：3，或 --尺寸 1024x1024（宽×高像素）"
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
    "帮助",
    "help",
    "无优化",
}


@dataclass(frozen=True)
class ImageRequest:
    """Frozen canvas, intent and explicit OC selection for all image planners."""

    prompt: str
    width: int
    height: int
    mode: Literal["generate", "caption", "layout"] = "caption"
    task_type: Literal["illustration", "comic_page", "meme"] = "illustration"
    positive_prefix: str = ""
    style_name: str = ""
    style_prompt: str = ""
    oc_context: dict | None = None
    oc_names: tuple[str, ...] = ()
    panel_count: int | None = None
    canvas_explicit: bool = True


@dataclass(frozen=True)
class StyleRequest:
    """A local preset operation, never an image-generation request."""

    operation: Literal[
        "list", "select", "edit", "create", "settings", "application", "disable"
    ]
    name: str = ""
    content: str = ""


def parse_command(
    text: str, rendering
) -> tuple[str, ImageRequest | StyleRequest | RoleRequest | None]:
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
    if keyword == "角色":
        return "role", parse_role(body[len(keyword) :].strip())
    if keyword == "风格":
        arguments = body[len(keyword) :].strip()
        if not arguments:
            return "style", StyleRequest("list")
        parts = arguments.split(maxsplit=1)
        operation = parts[0]
        value = parts[1] if len(parts) > 1 else ""
        if operation == "设置":
            if not value:
                return "style", StyleRequest("settings")
            if value not in {"1", "2"}:
                raise ValueError("请使用 /moss 风格 设置 1 或 /moss 风格 设置 2。")
            return "style", StyleRequest(
                "application", content="generate" if value == "1" else "all"
            )
        if operation in {"编辑", "新建"}:
            name, content = parse_style_definition(value.strip())
            return "style", StyleRequest(
                "edit" if operation == "编辑" else "create", name, content
            )
        if arguments == "关闭":
            return "style", StyleRequest("disable")
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
    modes = {
        "生成": "generate",
        "规划": "caption",
        "布局": "layout",
        "漫画": "layout",
        "表情包": "caption",
        "抽卡": "caption",
    }
    if keyword not in modes:
        raise ValueError("请使用 /moss 生成 <要求> 或 /moss 规划 <要求>。")
    mode = modes[keyword]
    task_type = {"漫画": "comic_page", "表情包": "meme"}.get(keyword, "illustration")
    draw = keyword == "抽卡"
    body = body[len(keyword) :].strip()
    # Mask literal text without changing offsets into the original input.
    masked = list(body)
    quote, escaped = "", False
    for index, character in enumerate(body):
        if quote:
            masked[index] = "\ufffc"
            if escaped:
                escaped = False
            elif character == "\\" and quote in {'"', "'"}:
                escaped = True
            elif character == quote:
                quote = ""
        elif character in {'"', "“", "‘", "「", "『"} or (
            character == "'"
            and (index == 0 or not re.match(r"[a-zA-Z0-9]", body[index - 1]))
            and "'" in body[index + 1 :]
        ):
            quote = {'"': '"', "'": "'", "“": "”", "‘": "’", "「": "」", "『": "』"}[
                character
            ]
            masked[index] = "\ufffc"
    flags_text = "".join(masked)
    boundary = r"(?<![^\s,，。.!！?？;；:：、])"
    ending = r"(?=$|[\s,，。.!！?？;；、])(?!\.\d)"
    role_matches = list(
        re.finditer(boundary + r"--角色\s+([^\s,，;；、]+)", flags_text)
    )
    oc_names = tuple(dict.fromkeys(role_name(match[1]) for match in role_matches))
    if len(oc_names) > 8:
        raise ValueError("一次最多指定 8 个 OC 角色。")
    panel_matches = list(re.finditer(boundary + r"--格数\s+(\d+)" + ending, flags_text))
    controls = role_matches + panel_matches
    if any(
        marker.start() not in {match.start() for match in controls}
        for marker in re.finditer(r"--角色|--格数", flags_text)
    ):
        raise ValueError("角色写法为 --角色 名称；漫画格数写法为 --格数 3。")
    panel_count = int(panel_matches[0][1]) if panel_matches else None
    if panel_matches and (
        len(panel_matches) != 1
        or task_type != "comic_page"
        or panel_count not in range(1, 5)
    ):
        raise ValueError("--格数 仅用于单页漫画，请指定 1～4 格。")
    canvas_text = list(flags_text)
    for control in controls:
        canvas_text[control.start() : control.end()] = "\ufffc" * (
            control.end() - control.start()
        )
    flags_text = "".join(canvas_text)
    if task_type == "comic_page":
        natural_counts = []
        for count in re.findall(
            r"(?<![第\d一二三四五六七八九十~～至到-])([一二两三四五六七八九十]|\d+)\s*格(?:漫画|(?=$|[\s,，。;；:：]))",
            flags_text,
        ):
            value = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4}.get(count)
            value = (
                value if value is not None else int(count) if count.isdecimal() else 0
            )
            if value not in range(1, 5):
                raise ValueError("单页漫画暂支持 1～4 格，请减少格数。")
            natural_counts.append(value)
        if len(set(natural_counts + ([panel_count] if panel_count else []))) > 1:
            raise ValueError("漫画格数要求冲突，请只保留一个格数。")
        if natural_counts:
            panel_count = natural_counts[0]
    size_matches = list(
        re.finditer(boundary + r"--尺寸\s+(\d+)\s*[xX×]\s*(\d+)" + ending, flags_text)
    )
    ratio_matches = list(
        re.finditer(
            boundary + r"(?:--)?比例\s*[:：]?\s*(\d+)\s*[:：]\s*(\d+)" + ending,
            flags_text,
        )
    )
    starts = {match.start() for match in size_matches + ratio_matches}
    markers = re.finditer(
        r"--尺寸|--比例|" + boundary + r"比例(?=\s*[:：]?\s*[+-]?\d)", flags_text
    )
    if any(marker.start() not in starts for marker in markers):
        raise ValueError("画幅写法例如 比例4：3、--比例 4:3 或 --尺寸 1024x1024。")
    if len(size_matches) > 1 or (size_matches and ratio_matches):
        raise ValueError("请只指定一组尺寸或比例，不要同时填写。")
    ratios = [tuple(map(int, match.groups())) for match in ratio_matches]
    if any(
        min(a, b) < 1 or max(a, b) > 100 or not 1 / 8 <= a / b <= 8 for a, b in ratios
    ):
        raise ValueError("比例无效或过于极端。")
    if len({(a // math.gcd(a, b), b // math.gcd(a, b)) for a, b in ratios}) > 1:
        raise ValueError("检测到不同的画幅比例，请只保留你要使用的一个比例。")
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
            ratios[0]
            if ratios
            else ("1:1" if task_type == "meme" else rendering.aspect_ratio).split(":"),
        )
        if min(a, b) < 1 or max(a, b) > 100 or not 1 / 8 <= a / b <= 8:
            raise ValueError("比例无效或过于极端。")
        width = max(
            256, round(math.sqrt(rendering.megapixels * 1024 * 1024 * a / b) / 16) * 16
        )
        height = max(
            256, round(math.sqrt(rendering.megapixels * 1024 * 1024 * b / a) / 16) * 16
        )
        while width * height > rendering.max_megapixels * 1024 * 1024:
            if width >= height:
                width -= 16
            else:
                height -= 16
    if width * height > rendering.max_megapixels * 1024 * 1024:
        raise ValueError("画幅超过配置的像素上限，请减小尺寸或调整插件配置。")
    # Remove only recognized canvas clauses and their adjacent clause separator.
    for match in sorted(
        size_matches + ratio_matches + controls,
        key=lambda item: item.start(),
        reverse=True,
    ):
        start, end = match.span()
        left = start
        while left and body[left - 1] in " \t":
            left -= 1
        if left and body[left - 1] in ",，;；、":
            start = left - 1
        if not body[end:].strip(" \t\r\n,，。.!！?？;；、"):
            end = len(body)
        elif not body[:start].strip():
            while end < len(body) and body[end] in " \t,，;；、":
                end += 1
        body = body[:start] + body[end:]
    body = body.strip()
    if not body:
        raise ValueError("请填写绘图要求。")
    return "draw" if draw else "generate", ImageRequest(
        body,
        width,
        height,
        mode,
        task_type=task_type,
        oc_names=oc_names,
        panel_count=panel_count,
        canvas_explicit=bool(size_matches or ratio_matches) if draw else True,
    )
