"""Safe HTTP image downloader.

Used by the ``/api/vectorize`` endpoint when the client sends an ``image_url``
instead of a multipart upload. Enforces:

- ``http`` / ``https`` only (no ``file://`` etc.)
- known image content-types
- max-size cap mirrored from ``settings.max_upload_bytes``
- streamed download with running size check (so a server lying about
  ``Content-Length`` can't OOM us)
- bounded redirect chain + per-request timeout
"""

from __future__ import annotations

import logging
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)


class UrlFetchError(Exception):
    """Raised when an image URL is rejected or fails to download cleanly."""


_ALLOWED_SCHEMES = frozenset({"http", "https"})

# Common image content-types VTracer/StarVector/Pillow handle. Servers often
# return ``application/octet-stream`` for legitimate images, so we accept that
# too and let Pillow decide if the bytes are a valid image downstream.
_ALLOWED_TYPES = frozenset(
    {
        "image/png",
        "image/jpeg",
        "image/jpg",
        "image/webp",
        "image/gif",
        "image/bmp",
        "image/tiff",
        "image/x-icon",
        "image/vnd.microsoft.icon",
        "application/octet-stream",
    }
)


def fetch_image(
    url: str,
    *,
    max_bytes: int,
    timeout: float = 15.0,
    max_redirects: int = 5,
) -> bytes:
    """Download bytes from ``url`` with strict safety checks.

    Raises :class:`UrlFetchError` for any user-facing rejection reason
    (bad scheme, oversized payload, network error, non-image content-type)
    so the API layer can surface a clear message.
    """
    parsed = urlparse(url.strip())
    if parsed.scheme not in _ALLOWED_SCHEMES:
        raise UrlFetchError(
            f"Only http(s) URLs are supported (got {parsed.scheme or 'no scheme'!r})."
        )
    if not parsed.netloc:
        raise UrlFetchError("URL is missing a host.")

    try:
        with httpx.Client(
            follow_redirects=True,
            timeout=timeout,
            max_redirects=max_redirects,
            headers={"User-Agent": "SvgBot/1.0 (+image-fetch)"},
        ) as client:
            with client.stream("GET", url) as resp:
                if resp.status_code >= 400:
                    raise UrlFetchError(
                        f"Image host returned HTTP {resp.status_code}."
                    )

                content_type = (
                    resp.headers.get("content-type", "").split(";", 1)[0].strip().lower()
                )
                if content_type and content_type not in _ALLOWED_TYPES:
                    raise UrlFetchError(
                        f"URL did not return an image (content-type: {content_type!r})."
                    )

                content_length = resp.headers.get("content-length")
                if content_length and content_length.isdigit():
                    if int(content_length) > max_bytes:
                        raise UrlFetchError(
                            f"Image is too large ({content_length} bytes; max {max_bytes})."
                        )

                buf = bytearray()
                for chunk in resp.iter_bytes(chunk_size=64 * 1024):
                    buf.extend(chunk)
                    if len(buf) > max_bytes:
                        raise UrlFetchError(
                            f"Image exceeded max size of {max_bytes} bytes during download."
                        )
                if not buf:
                    raise UrlFetchError("URL returned an empty response.")
                return bytes(buf)
    except httpx.RequestError as exc:
        raise UrlFetchError(f"Could not fetch URL: {exc}") from exc
