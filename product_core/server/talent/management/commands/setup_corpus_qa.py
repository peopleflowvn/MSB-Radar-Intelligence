# -*- coding: utf-8 -*-
"""Kiểm tra & bật đường dense cho hỏi đáp trên kho CV (Master Plan §24.4).

Gom mọi bước "chuẩn bị hạ tầng" thành một lệnh có thể chạy lại nhiều lần:

    python manage.py setup_corpus_qa                       # chẩn đoán, không đổi gì
    python manage.py setup_corpus_qa --list-models         # xem model embedding sẵn có
    python manage.py setup_corpus_qa --provider greennode --model <mã> --apply

Sau khi `--apply` thành công thì chạy tiếp:

    python manage.py rebuild_talent_vector_index --stale   # dựng projection + chunk
    python manage.py embed_talent_index --loop             # tính vector (nền)
    python manage.py pin_vector_dimensions --apply         # chốt chiều + HNSW
"""
from django.core.management.base import BaseCommand
from django.db import connection

from talent import vector_index
from talent.models import CVChunk, PersonSearchDocument

_OK = "  [OK] "
_WARN = "  [!]  "
_BAD = "  [X]  "


class Command(BaseCommand):
    help = "Chẩn đoán và cấu hình đường dense retrieval cho hỏi đáp kho CV."

    def add_arguments(self, parser):
        parser.add_argument("--provider", default="")
        parser.add_argument("--model", default="")
        parser.add_argument("--apply", action="store_true")
        parser.add_argument("--list-models", action="store_true")

    def handle(self, *args, **options):
        from ai.models import ProviderConfig, TaskModelRoute
        from ai.providers import list_models
        from ai.router import _provider_from_config, reset_router

        problems = []
        self.stdout.write(self.style.MIGRATE_HEADING("1. Cơ sở dữ liệu"))
        if connection.vendor != "postgresql":
            self.stdout.write(_WARN + f"vendor = {connection.vendor}. Dense retrieval và "
                              "full-text index CHỈ chạy trên PostgreSQL; nhánh từ khoá "
                              "vẫn hoạt động.")
            problems.append("chưa chạy trên PostgreSQL")
        else:
            self.stdout.write(_OK + "PostgreSQL")
            with connection.cursor() as cursor:
                cursor.execute("SELECT count(*) FROM pg_extension WHERE extname = 'vector'")
                if cursor.fetchone()[0]:
                    self.stdout.write(_OK + "extension pgvector đã bật")
                else:
                    self.stdout.write(_BAD + "chưa có extension pgvector — chạy `migrate`.")
                    problems.append("thiếu pgvector")
                cursor.execute(
                    "SELECT count(*) FROM pg_indexes WHERE indexname LIKE '%_fts'")
                self.stdout.write(_OK + f"{cursor.fetchone()[0]} chỉ mục full-text")

        self.stdout.write(self.style.MIGRATE_HEADING("2. Chỉ mục đã dựng"))
        docs = PersonSearchDocument.objects.count()
        chunks = CVChunk.objects.count()
        stale_docs = len(vector_index.stale_documents(limit=1))
        stale_chunks = len(vector_index.stale_chunks(limit=1))
        self.stdout.write(f"  PersonSearchDocument: {docs} · CVChunk: {chunks}")
        if not chunks:
            self.stdout.write(_WARN + "chưa có đoạn CV nào — chạy "
                              "`rebuild_talent_vector_index`.")
        if stale_docs or stale_chunks:
            self.stdout.write(_WARN + "còn bản ghi chưa/đã cũ vector — chạy "
                              "`embed_talent_index --loop`.")
        elif chunks:
            self.stdout.write(_OK + "mọi bản ghi đã có vector cập nhật")

        self.stdout.write(self.style.MIGRATE_HEADING("3. Model embedding"))
        from django.conf import settings
        self_host = getattr(settings, "TALENT_EMBEDDING_BASE_URL", "")
        if self_host:
            self.stdout.write(_OK + f"TỰ HOST: {self_host} · model "
                              f"{getattr(settings, 'TALENT_EMBEDDING_MODEL', '') or '(trống!)'} "
                              "(ưu tiên hơn route DB)")
        route = TaskModelRoute.objects.filter(task="talent_embedding").first()
        if route:
            self.stdout.write(("  " if self_host else _OK)
                              + f"route DB: {route.provider}/{route.model or '(trống)'} "
                              f"· {'bật' if route.enabled else 'TẮT'}"
                              + ("  [bị TỰ HOST ghi đè]" if self_host else ""))
        elif not self_host:
            self.stdout.write(_WARN + "chưa có route `talent_embedding` — dense tắt.")

        if options["list_models"]:
            for config in ProviderConfig.objects.filter(enabled=True):
                built = _provider_from_config(config)
                if built is None:
                    continue
                try:
                    names = list_models(built)
                except Exception as exc:                   # noqa: BLE001
                    self.stdout.write(f"  {config.provider}: không liệt kê được ({exc})")
                    continue
                hits = [n for n in names
                        if any(k in n.lower() for k in ("embed", "bge", "e5", "gte"))]
                self.stdout.write(f"  {config.provider}: {len(names)} model, "
                                  f"gợi ý embedding: {', '.join(hits[:10]) or '(không rõ)'}")

        provider, model = options["provider"], options["model"]
        if provider and model:
            if provider not in dict(ProviderConfig.PROVIDER_CHOICES):
                self.stdout.write(self.style.ERROR(
                    f"  Provider không hỗ trợ: {provider}"))
                return
            if not options["apply"]:
                self.stdout.write(f"  → sẽ đặt route talent_embedding = {provider}/{model} "
                                  f"(thêm --apply để thực thi)")
            else:
                TaskModelRoute.objects.update_or_create(
                    task="talent_embedding",
                    defaults={"provider": provider, "model": model, "enabled": True,
                              "updated_by": "setup_corpus_qa"})
                reset_router()
                self.stdout.write(_OK + f"đã đặt route talent_embedding = {provider}/{model}")

        self.stdout.write(self.style.MIGRATE_HEADING("4. Thử embed một chuỗi"))
        vector, used_model = vector_index.embed("chuyên viên quan hệ khách hàng cá nhân",
                                                task_type="RETRIEVAL_QUERY")
        if vector:
            self.stdout.write(_OK + f"{used_model} trả vector {len(vector)} chiều")
        else:
            self.stdout.write(_BAD + f"không lấy được vector (model: {used_model or 'chưa cấu hình'}).")
            problems.append("embedding chưa dùng được")

        self.stdout.write("")
        if problems:
            self.stdout.write(self.style.WARNING(
                "Chưa sẵn sàng dense: " + "; ".join(problems)
                + ". Hỏi đáp kho CV vẫn chạy bằng nhánh từ khoá."))
        else:
            self.stdout.write(self.style.SUCCESS(
                "Sẵn sàng. Tiếp: rebuild_talent_vector_index --stale → "
                "embed_talent_index --loop → pin_vector_dimensions --apply"))
