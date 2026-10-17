"""Adapt Anima's evidence-based character resolver, never its tag pipeline."""

import asyncio
import importlib.util
import re
import sys
import threading
import time
import unicodedata

from .skill import ROOT


class CharacterResolver:
    """Bound blocking lookups across requests, including timed-out workers."""

    def __init__(self, logger):
        spec = importlib.util.spec_from_file_location(
            "moss_anima_danbooru", ROOT / "vendor/anima/danbooru_tags.py"
        )
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        self.module = module
        self.logger = logger
        self.cache = {}
        self.slots = asyncio.Semaphore(2)
        self.cache_lock = threading.Lock()
        self.pending = set()

    def _query_records(self, query, autocomplete, deadline, trace):
        """Query public identity metadata with bounded caching and safe diagnostics.

        Args:
            query: One exact candidate or original-name autocomplete query.
            autocomplete: Whether to request the public autocomplete endpoint.
            deadline: Request-local monotonic deadline.
            trace: Request-local list of sanitized HTTP outcomes.

        Returns:
            Records from a successful response, or None when all sources failed.
        """
        endpoint = "autocomplete" if autocomplete else "tags"
        key = f"moss:{endpoint}:{query}"
        cached = self.cache.get(key)
        ttl = (
            3600
            if cached and cached[1]
            else (5 if cached and cached[1] is None else 60)
        )
        if cached and time.monotonic() - cached[0] < ttl:
            trace.append(
                {
                    "query": query,
                    "endpoint": endpoint,
                    "cache_hit": True,
                    "outcome": cached[2],
                }
            )
            return cached[1]
        for source in self.module.DEFAULT_DONMAI_BASE_URLS:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            attempt = {"query": query, "endpoint": endpoint, "source": source}
            trace.append(attempt)
            try:
                response = self.module.requests.get(
                    source + f"/{endpoint}.json",
                    params={"search[type]": "tag_query", "search[query]": query}
                    if autocomplete
                    else {"search[name_matches]": query, "limit": 10},
                    timeout=min(1.5, remaining),
                    headers={
                        "User-Agent": "MaiBotMOSS/0.2",
                        "Accept": "application/json",
                    },
                )
                attempt["status_code"] = response.status_code
                if response.status_code != 200:
                    continue
                data = response.json()
                if not isinstance(data, list):
                    attempt["error"] = "invalid_response"
                    continue
                records = []
                for item in data[:20]:
                    if not isinstance(item, dict):
                        continue
                    tag = item.get("tag") if isinstance(item.get("tag"), dict) else item
                    name = str(item.get("value") or tag.get("name") or "").strip()
                    if not name:
                        continue
                    records.append(
                        self.module.TagRecord(
                            name=name,
                            category=int(
                                item.get("category") or tag.get("category") or 0
                            ),
                            post_count=int(
                                item.get("post_count") or tag.get("post_count") or 0
                            ),
                            deprecated=bool(tag.get("is_deprecated")),
                            source=source,
                        )
                    )
                attempt["matches"] = len(records)
                self.cache[key] = (
                    time.monotonic(),
                    records,
                    "records" if records else "not_found",
                )
                return records
            except (
                self.module.requests.RequestException,
                ValueError,
                TypeError,
            ) as exc:
                attempt["error"] = type(exc).__name__
        self.cache[key] = (time.monotonic(), None, "source_unavailable")
        return None

    def _lookup(
        self, characters: list[dict], *, deadline=None, progress=None
    ) -> list[dict]:
        """Resolve source names and alias hints online before optional appearance work.

        Args:
            characters: Explicit source identities, not subjects inferred from style.
            deadline: Optional absolute monotonic deadline for all identities.
            progress: Request-local snapshots retaining verified partial results.

        Returns:
            Per-name results with attempted candidates and bounded lookup diagnostics.
        """
        deadline = deadline if deadline is not None else time.monotonic() + 8
        progress = progress if progress is not None else {}
        answers = []
        # One shared lock protects both upstream TTL records and bounded eviction.
        with self.cache_lock:
            for character in characters:
                base = {
                    "source_name": character["source_name"],
                    "copyright": character.get("copyright", ""),
                    "status": "unresolved",
                }
                source_name = unicodedata.normalize(
                    "NFKC", character["source_name"]
                ).strip()
                aliases = next(
                    (
                        values
                        for name, values in self.module.KNOWN_CORE_ALIASES.items()
                        if name.casefold() == source_name.casefold()
                    ),
                    (),
                )
                candidates = []
                for hint in [*aliases, *character.get("candidates", [])[:3]]:
                    hint = unicodedata.normalize("NFKC", hint).strip().casefold()
                    hint = self.module.KNOWN_CANONICAL_CORE_TAGS.get(hint, hint)
                    if (
                        re.fullmatch(r"[a-z0-9_.'():-]{3,100}", hint)
                        and hint not in candidates
                    ):
                        candidates.append(hint)
                candidates = candidates[:6]
                base["candidates"] = candidates
                base["candidate_source"] = (
                    "source_alias_and_hints" if aliases else "llm_hints"
                )
                trace = []
                best = None
                degraded = None
                reason = "no_matching_character_tag"
                progress[character["source_name"]] = dict(base)
                for candidate in candidates:
                    records = self._query_records(candidate, False, deadline, trace)
                    progress[character["source_name"]] = {
                        **base,
                        "lookup_trace": [dict(attempt) for attempt in trace[-8:]],
                    }
                    for record in records or []:
                        if self.module._normalize_query(record.name) != candidate:
                            continue
                        if record.deprecated:
                            reason = "deprecated_tag"
                        elif record.category != self.module.CHARACTER_CATEGORY:
                            reason = "not_character_category"
                            if record.post_count > 0:
                                degraded = record
                        else:
                            best = record
                            break
                    if best or time.monotonic() >= deadline:
                        break
                # Original-name autocomplete can resolve multilingual aliases; scoped
                # stem searches must still agree on the work, never on popularity.
                queries = [(source_name, None)]
                queries.extend(
                    (candidate.split("_(", 1)[0], candidate)
                    for candidate in candidates
                    if "_(" in candidate
                )
                seen = set()
                for query, scoped in queries:
                    if best or time.monotonic() >= deadline:
                        break
                    if query in seen:
                        continue
                    seen.add(query)
                    records = self._query_records(query, True, deadline, trace)
                    matches = {}
                    for record in records or []:
                        if (
                            record.category != self.module.CHARACTER_CATEGORY
                            or record.deprecated
                        ):
                            continue
                        normalized = self.module._normalize_query(record.name)
                        if scoped:
                            parts = normalized.split("_(", 1)
                            work = set(
                                re.findall(r"[a-z0-9]{2,}", scoped.split("_(", 1)[1])
                            )
                            if (
                                len(parts) != 2
                                or parts[0] != query
                                or not work.intersection(
                                    re.findall(r"[a-z0-9]{2,}", parts[1])
                                )
                            ):
                                reason = "work_mismatch"
                                continue
                        elif candidates and normalized not in candidates:
                            work = {
                                term
                                for candidate in candidates
                                if "_(" in candidate
                                for term in re.findall(
                                    r"[a-z0-9]{2,}", candidate.split("_(", 1)[1]
                                )
                            }
                            if work and not work.intersection(
                                re.findall(
                                    r"[a-z0-9]{2,}", normalized.split("_(", 1)[-1]
                                )
                            ):
                                reason = "work_mismatch"
                                continue
                        matches[normalized] = record
                    if len(matches) == 1:
                        best = next(iter(matches.values()))
                    elif len(matches) > 1:
                        reason = "ambiguous_identity"
                        break
                if best:
                    base.update(
                        status="verified",
                        canonical_tag=best.name,
                        lookup_reason="verified_online",
                        evidence=[
                            f"{best.name}|source={best.source}|category={best.category}|count={best.post_count}"
                        ],
                    )
                else:
                    if time.monotonic() >= deadline:
                        reason = "lookup_budget_exhausted"
                    elif trace and all(
                        "matches" not in attempt
                        and attempt.get("outcome") not in {"records", "not_found"}
                        for attempt in trace
                    ):
                        reason = "source_unavailable"
                    base["lookup_reason"] = reason
                    if reason in {"source_unavailable", "lookup_budget_exhausted"}:
                        base["status"] = "source_unavailable"
                    elif degraded:
                        base.update(status="degraded", canonical_tag=degraded.name)
                base["lookup_trace"] = [dict(attempt) for attempt in trace[-8:]]
                answers.append(base)
                progress[character["source_name"]] = dict(base)
            # An optional appearance request must never erase confirmed identities.
            for base in answers:
                if base["status"] == "verified" and deadline - time.monotonic() > 0.1:
                    try:
                        base["appearance_anchors"] = list(
                            self.module._fetch_stable_identity_tags(
                                base["canonical_tag"],
                                timeout=min(1.5, deadline - time.monotonic()),
                                user_agent="MaiBotMOSS/0.2",
                                cache=self.cache,
                            )
                        )
                    except Exception:
                        base["appearance_lookup"] = "unavailable"
                    progress[base["source_name"]] = dict(base)
            # Expiration controls reuse; eviction also bounds unused old keys.
            now = time.monotonic()
            for key in list(self.cache):
                entry = self.cache[key]
                if isinstance(entry, tuple) and now - entry[0] > 86400:
                    self.cache.pop(key, None)
            while len(self.cache) > 512:
                self.cache.pop(next(iter(self.cache)))
        return answers

    async def resolve(self, characters: list[dict], budget: float) -> list[dict]:
        """Return bounded evidence without waiting indefinitely for unavailable sites.

        Args:
            characters: Explicit original names and unverified candidate tags.
            budget: Total caller waiting budget, including semaphore admission.

        Returns:
            Per-name evidence; timed-out work retains its slot until it exits.
        """
        if not characters:
            return []
        started = asyncio.get_running_loop().time()
        acquired = False
        progress = {}
        try:
            await asyncio.wait_for(self.slots.acquire(), timeout=budget)
            acquired = True
            task = asyncio.create_task(
                asyncio.to_thread(
                    self._lookup,
                    characters,
                    deadline=started + budget,
                    progress=progress,
                )
            )
            self.pending.add(task)
            task.add_done_callback(lambda done: self.pending.discard(done))
            task.add_done_callback(lambda _: self.slots.release())
            task.add_done_callback(
                lambda done: done.exception() if not done.cancelled() else None
            )
            acquired = False
            return await asyncio.wait_for(
                asyncio.shield(task),
                timeout=max(
                    0.001, budget - (asyncio.get_running_loop().time() - started)
                ),
            )
        except Exception as exc:
            self.logger.warning(
                "MOSS character lookup unavailable: %s", type(exc).__name__
            )
            return [
                progress[c["source_name"]]
                if progress.get(c["source_name"], {}).get("status") == "verified"
                else {
                    "source_name": c["source_name"],
                    "copyright": c.get("copyright", ""),
                    "candidates": list(c.get("candidates", []))[:3],
                    **progress.get(c["source_name"], {}),
                    "status": "source_unavailable",
                    "lookup_reason": "lookup_budget_exhausted"
                    if isinstance(exc, TimeoutError)
                    else "lookup_error",
                    "error_type": type(exc).__name__,
                }
                for c in characters
            ]
        finally:
            if acquired:
                self.slots.release()
