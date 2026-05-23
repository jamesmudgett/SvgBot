from typing import Any, Literal

from pydantic import BaseModel, Field

# Stable identifiers the frontend uses to render a step-by-step progress UI.
# Keep this list in sync with ``frontend/src/api/client.ts``.
JobPhase = Literal[
    "queued",
    "fetching",
    "preprocessing",
    "starvector",
    "vtracer",
    "vtracer_smooth",
    "vtracer_mono",
    "refining",
    "sanitizing",
    "done",
    "failed",
]


class JobCreateResponse(BaseModel):
    job_id: str


class CandidateScore(BaseModel):
    """Per-engine score breakdown so the frontend can show the user *why* the
    winning engine was chosen, not just the winner's final score."""

    engine: str
    dino: float
    lpips: float
    mean: float
    selected: bool
    tried: int = 1


class JobMetrics(BaseModel):
    dino_score: float | None = None
    lpips: float | None = None
    engine: str
    candidates_tried: int = 1
    path_count: int = 0
    ms: int
    base_dino_score: float | None = None
    refine_passes: int = 0
    refine_coverage: float = 0.0
    candidate_scores: list[CandidateScore] = Field(default_factory=list)
    decision: str = ""


class JobResult(BaseModel):
    svg: str
    width: int
    height: int
    metrics: JobMetrics


class JobStatusResponse(BaseModel):
    job_id: str
    status: Literal["queued", "running", "completed", "failed"]
    phase: JobPhase = "queued"
    progress: str = ""
    result: JobResult | None = None
    error: str | None = None


class DiscoveryEndpoint(BaseModel):
    path: str
    method: str
    price_usd: str
    description: str


class DiscoveryDocument(BaseModel):
    name: str
    version: str
    description: str
    price_per_conversion_usd: str
    documentation_url: str
    endpoints: list[DiscoveryEndpoint]
    payment_protocols: list[str] = Field(default_factory=lambda: ["mpp", "x402"])


class AgentApiEndpoint(BaseModel):
    method: str
    path: str
    price_usd: str
    payment_required: bool
    description: str


class AgentApiPaymentInfo(BaseModel):
    enabled: bool
    price_usd: str
    protocols: list[str]
    mpp_discovery_url: str
    agent_instructions_url: str
    mpp: dict[str, Any] | None = None
    x402: dict[str, Any] | None = None


class AgentApiDocument(BaseModel):
    service: str
    version: str
    description: str
    base_url: str
    payment: AgentApiPaymentInfo
    endpoints: list[AgentApiEndpoint]
    workflow: list[str]
