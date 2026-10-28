"""MaiBot SDK entry point for explicit MOSS image and style commands."""

import asyncio
import hashlib
import json
import re
from dataclasses import replace

from maibot_sdk import Command, MaiBotPlugin

if __package__:
    from .moss.characters import CharacterResolver
    from .moss.commands import COMMAND_PATTERN, HELP, parse_command
    from .moss.config import MossConfig
    from .moss.config_ui import add_host_field_hints, build_runtime_status_section
    from .moss.oc import OCStore
    from .moss.planner import Planner
    from .moss.references import cache_reference
    from .moss.skill import OfficialSkill
    from .moss.storage import TaskStore
    from .moss.styles import StyleStore
    from .moss.tasks import TaskRunner
else:
    from moss.characters import CharacterResolver
    from moss.commands import COMMAND_PATTERN, HELP, parse_command
    from moss.config import MossConfig
    from moss.config_ui import add_host_field_hints, build_runtime_status_section
    from moss.oc import OCStore
    from moss.planner import Planner
    from moss.references import cache_reference
    from moss.skill import OfficialSkill
    from moss.storage import TaskStore
    from moss.styles import StyleStore
    from moss.tasks import TaskRunner


class MossPlugin(MaiBotPlugin):
    """Use public SDK APIs only; no implicit tools or host persona changes."""

    config_model = MossConfig

    def get_webui_config_schema(
        self,
        *,
        plugin_id: str = "",
        plugin_name: str = "",
        plugin_version: str = "",
        plugin_description: str = "",
        plugin_author: str = "",
    ) -> dict:
        """Add a read-only snapshot of live styles, OCs and running jobs.

        The host calls this hook on every config-page inspection, so a page
        refresh picks up styles or OCs created through chat commands.
        """
        schema = super().get_webui_config_schema(
            plugin_id=plugin_id,
            plugin_name=plugin_name,
            plugin_version=plugin_version,
            plugin_description=plugin_description,
            plugin_author=plugin_author,
        )
        styles = getattr(self, "styles", None)
        characters = getattr(self, "characters", None)
        loaded = styles is not None and characters is not None
        try:
            config = self.config
        except RuntimeError:
            config = MossConfig()
        sections = schema.setdefault("sections", {})
        sections.pop("plugin", None)
        sections["runtime_status"] = build_runtime_status_section(
            style_names=styles.effective_names(config.styles) if loaded else [],
            character_names=sorted(characters.state["library"]) if loaded else [],
            active_tasks=len(getattr(self, "jobs", {})),
            config_version=config.plugin.config_version,
            loaded=loaded,
        )
        return add_host_field_hints(schema)

    async def on_load(self):
        """Validate bundled resources and restore state without external requests."""
        self.jobs = {}
        self.accept_lock = asyncio.Lock()
        skill = await asyncio.to_thread(OfficialSkill)
        self.store = TaskStore(
            self.ctx.paths.data_dir, self.ctx.paths.runtime_dir, self.ctx.logger
        )
        await self.store.initialize()
        self.styles = StyleStore(self.store.data)
        await self.styles.initialize()
        try:
            imported = await self.styles.import_legacy(self.config.styles)
        except Exception as exc:
            self.ctx.logger.warning(
                "MOSS legacy style import skipped: %s", type(exc).__name__
            )
        else:
            if imported:
                self.ctx.logger.info("MOSS imported %d legacy styles", imported)
        self.characters = OCStore(self.store.data)
        await self.characters.initialize()
        resolver = CharacterResolver(self.ctx.logger)
        self.runner = TaskRunner(
            self.ctx,
            self.store,
            Planner(self.ctx, skill, resolver),
            self.styles,
            self.characters,
        )
        self.maintenance = asyncio.create_task(self._maintain())

    async def _maintain(self):
        """Keep cleanup off-loop and serialize it with task admission."""
        while True:
            async with self.accept_lock:
                await self.store.cleanup(
                    self.config.connection.retention_days, set(self.jobs)
                )
                if not self.jobs:
                    try:
                        await asyncio.to_thread(
                            cache_reference,
                            self.store.data / "draw_reference_cache",
                            None,
                            self.config.draw.limits.cache_mib * 1024**2,
                        )
                    except Exception as exc:
                        self.ctx.logger.warning(
                            "MOSS reference cleanup skipped: %s", type(exc).__name__
                        )
            await asyncio.sleep(3600)

    async def on_unload(self):
        """Cancel local waits only, never interrupt shared ComfyUI or resend."""
        tasks = list(self.jobs.values()) + [self.maintenance]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        iterator = self.store.retention_cursor.pop("iterator", None)
        if iterator is not None:
            iterator.close()

    async def on_config_update(
        self, scope: str, config_data: dict, version: str
    ) -> None:
        """Accept host configuration reloads without replacing active task snapshots.

        Args:
            scope: Configuration reload scope provided by the host.
            config_data: Updated payload already applied by the SDK.
            version: Host configuration reload version.
        """
        self.ctx.logger.info(
            "MOSS configuration updated: scope=%s version=%s", scope, version
        )

    @Command(
        "moss",
        description="MOSS 生图、漫画、表情包、角色、风格与图片解析",
        pattern=COMMAND_PATTERN,
    )
    async def handle_moss(self, **kwargs):
        """Authorize explicit QQ commands and capture each request's configuration."""
        text = str(kwargs.get("text") or "")
        match = re.match(COMMAND_PATTERN, text)
        if (
            not match
            or kwargs.get("platform") != "qq"
            or not kwargs.get("stream_id")
            or not kwargs.get("user_id")
        ):
            return False, None, 0
        message = kwargs.get("message") or {}
        if "@" in text[: match.start("command")]:
            # Never authorize a nickname typed in plain text or mentions of other users.
            mentions, first_text = [], ""
            segments = message.get("raw_message", [])
            if not isinstance(segments, list):
                return False, None, 0
            for segment in segments:
                if not isinstance(segment, dict):
                    return False, None, 0
                kind, data = segment.get("type"), segment.get("data")
                if kind in {"reply", "image"}:
                    continue
                if kind == "at" and isinstance(data, dict):
                    mentions.append(str(data.get("target_user_id") or ""))
                elif kind == "text" and isinstance(data, str):
                    if not data.strip():
                        continue
                    first_text = data
                    break
                else:
                    return False, None, 0
            if not mentions or not re.match(
                r"(?i)^\s*(?:\[image\]\s*)*/moss(?:\s|$)", first_text
            ):
                return False, None, 0
            info = message.get("message_info", {}).get("additional_config") or {}
            bot_id = str(
                info.get("platform_io_account_id") or info.get("self_id") or ""
            )
            if not bot_id:
                try:
                    login = await asyncio.wait_for(
                        self.ctx.api.call(
                            "adapter.napcat.action.call_data",
                            version="1",
                            action_name="get_login_info",
                            params={},
                        ),
                        timeout=10,
                    )
                    bot_id = str((login or {}).get("user_id") or "")
                except Exception:
                    return False, None, 0
            if not bot_id or any(target != bot_id for target in mentions):
                return False, None, 0
            text = text[match.start("command") :]
        segments = message.get("raw_message")
        if isinstance(segments, list):
            seen_command = False
            has_inline_mention = False
            parts = []
            for segment in segments:
                if not isinstance(segment, dict):
                    continue
                kind, data = segment.get("type"), segment.get("data")
                if kind == "text" and isinstance(data, str):
                    if not seen_command:
                        start = re.search(r"(?i)/moss(?=\s|$)", data)
                        if start:
                            seen_command = True
                            parts.append(data[start.start() :])
                    else:
                        parts.append(data)
                elif seen_command and kind == "at":
                    has_inline_mention = True
                    parts.append(" ")
                elif seen_command and kind == "image":
                    parts.append(" [image] ")
            if has_inline_mention:
                text = "".join(parts)
        config = self.config.model_copy(deep=True)
        stream, user = str(kwargs["stream_id"]), str(kwargs["user_id"])
        if not config.connection.enabled or (
            config.connection.allowed_sender_ids
            and user not in config.connection.allowed_sender_ids
        ):
            await self.runner.notice("MOSS 已关闭，或你没有使用权限。", stream)
            return True, None, 2
        try:
            action, request = parse_command(text, config.rendering)
        except ValueError as exc:
            await self.runner.notice(str(exc), stream)
            return True, None, 2
        if action == "help":
            await self.runner.notice(HELP, stream)
            return True, None, 2
        if action == "draw":
            if not config.draw.enabled:
                await self.runner.notice(
                    "高美学抽卡尚未启用，请由维护者配置搜索和视觉模型后开启。",
                    stream,
                )
                return True, None, 2
            segments = message.get("raw_message")
            if (
                "[image]" in text
                or message.get("reply_to")
                or any(
                    isinstance(segment, dict)
                    and segment.get("type") in {"image", "reply"}
                    for segment in (segments if isinstance(segments, list) else [])
                )
            ):
                await self.runner.notice(
                    "抽卡会联网选择参考，请单独发送文字要求；附图或引用图不会参与抽卡。",
                    stream,
                )
                return True, None, 2
        message_id = str(message.get("message_id") or "")
        if not message_id:
            await self.runner.notice("缺少消息编号，请重新发送指令。", stream)
            return True, None, 2
        scope = hashlib.sha256(json.dumps(["qq", stream, user]).encode()).hexdigest()
        task_id = hashlib.sha256(f"{scope}:{message_id}".encode()).hexdigest()[:24]
        context = {
            "scope": scope,
            "stream_id": stream,
            "user_id": user,
            "group_id": str(kwargs.get("group_id") or ""),
            "message_id": message_id,
            "reply_to": message.get("reply_to"),
        }
        async with self.accept_lock:
            if len(self.jobs) >= config.connection.max_pending:
                await self.runner.notice("MOSS 队列已满，请稍后再试。", stream)
                return True, None, 2
            if action in {"generate", "draw"}:
                try:
                    style_name, style_prompt = await self.styles.snapshot(
                        request.style_names, config.styles
                    )
                    oc_context = await self.characters.snapshot(request.oc_names)
                    request = replace(
                        request,
                        positive_prefix=config.styles.positive_prefix
                        if request.mode == "generate" and action == "generate"
                        else "",
                        style_name=style_name,
                        style_prompt=style_prompt,
                        oc_context=oc_context,
                    )
                except ValueError as exc:
                    await self.runner.notice(str(exc), stream)
                    return True, None, 2
            record = await self.store.create(task_id, scope, action)
            if record is None:
                return True, None, 2
            task = asyncio.create_task(
                self.runner.run(record, action, request, config, context)
            )
            self.jobs[task_id] = task
            task.add_done_callback(lambda _: self.jobs.pop(task_id, None))
            task.add_done_callback(
                lambda done: done.exception() if not done.cancelled() else None
            )
        return True, None, 2


def create_plugin():
    """Construct the plugin without networking or generation side effects."""
    return MossPlugin()
