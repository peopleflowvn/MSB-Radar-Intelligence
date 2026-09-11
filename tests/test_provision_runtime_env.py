import tempfile
import unittest
from pathlib import Path

from scripts.provision_runtime_env import build_runtime_values, write_runtime_env


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


if __name__ == "__main__":
    unittest.main()
