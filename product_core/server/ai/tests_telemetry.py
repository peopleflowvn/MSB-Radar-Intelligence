from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

from django.test import TestCase

from . import telemetry
from .providers import Completion
from .router import Router


class TelemetryTest(TestCase):
    def test_missing_usage_is_unknown_but_explicit_zero_is_known(self):
        result = Completion("text", "fixture", "m")
        self.assertEqual(telemetry.reported_usage(result), {"prompt_tokens": None, "completion_tokens": None})
        result.raw = {"usage": {"prompt_tokens": 5, "completion_tokens": 0}}
        self.assertEqual(telemetry.reported_usage(result), {"prompt_tokens": 5, "completion_tokens": 0})

    def test_capability_defaults_do_not_change_existing_task_routes(self):
        from . import tasks
        for name, route in tasks.DEFAULT_ROUTE.items():
            self.assertEqual(tasks.default_route(name), route)
            self.assertIn(tasks.capability_for(name), {"FAST", "DEEP", "VISION", "EMBEDDING"})
        self.assertEqual(tasks.default_route("unregistered_task"), ("", ""))

    def test_parallel_calls_join_one_trace_without_prompt_or_error_text(self):
        with telemetry.capture() as scope:
            with ThreadPoolExecutor(max_workers=2) as pool:
                def record():
                    telemetry.record({"task": "x", "provider": "fixture", "model": "m",
                        "ok": True, "prompt_tokens": 10, "completion_tokens": 2,
                        "latency_ms": 5, "error": "sensitive", "messages": ["private"]})
                futures = [telemetry.submit(pool, record) for _ in range(2)]
                for future in futures:
                    future.result()
            result = SimpleNamespace(trace={})
            telemetry.attach(result, scope)
        self.assertEqual(result.trace["usage"]["input_tokens"], 20)
        self.assertNotIn("private", str(result.trace))
        self.assertNotIn("sensitive", str(result.trace))
        with telemetry.capture() as second:
            self.assertEqual(second["calls"], [])

    def test_stream_budget_is_consumed_by_router_not_forwarded_to_provider(self):
        calls = []
        class Provider:
            model = "fixture"
            timeout = 60
            def stream(self, messages, *, timeout=None, model=None):
                calls.append(timeout)
                yield {"type": "done", "completion": Completion("ok", "fixture", "fixture")}
        router = Router(env={})
        router.maybe_refresh = lambda: None
        router.provider_order = lambda task="": ["fixture"]
        router.get_provider = lambda name: Provider()
        with telemetry.capture() as scope:
            list(router.stream([], budget_seconds=3))
        self.assertEqual(len(calls), 1)
        self.assertLessEqual(calls[0], 3)
        self.assertEqual(len(scope["calls"]), 1)

    def test_embedding_checks_every_coordinate_and_reports_failure(self):
        import json
        from unittest.mock import MagicMock, patch
        from talent import vector_index
        for bad in (float("nan"), float("inf"), True, "wrong"):
            vector = [0.1] * vector_index.MIN_DIMENSIONS
            vector[-1] = bad
            response = MagicMock()
            response.__enter__.return_value.read.return_value = json.dumps(
                {"data": [{"embedding": vector}]}).encode()
            with patch.object(vector_index, "_embedding_config", return_value=("fixture", "https://fixture.invalid", "fixture", "m")), \
                    patch.object(vector_index.urllib.request, "urlopen", return_value=response), \
                    telemetry.capture() as scope:
                self.assertEqual(vector_index.embed("fixture"), (None, "m"))
                self.assertFalse(scope["calls"][0]["ok"])
