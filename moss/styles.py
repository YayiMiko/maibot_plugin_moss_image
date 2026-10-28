"""Named style editing and request-local snapshots."""

import asyncio
import copy
import json
import re
from pathlib import Path

from .storage import atomic_write

BUILTIN_STYLES = {
    "立绘": (
        "character splash art, costume, soft fabric vs rigid metal contrast, "
        "glowing red/blue accents, dynamic flowing lines, white background,"
    )
}


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
    """Persist a shared style library and request-local snapshots."""

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
            if name != "":
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

    def effective_library(self, config) -> dict[str, str]:
        """Merge legacy config presets with the live chat-edited library.

        Args:
            config: Frozen plugin style configuration.

        Returns:
            Style names mapped to their complete visual text.
        """
        library = dict(BUILTIN_STYLES)
        library.update(parse_style_definition(item) for item in config.presets)
        library.update(self.state["library"])
        return library

    def effective_names(self, config) -> list[str]:
        """Return sorted style names for the read-only WebUI status section."""
        return sorted(self.effective_library(config))

    async def import_legacy(self, config) -> int:
        """Copy legacy config presets into runtime storage without overwriting."""
        async with self.lock:
            state = copy.deepcopy(self.state)
            imported = 0
            for item in config.presets:
                name, content = parse_style_definition(item)
                if name in state["library"]:
                    continue
                if len(state["library"]) >= 64:
                    break
                state["library"][name] = content
                imported += 1
            if not imported:
                return 0
            await asyncio.to_thread(atomic_write, self.path, state)
            self.state = state
            return imported

    async def snapshot(self, names: tuple[str, ...], config) -> tuple[str, str]:
        """Capture explicitly named styles under the library lock."""
        async with self.lock:
            library = self.effective_library(config)
            for name in names:
                if name not in library:
                    raise ValueError(
                        f"没有找到风格“{name}”，请使用 /moss 风格 查看或新建。"
                    )
            return ", ".join(names), "\n".join(library[name] for name in names)

    async def handle(self, request, task_id: str, config) -> list[str]:
        """Read or atomically edit the shared style library."""
        async with self.lock:
            library = self.effective_library(config)
            if request.operation == "list":
                return [
                    "MOSS 风格：",
                    *[
                        f"{name}：{content}"
                        for name, content in sorted(library.items())
                    ],
                    '调用：每次绘图要求中写 @名称；名称含空格时写 @"风格 名"。可多次指定，未指定不使用预设。',
                    "编辑：/moss 风格 编辑 名称=完整内容\n新建：/moss 风格 新建 名称=完整内容",
                    "风格库共享；聊天编辑覆盖同名配置项。",
                ]
            if task_id in self.state["processed"]:
                return ["本条风格操作已处理，没有重复修改。"]
            state = copy.deepcopy(self.state)
            exists = request.name in library
            if request.operation == "edit" and not exists:
                return ["该风格不存在，请使用 /moss 风格 新建 名称=内容。"]
            if request.operation == "create" and exists:
                return ["该风格已存在，请使用 /moss 风格 编辑 名称=完整内容。"]
            if not exists and len(library) >= 64:
                return ["风格数量已达上限，请联系维护者整理聊天保存的风格。"]
            state["library"][request.name] = request.content
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
            return [
                f"已{'编辑' if exists else '新建'}风格“{request.name}”：\n{request.content}"
            ]
