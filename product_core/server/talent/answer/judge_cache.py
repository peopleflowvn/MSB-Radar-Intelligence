# -*- coding: utf-8 -*-
"""Nhớ lại kết luận đã đọc, để không trả tiền đọc cùng một hồ sơ hai lần.

`engine.reusable_judgements` chỉ sống trong MỘT request, nên mỗi lượt hỏi lại
gọi model cho đúng những người đã đọc ở lượt trước — kể cả câu hỏi tinh chỉnh
("trong số đó ai ở Hà Nội?"). Production 20/09 chỉ có **một khoá GreenNode** và
hạn mức tính theo khoá, nên đó vừa là tiền vừa là nguyên nhân mất phần đọc sâu:
judge bắn 4 lô song song rồi phần lớn nhận 429.

Khoá cache là `judge.dossier_key(...)` — nó đã bao gồm câu hỏi (shape, need,
must/should, extract), người, **nội dung dossier** và danh sách nguồn. CV đổi hay
câu hỏi đổi ⇒ khoá đổi ⇒ không có chuyện đọc lại kết luận cũ trên dữ liệu mới.

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
JUDGE_SCHEMA_VERSION = 1


def scope_token_for(user):
    """Nhãn phạm vi của người hỏi. Không có người hỏi ⇒ không cache."""
    pk = getattr(user, "pk", None)
    return f"user:{pk}" if pk else ""


def _row_key(dossier_key, scope_token):
    raw = f"{JUDGE_SCHEMA_VERSION}|{scope_token}|{dossier_key}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _reusable(judgement):
    """Chỉ kết luận đã dứt khoát mới được nhớ."""
    criteria = getattr(judgement, "criteria", None) or []
    return not any(str(row.get("status") or "").upper() == "UNKNOWN"
                   for row in criteria)


def load(keys, *, scope_token):
    """`{dossier_key: Judgement}` cho những khoá đã có kết luận đầy đủ."""
    if not keys or not scope_token:
        return {}
    from talent.models import ConstraintJudgementCache
    from .judge import Judgement

    wanted = {_row_key(key, scope_token): key for key in keys}
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


def store(dossier_key, judgement, *, scope_token, person_id=None, tokens=0):
    """Nhớ một kết luận. Trả `True` nếu đã lưu."""
    if not scope_token or not dossier_key or not _reusable(judgement):
        return False
    from talent.models import ConstraintJudgementCache

    try:
        ConstraintJudgementCache.objects.update_or_create(
            key=_row_key(dossier_key, scope_token),
            defaults={
                "person_id": person_id or judgement.person_id,
                # `dossier_key` đã gói nội dung dossier; giữ nguyên để truy vết.
                "dossier_fingerprint": str(dossier_key)[:64],
                "constraint_canonical": "judge.turn",
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
