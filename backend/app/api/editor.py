"""Routes for the post-conversion SVG editor."""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from app.config import get_settings
from app.models.schemas import LlmEditRequest, LlmEditResponse
from app.services import editor_quota, jobs as job_service, llm_editor

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/editor", tags=["editor"])


@router.post("/llm-edit")
async def llm_edit(request: Request, body: LlmEditRequest) -> JSONResponse:
    """Apply a Grok-driven revision to the current editor SVG.

    The caller posts the current SVG, an instruction, and (optionally) a
    list of element ids the user has selected in the canvas. The server
    proxies to xAI so the API key never leaves the host. When
    ``include_original`` is true we attach the job's source raster so
    Grok can compare the SVG against the input image.
    """
    settings = get_settings()

    if not settings.xai_api_key:
        raise HTTPException(
            status_code=503,
            detail=(
                "Grok (xAI) is not configured on this server. Set XAI_API_KEY "
                "in backend/.env to enable LLM-driven SVG edits."
            ),
        )

    if len(body.svg.encode("utf-8")) > settings.editor_max_svg_bytes:
        raise HTTPException(
            status_code=413,
            detail=(
                "SVG is too large for an LLM edit "
                f"(over {settings.editor_max_svg_bytes} bytes). "
                "Try editing locally with the toolbar instead."
            ),
        )

    if not body.instruction.strip():
        raise HTTPException(status_code=400, detail="Instruction is required.")

    decision = editor_quota.check_and_decrement(request)
    quota_header = editor_quota.quota_header_value(decision)
    if not decision.allowed:
        return JSONResponse(
            status_code=402,
            content={
                "detail": (
                    "Free LLM-edit quota exhausted. Upgrade or wait for the "
                    "next reset to keep editing."
                ),
                "limit": decision.limit,
                "remaining": decision.remaining,
            },
            headers={"X-Editor-Quota-Remaining": quota_header},
        )

    original_image: tuple[bytes, str] | None = None
    if body.include_original:
        original_image = job_service.get_original(body.job_id)

    region_tuple: tuple[float, float, float, float] | None = None
    if body.region is not None:
        region_tuple = (
            float(body.region.x),
            float(body.region.y),
            float(body.region.width),
            float(body.region.height),
        )

    try:
        result = await run_in_threadpool(
            llm_editor.edit_svg,
            svg=body.svg,
            instruction=body.instruction,
            selected_ids=list(body.selected_ids or []),
            original_image=original_image,
            region=region_tuple,
            model=body.model,
        )
    except llm_editor.LlmEditError as exc:
        status = _status_for_code(exc.code)
        return JSONResponse(
            status_code=status,
            content={"detail": str(exc), "code": exc.code},
            headers={"X-Editor-Quota-Remaining": quota_header},
        )
    except Exception as exc:
        logger.exception("LLM edit failed")
        return JSONResponse(
            status_code=500,
            content={"detail": f"Internal LLM-edit failure: {exc}"},
            headers={"X-Editor-Quota-Remaining": quota_header},
        )

    payload = LlmEditResponse(
        svg=result.svg,
        summary=result.summary,
        model=result.model,
        ms=result.ms,
        tokens_in=result.tokens_in,
        tokens_out=result.tokens_out,
        quota_remaining=decision.remaining,
    )
    return JSONResponse(
        status_code=200,
        content=payload.model_dump(),
        headers={"X-Editor-Quota-Remaining": quota_header},
    )


def _status_for_code(code: str) -> int:
    return {
        "no_api_key": 503,
        "upstream_http": 502,
        "upstream_network": 502,
        "invalid_svg": 502,
    }.get(code, 500)
