"""Async ComfyUI transport with a single submission and bounded downloads."""

import asyncio
import io
import time
import uuid
from pathlib import Path

import httpx
from PIL import Image


class ComfyError(RuntimeError):
    """Expose only a safe error category, not addresses or response bodies."""


def validate_image(content: bytes) -> str:
    """Verify supported output bytes and prevent decompression-sized payloads."""
    with Image.open(io.BytesIO(content)) as image:
        if image.width * image.height > 64 * 1024 * 1024:
            raise ValueError("Image exceeds pixel budget")
        suffix = {
            "PNG": ".png",
            "JPEG": ".jpg",
            "WEBP": ".webp",
            "MPO": ".jpg",
            "GIF": ".gif",
        }.get(image.format)
        if not suffix:
            raise ValueError("Unsupported image container")
        image.verify()
    return suffix


class ComfyClient:
    """Do not retry ambiguous submissions or globally interrupt the shared GPU."""

    def __init__(self, config):
        self.config = config

    async def generate(self, graph: dict, record: dict, store, directory: Path) -> Path:
        """Persist submission state before POST, then download the final SaveImage.

        Args:
            graph: Fully bound task-owned workflow.
            record: Request-owned state, updated before every uncertain operation.
            store: Atomic task storage.
            directory: Request-owned output root.

        Returns:
            One verified local image path.

        Raises:
            ComfyError: Rejected workflow, failed sampling or missing output.
        """
        async with httpx.AsyncClient(
            base_url=self.config.comfyui_base_url + "/",
            timeout=20,
            follow_redirects=False,
        ) as client:
            # Persist this first: timeout, cancellation or lost ACK can still mean submission.
            record.update(
                status="submitting", submission_started=True, client_id=uuid.uuid4().hex
            )
            await store.save(record)
            response = await client.post(
                "prompt", json={"prompt": graph, "client_id": record["client_id"]}
            )
            if 400 <= response.status_code < 500:
                record["status"] = "generation_failed"
                raise ComfyError("workflow_rejected")
            response.raise_for_status()
            payload = response.json()
            prompt_id = payload.get("prompt_id")
            if (
                not isinstance(prompt_id, str)
                or not prompt_id
                or "/" in prompt_id
                or len(prompt_id) > 128
            ):
                raise ComfyError("invalid_submission_receipt")
            record.update(status="generating", prompt_id=prompt_id)
            await store.save(record)
            deadline = time.monotonic() + self.config.generation_timeout
            while time.monotonic() < deadline:
                response = await client.get(f"history/{prompt_id}")
                response.raise_for_status()
                history = response.json().get(prompt_id)
                if isinstance(history, dict) and history:
                    status = history.get("status") or {}
                    if status.get("status_str") not in {None, "success"}:
                        record["status"] = "generation_failed"
                        raise ComfyError("workflow_failed")
                    # Intermediate previews are not final outputs of our bound graph.
                    images = (
                        (history.get("outputs") or {}).get("18", {}).get("images", [])
                    )
                    if not images:
                        record["status"] = "generation_failed"
                        raise ComfyError("missing_final_image")
                    descriptor = images[0]
                    record.update(status="downloading", remote_state="completed")
                    await store.save(record)
                    break
                await asyncio.sleep(min(2, max(0.001, deadline - time.monotonic())))
            else:
                raise TimeoutError("Remote generation outcome is unknown")
            chunks, size = [], 0
            async with client.stream(
                "GET",
                "view",
                params={
                    k: descriptor.get(k, "output" if k == "type" else "")
                    for k in ("filename", "subfolder", "type")
                },
                timeout=120,
            ) as response:
                response.raise_for_status()
                async for chunk in response.aiter_bytes():
                    size += len(chunk)
                    if size > 32 * 1024 * 1024:
                        raise ComfyError("output_too_large")
                    chunks.append(chunk)
            content = b"".join(chunks)
            suffix = await asyncio.to_thread(validate_image, content)
            output = directory / f"{uuid.uuid4().hex}{suffix}"

            def save_output():
                directory.mkdir(parents=True, exist_ok=True)
                temporary = output.with_suffix(".download")
                try:
                    temporary.write_bytes(content)
                    temporary.chmod(0o600)
                    temporary.replace(output)
                finally:
                    temporary.unlink(missing_ok=True)

            await asyncio.to_thread(save_output)
            record.update(
                status="generated", remote_state="completed", output=str(output)
            )
            await store.save(record)
            return output
