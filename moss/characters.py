"""Adapt Anima's evidence-based character resolver, never its tag pipeline."""

import asyncio
import importlib.util
import re
import sys
import threading
import time

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

    def _lookup(self, characters: list[dict]) -> list[dict]:
        """Resolve each named identity separately, preserving its source binding."""
        answers = []
        # One shared lock protects both upstream TTL records and bounded eviction.
        with self.cache_lock:
            for character in characters:
                base = {
                    "source_name": character["source_name"],
                    "copyright": character.get("copyright", ""),
                    "status": "unresolved",
                }
                best, evidence = self.module._resolve_evidence_candidates(
                    tuple(character["candidates"][:3]),
                    donmai_base_urls=self.module.DEFAULT_DONMAI_BASE_URLS,
                    timeout=1.5,
                    user_agent="MaiBotMOSS/0.1",
                    cache=self.cache,
                )
                consistent = False
                if best:
                    # Popularity must not resolve a scoped name to another work.
                    best_name = self.module._normalize_query(best.name)
                    best_parts = best_name.split("_(", 1)
                    for candidate in character["candidates"][:3]:
                        candidate = self.module._normalize_query(candidate)
                        parts = candidate.split("_(", 1)
                        names = self.module._candidate_queries(parts[0])
                        if best_parts[0] not in names:
                            continue
                        if len(parts) == 2 and len(best_parts) == 2:
                            work = set(re.findall(r"[a-z0-9]{2,}", parts[1]))
                            other = set(re.findall(r"[a-z0-9]{2,}", best_parts[1]))
                            if not work.intersection(other):
                                continue
                        elif len(parts) == 2 and candidate != best_name:
                            continue
                        consistent = True
                        break
                if best and consistent and not best.deprecated:
                    verified = best.category == self.module.CHARACTER_CATEGORY
                    base.update(
                        status="verified" if verified else "degraded",
                        canonical_tag=best.name,
                        evidence=list(evidence),
                    )
                    if verified:
                        base["appearance_anchors"] = list(
                            self.module._fetch_stable_identity_tags(
                                best.name,
                                timeout=1.5,
                                user_agent="MaiBotMOSS/0.1",
                                cache=self.cache,
                            )
                        )
                answers.append(base)
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
        try:
            await asyncio.wait_for(self.slots.acquire(), timeout=budget)
            acquired = True
            task = asyncio.create_task(asyncio.to_thread(self._lookup, characters))
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
                {"source_name": c["source_name"], "status": "source_unavailable"}
                for c in characters
            ]
        finally:
            if acquired:
                self.slots.release()
