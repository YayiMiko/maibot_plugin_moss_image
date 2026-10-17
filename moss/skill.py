"""Pinned official skill and compiler, without machine-local Codex paths."""

import copy
import hashlib
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class OfficialSkill:
    """Validate resources and delegate all layout arithmetic to upstream code."""

    def __init__(self):
        manifest = json.loads(
            (ROOT / "vendor/provenance.json").read_text(encoding="utf-8")
        )
        for name, source in manifest.items():
            for filename, expected in source["sha256"].items():
                if (
                    hashlib.sha256(
                        (ROOT / "vendor" / name / filename).read_bytes()
                    ).hexdigest()
                    != expected
                ):
                    raise ValueError("Pinned resource integrity check failed")
        skill_dir = ROOT / "vendor/moss_skill"
        self.instructions = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
        self.layout_instructions = (skill_dir / "references/layout.md").read_text(
            encoding="utf-8"
        )
        spec = importlib.util.spec_from_file_location(
            "moss_official_compiler", skill_dir / "scripts/compile_prompt.py"
        )
        self.compiler = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.compiler)
        self.revision = manifest["moss_skill"]["commit"]

    def parse(self, text: str):
        """Reject duplicate fields and nonfinite numbers in untrusted JSON."""
        return json.loads(
            text,
            object_pairs_hook=self.compiler.unique_object,
            parse_constant=self.compiler.reject_constant,
        )

    def compile(
        self, draft: dict, width: int, height: int, *, layout: bool = False
    ) -> str:
        """Compile a draft only when its canvas matches the generation canvas."""
        if not isinstance(draft, dict):
            raise ValueError("Draft must be a JSON object")
        if "caption" not in draft:
            if draft.get("width") != width or draft.get("height") != height:
                raise ValueError("Layout canvas differs from the requested dimensions")
        elif layout:
            raise ValueError("Explicit layout mode requires a Layout draft")
        return self.compiler.compile_prompt(draft)

    def validate_raw(self, text: str, width: int, height: int) -> None:
        """Validate model-facing Layout without rewriting a literal raw prompt.

        Args:
            text: Literal natural language or compiled Layout JSON.
            width: Actual generation width.
            height: Actual generation height.

        Raises:
            ValueError: JSON is not a valid compiled Layout for this canvas.
        """
        if not text.lstrip().startswith(("{", "[")):
            return
        original = self.parse(text)
        if not isinstance(original, dict) or set(original) != {
            "summary",
            "items",
            "bbox_coord_space",
            "bbox_format",
        }:
            raise ValueError("Raw JSON must be a compiled MOSS Layout")
        if (
            original["bbox_coord_space"] != "abs_centralized"
            or original["bbox_format"] != "yxyx"
        ):
            raise ValueError("Raw Layout requires abs_centralized/yxyx boxes")
        draft = copy.deepcopy(original)
        if not isinstance(draft["items"], list):
            raise ValueError("Layout items must be a list")
        for item in draft["items"]:
            box = item.get("bbox") if isinstance(item, dict) else None
            if (
                not isinstance(box, list)
                or len(box) != 4
                or any(type(n) is not int for n in box)
            ):
                raise ValueError("Compiled Layout boxes must be four integers")
            y1, x1, y2, x2 = box
            item["bbox"] = [
                x1 + width // 2,
                y1 + height // 2,
                x2 + width // 2,
                y2 + height // 2,
            ]
        draft.update(
            width=width, height=height, bbox_coord_space="abs", bbox_format="xyxy"
        )
        if self.parse(self.compile(draft, width, height, layout=True)) != original:
            raise ValueError("Invalid compiled Layout")
