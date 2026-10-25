"""Bounded private draw contracts; none of these fields are MOSS Layout fields."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

RULES_VERSION = "draw-v3"


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

    category: Literal["poster", "illustration"]
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


class Review(StrictRecord):
    candidate_id: str = Field(pattern=r"^candidate-[1-3]$")
    rating: Literal["strong", "acceptable", "weak", "uncertain"]
    evidence: list[str] = Field(min_length=1, max_length=6)
    critical_flaws: list[str] = Field(max_length=6)
    fits_request: bool
    adaptable: bool
    complete_artwork: bool
    style_compatible: bool
    blueprint: Blueprint | None

    @property
    def eligible(self) -> bool:
        """Require independent quality, uncertainty and adaptation gates."""
        return (
            self.rating == "strong"
            and not self.critical_flaws
            and self.fits_request
            and self.adaptable
            and self.complete_artwork
            and self.style_compatible
            and self.blueprint is not None
        )


class Binding(StrictRecord):
    name: str = Field(min_length=1, max_length=200)
    item_index: int | None


class Adaptation(StrictRecord):
    """Export envelope checked before its official draft is compiled."""

    keep: list[str] = Field(min_length=1, max_length=12)
    replace: list[str] = Field(max_length=12)
    remove: list[str] = Field(max_length=12)
    recompose: list[str] = Field(max_length=12)
    constraint_sources: list[str] = Field(max_length=24)
    constraint_renderings: list[str] = Field(max_length=24)
    design_coverage: list[int] = Field(max_length=6)
    design_renderings: list[str] = Field(max_length=6)
    bindings: list[Binding] = Field(max_length=8)
    visible_texts: list[str] = Field(max_length=12)
    mode: Literal["caption", "layout"]
    draft: dict
