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


def display_url(url: str) -> str:
    """Keep a public resource locator without credentials, queries or fragments."""
    try:
        parsed = public_url(url)
        return urlunsplit(parsed._replace(query="", fragment=""))
    except (DrawError, ValueError, TypeError):
        return "<invalid-url>"


class ReferenceError(DrawError):
    """Carry bounded technical evidence without response bodies or authentication."""

    def __init__(self, code: str, *, stage="fetch", url="", status=None):
        super().__init__("reference_unreadable")
        self.details = {
            "stage": stage,
            "code": code,
            "url": display_url(url),
            "http_status": status,
        }


def validate_search_query(query: str) -> None:
    """Reject queries that could carry credentials, addresses or control data."""
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


def canonical_page_key(url: str) -> str:
    """Collapse locale, subpage and subdomain variants for candidate deduplication."""
    try:
        parsed = public_url(url)
    except (DrawError, ValueError, TypeError):
        return url
    host = (parsed.hostname or "").lower().removeprefix("www.")
    path = parsed.path.rstrip("/")
    if host in {"artstation.com"} or host.endswith(".artstation.com"):
        match = re.match(r"/(?:artwork|projects)/([^/]+)", path)
        if match:
            return f"artstation.com/{match.group(1)}"
    if host == "behance.net":
        match = re.match(r"/gallery/(\d+)", path)
        if match:
            return f"behance.net/gallery/{match.group(1)}"
    if host == "pentagram.com":
        match = re.match(r"/work/([^/]+)", path)
        if match:
            return f"pentagram.com/work/{match.group(1)}"
    if host == "itsnicethat.com":
        match = re.match(r"/(articles|features)/([^/]+)", path)
        if match:
            return f"itsnicethat.com/{match.group(1)}/{match.group(2)}"
    return host + path


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


def safe_http(url: str, *, payload=None, key="", limit=MAX_IMAGE, stage="fetch"):
    """Fetch bounded bytes with pinned public DNS, verified TLS and no proxies.

    Args:
        url: Public HTTPS resource; each redirect is independently validated.
        payload: Optional JSON payload, permitted only at the fixed Tavily endpoint.
        key: Authentication sent only to the fixed API, never to redirect targets.
        limit: Maximum response bytes, enforced even without Content-Length.
        stage: Internal search/page/image stage for sanitized technical evidence.

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
                raise ReferenceError("non_public_destination", stage=stage, url=url)
            # Connect to the already validated numeric address, never resolve twice.
            address = addresses[0][4][0]
            connection = http.client.HTTPSConnection(parsed.hostname, timeout=8)
            try:
                raw = socket.create_connection((address, 443), timeout=8)
                try:
                    if ipaddress.ip_address(
                        raw.getpeername()[0]
                    ) != ipaddress.ip_address(address):
                        raise ReferenceError("peer_mismatch", stage=stage, url=url)
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
                        raise ReferenceError(
                            "redirect_rejected",
                            stage=stage,
                            url=url,
                            status=response.status,
                        )
                    url = urljoin(url, response.getheader("Location") or "")
                    continue
                if response.status != 200:
                    raise ReferenceError(
                        "http_status", stage=stage, url=url, status=response.status
                    )
                if response.getheader("Content-Encoding", "identity") != "identity":
                    raise ReferenceError(
                        "unsupported_encoding",
                        stage=stage,
                        url=url,
                        status=response.status,
                    )
                length = response.getheader("Content-Length")
                if length is not None and (
                    not length.isdecimal() or int(length) > limit
                ):
                    raise ReferenceError(
                        "response_too_large",
                        stage=stage,
                        url=url,
                        status=response.status,
                    )
                chunks, size = [], 0
                while True:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise ReferenceError(
                            "timeout", stage=stage, url=url, status=response.status
                        )
                    secured.settimeout(min(5, remaining))
                    chunk = response.read1(min(65536, limit + 1 - size))
                    if not chunk:
                        break
                    chunks.append(chunk)
                    size += len(chunk)
                    if size > limit:
                        raise ReferenceError(
                            "response_too_large",
                            stage=stage,
                            url=url,
                            status=response.status,
                        )
                return (
                    url,
                    response.getheader("Content-Type", "").split(";")[0].lower(),
                    b"".join(chunks),
                )
            finally:
                connection.close()
    except ReferenceError:
        raise
    except DrawError:
        raise ReferenceError("unsafe_url", stage=stage, url=url) from None
    except Exception as exc:
        code = (
            "dns_failed"
            if isinstance(exc, socket.gaierror)
            else "timeout"
            if isinstance(exc, TimeoutError)
            else "tls_failed"
            if isinstance(exc, ssl.SSLError)
            else "connection_failed"
        )
        raise ReferenceError(code, stage=stage, url=url) from None
    raise ReferenceError("redirect_rejected", stage=stage, url=url)


class WorkPage(HTMLParser):
    """Read scoped publisher artwork elements, with social metadata as fallback."""

    def __init__(self, text, url=""):
        """Parse bounded HTML without fetching or executing embedded content.

        Args:
            text: Publisher HTML already limited by the page-fetch boundary.
            url: Final publisher URL used to enable known article selectors.
        """
        super().__init__(convert_charrefs=True)
        self.url, self.title, self.author = url, "", ""
        self.host = (urlsplit(url).hostname or "").lower().removeprefix("www.")
        self.og_type = ""
        self.body_images, self.social_images, self.image_origins = [], [], {}
        self.stack = []
        self.feed(text)
        if self.host == "abduzeedo.com":
            # Abduzeedo article bodies contain the actual artwork; its social image
            # is a cropped hero and must not be treated as the reference.
            ordered = self.body_images[:2]
        else:
            # Keep one body artwork and one metadata fallback within the two-fetch ceiling.
            ordered = (
                self.body_images[:1]
                + self.social_images[:1]
                + self.body_images[1:]
                + self.social_images[1:]
            )
        self.images = list(dict.fromkeys(ordered))[:2]

    def handle_starttag(self, tag, attrs):
        fields = dict(attrs)
        name = fields.get("property") or fields.get("name")
        content = fields.get("content") or ""
        if tag == "meta" and name in {
            "og:image",
            "og:image:secure_url",
            "twitter:image",
        }:
            if (
                content
                and content not in self.social_images
                and len(self.social_images) < 4
            ):
                self.social_images.append(content)
                self.image_origins.setdefault(content, "social_metadata")
        if tag == "meta" and name == "og:title":
            self.title = content[:300]
        if tag == "meta" and name == "og:type":
            self.og_type = content[:50].lower()
        if tag == "meta" and name in {"author", "article:author"}:
            self.author = content[:200]
        if tag == "img" and len(self.body_images) < 8:
            source = (
                fields.get("data-src")
                or fields.get("data-original")
                or fields.get("src")
                or ""
            )
            if not source:
                srcset = fields.get("srcset") or fields.get("data-srcset") or ""
                if srcset:
                    source = srcset.split(",")[0].strip().split(" ")[0]
            try:
                host = urlsplit(self.url).hostname
                image = urlsplit(urljoin(self.url, source))
            except ValueError:
                source, host, image = "", None, None
            in_article = any(element == "article" for element, _ in self.stack)
            in_article_body = any(
                "article-body" in classes for _, classes in self.stack
            )
            outside_navigation = not any(
                element in {"nav", "aside", "header", "footer"}
                for element, _ in self.stack
            )
            associated = (
                source
                and outside_navigation
                and (
                    in_article
                    and (
                        host in {"pentagram.com", "www.pentagram.com"}
                        and "workMedia__img" in fields.get("class", "").split()
                        and any(
                            element == "figure" and "workMedia" in classes
                            for element, classes in self.stack
                        )
                        and image.hostname == "pentagram-production.imgix.net"
                        or host in {"itsnicethat.com", "www.itsnicethat.com"}
                        and image.hostname == "m.itsnicethat.com"
                        and image.path.startswith("/original_images/")
                    )
                    or self.host == "abduzeedo.com"
                    and self.og_type in {"", "article"}
                    and in_article_body
                )
            )
            key = ""
            if image is not None:
                key = image.geturl() if self.host == "abduzeedo.com" else image.path
            if (
                associated
                and key
                and not any(
                    (
                        urlsplit(urljoin(self.url, old)).geturl()
                        if self.host == "abduzeedo.com"
                        else urlsplit(urljoin(self.url, old)).path
                    )
                    == key
                    for old in self.body_images
                )
            ):
                self.body_images.append(source)
                self.image_origins[source] = "article_artwork"
        if tag not in {
            "area",
            "base",
            "br",
            "col",
            "embed",
            "hr",
            "img",
            "input",
            "link",
            "meta",
            "param",
            "source",
            "track",
            "wbr",
        }:
            self.stack.append((tag, fields.get("class", "").split()))

    def handle_endtag(self, tag):
        """Close the matching scope even when publisher markup omits inner closes."""
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                del self.stack[index:]
                break


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
        self.seen_keys = set()
        self.searches = []
        self.page_priorities = {}

    async def search(self, query: str, *, sources=None) -> list[str]:
        """Return only source-scoped work pages; aggregate image URLs are not proof."""
        if self.calls >= self.config.limits.search_budget:
            return []
        validate_search_query(query)
        self.calls += 1
        sources = self.sources if sources is None else sources
        trace = {
            "query": query,
            "outcome": "failed",
            "returned": 0,
            "accepted": 0,
            "rejected": 0,
            "pages": [],
            "domains": sorted({source.domain for source in sources}),
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
                    "include_domains": sorted({source.domain for source in sources}),
                    "include_answer": False,
                    "include_images": True,
                    "include_image_descriptions": True,
                    "auto_parameters": False,
                },
                key=self.config.tavily_api_key,
                limit=512 * 1024,
                stage="search",
            )
            result = json.loads(body)
            pages = []
            results = result.get("results", [])
            if not isinstance(results, list):
                raise ValueError("Invalid search results")
            trace["returned"] = len(results[:5])
            accepted_keys = set()
            for item in results[:5]:
                url = item.get("url", "") if isinstance(item, dict) else ""
                try:
                    parsed = public_url(url)
                except (ValueError, TypeError, DrawError):
                    trace["rejected"] += 1
                    trace["filtered"].append(
                        {"url": display_url(url), "reason": "unsafe_url"}
                    )
                    continue
                canonical = canonical_page_key(url)
                reason = (
                    "source_or_path_not_allowed"
                    if not any(source.matches(parsed) for source in sources)
                    else "already_attempted"
                    if canonical in self.seen_keys
                    else "duplicate_result"
                    if canonical in accepted_keys
                    else ""
                )
                if not reason:
                    pages.append(url)
                    accepted_keys.add(canonical)
                    # Collections remain eligible, after individual work reports.
                    title = str(item.get("title") or "")[:500]
                    collection = bool(
                        re.search(
                            r"\b(?:trends?|round[ -]?ups?|round[ -]?up|(?:top|best)\s+\d+)\b|趋势|合集|盘点",
                            title,
                            re.I,
                        )
                    )
                    self.page_priorities[url] = int(collection)
                    trace["page_types"][display_url(url)] = (
                        "collection" if collection else "work_or_article"
                    )
                else:
                    trace["rejected"] += 1
                    trace["filtered"].append(
                        {"url": display_url(url), "reason": reason}
                    )
            # Prefer earlier approved sources (Abduzeedo first) without narrowing domains.
            source_rank = {
                source.domain.removeprefix("www."): index
                for index, source in enumerate(sources)
            }
            pages.sort(
                key=lambda page: source_rank.get(
                    (urlsplit(page).hostname or "").lower().removeprefix("www."),
                    len(source_rank),
                )
            )
            self.seen_keys.update(accepted_keys)
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
        """Confirm artwork association using scoped body elements or social metadata."""
        self.pages += 1
        self.seen.add(page_url)
        self.seen_keys.add(canonical_page_key(page_url))
        page_url, media, body = await fetch_public(
            page_url, limit=512 * 1024, stage="page"
        )
        parsed = public_url(page_url)
        source = next(
            (source for source in self.sources if source.matches(parsed)), None
        )
        if source is None:
            raise ReferenceError(
                "source_not_allowed", stage="page", url=page_url, status=200
            )
        if media not in {"text/html", "application/xhtml+xml"}:
            raise ReferenceError(
                "unexpected_page_type", stage="page", url=page_url, status=200
            )
        page = WorkPage(body.decode("utf-8", errors="replace"), page_url)
        if source.domain.removeprefix(
            "www."
        ) == "abduzeedo.com" and page.og_type not in {"", "article"}:
            raise ReferenceError(
                "not_an_article", stage="page", url=page_url, status=200
            )
        if not page.images or not page.title:
            raise ReferenceError(
                "missing_artwork_metadata", stage="page", url=page_url, status=200
            )
        image_failures = []
        for image_path in page.images[:2]:
            image_url = urljoin(page_url, image_path)
            try:
                image_url, _, content = await fetch_public(image_url, stage="image")
                try:
                    normalized, width, height, signature = await asyncio.to_thread(
                        normalize_image, content
                    )
                except DrawError:
                    raise ReferenceError(
                        "invalid_image", stage="decode", url=image_url, status=200
                    ) from None
                break
            except ReferenceError as exc:
                image_failures.append(exc.details)
                if len(image_failures) == min(2, len(page.images)):
                    exc.details["image_failures"] = [
                        dict(item) for item in image_failures
                    ]
                    raise
        record = {
            "id": f"candidate-{number}",
            "page": display_url(page_url),
            "image": display_url(image_url),
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
            "image_failures": image_failures,
            "image_origin": page.image_origins[image_path],
            "image_decoded": True,
            "source_route": "publisher",
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
