# -*- coding: utf-8 -*-
"""Chỉ số đo hiệu quả Talent Radar (Master Plan mục 50).

Năm chỉ số, và mỗi chỉ số trả lời đúng một câu hỏi mà người duyệt dự án sẽ hỏi:

    Tái sử dụng hồ sơ cũ   Có thật là moi được người từ kho không, hay chỉ
                           đang lọc lại đúng những người vừa nộp tuần này?
    Gộp trùng lặp          Một người ứng tuyển nhiều nơi có ra một hồ sơ không?
    Thời gian tới shortlist  Nhanh hơn cách cũ bao nhiêu?
    HM chấp nhận @10       Đề xuất có đúng gu người tuyển không?
    Chốt yêu cầu săn       Vòng lặp có khép được không, hay dừng ở giữa?

**Chỉ số nào chưa có dữ liệu thì trả `None`, không trả 0.** Số 0 đọc như "làm
rồi mà kém"; `None` đọc đúng như nó là — "chưa đủ dữ liệu để nói". Nhầm hai thứ
này trong một buổi bảo vệ là tự bắn vào chân.

Tất cả tính bằng truy vấn tổng hợp, không cache: quy mô còn nhỏ, mà một lớp cache
sai còn tệ hơn một truy vấn chậm.
"""
from core.models import SourceRecord
from django.db.models import Count
from django.utils import timezone
from people.models import Person

from .models import Candidacy, HiringNeed, HuntCandidate, HuntRequest

#: Hồ sơ cũ hơn mốc này thì tính là "moi từ kho", không phải người vừa nộp.
#: 6 tháng — đủ dài để không còn nằm trong tầm nhớ của recruiter.
STALE_DAYS = 180

#: Số ứng viên đầu bảng dùng để đo mức chấp nhận của HM.
TOP_N = 10


def collect():
    return {
        "historical_reuse": _historical_reuse(),
        "duplicate_consolidation": _duplicate_consolidation(),
        "time_to_first_shortlist": _time_to_first_shortlist(),
        "hm_acceptance": _hm_acceptance(),
        "hunt_conversion": _hunt_conversion(),
    }


def _historical_reuse():
    """Bao nhiêu người được shortlist có hồ sơ đã nằm trong kho từ lâu.

    Đây là chỉ số cốt lõi của cả dự án. Nếu con số này thấp thì sản phẩm chỉ
    đang làm nhanh hơn việc lọc hồ sơ mới — không phải làm được việc mới.
    """
    shortlisted = (Candidacy.objects
                   .filter(state__in=(Candidacy.STATE_SHORTLISTED,
                                      Candidacy.STATE_GOOD_FIT))
                   .values_list("person_id", flat=True).distinct())
    total = len(shortlisted)
    if not total:
        return _empty("Chưa ai được đưa vào shortlist.")

    cutoff = (timezone.now() - timezone.timedelta(days=STALE_DAYS)).date()

    # Mốc thời gian phải là NGÀY ỨNG TUYỂN (`applied_ts` trong payload), không
    # phải `first_seen_at` — cái sau là lúc Hub nhận được bản ghi. Đồng bộ cả
    # kho lịch sử về trong một buổi sẽ khiến mọi hồ sơ trông như vừa nộp hôm
    # nay, và chỉ số cốt lõi này luôn bằng 0.
    earliest = {}
    for person_id, payload in (SourceRecord.objects
                               .filter(person_id__in=shortlisted)
                               .values_list("person_id", "payload")):
        applied = str((payload or {}).get("applied_ts") or "")[:10]
        if applied and (person_id not in earliest or applied < earliest[person_id]):
            earliest[person_id] = applied

    cutoff_text = cutoff.isoformat()
    from_archive = sum(1 for applied in earliest.values() if applied < cutoff_text)
    return {
        "value": round(from_archive / total, 3),
        "label": "Tái sử dụng hồ sơ cũ",
        "detail": f"{from_archive}/{total} người được chọn đã nằm trong kho "
                  f"hơn {STALE_DAYS // 30} tháng",
        "unit": "ratio",
    }


def _duplicate_consolidation():
    """Bao nhiêu lượt ứng tuyển gộp lại thành bao nhiêu con người."""
    records = SourceRecord.objects.filter(person__isnull=False).count()
    people = Person.objects.filter(merged_into__isnull=True,
                                   source_records__isnull=False).distinct().count()
    if not people:
        return _empty("Chưa có dữ liệu ứng viên.")
    return {
        "value": round(records / people, 2),
        "label": "Lượt ứng tuyển trên mỗi người",
        "detail": f"{records} lượt ứng tuyển gộp thành {people} hồ sơ người",
        "unit": "x",
    }


def _time_to_first_shortlist():
    """Từ lúc mở vị trí tới lúc có người đầu tiên vào shortlist."""
    durations = []
    for need in HiringNeed.objects.all():
        first = (need.candidacies
                 .filter(state=Candidacy.STATE_SHORTLISTED, marked_at__isnull=False)
                 .order_by("marked_at").first())
        if first:
            durations.append((first.marked_at - need.created_at).total_seconds())
    if not durations:
        return _empty("Chưa vị trí nào có shortlist.")

    # Trung vị chứ không trung bình: một vị trí bị bỏ quên nửa tháng đủ kéo lệch
    # trung bình tới mức vô nghĩa.
    durations.sort()
    median = durations[len(durations) // 2]
    value, unit = _duration(median)
    return {
        "value": value,
        "label": "Thời gian tới shortlist đầu tiên",
        "detail": f"trung vị trên {len(durations)} vị trí",
        "unit": unit,
    }


def _duration(seconds):
    """Đổi sang đơn vị đọc được. "0.2 phút" là con số máy nói, không phải người.

    Chỉ số này sẽ nằm trên slide cạnh con số của cách làm cũ (tính bằng ngày),
    nên nó phải đọc trôi thành một câu tiếng Việt.
    """
    if seconds < 90:
        return round(seconds), "giây"
    if seconds < 7200:
        return round(seconds / 60), "phút"
    if seconds < 172800:
        return round(seconds / 3600, 1), "giờ"
    return round(seconds / 86400, 1), "ngày"


def _hm_acceptance():
    """Trong TOP_N người hệ thống đề xuất, HM đồng ý bao nhiêu."""
    considered = accepted = 0
    for need in HiringNeed.objects.all():
        rows = list(need.candidacies.order_by("-score_snapshot")[:TOP_N])
        judged = [r for r in rows if r.state != Candidacy.STATE_SUGGESTED]
        if not judged:
            continue
        considered += len(judged)
        accepted += sum(1 for r in judged if r.state != Candidacy.STATE_NOT_FIT)

    if not considered:
        return _empty("Chưa có đánh giá nào từ trưởng bộ phận.")
    return {
        "value": round(accepted / considered, 3),
        "label": f"Trưởng bộ phận chấp nhận (top {TOP_N})",
        "detail": f"{accepted}/{considered} hồ sơ đã chấm được cho là phù hợp",
        "unit": "ratio",
    }


def _hunt_conversion():
    """Bao nhiêu yêu cầu săn kết thúc bằng ít nhất một người chuyển lại HM."""
    hunts = list(HuntRequest.objects.annotate(n=Count("candidates")).filter(n__gt=0))
    if not hunts:
        return _empty("Chưa có yêu cầu săn nào.")

    submitted_hunts = set(
        HuntCandidate.objects
        .filter(state=HuntCandidate.STATE_SUBMITTED)
        .values_list("hunt_request_id", flat=True))
    converted = sum(1 for h in hunts if h.pk in submitted_hunts)
    return {
        "value": round(converted / len(hunts), 3),
        "label": "Yêu cầu săn có kết quả",
        "detail": f"{converted}/{len(hunts)} yêu cầu có ít nhất một người "
                  f"được chuyển lại trưởng bộ phận",
        "unit": "ratio",
    }


def _empty(reason):
    """`value: None` — chưa đủ dữ liệu, KHÁC với 0 nghĩa là làm rồi mà kém."""
    return {"value": None, "label": "", "detail": reason, "unit": ""}
