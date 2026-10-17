"""Explicit bindings for the user's native MOSS INT8 sampling graph."""

import json

from .skill import ROOT


def build_workflow(request, prompt: str, config, seed: int, task_id: str) -> dict:
    """Bind one task without guessing positive/negative encoders by JSON order.

    Args:
        request: Validated fixed canvas.
        prompt: Direct description, official Caption or compiled Layout.
        config: Detached model and sampling configuration.
        seed: Task-owned random seed.
        task_id: Internal hexadecimal output namespace.

    Returns:
        Native ComfyUI API graph; local UI workflows remain untouched.
    """
    graph = json.loads(
        (ROOT / "workflows/moss-int8-api.json").read_text(encoding="utf-8")
    )
    graph["20"]["inputs"]["unet_name"] = config.unet_name
    graph["21"]["inputs"]["clip_name"] = config.clip_name
    graph["22"]["inputs"]["vae_name"] = config.vae_name
    graph["4"]["inputs"]["text"] = prompt
    graph["5"]["inputs"]["text"] = config.negative_prompt
    graph["6"]["inputs"].update(width=request.width, height=request.height)
    graph["16"]["inputs"].update(
        seed=seed,
        steps=config.steps,
        cfg=config.cfg,
        sampler_name=config.sampler,
        scheduler=config.scheduler,
    )
    graph["18"]["inputs"]["filename_prefix"] = f"moss/{task_id}"
    return graph
