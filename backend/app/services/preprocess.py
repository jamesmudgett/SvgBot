from io import BytesIO

import cv2
import numpy as np
from PIL import Image

from app.config import Settings

_PROBE_THUMB = 512


class ImageTooLargeError(ValueError):
    """Raised when an upload exceeds kind-aware or absolute dimension limits."""


def read_image_dimensions(data: bytes) -> tuple[int, int]:
    with Image.open(BytesIO(data)) as img:
        return img.size


def dimension_cap_for_kind(kind: str, settings: Settings) -> int:
    if kind == "logo":
        return settings.max_image_dimension_logo
    if kind == "illustration":
        return settings.max_image_dimension_illustration
    return settings.max_image_dimension_photo


def probe_image_kind(data: bytes) -> str:
    """Classify on a small thumbnail so huge uploads are not fully decoded."""
    with Image.open(BytesIO(data)) as img:
        img.draft(img.mode, (_PROBE_THUMB, _PROBE_THUMB))
        thumb = img.copy()
        thumb.thumbnail((_PROBE_THUMB, _PROBE_THUMB), Image.Resampling.LANCZOS)
        arr = np.array(thumb.convert("RGBA"))
    stats = image_stats(arr)
    raw_kind = classify_image(stats)
    if is_monochrome_logo(arr):
        return "logo"
    return raw_kind


def validate_image_limits(data: bytes, settings: Settings) -> str:
    """Return probed image kind; raise ``ImageTooLargeError`` when over hard limits."""
    width, height = read_image_dimensions(data)
    long_edge = max(width, height)
    if long_edge > settings.max_image_dimension_absolute:
        raise ImageTooLargeError(
            f"Image too large ({width}×{height} px). "
            f"Maximum allowed dimension is {settings.max_image_dimension_absolute} px "
            "on the longest side."
        )

    kind = probe_image_kind(data)
    cap = dimension_cap_for_kind(kind, settings)
    if kind == "photo" and long_edge > cap:
        raise ImageTooLargeError(
            f"This image looks like a photo at {width}×{height} px. "
            f"Photos are limited to {cap} px on the longest side. "
            "Try resizing or cropping before uploading."
        )
    return kind


def load_image_bytes(data: bytes, max_dimension: int) -> tuple[Image.Image, np.ndarray]:
    with Image.open(BytesIO(data)) as img:
        img = img.convert("RGBA")
    img = _resize_if_needed(img, max_dimension)
    arr = np.array(img)
    return img, arr


def _resize_if_needed(img: Image.Image, max_dimension: int) -> Image.Image:
    w, h = img.size
    longest = max(w, h)
    if longest <= max_dimension:
        return img
    scale = max_dimension / longest
    new_size = (int(w * scale), int(h * scale))
    return img.resize(new_size, Image.Resampling.LANCZOS)


def image_stats(arr: np.ndarray) -> dict:
    rgb = arr[..., :3]
    flat = rgb.reshape(-1, 3)
    # Subsample for speed on large images
    if len(flat) > 50_000:
        idx = np.random.default_rng(0).choice(len(flat), 50_000, replace=False)
        flat = flat[idx]
    unique = np.unique(flat, axis=0)
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    edges = cv2.Canny(gray, 50, 150)
    edge_density = float(edges.mean() / 255.0)
    return {
        "width": arr.shape[1],
        "height": arr.shape[0],
        "unique_colors": len(unique),
        "edge_density": edge_density,
    }


def classify_image(stats: dict) -> str:
    colors = stats["unique_colors"]
    edges = stats["edge_density"]
    if colors <= 32 and edges < 0.08:
        return "logo"
    if colors <= 256 and edges < 0.15:
        return "illustration"
    return "photo"


def is_monochrome_logo(
    arr: np.ndarray, *, dominance_threshold: float = 0.92
) -> bool:
    """Return True iff an image is effectively two distinct colors.

    We bucket each RGB channel into 8 coarse bins (8^3 = 512 buckets) so JPEG
    noise and anti-aliasing collapse into a single bucket per dominant tone,
    then check whether the top 2 most-populated buckets cover at least
    ``dominance_threshold`` of the image.

    Why bucketing instead of k-means: k-means on a high-contrast 2-color image
    with even a tiny variance imbalance tends to split the larger cluster, which
    silently breaks the "top 2 clusters cover X%" heuristic.

    Designed to trigger on brand-mark logos like cleo (cream pill + brown text
    on brown background), where exactly 2 buckets dominate, while rejecting
    3-color logos (where 3 buckets each carry a meaningful share) and photos
    (where hundreds of buckets fragment the population).
    """
    if arr.ndim == 3 and arr.shape[2] == 4:
        arr = arr[..., :3]
    if arr.ndim != 3 or arr.shape[2] != 3:
        return False

    bucketed = (arr.astype(np.uint16) // 64).astype(np.uint8)
    flat_keys = (
        bucketed[..., 0].astype(np.uint32) * 16
        + bucketed[..., 1].astype(np.uint32) * 4
        + bucketed[..., 2].astype(np.uint32)
    ).ravel()
    counts = np.bincount(flat_keys, minlength=4 * 4 * 4)
    total = int(counts.sum())
    if total == 0:
        return False
    top2 = int(np.sort(counts)[-2:].sum())
    coverage = top2 / total
    return bool(coverage >= dominance_threshold)


def clean_for_tracing(
    img: Image.Image,
    *,
    kind: str = "logo",
    palette_size: int = 6,
    bilateral: bool = True,
    bilateral_d: int = 7,
    bilateral_sigma_color: int = 35,
    bilateral_sigma_space: int = 35,
) -> Image.Image:
    """Pre-clean an image so VTracer traces underlying shapes instead of JPEG/AA noise.

    For logos with anti-aliased text on flat fills, JPEG compression and edge
    anti-aliasing produce thousands of slightly-different colors along every
    boundary. VTracer faithfully traces those bumps, which is the exact reason
    rendered text looks "choppy" — too many control points along curves.

    Strategy by `kind`:
    - **logo**: edge-preserving bilateral filter (kills JPEG mosquito noise but
      keeps shape boundaries crisp), then k-means quantize to ``palette_size``
      colors so VTracer sees clean, perfectly-flat fills with sharp edges.
    - **illustration**: just bilateral filter, no palette snap (preserves
      gradient/shading fidelity).
    - **photo**: no-op (over-cleaning kills photographic detail).

    Returns a new ``RGB`` PIL image; the caller's image is untouched.
    """
    if kind == "photo":
        return img.convert("RGB")

    arr = np.array(img.convert("RGB"))
    if bilateral:
        arr = cv2.bilateralFilter(
            arr,
            d=bilateral_d,
            sigmaColor=float(bilateral_sigma_color),
            sigmaSpace=float(bilateral_sigma_space),
        )

    if kind == "logo" and palette_size > 0:
        arr = _kmeans_quantize(arr, palette_size)

    return Image.fromarray(arr, mode="RGB")


def clean_rgba_for_tracing(
    rgba: Image.Image,
    *,
    palette_size: int = 6,
    bilateral: bool = True,
    bilateral_d: int = 7,
    bilateral_sigma_color: int = 35,
    bilateral_sigma_space: int = 35,
) -> Image.Image:
    """Denoise and quantize an RGBA residual patch before VTracer sees it.

    Refinement extracts original pixels along defect regions. Those pixels still
    carry JPEG/AA noise, so tracing them raw produces choppy overlay paths that
    stack on the base SVG and worsen the score. Bilateral + palette snap keeps
    edges crisp while flattening interior color variation.
    """
    arr = np.array(rgba.convert("RGBA"))
    if not (arr[..., 3] > 0).any():
        return rgba

    rgb = arr[..., :3]
    if bilateral:
        rgb = cv2.bilateralFilter(
            rgb,
            d=bilateral_d,
            sigmaColor=float(bilateral_sigma_color),
            sigmaSpace=float(bilateral_sigma_space),
        )
    if palette_size > 0:
        rgb = _kmeans_quantize(rgb, palette_size)

    out = arr.copy()
    out[..., :3] = rgb
    return Image.fromarray(out, mode="RGBA")


def _kmeans_quantize(arr: np.ndarray, k: int) -> np.ndarray:
    """Snap every pixel to one of ``k`` k-means cluster centroids.

    Uses ``cv2.kmeans`` with k-means++ init for stable, well-separated palettes.
    If the image already has fewer than ``k`` distinct colors, the result is
    effectively a no-op (k-means converges to the same colors).
    """
    h, w = arr.shape[:2]
    flat = arr.reshape(-1, 3).astype(np.float32)
    criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 20, 1.0)
    _, labels, centers = cv2.kmeans(
        flat, k, None, criteria, 3, cv2.KMEANS_PP_CENTERS
    )
    centers = centers.astype(np.uint8)
    quantized = centers[labels.flatten()].reshape(h, w, 3)
    return quantized
