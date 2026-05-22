from fastapi import HTTPException, Request

from app.config import QualityTier, get_settings


def parse_form_bool(value: str | bool) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("true", "1", "yes", "on")


async def verify_payment(request: Request, _quality: QualityTier = "standard") -> None:
    """MPP charge hook — x402 is handled by ASGI middleware before the route."""
    settings = get_settings()
    if not settings.payments_enabled:
        return

    mpp = getattr(request.app.state, "mpp", None)
    if mpp is None:
        return

    try:
        await mpp.charge(request, amount=settings.price_per_conversion_usd)
    except Exception as e:
        raise HTTPException(402, f"Payment required: {e}") from e
