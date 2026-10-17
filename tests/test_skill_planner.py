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


def test_caption_keeps_literal_wording_and_cannot_replace_layout():
    skill = OfficialSkill()
    caption = 'A sign reads "こんにちは！".\nA second line reads "你好".'
    assert skill.compile({"caption": caption}, 1024, 1024) == caption
    assert not hasattr(skill, "validate_raw")
    with pytest.raises(ValueError):
        skill.compile({"caption": "a"}, 1024, 1024, layout=True)


def make_planner(responses):
    ctx = SimpleNamespace(
        llm=SimpleNamespace(generate=AsyncMock(side_effect=responses))
    )
    resolver = SimpleNamespace(resolve=AsyncMock(return_value=[]))
    return Planner(ctx, OfficialSkill(), resolver), ctx, resolver


def test_caption_uses_full_skill_without_layout_reference_or_history():
    planner, ctx, _ = make_planner(
        [{"success": True, "response": '{"caption":"A red cup."}'}]
    )
    config = Planning(danbooru_enabled=False)
    plan = asyncio.run(planner.plan(ImageRequest("red cup", 1024, 1024), config))
    assert plan.prompt == "A red cup." and plan.mode == "caption"
    messages = ctx.llm.generate.call_args.args[0]
    assert len(messages) == 2 and messages[0]["role"] == "system"
    assert planner.skill.instructions in messages[0]["content"]
    assert planner.skill.layout_instructions not in messages[0]["content"]
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


def test_removed_raw_mode_never_calls_services():
    planner, ctx, resolver = make_planner([])
    raw = "  Original wording, no default artists.\nSecond paragraph.  "
    with pytest.raises(PlanningError, match="unsupported_mode"):
        asyncio.run(planner.plan(ImageRequest(raw, 1024, 1024, "raw"), Planning()))
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
    assert [c["canonical_tag"] for c in payload["character_evidence"]] == [
        c["canonical_tag"] for c in resolver.resolve.return_value
    ]
    assert all(
        c["copyright"] == "Genshin Impact" for c in payload["character_evidence"]
    )
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


@pytest.mark.parametrize("mode", ["caption"])
def test_caption_routes_repair_accidental_layout_once(mode):
    planner, ctx, _ = make_planner(
        [
            {"success": True, "response": json.dumps(layout())},
            {"success": True, "response": '{"caption":"A quiet church."}'},
        ]
    )
    plan = asyncio.run(
        planner.plan(
            ImageRequest("church", 1024, 1024, mode), Planning(danbooru_enabled=False)
        )
    )
    assert plan.mode == mode and plan.compiled_prompt == "A quiet church."
    assert ctx.llm.generate.await_count == 2


def test_generate_preserves_original_with_frozen_context_without_model_calls(
    monkeypatch,
):
    planner, ctx, _ = make_planner([])
    monkeypatch.setattr(
        planner.skill,
        "compile",
        lambda *a, **kw: pytest.fail(
            "Tag generation must not invoke the official compiler"
        ),
    )
    request = ImageRequest(
        "成年旅人穿雨衣站在车站，牌子写“你好！”",
        880,
        1184,
        "generate",
        positive_prefix="best quality, highres,",
        style_name="测试",
        style_prompt="@artist name, 简洁平涂，",
    )
    plan = asyncio.run(planner.plan(request, Planning(danbooru_enabled=False)))
    assert plan.compiled_prompt == "" and plan.content_prompt == request.prompt
    assert plan.body_format == "natural_language"
    assert (
        plan.prompt
        == "best quality, highres\n@artist name, 简洁平涂\n" + request.prompt
    )
    assert (
        plan.prompt.count("best quality") == 1
        and plan.prompt.count("@artist name") == 1
    )
    assert plan.draft is None
    assert plan.prefixes["oc_context"] is None
    ctx.llm.generate.assert_not_awaited()
    assert plan.prefixes["style_prompt"] == request.style_prompt
    assert "white background" not in plan.prompt
    assert "BACKGROUND" not in plan.prompt


@pytest.mark.parametrize("mode", ["caption", "layout"])
def test_pure_skill_routes_ignore_generate_prefix_and_style(mode):
    draft = {"caption": "A red cup."} if mode == "caption" else layout()
    planner, ctx, _ = make_planner([{"success": True, "response": json.dumps(draft)}])
    request = ImageRequest(
        "a cup",
        1024,
        1024,
        mode,
        positive_prefix="DO NOT ADD",
        style_name="PRIVATE",
        style_prompt="DO NOT ADD STYLE",
    )
    plan = asyncio.run(planner.plan(request, Planning(danbooru_enabled=False)))
    assert plan.prompt == plan.compiled_prompt and plan.prefixes == {}
    assert "DO NOT ADD" not in plan.prompt
    payload = json.loads(ctx.llm.generate.call_args.args[0][1]["content"])
    assert "locked_prefixes" not in payload


@pytest.mark.parametrize(
    "candidates,expected",
    [
        ([" Cartethyia_(Wuthering Waves) "], ["cartethyia_(wuthering_waves)"]),
        (["ＬＵＭＩＮＥ_(GENSHIN_IMPACT)"], ["lumine_(genshin_impact)"]),
        (["bad/tag", ""], []),
        (None, []),
    ],
)
def test_candidate_normalization_never_discards_original_identity(candidates, expected):
    extraction = {
        "characters": [
            {
                "source_name": "荧",
                "copyright": "原神",
                "candidates": candidates,
                "depicted": True,
            }
        ]
    }
    planner, ctx, resolver = make_planner(
        [
            {"success": True, "response": json.dumps(extraction)},
        ]
    )
    plan = asyncio.run(
        planner.plan(ImageRequest("荧穿雨衣", 1024, 1024, "generate"), Planning())
    )
    assert resolver.resolve.call_args.args[0][0]["candidates"] == expected
    assert plan.characters[0]["source_name"] == "荧"
    assert plan.characters[0]["copyright"] == "原神"
    assert plan.prefixes["identity_references"] == []
    assert plan.prompt == "荧穿雨衣"
    assert ctx.llm.generate.await_count == 1


def test_generate_uses_verified_identity_as_a_binding_not_an_extra_subject():
    planner, _, resolver = make_planner(
        [
            {
                "success": True,
                "response": '{"characters":[{"source_name":"荧","depicted":true,"candidates":["Lumine_(Genshin_Impact)"]}]}',
            },
        ]
    )
    resolver.resolve.return_value = [
        {
            "source_name": "荧",
            "status": "verified",
            "canonical_tag": "lumine_(genshin_impact)",
        }
    ]
    plan = asyncio.run(
        planner.plan(ImageRequest("荧穿雨衣", 1024, 1024, "generate"), Planning())
    )
    assert '"荧" = lumine_(genshin_impact)' in plan.prompt
    assert "not extra people" in plan.prompt
    assert plan.prompt.endswith("\n荧穿雨衣")


def test_empty_candidates_do_not_call_danbooru_but_retain_source(monkeypatch):
    resolver = CharacterResolver(logging.getLogger("empty-candidates"))
    monkeypatch.setattr(
        resolver.module,
        "_resolve_evidence_candidates",
        lambda *a, **kw: pytest.fail("Empty hints must not query the network"),
    )
    result = asyncio.run(
        resolver.resolve(
            [{"source_name": "荧", "copyright": "原神", "candidates": []}], 1
        )
    )
    assert result == [
        {"source_name": "荧", "copyright": "原神", "status": "unresolved"}
    ]


def test_oc_interface_is_reserved_without_calls():
    planner, ctx, resolver = make_planner([])
    with pytest.raises(PlanningError, match="reserved_oc_context"):
        asyncio.run(
            planner.plan(
                ImageRequest("a person", 1024, 1024, oc_context={"name": "future"}),
                Planning(),
            )
        )
    ctx.llm.generate.assert_not_awaited()
    resolver.resolve.assert_not_awaited()
