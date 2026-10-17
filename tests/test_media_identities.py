"""Verified identities survive media expansion and styles remain true prefixes."""

import asyncio
import copy
import json
from unittest.mock import AsyncMock

import pytest
from test_media_planner import envelope, story
from test_skill_planner import make_planner

from moss.commands import ImageRequest
from moss.config import Planning
from moss.planner import PlanningError

NAMES = {"荧": "lumine_(genshin_impact)", "纳西妲": "nahida_(genshin_impact)"}


def media_inputs(kind, *, aliases=False, scene_only=False):
    """Return editable provider replies with identity-specific internal bindings."""
    names = ["荧", "旅行者"] if aliases else list(NAMES)
    board = story(2 if kind == "comic" else 1, "你好" if kind == "lettered" else None)
    for panel in board["panels"]:
        panel["characters"] = names[:1] if aliases else names
    draft = (
        {"caption": "Two friends resting together."}
        if kind == "caption"
        else envelope(board, comic=kind == "comic")
    )
    if kind != "caption":
        bindings = []
        for panel_index, panel in enumerate(board["panels"]):
            for name in panel["characters"]:
                index = next(
                    index
                    for index, item in enumerate(draft["draft"]["items"])
                    if item["label"] == "character"
                    and item["caption"].startswith(name)
                    and (kind != "comic" or index > draft["panel_indices"][panel_index])
                )
                bindings.append(
                    {
                        "source_name": name,
                        "panel_index": panel_index,
                        "item_index": index,
                    }
                )
        if scene_only:
            old_items = draft["draft"]["items"]
            keep = [
                i for i, item in enumerate(old_items) if item["label"] != "character"
            ]
            draft["draft"]["items"] = [old_items[i] for i in keep]
            draft["panel_indices"] = [keep.index(i) for i in draft["panel_indices"]]
            draft["text_indices"] = [keep.index(i) for i in draft["text_indices"]]
            for binding in bindings:
                binding["item_index"] = draft["panel_indices"][binding["panel_index"]]
        draft["character_bindings"] = bindings
    evidence = [
        {
            "source_name": name,
            "status": "verified",
            "canonical_tag": NAMES.get(name, NAMES["荧"]),
        }
        for name in names
    ]
    extraction = {
        "characters": [
            {
                "source_name": name,
                "depicted": True,
                "candidates": [item["canonical_tag"].upper()],
            }
            for name, item in zip(names, evidence, strict=True)
        ]
    }
    return board, draft, evidence, extraction


def run_media(
    kind,
    board,
    drafts,
    evidence,
    extraction,
    *,
    style="flat colors, @artist,",
    capture=None,
):
    """Run only mocked identity/story/export calls through the real compiler."""
    replies = [extraction, board, *drafts]
    planner, ctx, resolver = make_planner(
        [
            {"success": True, "response": json.dumps(reply, ensure_ascii=False)}
            for reply in replies
        ]
    )
    resolver.resolve.return_value = evidence
    request = ImageRequest(
        "荧也叫旅行者，与纳西妲休息，配字“你好”"
        if kind == "lettered"
        else "荧也叫旅行者，与纳西妲休息",
        1024,
        1024,
        "layout" if kind == "comic" else "caption",
        task_type="comic_page" if kind == "comic" else "meme",
        style_prompt=style,
    )
    plan = asyncio.run(planner.plan(request, Planning(), capture))
    return plan, ctx, resolver


@pytest.mark.parametrize("kind", ["caption", "comic", "lettered"])
@pytest.mark.parametrize("style", ["", "flat colors, @artist,", "水墨，@artist,\n留白"])
def test_verified_tags_survive_llm_omission_with_style_first(kind, style):
    board, draft, evidence, extraction = media_inputs(kind)
    plan, ctx, resolver = run_media(
        kind, board, [draft], evidence, extraction, style=style
    )
    assert resolver.resolve.await_args.args[0][0]["candidates"] == [NAMES["荧"]]
    caption = (
        json.loads(plan.prompt)["summary"]["caption"]
        if kind != "caption"
        else plan.prompt
    )
    assert (
        caption.startswith(style + "\n\n")
        if style
        else caption.startswith("Character identity references")
    )
    for name, tag in NAMES.items():
        assert tag in caption and f'"{name}" = {tag}' in caption
    assert len(plan.prefixes["identity_references"]) == 2
    if kind != "caption":
        compiled = json.loads(plan.prompt)
        assert set(compiled) == {"summary", "items", "bbox_coord_space", "bbox_format"}
        assert "character_bindings" not in plan.prompt
        for item in compiled["items"]:
            if item["label"] == "character":
                name = next(name for name in NAMES if name in item["caption"])
                assert NAMES[name] in item["caption"]
                assert all(
                    tag not in item["caption"]
                    for other, tag in NAMES.items()
                    if other != name
                )
            elif item["label"] == "text":
                assert (
                    item["text"] == "你好" and "genshin_impact" not in item["caption"]
                )
    assert ctx.llm.generate.await_count == 3


@pytest.mark.parametrize("kind", ["caption", "comic", "lettered"])
def test_aliases_share_one_identity_without_extra_cast(kind):
    board, draft, evidence, extraction = media_inputs(kind, aliases=True)
    plan, _, _ = run_media(kind, board, [draft], evidence, extraction)
    assert plan.prefixes["identity_references"] == [
        {"canonical_tag": NAMES["荧"], "source_names": ["荧", "旅行者"]}
    ]
    caption = plan.draft["summary"]["caption"] if kind != "caption" else plan.prompt
    assert caption.count(NAMES["荧"]) == 1
    assert '"荧" / "旅行者" = ' in caption


def test_comic_scene_only_items_keep_bindings_without_forcing_more_people():
    board, draft, evidence, extraction = media_inputs("comic", scene_only=True)
    plan, _, _ = run_media("comic", board, [draft], evidence, extraction)
    items = json.loads(plan.prompt)["items"]
    assert len(items) == 2 and all(item["label"] == "object" for item in items)
    for item in items:
        assert all(tag in item["caption"] for tag in NAMES.values())


@pytest.mark.parametrize("kind", ["caption", "comic", "lettered"])
def test_unverified_evidence_never_becomes_a_canonical_binding(kind):
    board, draft, evidence, extraction = media_inputs(kind)
    for item in evidence:
        item["status"] = "source_unavailable"
    if kind != "caption":
        draft.pop("character_bindings")
    plan, _, _ = run_media(kind, board, [draft], evidence, extraction)
    assert not plan.prefixes["identity_references"]
    assert all(tag not in plan.prompt for tag in NAMES.values())


@pytest.mark.parametrize(
    "fault",
    [
        "missing",
        "duplicate",
        "unknown",
        "wrong_panel",
        "text",
        "shared_item",
        "boolean",
        "cross_panel",
        "empty_caption",
    ],
)
def test_bad_identity_bindings_repair_once_then_fail_closed(fault):
    board, draft, evidence, extraction = media_inputs("comic")
    broken = copy.deepcopy(draft)
    bindings = broken["character_bindings"]
    if fault == "missing":
        broken.pop("character_bindings")
    elif fault == "duplicate":
        bindings[-1] = copy.deepcopy(bindings[0])
    elif fault == "unknown":
        bindings[0]["source_name"] = "陌生人"
    elif fault == "wrong_panel":
        bindings[0]["panel_index"] = 8
    elif fault == "text":
        broken["draft"]["items"][bindings[0]["item_index"]]["label"] = "text"
    elif fault == "shared_item":
        bindings[1]["item_index"] = bindings[0]["item_index"]
    elif fault == "boolean":
        bindings[0]["item_index"] = True
    elif fault == "empty_caption":
        broken["draft"]["items"][bindings[0]["item_index"]]["caption"] = ""
    else:
        bindings[0]["item_index"] = bindings[-1]["item_index"]
    plan, ctx, _ = run_media("comic", board, [broken, draft], evidence, extraction)
    assert all(tag in plan.prompt for tag in NAMES.values())
    assert ctx.llm.generate.await_count == 4
    with pytest.raises(PlanningError, match="invalid_media_draft"):
        run_media("comic", board, [broken, broken], evidence, extraction)


@pytest.mark.parametrize("kind", ["caption", "comic", "lettered"])
def test_echoed_style_is_moved_from_suffix_to_prefix(kind):
    board, draft, evidence, extraction = media_inputs(kind)
    target = draft if kind == "caption" else draft["draft"]["summary"]
    target["caption"] += " ECHO_STYLE"
    plan, _, _ = run_media(
        kind, board, [draft], evidence, extraction, style="ECHO_STYLE"
    )
    caption = plan.prompt if kind == "caption" else plan.draft["summary"]["caption"]
    assert caption.startswith("ECHO_STYLE\n\n") and caption.count("ECHO_STYLE") == 1


@pytest.mark.parametrize("kind", ["comic", "lettered"])
def test_missing_depicted_is_repaired_before_media_research(kind):
    board, draft, evidence, extraction = media_inputs(kind)
    broken = copy.deepcopy(extraction)
    broken["characters"][0].pop("depicted")
    planner, ctx, resolver = make_planner(
        [
            {"success": True, "response": json.dumps(reply)}
            for reply in [broken, extraction, board, draft]
        ]
    )
    resolver.resolve.return_value = evidence
    capture = AsyncMock()
    plan = asyncio.run(
        planner.plan(
            ImageRequest(
                "荧和纳西妲休息，配字“你好”"
                if kind == "lettered"
                else "荧和纳西妲休息",
                1024,
                1024,
                "layout" if kind == "comic" else "caption",
                task_type="comic_page" if kind == "comic" else "meme",
            ),
            Planning(),
            capture,
        )
    )
    assert all(tag in plan.prompt for tag in NAMES.values())
    assert [call.args[0] for call in capture.await_args_list] == [
        "identity",
        "identity_repair",
        "story",
        "media_draft",
    ]
    assert ctx.llm.generate.await_count == 4


def test_style_is_not_removed_from_inside_ordinary_words():
    board, draft, evidence, extraction = media_inputs("caption")
    draft["caption"] = "Two friends drinking tea and thinking quietly."
    plan, _, _ = run_media("caption", board, [draft], evidence, extraction, style="ink")
    assert plan.prompt.startswith("ink\n\n")
    assert "drinking" in plan.prompt and "thinking" in plan.prompt


@pytest.mark.parametrize("kind", ["caption", "comic", "lettered"])
def test_runtime_submits_exact_saved_identity_bound_prompt(
    plugin, command, comfy_transport, kind
):
    board, draft, evidence, extraction = media_inputs(kind)
    route = "漫画" if kind == "comic" else "表情包"
    command["text"] = (
        f"/moss {route} 荧与纳西妲休息"
        + ("，配字“你好”" if kind == "lettered" else "")
        + " --尺寸 1024x1024"
    )
    plugin.config.planning.danbooru_enabled = True
    plugin.config.styles.presets = ["千代风格=RUNTIME_STYLE"]
    plugin.ctx.llm.generate.side_effect = [
        {"success": True, "response": json.dumps(reply)}
        for reply in [extraction, board, draft]
    ]

    async def run():
        await plugin.on_load()
        plugin.runner.planner.resolver.resolve = AsyncMock(return_value=evidence)
        try:
            await plugin.handle_moss(**command)
            await asyncio.gather(*list(plugin.jobs.values()))
            record = json.loads(
                next(plugin.store.records.glob("*.json")).read_text(encoding="utf-8")
            )
            assert record["status"] == "sent"
            directory = plugin.store.runtime / record["task_id"]
            graph = json.loads(
                next(
                    call.content
                    for call in comfy_transport
                    if call.url.path == "/prompt"
                )
            )["prompt"]
            submitted = graph["4"]["inputs"]["text"]
            for name in ("prompt.txt", "content_prompt.txt", "compiled_prompt.txt"):
                assert (directory / name).read_text(encoding="utf-8") == submitted
            caption = (
                submitted
                if kind == "caption"
                else json.loads(submitted)["summary"]["caption"]
            )
            assert caption.startswith("RUNTIME_STYLE\n\n")
            assert all(tag in submitted for tag in NAMES.values())
            assert "character_bindings" not in submitted
            prefixes = json.loads(
                (directory / "prefixes.json").read_text(encoding="utf-8")
            )
            assert len(prefixes["identity_references"]) == 2
            plugin.ctx.send.image.assert_awaited_once()
        finally:
            await plugin.on_unload()

    asyncio.run(run())


def test_storyboard_must_keep_verified_identity_instead_of_translating_binding():
    board, draft, evidence, extraction = media_inputs("comic")
    wrong = copy.deepcopy(board)
    for panel in wrong["panels"]:
        panel["characters"] = ["a generic girl"]
    planner, ctx, resolver = make_planner(
        [
            {"success": True, "response": json.dumps(reply)}
            for reply in [extraction, wrong, board, draft]
        ]
    )
    resolver.resolve.return_value = evidence
    plan = asyncio.run(
        planner.plan(
            ImageRequest(
                "荧与纳西妲休息", 1024, 1024, "layout", task_type="comic_page"
            ),
            Planning(),
        )
    )
    assert all(tag in plan.prompt for tag in NAMES.values())
    assert ctx.llm.generate.await_count == 4
