import unittest

from scripts.init_standalone_env import GENERATED, ROOT, fill_secrets


class InitStandaloneEnvTest(unittest.TestCase):
    def test_template_gets_every_secret(self):
        lines = (ROOT / ".env.standalone.example").read_text(encoding="utf-8").splitlines()
        output, filled = fill_secrets(lines)
        self.assertEqual(sorted(filled), sorted(GENERATED))
        values = dict(line.split("=", 1) for line in output if "=" in line and not line.startswith("#"))
        for name in GENERATED:
            self.assertGreaterEqual(len(values[name]), 32)

    def test_existing_values_are_never_overwritten(self):
        lines = ["SECRET_KEY=keep", "POSTGRES_PASSWORD=keep-too", "# INTELLIGENCE_SERVICE_TOKEN="]
        output, filled = fill_secrets(lines)
        self.assertIn("SECRET_KEY=keep", output)
        self.assertIn("POSTGRES_PASSWORD=keep-too", output)
        self.assertIn("# INTELLIGENCE_SERVICE_TOKEN=", output)
        self.assertEqual(sorted(filled), ["INTELLIGENCE_INDEX_SCOPE_TOKEN", "INTELLIGENCE_SERVICE_TOKEN"])


if __name__ == "__main__":
    unittest.main()
