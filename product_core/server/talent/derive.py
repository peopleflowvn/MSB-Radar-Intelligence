# -*- coding: utf-8 -*-
"""Suy TalentProfile ra từ các SourceRecord đã đồng bộ.

Một người có thể có 5 lượt ứng tuyển ở 3 nguồn, trải dài 3 năm. Bài toán ở đây là gộp
chúng thành một góc nhìn tuyển dụng duy nhất.

Hai quy tắc chi phối:

1. **Bản ghi mới nhất thắng.** CV nộp tháng trước phản ánh hiện tại tốt hơn CV ba năm
   trước. Trừ khi trường đó trống — lúc đó lấy giá trị gần nhất còn có.

2. **Con người thắng máy.** Trường nào recruiter đã sửa tay thì nằm trong
   `curated_fields` và không bao giờ bị ghi đè. Recruiter đã nói chuyện với ứng viên
   biết rõ hơn bất kỳ CV nào.

Suy lại được bất cứ lúc nào và cho cùng kết quả — nên sửa quy tắc rồi chạy lại trên
toàn bộ dữ liệu là việc an toàn.
"""
import logging
import re

from django.utils import timezone
from people.models import Person, Signal

from .models import TalentProfile

log = logging.getLogger(__name__)

# Trường trên TalentProfile ← khoá trong payload của SourceRecord.
SIMPLE_FIELDS = {
    "current_title": ("current_title", "position"),
    "current_company": ("last_company",),
    "education": ("education",),
    "expected_salary": ("expected_salary",),
    "current_salary": ("current_salary",),
    "location": ("city", "address"),
    "seniority": ("job_level",),
    # Trường "mong muốn" chỉ có trên trang chi tiết ứng viên của nguồn, Edge bóc
    # riêng từng site (xem edge/KINH_NGHIEM_TRIEN_KHAI_CAC_KENH_TUYEN_DUNG.md
    # mục 41). Chưa có = để trống, không đoán.
    "desired_location": ("desired_location",),
    "desired_level": ("desired_level",),
    "desired_position": ("desired_position",),
    "job_type": ("job_type",),
    "foreign_language": ("foreign_language",),
    "marital_status": ("marital_status",),
}

# Tách kỹ năng: dấu phẩy, chấm phẩy, gạch đứng, xuống dòng. KHÔNG tách theo khoảng
# trắng — "Machine Learning" là một kỹ năng, không phải hai.
_SKILL_SPLIT = re.compile(r"[,;|/\n]+")

# Lấy số năm kinh nghiệm từ chuỗi tự do: "3 năm", "5 years", "hơn 2 năm".
_YEARS = re.compile(r"(\d+(?:[.,]\d+)?)\s*(?:năm|nam|year|yr)", re.IGNORECASE)


def parse_skills(value):
    """Chuỗi kỹ năng thô → danh sách đã chuẩn hoá, giữ nguyên thứ tự, bỏ trùng."""
    if isinstance(value, (list, tuple)):
        parts = [str(item) for item in value]
    else:
        parts = _SKILL_SPLIT.split(str(value or ""))

    seen, result = set(), []
    for part in parts:
        name = " ".join(str(part).split())[:60]
        if not name:
            continue
        key = name.lower()
        if key not in seen:
            seen.add(key)
            result.append(name)
    return result


def parse_years(value):
    """Số năm kinh nghiệm từ chuỗi tự do. None nếu không đọc được.

    Chặn trên 60 năm: dữ liệu CV có những giá trị vô lý (ai đó gõ nhầm năm sinh vào ô
    kinh nghiệm), và để lọt thì bộ lọc "trên 10 năm kinh nghiệm" sẽ đầy rác.
    """
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        years = float(value)
    else:
        text = str(value)
        match = _YEARS.search(text)
        if match:
            years = float(match.group(1).replace(",", "."))
        else:
            digits = re.search(r"\d+(?:[.,]\d+)?", text)
            if not digits:
                return None
            years = float(digits.group(0).replace(",", "."))
    return years if 0 <= years <= 60 else None


def _ordered_records(person):
    """SourceRecord của một người, mới nhất trước.

    Sắp theo applied_ts trong payload chứ không theo lúc Hub nhận: một CV cũ tải về
    hôm nay vẫn là CV cũ, và đó chính là lỗi dễ mắc nhất ở đây.
    """
    records = list(person.source_records.all())
    return sorted(
        records,
        key=lambda r: (str(r.payload.get("applied_ts") or ""),
                       r.last_seen_at.isoformat() if r.last_seen_at else ""),
        reverse=True)


def derive(person, save=True):
    """Dựng lại TalentProfile từ các SourceRecord. Trả về profile."""
    profile, _created = TalentProfile.objects.get_or_create(person=person)
    records = _ordered_records(person)
    if not records:
        return profile

    payloads = [r.payload or {} for r in records]

    for field, sources in SIMPLE_FIELDS.items():
        if profile.is_curated(field):
            continue
        value = _first_value(payloads, sources)
        if value:
            # Cắt theo đúng max_length của cột (Postgres từ chối chuỗi quá dài) -
            # các trường "mong muốn"/"tình trạng hôn nhân" ngắn hơn 200.
            limit = TalentProfile._meta.get_field(field).max_length or 200
            setattr(profile, field, value[:limit])

    if not profile.is_curated("years_experience"):
        for payload in payloads:
            years = parse_years(payload.get("years_experience") or payload.get("experience"))
            if years is not None:
                profile.years_experience = years
                break

    if not profile.is_curated("skills"):
        # Kỹ năng GỘP qua mọi bản ghi chứ không chỉ lấy bản mới nhất: một người
        # từng dùng SQL ba năm trước thì vẫn biết SQL, dù CV mới không nhắc lại.
        merged, seen = [], set()
        for payload in payloads:
            for skill in parse_skills(payload.get("skills")):
                key = skill.lower()
                if key not in seen:
                    seen.add(key)
                    merged.append(skill)
        if merged:
            profile.skills = merged[:100]

    if not profile.is_curated("industries"):
        companies, seen = [], set()
        for payload in payloads:
            name = str(payload.get("last_company") or "").strip()
            if name and name.lower() not in seen:
                seen.add(name.lower())
                companies.append(name[:120])
        if companies:
            profile.industries = companies[:20]

    newest = payloads[0].get("applied_ts") or ""
    profile.last_source_at = _parse_timestamp(newest) or records[0].last_seen_at
    profile.derived_at = timezone.now()

    if save:
        profile.save()
        try:
            _detect_job_change(person, payloads)
        except Exception:                          # noqa: BLE001
            # Suy hồ sơ đã xong và đã ghi; một lỗi ở nhánh sinh tín hiệu không
            # được kéo bước đó về 'pending' rồi lặp lại vô hạn.
            log.exception("Không dò được đổi việc cho Person %s", person.pk)
    return profile


# Từ khoá rác trong ô công ty — không phải tên nhà tuyển dụng thật, đừng coi là
# "đổi việc" khi một bên là placeholder.
_COMPANY_NOISE = {"", "-", "n/a", "na", "chưa cập nhật", "không có", "đang cập nhật",
                  "updating", "khác", "other", "công ty tnhh", "cong ty"}


def _detect_job_change(person, payloads):
    """Sinh Signal khi ứng viên đổi công ty giữa hai lượt ứng tuyển.

    Trước đây KHÔNG có gì sinh Signal từ chính luồng đồng bộ Edge → Hub (chỉ
    mạng xã hội và người tham chiếu). Một người vừa chuyển ngân hàng là tín hiệu
    bán hàng mạnh (đổi tài khoản lương, chuyển địa bàn) — `route_signal` sẽ chấm
    và lọc, ở đây chỉ ghi nhận + gắn provenance.

    `payloads` đã sắp mới nhất trước. So công ty của bản mới nhất với bản gần
    nhất có công ty KHÁC và không rỗng. Idempotent: khoá get_or_create gồm
    `observed_at` = mốc ứng tuyển của bản mới, nên chạy lại `derive()` không đẻ
    thêm Signal; chỉ lượt ứng tuyển mới hơn với công ty khác mới tạo cái mới.
    """
    def company(payload):
        return str(payload.get("last_company") or payload.get("current_company")
                   or "").strip()

    latest = company(payloads[0])
    if latest.lower() in _COMPANY_NOISE:
        return
    previous = ""
    for payload in payloads[1:]:
        name = company(payload)
        if name and name.lower() not in _COMPANY_NOISE:
            previous = name
            break
    if not previous or previous.lower() == latest.lower():
        return

    observed = _parse_timestamp(payloads[0].get("applied_ts") or "") or timezone.now()
    title = str(payloads[0].get("current_title") or payloads[0].get("position") or "")
    try:
        signal, created = Signal.objects.get_or_create(
            person=person, domain=Signal.DOMAIN_RB, signal_type="job_change",
            source="edge_sync", observed_at=observed,
            defaults={"confidence": 0.6,
                      "evidence": {
                          "tu_cong_ty": previous, "sang_cong_ty": latest,
                          "chuc_danh_moi": title,
                          "nguon": "so sánh hai lượt ứng tuyển gần nhất",
                          # `reason`/`role` là các key `rb.suggestions.from_signal`
                          # đọc để suy sản phẩm — không có thì Signal chỉ hiện ở
                          # Person 360 chứ không sinh đề xuất nào. Câu này khớp
                          # hint của PRODUCT_PAYROLL ("tài khoản lương").
                          "reason": f"Vừa chuyển việc sang {latest} — có thể "
                                    f"chuyển tài khoản lương, mở thẻ tín dụng",
                          "role": title}})
    except Exception:                              # noqa: BLE001
        log.exception("Không tạo được Signal đổi việc cho Person %s", person.pk)
        return
    if not created:
        return
    # Nối vào nhánh bán hàng như social/pipeline làm — route_signal tự chấm điểm
    # và lọc, tín hiệu yếu không sinh đề xuất nào.
    try:
        from rb.routing import route_signal
        route_signal(signal)
    except ImportError:                            # pragma: no cover — chưa bật module RB
        pass
    except Exception:                              # noqa: BLE001
        log.exception("Không route được Signal đổi việc %s", signal.pk)


# Fact do AI bóc từ TEXT CV (intel/extraction.py) → cột trên TalentProfile.
# Đây là chỗ "một đoạn văn bản dài" của Edge trở thành trường tra cứu được:
# derive() ở trên chỉ đọc payload có cấu trúc của nguồn tuyển dụng, KHÔNG đọc CV.
#   latest    — một giá trị, bản mới nhất thắng
#   merge     — cột JSONField list, hợp nhất không trùng
#   merge_str — cột CharField, nối các giá trị bằng " | "
_FACT_TO_PROFILE = {
    "city":               ("location", "latest"),
    "current_title":      ("current_title", "latest"),
    "current_company":    ("current_company", "latest"),
    "seniority":          ("seniority", "latest"),
    "education_level":    ("education", "latest"),
    "experience_summary": ("summary", "latest"),
    "skills":             ("skills", "merge"),
    "industries":         ("industries", "merge"),
    "languages":          ("foreign_language", "merge_str"),
}


def _fact_value(fact):
    return (fact.canonical_label or fact.normalized_value or fact.raw_value or "").strip()


def apply_extracted_facts(person, save=True):
    """Lấp các cột TalentProfile còn trống bằng fact AI bóc từ text CV.

    Thứ tự ưu tiên bám đúng triết lý "Edge-first, AI fill gaps" (§7.2): payload
    có cấu trúc của nguồn tuyển dụng (qua `derive()`) thắng, fact từ CV chỉ điền
    vào chỗ `derive()` để trống. Trường recruiter đã sửa tay (`curated_fields`)
    thì miễn nhiễm — con người thắng máy.

    Chạy lại được và cho cùng kết quả; gọi sau mỗi lượt `intel.run_for_person`.
    """
    profile = TalentProfile.objects.filter(person=person).first()
    if profile is None:
        return None

    from intel.facts import current_facts
    facts = current_facts(person).filter(
        field__in=list(_FACT_TO_PROFILE) + ["years_experience"])
    by_field = {}
    for fact in facts:
        by_field.setdefault(fact.field, []).append(fact)
    if not by_field:
        return profile

    changed = False
    for intel_field, (attr, mode) in _FACT_TO_PROFILE.items():
        if intel_field not in by_field or profile.is_curated(attr):
            continue

        if mode == "latest":
            if str(getattr(profile, attr) or "").strip():
                continue                    # derive() đã điền từ payload
            value = _fact_value(by_field[intel_field][0])
            if not value:
                continue
            limit = TalentProfile._meta.get_field(attr).max_length or 2000
            setattr(profile, attr, value[:limit])
            changed = True

        elif mode == "merge":
            have = list(getattr(profile, attr) or [])
            seen = {str(v).lower() for v in have}
            added = False
            for fact in by_field[intel_field]:
                value = _fact_value(fact)
                if value and value.lower() not in seen:
                    seen.add(value.lower())
                    have.append(value[:60])
                    added = True
            if added:
                setattr(profile, attr, have[:100])
                changed = True

        elif mode == "merge_str":
            if str(getattr(profile, attr) or "").strip():
                continue
            values, seen = [], set()
            for fact in by_field[intel_field]:
                value = _fact_value(fact)
                if value and value.lower() not in seen:
                    seen.add(value.lower())
                    values.append(value)
            if values:
                limit = TalentProfile._meta.get_field(attr).max_length or 200
                setattr(profile, attr, " | ".join(values)[:limit])
                changed = True

    if not profile.is_curated("years_experience") and profile.years_experience is None:
        for fact in by_field.get("years_experience", []):
            years = parse_years(_fact_value(fact))
            if years is not None:
                profile.years_experience = years
                changed = True
                break

    if changed and save:
        profile.save()
    return profile


def _first_value(payloads, keys):
    """Giá trị không rỗng đầu tiên, quét bản ghi mới trước rồi mới đến bản ghi cũ."""
    for payload in payloads:
        for key in keys:
            value = str(payload.get(key) or "").strip()
            if value:
                return value
    return ""


def _parse_timestamp(value):
    text = str(value or "").strip()
    if not text:
        return None
    for pattern in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            from datetime import datetime
            parsed = datetime.strptime(text, pattern)
            return timezone.make_aware(parsed) if timezone.is_naive(parsed) else parsed
        except (ValueError, TypeError):
            continue
    return None


def derive_all(limit=None):
    """Dựng lại hồ sơ cho mọi Person có bản ghi nguồn. Trả thống kê."""
    queryset = (Person.objects
                .filter(merged_into__isnull=True, source_records__isnull=False)
                .distinct())
    if limit:
        queryset = queryset[:limit]

    stats = {"processed": 0, "errors": 0}
    for person in queryset:
        try:
            derive(person)
        except Exception:                      # noqa: BLE001
            # Một hồ sơ hỏng không được làm dừng cả lô.
            log.exception("Không suy được TalentProfile cho Person %s", person.pk)
            stats["errors"] += 1
        stats["processed"] += 1
    return stats
