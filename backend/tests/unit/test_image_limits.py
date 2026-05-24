from __future__ import annotations

from io import BytesIO

import numpy as np
import pytest
from PIL import Image

from app.config import Settings
from app.services import preprocess


def _encode_png(img: Image.Image) -> bytes:
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _large_photo(width: int, height: int) -> bytes:
    arr = np.zeros((height, width, 3), dtype=np.uint8)
    for y in range(height):
        for x in range(width):
            arr[y, x] = (x % 256, y % 256, (x + y) % 256)
    return _encode_png(Image.fromarray(arr, mode="RGB"))


def _large_logo(width: int, height: int) -> bytes:
    arr = np.full((height, width, 3), (60, 30, 20), dtype=np.uint8)
    arr[height // 4 : 3 * height // 4, width // 4 : 3 * width // 4] = (245, 235, 220)
    return _encode_png(Image.fromarray(arr, mode="RGB"))


def test_rejects_oversized_photo():
    settings = Settings(max_image_dimension_photo=1536)
    data = _large_photo(2400, 1800)
    with pytest.raises(preprocess.ImageTooLargeError) as exc:
        preprocess.validate_image_limits(data, settings)
    assert "photo" in str(exc.value).lower()
    assert "1536" in str(exc.value)


def test_allows_oversized_logo_for_downscale():
    settings = Settings(max_image_dimension_logo=4096)
    data = _large_logo(3200, 2400)
    kind = preprocess.validate_image_limits(data, settings)
    assert kind == "logo"


def test_rejects_beyond_absolute_ceiling(monkeypatch: pytest.MonkeyPatch):
    settings = Settings(max_image_dimension_absolute=8192)
    data = _large_logo(100, 100)
    monkeypatch.setattr(preprocess, "read_image_dimensions", lambda _: (9000, 9000))
    with pytest.raises(preprocess.ImageTooLargeError) as exc:
        preprocess.validate_image_limits(data, settings)
    assert "8192" in str(exc.value)


def test_dimension_cap_for_kind():
    settings = Settings(
        max_image_dimension_logo=4096,
        max_image_dimension_illustration=3072,
        max_image_dimension_photo=1536,
    )
    assert preprocess.dimension_cap_for_kind("logo", settings) == 4096
    assert preprocess.dimension_cap_for_kind("illustration", settings) == 3072
    assert preprocess.dimension_cap_for_kind("photo", settings) == 1536


def test_load_image_respects_kind_cap():
    settings = Settings(max_image_dimension_logo=1024)
    data = _large_logo(2000, 1500)
    img, _ = preprocess.load_image_bytes(
        data, preprocess.dimension_cap_for_kind("logo", settings)
    )
    assert max(img.size) <= 1024
