"""Request-local orchestration, without public task recovery or debug commands."""

import asyncio
import secrets
import time
from dataclasses import asdict

from .comfy import ComfyClient
from .delivery import send_result
from .media import MetadataReader, MultipleImagesError, extract_metadata
from .planner import PlanningError
from .storage import atomic_write
from .vision import VisionError, reverse_image
from .workflow import build_workflow


class TaskRunner:
    """Separate planning from serial GPU submission and at-most-once delivery."""

    def __init__(self, ctx, store, planner, styles):
        self.ctx, self.store, self.planner = ctx, store, planner
        self.styles = styles
        self.gpu_lock = asyncio.Lock()

    async def run(self, record: dict, action: str, request, config, context: dict):
        """Run one accepted task using only its captured configuration and target.

        Args:
            record: Private identity and mutable state owned by this coroutine.
            action: Generation, local style management or metadata extraction.
            request: Fixed-canvas image intent, absent for metadata extraction.
            config: Detached configuration accepted with the original command.
            context: Authorized stream, sender and explicit message/quote IDs.
        """
        directory = self.store.runtime / record["task_id"]
        started = time.monotonic()
        try:

            async def capture(stage, response):
                await self.store.append_llm(record["task_id"], stage, response)

            if action != "style":
                await self.store.begin_llm(record)
            if action in {"metadata", "style", "reverse"}:
                if action == "style":
                    record["status"] = "editing_style"
                    await self.store.save(record)
                    parts = await self.styles.handle(
                        request, context["scope"], record["task_id"], config.styles
                    )
                else:
                    record["status"] = "reading_image"
                    await self.store.save(record)
                    content = await asyncio.wait_for(
                        MetadataReader(
                            self.ctx, config.connection.qq_cache_roots
                        ).resolve(context, single_only=action == "reverse"),
                        timeout=90,
                    )
                    if action == "reverse":
                        record.update(status="reversing", body_format="tags")
                        await self.store.save(record)
                        await asyncio.to_thread(
                            atomic_write,
                            directory / "vision_config.json",
                            config.vision.model_dump(),
                        )
                        tags = await reverse_image(
                            self.ctx, config.vision, content, capture
                        )
                        await asyncio.to_thread(
                            atomic_write, directory / "prompt.txt", tags
                        )
                        parts = ["图片反推结果（视觉推测，不是原始提示词）：", tags]
                    else:
                        parts = await asyncio.to_thread(extract_metadata, content)
                confirmed = await send_result(
                    self.ctx,
                    context["stream_id"],
                    context["group_id"],
                    record,
                    self.store,
                    config.delivery,
                    parts=parts,
                )
            else:
                record["status"] = "planning"
                await self.store.save(record)
                await asyncio.to_thread(
                    atomic_write, directory / "request.json", asdict(request)
                )
                await asyncio.to_thread(
                    atomic_write, directory / "config.json", config.model_dump()
                )

                plan = await self.planner.plan(request, config.planning, capture)
                record.update(
                    mode=plan.mode,
                    characters=plan.characters,
                    width=request.width,
                    height=request.height,
                    body_format=plan.body_format,
                    planner="direct-input"
                    if request.mode == "generate"
                    else "official-skill",
                )
                if request.mode != "generate":
                    record["skill_revision"] = self.planner.skill.revision
                if plan.draft is not None:
                    await asyncio.to_thread(
                        atomic_write, directory / "draft.json", plan.draft
                    )
                await asyncio.to_thread(
                    atomic_write, directory / "prompt.txt", plan.prompt
                )
                await asyncio.to_thread(
                    atomic_write, directory / "content_prompt.txt", plan.content_prompt
                )
                if plan.compiled_prompt:
                    await asyncio.to_thread(
                        atomic_write,
                        directory / "compiled_prompt.txt",
                        plan.compiled_prompt,
                    )
                await asyncio.to_thread(
                    atomic_write, directory / "prefixes.json", plan.prefixes
                )
                seed = secrets.randbelow(2**63)
                graph = await asyncio.to_thread(
                    build_workflow,
                    request,
                    plan.prompt,
                    config.rendering,
                    seed,
                    record["task_id"],
                )
                await asyncio.to_thread(
                    atomic_write, directory / "workflow.json", graph
                )
                record.update(status="queued", seed=seed)
                await self.store.save(record)
                async with self.gpu_lock:
                    async with asyncio.timeout(
                        config.connection.generation_timeout + 180
                    ):
                        image = await ComfyClient(config.connection).generate(
                            graph, record, self.store, directory / "outputs"
                        )
                confirmed = await send_result(
                    self.ctx,
                    context["stream_id"],
                    context["group_id"],
                    record,
                    self.store,
                    config.delivery,
                    image=image,
                )
            if not confirmed:
                await self.notice(
                    "结果已生成，但发送回执未确认；可能已送达，没有自动重发。",
                    context["stream_id"],
                )
        except asyncio.CancelledError:
            record["status"] = (
                "delivery_unknown"
                if record.get("delivery_started")
                else "remote_unknown"
                if record.get("submission_started")
                and record.get("remote_state") != "completed"
                else "interrupted"
            )
            await self.store.save(record)
            raise
        except Exception as exc:
            if record.get("delivery_started"):
                record["status"] = "delivery_unknown"
            elif record.get("status") != "generation_failed":
                record["status"] = (
                    "remote_unknown"
                    if record.get("submission_started")
                    and record.get("remote_state") != "completed"
                    else "planning_failed"
                    if isinstance(exc, PlanningError)
                    else "failed"
                )
            record["error_type"] = type(exc).__name__
            if isinstance(exc, PlanningError):
                record["error_kind"] = exc.reason
            if isinstance(exc, VisionError):
                record["error_kind"] = exc.reason
            await self.store.save(record)
            self.ctx.logger.warning(
                "MOSS task failed: task=%s error=%s",
                record["task_id"],
                type(exc).__name__,
            )
            if record["status"] == "delivery_unknown":
                notice = "结果发送回执未确认；可能已送达，没有自动重发。"
            elif record["status"] == "remote_unknown":
                notice = "ComfyUI 任务状态未确认，没有重新提交；请联系维护者检查。"
            elif isinstance(exc, PlanningError):
                notice = (
                    "提示词模型拒绝了本次请求，未提交生图。"
                    if exc.reason == "blocked"
                    else "提示词规划未完成，未提交生图，也没有用默认内容代替。"
                )
            elif action == "reverse":
                if isinstance(exc, MultipleImagesError):
                    notice = "反推一次只处理一张图片，请单独附图或引用目标图片。"
                elif isinstance(exc, VisionError):
                    notice = (
                        "视觉模型拒绝了本次识图请求，没有返回默认内容。"
                        if exc.reason == "blocked"
                        else "图片反推未完成，请检查视觉模型配置或稍后再试；没有自动重试。"
                    )
                else:
                    notice = (
                        "未能读取反推图片，请附一张静态图片或引用同一会话中的目标图片。"
                    )
            elif action == "metadata":
                notice = "未能读取本次图片，请附图或引用同一会话中含图片的消息。"
            else:
                notice = "MOSS 任务未完成，没有自动重试；请联系维护者检查。"
            await self.notice(notice, context["stream_id"])
        finally:
            record["elapsed_seconds"] = time.monotonic() - started
            await self.store.save(record)

    async def notice(self, text: str, stream: str):
        """Send one bounded auxiliary notice; failure never retries the image."""
        try:
            await asyncio.wait_for(
                self.ctx.send.text(
                    text, stream, timeout_ms=10000, sync_to_maisaka_history=False
                ),
                timeout=12,
            )
        except Exception as exc:
            self.ctx.logger.warning("MOSS notice unavailable: %s", type(exc).__name__)
