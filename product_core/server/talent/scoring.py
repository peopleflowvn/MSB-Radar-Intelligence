# -*- coding: utf-8 -*-
"""Chấm điểm mức phù hợp giữa ứng viên và nhu cầu tuyển dụng (Master Plan mục 23).

**Điểm số hoàn toàn TẤT ĐỊNH — LLM không tham gia.** Master Plan mục 23 nói rõ
"không để LLM tự tạo score hoàn toàn", và lý do rất cụ thể:

  • Cùng một câu hỏi phải cho cùng một thứ tự. LLM thì không.
  • Recruiter hỏi "vì sao người này xếp trên người kia" phải trả lời được bằng
    con số, không phải bằng "model thấy vậy".
  • Trọng số chỉnh được thì chỉnh được. Trực giác của model thì không.

LLM chỉ làm hai việc ở Phase 7: dịch câu hỏi thành tiêu chí (hiring_need.py), và
DIỄN GIẢI điểm số mà nó không tự tính (ai_search.py). Nhờ tách như vậy, phần giải
thích không thể mâu thuẫn với dữ liệu — nó chỉ được kể lại những FACT do bộ chấm
điểm sinh ra.

Mỗi chiều trả về (điểm 0..1, bằng chứng). Bằng chứng là thứ đi thẳng vào phần
FACT/UNKNOWN của lời giải thích (Master Plan mục 19.3).
"""
import re
from core.vn_locations import canonical_province
from django.utils import timezone

# Trọng số mặc định. Chỉnh được qua settings.TALENT_SCORING_WEIGHTS.
#
# Kỹ năng nặng nhất vì đó là thứ recruiter lọc trước tiên. "Độ tươi" có mặt vì
# người vừa nộp CV tuần trước đang tìm việc, người nộp ba năm trước thì chưa chắc —
# một hồ sơ khớp hoàn hảo nhưng đã nguội ba năm thì kém hữu ích hơn hồ sơ khớp
# vừa phải mà vừa mới nộp.
DEFAULT_WEIGHTS = {
    "skills": 0.30,
    "title": 0.18,
    "experience": 0.15,
    "location": 0.12,
    "industry": 0.08,
    "freshness": 0.10,
    "reachability": 0.07,
}

# Hồ sơ cũ hơn mốc này coi như đã nguội hoàn toàn về mặt "độ tươi".
FRESHNESS_HORIZON_DAYS = 365 * 3


class Dimension:
    """Kết quả chấm một chiều."""

    def __init__(self, key, score, weight, fact="", unknown=""):
        self.key = key
        self.score = score            # 0..1
        self.weight = weight
        self.fact = fact              # điều dữ liệu KHẲNG ĐỊNH
        self.unknown = unknown        # điều dữ liệu KHÔNG NÓI

    @property
    def contribution(self):
        return self.score * self.weight

    def as_dict(self):
        return {"key": self.key, "score": round(self.score, 3),
                "weight": self.weight, "fact": self.fact, "unknown": self.unknown}


def weights():
    from django.conf import settings
    configured = getattr(settings, "TALENT_SCORING_WEIGHTS", None) or {}
    merged = dict(DEFAULT_WEIGHTS)
    merged.update({k: float(v) for k, v in configured.items() if k in DEFAULT_WEIGHTS})
    return merged


def _person_cv_texts(person, profile):
    """Trích xuất toàn bộ văn bản từ TalentProfile và các tài liệu CV (Document.parsed_text)."""
    texts = []
    if profile:
        if profile.summary:
            texts.append(profile.summary)
        if profile.education:
            texts.append(profile.education)

    docs = getattr(person, "_prefetched_objects_cache", {}).get("documents")
    if docs is None and hasattr(person, "documents"):
        try:
            docs = list(person.documents.all())
        except Exception:
            docs = []
    if docs:
        for doc in docs:
            if doc.best_text:
                texts.append(doc.best_text)
    return texts


def score_person(person, criteria):
    """Chấm một ứng viên theo bộ tiêu chí. Trả dict kết quả đầy đủ.

    Chỉ chấm những chiều mà tiêu chí có nhắc tới. Chấm cả chiều không ai hỏi sẽ
    làm loãng điểm: tìm "biết SQL" mà điểm bị kéo xuống vì ứng viên không ở Hà Nội
    trong khi câu hỏi không hề nhắc tới nơi ở là sai.
    """
    profile = getattr(person, "talent_profile", None)
    active = weights()
    dimensions = []

    if criteria.get("skills"):
        dimensions.append(_skills(person, profile, criteria["skills"], active["skills"]))
    if criteria.get("title"):
        dimensions.append(_title(profile, criteria["title"], active["title"]))
    if criteria.get("min_years") is not None or criteria.get("max_years") is not None:
        dimensions.append(_experience(profile, criteria, active["experience"]))
    if criteria.get("location"):
        dimensions.append(_location(person, profile, criteria["location"],
                                    active["location"]))
    if criteria.get("company") or criteria.get("industry"):
        dimensions.append(_industry(person, profile,
                                    criteria.get("company") or criteria.get("industry"),
                                    active["industry"]))

    relevance_dims = list(dimensions)          # chỉ các chiều liên quan tới câu hỏi

    # Hai chiều dưới đây LUÔN được chấm dù không ai hỏi: một hồ sơ nguội ba năm
    # hoặc không có cách liên hệ thì recruiter không dùng được, bất kể khớp đến đâu.
    support_dims = [_freshness(profile, active["freshness"]),
                    _reachability(person, active["reachability"])]
    dimensions = relevance_dims + support_dims

    # Độ TƯƠI + LIÊN HỆ chỉ *điều chỉnh* một hồ sơ đã liên quan, KHÔNG được tự
    # nâng một hồ sơ không khớp gì lên trên ngưỡng. Nếu câu hỏi có tiêu chí nội
    # dung mà ứng viên không khớp chiều nào -> điểm liên quan = 0 -> tổng ~ 0.
    if relevance_dims:
        rw = sum(d.weight for d in relevance_dims) or 1.0
        relevance = sum(d.contribution for d in relevance_dims) / rw
        sw = sum(d.weight for d in support_dims) or 1.0
        support = sum(d.contribution for d in support_dims) / sw
        total = relevance * (0.75 + 0.25 * support)
    else:
        # Câu hỏi không có tiêu chí nội dung (vd "cho tôi xem hồ sơ mới") -> chỉ
        # còn độ tươi + khả năng liên hệ.
        sw = sum(d.weight for d in support_dims) or 1.0
        total = sum(d.contribution for d in support_dims) / sw

    return {
        "score": round(total, 4),
        "relevance": round(relevance, 4) if relevance_dims else None,
        "dimensions": [d.as_dict() for d in dimensions],
        "facts": [d.fact for d in dimensions if d.fact],
        "unknowns": [d.unknown for d in dimensions if d.unknown],
    }


# ---------------- từng chiều ----------------

def _skills(person, profile, wanted, weight):
    have = {s.lower() for s in (profile.skills if profile else [])}
    cv_texts = _person_cv_texts(person, profile)

    if not have and not cv_texts:
        return Dimension("skills", 0.0, weight,
                         unknown="Hồ sơ chưa ghi nhận kỹ năng hoặc tài liệu CV.")

    matched = []
    matched_from_cv = []
    for w in wanted:
        if _skill_present(w, have):
            matched.append(w)
        elif _skill_in_texts(w, cv_texts):
            matched.append(w)
            matched_from_cv.append(w)

    missing = [w for w in wanted if w not in matched]
    score = len(matched) / len(wanted) if wanted else 0.0

    if matched:
        if matched_from_cv:
            fact = f"Có {len(matched)}/{len(wanted)} kỹ năng yêu cầu (đối chiếu hồ sơ & CV): {', '.join(matched)}."
        else:
            fact = f"Có {len(matched)}/{len(wanted)} kỹ năng yêu cầu: {', '.join(matched)}."
    else:
        fact = f"Không thấy kỹ năng nào trong: {', '.join(wanted)}."
    unknown = f"Hồ sơ không nhắc tới: {', '.join(missing)}." if missing else ""
    return Dimension("skills", score, weight, fact, unknown)


def _skill_in_texts(wanted, texts):
    """Tìm kỹ năng trong văn bản CV thô hoặc tóm tắt."""
    if not wanted or not texts:
        return False
    needle = wanted.strip().lower()
    pattern = r"(?<!\w)" + re.escape(needle) + r"(?!\w)"
    for text in texts:
        if not text:
            continue
        # Kiểm tra match từ chính xác trước, hoặc chuỗi con nếu là từ ghép
        if re.search(pattern, text, re.IGNORECASE) or (len(needle) > 3 and needle in text.lower()):
            return True
    return False


def _skill_present(wanted, have):
    """Khớp kỹ năng theo cả bao hàm hai chiều.

    'SQL' phải khớp 'T-SQL' và 'SQL Server'; 'Power BI' phải khớp 'PowerBI'.
    Đây là chỗ khớp lỏng có lợi — kỹ năng được gõ tự do trong CV nên biến thể
    rất nhiều, và bỏ sót gây hại hơn khớp rộng.
    """
    needle = wanted.lower().replace(" ", "")
    for skill in have:
        flat = skill.replace(" ", "")
        if needle in flat or flat in needle:
            return True
    return False


def _title(profile, wanted, weight):
    current = (profile.current_title if profile else "") or ""
    if not current:
        return Dimension("title", 0.0, weight,
                         unknown="Hồ sơ chưa có chức danh.")

    a, b = current.lower(), wanted.lower()
    if b in a or a in b:
        return Dimension("title", 1.0, weight, f"Chức danh hiện tại: {current}.")

    # Bao hàm chuỗi đã loại xong. Phần còn lại là câu hỏi về NGHĨA — "BI
    # Developer" có gần "Data Analyst" không — mà so khớp chuỗi trả lời sai đến
    # mức người dùng nhìn là biết. Hỏi bộ nhớ độ gần chức danh trước.
    known = _semantic_title(wanted, current)
    if known is not None:
        return Dimension("title", known.score, weight,
                         fact=f"{current}: {known.reason}" if known.reason
                         else f"Chức danh {current} gần với {wanted}.")

    # Deterministic bilingual bridge: only cross-language pairs use the local
    # ontology. English-English job similarity still uses the curated LLM cache
    # above, avoiding broad assumptions such as Data Engineer == Data Analyst.
    if _has_vietnamese(wanted) != _has_vietnamese(current):
        from .semantic_index import similarity
        indexed_similarity = similarity(wanted, current)
        if indexed_similarity >= 0.4:
            return Dimension("title", indexed_similarity, weight,
                             f"{current}: tương đồng công việc/ngôn ngữ với {wanted}.")

    # Chưa chấm được (chưa gọi `semantic.warm`, hoặc LLM đang bận). Lùi về khớp
    # theo từ, và NÓI RÕ là chỉ so chữ — kẻo người đọc tưởng hệ thống đã hiểu
    # nghề nghiệp mà vẫn cho điểm thấp.
    #
    # Bỏ dấu câu trước khi tách từ: tiêu đề JD hay có dạng "Chuyên viên Phân
    # tích Dữ liệu (Data Analyst)", và nếu không bỏ ngoặc thì "analyst)" không
    # khớp "analyst" — cả danh sách tụt về 0 vì một dấu ngoặc.
    words_a, words_b = _words(a), _words(b)
    overlap = len(words_a & words_b) / max(1, len(words_b))
    fact = (f"Chức danh {current} khớp một phần với {wanted} (mới so chữ)."
            if overlap else "")
    unknown = ("" if overlap
               else f"Chức danh hiện tại là {current}; chưa đối chiếu được với "
                    f"{wanted} về mặt công việc.")
    return Dimension("title", overlap, weight, fact, unknown)


def _words(text):
    """Tách từ sau khi bỏ dấu câu và bỏ những từ chung chung không mang nghĩa."""
    parts = re.split(r"[^\w]+", text, flags=re.UNICODE)
    # "chuyên viên", "nhân viên", "senior"… có ở gần như mọi chức danh nên không
    # phân biệt được gì; giữ lại chỉ làm loãng tỉ lệ trùng.
    stop = {"", "senior", "junior", "lead", "chuyên", "viên", "nhân", "cán", "bộ"}
    return {p for p in parts if p not in stop}


def _has_vietnamese(text):
    return bool(re.search(r"[àáảãạăằắẳẵặâầấẩẫậđèéẻẽẹêềếểễệìíỉĩịòóỏõọôồốổỗộơờớởỡợ"
                          r"ùúủũụưừứửữựỳýỷỹỵ]", str(text or "").casefold()))


def _semantic_title(wanted, current):
    """Đọc bộ nhớ độ gần chức danh. Không có thì trả None, không tự gọi LLM.

    Cố ý không gọi LLM ở đây: hàm này chạy trong vòng lặp chấm từng người, và
    gọi mô hình bên trong vòng lặp là cách chắc chắn nhất để một lượt tìm kiếm
    biến thành bốn mươi lượt gọi. Việc chấm trước nằm ở `semantic.warm()`.
    """
    try:
        from . import semantic
        return semantic.lookup(wanted, current)
    except Exception:                          # noqa: BLE001
        # Chưa migrate, hoặc chạy ngoài Django. Chấm điểm không được phép hỏng
        # vì một tiện ích phụ.
        return None


def _experience(profile, criteria, weight):
    years = profile.years_experience if profile else None
    if years is None:
        return Dimension("experience", 0.0, weight,
                         unknown="Hồ sơ chưa ghi số năm kinh nghiệm.")

    low = criteria.get("min_years")
    high = criteria.get("max_years")

    if low is not None and years < low:
        # Giảm dần thay vì loại thẳng: thiếu nửa năm khác hẳn thiếu năm năm, và
        # recruiter thường vẫn muốn xem người sát ngưỡng.
        score = max(0.0, 1 - (low - years) / max(low, 1))
        return Dimension("experience", score, weight,
                         f"Có {years:g} năm kinh nghiệm, yêu cầu từ {low:g} năm.")
    if high is not None and years > high:
        score = max(0.0, 1 - (years - high) / max(high, 1))
        return Dimension("experience", score, weight,
                         f"Có {years:g} năm kinh nghiệm, yêu cầu đến {high:g} năm.")
    return Dimension("experience", 1.0, weight,
                     f"Có {years:g} năm kinh nghiệm, đúng khoảng yêu cầu.")


def _location(person, profile, wanted, weight):
    place = (profile.location if profile else "") or person.location or ""
    if not place:
        return Dimension("location", 0.0, weight, unknown="Hồ sơ chưa có nơi ở.")
    # Chuẩn hoá bí danh tỉnh/thành trước khi so ("Sài Gòn" == "Hồ Chí Minh") —
    # phải khớp với đúng cách bộ lọc tìm kiếm đối chiếu địa danh
    # (talent/search.py, core/vn_locations.py). Thiếu bước này thì một người
    # ĐÃ được tìm ra nhờ khớp địa danh vẫn có thể bị chấm 0 điểm ở đúng chiều
    # lẽ ra phải cho điểm tối đa, và lời giải thích tự mâu thuẫn với kết quả.
    if (canonical_province(wanted).lower() == canonical_province(place).lower()
            or wanted.lower() in place.lower() or place.lower() in wanted.lower()):
        return Dimension("location", 1.0, weight, f"Ở {place}.")
    # Khác vùng: không loại thẳng (điểm 0) — recruiter thường vẫn muốn xem người
    # sát nhu cầu, có thể chấp nhận đổi chỗ / làm từ xa. Nói rõ điểm lệch.
    return Dimension("location", 0.15, weight,
                     f"Ở {place}, khác {wanted} — cân nhắc nếu chấp nhận đổi vùng "
                     "hoặc làm từ xa.")


def _industry(person, profile, wanted, weight):
    companies = list(profile.industries or []) if profile else []
    current = (profile.current_company if profile else "") or ""
    cv_texts = _person_cv_texts(person, profile)

    haystack = " | ".join([current] + companies).lower()
    if not haystack.strip(" |") and not cv_texts:
        return Dimension("industry", 0.0, weight,
                         unknown="Hồ sơ chưa ghi nơi từng làm việc.")

    wanted_lower = wanted.lower().strip()
    if wanted_lower and wanted_lower in haystack:
        return Dimension("industry", 1.0, weight,
                         f"Từng làm tại: {current or companies[0]}.")

    # Kiểm tra trong văn bản chi tiết CV
    if wanted_lower and cv_texts:
        for text in cv_texts:
            if wanted_lower in text.lower():
                return Dimension("industry", 1.0, weight,
                                 f"Có kinh nghiệm/dự án trong lĩnh vực {wanted} (ghi nhận trong CV).")

    return Dimension("industry", 0.0, weight,
                     f"Nơi từng làm: {current or ', '.join(companies[:3]) if companies else '(chưa rõ)'}.",
                     f"Không thấy dấu hiệu từng làm trong lĩnh vực {wanted}.")


def _freshness(profile, weight):
    last = profile.last_source_at if profile else None
    if last is None:
        return Dimension("freshness", 0.0, weight,
                         unknown="Chưa rõ lần cuối ứng viên có hoạt động.")
    days = (timezone.now() - last).days
    score = max(0.0, 1 - days / FRESHNESS_HORIZON_DAYS)
    if days <= 30:
        fact = f"Vừa có hồ sơ mới {days} ngày trước."
    elif days <= 365:
        fact = f"Hồ sơ gần nhất cách đây {days // 30} tháng."
    else:
        fact = f"Hồ sơ gần nhất cách đây {days // 365} năm."
    return Dimension("freshness", score, weight, fact)


def _reachability(person, weight):
    """Không liên hệ được thì không dùng được, dù khớp đến đâu (Master Plan mục 23)."""
    channels = []
    if person.primary_email:
        channels.append("email")
    if person.primary_phone:
        channels.append("điện thoại")
    if not channels:
        return Dimension("reachability", 0.0, weight,
                         unknown="Không có email lẫn điện thoại để liên hệ.")
    score = 1.0 if len(channels) == 2 else 0.6
    return Dimension("reachability", score, weight,
                     f"Liên hệ được qua {' và '.join(channels)}.")
