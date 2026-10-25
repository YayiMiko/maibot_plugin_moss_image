"""Offline contract tests for template suitability instead of aesthetic ratings."""

import pytest
from pydantic import ValidationError

from moss.draw_models import RULES_VERSION, TemplateReview


def blueprint():
    return {
        "composition": "Central figure under a full-width title block.",
        "subjects": "One standing figure.",
        "light_palette": "Warm key light with a deep red field.",
        "typography": "Condensed uppercase title.",
        "medium_texture": "Flat ink with paper grain.",
        "design_relationships": ["Title overlaps the silhouette."],
        "remove_source_content": "Source title, brand and cast names.",
        "uncertainty": "",
    }


def usable(**updates):
    payload = {
        "candidate_id": "candidate-1",
        "template_usable": True,
        "usable_relationships": ["Title overlaps the silhouette."],
        "blocking_issues": [],
        "required_replacements": ["Replace the source title and cast."],
        "has_target_subject": False,
        "evidence": ["The title and figure share one vertical axis."],
        "blueprint": blueprint(),
    }
    payload.update(updates)
    return payload


def unusable(**updates):
    payload = {
        "candidate_id": "candidate-2",
        "template_usable": False,
        "usable_relationships": [],
        "blocking_issues": ["The alphabet has no subject structure."],
        "required_replacements": [],
        "has_target_subject": False,
        "evidence": ["Repeated letterforms form a grid."],
        "blueprint": None,
    }
    payload.update(updates)
    return payload


def test_usable_template_does_not_require_the_target_character():
    review = TemplateReview.model_validate(usable())
    assert review.usable
    assert review.has_target_subject is False


def test_unusable_template_requires_a_concrete_blocker():
    review = TemplateReview.model_validate(unusable())
    assert not review.usable
    assert review.blocking_issues


@pytest.mark.parametrize(
    "payload",
    [
        usable(blueprint=None),
        usable(usable_relationships=[]),
        usable(blocking_issues=["Would require a full redraw."]),
        unusable(blocking_issues=[]),
        unusable(blueprint=blueprint()),
        usable(evidence=[]),
        usable(candidate_id="candidate-9"),
        {**usable(), "rating": "strong"},
    ],
)
def test_invalid_template_states_are_rejected(payload):
    with pytest.raises(ValidationError):
        TemplateReview.model_validate(payload)


def test_contract_has_no_rating_or_score_field():
    schema = TemplateReview.model_json_schema()
    assert "rating" not in schema["properties"]
    assert "score" not in schema["properties"]
    assert RULES_VERSION == "draw-v4"
