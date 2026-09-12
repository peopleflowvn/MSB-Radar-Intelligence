# -*- coding: utf-8 -*-
"""R0-01 (docs/RADAR_AI_AGENT_BACKLOG.md §14) — manifest của MỘT lượt đo baseline.

Vì sao cần: mọi bộ eval hiện có (`answer_eval`, `corpus_qa_eval`...) đo chất
lượng tại một THỜI ĐIỂM, nhưng không ghi lại BỐI CẢNH đã đo — kho đổi, model đổi
hay prompt đổi đều có thể làm số liệu lệch, mà không có gì phân biệt được ba
nguyên nhân đó với "chất lượng thật sự đổi". `docs/RADAR_AI_AGENT_BACKLOG.md`
gọi đây là dependency của mọi ticket P0-01 đến P0-08 — không có manifest thì
không so sánh được hai lần chạy.

`manifest()` KHÔNG chạy eval nào — chỉ chụp lại "cái gì đang có" ngay lúc gọi:
phiên bản mã nguồn, kho dữ liệu (vân tay + độ phủ), route model đang hiệu lực
cho từng tác vụ, và hash các system prompt cốt lõi (chưa có prompt registry
thật — RA-22 — nên hash là cách rẻ nhất để biết "prompt có đổi không" giữa hai
lần chạy).
"""
from __future__ import annotations

import hashlib
import subprocess


def _git_commit():
    """SHA ngắn của commit hiện tại, hoặc "" nếu không lấy được (không phải lỗi
    nghiêm trọng — máy dev không phải lúc nào cũng có `.git`, ví dụ trong image
    Docker đã xoá lịch sử git để giảm dung lượng)."""
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=5, check=False)
        return out.stdout.strip() if out.returncode == 0 else ""
    except Exception:                              # noqa: BLE001
        return ""


def _hash(text):
    return hashlib.sha256(str(text or "").encode("utf-8")).hexdigest()[:16]


def _prompt_versions():
    """Hash các system prompt CỐT LÕI của Answer Engine.

    Không phải một prompt registry thật (đó là RA-22, chưa làm) — chỉ đủ để
    một manifest cũ và một manifest mới biết NGAY prompt có đổi hay không,
    thay vì phải diff code bằng tay mỗi khi so hai lần baseline.
    """
    versions = {}
    try:
        from talent.answer import plan as plan_stage
        versions["talent_answer_plan"] = _hash(plan_stage.SYSTEM)
    except Exception:                              # noqa: BLE001
        versions["talent_answer_plan"] = ""
    try:
        from talent.answer import judge as judge_stage
        versions["talent_answer_judge"] = _hash(judge_stage.SYSTEM)
        versions["talent_answer_judge_count"] = _hash(judge_stage.COUNT_SYSTEM)
    except Exception:                              # noqa: BLE001
        versions["talent_answer_judge"] = ""
        versions["talent_answer_judge_count"] = ""
    try:
        from talent.answer import compose as compose_stage
        versions["talent_answer_compose"] = _hash(compose_stage.SYSTEM)
    except Exception:                              # noqa: BLE001
        versions["talent_answer_compose"] = ""
    return versions


def _corpus_snapshot():
    """Vân tay + độ phủ của Kho con người — phần "dataset" của manifest.

    Tái dùng `answer.cache.corpus_fingerprint()` làm khoá đối chiếu nhanh (đã
    là nguồn sự thật cho việc "kho có đổi không" ở tầng cache), cộng thêm vài
    con số độ phủ để đọc manifest không cần tra thêm lệnh khác.
    """
    from talent.answer import cache as cache_stage
    from talent.answer import retrieve as retrieve_stage

    snapshot = {"fingerprint": "", "people": 0, "with_extracted_fact": 0}
    try:
        snapshot["fingerprint"] = cache_stage.corpus_fingerprint()
    except Exception:                              # noqa: BLE001
        pass
    try:
        from people.models import Person
        snapshot["people"] = Person.objects.filter(merged_into__isnull=True).count()
    except Exception:                              # noqa: BLE001
        pass
    try:
        from intel.models import ExtractedFact
        snapshot["with_extracted_fact"] = (
            ExtractedFact.objects.filter(status=ExtractedFact.STATUS_ACCEPTED,
                                         is_current=True)
            .values("person_id").distinct().count())
    except Exception:                              # noqa: BLE001
        pass
    try:
        snapshot["index"] = retrieve_stage.coverage()
    except Exception:                              # noqa: BLE001
        snapshot["index"] = {}
    return snapshot


def _effective_routes():
    """Provider/model đang thực sự hiệu lực cho MỌI task đã đăng ký.

    Đúng nguồn `/settings` dùng để hiển thị "cấu hình thực sự có hiệu lực"
    (`ai/views.py::provider_config`) — không tự suy luận lại logic router.
    """
    from ai import tasks as tasks_registry
    from ai.models import TaskModelRoute
    from ai.router import get_router

    router = get_router()
    task_names = dict.fromkeys(
        tasks_registry.names()
        + list(TaskModelRoute.objects.values_list("task", flat=True)))
    return [router.effective_config(task) for task in task_names]


def _eval_dataset_versions():
    """Nhận diện bộ câu hỏi eval hiện có — đổi câu hỏi cũng phải coi là đổi
    baseline, không chỉ đổi code/model/kho mới tính."""
    versions = {}
    try:
        from talent.management.commands.answer_eval import QUESTIONS
        versions["talent_answer_eval"] = {
            "count": len(QUESTIONS),
            "hash": _hash(repr(QUESTIONS)),
        }
    except Exception:                              # noqa: BLE001
        versions["talent_answer_eval"] = {"count": 0, "hash": ""}
    return versions


def manifest():
    """Snapshot đầy đủ một lượt baseline — dict JSON-serializable."""
    from django.utils import timezone

    return {
        "captured_at": timezone.now().isoformat(),
        "git_commit": _git_commit(),
        "corpus": _corpus_snapshot(),
        "prompt_versions": _prompt_versions(),
        "eval_datasets": _eval_dataset_versions(),
        "effective_routes": _effective_routes(),
    }
