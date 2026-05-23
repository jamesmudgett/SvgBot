"""Grok-backed SVG editor.

Exposes a single function, :func:`edit_svg`, that takes the current SVG
plus a natural-language instruction and returns a revised SVG. The backend
proxies to xAI's OpenAI-compatible chat completions endpoint so the API
key never leaves the server.

The function is intentionally synchronous so it can be wrapped in
``run_in_threadpool`` from the FastAPI route. It does no I/O of its own
beyond a single HTTP POST through :func:`_post_chat_completion`, which
tests monkeypatch.
"""

from __future__ import annotations

import base64
import logging
import re
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Any, Callable

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)


class LlmEditError(Exception):
    """Base error for editor LLM failures with a structured ``code``.

    ``code`` values:
    - ``"no_api_key"``: server is not configured for the editor.
    - ``"upstream_http"``: xAI returned a non-2xx response.
    - ``"upstream_network"``: network failure talking to xAI.
    - ``"invalid_svg"``: response did not contain a parseable SVG.
    """

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass
class EditResult:
    svg: str
    summary: str
    model: str
    ms: int
    tokens_in: int
    tokens_out: int


_SYSTEM_PROMPT = (
    "You are an SVG editor. Given the current SVG document and a user "
    "instruction, return ONLY a single complete, well-formed SVG document "
    "that satisfies the instruction. Preserve the existing viewBox, the "
    "xmlns attribute, and any element ids you do not change. Do not add "
    "explanations outside the SVG; if you must explain, put one short "
    "sentence BEFORE the SVG and wrap the SVG itself in a fenced code "
    "block of the form ```svg\\n<svg ...>...</svg>\\n```."
)


# Regex used to peel an SVG out of an arbitrary chat response. We try a
# fenced ```svg``` block first (the system prompt asks for this) and fall
# back to the first <svg ...>...</svg> in the message.
_FENCED_SVG = re.compile(r"```(?:svg|xml)?\s*(<svg[\s\S]*?</svg>)\s*```", re.IGNORECASE)
_BARE_SVG = re.compile(r"(<svg[\s\S]*?</svg>)", re.IGNORECASE)


def edit_svg(
    *,
    svg: str,
    instruction: str,
    selected_ids: list[str] | None = None,
    original_image: tuple[bytes, str] | None = None,
    region: tuple[float, float, float, float] | None = None,
    model: str | None = None,
) -> EditResult:
    """Send an edit request to Grok and return the revised SVG.

    ``original_image`` is ``(bytes, mime)`` and only attached when the user
    asked the chat panel to "Reference original" so we don't pay for an
    unnecessary image part on every turn. ``region`` is ``(x, y, width,
    height)`` in user-space coordinates (the SVG's viewBox units), and is
    forwarded as natural language so Grok scopes its revisions.
    """
    settings = get_settings()
    if not settings.xai_api_key:
        raise LlmEditError(
            "no_api_key",
            "Grok (xAI) is not configured: set XAI_API_KEY in backend/.env to "
            "enable the editor's LLM revisions.",
        )

    chosen_model = (model or settings.grok_model).strip() or "grok-4-latest"
    user_text = _format_user_message(svg, instruction, selected_ids or [], region)

    user_content: list[dict[str, Any]] = [{"type": "text", "text": user_text}]
    if original_image is not None:
        data, mime = original_image
        if mime == "application/octet-stream":
            mime = "image/png"
        b64 = base64.b64encode(data).decode("ascii")
        user_content.append(
            {
                "type": "image_url",
                "image_url": {"url": f"data:{mime};base64,{b64}"},
            }
        )

    payload = {
        "model": chosen_model,
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        "temperature": 0.2,
    }

    headers = {
        "Authorization": f"Bearer {settings.xai_api_key}",
        "Content-Type": "application/json",
    }

    started = time.monotonic()
    try:
        response = _post_chat_completion(
            url=settings.xai_api_url,
            headers=headers,
            json_body=payload,
            timeout=settings.editor_request_timeout_s,
        )
    except httpx.RequestError as exc:
        raise LlmEditError(
            "upstream_network",
            f"Could not reach Grok: {exc}",
        ) from exc

    if response.status_code >= 400:
        raise LlmEditError(
            "upstream_http",
            f"Grok returned HTTP {response.status_code}: {response.text[:300]}",
        )

    try:
        body = response.json()
    except ValueError as exc:
        raise LlmEditError(
            "invalid_svg",
            "Grok did not return JSON.",
        ) from exc

    content = _extract_assistant_content(body)
    new_svg = _extract_svg(content)
    if new_svg is None:
        raise LlmEditError(
            "invalid_svg",
            "Grok did not return a valid SVG document. Try a more specific "
            "instruction or rerun the request.",
        )

    summary = _extract_summary(content)
    usage = body.get("usage") or {}
    ms = int((time.monotonic() - started) * 1000)

    return EditResult(
        svg=new_svg,
        summary=summary,
        model=str(body.get("model") or chosen_model),
        ms=ms,
        tokens_in=int(usage.get("prompt_tokens") or 0),
        tokens_out=int(usage.get("completion_tokens") or 0),
    )


# ---------------------------------------------------------------------------
# Helpers


def _post_chat_completion(
    *,
    url: str,
    headers: dict,
    json_body: dict,
    timeout: float,
) -> httpx.Response:
    """Perform the actual HTTP call. Tests monkeypatch this function."""
    return httpx.post(url, headers=headers, json=json_body, timeout=timeout)


def _format_user_message(
    svg: str,
    instruction: str,
    selected_ids: list[str],
    region: tuple[float, float, float, float] | None,
) -> str:
    selection_line = (
        f"Selected element ids: {', '.join(selected_ids)}"
        if selected_ids
        else "Selected element ids: (none, treat the whole SVG as in scope)"
    )
    if region is not None:
        x, y, w, h = region
        region_line = (
            "Region of interest (user-space coordinates matching the SVG's "
            f"viewBox): x={x:g}, y={y:g}, width={w:g}, height={h:g}. "
            "Constrain your changes to elements (or vertices) inside this "
            "rectangle and leave everything outside it untouched."
        )
    else:
        region_line = "Region of interest: (none)"
    return (
        f"Instruction: {instruction.strip()}\n\n"
        f"{selection_line}\n"
        f"{region_line}\n\n"
        f"Current SVG:\n```svg\n{svg}\n```"
    )


def _extract_assistant_content(body: dict) -> str:
    """Pull the text content out of a chat-completions response.

    xAI follows the OpenAI shape: ``choices[0].message.content``. The
    content can be either a plain string or an array of parts; we
    normalize both.
    """
    choices = body.get("choices") or []
    if not choices:
        return ""
    msg = choices[0].get("message") or {}
    content = msg.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        out: list[str] = []
        for part in content:
            if isinstance(part, dict) and part.get("type") == "text":
                out.append(str(part.get("text") or ""))
            elif isinstance(part, str):
                out.append(part)
        return "\n".join(out)
    return ""


def _extract_svg(content: str) -> str | None:
    if not content:
        return None
    match = _FENCED_SVG.search(content)
    candidate = match.group(1) if match else None
    if candidate is None:
        match = _BARE_SVG.search(content)
        candidate = match.group(1) if match else None
    if not candidate:
        return None

    candidate = candidate.strip()
    if not _is_parseable_svg(candidate):
        return None
    return candidate


def _is_parseable_svg(svg: str) -> bool:
    try:
        root = ET.fromstring(svg)
    except ET.ParseError:
        return False
    tag = root.tag.lower()
    return tag.endswith("svg")


def _extract_summary(content: str) -> str:
    """Return a one-line plain-text summary of the change.

    Strategy: take everything before the first fenced/bare SVG block, trim
    to a single sentence, fall back to a short canned message if empty.
    """
    if not content:
        return "Updated SVG."
    head = content
    for pattern in (_FENCED_SVG, _BARE_SVG):
        m = pattern.search(content)
        if m:
            head = content[: m.start()]
            break
    head = head.strip()
    if not head:
        return "Updated SVG."
    first_line = head.splitlines()[0].strip()
    if len(first_line) > 240:
        first_line = first_line[:237] + "..."
    return first_line or "Updated SVG."


__all__ = ["edit_svg", "EditResult", "LlmEditError"]
