from functools import lru_cache
import os
from pathlib import Path
from typing import Literal, Self

from pydantic import model_validator
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)

# Always load backend/.env regardless of process cwd (e.g. repo root via run.sh)
_BACKEND_ROOT = Path(__file__).resolve().parent.parent
_ENV_FILE = _BACKEND_ROOT / ".env"


def env_file_path() -> Path:
    return _ENV_FILE


def _read_env_file_flag(key: str) -> bool | None:
    """Read a boolean flag from backend/.env (authoritative for local dev)."""
    if not _ENV_FILE.is_file():
        return None
    for line in _ENV_FILE.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if not stripped.upper().startswith(f"{key.upper()}="):
            continue
        val = stripped.split("=", 1)[1].strip().strip('"').strip("'").lower()
        if val in ("true", "1", "yes", "on"):
            return True
        if val in ("false", "0", "no", "off"):
            return False
        return None
    return None


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE) if _ENV_FILE.is_file() else None,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        # Prefer backend/.env over shell env (avoids stale STARVECTOR_ENABLED=false in OS)
        return (
            init_settings,
            dotenv_settings,
            env_settings,
            file_secret_settings,
        )

    app_name: str = "SvgBot"
    debug: bool = False
    cors_origins: str = (
        "http://localhost:5173,http://127.0.0.1:5173,"
        "http://localhost:4173,http://127.0.0.1:4173"
    )

    max_upload_bytes: int = 20 * 1024 * 1024
    max_image_dimension: int = 2048

    starvector_model: str = "starvector/starvector-1b-im2svg"
    starvector_enabled: bool = True
    starvector_attn_implementation: str = "eager"  # StarVector does not support sdpa yet
    starvector_max_length: int = 4000
    starvector_k_high: int = 5
    starvector_k_standard: int = 3
    hf_token: str = ""
    dino_score_threshold: float = 0.35

    job_ttl_seconds: int = 3600

    # Cross-engine ensemble + residual refinement (always runs; set max_passes=0 to skip)
    auto_use_ensemble: bool = True
    refine_max_passes: int = 20
    refine_min_delta: float = 0.0005
    refine_residual_threshold: int = 12
    refine_min_mask_ratio: float = 0.0005

    # Smooth-curve VTracer pipeline: palette-quantize the input + smooth grid so
    # logo letters don't get traced as choppy bumps along JPEG/AA noise.
    vtracer_smooth_enabled: bool = True
    vtracer_smooth_palette_size: int = 6
    vtracer_smooth_bilateral: bool = True

    # Geometric smoothing post-process pass (Phase 5). Hybrid B-then-A strategy:
    # supersample-retrace first, Schneider Bezier refit as fallback. See
    # backend/app/services/smooth_paths.py.
    path_smoothing_enabled: bool = True
    # DinoScore (ResNet-50 features) is sensitive to sub-pixel alignment; a
    # smoothed SVG with visually identical or better geometry can score lower
    # than its choppy original purely because pixels shifted. Logos use a
    # wider gate because the smoothing pass trades a small metric drop for
    # visibly cleaner letterform curves.
    path_smoothing_max_delta: float = 0.01
    path_smoothing_max_delta_logo: float = 0.08
    path_smoothing_supersample_scale: int = 8
    path_smoothing_blur_sigma: float = 2.0
    path_smoothing_chaikin_iterations: int = 3
    path_smoothing_corner_angle_deg: float = 75.0
    path_smoothing_corner_retention_threshold: float = 0.8
    # rdp_tolerance is in user-units (typically pixels). VTracer's stair-stepped
    # output has 1-2 px amplitude noise along letter contours; a tolerance of
    # ~1.5 collapses those steps while preserving real geometry.
    path_smoothing_rdp_tolerance_logo: float = 1.5
    path_smoothing_rdp_tolerance_illustration: float = 0.6

    # Payments ($0.50 per conversion when enabled)
    payments_enabled: bool = False
    price_per_conversion_usd: str = "0.50"
    mpp_secret_key: str = ""
    mpp_tempo_recipient: str = ""
    mpp_tempo_currency: str = ""

    x402_enabled: bool = False
    x402_evm_address: str = ""
    x402_facilitator_url: str = "https://x402.org/facilitator"
    x402_network: str = "eip155:84532"

    data_dir: str = "./data/jobs"

    @model_validator(mode="after")
    def starvector_enabled_from_backend_dotenv(self) -> Self:
        """backend/.env wins over stale shell STARVECTOR_ENABLED=false."""
        from_file = _read_env_file_flag("STARVECTOR_ENABLED")
        if from_file is not None:
            self.starvector_enabled = from_file
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()


def starvector_config_debug() -> dict:
    """Diagnostics for /health when StarVector appears disabled."""
    s = get_settings()
    return {
        "starvector_enabled": s.starvector_enabled,
        "env_file": str(_ENV_FILE),
        "env_file_exists": _ENV_FILE.is_file(),
        "env_file_value": _read_env_file_flag("STARVECTOR_ENABLED"),
        "process_env": os.environ.get("STARVECTOR_ENABLED"),
    }


QualityTier = Literal["standard", "high"]
EngineChoice = Literal[
    "auto", "starvector", "vtracer", "vtracer_smooth", "vtracer_mono"
]
