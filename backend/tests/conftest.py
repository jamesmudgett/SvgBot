import io

import pytest
from PIL import Image


@pytest.fixture
def logo_png() -> bytes:
    img = Image.new("RGBA", (64, 64), (255, 0, 0, 255))
    for x in range(20, 44):
        for y in range(20, 44):
            img.putpixel((x, y), (0, 0, 255, 255))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture
def gradient_png() -> bytes:
    img = Image.new("RGB", (80, 80))
    pixels = img.load()
    for x in range(80):
        for y in range(80):
            pixels[x, y] = (x * 3, y * 3, 128)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
