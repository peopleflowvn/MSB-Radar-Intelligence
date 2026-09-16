# -*- coding: utf-8 -*-
"""③ Đọc bằng chứng → phán đoán khách nào đáng theo đuổi + BÓC thuộc tính.

Đây là chặng `rb/prospects.py` hoàn toàn không có. Bộ cũ đi thẳng từ bộ lọc SQL
sang `_score()` — tức từ "khớp cột" sang "điểm ưu tiên", không có chỗ nào ĐỌC.
Hệ quả: mọi câu hỏi mà câu trả lời nằm trong *nội dung* tín hiệu ("có dấu hiệu
chuẩn bị mua nhà", "đang than phiền về ngân hàng cũ") đều không trả lời được,
dù dữ liệu có sẵn trong `SocialPost.content`.

## Ba khác biệt so với ③ của Talent

**1. Thời gian là một phần của phán đoán, không phải siêu dữ liệu.**
Mỗi đoạn gửi cho model đều kèm "cách đây bao nhiêu ngày", và prompt bắt phải cân
nhắc nó. Một CV hai năm tuổi vẫn nói đúng người đó từng làm gì; một tín hiệu vay
mua nhà hai năm tuổi thì gần như chắc chắn đã hết hiệu lực.

**2. Phải phân biệt NHU CẦU với TRẠNG THÁI.**
"Đang hỏi vay mua nhà" (nhu cầu, hành động được ngay) khác "đã vay mua nhà"
(trạng thái, có thể là cơ hội bán chéo nhưng không phải cùng một việc). Bộ khớp
chữ không phân biệt được hai câu này — chúng chứa gần hết cùng bộ từ.

**3. Phải đọc được lời TỪ CHỐI.**
Nếu bằng chứng có kết quả tiếp cận trước mà khách đã nói không, model phải đánh
dấu và ④ sẽ loại. Đây là ràng buộc không tồn tại bên Talent: ứng viên trượt một
vị trí vẫn hợp lệ cho vị trí khác, còn khách đã nói "không quan tâm" mà bị chào
lại là cách nhanh nhất để mất khách.

Chống bịa: model chỉ được trích **nguyên văn** từ đoạn đã gửi; CODE đối chiếu
lại từng trích dẫn với văn bản gốc, không khớp thì loại bỏ trích dẫn đó.
"""
from __future__ import annotations

import logging
import math
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from ai.jsonx import extract_json
from ai.prompt_guard import GUARD_RULE
from ai.router import complete

log = logging.getLogger(__name__)

TASK = "rb_prospect_search"

#: Số hồ sơ mỗi lượt đọc. Giữ NHỎ có chủ ý — cùng lý do với Talent: lô lớn khiến
#: model vượt trần token và trả JSON cụt, parse ra rỗng, rồi ⑤ đi báo "không có
#: khách nào" trong khi ② đã tìm được vài chục người.
BATCH = 8
MAX_TOKENS = 6000
#: Số lô đọc song song. Vừa phải: bắn quá nhiều lượt cùng lúc vào một khoá nhà
#: cung cấp thì dính hạn mức, đổi chậm lấy lỗi 429.
WORKERS = 4
#: Trích dẫn ngắn hơn mức này không đủ để đối chiếu — bỏ.
MIN_QUOTE = 12

SYSTEM = """Bạn là chuyên viên quan hệ khách hàng (RM) giàu kinh nghiệm của ngân hàng
MSB, đang sàng danh sách khách hàng tiềm năng.

Bạn nhận: một NHU CẦU TÌM KIẾM và một DANH SÁCH khách hàng, mỗi người kèm các
đoạn bằng chứng nguyên văn. Mỗi đoạn có nhãn nguồn và **thời gian**:

    [social]   chính lời khách viết trên mạng xã hội — bằng chứng MẠNH NHẤT
    [comment]  bình luận dưới bài của họ
    [signal]   tín hiệu hệ thống đã ghi nhận
    [interest] nhóm sản phẩm họ có dấu hiệu quan tâm
    [outcome]  KẾT QUẢ lần MSB đã tiếp cận trước đây
    [profile]  thông tin hồ sơ (nghề nghiệp, phân khúc) — nền tĩnh, yếu nhất

Với TỪNG khách hàng, quyết định dựa DUY NHẤT trên đoạn được cấp:

1. Người này có thoả nhu cầu tìm kiếm không? Ràng buộc trong "bat_buoc" mà không
   có bằng chứng thì KHÔNG thoả — không suy đoán, không cho qua vì "có vẻ hợp".

2. **Cân nhắc THỜI GIAN.** Mỗi đoạn ghi rõ cách đây bao nhiêu ngày. Nhu cầu tài
   chính hết hạn: một người hỏi vay mua nhà 5 ngày trước đang cần thật; hỏi 400
   ngày trước thì gần như chắc đã xong việc đó. Nêu rõ trong "vi_sao" nếu bằng
   chứng đã cũ.

3. **Phân biệt NHU CẦU với TRẠNG THÁI.** "Đang tìm hiểu vay mua nhà" là nhu cầu
   — hành động được ngay. "Đã mua nhà rồi" là trạng thái — có thể mở ra sản phẩm
   khác (bảo hiểm, thẻ), nhưng KHÔNG phải cùng một nhu cầu. Nói rõ bạn đọc được
   cái nào.

4. **Đọc kỹ đoạn [outcome].** Nếu MSB đã tiếp cận và khách nói KHÔNG QUAN TÂM
   hoặc ĐANG DÙNG RỒI cho đúng nhóm sản phẩm này, đặt "da_tu_choi": true. Chào
   lại người vừa từ chối là cách nhanh nhất để mất khách.

5. Trích NGUYÊN VĂN đoạn chứng minh (copy đúng chữ từ đoạn được cấp, không viết
   lại, không tóm tắt). Không trích được thì không được khẳng định. Người nào
   bạn đánh thoa=true thì BẮT BUỘC có ít nhất một trích dẫn, và "doan" phải là
   số thứ tự đoạn bạn lấy câu chữ đó ra.

6. Bóc các thuộc tính trong "can_boc" nếu bằng chứng có nói. Không có thì để
   null — TUYỆT ĐỐI không đoán thu nhập, tài sản, hay tình trạng tài chính.

Chỉ trả JSON:
{"ket_qua": [{
  "id": <id khách hàng>,
  "thoa": true|false,
  "do_tin": 0.0-1.0,
  "da_tu_choi": true|false,
  "nhu_cau_hay_trang_thai": "nhu_cau"|"trang_thai"|"khong_ro",
  "vi_sao": "<2-4 câu MỘT DÒNG (không xuống dòng trong chuỗi JSON): đọc được
    CỤ THỂ điều gì, cách đây bao lâu, khớp với điều kiện nào — hoặc vì sao loại.
    Không viết chung chung kiểu 'có nhu cầu tài chính' mà không nói rõ nhu cầu
    gì và căn cứ ở đâu>",
  "trich_dan": [{"doan": <số thứ tự đoạn>, "nguyen_van": "<copy đúng chữ>"}],
  "boc_duoc": {"<tên thuộc tính>": <giá trị hoặc null>},
  "con_thieu": "<điều chưa rõ, để trống nếu không>"
}]}

Bắt buộc: liệt kê ĐỦ mọi khách hàng được cấp, kể cả người bị loại (thoa=false).
Viết tiếng Việt, gọn.""" + "\n\n" + GUARD_RULE


@dataclass
class Judgement:
    """Phán đoán về một khách hàng.

    Giữ đúng các trường mà `core/answer/verify.py` và `core/answer/cache.py`
    trông đợi (`person_id`, `name`, `as_dict()`), cộng thêm hai trường chỉ Growth
    mới cần: `declined` và `need_kind`.
    """

    person_id: int
    name: str = ""
    relevant: bool = False
    confidence: float = 0.0
    why: str = ""
    evidence: list = field(default_factory=list)   # [{ref, source, quote, age_days}]
    extracted: dict = field(default_factory=dict)
    gap: str = ""
    #: Khách đã từng từ chối đúng nhóm sản phẩm này — ④ sẽ loại.
    declined: bool = False
    #: "nhu_cau" | "trang_thai" | "khong_ro" — xem prompt mục 3.
    need_kind: str = "khong_ro"
    #: Ngày của bằng chứng MỚI NHẤT. ④ dùng cho chiều `timing`.
    freshest_days: object = None
    criteria: list = field(default_factory=list)

    def as_dict(self):
        return {"person_id": self.person_id, "name": self.name,
                "relevant": self.relevant, "confidence": self.confidence,
                "why": self.why, "evidence": self.evidence,
                "extracted": self.extracted, "gap": self.gap,
                "declined": self.declined, "need_kind": self.need_kind,
                "freshest_days": self.freshest_days, "criteria": self.criteria}


def from_row(row):
    """Dựng lại `Judgement` từ một dòng đã cache. Xem `cache.py`."""
    return Judgement(
        person_id=row["person_id"], name=row.get("name", ""),
        relevant=row.get("relevant", False), confidence=row.get("confidence", 0.0),
        why=row.get("why", ""), evidence=row.get("evidence") or [],
        extracted=row.get("extracted") or {}, gap=row.get("gap", ""),
        declined=row.get("declined", False),
        need_kind=row.get("need_kind", "khong_ro"),
        freshest_days=row.get("freshest_days"),
        criteria=row.get("criteria") or [])


class JudgeReport(list):
    """Danh sách phán đoán, mang theo số liệu về CHÍNH lần chạy này.

    `broken`/`incomplete` là thứ ⑤ bắt buộc phải biết: ② tìm được người mà ③
    không đọc nổi thì KHÔNG được kết luận "kho không có ai". Không mang số liệu
    này theo thì một lỗi nhà cung cấp trông y hệt một kho rỗng.
    """

    def __init__(self, rows, *, batches=0, failed=0):
        super().__init__(rows)
        self.batches = batches
        self.failed = failed

    @property
    def broken(self):
        """Mọi lô đều hỏng — không có phán đoán nào là thật."""
        return bool(self.batches) and self.failed >= self.batches

    @property
    def incomplete(self):
        return bool(self.failed) and not self.broken


def _fold(text):
    from talent.vector_index import fold_text
    return fold_text(text)


def _verify_quote(quote, candidate):
    """Trích dẫn phải có mặt THẬT trong đoạn đã gửi. Không thì bỏ.

    So trên dạng bỏ dấu + gộp khoảng trắng: model hay chuẩn hoá lại khoảng trắng
    hoặc gõ thiếu dấu, và loại một trích dẫn đúng vì lý do đó thì ta tự bịt mắt
    mình. Nhưng nội dung thì phải khớp — đây là toàn bộ điểm của phép kiểm.
    """
    text = " ".join(str(quote or "").split())
    if len(text) < MIN_QUOTE:
        return None
    needle = _fold(text)
    for passage in candidate.passages:
        if needle in _fold(passage.text):
            return text
    return None


def _passage_at(number, candidate):
    try:
        index = int(number) - 1
    except (TypeError, ValueError):
        return None
    if 0 <= index < len(candidate.passages):
        return candidate.passages[index]
    return None


def _num(value, low=0.0, high=1.0):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return low
    if math.isnan(number) or math.isinf(number):
        return low
    return max(low, min(high, number))


def _dossier(index, candidate, query_plan):
    """Hồ sơ một khách hàng, đánh số đoạn để model trích dẫn được."""
    lines = [f"--- KHÁCH HÀNG id={candidate.person_id} ({candidate.name}) ---"]
    for number, passage in enumerate(candidate.passages, start=1):
        age = passage.age_days()
        when = f"cách đây {age} ngày" if age is not None else "không rõ thời điểm"
        lines.append(f"[{number}] ({passage.source}, {when}) {passage.text}")
    if len(lines) == 1:
        lines.append("[1] (không có bằng chứng nào được lập chỉ mục cho người này)")
    del index, query_plan
    return "\n".join(lines)


def _messages(query_plan, batch):
    need = {
        "nhu_cau": getattr(query_plan, "information_need", ""),
        "bat_buoc": list(getattr(query_plan, "must_have", None) or []),
        "mong_muon": list(getattr(query_plan, "should_have", None) or []),
        "can_boc": list(getattr(query_plan, "extract", None) or []),
        "san_pham_quan_tam": list(getattr(query_plan, "products", None) or []),
    }
    import json
    body = "\n\n".join(_dossier(i, c, query_plan) for i, c in enumerate(batch))
    return [
        {"role": "system", "content": SYSTEM},
        {"role": "user",
         "content": (f"NHU CẦU TÌM KIẾM:\n{json.dumps(need, ensure_ascii=False)}\n\n"
                     f"DANH SÁCH KHÁCH HÀNG:\n{body}")},
    ]


def _parse_batch(text, batch, query_plan):
    """JSON của model → `[Judgement]`, đã đối chiếu từng trích dẫn."""
    raw = extract_json(text) or {}
    rows = raw.get("ket_qua") if isinstance(raw, dict) else None
    if not isinstance(rows, list):
        return []

    by_id = {c.person_id: c for c in batch}
    wanted = [str(k).strip() for k in (getattr(query_plan, "extract", None) or [])]
    out = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            person_id = int(row.get("id"))
        except (TypeError, ValueError):
            continue
        candidate = by_id.get(person_id)
        if candidate is None:
            # Model bịa ra một id không có trong lô. Bỏ im lặng chứ không cố
            # đoán ý — đoán ở đây là gán bằng chứng của người này cho người kia.
            continue

        evidence, ages = [], []
        for item in (row.get("trich_dan") or []):
            if not isinstance(item, dict):
                continue
            passage = _passage_at(item.get("doan"), candidate)
            if passage is None:
                continue
            quote = _verify_quote(item.get("nguyen_van"), candidate)
            if quote is None:
                log.info("rb.answer.judge: bỏ trích dẫn không đối chiếu được (person=%s)",
                         person_id)
                continue
            age = passage.age_days()
            if age is not None:
                ages.append(age)
            evidence.append({"ref": passage.ref, "source": passage.source,
                             "quote": quote, "url": passage.url, "age_days": age})

        relevant = bool(row.get("thoa"))
        if relevant and not evidence:
            # "Thoả" mà không trích được câu nào là một khẳng định trần. Hạ
            # xuống không-thoả thay vì tin lời: cả chặng này sinh ra để không
            # còn khẳng định nào không có bằng chứng.
            log.info("rb.answer.judge: thoa=true nhưng không có trích dẫn hợp lệ "
                     "(person=%s) — hạ xuống false", person_id)
            relevant = False

        extracted = {}
        source = row.get("boc_duoc")
        if isinstance(source, dict):
            for key, value in source.items():
                name = str(key).strip()
                if value in (None, "", []) or not name:
                    continue
                # Chỉ giữ thuộc tính câu hỏi THẬT SỰ cần. Model hay bóc thêm cho
                # "đầy đủ", và mỗi trường thừa là một trường không ai kiểm.
                if wanted and name not in wanted:
                    continue
                extracted[name] = value

        need_kind = row.get("nhu_cau_hay_trang_thai")
        out.append(Judgement(
            person_id=person_id,
            name=candidate.name,
            relevant=relevant,
            confidence=_num(row.get("do_tin")),
            why=" ".join(str(row.get("vi_sao") or "").split())[:700],
            evidence=evidence,
            extracted=extracted,
            gap=" ".join(str(row.get("con_thieu") or "").split())[:300],
            declined=bool(row.get("da_tu_choi")),
            need_kind=(need_kind if need_kind in ("nhu_cau", "trang_thai", "khong_ro")
                       else "khong_ro"),
            freshest_days=min(ages) if ages else candidate.freshest_days(),
        ))
    return out


def _read_batch(query_plan, batch, caller):
    try:
        result = caller(_messages(query_plan, batch), task=TASK, temperature=0.1,
                        max_tokens=MAX_TOKENS)
    except Exception as exc:                       # noqa: BLE001
        log.warning("rb.answer.judge: lô %d hồ sơ đọc hỏng: %s", len(batch), exc)
        return None
    rows = _parse_batch(getattr(result, "text", ""), batch, query_plan)
    if not rows:
        log.warning("rb.answer.judge: lô %d hồ sơ không parse được kết quả nào",
                    len(batch))
        return None
    if len(rows) < len(batch):
        log.info("rb.answer.judge: lô trả %d/%d hồ sơ", len(rows), len(batch))
    return rows


def judge(query_plan, candidates, *, complete_fn=None, batch_size=BATCH):
    """`[Candidate]` → `JudgeReport`. Không bao giờ ném lỗi lên trên."""
    candidates = list(candidates)
    if not candidates:
        return JudgeReport([])

    caller = complete_fn or complete
    batches = [candidates[i:i + batch_size]
               for i in range(0, len(candidates), batch_size)]

    results = [None] * len(batches)
    if len(batches) == 1:
        results[0] = _read_batch(query_plan, batches[0], caller)
    else:
        from ai.telemetry import submit
        with ThreadPoolExecutor(max_workers=min(WORKERS, len(batches))) as workers:
            futures = {submit(workers, _read_batch, query_plan, b, caller): i
                       for i, b in enumerate(batches)}
            for future, index in futures.items():
                try:
                    results[index] = future.result()
                except Exception:                  # noqa: BLE001
                    log.exception("rb.answer.judge: lô %d hỏng", index)
                    results[index] = None
        # Luồng phụ dùng ORM qua `_verify_quote`/prompt guard; Django cấp kết nối
        # theo TỪNG luồng và không đóng thì mỗi lượt để lại vài kết nối treo.
        from django.db import connection
        connection.close()

    rows, failed = [], 0
    for result in results:
        if result is None:
            failed += 1
        else:
            rows.extend(result)
    if failed:
        log.warning("rb.answer.judge: %d/%d lô hỏng", failed, len(batches))
    return JudgeReport(rows, batches=len(batches), failed=failed)
