"""Strict receipts and single-card long results through public SDK capabilities."""

import asyncio
import base64


async def send_result(
    ctx, stream: str, group: str, record: dict, store, config, *, image=None, parts=None
) -> bool:
    """Attempt one image/text/card send; never fall back to duplicate body sends.

    Args:
        ctx: Public SDK context.
        stream: Authorized request destination.
        group: Current group ID, or empty for private chats.
        record: Private request-local state.
        store: Atomic task storage.
        config: Delivery timeout and long-result threshold.
        image: Optional validated local image.
        parts: Optional semantic metadata sections.

    Returns:
        True only when the platform supplies an explicit successful message ID.
    """
    options = {
        "return_details": True,
        "timeout_ms": (config.timeout_seconds - 10) * 1000,
        "sync_to_maisaka_history": False,
    }
    record["computation_completed"] = True
    await store.save(record)
    if image is not None:

        def encode():
            return base64.b64encode(image.read_bytes()).decode("ascii")

        payload = await asyncio.to_thread(encode)
        method, mode = ctx.send.image, "image"
    else:
        text = "\n".join(parts or [])
        if not text.strip():
            raise ValueError("Empty text result")
        if len(text) > 32768:
            text = text[:32768] + "\n内容超过展示上限，末尾已省略。"
        if group and len(text) > config.group_forward_threshold:
            login = await asyncio.wait_for(
                ctx.api.call(
                    "adapter.napcat.action.call_data",
                    version="1",
                    action_name="get_login_info",
                    params={},
                ),
                timeout=10,
            )
            if (
                not isinstance(login, dict)
                or not str(login.get("user_id") or "").strip()
            ):
                raise ValueError("Forward identity unavailable")
            payload = [
                {
                    "user_id": str(login["user_id"]),
                    "nickname": str(login.get("nickname") or "MOSS"),
                    "segments": [{"type": "text", "content": text[i : i + 2000]}],
                }
                for i in range(0, len(text), 2000)
            ]
            options.update(show_log=False, processed_plain_text="[MOSS 法术解析结果]")
            method, mode = ctx.send.forward, "forward"
        else:
            method, payload, mode = ctx.send.text, text, "text"
    record.update(
        status="sending",
        delivery_started=True,
        delivery={"mode": mode, "status": "delivery_unknown"},
    )
    await store.save(record)
    try:
        result = await asyncio.wait_for(
            method(payload, stream, **options), timeout=config.timeout_seconds
        )
        if (
            isinstance(result, dict)
            and result.get("sent") is True
            and isinstance(result.get("message_id"), (str, int))
            and not isinstance(result.get("message_id"), bool)
            and str(result.get("message_id") or "").strip()
        ):
            record.update(
                status="sent" if image else "completed",
                delivery={
                    "mode": mode,
                    "status": "sent",
                    "message_id": str(result["message_id"]),
                },
            )
            await store.save(record)
            return True
    except asyncio.CancelledError:
        record["status"] = "delivery_unknown"
        await store.save(record)
        raise
    except Exception as exc:
        ctx.logger.warning("MOSS delivery unconfirmed: %s", type(exc).__name__)
    record["status"] = "delivery_unknown"
    await store.save(record)
    return False
