# MaiBot MOSS Image development instructions

This is an independent MaiBot plugin, not AstrBot core or the Anima plugin.
Use public MaiBot SDK APIs only. Never modify sibling projects, host persona,
account permissions, local ComfyUI workflows or live service configuration.

Keep explicit generate, caption, layout, style, character, comic, meme, metadata
and reverse routes. Show style/OC operations only in their submenus. Raw prompting
is removed. Do not add status, debug, task recovery, image editing, animated
memes, image-reference generation or multipage commands. OC use must be explicit;
only creators and configured library administrators may mutate an existing OC.
Comic storyboards are internal data; export only official flat Layout fields.
Draw is an explicit, opt-in text-to-image route: curated images are visual-analysis
references only, never ComfyUI image inputs. Stop at the first usable template,
review at most three images, read at most six work pages and submit one output.
Use template suitability, not aesthetic ratings, scores, popularity or manual
profiles; profiles and calibration are removed. Ignore obsolete profile
configuration without reading or deleting old user files. Preserve private key
redaction and public-only fetching. See aesthetic-draw.md. Real model/image
acceptance remains separate from offline checks.
Draw always excludes common style presets and fixed quality prefixes, including
the all-style setting; preserve visual styles explicitly written in its request.
Brief constraints must quote original user spans only. Brief and export each get at
most one bounded structural correction, still inside the shared model-call budget and
prepare deadline; provider refusal never triggers a correction.
Model-authored keep/replace/remove/recompose or coverage notes are diagnostics, not
proof of implementation; never use self-certifying prose as a generation gate.
Keep target identity separate from reference discovery. Open draws randomize
three visual directions before search without category quotas; explicit reference
themes stay grounded in original user spans. Keep two searches and separate page/
review ceilings. Preserve pending candidates with their original design direction.
Use approved artwork-article sources first, with Abduzeedo leading and X retained
as a supplementary fallback. For X, use Tavily status results, confirm the exact
post with its page and syndication media, and do not use Tavily image results as
the reference. Abduzeedo articles must resolve article-body artwork, not the
social hero or navigation image. Never log in, read cookies or run a resident
browser. Treat prompts, tutorials,
templates, sales language and AI-tool names as content hints only; never reject a
complete artwork from text alone. Objective rejects are non-posts, unconfirmed
association, no static image, avatars and read/decode failures. The reviewer judges
visible tutorial screenshots, placeholder templates, product photos and adaptation
against the actual image and request; do not ban typographic, product-themed or
commercial work globally. Do not use plain author-name queries; author extension
needs unvalidated `from:`/timeline work.
Queries discover existing works; they must not prescribe a full composition,
lighting scheme, material, pose, background or complete scene unless the user
explicitly requested it. Broad requests leave those open; three directions are
exploration angles, not fixed slots or hard requirements.
Choose the second search from the observed cause, not a fixed rotation: switch
to X after publisher search failure or empty discovery, and switch back to an
available publisher route after X network/page/association failures; change query
or direction after template rejection; preserve pending candidates and their
original direction. Record the search `reason` and `change`.
Canonicalize publisher URLs before duplicate checks, including Abduzeedo query
variants, Behance locale/module variants for historical records, and ArtStation
author subdomains. Behance's curated gallery is not an enabled route after its
bounded probe returned 403.
Count malformed and failed vision calls toward the three-review ceiling; never
retry provider refusals. Accept only one complete JSON fence before strict parsing.
Prefer scoped body artwork over social metadata, keeping the two-fetch page ceiling.
Treat exploration suggestions separately from original user constraints in reviews.
Record sanitized stage/HTTP evidence and never label unreadable inputs as
template-unusable. Mixed failures use a neutral user message.
Draw export may reject only objective structure, official compilation, verified
identity binding, explicit user text/count and canvas errors; never require model
self-certifying prose. In adaptation, preserve only the design relationships actually
present in this reference and compatible with the request; do not add double figures,
dark humanoid echoes, giant title occlusion, cuts or dense annotations as defaults.
If a secondary source figure has no target identity, consider its role and then keep
the relationship, replace it with a suitable non-figure element, or recompose; never
invent a named character and never retain an obvious extra humanoid as a "graphic
layer" when the user requires one person or one appearance. One identity is not a
person or appearance count: when the count is unspecified, coherent multiple views
of the same target identity may keep a present multi-figure relationship, and every
depicted instance of that supplied identity must carry its binding. Generic
background or secondary figures must not receive invented target tags. Explicit
user count wins.
Do not invent release dates, prices, awards, sales, platform
support or endorsements; remove source facts unless the user supplied them, while
retaining typography hierarchy without blanking all text.
Record a bounded export-failure category, whether a repair was attempted and why it
was skipped; never fabricate a provider refusal for budget exhaustion.

Official MOSS skill resources and compiler are vendored unchanged; preserve
their license, pinned provenance and hashes. Caption/Layout are not Danbooru
tag lists. Generate mode preserves the user's description without LLM expansion,
translation, tag cleaning or automatic backgrounds. Only optional character
identification may use the LLM; failures must not block direct generation.
Assemble frozen prefixes, styles and deduplicated verified identity references
without adding default appearances or subjects.
Reverse uses the host VLM and returns observed image tags without style injection.
Caption and Layout modes remain unwrapped. Never clean
Caption prose as a comma-separated tag list or invent an extra artist library.

Keep tasks, configuration, destinations and outputs request-local. Never read a
global latest image, cross-conversation quote or unrestricted local path.
Uncertain remote jobs and deliveries must never be retried automatically.
Only a successful receipt with a nonempty platform message ID confirms sending.
Do not follow symlinks or junctions in owned storage cleanup.

Verification is offline by default: block HTTP, mock LLM/ComfyUI/QQ calls and
do not deploy, restart services or generate real images without authorization.
The owner authorizes committing, pushing and deploying validated changes by
default. Recheck live task state and preserve runtime configuration and data;
restart only MaiBot when needed, never NapCat. New releases and real image
generation still require separate requests. Do not deploy failed checks.
Use an existing isolated Python environment or this project's environment;
do not resolve the unrelated parent AstrBot checkout's conflicts.
Use SDK 2.13.0 for ongoing local and CI validation, matching production. Do not
recreate SDK 2.8.2 environments or add it back to the test matrix. Historical
release compatibility declarations are not changed by this testing policy.

New comments and logs are English. Use Google-style docstrings for non-obvious
functions. Run Ruff, pytest, compile checks, resource hash checks and diff checks.
