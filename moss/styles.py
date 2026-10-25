"""Named style editing and per-caller selection without touching host settings."""

import asyncio
import copy
import json
import re
from pathlib import Path

from .storage import atomic_write


def parse_style_definition(text: str) -> tuple[str, str]:
    """Validate a named preset without rewriting its artist notation or prose.

    Args:
        text: Name and complete style text separated by an equals sign.

    Returns:
        Trimmed name and otherwise unchanged style text.

    Raises:
        ValueError: The name, separator or bounded content is invalid.
    """
    name, separator, content = text.partition("=")
    name, content = name.strip(), content.strip()
    if (
        not separator
        or not name
        or len(name) > 80
        or re.search(r"[,，\n\r@()[\]{}=]", name)
        or name in {"编辑", "新建", "关闭"}
        or not content
        or len(content) > 4096
        or "\x00" in name + content
    ):
        raise ValueError("请使用 名称=完整风格内容；名称最多 80 字，内容最多 4096 字。")
    return name, content


class StyleStore:
    """Persist a shared style library and independently scoped selections."""

    def __init__(self, data: Path):
        self.path = Path(data) / "styles.json"
        self.lock = asyncio.Lock()
        self.state = {
            "library": {},
            "selections": {},
            "applications": {},
            "processed": [],
        }

    async def initialize(self):
        """Validate existing private state instead of silently replacing damage."""
        if self.path.is_symlink() or self.path.is_junction():
            raise ValueError("Linked style storage is not permitted")
        if not self.path.exists():
            return
        if self.path.stat().st_size > 8 * 1024 * 1024:
            raise ValueError("Style storage exceeds size limit")
        state = json.loads(
            await asyncio.to_thread(self.path.read_text, encoding="utf-8")
        )
        if isinstance(state, dict) and set(state) == {
            "library",
            "selections",
            "processed",
        }:
            # Older libraries inherit the new default without rewriting live data.
            state["applications"] = {}
        if not isinstance(state, dict) or set(state) != set(self.state):
            raise ValueError("Invalid style storage schema")
        if (
            not isinstance(state["library"], dict)
            or len(state["library"]) > 64
            or not isinstance(state["selections"], dict)
            or len(state["selections"]) > 4096
            or not isinstance(state["applications"], dict)
            or len(state["applications"]) > 4096
            or not isinstance(state["processed"], list)
            or len(state["processed"]) > 128
        ):
            raise ValueError("Invalid style storage bounds")
        for name, content in state["library"].items():
            if not isinstance(name, str) or not isinstance(content, str):
                raise ValueError("Invalid stored style")
            if parse_style_definition(name + "=" + content) != (name, content):
                raise ValueError("Noncanonical stored style")
        for scope, name in state["selections"].items():
            if not isinstance(scope, str) or not re.fullmatch(r"[a-f0-9]{64}", scope):
                raise ValueError("Invalid stored style scope")
            if not isinstance(name, str):
                raise ValueError("Invalid stored style selection")
            parse_style_definition(name + "=selection")
        for scope, application in state["applications"].items():
            if (
                not isinstance(scope, str)
                or not re.fullmatch(r"[a-f0-9]{64}", scope)
                or not isinstance(application, str)
                or application not in {"generate", "all"}
            ):
                raise ValueError("Invalid stored style application")
        if any(
            not isinstance(task, str) or not re.fullmatch(r"[a-f0-9]{24}", task)
            for task in state["processed"]
        ):
            raise ValueError("Invalid style operation receipts")
        self.state = state

    async def snapshot(
        self, scope: str, config, task_type: str = "illustration"
    ) -> tuple[str, str]:
        """Capture the effective style before task admission completes.

        Args:
            scope: Hash of the platform, conversation and sender.
            config: Detached style library and application defaults.
            task_type: Illustration, comic page or meme. The caller excludes
                explicit Caption/Layout illustration routes entirely; draw is
                always excluded regardless of the configured application.

        Returns:
            Frozen name and content, or empty strings for excluded media.
        """
        if task_type == "draw":
            return "", ""
        async with self.lock:
            application = self.state["applications"].get(
                scope, config.default_application
            )
            if task_type != "illustration" and application == "generate":
                return "", ""
            library = dict(parse_style_definition(item) for item in config.presets)
            library.update(self.state["library"])
            name = self.state["selections"].get(scope, config.default_style)
            if name not in library:
                name = config.default_style
            return name, library.get(name, "")

    async def handle(self, request, scope: str, task_id: str, config) -> list[str]:
        """Apply a submenu operation atomically under the host command permissions.

        Args:
            request: Validated list, select, edit or create operation.
            scope: Hash of the current platform, conversation and sender.
            task_id: Message-scoped deduplication key.
            config: Detached configuration defaults for this operation.

        Returns:
            Display sections suitable for the existing bounded forward sender.
        """
        async with self.lock:
            library = dict(parse_style_definition(item) for item in config.presets)
            library.update(self.state["library"])
            active = self.state["selections"].get(scope, config.default_style)
            application = self.state["applications"].get(
                scope, config.default_application
            )
            usage = (
                "仅「生成」" if application == "generate" else "「生成、漫画、表情包」"
            )
            if request.operation == "settings":
                return [
                    "风格用于哪些功能？\n1. 仅「生成」"
                    + ("（默认）" if config.default_application == "generate" else "")
                    + "\n2.「生成、漫画、表情包」"
                    + ("（默认）" if config.default_application == "all" else ""),
                    "当前：" + usage,
                    "选择：/moss 风格 设置 1\n或：/moss 风格 设置 2",
                    "「规划」「布局」「抽卡」始终不使用风格预设。选择仅影响你在本会话中的后续任务。",
                ]
            if request.operation == "list":
                return [
                    "MOSS 风格：",
                    "当前：" + (active if active in library else "未配置默认风格"),
                    "用途：" + usage,
                    *[
                        f"{name}：{content}"
                        for name, content in sorted(library.items())
                    ],
                    "选择：/moss 风格 <名称>\n编辑：/moss 风格 编辑 名称=完整内容\n新建：/moss 风格 新建 名称=完整内容\n用途设置：/moss 风格 设置",
                    "风格库共享；聊天编辑覆盖同名配置项。选择仅影响你在本会话中的后续任务。",
                ]
            if task_id in self.state["processed"]:
                return ["本条风格操作已处理，没有重复修改。"]
            state = copy.deepcopy(self.state)
            if request.operation == "application":
                if request.content not in {"generate", "all"}:
                    raise ValueError("Invalid style application")
                if (
                    scope not in state["applications"]
                    and len(state["applications"]) >= 4096
                ):
                    return ["风格设置记录已达上限，请联系维护者。"]
                state["applications"][scope] = request.content
                usage = (
                    "仅「生成」"
                    if request.content == "generate"
                    else "「生成、漫画、表情包」"
                )
                notice = f"已设为用于{usage}，仅影响你在本会话中的后续任务。「规划」「布局」「抽卡」不使用风格预设。"
            elif request.operation == "select":
                if request.name not in library:
                    return ["没有找到该风格，请使用 /moss 风格 查看列表。"]
                if (
                    scope not in state["selections"]
                    and len(state["selections"]) >= 4096
                ):
                    return ["风格选择记录已达上限，请联系维护者。"]
                state["selections"][scope] = request.name
                notice = f"已选择风格“{request.name}”，用于你本会话的{usage}。"
            else:
                exists = request.name in library
                if request.operation == "edit" and not exists:
                    return ["该风格不存在，请使用 /moss 风格 新建 名称=内容。"]
                if request.operation == "create" and exists:
                    return ["该风格已存在，请使用 /moss 风格 编辑 名称=完整内容。"]
                if not exists and len(library) >= 64:
                    return ["风格数量已达上限，请联系维护者整理聊天保存的风格。"]
                state["library"][request.name] = request.content
                notice = f"已{'编辑' if exists else '新建'}风格“{request.name}”：\n{request.content}"
            state["processed"] = (state["processed"] + [task_id])[-128:]
            write = asyncio.create_task(
                asyncio.to_thread(atomic_write, self.path, state)
            )
            try:
                await asyncio.shield(write)
            except asyncio.CancelledError:
                await write
                self.state = state
                raise
            self.state = state
            return [notice]
