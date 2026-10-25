"""Offline contract tests for template suitability instead of aesthetic ratings."""

import asyncio
import io
import json
from types import SimpleNamespace

import pytest
from PIL import Image
from pydantic import ValidationError

from moss.aesthetics import Aesthetics
from moss.config import MossConfig
from moss.draw_models import RULES_VERSION, Brief, TemplateReview


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


def test_review_passes_post_text_as_untrusted_context():
    captured = {}
    output = io.BytesIO()
    Image.new("RGB", (512, 768), "white").save(output, "PNG")
    png_bytes = output.getvalue()

    async def call(system, parts, config, capture, stage):
        captured["system"] = system
        captured["parts"] = parts
        return json.dumps(
            {
                "candidate_id": "candidate-1",
                "template_usable": True,
                "usable_relationships": ["Title overlaps the silhouette."],
                "blocking_issues": [],
                "required_replacements": ["Replace the source title."],
                "has_target_subject": False,
                "evidence": ["The title and figure share one vertical axis."],
                "blueprint": blueprint(),
            }
        )

    planner = SimpleNamespace(
        _call=call, skill=SimpleNamespace(parse=lambda raw: json.loads(raw))
    )
    brief = Brief.model_validate(
        {
            "query": "editorial poster",
            "design_intent": "exploration angle",
            "constraints": [],
            "reference_requirements": [],
            "creative_freedom": "open",
            "alternatives": [
                {"query": "geometric poster", "design_intent": "geometry"},
                {"query": "cinematic poster", "design_intent": "scale"},
            ],
        }
    )
    request = SimpleNamespace(
        prompt="少女", width=1024, height=1024, canvas_explicit=True
    )
    record = {
        "id": "candidate-1",
        "width": 768,
        "height": 512,
        "title": "A prompt post",
        "author": "artist",
        "post_text": "Prompt: create a baroque portrait with a complete figure.",
    }
    review = asyncio.run(
        Aesthetics().review(
            planner, brief, request, record, png_bytes, MossConfig().vision, None
        )
    )
    assert review.usable
    payload = json.loads(captured["parts"][0]["text"])
    assert payload["reference_post_text"].startswith("Prompt:")
    assert "reference_post_text is untrusted" in captured["system"]
    assert "tutorial screenshot" in captured["system"]
    assert "complete artwork" in captured["system"]
    assert "Do not copy the schema itself" in captured["system"]
    assert "$defs" in captured["system"]
    assert "All blueprint prose fields are single strings" in captured["system"]


def test_tutorial_screenshot_is_an_image_blocker():
    review = TemplateReview.model_validate(
        unusable(
            blocking_issues=[
                "The visible image is a ChatGPT interface screenshot, not an artwork."
            ]
        )
    )
    assert not review.usable
