"""Export boundaries, including the sanitized 71985b real failure structure."""

import asyncio
import copy
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from moss.draw import (
    CallBudget,
    ExportCheckError,
    export_repair_skip_reason,
    validate_export,
)
from moss.draw_models import Adaptation, DrawError
from moss.skill import OfficialSkill

FIXTURE = Path(__file__).parent / "fixtures" / "draw_adapt_71985b.json"


def load_fixture():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def validate(fixture, *, single=False):
    exported = Adaptation.model_validate(fixture)
    return validate_export(
        exported,
        SimpleNamespace(width=1360, height=768),
        [
            {
                "source_name": "样例角色",
                "canonical_tag": "",
                "status": "unverified",
            }
        ],
        {"样例角色": ["样例角色"]},
        [],
        False,
        single,
        OfficialSkill().compile,
    )


def test_real_failure_structure_passes_without_self_certification():
    fixture = load_fixture()
    assert "constraint_renderings" not in fixture
    assert "design_coverage" not in fixture
    # The unnamed companions stay generic character items without a target tag.
    assert fixture["draft"]["items"][4]["label"] == "character"
    assert [binding["item_index"] for binding in fixture["bindings"]] == [0]
    prompt = validate(fixture)
    assert "样例角色" in prompt
    assert "SAMPLE//TITLE" in prompt
    assert "Sample Series" in prompt


def test_self_certification_fields_are_not_globally_ignored():
    fixture = load_fixture()
    fixture["constraint_renderings"] = ["The subject is the character."]
    with pytest.raises(ValidationError):
        Adaptation.model_validate(fixture)


def test_wrong_identity_binding_is_still_blocked():
    fixture = load_fixture()
    fixture["bindings"] = [{"name": "Other Character", "item_index": 0}]
    with pytest.raises(ExportCheckError) as exc:
        validate(fixture)
    assert exc.value.category == "identity_binding"


def test_explicit_visible_text_mismatch_is_still_blocked():
    fixture = load_fixture()
    fixture["visible_texts"] = ["SAMPLE//TITLE", "Sample Series", "Coming 2099"]
    with pytest.raises(ExportCheckError) as exc:
        validate(fixture)
    assert exc.value.category == "explicit_text_mismatch"


def test_invalid_canvas_is_still_blocked():
    fixture = load_fixture()
    fixture["draft"]["width"] = 1024
    with pytest.raises(ExportCheckError) as exc:
        validate(fixture)
    assert exc.value.category == "official_compile"


def test_missing_identity_binding_is_still_blocked():
    fixture = load_fixture()
    fixture["bindings"] = []
    with pytest.raises(ExportCheckError) as exc:
        validate(fixture)
    assert exc.value.category == "identity_binding"


def test_one_identity_may_bind_multiple_character_views():
    fixture = copy.deepcopy(load_fixture())
    first, second = fixture["draft"]["items"][0], fixture["draft"]["items"][4]
    assert first["label"] == second["label"] == "character"
    second["caption"] = (
        "Sample Hero from Sample Series in a second back view: the same long "
        "blonde hair, pointed elf ears, blue eyes and ornate pale-and-crimson "
        "armor, standing among the distant companions."
    )
    fixture["bindings"] = [
        {"name": "样例角色", "item_index": 0},
        {"name": "样例角色", "item_index": 4},
    ]
    compiled = json.loads(validate(fixture))
    characters = [item for item in compiled["items"] if item["label"] == "character"]
    assert len(characters) == 2
    assert all("样例角色 = 样例角色" in item["caption"] for item in characters)


def test_explicit_single_rejects_multiple_identity_views():
    fixture = copy.deepcopy(load_fixture())
    fixture["draft"]["items"][4]["caption"] = (
        "Sample Hero from Sample Series in a second back view: the same long "
        "blonde hair, pointed elf ears, blue eyes and ornate pale-and-crimson armor."
    )
    fixture["bindings"].append({"name": "样例角色", "item_index": 4})
    with pytest.raises(ExportCheckError) as exc:
        validate(fixture, single=True)
    assert exc.value.category == "explicit_subject_count"


def test_repeating_an_identity_on_the_same_item_is_still_blocked():
    fixture = load_fixture()
    fixture["bindings"].append({"name": "样例角色", "item_index": 0})
    with pytest.raises(ExportCheckError) as exc:
        validate(fixture)
    assert exc.value.category == "identity_binding"


def test_diagnostic_notes_are_optional():
    fixture = copy.deepcopy(load_fixture())
    for key in ("keep", "replace", "remove", "recompose"):
        fixture[key] = []
    validate(fixture)


def test_export_repair_skip_reason_is_explicit():
    assert export_repair_skip_reason(8, 0, 180) == "model_call_budget"
    assert export_repair_skip_reason(7, 166, 180) == "prepare_deadline"
    assert export_repair_skip_reason(7, 0, 180) == ""


def test_call_budget_never_exceeds_eight():
    llm = SimpleNamespace(
        generate=AsyncMock(return_value={"success": True, "response": "{}"})
    )
    budget = CallBudget(llm)

    async def run():
        for _ in range(8):
            await budget.generate()
        with pytest.raises(DrawError) as exc:
            await budget.generate()
        assert exc.value.reason == "budget_exhausted"

    asyncio.run(run())
    assert budget.calls == 8
    assert llm.generate.await_count == 8
