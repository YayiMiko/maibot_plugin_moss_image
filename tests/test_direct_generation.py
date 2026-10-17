"""Direct input is immutable; identity research is optional and cannot expand it."""

import asyncio
import json
from unittest.mock import AsyncMock

import pytest
from test_skill_planner import make_planner

from moss.commands import ImageRequest, parse_command
from moss.config import MossConfig, Planning
from moss.planner import PlanningError


def test_direct_keeps_quotes_newlines_repetitions_and_only_removes_canvas_flag():
    original = "画个穿雨衣的小姑娘，站在路灯下面发呆\n牌子写“--比例 1:1，不要改我”\n发呆，发呆。"
    _, request = parse_command(
        "/moss 生成 " + original + " --比例 16:9", MossConfig().rendering
    )
    planner, ctx, _ = make_planner([])
    plan = asyncio.run(planner.plan(request, Planning(danbooru_enabled=False)))
    assert request.width > request.height
    assert request.prompt == plan.prompt == plan.content_prompt == original
    ctx.llm.generate.assert_not_awaited()


@pytest.mark.parametrize("value", ["", " \n\t", "hello\x00world"])
def test_invalid_direct_inputs_fail_before_any_lookup(value):
    planner, ctx, resolver = make_planner([])
    with pytest.raises(PlanningError, match="invalid_input"):
        asyncio.run(
            planner.plan(ImageRequest(value, 1024, 1024, "generate"), Planning())
        )
    ctx.llm.generate.assert_not_awaited()
    resolver.resolve.assert_not_awaited()


@pytest.mark.parametrize(
    "reply",
    [
        {"success": False, "error": "private service failure"},
        {"success": True, "blocked": True, "response": "private refusal"},
        {"success": True, "response": "not JSON"},
        {"success": True, "response": '{"characters":{}}'},
        {"success": True, "response": '{"characters":[]}', "finish_reason": "length"},
    ],
)
def test_failed_identity_research_never_blocks_original_description(reply):
    planner, ctx, resolver = make_planner([reply])
    body = "只画小猫，不要补别的人物"
    plan = asyncio.run(
        planner.plan(ImageRequest(body, 1024, 1024, "generate"), Planning())
    )
    assert plan.prompt == plan.content_prompt == body
    assert ctx.llm.generate.await_count == 1
    resolver.resolve.assert_not_awaited()


def test_identity_timeout_and_provider_exception_degrade_but_cancellation_propagates():
    async def slow(*args, **kwargs):
        await asyncio.Event().wait()

    async def run():
        for failure in (slow, RuntimeError("private endpoint")):
            planner, ctx, _ = make_planner([])
            ctx.llm.generate = AsyncMock(side_effect=failure)
            plan = await planner.plan(
                ImageRequest("荧穿雨衣", 1024, 1024, "generate"),
                Planning().model_copy(update={"timeout": 0.01}),
            )
            assert plan.prompt == "荧穿雨衣"
        planner, ctx, _ = make_planner([])
        ctx.llm.generate.side_effect = asyncio.CancelledError()
        with pytest.raises(asyncio.CancelledError):
            await planner.plan(
                ImageRequest("荧穿雨衣", 1024, 1024, "generate"), Planning()
            )

    asyncio.run(run())


@pytest.mark.parametrize("lookup", ["error", "timeout", "malformed", "unverified"])
def test_lookup_failure_retains_original_without_fabricated_canonical_tag(lookup):
    planner, ctx, resolver = make_planner(
        [
            {
                "success": True,
                "response": '{"characters":[{"source_name":"荧","depicted":true,"candidates":["lumine_(genshin_impact)"]}]}',
            }
        ]
    )
    if lookup == "error":
        resolver.resolve.side_effect = RuntimeError("private endpoint")
    elif lookup == "timeout":

        async def slow(*args):
            await asyncio.Event().wait()

        resolver.resolve.side_effect = slow
    elif lookup == "malformed":
        resolver.resolve.return_value = None
    else:
        resolver.resolve.return_value = [
            {
                "source_name": "荧",
                "status": "degraded",
                "canonical_tag": "wrong_tag",
                "appearance_anchors": ["default dress"],
            }
        ]
    config = Planning().model_copy(update={"danbooru_budget": 0.01})
    plan = asyncio.run(
        planner.plan(ImageRequest("荧穿雨衣", 1024, 1024, "generate"), config)
    )
    assert plan.prompt == "荧穿雨衣" and plan.prefixes["identity_references"] == []
    assert ctx.llm.generate.await_count == 1


def test_aliases_group_by_verified_tag_without_repeating_or_injecting_appearance():
    names = ["荧", "旅行者"]
    extracted = {
        "characters": [
            {
                "source_name": name,
                "depicted": True,
                "candidates": ["LUMINE_(GENSHIN_IMPACT)"],
            }
            for name in names
        ]
    }
    planner, ctx, resolver = make_planner(
        [{"success": True, "response": json.dumps(extracted)}]
    )
    resolver.resolve.return_value = [
        {
            "source_name": name,
            "status": "verified",
            "canonical_tag": "lumine_(genshin_impact)",
            "appearance_anchors": ["white dress", "solo"],
        }
        for name in names
    ]
    body = "画荧，也就是旅行者，穿雨衣"
    plan = asyncio.run(
        planner.plan(ImageRequest(body, 1024, 1024, "generate"), Planning())
    )
    assert plan.content_prompt == body and plan.prompt.endswith(body)
    assert plan.prompt.count("lumine_(genshin_impact)") == 1
    assert '"荧" / "旅行者" = lumine_(genshin_impact)' in plan.prompt
    assert "white dress" not in plan.prompt and "solo" not in plan.prompt
    assert ctx.llm.generate.await_count == 1
    system = ctx.llm.generate.call_args.args[0][0]["content"]
    assert "identity lookup ONLY" in system and "depicted" in system


def test_existing_canonical_tag_and_multiple_people_are_preserved():
    identities = [
        ("荧", "lumine_(genshin_impact)"),
        ("纳西妲", "nahida_(genshin_impact)"),
    ]
    extracted = {
        "characters": [
            {"source_name": name, "depicted": True, "candidates": [tag]}
            for name, tag in identities
        ]
    }
    planner, ctx, resolver = make_planner(
        [{"success": True, "response": json.dumps(extracted)}]
    )
    resolver.resolve.return_value = [
        {"source_name": name, "status": "verified", "canonical_tag": tag}
        for name, tag in identities
    ]
    body = "荧 LUMINE_(GENSHIN_IMPACT) 和纳西妲，两个人并肩站着"
    plan = asyncio.run(
        planner.plan(ImageRequest(body, 1024, 1024, "generate"), Planning())
    )
    assert plan.prompt.casefold().count("lumine_(genshin_impact)") == 1
    assert plan.prompt.count("nahida_(genshin_impact)") == 1
    assert plan.content_prompt == body and plan.prompt.endswith(body)
    assert len(plan.prefixes["identity_references"]) == 1


def test_non_depicted_and_quoted_names_never_add_character_references():
    characters = [
        {
            "source_name": "荧",
            "depicted": False,
            "candidates": ["lumine_(genshin_impact)"],
        },
        {
            "source_name": "纳西妲",
            "depicted": True,
            "candidates": ["nahida_(genshin_impact)"],
        },
        {"source_name": "派蒙", "candidates": ["paimon_(genshin_impact)"]},
    ]
    planner, ctx, resolver = make_planner(
        [{"success": True, "response": json.dumps({"characters": characters})}]
    )
    body = "不要画荧，只有一只猫，牌子写“纳西妲”，没有派蒙"
    plan = asyncio.run(
        planner.plan(ImageRequest(body, 1024, 1024, "generate"), Planning())
    )
    assert plan.prompt == body
    resolver.resolve.assert_not_awaited()
    assert ctx.llm.generate.await_count == 1


def test_chinese_only_style_and_body_do_not_require_tags_or_translation():
    planner, ctx, _ = make_planner([])
    body = "一个普通人说：“你好。”\n背景不必补充"
    plan = asyncio.run(
        planner.plan(
            ImageRequest(body, 1024, 1024, "generate", style_prompt="水墨画，"),
            Planning(danbooru_enabled=False),
        )
    )
    assert plan.prompt == "水墨画\n" + body
    assert plan.content_prompt == body and plan.compiled_prompt == ""
    ctx.llm.generate.assert_not_awaited()


@pytest.mark.parametrize("mode", ["generate", "caption"])
def test_identity_example_contains_boolean_depiction_and_name_boundaries(mode):
    replies = [{"success": True, "response": '{"characters":[]}'}]
    if mode == "caption":
        replies.append({"success": True, "response": '{"caption":"A sleepy Ganyu."}'})
    planner, ctx, _ = make_planner(replies)
    asyncio.run(planner.plan(ImageRequest("甘雨困困", 1024, 1024, mode), Planning()))
    instruction = ctx.llm.generate.await_args_list[0].args[0][0]["content"]
    assert '"depicted":true' in instruction and 'not "甘雨困困"' in instruction


@pytest.mark.parametrize(
    "repair", ["verified", "false", "missing", "string", "refusal", "timeout"]
)
def test_direct_missing_depiction_repairs_once_without_rewriting_or_fabrication(repair):
    identity = {"source_name": "甘雨", "candidates": ["ganyu_(genshin_impact)"]}
    fixed = {**identity, "depicted": True}
    if repair == "false":
        fixed["depicted"] = False
    elif repair == "missing":
        fixed.pop("depicted")
    elif repair == "string":
        fixed["depicted"] = "true"
    result = (
        {"success": True, "blocked": True, "response": "private refusal"}
        if repair == "refusal"
        else {"success": True, "response": json.dumps({"characters": [fixed]})}
    )
    planner, ctx, resolver = make_planner(
        [
            {"success": True, "response": json.dumps({"characters": [identity]})},
            TimeoutError("private error") if repair == "timeout" else result,
        ]
    )
    resolver.resolve.return_value = [
        {
            "source_name": "甘雨",
            "status": "verified",
            "canonical_tag": "ganyu_(genshin_impact)",
        }
    ]
    capture = AsyncMock()
    original = "甘雨困困，不要改写这句"
    plan = asyncio.run(
        planner.plan(
            ImageRequest(original, 1024, 1024, "generate"), Planning(), capture
        )
    )
    assert plan.content_prompt == original and plan.prompt.endswith(original)
    assert ctx.llm.generate.await_count == 2
    assert ("ganyu_(genshin_impact)" in plan.prompt) == (repair == "verified")
    if repair != "verified":
        resolver.resolve.assert_not_awaited()
    if repair in {"missing", "string", "refusal", "timeout"}:
        assert capture.await_args_list[-1].args[0] == "identity_invalid"
