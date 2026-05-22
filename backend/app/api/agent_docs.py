"""Machine-readable agent API instructions and MPP discovery helpers."""

from __future__ import annotations

from fastapi import APIRouter, Request

from app.config import get_settings
from app.models.schemas import (
    AgentApiDocument,
    AgentApiEndpoint,
    AgentApiPaymentInfo,
    DiscoveryDocument,
    DiscoveryEndpoint,
)

router = APIRouter(tags=["agent"])


def _base_url(request: Request) -> str:
    return str(request.base_url).rstrip("/")


def build_discovery(request: Request) -> DiscoveryDocument:
    settings = get_settings()
    base = _base_url(request)
    price = settings.price_per_conversion_usd
    protocols = ["mpp", "x402"] if settings.payments_enabled else []

    return DiscoveryDocument(
        name=settings.app_name,
        version="0.1.0",
        description="High-quality image to fontless SVG conversion for humans and agents.",
        price_per_conversion_usd=price,
        documentation_url=f"{base}/.well-known/agent-api",
        endpoints=[
            DiscoveryEndpoint(
                path="/api/vectorize",
                method="POST",
                price_usd=price if settings.payments_enabled else "0",
                description=(
                    "Vectorize an image to fontless SVG. "
                    "Returns job_id; poll GET /api/jobs/{job_id} until completed."
                ),
            ),
        ],
        payment_protocols=protocols,
    )


def build_agent_api(request: Request) -> AgentApiDocument:
    settings = get_settings()
    base = _base_url(request)
    price = settings.price_per_conversion_usd
    payments_on = settings.payments_enabled

    mpp_info = None
    if payments_on and settings.mpp_secret_key:
        mpp_info = {
            "method": "tempo",
            "intent": "charge",
            "amount_usd": price,
            "currency": settings.mpp_tempo_currency or None,
            "recipient": settings.mpp_tempo_recipient or None,
            "discovery": f"{base}/.well-known/mpp-discovery",
            "paid_route": "POST /api/vectorize",
            "client_docs": "https://mpp.dev/guides/one-time-payments",
            "steps": [
                f"GET {base}/.well-known/mpp-discovery to read price ({price} USD) and protocols.",
                "Use the MPP client SDK (pympp) or Tempo wallet to attach payment credentials to POST /api/vectorize.",
                "The server verifies the charge via mpp.charge() before enqueueing the job.",
            ],
        }

    x402_info = None
    if payments_on and settings.x402_enabled and settings.x402_evm_address:
        x402_info = {
            "scheme": "exact",
            "amount_usd": price,
            "network": settings.x402_network,
            "pay_to": settings.x402_evm_address,
            "facilitator": settings.x402_facilitator_url,
            "paid_route": "POST /api/vectorize",
            "client_docs": "https://docs.x402.org",
            "headers": {
                "required_response": "PAYMENT-REQUIRED",
                "retry_with": "PAYMENT-SIGNATURE",
                "confirmation": "PAYMENT-RESPONSE",
            },
            "steps": [
                f"POST {base}/api/vectorize without payment → HTTP 402 with PAYMENT-REQUIRED (amount {price} USD).",
                "Sign a USDC (exact scheme) payment for the advertised network and pay_to address.",
                "Retry the same multipart POST with PAYMENT-SIGNATURE header containing the signed payload.",
                "On success you receive 200 and job_id; poll GET /api/jobs/{job_id}.",
            ],
        }

    protocols: list[str] = []
    if mpp_info:
        protocols.append("mpp")
    if x402_info:
        protocols.append("x402")

    workflow = [
        f"GET {base}/health — confirm API is up (optional: starvector availability).",
        f"GET {base}/.well-known/agent-api — read pricing and payment steps.",
    ]
    if payments_on:
        workflow.append(
            f"Pay {price} USD via MPP (Tempo) or x402, then POST {base}/api/vectorize (multipart)."
        )
    else:
        workflow.append(f"POST {base}/api/vectorize (multipart) — no payment when PAYMENTS_ENABLED=false.")
    workflow.extend(
        [
            f"Poll GET {base}/api/jobs/{{job_id}} every 1–2s until status is completed or failed.",
            f"GET {base}/api/jobs/{{job_id}}/svg — download SVG attachment.",
        ]
    )

    return AgentApiDocument(
        service=settings.app_name,
        version="0.1.0",
        description="Image → fontless SVG for autonomous agents (StarVector + VTracer).",
        base_url=base,
        payment=AgentApiPaymentInfo(
            enabled=payments_on,
            price_usd=price,
            protocols=protocols,
            mpp_discovery_url=f"{base}/.well-known/mpp-discovery",
            agent_instructions_url=f"{base}/.well-known/agent-api",
            mpp=mpp_info,
            x402=x402_info,
        ),
        endpoints=[
            AgentApiEndpoint(
                method="GET",
                path="/health",
                price_usd="0",
                payment_required=False,
                description="Liveness and engine availability.",
            ),
            AgentApiEndpoint(
                method="GET",
                path="/.well-known/mpp-discovery",
                price_usd="0",
                payment_required=False,
                description="MPP/x402 discovery document with per-conversion pricing.",
            ),
            AgentApiEndpoint(
                method="GET",
                path="/.well-known/agent-api",
                price_usd="0",
                payment_required=False,
                description="This document — full agent workflow and payment instructions.",
            ),
            AgentApiEndpoint(
                method="POST",
                path="/api/vectorize",
                price_usd=price if payments_on else "0",
                payment_required=payments_on,
                description=(
                    "Start conversion. Multipart fields: file (image), quality (standard|high), "
                    "engine (auto|starvector|vtracer), fontless (true|false). Returns { job_id }."
                ),
            ),
            AgentApiEndpoint(
                method="GET",
                path="/api/jobs/{job_id}",
                price_usd="0",
                payment_required=False,
                description="Job status; includes result.svg when completed.",
            ),
            AgentApiEndpoint(
                method="GET",
                path="/api/jobs/{job_id}/svg",
                price_usd="0",
                payment_required=False,
                description="Download completed SVG (image/svg+xml).",
            ),
        ],
        workflow=workflow,
    )


@router.get("/.well-known/mpp-discovery", response_model=DiscoveryDocument)
async def mpp_discovery(request: Request):
    return build_discovery(request)


@router.get("/.well-known/agent-api", response_model=AgentApiDocument)
async def agent_api(request: Request):
    return build_agent_api(request)
