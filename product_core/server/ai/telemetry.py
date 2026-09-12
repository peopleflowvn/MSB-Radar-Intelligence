"""Request-local AI usage. No prompts, CV text, credentials or private reasoning."""
from contextlib import contextmanager
from contextvars import ContextVar, copy_context
from functools import wraps
from threading import Lock

_active = ContextVar("radar_ai_usage", default=None)


@contextmanager
def capture():
    existing = _active.get()
    if existing is not None:
        yield existing
        return
    value = {"calls": [], "lock": Lock()}
    token = _active.set(value)
    try:
        yield value
    finally:
        _active.reset(token)


def record(entry):
    active = _active.get()
    if active is None:
        return
    row = {key: entry.get(key) for key in (
        "task", "provider", "model", "capability", "latency_ms", "ok", "route_reason")}
    row.update(input_tokens=entry.get("prompt_tokens") if entry.get("ok") else None,
               output_tokens=entry.get("completion_tokens") if entry.get("ok") else None,
               error=bool(entry.get("error")))
    with active["lock"]:
        active["calls"].append(row)


def reported_usage(result):
    """Provider defaults of zero must not certify missing usage as free."""
    raw = getattr(result, "raw", {}) or {}
    usage = raw.get("usage") or {}
    values = []
    for key, attr in (("prompt_tokens", "prompt_tokens"), ("completion_tokens", "completion_tokens")):
        value = usage.get(key)
        if type(value) is int and value >= 0:
            values.append(value)
        else:
            value = getattr(result, attr, None)
            values.append(value if type(value) is int and value > 0 else None)
    return dict(prompt_tokens=values[0], completion_tokens=values[1])


def attach(result, active):
    if result is not None and hasattr(result, "trace"):
        with active["lock"]:
            rows = list(active["calls"])
        result.trace["llm_calls"] = rows
        result.trace["usage"] = {
            "input_tokens": sum(r["input_tokens"] for r in rows if r["input_tokens"] is not None),
            "output_tokens": sum(r["output_tokens"] for r in rows if r["output_tokens"] is not None),
            "failed_attempts": sum(not r["ok"] for r in rows),
            "tokens_complete": all(r["ok"] and r["input_tokens"] is not None
                                   and r["output_tokens"] is not None for r in rows),
            "usage_scope": "reported tokens only; unreported attempt usage remains unknown",
        }


def traced_answer(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        with capture() as active:
            result = fn(*args, **kwargs)
            attach(result, active)
            return result
    return wrapped


def traced_stream(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        with capture() as active:
            for event in fn(*args, **kwargs):
                if event.get("type") == "done":
                    attach(event.get("result"), active)
                yield event
    return wrapped


def submit(pool, fn, *args):
    """A fresh Context for each thread; callers share the guarded collector."""
    return pool.submit(copy_context().run, fn, *args)
