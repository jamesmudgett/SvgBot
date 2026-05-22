import re
import xml.etree.ElementTree as ET

FORBIDDEN_TAGS = {"text", "tspan", "font", "font-face"}
FORBIDDEN_ATTR_PATTERN = re.compile(r"font(-family|-size|-weight)?", re.I)


def _serialize_svg(root: ET.Element) -> str:
    """Serialize SVG without ns0: prefixes (invalid in many browser XML parsers)."""
    try:
        ET.register_namespace("", "http://www.w3.org/2000/svg")
    except Exception:
        pass

    out = ET.tostring(root, encoding="unicode")
    out = re.sub(r"<ns\d+:", "<", out)
    out = re.sub(r"</ns\d+:", "</", out)
    out = re.sub(
        r'\sxmlns:ns\d+="http://www.w3.org/2000/svg"',
        ' xmlns="http://www.w3.org/2000/svg"',
        out,
        count=1,
    )
    if not re.search(r"<svg[^>]*\sxmlns=", out):
        out = re.sub(r"<svg\b", '<svg xmlns="http://www.w3.org/2000/svg"', out, count=1)
    return out


def strip_text_nodes(svg: str) -> str:
    """Remove text elements; diagrams lose labels but stay fontless."""
    try:
        root = ET.fromstring(svg)
    except ET.ParseError:
        return svg

    to_remove: list[ET.Element] = []
    for elem in root.iter():
        local = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
        if local in FORBIDDEN_TAGS:
            to_remove.append(elem)
            continue
        for attr in list(elem.attrib):
            if FORBIDDEN_ATTR_PATTERN.search(attr):
                del elem.attrib[attr]

    for elem in to_remove:
        parent = _find_parent(root, elem)
        if parent is not None:
            parent.remove(elem)

    return _serialize_svg(root)


def _find_parent(root: ET.Element, child: ET.Element) -> ET.Element | None:
    for elem in root.iter():
        if child in list(elem):
            return elem
    return None


def is_fontless(svg: str) -> bool:
    lower = svg.lower()
    if any(f"<{tag}" in lower for tag in FORBIDDEN_TAGS):
        return False
    if "@font-face" in lower or "font-family" in lower:
        return False
    return True


def enforce_fontless(svg: str) -> str:
    cleaned = strip_text_nodes(svg)
    if not is_fontless(cleaned):
        raise ValueError("SVG still contains font or text elements after sanitization")
    return cleaned
