# MaiBot MOSS Image development instructions

This is an independent MaiBot plugin, not AstrBot core or the Anima plugin.
Use public MaiBot SDK APIs only. Never modify sibling projects, host persona,
account permissions, local ComfyUI workflows or live service configuration.

Keep explicit generate, caption, layout, style, metadata and reverse routes.
Show style selection and editing only in the style submenu. Raw prompting is
removed. Do not add status, debug, character libraries, task recovery, image
editing, comic or meme commands. OC, comic and meme interfaces remain reserved.

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

New comments and logs are English. Use Google-style docstrings for non-obvious
functions. Run Ruff, pytest, compile checks, resource hash checks and diff checks.
