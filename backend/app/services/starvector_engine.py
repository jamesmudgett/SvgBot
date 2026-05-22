"""StarVector neural im2svg engine (optional, GPU)."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from PIL import Image

from app.config import get_settings, starvector_config_debug
from app.services.cairo_compat import apply_starvector_patches, ensure_cairo_stubs
from app.services.dino_score import score_svg

logger = logging.getLogger(__name__)


class StarVectorUnavailable(Exception):
    pass


@dataclass
class StarVectorResult:
    svg: str
    dino_score: float
    candidates_tried: int


_model = None


def _ensure_hf_token() -> None:
    import os

    token = os.environ.get("HF_TOKEN") or os.environ.get("HUGGING_FACE_HUB_TOKEN")
    if not token:
        logger.warning(
            "HF_TOKEN not set — Hugging Face downloads may be slow or rate-limited. "
            "Set HF_TOKEN in .env for faster model pulls."
        )


def _load_model():
    global _model
    if _model is not None:
        return _model

    settings = get_settings()
    if not settings.starvector_enabled:
        dbg = starvector_config_debug()
        raise StarVectorUnavailable(
            "StarVector is disabled in config "
            f"(starvector_enabled={dbg['starvector_enabled']}, "
            f"backend/.env={dbg['env_file_value']!r}, "
            f"process env STARVECTOR_ENABLED={dbg['process_env']!r}). "
            "Set STARVECTOR_ENABLED=true in backend/.env, remove a false shell override "
            "(PowerShell: Remove-Item Env:STARVECTOR_ENABLED), and restart uvicorn."
        )

    try:
        import torch
        import transformers
        from starvector.model.builder import load_pretrained_model
    except ImportError as e:
        raise StarVectorUnavailable(
            "starvector package not installed. Run: "
            "pip install -r backend/requirements-starvector-deps.txt && "
            "pip install --no-deps -r backend/requirements-starvector-package.txt "
            "(see README)"
        ) from e

    tf_major = int(transformers.__version__.split(".", maxsplit=1)[0])
    if tf_major >= 5:
        raise StarVectorUnavailable(
            f"transformers {transformers.__version__} is incompatible with StarVector "
            "(meta-device load error). Install pinned deps:\n"
            "  pip install 'transformers==4.49.0' 'tokenizers==0.21.1'"
        )

    ensure_cairo_stubs()
    apply_starvector_patches()

    _ensure_hf_token()
    device = "cuda" if torch.cuda.is_available() else "cpu"
    dtype = torch.float16 if torch.cuda.is_available() else torch.float32
    logger.info("Loading StarVector model %s on %s ...", settings.starvector_model, device)

    load_kwargs = {
        "trust_remote_code": True,
        "attn_implementation": settings.starvector_attn_implementation,
        "torch_dtype": dtype,
        "low_cpu_mem_usage": False,
    }

    try:
        _tokenizer, model, _processor, _ctx = load_pretrained_model(
            settings.starvector_model,
            device=device,
            **load_kwargs,
        )
    except Exception as exc:
        raise StarVectorUnavailable(f"Failed to load StarVector model: {exc}") from exc

    model.eval()
    _model = model
    return _model


def availability() -> dict:
    """Why StarVector is or is not usable (for /health and debugging)."""
    settings = get_settings()
    info: dict = {
        "enabled": settings.starvector_enabled,
        "package": False,
        "cuda": False,
        "ready": False,
        "reason": "",
    }
    if not settings.starvector_enabled:
        info["reason"] = "STARVECTOR_ENABLED is false (see backend/.env; shell env may override if config fix not loaded)"
        return info
    try:
        import torch
        import transformers

        import starvector  # noqa: F401

        info["package"] = True
        info["transformers"] = transformers.__version__
        if int(transformers.__version__.split(".", maxsplit=1)[0]) >= 5:
            info["reason"] = (
                f"transformers {transformers.__version__} incompatible with StarVector; "
                "pip install 'transformers==4.49.0' 'tokenizers==0.21.1'"
            )
            return info
        info["cuda"] = torch.cuda.is_available()
        if not info["cuda"]:
            info["reason"] = "CUDA not available - StarVector needs an NVIDIA GPU"
            return info
        info["ready"] = True
        info["reason"] = "ok"
        return info
    except ImportError:
        info["reason"] = (
            "starvector package not installed (pip install -r backend/requirements-starvector-deps.txt "
            "&& pip install --no-deps -r backend/requirements-starvector-package.txt)"
        )
        return info


def is_available() -> bool:
    return availability()["ready"]


def _finalize_svg(raw_svg: str) -> str:
    """Validate / clean model output without requiring native Cairo."""
    ensure_cairo_stubs()
    apply_starvector_patches()
    from svgpathtools import svgstr2paths

    match = re.search(r"<svg[\s\S]*</svg>", raw_svg, re.IGNORECASE)
    candidate = match.group(0) if match else raw_svg

    try:
        svgstr2paths(candidate)
        return candidate
    except Exception:
        from starvector.data.util import clean_svg

        cleaned = clean_svg(candidate)
        svgstr2paths(cleaned)
        return cleaned


def _generate_one(model, img: Image.Image, max_length: int) -> str:
    rgb = img.convert("RGB")
    image_tensor = model.process_images([rgb])[0]
    if hasattr(image_tensor, "cuda") and __import__("torch").cuda.is_available():
        image_tensor = image_tensor.cuda()

    batch = {"image": image_tensor}
    raw_svg = model.generate_im2svg(batch, max_length=max_length)[0]
    return _finalize_svg(raw_svg)


def vectorize(img: Image.Image, width: int, height: int, k: int = 3) -> StarVectorResult:
    settings = get_settings()
    model = _load_model()
    max_length = settings.starvector_max_length

    best_svg = ""
    best_dino = -1.0
    tried = 0

    for _ in range(max(1, k)):
        try:
            svg = _generate_one(model, img, max_length=max_length)
            tried += 1
            dino, _ = score_svg(img, svg, width, height)
            if dino > best_dino:
                best_dino = dino
                best_svg = svg
        except Exception as e:
            logger.warning("StarVector candidate failed: %s", e)

    if not best_svg:
        raise StarVectorUnavailable("All StarVector candidates failed")

    return StarVectorResult(svg=best_svg, dino_score=best_dino, candidates_tried=tried)
