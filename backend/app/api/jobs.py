import logging

from fastapi import (
    APIRouter,
    BackgroundTasks,
    File,
    Form,
    HTTPException,
    Request,
    UploadFile,
)
from fastapi.responses import Response

from app.api.deps import parse_form_bool, verify_payment

logger = logging.getLogger(__name__)
from app.config import EngineChoice, QualityTier, get_settings
from app.models.schemas import JobCreateResponse, JobStatusResponse
from app.services import jobs as job_service

router = APIRouter(prefix="/api", tags=["vectorize"])


@router.post("/vectorize", response_model=JobCreateResponse)
async def create_vectorize_job(
    request: Request,
    background_tasks: BackgroundTasks,
    file: UploadFile | None = File(None),
    image_url: str | None = Form(None),
    quality: QualityTier = Form("standard"),
    engine: EngineChoice = Form("auto"),
    fontless: str = Form("true"),
):
    """Vectorize an image. Provide either a multipart ``file`` upload OR an
    ``image_url`` form field pointing to a publicly-fetchable image.

    When both are sent, ``file`` takes precedence; when neither is sent we
    return 400 so the client gets an actionable error instead of a stalled job.
    """
    try:
        await verify_payment(request, quality)
        settings = get_settings()

        data: bytes | None = None
        if file is not None and file.filename:
            data = await file.read()
            if len(data) > settings.max_upload_bytes:
                raise HTTPException(413, "File too large")
            if not data:
                raise HTTPException(400, "Empty file")

        url = (image_url or "").strip() or None
        if data is None and not url:
            raise HTTPException(
                400, "Provide either an uploaded `file` or an `image_url`."
            )

        job_id = job_service.create_job(
            background_tasks,
            image_data=data,
            image_url=url,
            quality=quality,
            engine=engine,
            fontless=parse_form_bool(fontless),
        )
        return JobCreateResponse(job_id=job_id)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("vectorize upload failed")
        raise HTTPException(500, f"Upload failed: {exc}") from exc


@router.get("/jobs/{job_id}", response_model=JobStatusResponse)
async def get_job_status(job_id: str):
    job = job_service.get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    return job


@router.get("/jobs/{job_id}/svg")
async def download_svg(job_id: str):
    job = job_service.get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    if job.status != "completed" or not job.result:
        raise HTTPException(409, f"Job not ready: {job.status}")
    return Response(
        content=job.result.svg,
        media_type="image/svg+xml",
        headers={"Content-Disposition": f'attachment; filename="{job_id}.svg"'},
    )
