import time

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import url_fetch

client = TestClient(app)


def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_discovery():
    r = client.get("/.well-known/mpp-discovery")
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "SvgBot"
    assert body["price_per_conversion_usd"] == "0.50"
    assert any(e["path"] == "/api/vectorize" for e in body["endpoints"])
    assert body["documentation_url"].endswith("/.well-known/agent-api")


def test_agent_api():
    r = client.get("/.well-known/agent-api")
    assert r.status_code == 200
    body = r.json()
    assert body["service"] == "SvgBot"
    assert body["payment"]["price_usd"] == "0.50"
    assert any(e["path"] == "/api/vectorize" for e in body["endpoints"])
    assert len(body["workflow"]) >= 3


def test_vectorize_job_flow(logo_png: bytes):
    r = client.post(
        "/api/vectorize",
        files={"file": ("logo.png", logo_png, "image/png")},
        data={"quality": "standard", "engine": "vtracer"},
    )
    assert r.status_code == 200
    job_id = r.json()["job_id"]

    for _ in range(60):
        status = client.get(f"/api/jobs/{job_id}")
        assert status.status_code == 200
        data = status.json()
        if data["status"] in ("completed", "failed"):
            break
        time.sleep(0.5)

    assert data["status"] == "completed", data.get("error")
    assert data["phase"] == "done"
    assert data["result"]["svg"]
    metrics = data["result"]["metrics"]
    assert metrics["engine"] == "vtracer"
    assert "base_dino_score" in metrics
    assert metrics["base_dino_score"] is not None
    assert metrics["refine_passes"] >= 0
    assert 0.0 <= metrics["refine_coverage"] <= 1.0

    svg_resp = client.get(f"/api/jobs/{job_id}/svg")
    assert svg_resp.status_code == 200
    assert "image/svg+xml" in svg_resp.headers["content-type"]


def test_vectorize_rejects_oversized_photo():
    """Photos above the kind-specific cap must fail fast with a clear 413."""
    from tests.unit.test_image_limits import _large_photo

    r = client.post(
        "/api/vectorize",
        files={"file": ("big-photo.png", _large_photo(2400, 1800), "image/png")},
        data={"quality": "standard", "engine": "vtracer"},
    )
    assert r.status_code == 413
    assert "photo" in r.json()["detail"].lower()


def test_vectorize_requires_file_or_url():
    """Submitting neither a file nor a URL must produce a clear 400 instead of
    silently queueing a job that will never have any input bytes."""
    r = client.post(
        "/api/vectorize",
        data={"quality": "standard", "engine": "vtracer"},
    )
    assert r.status_code == 400
    assert "image_url" in r.json()["detail"]


def test_vectorize_via_image_url(
    logo_png: bytes, monkeypatch: pytest.MonkeyPatch
):
    """Posting `image_url` instead of a file must download the bytes and run
    the same pipeline. We monkeypatch the fetcher so the test stays offline."""
    captured: dict[str, str] = {}

    def fake_fetch(url: str, *, max_bytes: int, timeout: float = 15.0, **_):
        captured["url"] = url
        captured["max_bytes"] = max_bytes
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

    for _ in range(60):
        status = client.get(f"/api/jobs/{job_id}")
        body = status.json()
        if body["status"] in ("completed", "failed"):
            break
        time.sleep(0.5)

    assert body["status"] == "completed", body.get("error")
    assert body["phase"] == "done"
    assert captured["url"] == "https://example.com/logo.png"
    assert captured["max_bytes"] > 0


def test_vectorize_url_failure_surfaces_in_job(
    monkeypatch: pytest.MonkeyPatch,
):
    """When the URL fetch fails, the job should end in a failed state with a
    user-readable error — not crash the server and not stay queued forever."""

    def boom(url: str, *, max_bytes: int, timeout: float = 15.0, **_):
        raise url_fetch.UrlFetchError("URL did not return an image (content-type: 'text/html').")

    monkeypatch.setattr(url_fetch, "fetch_image", boom)

    r = client.post(
        "/api/vectorize",
        data={
            "image_url": "https://example.com/page.html",
            "quality": "standard",
            "engine": "vtracer",
        },
    )
    assert r.status_code == 200
    job_id = r.json()["job_id"]

    for _ in range(20):
        body = client.get(f"/api/jobs/{job_id}").json()
        if body["status"] == "failed":
            break
        time.sleep(0.2)

    assert body["status"] == "failed"
    assert body["phase"] == "failed"
    assert "image" in body["error"].lower()
