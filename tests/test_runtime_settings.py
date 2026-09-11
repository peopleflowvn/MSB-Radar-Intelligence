import unittest

from radar_intelligence.config import RuntimeSettings


def complete():
    return {
        "RADAR_BASE_URL": "https://radar.example",
        "RADAR_SERVICE_TOKEN": "radar-secret",
        "RADAR_INDEX_SCOPE_TOKEN": "scope-secret",
        "GREENNODE_BASE_URL": "https://green.example/v1",
        "GREENNODE_API_KEY": "green-secret",
        "GREENNODE_MODEL_FAST": "fast",
        "GREENNODE_MODEL_DEEP": "deep",
        "GREENNODE_MODEL_VISION": "vision",
        "GREENNODE_MODEL_EMBEDDING": "embedding",
    }


class RuntimeSettingsTest(unittest.TestCase):
    def test_complete_configuration_is_ready_without_exposing_secrets(self):
        status = RuntimeSettings.from_env(complete()).public_status()
        self.assertTrue(status["ready"])
        self.assertTrue(status["radar_configured"])
        self.assertTrue(status["greennode_configured"])
        rendered = repr(status)
        self.assertNotIn("radar-secret", rendered)
        self.assertNotIn("green-secret", rendered)

    def test_missing_configuration_reports_names_only(self):
        status = RuntimeSettings.from_env({}).public_status()
        self.assertFalse(status["ready"])
        self.assertIn("GREENNODE_API_KEY", status["missing"])
        self.assertFalse(status["radar_configured"])

    def test_external_urls_must_use_https(self):
        values = complete()
        values["RADAR_BASE_URL"] = "http://radar.example"
        with self.assertRaisesRegex(ValueError, "RADAR_BASE_URL"):
            RuntimeSettings.from_env(values)

    def test_fixed_docker_internal_hub_url_is_allowed(self):
        values = complete()
        values["RADAR_BASE_URL"] = "http://hub:8000"
        self.assertTrue(RuntimeSettings.from_env(values).ready)


if __name__ == "__main__":
    unittest.main()
