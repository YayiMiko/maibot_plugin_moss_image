# Changelog

## Unreleased

- Standardize ongoing local and CI tests on production SDK 2.13.0; remove the 2.8.2 matrix while retaining Windows/Linux and Python 3.12/3.13 coverage. Existing release artifacts and compatibility declarations are unchanged.

## v0.2.0 — 2026-10-18

- Add per-user/conversation style settings (`/moss 风格 设置 1` for generation only, `2` for generation/comics/memes by default), with backward-compatible style storage and immutable admission snapshots. Caption/Layout illustration routes, reverse and metadata remain style-free.
- Preserve media styles in legal global Caption/Layout descriptions before official compilation instead of relying on LLM copying; keep user intent separate, quality prefixes generation-only and pinned resources unchanged.
- Adapt official composition guidance for tool-less JSON planning instead of sending filesystem/shell instructions to the LLM; keep pinned resources unchanged and compile only in the host. Structural repairs treat previous tool-call text as data, never executable instructions.
- Add explicit OC management with stable appearance, separate optional wardrobe, aliases, owner/configured-admin mutation permissions and request-local snapshots; never select a default character or search OC names on Danbooru.
- Add one-page comics with 1–4 flexible panels, private storyboards and official flat Layout exports; retain recurring characters across panels and restore frozen visible wording through internal bindings.
- Add single static memes with square defaults, official Caption/Layout selection and explicit copy preservation without forced lettering or chibi style.
- Preserve direct-input generation, official pinned resources, model/ComfyUI configuration and at-most-once delivery.
- Accept natural canvas clauses such as `，比例4：3`, punctuation-adjacent legacy flags, full-width colons and optional spaces without rewriting the remaining description.
- Preserve quoted aspect-ratio text, accept repeated equivalent ratios and reject conflicting or malformed canvas instructions instead of silently using the default.
- Validate 360 offline plugin tests on SDK 2.8.2 and 2.13.0, plus 8 upstream compiler tests; retain configuration schema version `0.1.0` and migrate older style storage without replacing library data.

Server loading and source/configuration consistency are checked separately. Offline validation does not imply live image-generation, QQ delivery or visual-quality acceptance; this release does not automatically retry old tasks or generate test images.

## v0.1.2 — 2026-10-17

- Replace implicit generation and raw prompting with explicit generate, forced Caption and Layout routes.
- Make generate mode preserve the original user description without LLM expansion, translation, tag cleaning, official compilation or implicit white backgrounds; assemble fixed quality prefixes, styles and verified identity references only.
- Keep optional identity lookup separate, merge aliases and avoid duplicating canonical tags already present; research failures retain the original description without blocking generation.
- Compact the annotated main menu into seven lines, retaining official expansion descriptions and canvas examples.
- Add single-image reverse prompting through the host's native VLM, isolated from generation prefixes and styles, with bounded latest-task diagnostics and long-result group forwards.
- Add a style submenu with selection, creation and editing, private persistence and independently scoped user/conversation selections.
- Normalize mixed-case candidate tags and retain original character names even when candidate validation or lookup fails.
- Reserve an empty OC context without exposing character management.
- Keep the mandatory host configuration callback and test all SDK lifecycle overrides.
- Retain the official skill, compiler, workflow models and uncertain-delivery safeguards unchanged.
- Withdraw the GitHub releases and tags for v0.1.0 and v0.1.1; preserve commit history and local installation archives.
- Validate 183 offline plugin tests on SDK 2.8.2 and 2.13.0, plus 8 upstream compiler tests; preserve the existing configuration schema and runtime settings.

Server loading and source/configuration consistency are verified separately. This release does not claim live image-generation or visual-quality acceptance for the direct-input route.

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
