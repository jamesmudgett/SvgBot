import logging
import os
import traceback

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.discovery import router as discovery_router
from app.api.editor import router as editor_router
from app.api.jobs import router as jobs_router
from app.config import get_settings, starvector_config_debug
from app.payments.setup import configure_payments
from app.services.cairo_compat import ensure_cairo_stubs

logging.basicConfig(level=logging.INFO)

# Light startup only — StarVector patches load lazily in starvector_engine
ensure_cairo_stubs()

settings = get_settings()
if settings.hf_token and not os.environ.get("HF_TOKEN"):
    os.environ["HF_TOKEN"] = settings.hf_token

app = FastAPI(title=settings.app_name, version="0.1.0")
logger = logging.getLogger(__name__)

_dbg = starvector_config_debug()
logger.info(
    "StarVector config: enabled=%s (backend/.env=%s, process env=%s)",
    _dbg["starvector_enabled"],
    _dbg["env_file_value"],
    _dbg["process_env"],
)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.error("Unhandled error on %s %s: %s", request.method, request.url.path, exc)
    logger.debug(traceback.format_exc())
    return JSONResponse(
        status_code=500,
        content={"detail": str(exc), "path": request.url.path},
    )


origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1)(:\d+)?",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

configure_payments(app)

app.include_router(discovery_router)
app.include_router(jobs_router)
app.include_router(editor_router)
