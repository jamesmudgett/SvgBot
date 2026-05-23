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


class LlmEditRegion(BaseModel):
    """User-space rectangle the user lassoed in the editor.

    Forwarded to Grok so the LLM scopes its changes to that area instead
    of touching the whole document. Coordinates are in the SVG's user
    units, i.e. the same coordinate system as the document's viewBox.
    """

    x: float
    y: float
    width: float
    height: float


class LlmEditRequest(BaseModel):
    """Body for ``POST /api/editor/llm-edit``.

    The frontend ships the current SVG (post-undo state), the natural-
    language instruction, and the ids of any elements the user marqueed
    in the editor. ``include_original`` toggles whether we attach the
    source raster from the job so Grok can see what the user is trying
    to match. ``region`` is an optional bounding box snapshot from the
    marquee tool that scopes the edit.
    """

    job_id: str
    svg: str
    instruction: str
    selected_ids: list[str] = Field(default_factory=list)
    include_original: bool = False
    region: LlmEditRegion | None = None
    model: str | None = None


class LlmEditResponse(BaseModel):
    svg: str
    summary: str
    model: str
    ms: int
    tokens_in: int = 0
    tokens_out: int = 0
    quota_remaining: int | None = None
