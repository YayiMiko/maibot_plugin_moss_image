# Changelog

## Unreleased

- Replace implicit generation and raw prompting with explicit generate, forced Caption and Layout routes.
- Return generate mode to a single Anima-inspired English tag plan; freeze quality prefixes, identities and styles, then assemble them without official Caption expansion or compilation.
- Explain every main-menu command and canvas flag, including official expansion in Layout mode.
- Add single-image reverse prompting through the host's native VLM, isolated from generation prefixes and styles, with bounded latest-task diagnostics and long-result group forwards.
- Add a style submenu with selection, creation and editing, private persistence and independently scoped user/conversation selections.
- Normalize mixed-case candidate tags and retain original character names even when candidate validation or lookup fails.
- Reserve an empty OC context without exposing character management.
- Keep the mandatory host configuration callback and test all SDK lifecycle overrides.
- Retain the official skill, compiler, workflow models and uncertain-delivery safeguards unchanged.
- Withdraw the GitHub releases and tags for v0.1.0 and v0.1.1; preserve commit history and local installation archives.

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
