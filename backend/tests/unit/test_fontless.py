from app.services.fontless import enforce_fontless, is_fontless


def test_strip_text():
    svg = '<svg xmlns="http://www.w3.org/2000/svg"><text>hi</text><path d="M0 0"/></svg>'
    out = enforce_fontless(svg)
    assert is_fontless(out)
    assert "path" in out.lower()
    assert "hi" not in out
    assert "ns0:" not in out


def test_no_ns0_prefixes():
    svg = '<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"><path d="M0 0"/></svg>'
    out = enforce_fontless(svg)
    assert "<svg" in out
    assert "ns0:" not in out
    assert 'xmlns:ns0' not in out


def test_plain_path_ok():
    svg = '<svg xmlns="http://www.w3.org/2000/svg"><path fill="#f00" d="M0 0 L10 0 L10 10 Z"/></svg>'
    assert is_fontless(enforce_fontless(svg))
