# MaiBot MOSS Image development instructions

This is an independent MaiBot plugin, not AstrBot core or the Anima plugin.
Use public MaiBot SDK APIs only. Never modify sibling projects, host persona,
account permissions, local ComfyUI workflows or live service configuration.

## Repository layout

- `plugin.py` is the MaiBot SDK entry point; `_manifest.json` and
  `pyproject.toml` are plugin/package metadata.
- `moss/` contains runtime code.
- `assets/comfyui/` holds the bundled ComfyUI API graph and other runtime JSON
  assets. It is not a GitHub Actions directory; CI lives only under
  `.github/workflows/`.
- `vendor/` holds pinned upstream skill/compiler resources and provenance.
- `tests/` is the offline test suite; `docs/` contains operator and developer
  documentation. `README.md`, `LICENSE` and `NOTICE` stay at the repository root.

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
Draw uses only explicitly selected style snapshots and excludes fixed quality prefixes; keep style contents out of reference searches.
Brief constraints must quote original user spans only. Brief and export each get at
most one bounded structural correction, still inside the shared model-call budget and
prepare deadline; provider refusal never triggers a correction.
Model-authored keep/replace/remove/recompose or coverage notes are diagnostics, not
proof of implementation; never use self-certifying prose as a generation gate.
Keep target identity separate from reference discovery. Open draws randomize
three visual directions before search without category quotas; explicit reference
themes stay grounded in original user spans. Keep two searches and separate page/
review ceilings. Preserve pending candidates with their original design direction.
The default discovery route is X first, then Abduzeedo as a bounded publisher
fallback. Old Pentagram, It's Nice That and ArtStation parsers remain reusable
only when explicitly supplied; they are not default routes. For X, use Tavily
status results, confirm the exact post with its page and syndication media, and do
not use Tavily image results as the reference. Abduzeedo articles must resolve
article-body artwork, not the social hero or navigation image. Keep one review
slot for the second source: after two unsuitable reviews on the initial route,
trigger the fallback search if budget remains; never clear pending pages. Never
log in, read cookies or run a resident browser. Treat prompts, tutorials,
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
Default second route is Abduzeedo. Switch to it after X search failure, empty
discovery, unreadable candidates or template rejection, changing the query or
direction according to the failure cause. Preserve pending X candidates while the
fallback gets a review opportunity; do not increase the existing search/page/
review/model/deadline budgets. Record the search `reason` and `change`.
Canonicalize publisher URLs before duplicate checks, including Abduzeedo query
variants, Behance locale/module variants for historical records, and ArtStation
author subdomains. Behance's curated gallery is not an enabled route after its
bounded probe returned 403; the other old parsers remain reusable but are not
default routes.
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
Caption and Layout modes use explicit style snapshots in the official draft. Never clean
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

## Prompt and identity behavior

Generate uses the user's original description without LLM expansion, translation,
tag cleaning or automatic backgrounds. It assembles the configured positive
prefix, explicitly selected styles and deduplicated verified identity references.
The prefix never applies to repair, reverse or draw routes.

`/moss 规划` forces the official Caption path; `/moss 布局` forces the official
natural-language expansion and Layout compiler. Both share the vendored skill and
compiler, with at most one textual repair for invalid official JSON. Provider
refusals, service errors and truncation are terminal, not retried with a default
image. Saved `draft.json`, `compiled_prompt.txt` and `prompt.txt` distinguish the
official path from `direct-input`.

Optional Danbooru identity work is separate from generation. It uses an LLM to
extract names and candidates, then Anima query evidence and category validation;
unconfirmed names stay unverified, aliases merge, and already-present canonical
tags are not appended twice. Research failures never block the original
description. OC names and aliases are never sent to Danbooru.

The bundled ComfyUI graph at `assets/comfyui/moss-int8-api.json` binds the native
MOSS INT8 model, `moss_image` encoder, FLUX.2 VAE, Flow shift 5, the negative SLG
layer 22 branch and the default Euler/sgm_uniform sampling settings. It updates
only explicitly bound prompt, size, model and sampling fields; it does not infer
positive/negative nodes from JSON order. The ComfyUI installation must provide
the referenced native nodes and model files.

## Tasks, delivery and retention

Tasks are deduplicated by conversation, user and message ID. Each task owns a
configuration snapshot, random seed and runtime directory. GPU submissions are
serialized; delivery waiting does not hold the sampling lock, and cross-plugin
GPU queuing belongs to ComfyUI. Each generation stores `content_prompt.txt`, the
prefix snapshot, the final submitted prompt, configuration, workflow and result.

Only a successful image send is a success. Uncertain remote submission or
delivery is recorded as `remote_unknown` or `delivery_unknown`; it is never
retried automatically, and the plugin never restarts ComfyUI globally. Reloading
the plugin classifies old records but does not resume them. Long spell, reverse or
style-menu output uses one forward card when it exceeds the configured threshold;
an unknown receipt is never turned into a long-text resend.

The latest raw LLM response is kept only in the private `last_llm_response.json`,
up to four calls, with bounded text and truncation markers. A new task replaces
it; late returns cannot overwrite a newer task. Parsing clears old calls, reverse
stores this task's VLM response, and style/OC operations leave diagnostics alone.

Finished records and task directories default to 30-day retention. Cleanup skips
unknown remote jobs, active jobs, damaged records, orphan directories and linked
targets. Deletion is irreversible; `0` disables time-based cleanup.

## Verification

```text
uv sync --dev
uv run ruff check .
uv run ruff format --check .
uv run pytest -q -c pyproject.toml
```

Tests block real HTTP and use LLM, ComfyUI and QQ doubles. Offline success does
not prove server loading, real tooling, QQ receipts or visual acceptance.

New comments and logs are English. Use Google-style docstrings for non-obvious
functions. Run Ruff, pytest, compile checks, resource hash checks and diff checks.
