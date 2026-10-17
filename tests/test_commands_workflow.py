"""Explicit routes, hidden style operations and native workflow invariants."""

import json

import pytest
from pydantic import ValidationError

from moss.commands import ImageRequest, parse_command
from moss.config import MossConfig
from moss.workflow import build_workflow


@pytest.mark.parametrize(
    "word",
    [
        "状态",
        "描述",
        "查看角色",
        "添加角色",
        "删除角色",
        "查看风格",
        "核对任务",
        "恢复任务",
        "调试",
        "漫画",
        "表情包",
        "无优化",
    ],
)
def test_removed_routes_cannot_accidentally_generate(word):
    with pytest.raises(ValueError):
        parse_command(f"/moss {word} test", MossConfig().rendering)


@pytest.mark.parametrize(
    "text,action,mode",
    [
        ("/moss 生成 cup", "generate", "generate"),
        ("/moss 规划 cup", "generate", "caption"),
        ("/moss 布局 poster", "generate", "layout"),
        ("/moss 风格", "style", None),
        ("[image] /moss 解析法术", "metadata", None),
        ("/moss", "help", None),
    ],
)
def test_only_supported_routes(text, action, mode):
    result, request = parse_command(text, MossConfig().rendering)
    assert result == action
    if action == "generate":
        assert request.mode == mode


def test_default_canvas_matches_native_resolution_selector():
    _, request = parse_command("/moss 生成 cup", MossConfig().rendering)
    assert (request.width, request.height) == (880, 1184)
    _, square = parse_command("/moss 生成 cup --比例 1:1", MossConfig().rendering)
    assert square.width == square.height == 1024


@pytest.mark.parametrize(
    "suffix",
    [
        "--尺寸 1025x1024",
        "--尺寸 128x128",
        "--尺寸 8192x8192",
        "--比例 0:4",
        "--比例 99:1",
        "--尺寸 invalid",
        "--尺寸 1024x1024 --比例 3:4",
    ],
)
def test_invalid_explicit_dimensions_never_silently_change(suffix):
    with pytest.raises(ValueError):
        parse_command("/moss 生成 cup " + suffix, MossConfig().rendering)


def test_flags_do_not_rewrite_literal_visible_text():
    _, request = parse_command(
        "/moss 规划 写着“--尺寸 1024x1024”", MossConfig().rendering
    )
    assert request.prompt == "写着“--尺寸 1024x1024”" and request.width == 880
    with pytest.raises(ValueError):
        parse_command("/moss cup", MossConfig().rendering)


def test_workflow_uses_explicit_bindings_and_moss_sampling():
    config = MossConfig()
    request = ImageRequest("cup", 1024, 1024)
    prompt = '{"items":[],"summary":{"caption":"not prefixed"}}'
    graph = build_workflow(request, prompt, config.rendering, 42, "a" * 24)
    assert graph["4"]["inputs"]["text"] == prompt
    assert graph["5"]["inputs"]["text"] == config.rendering.negative_prompt
    assert graph["16"]["inputs"]["positive"] == ["4", 0]
    assert graph["16"]["inputs"]["negative"] == ["5", 0]
    assert graph["6"]["class_type"] == "EmptyFlux2LatentImage"
    assert graph["6"]["inputs"] == {"width": 1024, "height": 1024, "batch_size": 1}
    assert graph["21"]["inputs"]["type"] == "moss_image"
    assert graph["15"]["inputs"] == {"model": ["20", 0], "shift": 5, "sampling": "flow"}
    assert graph["13"]["inputs"]["single_layers"] == "22"
    assert graph["16"]["inputs"]["steps"] == 50
    assert graph["16"]["inputs"]["cfg"] == 3
    assert "ResolutionSelector" not in json.dumps(graph)
    other = build_workflow(request, "different", config.rendering, 99, "b" * 24)
    assert graph["4"]["inputs"]["text"] == prompt
    assert other["4"]["inputs"]["text"] == "different"


@pytest.mark.parametrize(
    "data",
    [
        {"rendering": {"cfg": float("nan")}},
        {"rendering": {"aspect_ratio": "0:1"}},
        {"connection": {"comfyui_base_url": "file:///tmp"}},
        {"connection": {"comfyui_base_url": "https://secret:pw@host"}},
        {"rendering": {"megapixels": 4, "max_megapixels": 1}},
    ],
)
def test_invalid_configuration_is_rejected(data):
    with pytest.raises(ValidationError):
        MossConfig.model_validate(data)
