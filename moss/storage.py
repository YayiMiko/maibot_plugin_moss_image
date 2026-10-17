"""Atomic task files and latest-only LLM diagnostics, isolated from chat history."""

import asyncio
import copy
import json
import os
import re
import time
import uuid
from pathlib import Path

from .retention import clean_history

TERMINAL = {
    "sent",
    "completed",
    "failed",
    "planning_failed",
    "input_missing",
    "generation_failed",
    "delivery_unknown",
    "interrupted",
}


def atomic_write(path: Path, data) -> None:
    """Write UTF-8 JSON or text privately without exposing partial contents."""
    if (
        path.is_symlink()
        or path.is_junction()
        or any(p.is_symlink() or p.is_junction() for p in path.parents)
    ):
        raise ValueError("Linked storage paths are not permitted")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("x", encoding="utf-8") as handle:
            temporary.chmod(0o600)
            handle.write(
                data
                if isinstance(data, str)
                else json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False)
            )
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


class TaskStore:
    """Keep task records private and late LLM returns out of newer diagnostics."""

    def __init__(self, data: Path, runtime: Path, logger):
        self.data, self.runtime, self.logger = Path(data), Path(runtime), logger
        self.records = self.data / "tasks"
        self.lock = asyncio.Lock()
        self.latest_order = (0, "")
        self.latest = None
        self.retention_cursor = {}

    async def initialize(self):
        """Classify interrupted records without resubmitting or resending them."""

        def restore():
            if any(
                p.is_symlink() or p.is_junction()
                for root in (self.data, self.runtime)
                for p in (root, *root.parents)
            ):
                raise ValueError("Linked storage roots are not permitted")
            self.records.mkdir(parents=True, exist_ok=True)
            self.runtime.mkdir(parents=True, exist_ok=True)
            for path in self.records.glob("*.json"):
                try:
                    if (
                        not re.fullmatch(r"[a-f0-9]{24}", path.stem)
                        or path.is_symlink()
                        or path.stat().st_size > 1024 * 1024
                    ):
                        continue
                    record = json.loads(path.read_text(encoding="utf-8"))
                    if record.get("task_id") != path.stem:
                        continue
                    if record.get("status") not in TERMINAL | {"remote_unknown"}:
                        record["status"] = (
                            "delivery_unknown"
                            if record.get("delivery_started")
                            else "remote_unknown"
                            if record.get("submission_started")
                            and record.get("remote_state") != "completed"
                            else "interrupted"
                        )
                        atomic_write(path, record)
                except (OSError, ValueError, TypeError, AttributeError):
                    self.logger.warning("Unreadable MOSS task record: %s", path.name)

        await asyncio.to_thread(restore)

    async def create(self, task_id: str, scope: str, action: str) -> dict | None:
        """Atomically deduplicate by platform, conversation, caller and message ID."""
        async with self.lock:
            path = self.records / f"{task_id}.json"
            if path.exists():
                return None
            record = {
                "task_id": task_id,
                "scope": scope,
                "action": action,
                "created_at": time.time(),
                "created_ns": time.time_ns(),
                "status": "accepted",
            }
            await asyncio.to_thread(atomic_write, path, record)
            return record

    async def save(self, record: dict) -> None:
        """Persist a request-owned state transition off the event loop."""
        operation = asyncio.create_task(
            asyncio.to_thread(
                atomic_write,
                self.records / f"{record['task_id']}.json",
                copy.deepcopy(record),
            )
        )
        try:
            await asyncio.shield(operation)
        except asyncio.CancelledError:
            await operation
            raise

    async def begin_llm(self, record: dict) -> None:
        """Replace the previous diagnostic even when the new task uses no LLM."""
        async with self.lock:
            order = (record["created_ns"], record["task_id"])
            if order > self.latest_order:
                self.latest_order = order
                self.latest = {
                    "task_id": record["task_id"],
                    "scope": record["scope"],
                    "calls": [],
                }
                try:
                    await asyncio.to_thread(
                        atomic_write, self.data / "last_llm_response.json", self.latest
                    )
                except (OSError, ValueError):
                    self.logger.warning(
                        "MOSS latest diagnostic could not be initialized"
                    )

    async def append_llm(self, task_id: str, stage: str, result) -> None:
        """Keep only the current task's bounded raw response before compilation."""
        async with self.lock:
            if not self.latest or self.latest["task_id"] != task_id:
                return
            data = result if isinstance(result, dict) else {}
            response, refusal = (
                str(data.get("response") or ""),
                str(data.get("refusal") or ""),
            )
            self.latest["calls"] = (
                self.latest["calls"]
                + [
                    {
                        "stage": stage,
                        "success": bool(data.get("success")),
                        "response": response[:32768],
                        "refusal": refusal[:32768],
                        "truncated": len(response) > 32768 or len(refusal) > 32768,
                        "finish_reason": str(data.get("finish_reason") or "")[:80],
                    }
                ]
            )[-4:]
            try:
                await asyncio.to_thread(
                    atomic_write, self.data / "last_llm_response.json", self.latest
                )
            except (OSError, ValueError):
                self.logger.warning("MOSS latest diagnostic could not be saved")

    async def cleanup(self, days: int, active: set[str]) -> None:
        """Delete only expired terminal records and validated task directories."""
        async with self.lock:
            operation = asyncio.create_task(
                asyncio.to_thread(
                    clean_history,
                    self.records,
                    self.runtime,
                    days,
                    active,
                    self.logger,
                    self.retention_cursor,
                )
            )
            try:
                removed = await asyncio.shield(operation)
            except asyncio.CancelledError:
                await operation
                raise
            if removed:
                self.logger.info("MOSS retention removed %s expired tasks", removed)
