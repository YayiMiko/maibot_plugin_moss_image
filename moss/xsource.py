"""Discover public X posts and associate the exact post with its artwork."""

import asyncio
import hashlib
import html
import json
import re
import time
from urllib.parse import urlsplit

from .draw_models import DrawError
from .references import (
    ReferenceError,
    display_url,
    fetch_public,
    normalize_image,
    validate_search_query,
)

X_ENABLED = True
X_DOMAIN = "x.com"
STATUS_HOSTS = {
    "x.com",
    "www.x.com",
    "mobile.x.com",
    "twitter.com",
    "www.twitter.com",
    "mobile.twitter.com",
}
MEDIA_RE = re.compile(r"pbs\.twimg\.com/media/([A-Za-z0-9_-]+)")
OG_RE = re.compile(
    r'<meta[^>]+(?:property|name)=["\'](?:og:image|twitter:image)["\'][^>]+content=["\']([^"\']+)',
    re.I,
)
TUTORIAL_MARKERS = (
    "prompt:",
    "prompt :",
    "here is the prompt",
    "here's the prompt",
    "use this prompt",
    "copy this prompt",
    "how to make",
    "how to create",
    "how to draw",
    "how to design",
    "how to generate",
    "tutorial",
    "step by step",
    "workflow",
    "settings:",
    "recreate this",
    "recreate the",
    "recreate it",
    "template",
    "[name]",
    "your character here",
    "ych",
    "blank template",
)
SALES_MARKERS = (
    "buy now",
    "shop now",
    "on sale",
    "discount",
    "commission open",
    "commissions open",
    "pre-order",
    "preorder",
    "link in bio",
    "merch",
    "store",
    "kickstarter",
    "wishlist",
)
PRODUCT_MARKERS = (
    "manhole",
    "action figure",
    "figurine",
    "product photo",
    "product shot",
)
STRONG_ART_MARKERS = (
    "poster",
    "illustration",
    "key visual",
    "artwork",
)
AI_TOOL_MARKERS = (
    "midjourney",
    "chatgpt",
    "stable diffusion",
    "dall-e",
    "dalle",
    "ai art",
    "ai-art",
)


def status_id(url: str) -> str | None:
    """Return a status id only for an X/Twitter status URL."""
    try:
        parsed = urlsplit(url)
    except ValueError:
        return None
    match = re.match(r"^/(?:i/|[^/]+/)status/(\d+)", parsed.path)
    if parsed.hostname in STATUS_HOSTS and match:
        return match.group(1)
    return None


def canonical_status_url(tweet_id: str) -> str:
    """Use one stable locator regardless of the author handle."""
    return f"https://x.com/i/status/{tweet_id}"


def page_markers(body: bytes) -> dict:
    """Read bounded page metadata without treating recommendations as post media."""
    text = body.decode("utf-8", errors="replace")
    lower = text.lower()
    og_urls = [html.unescape(value) for value in OG_RE.findall(text)]
    og_media_ids = []
    for value in og_urls:
        match = MEDIA_RE.search(value)
        og_media_ids.append(match.group(1) if match else None)
    return {
        "og_urls": og_urls[:3],
        "og_media_ids": [value for value in og_media_ids[:3] if value],
        "html_media_ids": list(dict.fromkeys(MEDIA_RE.findall(text)))[:12],
        "login_wall": any(
            marker in lower
            for marker in ("log in to x", "sign in to x", "join x today")
        ),
        "js_shell": "javascript is not available" in lower,
    }


def content_classification(text: str) -> tuple[str | None, list[str]]:
    """Reject obvious tutorials/templates/ads; keep AI-tool mentions as flags."""
    normalized = " ".join(text.casefold().split())
    flags = []
    if any(marker in normalized for marker in TUTORIAL_MARKERS):
        return "tutorial_or_template", ["tutorial_or_template"]
    has_art = any(marker in normalized for marker in STRONG_ART_MARKERS)
    if any(marker in normalized for marker in SALES_MARKERS) and not has_art:
        return "ad_only", ["ad_only"]
    if any(marker in normalized for marker in PRODUCT_MARKERS) and not has_art:
        return "product_only", ["product_only"]
    if any(marker in normalized for marker in AI_TOOL_MARKERS):
        flags.append("ai_tool_mention")
    if any(marker in normalized for marker in SALES_MARKERS):
        flags.append("sales_mention")
    return None, flags


class XReferenceClient:
    """Use Tavily only for discovery; resolve media from the exact X post."""

    def __init__(self, config):
        self.config = config
        self.calls = 0
        self.pages = 0
        self.seen = set()
        self.seen_keys = set()
        self.searches = []
        self.page_priorities = {}

    async def search(self, query: str, *, sources=None) -> list[str]:
        """Return canonical X status URLs, never profiles or trending pages."""
        if self.calls >= self.config.limits.search_budget:
            return []
        validate_search_query(query)
        self.calls += 1
        trace = {
            "route": "x",
            "query": query,
            "outcome": "failed",
            "returned": 0,
            "accepted": 0,
            "rejected": 0,
            "pages": [],
            "domains": [X_DOMAIN],
            "filtered": [],
            "page_types": {},
        }
        self.searches.append(trace)
        try:
            _, _, body = await fetch_public(
                "https://api.tavily.com/search",
                payload={
                    "query": query,
                    "search_depth": "basic",
                    "max_results": 5,
                    "include_domains": [X_DOMAIN],
                    "include_answer": False,
                    "include_images": False,
                    "auto_parameters": False,
                },
                key=self.config.tavily_api_key,
                limit=512 * 1024,
                stage="search",
            )
            result = json.loads(body)
            results = result.get("results", [])
            if not isinstance(results, list):
                raise ValueError("Invalid search results")
            trace["returned"] = len(results[:5])
            pages = []
            accepted_keys = set()
            for item in results[:5]:
                url = item.get("url", "") if isinstance(item, dict) else ""
                tweet_id = status_id(url)
                if not tweet_id:
                    trace["rejected"] += 1
                    trace["filtered"].append(
                        {"url": display_url(url), "reason": "not_a_post"}
                    )
                    continue
                canonical = canonical_status_url(tweet_id)
                reason = (
                    "already_attempted"
                    if canonical in self.seen_keys or canonical in self.seen
                    else "duplicate_result"
                    if canonical in accepted_keys
                    else ""
                )
                if reason:
                    trace["rejected"] += 1
                    trace["filtered"].append(
                        {"url": display_url(canonical), "reason": reason}
                    )
                    continue
                accepted_keys.add(canonical)
                pages.append(canonical)
                self.page_priorities[canonical] = 0
                trace["page_types"][display_url(canonical)] = "x_status"
            for page in pages:
                self.seen_keys.add(page)
            trace.update(
                outcome="ok",
                accepted=len(pages),
                pages=[display_url(page) for page in pages],
            )
            return pages
        except asyncio.CancelledError:
            raise
        except ReferenceError as exc:
            trace["failure"] = exc.details
            raise DrawError("search_unavailable") from None
        except Exception:
            trace["failure"] = {"stage": "search", "code": "invalid_response"}
            raise DrawError("search_unavailable") from None

    async def candidate(self, page_url: str, number: int):
        """Resolve one status page and confirm media belongs to that exact post."""
        self.pages += 1
        self.seen.add(page_url)
        tweet_id = status_id(page_url)
        if not tweet_id:
            raise ReferenceError("not_a_post", stage="page", url=page_url)
        canonical = canonical_status_url(tweet_id)
        page_url, page_media, page_body = await fetch_public(
            canonical, limit=512 * 1024, stage="page"
        )
        if page_media not in {"text/html", "application/xhtml+xml"}:
            raise ReferenceError(
                "unexpected_page_type", stage="page", url=page_url, status=200
            )
        markers = page_markers(page_body)
        if markers["login_wall"] or markers["js_shell"]:
            raise ReferenceError("login_wall", stage="page", url=page_url, status=200)
        sync_url = (
            "https://cdn.syndication.twimg.com/tweet-result"
            f"?id={tweet_id}&lang=en&token=a"
        )
        sync_url, sync_media, sync_body = await fetch_public(
            sync_url, limit=512 * 1024, stage="syndication"
        )
        if sync_media not in {"application/json", "text/json"}:
            raise ReferenceError(
                "unexpected_page_type", stage="syndication", url=sync_url, status=200
            )
        try:
            data = json.loads(sync_body)
        except Exception:
            raise ReferenceError(
                "association_unavailable", stage="syndication", url=sync_url
            ) from None
        if str(data.get("id_str") or data.get("id") or "") != tweet_id:
            raise ReferenceError(
                "association_unavailable", stage="syndication", url=sync_url
            )
        text = str(data.get("text") or "")
        hard_reason, flags = content_classification(text)
        if hard_reason:
            exc = ReferenceError("unsuitable_content", stage="filter", url=canonical)
            exc.details["filter_reason"] = hard_reason
            exc.details["content_flags"] = flags
            raise exc
        photos = []
        for item in data.get("mediaDetails") or []:
            if not isinstance(item, dict) or item.get("type") != "photo":
                continue
            media_url = item.get("media_url_https")
            match = MEDIA_RE.search(media_url or "")
            if not media_url or not match:
                continue
            sizes = item.get("sizes") or {}
            large = sizes.get("large") or {}
            photos.append(
                {
                    "media_id": match.group(1),
                    "url": media_url,
                    "width": large.get("w"),
                    "height": large.get("h"),
                }
            )
        if not photos:
            raise ReferenceError("no_media", stage="media", url=canonical)
        photos = [
            *[item for item in photos if item["media_id"] in markers["og_media_ids"]],
            *[
                item
                for item in photos
                if item["media_id"] not in markers["og_media_ids"]
            ],
        ]
        ordered = list({item["media_id"]: item for item in photos}.values())[:2]
        image_failures = []
        normalized = width = height = signature = image_url = None
        chosen_origin = None
        for item in ordered:
            candidate_url = (
                item["url"] if "?" in item["url"] else item["url"] + "?name=orig"
            )
            try:
                image_url, _, content = await fetch_public(
                    candidate_url, limit=8 * 1024 * 1024, stage="image"
                )
                try:
                    normalized, width, height, signature = await asyncio.to_thread(
                        normalize_image, content
                    )
                except DrawError:
                    raise ReferenceError(
                        "invalid_image", stage="decode", url=image_url, status=200
                    ) from None
                chosen_origin = (
                    "x_og"
                    if item["media_id"] in markers["og_media_ids"]
                    else "x_syndication"
                )
                break
            except ReferenceError as exc:
                image_failures.append(exc.details)
        if normalized is None:
            exc = ReferenceError("media_unreadable", stage="image", url=canonical)
            exc.details["image_failures"] = [dict(item) for item in image_failures]
            raise exc
        author = ""
        user = data.get("user") or {}
        if isinstance(user, dict):
            author = str(user.get("screen_name") or "")
        title = (text.splitlines()[0] if text.strip() else f"X post by @{author}")[:300]
        return (
            {
                "id": f"candidate-{number}",
                "page": display_url(canonical),
                "image": display_url(image_url),
                "title": title,
                "author": author,
                "source_kind": "x_post",
                "source_evidence": (
                    "X status; page metadata and syndication share the same post id."
                ),
                "retrieved_at": time.time(),
                "published_at": data.get("created_at"),
                "width": width,
                "height": height,
                "sha256": hashlib.sha256(normalized).hexdigest(),
                "signature": signature,
                "image_failures": image_failures,
                "image_origin": chosen_origin,
                "source_route": "x",
                "post_text": text[:500],
                "media": [
                    {
                        "media_id": item["media_id"],
                        "width": item["width"],
                        "height": item["height"],
                    }
                    for item in ordered
                ],
                "association": {
                    "page_status": 200,
                    "syndication_id_match": True,
                    "photo_count": len(photos),
                },
                "content_flags": flags,
                "canonical_key": f"x.com/i/status/{tweet_id}",
            },
            normalized,
        )
