from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from radar_intelligence import __version__
from radar_intelligence.config import RuntimeSettings


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        if self.path not in {"/health", "/ready"}:
            self.send_error(404)
            return
        if self.path == "/health":
            body = {"status": "ok", "service": "msb-radar-intelligence", "version": __version__}
            status = 200
        else:
            readiness = RuntimeSettings.from_env().public_status()
            body = {"status": "ready" if readiness["ready"] else "not_ready", **readiness}
            status = 200 if readiness["ready"] else 503
        payload = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format: str, *args: object) -> None:
        return


def main() -> None:
    host = os.environ.get("INTELLIGENCE_BIND_HOST", "127.0.0.1").strip()
    raw_port = os.environ.get("INTELLIGENCE_PORT", "8081").strip()
    if not host:
        raise ValueError("INTELLIGENCE_BIND_HOST must not be empty")
    try:
        port = int(raw_port)
    except ValueError:
        raise ValueError("INTELLIGENCE_PORT must be an integer") from None
    if not 1 <= port <= 65535:
        raise ValueError("INTELLIGENCE_PORT must be between 1 and 65535")
    server = ThreadingHTTPServer((host, port), Handler)
    print(f"MSB Radar Intelligence listening on {host}:{port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
