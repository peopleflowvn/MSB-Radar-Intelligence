import tempfile
import unittest
from pathlib import Path

from scripts.provision_runtime_env import (
    build_runtime_values, sync_radar_bridge_tokens, write_runtime_env,
)


class ProvisionRuntimeEnvTest(unittest.TestCase):
    def test_only_allowlisted_values_are_written_and_tokens_are_stable(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "hub.env"
            target = Path(directory) / "runtime.env"
            source.write_text(
                "SECRET_KEY=must-not-copy\nPOSTGRES_PASSWORD=must-not-copy\n"
                "MSB_AI_GREENNODE_BASE_URL=https://maas.example/v1\n"
                "MSB_AI_GREENNODE_API_KEY=key\nMSB_AI_GREENNODE_MODEL=chat-model\n",
                encoding="utf-8",
            )
            write_runtime_env(source, target)
            first = target.read_text(encoding="utf-8")
            write_runtime_env(source, target)
            second = target.read_text(encoding="utf-8")
        self.assertEqual(first, second)
        self.assertNotIn("SECRET_KEY", first)
        self.assertNotIn("POSTGRES_PASSWORD", first)
        self.assertIn("GREENNODE_MODEL_FAST=chat-model", first)
        self.assertIn("GREENNODE_MODEL_EMBEDDING=\n", first)

    def test_embedding_never_falls_back_to_chat_model(self):
        values = build_runtime_values({"MSB_AI_GREENNODE_MODEL": "chat"}, {})
        self.assertEqual(values["GREENNODE_MODEL_EMBEDDING"], "")

    def test_radar_uses_fixed_private_hub_url(self):
        values = build_runtime_values({}, {"RADAR_BASE_URL": "https://stale.example"})
        self.assertEqual(values["RADAR_BASE_URL"], "http://hub:8000")

    def test_reviewed_embedding_model_is_applied(self):
        values = build_runtime_values({}, {}, embedding_model="baai/bge-m3")
        self.assertEqual(values["GREENNODE_MODEL_EMBEDDING"], "baai/bge-m3")

    def test_bridge_sync_preserves_radar_env_and_adds_only_bridge_tokens(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = Path(directory) / "runtime.env"
            radar = Path(directory) / "radar.env"
            runtime.write_text("RADAR_SERVICE_TOKEN=svc\nRADAR_INDEX_SCOPE_TOKEN=idx\n", encoding="utf-8")
            radar.write_text("# keep comments\nSECRET_KEY='keep'\nPOSTGRES_PASSWORD=keep-too\n", encoding="utf-8")
            sync_radar_bridge_tokens(runtime, radar)
            values = radar.read_text(encoding="utf-8")
        self.assertIn("# keep comments\nSECRET_KEY='keep'", values)
        self.assertIn("POSTGRES_PASSWORD=keep-too", values)
        self.assertIn("INTELLIGENCE_SERVICE_TOKEN=svc", values)
        self.assertIn("INTELLIGENCE_INDEX_SCOPE_TOKEN=idx", values)


if __name__ == "__main__":
    unittest.main()
