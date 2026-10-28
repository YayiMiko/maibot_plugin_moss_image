"""Real resolver paths use original names, live evidence and partial-result safety."""

import asyncio
import json
import logging
import time
from types import SimpleNamespace

import pytest
from test_media_planner import envelope, story

from moss.characters import CharacterResolver


def wiki_page(title, *names):
    """Build source-name evidence, distinct from a tag's mere existence."""
    return {"title": title, "other_names": list(names), "is_deleted": False}


def response(records=(), status=200):
    """Build the public read-only metadata response used by offline transports."""
    return SimpleNamespace(status_code=status, json=lambda: list(records))


@pytest.mark.parametrize(
    "hints", [[], ["卡提希娅_(鸣潮)"], ["cantarella_(wuthering_waves)"]]
)
def test_source_alias_evidence_recovers_missing_invalid_and_wrong_character_hints(
    monkeypatch, hints
):
    resolver = CharacterResolver(logging.getLogger("source-name"))
    correct = "cartethyia_(wuthering_waves)"
    calls = []

    def get(url, **kwargs):
        params = kwargs["params"]
        calls.append((url, params))
        if url.endswith("/wiki_pages.json"):
            assert params["search[other_names_match]"] == "卡提希娅"
            return response([wiki_page(correct, "Cartethyia", "卡提希娅")])
        if url.endswith("/tags.json"):
            assert params["search[name_matches]"] == correct
            return response([{"name": correct, "category": 4, "post_count": 2496}])
        pytest.fail("A verified source name must not search a guessed wrong identity")

    monkeypatch.setattr(resolver.module.requests, "get", get)
    monkeypatch.setattr(
        resolver.module, "_fetch_stable_identity_tags", lambda *a, **kw: ()
    )
    source = [{"source_name": "卡缇希娅", "copyright": "鸣潮", "candidates": hints}]
    result = resolver._lookup(source)[0]
    assert result["canonical_tag"] == correct and result["status"] == "verified"
    assert result["identity_basis"] == "published_other_name"
    before = len(calls)
    resolver._lookup([{**source[0], "candidates": ["invented_other_character"]}])
    assert len(calls) == before


def test_existing_wrong_tag_is_not_identity_evidence(monkeypatch):
    resolver = CharacterResolver(logging.getLogger("wrong-existing-tag"))
    wrong = "cantarella_(wuthering_waves)"

    def get(url, **kwargs):
        if url.endswith("/tags.json"):
            return response([{"name": wrong, "category": 4, "post_count": 1990}])
        if url.endswith("/wiki_pages.json"):
            return response([wiki_page(wrong, "Cantarella", "坎特蕾拉")])
        return response()

    monkeypatch.setattr(resolver.module.requests, "get", get)
    result = resolver._lookup([{"source_name": "卡缇希娅", "candidates": [wrong]}])[0]
    assert result["status"] == "unresolved" and "canonical_tag" not in result
    assert result["lookup_reason"] == "identity_unconfirmed"


@pytest.mark.parametrize("kind", ["multiple", "partial", "deleted", "general"])
def test_source_wiki_never_turns_ambiguous_or_non_character_matches_into_verified_identity(
    monkeypatch, kind
):
    resolver = CharacterResolver(logging.getLogger("wiki-boundaries"))

    def get(url, **kwargs):
        if url.endswith("/wiki_pages.json"):
            page = wiki_page("name_(game)", "角色原名")
            if kind == "multiple":
                return response([page, wiki_page("other_(game)", "角色原名")])
            if kind == "partial":
                page["other_names"] = ["角色原名的同名人物"]
            if kind == "deleted":
                page["is_deleted"] = True
            return response([page])
        if url.endswith("/tags.json"):
            return response([{"name": "name_(game)", "category": 0, "post_count": 10}])
        return response()

    monkeypatch.setattr(resolver.module.requests, "get", get)
    result = resolver._lookup([{"source_name": "角色原名", "candidates": []}])[0]
    assert result["status"] != "verified"


@pytest.mark.parametrize(
    "hints", [[], ["卡提希娅_(鸣潮)"], ["cantarella_(wuthering_waves)"]]
)
def test_real_planner_keeps_original_body_and_submits_source_verified_identity(
    plugin, command, comfy_transport, monkeypatch, hints
):
    plugin.config.planning.danbooru_enabled = True
    body = "鸣潮角色卡缇希娅在教堂里祈祷"
    command["text"] = "/moss 生成 " + body
    plugin.ctx.llm.generate.return_value = {
        "success": True,
        "response": json.dumps(
            {
                "characters": [
                    {
                        "source_name": "卡缇希娅",
                        "copyright": "鸣潮",
                        "candidates": hints,
                        "depicted": True,
                    }
                ]
            }
        ),
    }

    def get(url, **kwargs):
        if url.endswith("/wiki_pages.json"):
            return response([wiki_page("cartethyia_(wuthering_waves)", "卡提希娅")])
        return response(
            [{"name": "cartethyia_(wuthering_waves)", "category": 4, "post_count": 100}]
        )

    async def run():
        await plugin.on_load()
        resolver = plugin.runner.planner.resolver
        monkeypatch.setattr(resolver.module.requests, "get", get)
        monkeypatch.setattr(
            resolver.module, "_fetch_stable_identity_tags", lambda *a, **kw: ()
        )
        try:
            await plugin.handle_moss(**command)
            await asyncio.gather(*list(plugin.jobs.values()))
            submission = next(
                call for call in comfy_transport if call.url.path == "/prompt"
            )
            prompt = json.loads(submission.content)["prompt"]["4"]["inputs"]["text"]
            assert prompt.endswith(body)
            assert "cartethyia_(wuthering_waves)" in prompt
            assert "cantarella_" not in prompt and "卡提希娅_(鸣潮)" not in prompt
            assert plugin.ctx.llm.generate.await_count == 1
        finally:
            await plugin.on_unload()

    asyncio.run(run())


@pytest.mark.parametrize(
    "hints",
    [
        [],
        ["luoxi_(arknights_endfield)"],
        ["ROSSI_(ARKNIGHTS:ENDFIELD)"],
        ["invented_name"],
    ],
)
def test_known_original_name_supplies_online_verified_candidate(monkeypatch, hints):
    resolver = CharacterResolver(logging.getLogger("alias"))
    calls = []

    def get(url, **kwargs):
        calls.append((url, kwargs.get("params")))
        assert url.endswith("/tags.json")
        assert kwargs["params"]["search[name_matches]"] == "rossi_(arknights)"
        return response(
            [{"name": "rossi_(arknights)", "category": 4, "post_count": 2200}]
        )

    monkeypatch.setattr(resolver.module.requests, "get", get)
    monkeypatch.setattr(
        resolver.module, "_fetch_stable_identity_tags", lambda *a, **kw: ()
    )
    source = [
        {"source_name": "洛茜", "copyright": "明日方舟终末地", "candidates": hints}
    ]
    result = resolver._lookup(source)[0]
    assert (
        result["status"] == "verified"
        and result["canonical_tag"] == "rossi_(arknights)"
    )
    assert result["candidate_source"] == "source_alias_and_hints"
    assert result["lookup_reason"] == "verified_online"
    assert result["lookup_trace"][0]["status_code"] == 200 and len(calls) == 1
    resolver._lookup(source)
    assert len(calls) == 1


@pytest.mark.parametrize(
    "failure",
    ["missing", "http403", "timeout", "deprecated", "general", "invalid_json"],
)
def test_local_alias_is_never_treated_as_online_evidence(monkeypatch, failure):
    resolver = CharacterResolver(logging.getLogger("alias-failure"))

    def get(url, **kwargs):
        if failure == "timeout":
            raise resolver.module.requests.Timeout("private error details")
        if failure == "invalid_json":
            return (
                response(status=200)
                if url.endswith("autocomplete.json")
                else SimpleNamespace(status_code=200, json=lambda: {"error": "private"})
            )
        if failure == "http403":
            return response(status=403)
        if failure in {"general", "deprecated"} and url.endswith("tags.json"):
            return response(
                [
                    {
                        "name": "rossi_(arknights)",
                        "category": 0 if failure == "general" else 4,
                        "post_count": 22,
                        "is_deprecated": failure == "deprecated",
                    }
                ]
            )
        return response()

    monkeypatch.setattr(resolver.module.requests, "get", get)
    result = resolver._lookup([{"source_name": "洛茜", "candidates": []}])[0]
    assert result["status"] != "verified"
    assert result["lookup_reason"] != "verified_online"
    assert result["candidates"] == ["rossi_(arknights)"]
    assert "private" not in json.dumps(result)
    if failure in {"http403", "timeout"}:
        assert result["status"] == "source_unavailable"
        assert result["lookup_reason"] == "source_unavailable"
        assert result["lookup_trace"]


@pytest.mark.parametrize("hints", [[], ["wrong_romanization"], ["wrong_name_(game)"]])
def test_autocomplete_alone_cannot_verify_unrelated_identity(monkeypatch, hints):
    resolver = CharacterResolver(logging.getLogger("original"))

    def get(url, **kwargs):
        if (
            url.endswith("autocomplete.json")
            and kwargs["params"]["search[query]"] == "角色原名"
        ):
            return response(
                [{"value": "correct_name_(game)", "category": 4, "post_count": 100}]
            )
        return response()

    monkeypatch.setattr(resolver.module.requests, "get", get)
    monkeypatch.setattr(
        resolver.module, "_fetch_stable_identity_tags", lambda *a, **kw: ()
    )
    result = resolver._lookup([{"source_name": "角色原名", "candidates": hints}])[0]
    assert result["status"] == "unresolved" and "canonical_tag" not in result
    assert result["lookup_reason"] == "identity_unconfirmed"
    assert any(item["query"] == "角色原名" for item in result["lookup_trace"])


def test_autocomplete_accepts_exact_source_name_with_character_category(monkeypatch):
    resolver = CharacterResolver(logging.getLogger("exact-name"))

    def get(url, **kwargs):
        if url.endswith("autocomplete.json"):
            return response(
                [{"value": "alice_(game)", "category": 4, "post_count": 100}]
            )
        return response()

    monkeypatch.setattr(resolver.module.requests, "get", get)
    monkeypatch.setattr(
        resolver.module, "_fetch_stable_identity_tags", lambda *a, **kw: ()
    )
    result = resolver._lookup([{"source_name": "Alice", "candidates": []}])[0]
    assert result["status"] == "verified"
    assert result["canonical_tag"] == "alice_(game)"


def test_direct_generation_does_not_inject_autocomplete_guess(
    plugin, command, comfy_transport, monkeypatch
):
    plugin.config.planning.danbooru_enabled = True
    command["text"] = "/moss 生成 角色原名在雨中"
    plugin.ctx.llm.generate.return_value = {
        "success": True,
        "response": json.dumps(
            {
                "characters": [
                    {"source_name": "角色原名", "candidates": [], "depicted": True}
                ]
            }
        ),
    }

    def get(url, **kwargs):
        if url.endswith("autocomplete.json"):
            return response(
                [{"value": "unrelated_(game)", "category": 4, "post_count": 100}]
            )
        return response()

    async def run():
        await plugin.on_load()
        monkeypatch.setattr(plugin.runner.planner.resolver.module.requests, "get", get)
        try:
            await plugin.handle_moss(**command)
            await asyncio.gather(*list(plugin.jobs.values()))
            submission = next(
                call for call in comfy_transport if call.url.path == "/prompt"
            )
            prompt = json.loads(submission.content)["prompt"]["4"]["inputs"]["text"]
            assert prompt.endswith("角色原名在雨中")
            assert "unrelated_(game)" not in prompt
        finally:
            await plugin.on_unload()

    asyncio.run(run())


@pytest.mark.parametrize("kind", ["ambiguous", "wrong_work"])
def test_autocomplete_never_chooses_popular_namesake(monkeypatch, kind):
    resolver = CharacterResolver(logging.getLogger("ambiguous"))

    def get(url, **kwargs):
        if url.endswith("autocomplete.json"):
            if kind == "ambiguous":
                return response(
                    [
                        {"value": "name_(game)", "category": 4, "post_count": 10},
                        {"value": "name_(other)", "category": 4, "post_count": 99999},
                    ]
                )
            return response(
                [{"value": "pandora_(other_game)", "category": 4, "post_count": 99999}]
            )
        return response()

    monkeypatch.setattr(resolver.module.requests, "get", get)
    result = resolver._lookup(
        [
            {
                "source_name": "潘多拉",
                "candidates": [] if kind == "ambiguous" else ["pandora_(re:zero)"],
            }
        ]
    )[0]
    assert result["status"] == "unresolved" and "canonical_tag" not in result
    assert result["lookup_reason"] == (
        "identity_unconfirmed" if kind == "ambiguous" else "work_mismatch"
    )


@pytest.mark.parametrize("slow_stage", ["appearance", "second_identity"])
def test_timeout_keeps_verified_partial_results_and_worker_slot(
    monkeypatch, slow_stage
):
    resolver = CharacterResolver(logging.getLogger("partial"))

    def get(url, **kwargs):
        if kwargs.get("params", {}).get("search[name_matches]") == "rossi_(arknights)":
            return response([{"name": "rossi_(arknights)", "category": 4}])
        time.sleep(0.08)
        return response()

    def appearance(*args, **kwargs):
        time.sleep(0.3)
        return ()

    monkeypatch.setattr(resolver.module.requests, "get", get)
    monkeypatch.setattr(resolver.module, "_fetch_stable_identity_tags", appearance)

    async def run():
        characters = [{"source_name": "洛茜", "candidates": []}]
        if slow_stage == "second_identity":
            characters.append(
                {"source_name": "另一角色", "candidates": ["other_(game)"]}
            )
        result = await resolver.resolve(
            characters, 0.04 if slow_stage == "second_identity" else 0.2
        )
        if slow_stage == "appearance":
            assert result[0]["status"] == "verified"
            assert resolver.slots._value == 1 and resolver.pending
        else:
            assert resolver.slots._value == 1 and resolver.pending
            assert result[1]["lookup_reason"] == "lookup_budget_exhausted"
        assert result[0]["canonical_tag"] == "rossi_(arknights)"
        await asyncio.gather(*list(resolver.pending))

    asyncio.run(run())


@pytest.mark.parametrize("route", ["生成", "漫画", "表情包"])
def test_rossi_real_resolver_survives_to_submitted_workflow(
    plugin, command, comfy_transport, monkeypatch, route
):
    plugin.config.planning.danbooru_enabled = True
    command["text"] = f"/moss {route} 明日方舟终末地角色洛茜采蘑菇 --尺寸 1024x1024"
    identity = {
        "characters": [
            {
                "source_name": "洛茜",
                "copyright": "明日方舟终末地",
                "depicted": True,
                "candidates": ["luoxi_(arknights_endfield)"],
            }
        ]
    }
    replies = [identity]
    if route != "生成":
        board = story(1)
        board["panels"][0]["characters"] = ["洛茜"]
        draft = {"caption": "Rossi gathers mushrooms."}
        if route == "漫画":
            draft = envelope(board)
            draft["character_bindings"] = [
                {"source_name": "洛茜", "panel_index": 0, "item_index": 1}
            ]
        replies += [board, draft]
    plugin.ctx.llm.generate.side_effect = [
        {"success": True, "response": json.dumps(reply)} for reply in replies
    ]

    async def run():
        await plugin.on_load()
        resolver = plugin.runner.planner.resolver
        monkeypatch.setattr(
            resolver.module.requests,
            "get",
            lambda *a, **kw: response([{"name": "rossi_(arknights)", "category": 4}]),
        )
        monkeypatch.setattr(
            resolver.module, "_fetch_stable_identity_tags", lambda *a, **kw: ()
        )
        try:
            await plugin.handle_moss(**command)
            await asyncio.gather(*list(plugin.jobs.values()))
            record = json.loads(
                next(plugin.store.records.glob("*.json")).read_text(encoding="utf-8")
            )
            assert record["status"] == "sent"
            assert record["characters"][0]["lookup_reason"] == "verified_online"
            assert record["characters"][0]["lookup_trace"][0]["status_code"] == 200
            submitted = json.loads(
                next(
                    call.content
                    for call in comfy_transport
                    if call.url.path == "/prompt"
                )
            )["prompt"]["4"]["inputs"]["text"]
            assert "rossi_(arknights)" in submitted and "luoxi_" not in submitted
            assert (plugin.store.runtime / record["task_id"] / "prompt.txt").read_text(
                encoding="utf-8"
            ) == submitted
        finally:
            await plugin.on_unload()

    asyncio.run(run())
