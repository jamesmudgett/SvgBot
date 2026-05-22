from __future__ import annotations

import numpy as np
from PIL import Image

from app.services import preprocess


def _noisy_logo() -> Image.Image:
    """Synthetic 'JPEG-noisy' logo: 3 base colors + per-pixel noise to mimic
    AA/JPEG artifacts that produce thousands of unique colors."""
    rng = np.random.default_rng(42)
    arr = np.zeros((80, 80, 3), dtype=np.uint8)
    arr[:, :] = (60, 30, 20)
    arr[20:60, 10:70] = (245, 235, 220)
    arr[30:50, 25:55] = (40, 20, 15)
    noise = rng.integers(-12, 13, size=arr.shape, dtype=np.int16)
    arr = np.clip(arr.astype(np.int16) + noise, 0, 255).astype(np.uint8)
    return Image.fromarray(arr, mode="RGB")


def test_clean_for_tracing_collapses_palette_for_logos():
    img = _noisy_logo()
    raw_unique = len(np.unique(np.array(img).reshape(-1, 3), axis=0))
    assert raw_unique > 100, "fixture should look like a JPEG-noisy logo"

    cleaned = preprocess.clean_for_tracing(img, kind="logo", palette_size=4)
    cleaned_arr = np.array(cleaned)
    assert cleaned.mode == "RGB"
    assert cleaned_arr.shape == (80, 80, 3)
    cleaned_unique = len(np.unique(cleaned_arr.reshape(-1, 3), axis=0))
    assert cleaned_unique <= 4, f"expected <=4 colors after k-means, got {cleaned_unique}"


def test_clean_for_tracing_preserves_dominant_regions():
    """The cleaned image must still recognizably contain the original shapes:
    sample points well inside each region should keep roughly the same color."""
    img = _noisy_logo()
    cleaned = np.array(preprocess.clean_for_tracing(img, kind="logo", palette_size=4))

    bg_mid = cleaned[5, 5]
    pill_mid = cleaned[40, 40]

    assert int(bg_mid[0]) < 120
    assert not np.allclose(bg_mid, pill_mid, atol=20)


def test_clean_for_tracing_photo_is_passthrough():
    img = Image.new("RGB", (32, 32), (123, 200, 50))
    cleaned = preprocess.clean_for_tracing(img, kind="photo")
    assert np.array_equal(np.array(img), np.array(cleaned))


def test_clean_for_tracing_illustration_skips_palette_snap():
    img = _noisy_logo()
    cleaned = np.array(preprocess.clean_for_tracing(img, kind="illustration"))
    # Bilateral filter only — should reduce unique colors but keep many more
    # than the 4-color logo path.
    unique = len(np.unique(cleaned.reshape(-1, 3), axis=0))
    assert unique > 4


def test_clean_rgba_for_tracing_collapses_opaque_pixels():
    rgb = _noisy_logo()
    arr = np.array(rgb.convert("RGBA"))
    arr[..., 3] = 0
    arr[25:55, 15:65, 3] = 255
    rgba = Image.fromarray(arr, mode="RGBA")

    cleaned = preprocess.clean_rgba_for_tracing(rgba, palette_size=4)
    cleaned_arr = np.array(cleaned)

    opaque = cleaned_arr[..., 3] > 0
    opaque_unique = len(np.unique(cleaned_arr[opaque][..., :3], axis=0))
    assert opaque_unique <= 4
    assert not (cleaned_arr[..., 3] > 0).any() or opaque.any()
    assert np.all(cleaned_arr[~opaque, 3] == 0)
