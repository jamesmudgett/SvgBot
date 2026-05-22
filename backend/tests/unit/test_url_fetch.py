"""Tests for the safe-image URL fetcher used by /api/vectorize.

We mount an httpx ``MockTransport`` so each test can script the response without
hitting the network. This locks in:
- bad URL schemes are rejected with a friendly message
- oversized payloads abort mid-stream (so a lying Content-Length can't OOM us)
- unsupported content-types are rejected
- happy-path returns the bytes intact
"""

from __future__ import annotations

import httpx
import pytest

from app.services import url_fetch


def _patched_client(monkeypatch: pytest.MonkeyPatch, transport: httpx.MockTransport) -> None:
    original = httpx.Client

    def make_client(*args, **kwargs):
        kwargs["transport"] = transport
        return original(*args, **kwargs)

    monkeypatch.setattr(httpx, "Client", make_client)


def test_fetch_image_rejects_non_http_schemes():
    with pytest.raises(url_fetch.UrlFetchError) as exc:
        url_fetch.fetch_image("ftp://example.com/foo.png", max_bytes=1024)
    assert "http(s)" in str(exc.value)


def test_fetch_image_rejects_missing_host():
    with pytest.raises(url_fetch.UrlFetchError):
        url_fetch.fetch_image("http:///foo.png", max_bytes=1024)


def test_fetch_image_rejects_unsupported_content_type(monkeypatch: pytest.MonkeyPatch):
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200, headers={"content-type": "text/html"}, content=b"<html></html>"
        )
    )
    _patched_client(monkeypatch, transport)
    with pytest.raises(url_fetch.UrlFetchError) as exc:
        url_fetch.fetch_image("https://example.com/page", max_bytes=10_000)
    assert "content-type" in str(exc.value).lower()


def test_fetch_image_rejects_oversized_via_content_length(
    monkeypatch: pytest.MonkeyPatch,
):
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            headers={
                "content-type": "image/png",
                "content-length": "999999",
            },
            content=b"\x89PNG\r\n",
        )
    )
    _patched_client(monkeypatch, transport)
    with pytest.raises(url_fetch.UrlFetchError) as exc:
        url_fetch.fetch_image("https://example.com/big.png", max_bytes=1024)
    assert "too large" in str(exc.value).lower()


def test_fetch_image_aborts_when_stream_exceeds_max(monkeypatch: pytest.MonkeyPatch):
    """Even when Content-Length is missing or lies, the running counter must trip."""
    big_chunk = b"\x89PNG\r\n" + b"\x00" * 4096

    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200, headers={"content-type": "image/png"}, content=big_chunk
        )
    )
    _patched_client(monkeypatch, transport)
    with pytest.raises(url_fetch.UrlFetchError) as exc:
        url_fetch.fetch_image("https://example.com/lie.png", max_bytes=512)
    assert "exceeded" in str(exc.value).lower() or "too large" in str(exc.value).lower()


def test_fetch_image_returns_bytes_for_valid_image(monkeypatch: pytest.MonkeyPatch):
    payload = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64

    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200, headers={"content-type": "image/png"}, content=payload
        )
    )
    _patched_client(monkeypatch, transport)
    out = url_fetch.fetch_image("https://example.com/logo.png", max_bytes=10_000)
    assert out == payload


def test_fetch_image_propagates_http_errors(monkeypatch: pytest.MonkeyPatch):
    transport = httpx.MockTransport(
        lambda request: httpx.Response(404, text="not found")
    )
    _patched_client(monkeypatch, transport)
    with pytest.raises(url_fetch.UrlFetchError) as exc:
        url_fetch.fetch_image("https://example.com/missing.png", max_bytes=1024)
    assert "404" in str(exc.value)
