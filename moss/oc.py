"""Explicit OC presets with owner-scoped mutations and atomic private storage."""

import asyncio
import copy
import json
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .storage import atomic_write


def role_name(value: str) -> str:
    """Validate a name usable as an unquoted command argument, never a path.

    Args:
        value: Canonical OC name or alias, not a filesystem location.

    Returns:
        The unchanged name after validation.

    Raises:
        ValueError: The name is empty, ambiguous or contains control characters.
    """
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 80
        or re.search(r"[\t\r\n,，、;；=@+()[\]{}\x00\ufffc/\\]", value)
        or value.startswith("--")
        or value in {"新建", "编辑", "删除", "服装", "别名"}
    ):
        raise ValueError("角色名称最多 80 字，不能含逗号、等号或命令关键字。")
    return value


class OCDefinition(BaseModel):
    """Stable appearance and optional wardrobe are separate visual references."""

    model_config = ConfigDict(extra="forbid", strict=True)
    name: str
    description: str = Field(min_length=1, max_length=4096)
    default_outfit: str = Field(default="", max_length=2048)
    aliases: list[str] = Field(default_factory=list, max_length=8)

    @model_validator(mode="after")
    def valid_definition(self):
        role_name(self.name)
        for alias in self.aliases:
            role_name(alias)
        if (
            len(set([self.name, *self.aliases])) != len(self.aliases) + 1
            or not self.description.strip()
            or "\x00" in self.description + self.default_outfit
        ):
            raise ValueError("Invalid OC description or duplicate aliases")
        return self


class StoredOC(OCDefinition):
    owner: str = Field(min_length=1, max_length=128)
    updated_at: float = Field(ge=0, allow_inf_nan=False)


@dataclass(frozen=True)
class RoleRequest:
    operation: Literal["list", "show", "create", "edit", "outfit", "aliases", "delete"]
    name: str = ""
    content: str = ""


def parse_role(arguments: str) -> RoleRequest:
    """Parse only the role submenu, without implicit generation or selection.

    Args:
        arguments: Text following the explicit role submenu keyword.

    Returns:
        A read or mutation request with bounded, validated arguments.

    Raises:
        ValueError: The requested syntax cannot safely identify a preset.
    """
    if not arguments:
        return RoleRequest("list")
    pieces = arguments.split(maxsplit=1)
    word, value = pieces[0], pieces[1].strip() if len(pieces) == 2 else ""
    operations = {"新建": "create", "编辑": "edit", "服装": "outfit", "别名": "aliases"}
    if word in operations:
        name, sep, content = value.partition("=")
        name, content = name.strip(), content.strip()
        if (
            not sep
            or (word in {"新建", "编辑"} and not content)
            or len(content) > 4096
            or "\x00" in content
        ):
            raise ValueError(
                f"请使用 /moss 角色 {word} 名称=内容；服装或别名留空可清除。"
            )
        return RoleRequest(operations[word], role_name(name), content)
    if word == "删除":
        return RoleRequest("delete", role_name(value))
    return RoleRequest("show", role_name(arguments))


class OCStore:
    """Shared readable library; no implicit default character or latest-image state."""

    def __init__(self, data: Path):
        self.path = Path(data) / "characters.json"
        self.lock = asyncio.Lock()
        self.state = {"library": {}, "processed": []}

    async def initialize(self):
        """Validate bounded persisted data without replacing unreadable user presets."""
        if self.path.is_symlink() or self.path.is_junction():
            raise ValueError("Linked OC storage is not permitted")
        if not self.path.exists():
            return
        if self.path.stat().st_size > 8 * 1024 * 1024:
            raise ValueError("OC storage exceeds size limit")
        state = json.loads(
            await asyncio.to_thread(self.path.read_text, encoding="utf-8")
        )
        if (
            not isinstance(state, dict)
            or set(state) != set(self.state)
            or not isinstance(state["library"], dict)
            or len(state["library"]) > 64
            or not isinstance(state["processed"], list)
            or len(state["processed"]) > 128
        ):
            raise ValueError("Invalid OC storage schema")
        seen = set()
        for name, value in state["library"].items():
            definition = StoredOC.model_validate(value)
            if name != definition.name or seen.intersection(
                [name, *definition.aliases]
            ):
                raise ValueError("Conflicting OC names or aliases")
            seen.update([name, *definition.aliases])
        if any(
            not isinstance(task, str) or not re.fullmatch(r"[a-f0-9]{24}", task)
            for task in state["processed"]
        ):
            raise ValueError("Invalid OC mutation receipts")
        self.state = state

    async def snapshot(self, names: tuple[str, ...]) -> dict | None:
        """Return detached definitions for explicitly selected names and aliases.

        Args:
            names: Explicit names supplied with the image command, never inferred.

        Returns:
            Owner-free visual references or None when nothing was selected.

        Raises:
            ValueError: An explicitly selected OC is missing or invalid.
        """
        if not names:
            return None
        async with self.lock:
            result = {}
            for name in names:
                match = next(
                    (
                        value
                        for value in self.state["library"].values()
                        if name == value["name"] or name in value["aliases"]
                    ),
                    None,
                )
                if match is None:
                    raise ValueError(
                        f"没有找到角色“{name}”，请使用 /moss 角色 查看或新建。"
                    )
                definition = OCDefinition.model_validate(
                    {
                        key: value
                        for key, value in match.items()
                        if key not in {"owner", "updated_at"}
                    }
                )
                result[definition.name] = definition.model_dump()
            return {"characters": list(result.values())}

    async def handle(
        self, request: RoleRequest, user: str, admins: list[str], task_id: str
    ) -> list[str]:
        """Read or atomically mutate one preset after checking its stored owner.

        Args:
            request: Validated role submenu operation.
            user: Host-authenticated caller ID, never a nickname or client role flag.
            admins: Explicit library administrators from the frozen plugin config.
            task_id: Message-scoped mutation deduplication key.

        Returns:
            Bounded text sections for the common receipt-aware result sender.
        """
        async with self.lock:
            library = self.state["library"]
            name = next(
                (
                    key
                    for key, entry in library.items()
                    if request.name == key or request.name in entry["aliases"]
                ),
                request.name,
            )
            old = library.get(name)
            if request.operation == "list":
                return [
                    "MOSS OC 角色（不会自动出场）：",
                    *[
                        f"{key}：{value['description'][:100]}"
                        for key, value in sorted(library.items())
                    ],
                    '查看：/moss 角色 名称\n新建：/moss 角色 新建 名称=稳定外观\n编辑：/moss 角色 编辑 名称=稳定外观\n服装：/moss 角色 服装 名称=默认服装\n别名：/moss 角色 别名 名称=别名1,别名2\n删除：/moss 角色 删除 名称\n调用：每次生图要求中加 +名称；名称含空格时写 +"角色 名"。可重复指定；只写选择器时需补充绘图要求。',
                    "读取共享；修改和删除限创建者或配置中的角色库管理员。默认服装与身份分开，原文直出不自动拼默认服装。",
                ]
            if request.operation == "show":
                return (
                    [
                        f"{name}\n外观：{old['description']}\n默认服装：{old['default_outfit'] or '未设置'}\n别名：{', '.join(old['aliases']) or '无'}"
                    ]
                    if old
                    else ["该角色不存在，请使用 /moss 角色 查看列表。"]
                )
            if task_id in self.state["processed"]:
                return ["本条角色操作已处理，没有重复修改。"]
            if request.operation == "create" and old:
                return ["该角色或别名已存在，请使用编辑操作。"]
            if request.operation != "create" and not old:
                return ["该角色不存在，请先新建。"]
            if old and old["owner"] != user and user not in admins:
                return ["只有该角色的创建者或角色库管理员可以修改、删除。"]
            state = copy.deepcopy(self.state)
            if request.operation == "delete":
                del state["library"][name]
                notice = f"已删除角色“{name}”，本操作不可撤销；已接收任务的角色快照不受影响。"
            else:
                if old is None and len(library) >= 64:
                    return ["角色数量已达上限，请先整理。"]
                entry = (
                    copy.deepcopy(old)
                    if old
                    else {
                        "name": name,
                        "description": request.content,
                        "default_outfit": "",
                        "aliases": [],
                        "owner": user,
                        "updated_at": time.time(),
                    }
                )
                if request.operation == "edit":
                    entry["description"] = request.content
                elif request.operation == "outfit":
                    entry["default_outfit"] = request.content
                elif request.operation == "aliases":
                    entry["aliases"] = [
                        part.strip()
                        for part in re.split(r"[,，、]", request.content)
                        if part.strip()
                    ]
                entry["updated_at"] = time.time()
                entry = StoredOC.model_validate(entry).model_dump()
                existing = {
                    alias
                    for key, value in library.items()
                    if key != name
                    for alias in [key, *value["aliases"]]
                }
                if existing.intersection([name, *entry["aliases"]]):
                    return ["名称或别名与其他角色冲突，未保存。"]
                state["library"][name] = entry
                notice = f"已保存角色“{name}”。"
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
