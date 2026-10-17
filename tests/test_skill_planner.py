"""Compiler contracts, literal wording and no model-generated coordinate math."""

import asyncio
import copy
import json
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from moss.characters import CharacterResolver
from moss.commands import ImageRequest
from moss.config import Planning
from moss.planner import Planner, PlanningError
from moss.skill import OfficialSkill


def layout():
    return {
        "width": 1024,
        "height": 1024,
        "bbox_coord_space": "abs",
        "bbox_format": "xyxy",
        "summary": {"caption": "A quiet Chinese poster."},
        "items": [
            {
                "label": "text",
                "caption": "Black calligraphy.",
                "text": "你好，世界！\n再见。",
                "bbox": [100.2, 200.4, 900.1, 400.8],
            }
        ],
    }


def test_official_resources_and_centered_geometry():
    skill = OfficialSkill()
    draft = layout()
    before = copy.deepcopy(draft)
    result = skill.parse(skill.compile(draft, 1024, 1024))
    assert result["items"][0]["bbox"] == [-312, -412, -111, 389]
    assert result["items"][0]["text"] == "你好，世界！\n再见。"
    assert result["bbox_coord_space"] == "abs_centralized"
    assert result["bbox_format"] == "yxyx"
    assert "width" not in result and "height" not in result
    assert draft == before
    assert "\n" not in skill.compile(draft, 1024, 1024)


@pytest.mark.parametrize(
    "change",
    ["canvas", "outside", "extra", "empty", "nested", "nan", "bool", "inverted"],
)
def test_invalid_layouts_are_rejected(change):
    draft = layout()
    if change == "canvas":
        draft["width"] = 1536
    if change == "outside":
        draft["items"][0]["bbox"][2] = 2000
    if change == "extra":
        draft["surprise"] = "discard me"
    if change == "empty":
        draft["items"][0]["text"] = ""
    if change == "nested":
        draft["items"][0]["children"] = []
    if change == "nan":
        draft["items"][0]["bbox"][0] = float("nan")
    if change == "bool":
        draft["items"][0]["bbox"][0] = True
    if change == "inverted":
        draft["items"][0]["bbox"] = [100, 200, 50, 300]
    with pytest.raises(ValueError):
        OfficialSkill().compile(draft, 1024, 1024)


@pytest.mark.parametrize(
    "text", ['{"caption":"a","caption":"b"}', '{"caption":NaN}', "[]"]
)
def test_json_errors_do_not_silently_drop_data(text):
    skill = OfficialSkill()
    with pytest.raises(ValueError):
        skill.compile(skill.parse(text), 1024, 1024)


def test_caption_and_literal_raw_prompt():
    skill = OfficialSkill()
    caption = 'A sign reads "こんにちは！".\nA second line reads "你好".'
    assert skill.compile({"caption": caption}, 1024, 1024) == caption
    raw = skill.compile(layout(), 1024, 1024)
    skill.validate_raw(raw, 1024, 1024)
    with pytest.raises(ValueError):
        skill.validate_raw(raw, 512, 512)
    with pytest.raises(ValueError):
        skill.validate_raw('{"caption":"not a compiled layout"}', 1024, 1024)
    with pytest.raises(ValueError):
        skill.compile({"caption": "a"}, 1024, 1024, layout=True)


def make_planner(responses):
    ctx = SimpleNamespace(
        llm=SimpleNamespace(generate=AsyncMock(side_effect=responses))
    )
    resolver = SimpleNamespace(resolve=AsyncMock(return_value=[]))
    return Planner(ctx, OfficialSkill(), resolver), ctx, resolver


def test_auto_caption_uses_full_skill_without_history():
    planner, ctx, _ = make_planner(
        [{"success": True, "response": '{"caption":"A red cup."}'}]
    )
    config = Planning(danbooru_enabled=False)
    plan = asyncio.run(planner.plan(ImageRequest("red cup", 1024, 1024), config))
    assert plan.prompt == "A red cup." and plan.mode == "caption"
    messages = ctx.llm.generate.call_args.args[0]
    assert len(messages) == 2 and messages[0]["role"] == "system"
    assert planner.skill.instructions in messages[0]["content"]
    assert planner.skill.layout_instructions in messages[0]["content"]
    assert ctx.llm.generate.call_args.kwargs["task_name"] == "utils"
    assert "history" not in ctx.llm.generate.call_args.kwargs


def test_structural_repair_happens_only_once_and_keeps_original_request():
    planner, ctx, _ = make_planner(
        [
            {"success": True, "response": '{"caption":"not Layout"}'},
            {"success": True, "response": json.dumps(layout(), ensure_ascii=False)},
        ]
    )
    plan = asyncio.run(
        planner.plan(
            ImageRequest("标题“你好，世界！”", 1024, 1024, "layout"),
            Planning(danbooru_enabled=False),
        )
    )
    assert plan.mode == "layout" and ctx.llm.generate.await_count == 2
    assert "标题“你好，世界！”" in ctx.llm.generate.call_args.args[0][1]["content"]


@pytest.mark.parametrize(
    "response",
    [
        {"success": True, "blocked": True, "response": ""},
        {"success": True, "response": "I cannot help with that request."},
        {"success": False, "error": "private provider error"},
        {"success": True, "response": '{"caption":"A cup"}', "finish_reason": "length"},
    ],
)
def test_provider_failure_and_refusal_never_trigger_repair(response):
    planner, ctx, _ = make_planner([response])
    with pytest.raises(PlanningError):
        asyncio.run(
            planner.plan(
                ImageRequest("a cup", 1024, 1024), Planning(danbooru_enabled=False)
            )
        )
    assert ctx.llm.generate.await_count == 1


def test_two_invalid_drafts_fail_without_default_image():
    planner, ctx, _ = make_planner([{"success": True, "response": "nonsense"}] * 2)
    with pytest.raises(PlanningError, match="invalid_draft"):
        asyncio.run(
            planner.plan(
                ImageRequest("a cup", 1024, 1024), Planning(danbooru_enabled=False)
            )
        )
    assert ctx.llm.generate.await_count == 2


@pytest.mark.parametrize("intent", ["comic_page", "meme"])
def test_future_intents_are_reserved_without_calls(intent):
    planner, ctx, resolver = make_planner([])
    with pytest.raises(PlanningError, match="reserved_task_type"):
        asyncio.run(
            planner.plan(
                ImageRequest("a page", 1024, 1024, task_type=intent), Planning()
            )
        )
    ctx.llm.generate.assert_not_awaited()
    resolver.resolve.assert_not_awaited()


def test_raw_skips_all_llm_and_identity_lookup():
    planner, ctx, resolver = make_planner([])
    raw = "  Original wording, no default artists.\nSecond paragraph.  "
    plan = asyncio.run(planner.plan(ImageRequest(raw, 1024, 1024, "raw"), Planning()))
    assert plan.prompt == raw
    ctx.llm.generate.assert_not_awaited()
    resolver.resolve.assert_not_awaited()


def test_identity_evidence_is_bound_per_explicit_character():
    extraction = {
        "characters": [
            {
                "source_name": "荧",
                "copyright": "Genshin Impact",
                "candidates": ["lumine_(genshin_impact)"],
            },
            {
                "source_name": "纳西妲",
                "copyright": "Genshin Impact",
                "candidates": ["nahida_(genshin_impact)"],
            },
            {"source_name": "狐莉", "candidates": ["invented_character"]},
        ]
    }
    planner, ctx, resolver = make_planner(
        [
            {"success": True, "response": json.dumps(extraction, ensure_ascii=False)},
            {
                "success": True,
                "response": '{"caption":"Lumine and Nahida, both wearing raincoats."}',
            },
        ]
    )
    resolver.resolve.return_value = [
        {
            "source_name": "荧",
            "canonical_tag": "lumine_(genshin_impact)",
            "status": "verified",
        },
        {
            "source_name": "纳西妲",
            "canonical_tag": "nahida_(genshin_impact)",
            "status": "verified",
        },
    ]
    plan = asyncio.run(
        planner.plan(ImageRequest("荧和纳西妲穿雨衣", 1024, 1024), Planning())
    )
    candidates = resolver.resolve.call_args.args[0]
    assert [c["source_name"] for c in candidates] == ["荧", "纳西妲"]
    payload = json.loads(ctx.llm.generate.call_args.args[0][1]["content"])
    assert payload["character_evidence"] == resolver.resolve.return_value
    assert plan.prompt.endswith("raincoats.")
    assert "lumine_" not in plan.prompt


def test_danbooru_adapter_uses_character_evidence_not_tag_replacement(monkeypatch):
    resolver = CharacterResolver(logging.getLogger("characters"))
    module = resolver.module
    monkeypatch.setattr(
        module,
        "_resolve_evidence_candidates",
        lambda candidates, **kw: (
            module.TagRecord(candidates[0], 4, 100, source="test"),
            ("verified",),
        ),
    )
    monkeypatch.setattr(
        module, "_fetch_stable_identity_tags", lambda *a, **kw: ("blonde_hair",)
    )
    result = asyncio.run(
        resolver.resolve(
            [
                {"source_name": "荧", "candidates": ["lumine_(genshin_impact)"]},
                {"source_name": "纳西妲", "candidates": ["nahida_(genshin_impact)"]},
            ],
            1,
        )
    )
    assert [r["source_name"] for r in result] == ["荧", "纳西妲"]
    assert all(r["status"] == "verified" for r in result)
    assert result[0]["appearance_anchors"] == ["blonde_hair"]
