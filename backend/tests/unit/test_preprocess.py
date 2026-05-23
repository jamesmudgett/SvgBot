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


def test_is_monochrome_logo_detects_two_color_image():
    """A bg + foreground (with a tiny bit of anti-aliasing) must be classified
    as monochrome so the orchestrator runs the dedicated 2-color tracing pass."""
    img = Image.new("RGB", (200, 200), (245, 240, 230))
    arr = np.array(img)
    arr[40:160, 40:160] = (50, 30, 25)
    rng = np.random.default_rng(0)
    noise = rng.integers(-5, 6, size=arr.shape, dtype=np.int16)
    arr = np.clip(arr.astype(np.int16) + noise, 0, 255).astype(np.uint8)
    assert preprocess.is_monochrome_logo(arr) is True


def test_is_monochrome_logo_rejects_full_color_photo():
    """A natural gradient (many distinct dominant colors) must not be flagged."""
    arr = np.zeros((128, 128, 3), dtype=np.uint8)
    for y in range(128):
        for x in range(128):
            arr[y, x] = (x * 2 % 256, y * 2 % 256, (x + y) * 2 % 256)
    assert preprocess.is_monochrome_logo(arr) is False


def test_is_monochrome_logo_accepts_cleo_fixture():
    """The actual cleo benchmark image must classify as monochrome — that's the
    whole reason we added this code path."""
    from pathlib import Path

    fixture = (
        Path(__file__).resolve().parent.parent / "fixtures" / "cleo.png"
    )
    with Image.open(fixture) as img:
        arr = np.array(img.convert("RGB"))
    assert preprocess.is_monochrome_logo(arr) is True, (
        "cleo logo must be detected as monochrome (brown + cream), otherwise "
        "the 2-color tracing pass never runs and we keep getting color-drifted "
        "letterforms"
    )


def test_is_monochrome_logo_rejects_three_color_logo():
    """A logo with three distinct colors (e.g. brand mark with accent) is NOT
    a candidate for the binary 2-color trace pass."""
    arr = np.zeros((180, 180, 3), dtype=np.uint8)
    arr[:, :] = (245, 240, 230)
    arr[20:90, 20:90] = (50, 30, 25)
    arr[100:160, 100:160] = (200, 60, 50)
    assert preprocess.is_monochrome_logo(arr) is False


def test_clean_for_tracing_palette_2_produces_exactly_two_colors():
    """The palette=2 cleaning path must collapse to exactly 2 colors so the
    vtracer monochrome pass produces a single foreground / single background
    SVG with no inter-letter color drift."""
    img = Image.new("RGB", (120, 120), (245, 240, 230))
    arr = np.array(img)
    arr[20:100, 20:100] = (50, 30, 25)
    rng = np.random.default_rng(1)
    noise = rng.integers(-10, 11, size=arr.shape, dtype=np.int16)
    arr = np.clip(arr.astype(np.int16) + noise, 0, 255).astype(np.uint8)
    img = Image.fromarray(arr, mode="RGB")

    cleaned = preprocess.clean_for_tracing(img, kind="logo", palette_size=2, bilateral=False)
    cleaned_arr = np.array(cleaned)
    unique = len(np.unique(cleaned_arr.reshape(-1, 3), axis=0))
    assert unique == 2, f"expected exactly 2 colors, got {unique}"


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
