"""Perceptual fidelity scoring for vectorization candidates."""

from __future__ import annotations

import numpy as np
from PIL import Image

from app.services.svg_raster import rasterize_svg

_dino_model = None
_lpips_model = None


def _get_dino():
    global _dino_model
    if _dino_model is None:
        import torch
        import torchvision.transforms as T
        from torchvision.models import resnet50, ResNet50_Weights

        weights = ResNet50_Weights.DEFAULT
        model = resnet50(weights=weights)
        model.fc = torch.nn.Identity()
        model.eval()
        _dino_model = (model, weights.transforms())
    return _dino_model


def _get_lpips():
    global _lpips_model
    if _lpips_model is None:
        import lpips
        import torch

        _lpips_model = lpips.LPIPS(net="alex")
        _lpips_model.eval()
    return _lpips_model


def _embed(img: Image.Image) -> np.ndarray:
    import torch

    model, transform = _get_dino()
    t = transform(img).unsqueeze(0)
    with torch.no_grad():
        feat = model(t)
    return feat.numpy().flatten()


def dino_score(original: Image.Image, rendered: Image.Image) -> float:
    """Higher is better: 1 - normalized L2 distance between embeddings."""
    if original.size != rendered.size:
        rendered = rendered.resize(original.size, Image.Resampling.LANCZOS)
    a = _embed(original.convert("RGB"))
    b = _embed(rendered.convert("RGB"))
    dist = float(np.linalg.norm(a - b))
    # Normalize to roughly 0-1 (higher = better match)
    return max(0.0, 1.0 - dist / 50.0)


def lpips_score(original: Image.Image, rendered: Image.Image) -> float:
    """Lower LPIPS is better; returns 1 - lpips for consistency with dino_score direction."""
    import torch
    from torchvision.transforms import functional as F

    model = _get_lpips()
    if original.size != rendered.size:
        rendered = rendered.resize(original.size, Image.Resampling.LANCZOS)
    t1 = F.to_tensor(original.convert("RGB")).unsqueeze(0) * 2 - 1
    t2 = F.to_tensor(rendered.convert("RGB")).unsqueeze(0) * 2 - 1
    with torch.no_grad():
        val = model(t1, t2).item()
    return max(0.0, 1.0 - val)


def score_svg(original: Image.Image, svg: str, width: int, height: int) -> tuple[float, float]:
    try:
        rendered = rasterize_svg(svg, width, height)
    except Exception:
        return 0.0, 0.0
    return dino_score(original, rendered), lpips_score(original, rendered)
