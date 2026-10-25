# Changelog

## Unreleased

- Replace draw aesthetic ratings with a template-suitability contract: judge whether the actual image's composition, relationships and typography can be adapted, require a blueprint only when usable, and stop on the first usable reference. Remove personal profiles, score gates and separate quality booleans.
- Prefer public X status posts for draw discovery, confirm the exact post with page metadata and syndication media, and reject only objective failures: non-posts, unconfirmed association, no static image, avatars and read/decode errors. Prompts, tutorials, templates, sales language and AI-tool names are content hints, not hard rejections; the actual image and request decide. Never use Tavily image results as the reference and never require X API or a browser login.
- Keep X as the priority route but choose the second search from the failure cause: switch source after X network/page/association failures, change query or direction after empty discovery or template rejection, and preserve pending candidates with their original direction. Record the search reason and change; keep two searches, six work pages, two image URLs per page and three visual reviews. Canonicalize publisher URLs to collapse Behance locale/module duplicates and accept ArtStation author subdomains.
- Make discovery queries short and work-oriented instead of prescribing a finished composition, lighting, material, pose or background; broad requests keep those open and take the design from the selected reference.
- Distinguish empty discovery, unreadable references, template rejection, invalid review, actual duplicate/canvas problems and mixed failures. Use a neutral mixed-failure message instead of reporting duplicates or canvas issues that did not occur.
- Accept one complete JSON code fence before strict parsing, preserving duplicate/nonfinite-field rejection. Count every draw vision attempt, retain pending candidates after malformed reviews and distinguish invalid, rejected, mixed and unavailable outcomes without retrying refusals.
- Prefer scoped Pentagram/It's Nice That article artwork over social thumbnails with a bounded metadata fallback. Record image provenance, prioritize individual work reports over explicit trend collections and separate provisional exploration from user requirements during visual review.

- Redesign draw as automatic curation without personal taste profiles, anchors, calibration or import tooling; ignore obsolete configuration fields without touching old user data.
- Preserve a request-local candidate pool with each work's design intent. Recover pending works after empty/failed supplemental searches, change sources after read failures and explore a new direction after visual rejection.
- Separate six work-page attempts from three visual reviews, retain two searches and the existing shared model/deadline limits. Prefer editorial sources, accept explicit bare-domain aliases and creative features, report filtered result reasons and try at most two page-associated image URLs.
- Judge the actual image with built-in visual criteria and reconstruct 1–6 transferable design relationships in the same call. Preserve official compilation, verified character bindings, explicit canvas and at-most-once image delivery.

- Separate target identities from reference discovery and randomize visual directions before search. Open draws explore available poster/illustration categories, retain specific reference themes when present, and reject character/franchise-locked search terms before HTTP. Extend built-in publication channels with Pentagram and It's Nice That, retaining page-image validation and the existing three-candidate/two-search limits.
- Record bounded discovery counts and sanitized page/image/decode failure evidence including available HTTP status; distinguish empty discovery, unreadable references, incompatible inputs and actual visual rejection. Keep unattempted metadata candidates eligible across complementary searches and prioritize source diversity.
- Exclude common style presets and quality prefixes from draw at both admission and planning boundaries, even under the all-style setting; preserve visual styles explicitly requested by the user. Separate brief constraints from nonexistent preset context, share one structural correction across brief/export, and report brief validation/provider failures before reference search.
- Add opt-in `/moss 抽卡` with source-scoped Tavily discovery, verified-page image associations, automatic visual admission and blueprint extraction in one call, and official Caption/Layout adaptation. Stop at the first eligible reference, review at most three images, read at most six pages, prepare within 180 seconds by default and submit one image through the existing delivery boundary.
- Preserve explicit canvas or inherit the reference ratio, and retain verified character/explicit OC bindings in draw without common style presets. Add bounded public-only HTTPS fetching and reference retention, and exclude search credentials from all task snapshots. Draw defaults to disabled on new installations; real source/model/image acceptance remains separate.
- Bind candidate tags to independently queried original-name wiki aliases or existing explicit aliases before treating tag existence as identity verification. Resolve published alternate names even when the LLM returns Chinese or wrong-character candidates; cache source-name evidence without caching LLM guesses. Recognize the existing Cartethyia spelling variant without rewriting user descriptions.
- Clarify ASCII canonical-tag hints in identity extraction, and add offline regressions for same-work wrong identities, missing/invalid hints, ambiguous aliases and final workflow submissions. Preserve the v0.2.0 direct-input boundary, existing media/style fixes, rendering settings and pinned official resources.
- Prune redundant style/media parameter combinations and prompt-string assertions; retain original-name online-resolution paths, rejection/timeout boundaries and final workflow assertions rather than using test count as acceptance evidence.
- Resolve extracted original names through known alias hints and online exact/autocomplete metadata, rather than depending only on LLM romanization. Local aliases still require live character-category evidence; ambiguous or cross-work names are not selected by popularity.
- Preserve per-task candidates, bounded HTTP traces and specific lookup reasons. Publish verified identities before optional appearance requests and retain request-local partial results when the lookup budget expires.
- Preserve verified Danbooru identity bindings through comic/meme exports, validate per-panel/item references, and inject canonical tags in legal Caption/Layout descriptions rather than relying on LLM copying. Unverified identities remain unverified and OC names are never inferred.
- Make media styles actual prefixes of Caption or `summary.caption`, relocating exact echoed styles without rewriting ordinary words, drawing preset text or changing standalone Caption/Layout routes.
- Include boolean depiction in the identity JSON example, distinguish missing fields from exclusions with one bounded repair, and clarify adjacent name/expression boundaries. Direct generation continues to preserve the user's original description when optional research fails.
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
