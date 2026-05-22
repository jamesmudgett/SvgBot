"""Wire x402 and MPP payment middleware when enabled."""

from __future__ import annotations

import logging

from fastapi import FastAPI

from app.config import get_settings

logger = logging.getLogger(__name__)


def configure_payments(app: FastAPI) -> None:
    settings = get_settings()
    if not settings.payments_enabled:
        logger.info("Payments disabled (PAYMENTS_ENABLED=false)")
        return

    try:
        _configure_mpp(app, settings)
        _configure_x402(app, settings)
    except Exception as exc:
        logger.error("Payment setup failed (API will run without payments): %s", exc)


def _configure_mpp(app: FastAPI, settings) -> None:
    if not settings.mpp_secret_key:
        logger.warning("MPP_SECRET_KEY not set; skipping MPP middleware")
        return

    try:
        from mpp.server import Mpp
        from mpp.methods.tempo import ChargeIntent, tempo
    except ImportError:
        logger.warning("pympp not installed; skipping MPP")
        return

    if not settings.mpp_tempo_recipient or not settings.mpp_tempo_currency:
        logger.warning("MPP tempo recipient/currency not configured")
        return

    mpp = Mpp.create(
        method=tempo(
            currency=settings.mpp_tempo_currency,
            intents={"charge": ChargeIntent()},
            recipient=settings.mpp_tempo_recipient,
        ),
        secret_key=settings.mpp_secret_key,
    )
    app.state.mpp = mpp
    logger.info("MPP payment middleware configured")


def _configure_x402(app: FastAPI, settings) -> None:
    if not settings.x402_enabled or not settings.x402_evm_address:
        logger.info("x402 disabled or EVM_ADDRESS missing")
        return

    try:
        from x402.http import FacilitatorConfig, HTTPFacilitatorClient
        from x402.http.types import PaymentOption, RouteConfig
        from x402.mechanisms.evm.exact import ExactEvmServerScheme
        from x402.server import x402ResourceServer
        from x402.fastapi import PaymentMiddlewareASGI
    except ImportError:
        logger.warning("x402 package not installed; skipping x402")
        return

    facilitator = HTTPFacilitatorClient(
        FacilitatorConfig(url=settings.x402_facilitator_url)
    )
    server = x402ResourceServer(facilitator)
    server.register(settings.x402_network, ExactEvmServerScheme())

    routes = {
        "POST /api/vectorize": RouteConfig(
            accepts=[
                PaymentOption(
                    scheme="exact",
                    price=settings.price_per_conversion_usd,
                    network=settings.x402_network,
                    pay_to=settings.x402_evm_address,
                ),
            ]
        ),
    }

    app.add_middleware(
        PaymentMiddlewareASGI,
        routes=routes,
        server=server,
    )
    logger.info("x402 payment middleware configured for POST /api/vectorize")
