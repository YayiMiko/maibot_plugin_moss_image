"""Bounded private draw contracts; none of these fields are MOSS Layout fields."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

RULES_VERSION = "draw-v4"


class DrawError(RuntimeError):
    """Expose a bounded reason without retaining URLs or provider exceptions."""

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


class StrictRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Constraint(StrictRecord):
    """An explicit requirement backed by a literal span in the user's request."""

    source: str = Field(min_length=1, max_length=2048)
    requirement: str = Field(min_length=1, max_length=2048)


class SearchDirection(StrictRecord):
    """One visual exploration direction, independent of target character identity."""

    query: str = Field(min_length=1, max_length=300)
    design_intent: str = Field(min_length=1, max_length=1200)


class Brief(SearchDirection):
    constraints: list[Constraint] = Field(max_length=24)
    reference_requirements: list[Constraint] = Field(max_length=12)
    creative_freedom: str = Field(min_length=1, max_length=2048)
    alternatives: list[SearchDirection] = Field(min_length=2, max_length=2)


class Blueprint(StrictRecord):
    """Observed visual organization, explicitly separate from requested changes."""

    composition: str = Field(min_length=1, max_length=4096)
    subjects: str = Field(min_length=1, max_length=2048)
    light_palette: str = Field(min_length=1, max_length=2048)
    typography: str = Field(min_length=1, max_length=2048)
    medium_texture: str = Field(min_length=1, max_length=2048)
    design_relationships: list[str] = Field(min_length=1, max_length=6)
    remove_source_content: str = Field(min_length=1, max_length=2048)
    uncertainty: str = Field(max_length=1024)


class TemplateReview(StrictRecord):
    """Judge template suitability instead of assigning an aesthetic rating."""

    candidate_id: str = Field(pattern=r"^candidate-[1-3]$")
    template_usable: bool
    usable_relationships: list[str] = Field(default_factory=list, max_length=6)
    blocking_issues: list[str] = Field(default_factory=list, max_length=6)
    required_replacements: list[str] = Field(default_factory=list, max_length=6)
    has_target_subject: bool
    evidence: list[str] = Field(min_length=1, max_length=6)
    blueprint: Blueprint | None

    @model_validator(mode="after")
    def check_consistency(self) -> "TemplateReview":
        """Keep usable and unusable states explainable and mutually exclusive."""
        text_fields = [
            self.candidate_id,
            *self.usable_relationships,
            *self.blocking_issues,
            *self.required_replacements,
            *self.evidence,
        ]
        if self.blueprint is not None:
            text_fields.extend(
                [
                    self.blueprint.composition,
                    self.blueprint.subjects,
                    self.blueprint.light_palette,
                    self.blueprint.typography,
                    self.blueprint.medium_texture,
                    *self.blueprint.design_relationships,
                    self.blueprint.remove_source_content,
                ]
            )
        if any(not value.strip() for value in text_fields):
            raise ValueError("Review text fields must be nonempty")
        if self.template_usable:
            if self.blueprint is None:
                raise ValueError("Usable template requires a blueprint")
            if not self.usable_relationships:
                raise ValueError("Usable template requires design relationships")
            if self.blocking_issues:
                raise ValueError("Usable template cannot have blocking issues")
        else:
            if self.blueprint is not None:
                raise ValueError("Unusable template must not return a blueprint")
            if not self.blocking_issues:
                raise ValueError("Unusable template must explain the blocker")
        return self

    @property
    def usable(self) -> bool:
        """Gate only on template suitability and a concrete blueprint."""
        return (
            self.template_usable
            and self.blueprint is not None
            and not self.blocking_issues
        )


class Binding(StrictRecord):
    name: str = Field(min_length=1, max_length=200)
    item_index: int | None


class Adaptation(StrictRecord):
    """Export envelope checked before its official draft is compiled.

    ``keep``/``replace``/``remove``/``recompose`` are diagnostics only. They do
    not prove that the draft implements a requirement, so they are not gates.
    """

    keep: list[str] = Field(default_factory=list, max_length=12)
    replace: list[str] = Field(default_factory=list, max_length=12)
    remove: list[str] = Field(default_factory=list, max_length=12)
    recompose: list[str] = Field(default_factory=list, max_length=12)
    bindings: list[Binding] = Field(max_length=8)
    visible_texts: list[str] = Field(max_length=12)
    mode: Literal["caption", "layout"]
    draft: dict
