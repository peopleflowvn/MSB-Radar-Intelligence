# -*- coding: utf-8 -*-
"""Discover, probe and optionally activate GreenNode's BGE-M3 embedding model."""
from django.core.management.base import BaseCommand, CommandError

from ai.models import ProviderConfig, TaskModelRoute
from ai.providers import OpenAICompatibleProvider, PROVIDER_DEFAULTS, list_models
from talent import vector_index
from talent.models import CVChunk, EmbeddingConfig, PersonSearchDocument


class Command(BaseCommand):
    help = "Dò model BGE-M3 trên GreenNode, probe vector và bật làm nguồn embedding."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true")

    def handle(self, *args, **options):
        pc = ProviderConfig.objects.filter(provider="greennode", enabled=True).first()
        if not pc or not pc.get_api_key():
            raise CommandError("GreenNode chưa bật hoặc chưa có khoá trong /settings.")
        provider = OpenAICompatibleProvider(
            "greennode", pc.base_url or PROVIDER_DEFAULTS["greennode"]["base_url"],
            pc.get_api_key(), pc.model or "catalog-probe", timeout=pc.timeout)
        ids = list_models(provider)
        matches = [item for item in ids if "bge-m3" in item.lower().replace("_", "-")]
        self.stdout.write(f"GreenNode: {len(ids)} model; BGE-M3: {matches or '(không có)'}")
        if not matches:
            raise CommandError("GreenNode /models không trả về BGE-M3; không đổi cấu hình.")
        model = sorted(matches, key=lambda item: (len(item), item))[0]
        if not options["apply"]:
            self.stdout.write(f"Dry-run: sẽ dùng greennode/{model}")
            return

        cfg = EmbeddingConfig.load()
        old = (cfg.mode, cfg.greennode_model)
        changed = old != (cfg.MODE_GREENNODE, model)
        cfg.mode, cfg.greennode_model = cfg.MODE_GREENNODE, model
        cfg.updated_by = "configure-greennode-embedding"
        cfg.save(update_fields=["mode", "greennode_model", "updated_by", "updated_at"])
        vector, used_model = vector_index.embed(
            "chuyên viên quan hệ khách hàng cá nhân", task_type="RETRIEVAL_QUERY")
        if not vector:
            cfg.mode, cfg.greennode_model = old
            cfg.save(update_fields=["mode", "greennode_model", "updated_at"])
            raise CommandError("Probe BGE-M3 thất bại; đã khôi phục cấu hình trước đó.")

        TaskModelRoute.objects.update_or_create(
            task="talent_embedding",
            defaults={"provider": "greennode", "model": model, "enabled": True,
                      "updated_by": "configure-greennode-embedding"})
        if changed:
            PersonSearchDocument.objects.exclude(embedding_fingerprint="").update(
                embedding_fingerprint="pending-reembed")
            CVChunk.objects.exclude(embedding_fingerprint="").update(
                embedding_fingerprint="pending-reembed")
        queue_note = "đã xếp lại hàng đợi" if changed else "giữ nguyên hàng đợi hiện tại"
        self.stdout.write(self.style.SUCCESS(
            f"Đã bật greennode/{used_model}; probe OK {len(vector)} chiều; {queue_note}."))
