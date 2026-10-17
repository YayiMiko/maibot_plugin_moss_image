# Changelog

## v0.1.1 — 2026-10-17

- Move the configuration example, development instructions and changelog into `docs/`.
- Keep a minimal root `AGENTS.md` entry point so repository-wide agent instructions remain discoverable.
- Update README links and offline checks for the reorganized files.
- Preserve runtime behavior, the configuration schema and pinned vendor resources.

## v0.1.0 — 2026-10-17

Initial release of the independent MaiBot MOSS Image plugin.

- Four explicit routes: natural-language generation, Layout, raw prompting and image metadata extraction.
- Bundle the pinned official MOSS-Image Prompt Enhancer skill, compiler, references, tests and license; verify resource hashes on load.
- Keep editable Caption/Layout drafts separate from model-facing compiled prompts, with fixed canvas dimensions.
- Adapt Anima's evidence-based Danbooru character lookup without tag-cleaning or rewriting complete MOSS prompts.
- Use native MOSS INT8 workflow bindings, request-local configuration, unique outputs and message deduplication.
- Require explicit successful platform receipts; never automatically resubmit ambiguous remote jobs or resend uncertain deliveries.
- Deliver long group metadata results as a single forward card and retain bounded private latest-task LLM diagnostics.
- Reserve internal comic-page and meme task types without exposing unfinished commands.
- Validate 108 offline plugin tests on SDK 2.8.2 and 2.13.0, plus 8 upstream compiler tests; Ruff and compile checks pass.

This release does not deploy services or claim live QQ delivery, production loading, or image-quality acceptance.
