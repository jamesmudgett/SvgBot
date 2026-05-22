from fastapi import APIRouter

from app.api.agent_docs import router as agent_router
from app.config import get_settings, starvector_config_debug
from app.services import starvector_engine

router = APIRouter(tags=["discovery"])
router.include_router(agent_router)


API_VERSION = "0.1.1"


@router.get("/health")
async def health():
    sv = starvector_engine.availability()
    return {
        "status": "ok",
        "api_version": API_VERSION,
        "starvector": sv["ready"],
        "starvector_detail": sv,
        "starvector_config": starvector_config_debug(),
        "payments": get_settings().payments_enabled,
        "price_per_conversion_usd": get_settings().price_per_conversion_usd,
    }
