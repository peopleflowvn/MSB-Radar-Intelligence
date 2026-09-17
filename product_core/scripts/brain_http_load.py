"""Bounded HTTP/SSE probes. Supply credentials through environment, never output them.

Each request creates a separate conversation. This measures endpoint latency and
completion, not answer correctness. Use a dedicated test account/corpus.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import math
import os
from pathlib import Path
import time
from urllib.error import HTTPError
from urllib.parse import urlparse
from urllib.request import Request, build_opener, HTTPRedirectHandler
import uuid


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def percentile(values, quantile):
    if not values:
        return None
    values = sorted(values)
    pos = (len(values) - 1) * quantile
    low, high = math.floor(pos), math.ceil(pos)
    return round(values[low] + (values[high] - values[low]) * (pos - low), 2)


def probe(url, question, timeout, headers):
    started = time.monotonic()
    row = {"ok": False, "status": None, "error": None, "first_answer_ms": None}
    identity = str(uuid.uuid4())
    body = json.dumps({"q": question, "surface": "talent", "stream": True,
                       "conversation_id": "load-" + identity, "client_turn_id": identity}).encode()
    request = Request(url, data=body, headers={**headers, "Content-Type": "application/json"})
    try:
        with build_opener(NoRedirect).open(request, timeout=timeout) as response:
            row["status"] = response.status
            if "text/event-stream" not in response.headers.get("Content-Type", ""):
                row["error"] = "unexpected_content_type"
                return row
            event, size = "", 0
            for line in response:
                size += len(line)
                if size > 2_000_000:
                    row["error"] = "response_size_limit"
                    break
                if time.monotonic() - started > timeout:
                    row["error"] = "deadline"
                    break
                text = line.decode("utf-8", errors="replace").strip()
                if text.startswith("event:"):
                    event = text[6:].strip()
                elif text.startswith("data:"):
                    if event == "answer" and row["first_answer_ms"] is None:
                        row["first_answer_ms"] = round((time.monotonic() - started) * 1000, 2)
                    if event == "error":
                        row["error"] = "sse_error"
                        break
                    if event == "done":
                        json.loads(text[5:])
                        row["ok"] = True
                        break
            if not row["ok"] and row["error"] is None:
                row["error"] = "incomplete_stream"
    except HTTPError as exc:
        row.update(status=exc.code, error="http_error")
    except Exception as exc:
        # Exception messages may contain credentials, URLs or response content.
        row["error"] = type(exc).__name__
    finally:
        row["latency_ms"] = round((time.monotonic() - started) * 1000, 2)
    return row


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True)
    parser.add_argument("--question", required=True)
    parser.add_argument("--requests", type=int, default=4, choices=range(1, 21))
    parser.add_argument("--concurrency", type=int, default=2, choices=range(1, 5))
    parser.add_argument("--timeout", type=int, default=60, choices=range(1, 151))
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    parsed = urlparse(args.url)
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        parser.error("URL must not contain credentials, query or fragment")
    if parsed.scheme != "https" and not (parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1", "::1"}):
        parser.error("Use HTTPS, or HTTP on localhost")
    output = Path(args.out)
    if output.exists():
        parser.error("Output already exists; choose a new evidence file")
    headers = {}
    for name, env in (("Cookie", "BRAIN_LOAD_COOKIE"), ("X-CSRFToken", "BRAIN_LOAD_CSRF"),
                      ("Authorization", "BRAIN_LOAD_AUTHORIZATION")):
        if os.environ.get(env):
            headers[name] = os.environ[env]
    headers["Referer"] = args.url
    started = time.monotonic()
    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        rows = list(pool.map(lambda _: probe(args.url, args.question, args.timeout, headers), range(args.requests)))
    elapsed = time.monotonic() - started
    successful = [r["latency_ms"] for r in rows if r["ok"]]
    report = {"scope": "HTTP SSE completion only; no semantic or production acceptance implied",
              "concurrency": args.concurrency, "requests": args.requests, "rows": rows,
              "successes": len(successful), "elapsed_seconds": round(elapsed, 2),
              "successful_requests_per_second": round(len(successful) / elapsed, 4),
              "successful_latency_p50_ms": percentile(successful, .5),
              "successful_latency_p95_ms": percentile(successful, .95)}
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)
    return 0 if len(successful) == args.requests else 1


if __name__ == "__main__":
    raise SystemExit(main())
