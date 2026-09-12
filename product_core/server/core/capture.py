# -*- coding: utf-8 -*-
"""Đo năng lực thu thập và hợp nhất dữ liệu (Master Plan mục 9).

Đây là chỗ **moat kỹ thuật trở thành con số nhìn thấy được**. Trước module này,
việc Radar thu hồ sơ từ năm nền tảng rồi hợp nhất về một người là thứ chỉ đọc
được trong tài liệu kiến trúc — không có màn hình nào chứng minh nó.

Ba câu hỏi module này trả lời, và mỗi câu phục vụ một mục đích khác nhau:

    Nguồn nào đang chảy?      → vận hành: nguồn nào đứng thì biết ngay
    Bao nhiêu lượt → 1 người? → *"Ba lượt hồ sơ, nhưng chỉ là một con người"*
    Bóc tách có được không?   → chất lượng dữ liệu đầu vào cho AI Search

Câu thứ hai là câu quan trọng nhất. Nó là con số duy nhất trong cả hệ thống
chứng minh được **vấn đề tổ chức**: cùng một người ứng tuyển ba lần ở ba nơi,
và nếu không có Hub thì đó là ba hồ sơ rời rạc mà không ai biết là một.

## Vì sao không tính "tỷ lệ thu thập thành công"

Cám dỗ hiển nhiên là hiện `đã thu / có thể thu`. Nhưng **mẫu số không tồn tại**:
Hub không biết trên TopCV có bao nhiêu hồ sơ ứng tuyển mà nó chưa thấy. Bịa ra
mẫu số đó là bịa ra một tỷ lệ, và một tỷ lệ bịa đặt trước hội đồng giám khảo sẽ
sụp ngay ở câu hỏi đầu tiên.

Nên chỉ đếm những thứ **đếm được thật**: bản ghi đã nhận, người đã hợp nhất, tài
liệu đã bóc tách. Tỷ lệ thu thập thật sự phải đo bằng bài kiểm có kiểm soát
(đối chiếu tay trên một mẫu nhỏ), và nó thuộc `docs/HACKATHON_METRICS.md`, không
thuộc dashboard.
"""
from datetime import timedelta

from django.db.models import Count
from django.utils import timezone

from .models import SourceRecord

#: Nhãn hiển thị của các nhà cung cấp Edge biết thu. Giữ ở đây chứ không đọc từ
#: dữ liệu: nguồn chưa có bản ghi nào vẫn phải hiện ra với số 0, vì "TopCV chưa
#: kết nối" là thông tin vận hành, còn một danh sách chỉ gồm nguồn đang chạy thì
#: im lặng đúng lúc cần nói nhất.
PROVIDER_LABELS = {
    "topcv": "TopCV",
    "vietnamworks": "VietnamWorks",
    "careerviet": "CareerViet",
    "vieclam24h": "Việc Làm 24h",
    "itviec": "ITviec",
}


def collect(now=None):
    """Toàn bộ số liệu thu thập, dùng cho dashboard và cho pitch."""
    now = now or timezone.now()
    return {
        "providers": provider_coverage(now=now),
        "consolidation": consolidation(),
        "parsing": parse_quality(),
    }


def provider_coverage(now=None):
    """Mỗi nhà cung cấp đang đóng góp bao nhiêu, và có còn chảy không."""
    now = now or timezone.now()
    today = now - timedelta(days=1)

    rows = {
        item["source"]: item
        for item in SourceRecord.objects.values("source").annotate(
            records=Count("id"),
            people=Count("person", distinct=True),
        )
    }
    fresh = {
        item["source"]: item["records"]
        for item in SourceRecord.objects.filter(last_seen_at__gte=today)
        .values("source").annotate(records=Count("id"))
    }
    pending = {
        item["source"]: item["records"]
        for item in SourceRecord.objects.filter(status=SourceRecord.STATUS_PENDING)
        .values("source").annotate(records=Count("id"))
    }

    # Nguồn lạ (Edge có provider mới mà bảng nhãn chưa kịp cập nhật) vẫn phải
    # hiện ra — giấu đi thì dữ liệu vào hệ thống mà không ai biết từ đâu.
    known = list(PROVIDER_LABELS)
    unknown = sorted(set(rows) - set(known) - {""})

    result = []
    for source in known + unknown:
        records = rows.get(source, {}).get("records", 0)
        result.append({
            "source": source,
            "label": PROVIDER_LABELS.get(source, source or "Không rõ nguồn"),
            "records": records,
            "people": rows.get(source, {}).get("people", 0),
            "new_today": fresh.get(source, 0),
            "pending": pending.get(source, 0),
            "connected": records > 0,
        })
    result.sort(key=lambda row: (-row["records"], row["label"]))
    return result


def consolidation():
    """*"Ba lượt hồ sơ, nhưng chỉ là một con người"* — bằng số.

    `multi_source_people` là con số đắt nhất ở đây: số người mà Hub đã chứng
    minh được là **cùng một người** dù xuất hiện ở nhiều nền tảng khác nhau.
    Không có Hub thì mỗi lượt đó là một hồ sơ rời, và tổ chức không biết mình
    đã từng biết ai.
    """
    total_records = SourceRecord.objects.count()
    resolved = SourceRecord.objects.filter(person__isnull=False)
    unique_people = resolved.values("person").distinct().count()

    # Người xuất hiện ở nhiều NGUỒN khác nhau (không phải nhiều lượt cùng nguồn:
    # ứng tuyển hai vị trí trên cùng TopCV không chứng minh được điều gì về việc
    # hợp nhất dữ liệu liên nền tảng).
    per_person = list(resolved.values("person")
                      .annotate(sources=Count("source", distinct=True),
                                records=Count("id")))
    multi_source = [row for row in per_person if row["sources"] > 1]
    # Lấy max trên TOÀN BỘ, không phải chỉ trên nhóm nhiều nguồn: nếu ai cũng
    # chỉ có một nguồn thì con số đúng là 1, không phải 0. Tính trên nhóm đã
    # lọc sẽ hiện "0 nguồn cho người nhiều nhất" trên dashboard trong khi kho
    # đang có dữ liệu — nhìn như hệ thống hỏng.
    best = max((row["sources"] for row in per_person), default=0)

    return {
        "source_records": total_records,
        "unique_people": unique_people,
        "pending": SourceRecord.objects.filter(
            status=SourceRecord.STATUS_PENDING).count(),
        "multi_source_people": len(multi_source),
        "max_sources_for_one_person": best,
        # Trung bình bao nhiêu lượt hồ sơ gộp về một người. 1.0 = chưa hợp nhất
        # được gì; càng cao thì kho càng có lịch sử.
        "records_per_person": (round(resolved.count() / unique_people, 2)
                               if unique_people else None),
    }


def parse_quality():
    """Bóc tách CV có ra chữ không — chất lượng đầu vào của AI Search."""
    from people.models import Document

    total = Document.objects.count()
    if not total:
        # `None` chứ không phải 0: "chưa có tài liệu nào" và "bóc tách hỏng
        # hoàn toàn" là hai tình trạng khác hẳn nhau, cùng nguyên tắc với
        # `hiring/metrics.py`.
        return {"documents": 0, "parsed": 0, "failed": 0, "success_rate": None,
                "stored": 0}

    parsed = Document.objects.filter(parse_status=Document.PARSE_DONE).count()
    return {
        "documents": total,
        "parsed": parsed,
        "failed": Document.objects.filter(parse_status=Document.PARSE_FAILED).count(),
        "success_rate": round(parsed / total, 3),
        # Có bản ghi nhưng chưa có file trên Hub là một tình trạng riêng: Edge
        # đã báo có CV mà chưa tải lên được.
        "stored": Document.objects.exclude(storage_key="").count(),
    }
