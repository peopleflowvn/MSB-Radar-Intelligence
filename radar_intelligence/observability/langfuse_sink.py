from __future__ import annotations

from contextlib import contextmanager
import os


def _configured() -> bool:
    return all(os.environ.get(name, "").strip() for name in (
        "LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "LANGFUSE_BASE_URL"))


@contextmanager
def safe_span(name: str, metadata: dict | None = None):
    """Create an opt-in Langfuse span containing allow-listed metadata only.

    Queries, evidence, scope tokens and model reasoning must never be passed to
    this function. Observability failure is non-critical and cannot break an
    answer request.
    """
    if not _configured():
        yield None
        return
    try:
        from langfuse import get_client
        observation = get_client().start_as_current_observation(
            as_type="span", name=name, metadata=dict(metadata or {}))
        span = observation.__enter__()
    except Exception:  # noqa: BLE001 - telemetry startup must fail open
        yield None
        return
    try:
        yield span
    except BaseException as exc:
        observation.__exit__(type(exc), exc, exc.__traceback__)
        raise
    else:
        try:
            observation.__exit__(None, None, None)
        except Exception:  # noqa: BLE001 - telemetry shutdown must fail open
            return
