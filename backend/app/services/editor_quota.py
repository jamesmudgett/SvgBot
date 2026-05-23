"""In-memory quota counter for the post-conversion SVG editor.

This is a deliberately minimal hook so we can wire a paywall later without
restructuring the route. Behavior:

- ``editor_free_limit == 0`` (default): everything is allowed; remaining
  is reported as ``None`` so the response header can simply say ``unlimited``.
- ``editor_free_limit > 0``: each unique client (identified by IP for
  anonymous traffic, swappable for a session id later) gets that many
  edits. The counter resets when the process restarts; a real
  implementation will swap the dict for Redis or a DB table.
"""

from __future__ import annotations

from dataclasses import dataclass
from threading import Lock

from app.config import get_settings


@dataclass(frozen=True)
class QuotaDecision:
    allowed: bool
    remaining: int | None
    limit: int | None


_lock = Lock()
_used: dict[str, int] = {}


def reset_for_tests() -> None:
    """Drop all per-client counters; meant for unit tests only."""
    with _lock:
        _used.clear()


def _client_id_from_request(request) -> str:
    """Best-effort identifier for an anonymous client.

    Prefers ``X-Forwarded-For`` (for deployments behind a proxy), falls
    back to the connecting peer. We do NOT hash this; it lives only in
    process memory until restart.
    """
    fwd = (request.headers.get("x-forwarded-for") or "").split(",")
    head = fwd[0].strip() if fwd else ""
    if head:
        return head
    client = request.client
    if client and client.host:
        return client.host
    return "unknown"


def check_and_decrement(request) -> QuotaDecision:
    """Charge one editor edit against the calling client's quota.

    Returns a decision that the route layer turns into either a 402 or a
    200 with the appropriate ``X-Editor-Quota-Remaining`` header.
    """
    settings = get_settings()
    limit = int(settings.editor_free_limit or 0)
    if limit <= 0:
        return QuotaDecision(allowed=True, remaining=None, limit=None)

    client_id = _client_id_from_request(request)
    with _lock:
        used = _used.get(client_id, 0)
        if used >= limit:
            return QuotaDecision(allowed=False, remaining=0, limit=limit)
        _used[client_id] = used + 1
        remaining = limit - (used + 1)
    return QuotaDecision(allowed=True, remaining=remaining, limit=limit)


def quota_header_value(decision: QuotaDecision) -> str:
    if decision.remaining is None:
        return "unlimited"
    return str(max(decision.remaining, 0))


__all__ = [
    "QuotaDecision",
    "check_and_decrement",
    "quota_header_value",
    "reset_for_tests",
]
