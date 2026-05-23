from __future__ import annotations

import io
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from fastapi import BackgroundTasks
from PIL import Image

from app.config import EngineChoice, QualityTier, get_settings
from app.models.schemas import (
    CandidateScore,
    JobMetrics,
    JobPhase,
    JobResult,
    JobStatusResponse,
)
from app.services import url_fetch
from app.services.orchestrator import vectorize_bytes

logger = logging.getLogger(__name__)


# Map Pillow ``Image.format`` values to media types so the editor's
# ``GET /jobs/{id}/original`` endpoint serves the bytes with a meaningful
# content-type. Anything we can't recognize falls back to octet-stream.
_FORMAT_MIME: dict[str, str] = {
    "PNG": "image/png",
    "JPEG": "image/jpeg",
    "WEBP": "image/webp",
    "GIF": "image/gif",
    "BMP": "image/bmp",
    "TIFF": "image/tiff",
    "ICO": "image/x-icon",
}


def _detect_image_mime(data: bytes) -> str:
    try:
        with Image.open(io.BytesIO(data)) as img:
            fmt = (img.format or "").upper()
        return _FORMAT_MIME.get(fmt, "application/octet-stream")
    except Exception:
        return "application/octet-stream"


@dataclass
class _Job:
    job_id: str
    status: str = "queued"
    phase: JobPhase = "queued"
    progress: str = "Queued"
    result: JobResult | None = None
    error: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    # Source raster bytes are kept on the job so the editor can render the
    # original on top of the SVG. Captured eagerly for uploads and after the
    # URL fetcher resolves for image_url submissions.
    original_bytes: bytes | None = None
    original_mime: str | None = None


_store: dict[str, _Job] = {}


def create_job(
    background_tasks: BackgroundTasks,
    *,
    image_data: bytes | None = None,
    image_url: str | None = None,
    quality: QualityTier,
    engine: EngineChoice,
    fontless: bool,
) -> str:
    """Queue a vectorization job. Caller must supply either bytes or a URL."""
    if image_data is None and not image_url:
        raise ValueError("create_job requires either image_data or image_url")

    job_id = str(uuid.uuid4())
    job = _Job(job_id=job_id)
    if image_data is not None:
        job.original_bytes = image_data
        job.original_mime = _detect_image_mime(image_data)
    _store[job_id] = job
    background_tasks.add_task(
        _run_job,
        job_id,
        image_data=image_data,
        image_url=image_url,
        quality=quality,
        engine=engine,
        fontless=fontless,
    )
    return job_id


def _run_job(
    job_id: str,
    *,
    image_data: bytes | None,
    image_url: str | None,
    quality: QualityTier,
    engine: EngineChoice,
    fontless: bool,
) -> None:
    job = _store[job_id]
    job.status = "running"

    try:
        if image_data is None:
            assert image_url is not None
            job.phase = "fetching"
            job.progress = "Downloading image"
            settings = get_settings()
            try:
                image_data = url_fetch.fetch_image(
                    image_url, max_bytes=settings.max_upload_bytes
                )
            except url_fetch.UrlFetchError as exc:
                job.status = "failed"
                job.phase = "failed"
                job.error = str(exc)
                job.progress = "Failed"
                return
            job.original_bytes = image_data
            job.original_mime = _detect_image_mime(image_data)

        def on_progress(phase: str, message: str) -> None:
            job.phase = phase  # type: ignore[assignment]
            job.progress = message

        out = vectorize_bytes(
            image_data,
            quality=quality,
            engine=engine,
            fontless=fontless,
            progress_callback=on_progress,
        )
        job.result = JobResult(
            svg=out.svg,
            width=out.width,
            height=out.height,
            metrics=JobMetrics(
                dino_score=out.dino_score,
                lpips=out.lpips,
                engine=out.engine,
                candidates_tried=out.candidates_tried,
                path_count=out.path_count,
                ms=out.ms,
                base_dino_score=out.base_dino_score,
                refine_passes=out.refine_passes,
                refine_coverage=out.refine_coverage,
                candidate_scores=[CandidateScore(**c) for c in out.candidate_scores],
                decision=out.decision,
            ),
        )
        job.status = "completed"
        job.phase = "done"
        job.progress = "Done"
    except Exception as e:
        logger.exception("vectorize job %s failed", job_id)
        job.status = "failed"
        job.phase = "failed"
        job.error = str(e)
        job.progress = "Failed"


def get_job(job_id: str) -> JobStatusResponse | None:
    job = _store.get(job_id)
    if not job:
        return None
    return JobStatusResponse(
        job_id=job.job_id,
        status=job.status,  # type: ignore[arg-type]
        phase=job.phase,
        progress=job.progress,
        result=job.result,
        error=job.error,
    )


def get_original(job_id: str) -> tuple[bytes, str] | None:
    """Return ``(bytes, mime)`` for the job's source raster or ``None`` if the
    job is unknown / never received any source bytes (e.g. a URL fetch failed
    before the bytes were captured)."""
    job = _store.get(job_id)
    if not job or not job.original_bytes:
        return None
    return job.original_bytes, job.original_mime or "application/octet-stream"
