# -*- coding: utf-8 -*-
"""Khớp `must_have` với TRƯỜNG CÓ CẤU TRÚC trên TOÀN KHO — không phải top-N.

Vì sao cần lớp này, dù đã có ② (vector + FTS):

    Truy hồi ngữ nghĩa là xấp xỉ. "phải biết tiếng Anh" nhúng thành vector thì
    kéo về CV có chữ GẦN NGHĨA "tiếng Anh" — bỏ sót người chỉ ghi "English",
    "TOEIC 850", hay liệt kê trong bảng kỹ năng mà không viết thành câu. Và
    ngay cả khi tìm đúng, RRF vẫn có thể xếp người đó dưới hạng 60 (`POOL`) nếu
    câu hỏi có nhiều tiêu chí khác cạnh tranh điểm.

    `must_have` theo đúng nghĩa của ① (`plan.py`): "BẮT BUỘC, không thoả thì
    loại". Đó là một phép LỌC tất định, không phải một tín hiệu xếp hạng mờ.
    Bây giờ `ExtractedFact`/`TalentProfile` đã có dữ liệu (nhờ sửa
    `intel/extraction.py` 05/09), lọc được thật trên TOÀN kho bằng SQL — vài
    chục mili-giây, không LLM, không giới hạn ở pool.

Chỉ áp cho `must_have` — `should_have` cố ý bỏ qua vì nó là "ưu tiên", ép cứng
sẽ loại oan người thiếu MỘT tiêu chí phụ nhưng vẫn đáng xem. NGOẠI LỆ DUY NHẤT:
ngưỡng số năm kinh nghiệm (xem `_YEARS_ALSO_FROM_SHOULD_HAVE` bên dưới) — đây
không phải "ưu tiên mềm" như kỹ năng/thành phố, mà là một phép so sánh số học
tất định giống hệt dù nằm ở must_have hay should_have; đo trên production
05/09 thấy plan.py (LLM, "must_have... Rất ít") xếp CÙNG một câu hỏi
("trên 3 năm kinh nghiệm ngành ngân hàng") vào should_have ở một lượt hỏi và
must_have ở lượt khác — bảo đảm "rà soát toàn kho" của lớp này không thể phụ
thuộc vào một lựa chọn không ổn định của LLM cho đúng loại tiêu chí này.

Đây là LỌC BỔ SUNG, không thay ②: câu hỏi không khớp được field nào (must_have
rỗng hoặc toàn câu chữ tự do không quy về được trường có cấu trúc) thì trả
`None` — im lặng nhường lại cho đường ngữ nghĩa như cũ, không đoán bừa.
"""
from __future__ import annotations

import re
import unicodedata

#: Trần số người ghim thêm qua đường này. `retrieve()` đọc TẤT CẢ `pinned_ids`
#: bằng LLM ở ③ bất kể `POOL` — must_have khớp cấu trúc mà có SẴN hàng trăm
#: người (ví dụ khi backfill xong, "biết tiếng Anh" khớp đa số kho) thì vẫn
#: phải cắt, nếu không ③ đọc cả trăm hồ sơ cho một câu hỏi, phá đúng ngân sách
#: thời gian mà cả phiên này đang cố giữ (~15-40s/câu). Khớp NHIỀU người là
#: tin tốt (đủ ứng viên) — không cần đọc HẾT để biết điều đó.
MAX_STRUCTURED_PINS = 40

#: Trường có cấu trúc, KHÔNG nhạy cảm, đủ dữ liệu sau khi bật extraction 05/09.
#: `merge` = mảng (khớp có mặt trong danh sách); `text` = so khớp chuỗi đơn.
_MERGE_FIELDS = ("skills", "industries", "languages", "certifications")
_TEXT_FIELDS = ("city", "current_title", "current_company", "seniority",
                "education_level", "university", "major")

#: Câu nói tới NƠI LÀM VIỆC MONG MUỐN thì đối chiếu thẳng
#: `TalentProfile.desired_location`/`.location` (Edge đã chuẩn hoá về tên
#: tỉnh/thành chuẩn khi đồng bộ - xem edge/app/geo.py).
_LOCATION_HINTS = ("lam viec", "lam o", "lam tai", "muon lam", "khu vuc",
                   "dia diem", "dia ban", "song o", "o tai", "muon vao",
                   "work in", "based in", "location", "chuyen den", "di chuyen")
#: Tên gọi khác của vài thành phố lớn (đã bỏ dấu) -> tên chuẩn (đã bỏ dấu) mà
#: Edge lưu. Chỉ cần vài cái phổ biến nhất; phần còn lại khớp thẳng theo tên.
_CITY_ALIASES = {
    "sai gon": "ho chi minh", "saigon": "ho chi minh", "hcm": "ho chi minh",
    "tphcm": "ho chi minh", "tp hcm": "ho chi minh", "hcmc": "ho chi minh",
    "sg": "ho chi minh", "ha noi": "ha noi", "hn": "ha noi", "hanoi": "ha noi",
    "da nang": "da nang", "danang": "da nang", "vung tau": "ba ria - vung tau",
    "nha trang": "khanh hoa", "hue": "thua thien hue",
}

_YEARS_RE = re.compile(
    r"(?:tren|hon|it nhat|toi thieu|>=?|từ)?\s*(\d+(?:[.,]\d+)?)\s*"
    r"nam(?:\s*kinh\s*nghiem)?", re.I)


def _fold(text):
    return "".join(c for c in unicodedata.normalize("NFD", str(text or "").lower())
                   if unicodedata.category(c) != "Mn")


def _tokens(text):
    return re.findall(r"[a-z0-9+#.]+", _fold(text))


#: Từ đệm trong câu điều kiện ("biết Python", "có kinh nghiệm về SQL") — không
#: mang nghĩa để khớp với một giá trị trường như "Python".
_FILLER = frozenset("""biet thanh thao su dung co kinh nghiem ve ky nang lam o tai
va hoac voi trong nganh linh vuc vi tri chuc danh la mot the know using with
experience in skill skills of and or""".split())


def _phrase_tokens(phrase):
    tokens = _tokens(phrase)
    core = [t for t in tokens if t not in _FILLER]
    return core or tokens


def _contains_run(haystack, needle):
    """`needle` xuất hiện NGUYÊN CỤM TỪ trong `haystack` (theo từ, không theo ký tự)."""
    n = len(needle)
    return n > 0 and any(haystack[i:i + n] == needle for i in range(len(haystack) - n + 1))


def value_matches(value, phrase):
    """Giá trị trường có cấu trúc có khớp câu điều kiện không — theo TỪ.

    Bản cũ so chuỗi con hai chiều (`cand in folded or folded in cand`), nên:
      * cấp bậc "senior" khớp điều kiện "Senior Data Analyst" → MỌI người có
        cấp bậc senior bị ghim vào đọc (production 19/09: 40 chuyên viên ngân
        hàng chiếm chỗ của người làm phân tích dữ liệu);
      * kỹ năng một chữ ("R", "C") khớp bất kỳ câu nào có chữ cái đó.
    Nay: câu điều kiện nằm trọn trong giá trị ("data analyst" ⊂ "senior data
    analyst") thì khớp; giá trị nằm trong câu thì chỉ khớp khi nó phủ phần lớn
    câu (≥ 60% số từ, và ≥ 2 từ nếu câu dài hơn một từ).
    """
    v, p = _tokens(value), _phrase_tokens(phrase)
    if not v or not p:
        return False
    if _contains_run(v, p):
        return True
    if _contains_run(p, v):
        return len(v) >= max(1 if len(p) == 1 else 2, -(-len(p) * 3 // 5))
    return False


def _years_experience_threshold(phrase):
    """"trên 3 năm kinh nghiệm" → 3.0, hoặc None nếu câu không nói số năm KN."""
    folded = _fold(phrase)
    if "kinh nghiem" not in folded and "nam" not in folded:
        return None
    m = _YEARS_RE.search(folded)
    return float(m.group(1).replace(",", ".")) if m else None


def _match_ids_for_phrase(phrase, universe_ids):
    """`set[person_id]` khớp CỨNG một điều kiện `must_have`, hoặc `None` nếu
    câu chữ không quy về được trường có cấu trúc nào (→ nhường ② lo)."""
    from django.db.models import Q
    from intel.models import ExtractedFact
    from talent.models import TalentProfile

    folded = _fold(phrase)
    if not folded.strip():
        return None

    years = _years_experience_threshold(phrase)
    if years is not None:
        # Hai nguồn, hợp lại: `TalentProfile.years_experience` (Edge/derive)
        # VÀ `ExtractedFact` field="years_experience" (AI mới bóc, chưa chắc
        # đã đồng bộ ngược vào TalentProfile). Đo trên production 05/09: bỏ
        # nguồn AI thì "trên 3 năm KN" ra 0 người dù ExtractedFact đã có dữ
        # liệu — coverage thấp bị hiểu nhầm thành "kho không có ai".
        from_profile = set(TalentProfile.objects
                          .filter(person_id__in=universe_ids,
                                  years_experience__gte=years)
                          .values_list("person_id", flat=True))
        from_facts = set()
        rows = (ExtractedFact.objects
                .filter(person_id__in=universe_ids, field="years_experience",
                        is_current=True)
                .exclude(status=ExtractedFact.STATUS_REJECTED)
                .values_list("person_id", "normalized_value", "raw_value"))
        for pid, norm, raw in rows:
            m = re.search(r"\d+(?:[.,]\d+)?", str(norm or raw or ""))
            if m and float(m.group(0).replace(",", ".")) >= years:
                from_facts.add(pid)
        return from_profile | from_facts

    # Nơi làm việc mong muốn: chỉ xét khi câu có tín hiệu địa điểm, để không
    # nhầm "python developer" thành một địa danh. Đối chiếu cả `desired_location`
    # và `location` (nơi ở) - "muốn làm ở X" cũng thường trùng nơi ở.
    if any(h in folded for h in _LOCATION_HINTS):
        needle = folded
        for alias, canon in _CITY_ALIASES.items():
            if alias in needle:
                needle = needle.replace(alias, canon)
        hits = set()
        rows = (TalentProfile.objects
                .filter(person_id__in=universe_ids)
                .filter(Q(desired_location__gt="") | Q(location__gt=""))
                .values_list("person_id", "desired_location", "location"))
        for pid, desired, loc in rows:
            parts = [_fold(p) for value in (desired, loc)
                     for p in re.split(r"[,;/]", str(value or ""))]
            if any(p and (p in needle or needle in p) for p in parts):
                hits.add(pid)
        if hits:
            return hits

    # Merge fields (mảng): khớp có CHỨA cụm từ, không cần khớp cả cụm.
    for field in _MERGE_FIELDS:
        if _phrase_hints_field(folded, field):
            ids = set(ExtractedFact.objects
                      .filter(person_id__in=universe_ids, field=field,
                              is_current=True)
                      .exclude(status=ExtractedFact.STATUS_REJECTED)
                      .values_list("person_id", "normalized_value", "raw_value"))
            return {pid for pid, norm, raw in ids
                    if value_matches(norm, phrase) or value_matches(raw, phrase)}

    # Trường "latest" (chuỗi đơn): khớp lỏng hai chiều.
    hits = set()
    rows = (ExtractedFact.objects
            .filter(person_id__in=universe_ids, field__in=_TEXT_FIELDS,
                    is_current=True)
            .exclude(status=ExtractedFact.STATUS_REJECTED)
            .values_list("person_id", "normalized_value", "raw_value"))
    for pid, norm, raw in rows:
        if value_matches(norm or raw, phrase):
            hits.add(pid)
    return hits or None


def _phrase_hints_field(folded_phrase, field):
    """Câu có nhắc tới ĐÚNG LOẠI trường này không (kỹ năng khác ngôn ngữ khác
    ngành) — tránh so một câu về "tiếng Anh" với danh sách chứng chỉ."""
    hints = {
        "skills": ("ky nang", "biet", "thanh thao", "su dung"),
        "languages": ("tieng anh", "tieng nhat", "tieng trung", "tieng han",
                      "english", "ngoai ngu", "ielts", "toeic"),
        "industries": ("nganh", "linh vuc", "industry"),
        "certifications": ("chung chi", "certificate", "chung nhan"),
    }
    return any(h in folded_phrase for h in hints.get(field, ()))


def must_have_pins(query_plan):
    """`set[person_id]` ĐÁNG GHIM vì khớp cứng ít nhất một `must_have` có cấu
    trúc, hoặc `None` nếu không câu nào quy được về trường có cấu trúc.

    CỐ Ý là GHIM (đảm bảo có mặt để ③ xét), KHÔNG PHẢI LỌC LOẠI TRỪ. Backfill
    05/09 mới xong 6/798 người — nếu dùng làm bộ lọc "phải có mặt trong
    ExtractedFact mới được xét" thì loại oan gần hết kho vì THIẾU DỮ LIỆU bị
    hiểu nhầm thành THIẾU THUỘC TÍNH. Khi coverage đủ cao (theo dõi qua
    `intel/extraction.py::coverage_summary`), có thể siết lại thành bộ lọc
    thật — chưa làm bây giờ để không kéo tụt độ đầy đủ đang có.

    `must_have` có NHIỀU điều kiện thì hợp UNION theo từng điều kiện quy được
    (không giao nhau): ③ vẫn tự đối chiếu ĐỦ mọi `must_have` cho người được
    chọn cuối, đây chỉ là đảm bảo họ KHÔNG bị pool ngữ nghĩa bỏ sót từ vòng
    ngoài.

    Ngưỡng số năm KN trong `should_have` cũng được soi (không chỉ `must_have`)
    — xem lý do ở docstring đầu module.
    """
    from people.models import Person

    must = [m for m in (getattr(query_plan, "must_have", None) or []) if str(m).strip()]
    # Ngưỡng số năm KN: soi thêm cả should_have (xem lý do ở docstring module).
    # Chỉ riêng mẫu này — KHÔNG mở rộng sang skills/thành phố/... của should_have.
    should = [s for s in (getattr(query_plan, "should_have", None) or []) if str(s).strip()]
    years_from_should = [s for s in should if _years_experience_threshold(s) is not None]
    if not must and not years_from_should:
        return None

    universe = list(Person.applicants().values_list("id", flat=True))
    scores = {}
    for phrase in must + years_from_should:
        ids = _match_ids_for_phrase(phrase, universe)
        if ids is None:
            continue                      # câu này không quy được — bỏ qua, không đoán
        for person_id in ids:
            scores[person_id] = scores.get(person_id, 0) + 1
    if not scores:
        return None

    # Rank by number of requested structured conditions matched, then by the
    # amount of searchable evidence available. Person id is only a final stable
    # tie-breaker. The old set(sorted(ids)[:40]) favored early imports and could
    # make the deep-read group look random to recruiters.
    from talent.models import PersonSearchDocument
    evidence_size = {pid: len(content or "") for pid, content in
                     PersonSearchDocument.objects.filter(person_id__in=scores)
                     .values_list("person_id", "content")}
    ranked = sorted(scores, key=lambda pid: (-scores[pid], -evidence_size.get(pid, 0), pid))
    return ranked[:MAX_STRUCTURED_PINS]


#: Số yêu cầu tối đa một lần đối chiếu — đủ cho một JD thật, không để một câu
#: lệnh kéo theo hàng chục truy vấn CSDL.
MAX_REQUIREMENTS = 12


def match_requirements(person_id, requirements):
    """Từng câu trong `requirements` (một yêu cầu vị trí/JD) → MỘT người này có
    khớp không. Dùng đúng luật khớp trường có cấu trúc của `must_have_pins` —
    không viết luật khớp thứ hai cho cùng một việc "đối chiếu must_have".

    Trả `[{"requirement", "status"}]`, `status` một trong:

        "satisfied"  khớp được trên trường có cấu trúc.
        "missing"    quy về được trường có cấu trúc, nhưng người này KHÔNG khớp.
        "unknown"    câu không quy về được trường có cấu trúc nào (giống hệt lúc
                     `must_have_pins` trả `None` cho toàn kho) — KHÔNG phải
                     "missing". Người gọi phải nói rõ đây là "chưa xác định
                     được", không phải "ứng viên không có".

    Chỉ xét MỘT người (`universe_ids=[person_id]`) nên không cần quét toàn kho.
    """
    universe = [person_id]
    rows = []
    for requirement in requirements[:MAX_REQUIREMENTS]:
        text = str(requirement).strip()
        if not text:
            continue
        ids = _match_ids_for_phrase(text, universe)
        if ids is None:
            status = "unknown"
        elif person_id in ids:
            status = "satisfied"
        else:
            status = "missing"
        rows.append({"requirement": text, "status": status})
    return rows
