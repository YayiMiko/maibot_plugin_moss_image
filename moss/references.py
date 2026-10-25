"""Public-only HTTPS discovery and bounded, plugin-owned reference images."""

import asyncio
import hashlib
import http.client
import io
import ipaddress
import json
import re
import socket
import ssl
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlsplit, urlunsplit

from PIL import Image, ImageOps

from .draw_models import DrawError

MAX_IMAGE = 8 * 1024 * 1024
HTTP_WORKERS = ThreadPoolExecutor(max_workers=2, thread_name_prefix="moss-reference")
IMAGE_LOCK = threading.Lock()


async def fetch_public(url, **kwargs):
    """Bound live HTTP workers even when a cancelled DNS/socket call finishes late."""
    return await asyncio.get_running_loop().run_in_executor(
        HTTP_WORKERS, partial(safe_http, url, **kwargs)
    )


def public_url(url: str):
    """Validate URL syntax; actual DNS and peer checks happen on every connection."""
    parsed = urlsplit(url)
    if (
        len(url) > 4096
        or parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port not in {None, 443}
        or any(ord(char) < 33 for char in url)
        or "\\" in url
        or "%" in parsed.hostname
    ):
        raise DrawError("reference_unreadable")
    return parsed


def safe_http(url: str, *, payload=None, key="", limit=MAX_IMAGE):
    """Fetch bounded bytes with pinned public DNS, verified TLS and no proxies.

    Args:
        url: Public HTTPS resource; each redirect is independently validated.
        payload: Optional JSON payload, permitted only at the fixed Tavily endpoint.
        key: Authentication sent only to the fixed API, never to redirect targets.
        limit: Maximum response bytes, enforced even without Content-Length.

    Returns:
        Final URL, media type and bounded response bytes.

    Raises:
        DrawError: Unsafe destination, redirect, size, protocol or HTTP failure.
    """
    if payload is not None and url != "https://api.tavily.com/search":
        raise DrawError("search_unavailable")
    deadline = time.monotonic() + 20
    try:
        for redirect in range(4):
            parsed = public_url(url)
            addresses = socket.getaddrinfo(
                parsed.hostname, 443, type=socket.SOCK_STREAM
            )
            if not addresses or any(
                not ipaddress.ip_address(item[4][0]).is_global for item in addresses
            ):
                raise DrawError("reference_unreadable")
            # Connect to the already validated numeric address, never resolve twice.
            address = addresses[0][4][0]
            connection = http.client.HTTPSConnection(parsed.hostname, timeout=8)
            try:
                raw = socket.create_connection((address, 443), timeout=8)
                try:
                    if ipaddress.ip_address(
                        raw.getpeername()[0]
                    ) != ipaddress.ip_address(address):
                        raise DrawError("reference_unreadable")
                    connection.sock = ssl.create_default_context().wrap_socket(
                        raw, server_hostname=parsed.hostname
                    )
                    secured = connection.sock
                except BaseException:
                    raw.close()
                    raise
                headers = {
                    "User-Agent": "MOSS-Reference/1.0",
                    "Accept-Encoding": "identity",
                }
                body = None
                if payload is not None:
                    headers.update(
                        {
                            "Authorization": "Bearer " + key,
                            "Content-Type": "application/json",
                        }
                    )
                    body = json.dumps(payload).encode("utf-8")
                connection.request(
                    "POST" if payload is not None else "GET",
                    urlunsplit(("", "", parsed.path or "/", parsed.query, "")),
                    body=body,
                    headers=headers,
                )
                response = connection.getresponse()
                if response.status in {301, 302, 303, 307, 308}:
                    if payload is not None or redirect == 3:
                        raise DrawError("reference_unreadable")
                    url = urljoin(url, response.getheader("Location") or "")
                    continue
                if (
                    response.status != 200
                    or response.getheader("Content-Encoding", "identity") != "identity"
                ):
                    raise DrawError("reference_unreadable")
                length = response.getheader("Content-Length")
                if length is not None and (
                    not length.isdecimal() or int(length) > limit
                ):
                    raise DrawError("reference_unreadable")
                chunks, size = [], 0
                while True:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise DrawError("reference_unreadable")
                    secured.settimeout(min(5, remaining))
                    chunk = response.read1(min(65536, limit + 1 - size))
                    if not chunk:
                        break
                    chunks.append(chunk)
                    size += len(chunk)
                    if size > limit:
                        raise DrawError("reference_unreadable")
                return (
                    url,
                    response.getheader("Content-Type", "").split(";")[0].lower(),
                    b"".join(chunks),
                )
            finally:
                connection.close()
    except DrawError:
        raise
    except Exception:
        raise DrawError("reference_unreadable") from None
    raise DrawError("reference_unreadable")


class WorkPage(HTMLParser):
    """Read publisher-declared artwork metadata without executing website code."""

    def __init__(self, text):
        super().__init__(convert_charrefs=True)
        self.images, self.title, self.author = [], "", ""
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        fields = dict(attrs)
        name = fields.get("property") or fields.get("name")
        content = fields.get("content") or ""
        if tag == "meta" and name in {
            "og:image",
            "og:image:secure_url",
            "twitter:image",
        }:
            if content and content not in self.images:
                self.images.append(content)
        if tag == "meta" and name == "og:title":
            self.title = content[:300]
        if tag == "meta" and name in {"author", "article:author"}:
            self.author = content[:200]


def normalize_image(content: bytes, edge=1536):
    """Reject oversized or animated inputs before decoding and strip metadata."""
    if len(content) > MAX_IMAGE:
        raise DrawError("reference_unreadable")
    IMAGE_LOCK.acquire()
    try:
        with Image.open(io.BytesIO(content)) as image:
            if (
                image.format not in {"JPEG", "PNG", "WEBP"}
                or getattr(image, "n_frames", 1) != 1
                or image.width * image.height > 12_000_000
                or min(image.size) < 256
            ):
                raise DrawError("reference_unreadable")
            normalized = ImageOps.exif_transpose(image).convert("RGB")
            width, height = normalized.size
            normalized.thumbnail((edge, edge))
            thumbnail = normalized.resize((9, 8)).convert("L")
            pixels = [thumbnail.getpixel((x, y)) for y in range(8) for x in range(9)]
            signature = sum(
                (pixels[y * 9 + x] > pixels[y * 9 + x + 1]) << (y * 8 + x)
                for y in range(8)
                for x in range(8)
            )
            output = io.BytesIO()
            normalized.save(output, "JPEG", quality=90)
        return output.getvalue(), width, height, f"{signature:016x}"
    except DrawError:
        raise
    except Exception:
        raise DrawError("reference_unreadable") from None
    finally:
        IMAGE_LOCK.release()


class ReferenceClient:
    """Discover works from explicitly approved publication channels, one at a time."""

    def __init__(self, config, sources):
        self.config, self.sources = config, sources
        self.calls, self.pages = 0, 0
        self.seen = set()

    async def search(self, query: str) -> list[str]:
        """Return only source-scoped work pages; aggregate image URLs are not proof."""
        if self.calls >= self.config.limits.search_budget:
            return []
        if (
            len(query) > 300
            or "@" in query
            or "://" in query
            or any(ord(char) < 32 for char in query)
            or re.search(
                r"(?<!\d)\d{5,}(?!\d)|\b\d{1,3}(?:\.\d{1,3}){3}\b|(?:api.?key|token|password)\s*[:=]",
                query,
                re.I,
            )
        ):
            raise DrawError("invalid_export")
        self.calls += 1
        try:
            _, _, body = await fetch_public(
                "https://api.tavily.com/search",
                payload={
                    "query": query,
                    "search_depth": "basic",
                    "max_results": 5,
                    "include_domains": sorted(
                        {source.domain for source in self.sources}
                    ),
                    "include_answer": False,
                    "include_images": True,
                    "include_image_descriptions": True,
                    "auto_parameters": False,
                },
                key=self.config.tavily_api_key,
                limit=512 * 1024,
            )
            result = json.loads(body)
            pages = []
            for item in result.get("results", [])[:5]:
                url = item.get("url", "")
                parsed = public_url(url)
                if (
                    any(source.matches(parsed) for source in self.sources)
                    and url not in self.seen
                ):
                    self.seen.add(url)
                    pages.append(url)
            return pages
        except asyncio.CancelledError:
            raise
        except Exception:
            raise DrawError("search_unavailable") from None

    async def candidate(self, page_url: str, number: int):
        """Confirm a page-image association using the publisher's own metadata."""
        self.pages += 1
        page_url, media, body = await fetch_public(page_url, limit=512 * 1024)
        parsed = public_url(page_url)
        source = next(
            (source for source in self.sources if source.matches(parsed)), None
        )
        if source is None or media not in {"text/html", "application/xhtml+xml"}:
            raise DrawError("reference_unreadable")
        page = WorkPage(body.decode("utf-8", errors="replace"))
        if not page.images or not page.title:
            raise DrawError("reference_unreadable")
        image_url = urljoin(page_url, page.images[0])
        image_url, _, content = await fetch_public(image_url)
        normalized, width, height, signature = await asyncio.to_thread(
            normalize_image, content
        )
        record = {
            "id": f"candidate-{number}",
            "page": urlunsplit(parsed._replace(query="", fragment="")),
            "image": urlunsplit(public_url(image_url)._replace(query="", fragment="")),
            "title": page.title,
            "author": page.author,
            "source_kind": source.kind,
            "source_evidence": source.evidence,
            "retrieved_at": time.time(),
            "published_at": None,
            "width": width,
            "height": height,
            "sha256": hashlib.sha256(normalized).hexdigest(),
            "signature": signature,
        }
        return record, normalized


def cache_reference(root: Path, content: bytes | None, capacity: int):
    """Store only normalized selected artwork and bound private cache size/age.

    Args:
        root: Plugin-owned cache directory, never an arbitrary runtime path.
        content: Validated JPEG bytes, or None for an expiration-only maintenance pass.
        capacity: Maximum bytes including the incoming image.

    Returns:
        Content hash identifying the cached JPEG.

    Raises:
        DrawError: Linked storage, unknown cache contents or exhausted capacity.
    """
    if any(path.is_symlink() or path.is_junction() for path in (root, *root.parents)):
        raise DrawError("reference_unreadable")
    if content is None and not root.exists():
        return None
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    incoming = len(content) if content is not None else 0
    files = []
    for path in root.iterdir():
        if path.is_symlink() or path.is_junction() or not path.is_file():
            raise DrawError("reference_unreadable")
        if (
            len(path.stem) != 64
            or any(char not in "0123456789abcdef" for char in path.stem)
            or path.suffix != ".jpg"
        ):
            raise DrawError("reference_unreadable")
        files.append(path)
        if len(files) > 1024:
            raise DrawError("budget_exhausted")
    total = sum(path.stat().st_size for path in files)
    for path in sorted(files, key=lambda item: item.stat().st_mtime):
        if (
            total + incoming <= capacity
            and path.stat().st_mtime >= time.time() - 7 * 86400
        ):
            continue
        total -= path.stat().st_size
        path.unlink()
    if total + incoming > capacity:
        raise DrawError("budget_exhausted")
    if content is None:
        return None
    digest = hashlib.sha256(content).hexdigest()
    target = root / (digest + ".jpg")
    if not target.exists():
        # A selected normalized image is small; exclusive creation avoids link replacement.
        with target.open("xb") as handle:
            target.chmod(0o600)
            handle.write(content)
    target.touch()
    return digest
