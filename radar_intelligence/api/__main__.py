from __future__ import annotations

import json
import os
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from radar_intelligence import __version__
from radar_intelligence.config import RuntimeSettings
from radar_intelligence.api.codec import (
    ApiContractError, decode_answer_request, decode_search_request,
)
from radar_intelligence.api.search_service import SearchService


class Handler(BaseHTTPRequestHandler):
    search_service = None

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/index-status":
            if not self._service_authorized() or self.search_service is None:
                self._json(404, {"detail": "Not found."})
            else:
                self._json(200, self.search_service.index_status())
            return
        if self.path not in {"/health", "/ready"}:
            self.send_error(404)
            return
        if self.path == "/health":
            body = {
                "status": "ok",
                "service": "msb-radar-intelligence",
                "version": __version__,
                "release_sha": os.environ.get("INTELLIGENCE_RELEASE_SHA", "").strip() or None,
            }
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

    def do_POST(self) -> None:  # noqa: N802
        if self.path not in {"/v1/search", "/v1/answer"}:
            self.send_error(404)
            return
        if not self._service_authorized():
            self._json(404, {"detail": "Not found."})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 1 <= length <= 64 * 1024:
                raise ApiContractError("request body size is invalid")
            payload = json.loads(self.rfile.read(length))
            request = (decode_search_request(payload) if self.path == "/v1/search"
                       else decode_answer_request(payload))
            service = self.search_service
            if service is None:
                raise RuntimeError("search service is unavailable")
            result = (service.search(request) if self.path == "/v1/search"
                      else service.answer(request))
            if result is None:
                self._json(404, {"detail": "Not found."})
            else:
                self._json(200, {"hits": result} if self.path == "/v1/search" else result)
        except (ApiContractError, json.JSONDecodeError, UnicodeDecodeError) as exc:
            self._json(400, {"detail": str(exc)})
        except Exception:
            self._json(503, {"detail": "Search temporarily unavailable."})

    def _service_authorized(self) -> bool:
        expected = os.environ.get("RADAR_SERVICE_TOKEN", "")
        supplied = self.headers.get("Authorization", "")
        supplied = supplied[7:] if supplied.startswith("Bearer ") else ""
        return bool(expected) and hmac.compare_digest(expected, supplied)

    def _json(self, status: int, body: dict) -> None:
        payload = json.dumps(body, ensure_ascii=False).encode()
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
    settings = RuntimeSettings.from_env()
    if settings.ready:
        database = os.environ.get(
            "INTELLIGENCE_INDEX_DB", "/var/lib/radar-intelligence/index.sqlite3")
        Handler.search_service = SearchService(settings, database)
    server = ThreadingHTTPServer((host, port), Handler)
    print(f"MSB Radar Intelligence listening on {host}:{port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
