from __future__ import annotations

import json
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
    server = ThreadingHTTPServer(("127.0.0.1", 8081), Handler)
    print("MSB Radar Intelligence listening on http://127.0.0.1:8081")
    server.serve_forever()


if __name__ == "__main__":
    main()
