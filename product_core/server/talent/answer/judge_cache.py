# -*- coding: utf-8 -*-
"""Nhớ lại kết luận đã đọc, để không trả tiền đọc cùng một hồ sơ hai lần.

`engine.reusable_judgements` chỉ sống trong MỘT request, nên mỗi lượt hỏi lại
gọi model cho đúng những người đã đọc ở lượt trước — kể cả câu hỏi tinh chỉnh
("trong số đó ai ở Hà Nội?"). Production 20/09 chỉ có **một khoá GreenNode** và
hạn mức tính theo khoá, nên đó vừa là tiền vừa là nguyên nhân mất phần đọc sâu:
judge bắn 4 lô song song rồi phần lớn nhận 429.

Khoá gồm đúng ba thứ quyết định một kết luận: **người**, **dấu nội dung hồ sơ**,
và **bộ tiêu chí đã chuẩn hoá**. CV đổi thì dấu đổi, nên không đọc lại kết luận
cũ trên dữ liệu mới. Bản đầu lấy khoá từ `judge.dossier_key`, trong đó có câu chữ
kế hoạch do LLM sinh và danh sách đoạn đã chọn — đo trên production: ba lượt hỏi
cùng một câu tạo ba tập khoá mới, 0 lần dùng lại.

Hai luật giữ cho cache không nói quá:

* Kết luận còn `UNKNOWN` thì **không** lưu: lượt sau có thể chọn được đoạn bằng
  chứng khác và kết luận được. Lưu lại nghĩa là đóng băng một câu "chưa biết".
* `scope_token` gắn theo người hỏi. Dùng chung giữa các người dùng sẽ tiết kiệm
  hơn nhiều, nhưng chỉ được làm sau khi rà RBAC — và bản này không rà, nên không
  làm.
"""
import hashlib
import logging

log = logging.getLogger(__name__)

#: Phiên bản schema/prompt của chặng đọc. Đổi prompt hay đổi hình dạng kết luận
#: thì tăng số này, nếu không cache cũ sẽ trả kết luận theo luật đã bỏ.
JUDGE_SCHEMA_VERSION = 3


def scope_token_for(user):
    """Nhãn phạm vi của người hỏi. Không có người hỏi ⇒ không cache."""
    pk = getattr(user, "pk", None)
    return f"user:{pk}" if pk else ""


def criteria_signature(query_plan):
    """Dấu của BỘ TIÊU CHÍ, đã chuẩn hoá — không phải của câu chữ kế hoạch.

    Bản đầu của cache này lấy khoá từ `judge.dossier_key`, trong đó có
    `information_need`/`extract` do LLM sinh và danh sách đoạn CV đã chọn. Cả hai
    đổi mỗi lượt, nên đo trên production 20/09: ba lượt hỏi **cùng một câu** tạo
    ba tập khoá mới hoàn toàn, 0 lần dùng lại — một cache chỉ ghi.

    Nay khoá dựa trên đúng ba thứ quyết định kết luận: người, nội dung hồ sơ, và
    bộ tiêu chí. Chuẩn hoá (bỏ dấu, hạ chữ, sắp xếp) để cùng một yêu cầu diễn đạt
    hơi khác vẫn gặp nhau.
    """
    from people.normalize import normalize_name

    items = [*(getattr(query_plan, "must_have", None) or []),
             *(getattr(query_plan, "should_have", None) or [])]
    folded = sorted({normalize_name(str(item)).strip() for item in items if str(item).strip()})
    return "|".join(folded)


def person_fingerprint(person_id, candidate=None):
    """Dấu nội dung hồ sơ. Ưu tiên `BaseDossier` của V2; không có thì dựng từ nguồn."""
    try:
        from talent.models import BaseDossier
        row = (BaseDossier.objects.filter(person_id=person_id)
               .values_list("fingerprint", flat=True).first())
        if row:
            return str(row)[:64]
    except Exception:                              # noqa: BLE001 - chưa migrate
        pass
    sources = [(getattr(p, "document_id", ""), getattr(p, "ordinal", ""))
               for p in (getattr(candidate, "passages", None) or [])]
    return hashlib.sha256(str(sorted(sources)).encode("utf-8")).hexdigest()[:64]


def _row_key(person_id, fingerprint, criteria, scope_token):
    raw = f"{JUDGE_SCHEMA_VERSION}|{scope_token}|{person_id}|{fingerprint}|{criteria}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _reusable(judgement):
    """Chỉ kết luận đã dứt khoát mới được nhớ."""
    criteria = getattr(judgement, "criteria", None) or []
    return not any(str(row.get("status") or "").upper() == "UNKNOWN"
                   for row in criteria)


def load(entries, *, scope_token, criteria):
    """`{person_id: Judgement}` cho những hồ sơ đã có kết luận đầy đủ.

    `entries` là `{person_id: fingerprint}`.
    """
    if not entries or not scope_token or not criteria:
        return {}
    from talent.models import ConstraintJudgementCache
    from .judge import Judgement

    wanted = {_row_key(pid, fp, criteria, scope_token): pid
              for pid, fp in entries.items()}
    found = {}
    try:
        rows = (ConstraintJudgementCache.objects
                .filter(key__in=list(wanted), complete=True,
                        schema_version=JUDGE_SCHEMA_VERSION)
                .values_list("key", "judgement"))
        for row_key, payload in rows:
            if not isinstance(payload, dict) or not payload.get("person_id"):
                continue
            found[wanted[row_key]] = Judgement(**payload)
    except Exception:                              # noqa: BLE001 - cache never breaks a turn
        log.exception("judge_cache: đọc cache hỏng, bỏ qua")
        return {}
    return found


def store(judgement, *, scope_token, criteria, fingerprint, person_id=None,
          tokens=0):
    """Nhớ một kết luận. Trả `True` nếu đã lưu."""
    person_id = person_id or getattr(judgement, "person_id", None)
    if not scope_token or not criteria or not person_id or not _reusable(judgement):
        return False
    from talent.models import ConstraintJudgementCache

    try:
        ConstraintJudgementCache.objects.update_or_create(
            key=_row_key(person_id, fingerprint, criteria, scope_token),
            defaults={
                "person_id": person_id,
                "dossier_fingerprint": str(fingerprint)[:64],
                "constraint_canonical": str(criteria)[:500],
                "scope_token": scope_token[:64],
                "schema_version": JUDGE_SCHEMA_VERSION,
                "model": (getattr(judgement, "model", "") or "")[:120],
                "prompt_version": f"judge.v{JUDGE_SCHEMA_VERSION}",
                "judgement": judgement.as_dict(),
                "complete": True,
                "token_usage": max(0, int(tokens or 0)),
            })
        return True
    except Exception:                              # noqa: BLE001
        log.exception("judge_cache: ghi cache hỏng, bỏ qua")
        return False
