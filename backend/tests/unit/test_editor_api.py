"""Tests for the post-conversion SVG editor endpoints.

Covers:
- ``GET /api/jobs/{id}/original`` (download the original raster bytes
  associated with a vectorize job, used by the editor to overlay the
  source image on top of the SVG).
- ``POST /api/editor/llm-edit`` (Grok-backed SVG revision endpoint).
"""

from __future__ import annotations

import json
import time
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app
from app.services import url_fetch

client = TestClient(app)


# ----------------------------------------------------------------------------
# /api/jobs/{id}/original
# ----------------------------------------------------------------------------


def _wait_for_completion(job_id: str, timeout_s: float = 30.0) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        body = client.get(f"/api/jobs/{job_id}").json()
        if body["status"] in ("completed", "failed"):
            return body
        time.sleep(0.25)
    raise AssertionError(f"job {job_id} did not finish within {timeout_s}s")


def test_original_endpoint_returns_uploaded_bytes(logo_png: bytes):
    """Uploading a PNG and then asking for /original must return the exact
    bytes that were uploaded with an image content-type, so the editor can
    render the source on top of the SVG without re-encoding artifacts."""

    r = client.post(
        "/api/vectorize",
        files={"file": ("logo.png", logo_png, "image/png")},
        data={"quality": "standard", "engine": "vtracer"},
    )
    assert r.status_code == 200
    job_id = r.json()["job_id"]

    body = _wait_for_completion(job_id)
    assert body["status"] == "completed", body.get("error")

    orig = client.get(f"/api/jobs/{job_id}/original")
    assert orig.status_code == 200
    assert orig.headers["content-type"].startswith("image/")
    assert orig.content == logo_png


def test_original_endpoint_via_url_capture(
    logo_png: bytes, monkeypatch: pytest.MonkeyPatch
):
    """When the source came from an image_url, the bytes that were fetched
    should still be retrievable via /original (the editor doesn't care how
    they got there)."""

    def fake_fetch(url: str, *, max_bytes: int, timeout: float = 15.0, **_):
        return logo_png

    monkeypatch.setattr(url_fetch, "fetch_image", fake_fetch)

    r = client.post(
        "/api/vectorize",
        data={
            "image_url": "https://example.com/logo.png",
            "quality": "standard",
            "engine": "vtracer",
        },
    )
    assert r.status_code == 200
    job_id = r.json()["job_id"]

    body = _wait_for_completion(job_id)
    assert body["status"] == "completed", body.get("error")

    orig = client.get(f"/api/jobs/{job_id}/original")
    assert orig.status_code == 200
    assert orig.content == logo_png


def test_original_endpoint_404_for_unknown_job():
    r = client.get("/api/jobs/does-not-exist/original")
    assert r.status_code == 404


# ----------------------------------------------------------------------------
# /api/editor/llm-edit
# ----------------------------------------------------------------------------


_VALID_SVG_IN = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">'
    '<rect id="el-1" x="0" y="0" width="64" height="64" fill="#ff0000"/>'
    "</svg>"
)
_VALID_SVG_OUT = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">'
    '<rect id="el-1" x="0" y="0" width="64" height="64" fill="#00ff00"/>'
    "</svg>"
)


def _stub_grok_response(svg: str = _VALID_SVG_OUT, summary: str = "Recolored fill") -> dict:
    """Build a chat-completions style payload that wraps an SVG."""
    body = (
        f"{summary}\n\n```svg\n{svg}\n```"
    )
    return {
        "id": "stub",
        "model": "grok-4-stub",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": body},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 12, "completion_tokens": 34, "total_tokens": 46},
    }


class _StubResponse:
    """Tiny stand-in for httpx.Response used by the LLM client."""

    def __init__(self, *, status_code: int = 200, json_body: dict | None = None,
                 text: str = ""):
        self.status_code = status_code
        self._json = json_body or {}
        self.text = text or json.dumps(self._json)

    def json(self) -> dict:
        return self._json

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                f"status {self.status_code}",
                request=httpx.Request("POST", "https://api.x.ai/v1/chat/completions"),
                response=httpx.Response(self.status_code),
            )


def _patch_grok(monkeypatch: pytest.MonkeyPatch, response: _StubResponse) -> dict:
    """Patch ``llm_editor._post_chat_completion`` to return ``response`` and
    return a dict the test can introspect for the captured request body."""
    from app.services import llm_editor

    captured: dict[str, Any] = {}

    def fake_post(*, url: str, headers: dict, json_body: dict, timeout: float):
        captured["url"] = url
        captured["headers"] = headers
        captured["json"] = json_body
        captured["timeout"] = timeout
        return response

    monkeypatch.setattr(llm_editor, "_post_chat_completion", fake_post)
    return captured


def _override_settings(monkeypatch: pytest.MonkeyPatch, **fields: Any) -> None:
    """Mutate the cached Settings instance for the duration of the test.

    The dotenv layer in ``Settings.settings_customise_sources`` runs before
    process env, so ``monkeypatch.setenv`` alone is not enough to override
    ``XAI_API_KEY`` when ``backend/.env`` ships ``XAI_API_KEY=`` (empty).
    ``monkeypatch.setattr`` auto-restores the original values at the end
    of each test.
    """
    settings = get_settings()
    for key, value in fields.items():
        monkeypatch.setattr(settings, key, value)


def test_llm_edit_calls_grok_and_returns_svg(monkeypatch: pytest.MonkeyPatch):
    _override_settings(monkeypatch, xai_api_key="test-key")

    captured = _patch_grok(
        monkeypatch,
        _StubResponse(json_body=_stub_grok_response()),
    )

    r = client.post(
        "/api/editor/llm-edit",
        json={
            "job_id": "any",
            "svg": _VALID_SVG_IN,
            "instruction": "Make the rect green",
            "selected_ids": ["el-1"],
            "include_original": False,
        },
    )

    assert r.status_code == 200, r.text
    body = r.json()
    assert "<svg" in body["svg"]
    assert "00ff00" in body["svg"].lower()
    assert body["summary"]
    assert "X-Editor-Quota-Remaining" in r.headers

    assert captured["url"].startswith("https://")
    assert captured["headers"]["Authorization"].startswith("Bearer ")
    payload = captured["json"]
    assert payload["model"]
    text_parts: list[str] = []
    for m in payload["messages"]:
        content = m.get("content")
        if isinstance(content, str):
            text_parts.append(content)
        elif isinstance(content, list):
            for part in content:
                if isinstance(part, dict) and part.get("type") == "text":
                    text_parts.append(str(part.get("text") or ""))
    assert any("Make the rect green" in t for t in text_parts)


def test_llm_edit_includes_original_when_requested(
    monkeypatch: pytest.MonkeyPatch, logo_png: bytes
):
    """When ``include_original=true`` the request body should contain a
    ``data:image/...`` reference so Grok can see the source raster."""

    _override_settings(monkeypatch, xai_api_key="test-key")

    r = client.post(
        "/api/vectorize",
        files={"file": ("logo.png", logo_png, "image/png")},
        data={"quality": "standard", "engine": "vtracer"},
    )
    assert r.status_code == 200
    job_id = r.json()["job_id"]
    body = _wait_for_completion(job_id)
    assert body["status"] == "completed", body.get("error")

    captured = _patch_grok(
        monkeypatch,
        _StubResponse(json_body=_stub_grok_response()),
    )

    edit = client.post(
        "/api/editor/llm-edit",
        json={
            "job_id": job_id,
            "svg": _VALID_SVG_IN,
            "instruction": "Match the original",
            "selected_ids": [],
            "include_original": True,
        },
    )

    assert edit.status_code == 200, edit.text

    payload = captured["json"]
    serialized = json.dumps(payload)
    assert "data:image/" in serialized


def test_llm_edit_forwards_region_to_grok(monkeypatch: pytest.MonkeyPatch):
    """When the marquee region is supplied, the user-message text must
    describe its bounds so Grok can scope its edits to it."""

    _override_settings(monkeypatch, xai_api_key="test-key")

    captured = _patch_grok(
        monkeypatch,
        _StubResponse(json_body=_stub_grok_response()),
    )

    r = client.post(
        "/api/editor/llm-edit",
        json={
            "job_id": "any",
            "svg": _VALID_SVG_IN,
            "instruction": "Smooth corners in this region",
            "selected_ids": [],
            "include_original": False,
            "region": {"x": 12, "y": 34, "width": 56, "height": 78},
        },
    )
    assert r.status_code == 200, r.text

    payload = captured["json"]
    serialized = json.dumps(payload)
    assert "Region of interest" in serialized
    assert "x=12" in serialized
    assert "y=34" in serialized
    assert "width=56" in serialized
    assert "height=78" in serialized


def test_llm_edit_no_api_key_returns_503(monkeypatch: pytest.MonkeyPatch):
    _override_settings(monkeypatch, xai_api_key="")

    r = client.post(
        "/api/editor/llm-edit",
        json={
            "job_id": "any",
            "svg": _VALID_SVG_IN,
            "instruction": "Recolor",
        },
    )

    assert r.status_code == 503
    assert "grok" in r.json()["detail"].lower() or "xai" in r.json()["detail"].lower()


def test_llm_edit_invalid_svg_response_returns_502(monkeypatch: pytest.MonkeyPatch):
    _override_settings(monkeypatch, xai_api_key="test-key")

    bad_payload = {
        "id": "stub",
        "model": "grok-4-stub",
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": "Sorry I can't help with that.",
                },
                "finish_reason": "stop",
            }
        ],
    }
    _patch_grok(monkeypatch, _StubResponse(json_body=bad_payload))

    r = client.post(
        "/api/editor/llm-edit",
        json={
            "job_id": "any",
            "svg": _VALID_SVG_IN,
            "instruction": "Recolor",
        },
    )

    assert r.status_code == 502
    assert "svg" in r.json()["detail"].lower()


def test_llm_edit_rejects_oversize_svg(monkeypatch: pytest.MonkeyPatch):
    _override_settings(
        monkeypatch, xai_api_key="test-key", editor_max_svg_bytes=256
    )

    big_svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1 1">'
        + ('<rect width="1" height="1"/>' * 200)
        + "</svg>"
    )

    r = client.post(
        "/api/editor/llm-edit",
        json={
            "job_id": "any",
            "svg": big_svg,
            "instruction": "shrink",
        },
    )

    assert r.status_code == 413
    assert "svg" in r.json()["detail"].lower()


def test_llm_edit_quota_blocks_when_limit_exhausted(
    monkeypatch: pytest.MonkeyPatch,
):
    """When EDITOR_FREE_LIMIT is set to 0 we have unlimited; setting it to 1
    should permit one request and then 402 the next from the same client."""

    _override_settings(
        monkeypatch, xai_api_key="test-key", editor_free_limit=1
    )

    from app.services import editor_quota

    editor_quota.reset_for_tests()

    _patch_grok(
        monkeypatch,
        _StubResponse(json_body=_stub_grok_response()),
    )

    payload = {
        "job_id": "any",
        "svg": _VALID_SVG_IN,
        "instruction": "tweak",
    }
    r1 = client.post("/api/editor/llm-edit", json=payload)
    assert r1.status_code == 200, r1.text
    assert r1.headers["X-Editor-Quota-Remaining"] == "0"

    r2 = client.post("/api/editor/llm-edit", json=payload)
    assert r2.status_code == 402
    assert r2.headers["X-Editor-Quota-Remaining"] == "0"

    editor_quota.reset_for_tests()
