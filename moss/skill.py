"""Pinned official skill and compiler, without machine-local Codex paths."""

import hashlib
import importlib.util
import json
import re
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
        upstream = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
        # Keep upstream files intact; a tool-less LLM is not a filesystem agent.
        guidance = upstream[
            upstream.index("## Choose the deliverable") : upstream.index(
                "## Compile and deliver"
            )
        ]
        guidance = guidance.replace(
            'Write a UTF-8 JSON file containing exactly `{"caption":"..."}`.',
            'Return a JSON object containing exactly `{"caption":"..."}`.',
        ).replace(
            "Read [references/layout.md](references/layout.md) before writing a Layout draft.",
            "For Layout drafts, follow the reference supplied in this system message.",
        )
        self.instructions = (
            "HOST JSON-ONLY PLANNER CONTRACT: You are a tool-less JSON planning endpoint, "
            "not an interactive filesystem or shell agent. All necessary guidance is supplied "
            "in this message. The host alone saves files, invokes the official compiler, "
            "validates coordinates and submits images. Do not read or locate files, run "
            "commands, request tools or simulate tool calls. Return only the JSON object "
            "required by the current stage, starting with { and ending with }. No preamble, "
            "Markdown fences, file links, executable code, tool-call markup or compiled "
            "coordinates. For a private storyboard or export envelope, follow the stage "
            "schema below; the official guidance describes image composition, not extra "
            "output fields or operational steps.\n\n" + guidance.strip()
        )
        self.layout_instructions = (
            (skill_dir / "references/layout.md")
            .read_text(encoding="utf-8")
            .replace(
                "Recompile after every geometry or canvas edit.",
                "The host recompiles after every geometry or canvas edit.",
            )
        )
        spec = importlib.util.spec_from_file_location(
            "moss_official_compiler", skill_dir / "scripts/compile_prompt.py"
        )
        self.compiler = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.compiler)
        self.revision = manifest["moss_skill"]["commit"]

    def parse(self, text: str):
        """Unwrap one complete JSON fence, retaining strict JSON validation."""
        text = text.strip()
        fenced = re.fullmatch(
            r"```(?:json)?[ \t]*\r?\n(.*?)\r?\n```", text, re.S | re.I
        )
        if fenced:
            text = fenced[1]
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
