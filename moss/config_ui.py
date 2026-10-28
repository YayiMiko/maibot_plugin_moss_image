"""WebUI-only schema additions for live runtime state.

The fields built here are deliberately not part of ``MossConfig``.  The host
renders them as disabled controls, and its config validator ignores them when
the form is saved, so runtime names never leak into ``config.toml``.
"""

from __future__ import annotations

from typing import Any

EMPTY_LIBRARY = "（暂无）"
NOT_LOADED = "（插件尚未加载）"


def _example_text(value: Any) -> str:
    """Render a schema example as compact single-line help text."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (list, tuple)):
        return "、".join(str(item) for item in value)
    if isinstance(value, dict):
        return ", ".join(f"{key}={item}" for key, item in value.items())
    return str(value)


def add_host_field_hints(schema: dict[str, Any]) -> dict[str, Any]:
    """Expose descriptions and examples through the host's hint/placeholder.

    The current plugin config renderer displays ``hint`` and ``placeholder``
    but not the schema's ``description`` or ``example`` fields.  Populate the
    visible fields from the same metadata so every control remains explained.
    """
    for section in schema.get("sections", {}).values():
        for field in section.get("fields", {}).values():
            description = str(field.get("description") or "").strip()
            example = field.get("example")
            parts = [part for part in (description,) if part]
            if example is not None:
                parts.append(f"示例：{_example_text(example)}")
            if parts and not field.get("hint"):
                field["hint"] = " ".join(parts)
            if example is not None and not field.get("placeholder"):
                field["placeholder"] = _example_text(example)
    return schema


def _readonly_field(
    *,
    name: str,
    label: str,
    value: Any,
    description: str,
    example: Any,
    order: int,
    field_type: str = "string",
    ui_type: str = "textarea",
    rows: int = 6,
) -> dict[str, Any]:
    """Build the same field shape as the SDK schema generator."""
    return {
        "name": name,
        "type": field_type,
        "default": value,
        "description": description,
        "required": False,
        "choices": None,
        "min": None,
        "max": None,
        "step": None,
        "pattern": None,
        "max_length": None,
        "label": label,
        "placeholder": None,
        "hint": None,
        "icon": None,
        "hidden": False,
        "disabled": True,
        "order": order,
        "input_type": None,
        "ui_type": ui_type,
        "rows": rows,
        "group": None,
        "depends_on": None,
        "depends_value": None,
        "item_type": None,
        "item_fields": None,
        "min_items": None,
        "max_items": None,
        "example": example,
    }


def build_runtime_status_section(
    *,
    style_names: list[str],
    character_names: list[str],
    active_tasks: int,
    config_version: str,
    loaded: bool,
) -> dict[str, Any]:
    """Return a read-only section describing the current plugin instance.

    Args:
        style_names: Effective style names, already validated and sorted.
        character_names: Stored canonical OC names, already validated and sorted.
        active_tasks: Number of currently running MOSS jobs.
        config_version: Version of the configuration currently in effect.
        loaded: Whether the style and OC stores finished loading.

    Returns:
        A WebUI section whose fields are rendered but never saved into config.
    """
    missing = NOT_LOADED if not loaded else EMPTY_LIBRARY
    styles_value = "\n".join(style_names) if style_names else missing
    characters_value = "\n".join(character_names) if character_names else missing
    return {
        "name": "runtime_status",
        "title": "运行时状态（只读）",
        "description": "来自当前插件实例和 styles.json、characters.json；刷新本页后更新。",
        "icon": None,
        "collapsed": False,
        "order": 90,
        "fields": {
            "style_library": _readonly_field(
                name="style_library",
                label=f"当前风格库（{len(style_names)}）",
                value=styles_value,
                description="只读。风格库由 /moss 风格 管理；每行一个名称，名称后内容不在此显示。",
                example="千代风格、test、立绘",
                order=0,
            ),
            "character_library": _readonly_field(
                name="character_library",
                label=f"当前 OC 角色（{len(character_names)}）",
                value=characters_value,
                description="只读。OC 由 /moss 角色 管理；这里只显示名称，不显示外观或服装内容。",
                example="狐莉",
                order=1,
            ),
            "active_tasks": _readonly_field(
                name="active_tasks",
                label="当前运行任务",
                value=int(active_tasks),
                description="只读。此刻仍在运行或等待发送的 MOSS 任务数量。",
                example=0,
                order=2,
                field_type="integer",
                ui_type="number",
                rows=3,
            ),
            "config_version": _readonly_field(
                name="config_version",
                label="配置版本",
                value=config_version,
                description="只读。插件启动时实际生效的配置结构版本。",
                example="0.2.0",
                order=3,
                ui_type="text",
                rows=3,
            ),
        },
    }
