# -*- coding: utf-8 -*-
from io import StringIO
from unittest import mock

from django.core.management import call_command
from django.test import TestCase

from ai.models import ProviderConfig
from people.models import Person
from talent.models import EmbeddingConfig, PersonSearchDocument


class ConfigureGreenNodeEmbeddingTest(TestCase):
    def setUp(self):
        provider = ProviderConfig.objects.create(provider="greennode", enabled=True)
        provider.set_api_key("test-key")
        provider.save()
        self.person = Person.objects.create(display_name="Ứng viên")
        self.projection = PersonSearchDocument.objects.create(
            person=self.person,
            fingerprint="current-content",
            content="Kỹ sư dữ liệu",
            content_norm="ky su du lieu",
            embedding_fingerprint="current-content",
        )

    def _run(self):
        output = StringIO()
        with mock.patch(
                "talent.management.commands.configure_greennode_embedding.list_models",
                return_value=["baai/bge-m3"]), mock.patch(
                "talent.management.commands.configure_greennode_embedding.vector_index.embed",
                return_value=([0.1] * 1024, "baai/bge-m3")):
            call_command("configure_greennode_embedding", "--apply", stdout=output)
        return output.getvalue()

    def test_same_model_does_not_reset_completed_backfill(self):
        cfg = EmbeddingConfig.load()
        cfg.mode = cfg.MODE_GREENNODE
        cfg.greennode_model = "baai/bge-m3"
        cfg.save()

        output = self._run()

        self.projection.refresh_from_db()
        self.assertEqual(self.projection.embedding_fingerprint, "current-content")
        self.assertIn("giữ nguyên hàng đợi", output)

    def test_changed_model_marks_existing_vectors_stale(self):
        cfg = EmbeddingConfig.load()
        cfg.mode = cfg.MODE_GEMINI
        cfg.save()

        output = self._run()

        self.projection.refresh_from_db()
        self.assertEqual(self.projection.embedding_fingerprint, "pending-reembed")
        self.assertIn("đã xếp lại hàng đợi", output)
