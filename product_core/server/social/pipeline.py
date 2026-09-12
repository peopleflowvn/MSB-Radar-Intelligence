# -*- coding: utf-8 -*-
"""Từ một bài đăng tới một tín hiệu gắn vào hồ sơ người (Master Plan mục 31).

```text
Bài đăng
   ↓  intent.detect()          chấm ý định, đa nhãn
   ↓  _resolve_author()        khớp với người đã có trong kho
   ↓  people.Signal            tín hiệu, kèm bằng chứng
Cơ hội cho recruiter
```

Câu đáng giá nhất của cả Social Radar nằm ở bước khớp người:

> *Người này từng ứng tuyển 9 tháng trước, và vừa có tín hiệu tìm việc.*

Không khớp được thì bài viết chỉ là một dòng chữ trên mạng. Khớp được thì nó
thành một lý do để gọi điện — và lý do ấy có ngày tháng, có bằng chứng.

**Không tự tạo Person mới từ một bài đăng.** Bài viết cho ta cùng lắm là một số
điện thoại và một cái tên hiển thị; tạo Person từ đó sẽ đổ vào People Database
những hồ sơ rỗng mà không nghiệp vụ nào dùng được, và làm hỏng chính chỉ số
"gộp trùng lặp". Chỉ khi bài có định danh mạnh **và** khớp người đã có thì mới
gắn. Không khớp thì bài vẫn nằm đó cho recruiter tự xem.
"""
import logging

from django.db import transaction
from django.utils import timezone
from people import resolution
from people.models import Signal

from . import intent as intent_module
from .models import SocialPost

log = logging.getLogger(__name__)

#: Dưới ngưỡng này thì không sinh tín hiệu. Đặt ở tầng này chứ không ở
#: `intent.py`: tuyển dụng muốn nghe rộng, bán lẻ muốn chắc mới động vào.
THRESHOLDS = {
    intent_module.DOMAIN_TALENT: 0.5,
    intent_module.DOMAIN_RB: 0.7,
}

SIGNAL_TYPES = {
    intent_module.DOMAIN_TALENT: "job_seeking",
    intent_module.DOMAIN_RB: "financial_need",
}


class Processed:
    def __init__(self, post, intent, signals, matched):
        self.post = post
        self.intent = intent
        self.signals = signals
        self.matched = matched      # có khớp được người đã có trong kho không

    def as_dict(self):
        return {
            "post_id": self.post.pk,
            "intent": self.intent.as_dict(),
            "matched_person": self.post.person_id,
            "signals": [{"domain": s.domain, "type": s.signal_type,
                         "confidence": s.confidence} for s in self.signals],
        }


@transaction.atomic
def process(post, rescore=True):
    """Chấm ý định, khớp người, sinh tín hiệu. Trả `Processed`."""
    if rescore or not post.intent:
        result = intent_module.detect(
            post.content, community=post.community,
            comments=list(post.comments.all()), author_name=post.author_name)
        post.intent = result.scores
        post.intent_reason = result.reason
        post.intent_fallback = result.fallback
        post.contacts = result.contacts
        post.status = SocialPost.STATUS_SCORED
    else:
        result = intent_module.Intent(post.intent or {}, reason=post.intent_reason,
                                      contacts=post.contacts)

    matched = _resolve_author(post, result)
    signals = _make_signals(post, result) if post.person_id else []
    _route_to_rb(signals)

    if post.person_id:
        post.status = SocialPost.STATUS_LINKED
    elif not result.is_relevant:
        post.status = SocialPost.STATUS_IGNORED
    post.save()

    return Processed(post, result, signals, matched)


def _route_to_rb(signals):
    """Đẩy tín hiệu tài chính sang RB Radar (Master Plan mục 32).

    Import trong hàm chứ không ở đầu file: Social Radar phải chạy được cả khi
    chưa bật module bán lẻ. Nghiệp vụ này là năng lực dùng chung (mục 26), nó
    không được phụ thuộc cứng vào một nghiệp vụ tiêu thụ cụ thể.
    """
    financial = [s for s in signals if s.domain == intent_module.DOMAIN_RB]
    if not financial:
        return
    try:
        from rb import routing
    except ImportError:                        # pragma: no cover
        return
    for signal in financial:
        routing.route_signal(signal)


def _resolve_author(post, result):
    """Khớp tác giả với người đã có trong kho. KHÔNG tạo người mới."""
    payload = {
        "fullname": post.author_name,
        "email": result.contacts.get("email", ""),
        "phone": result.contacts.get("phone", ""),
        "facebook": post.author_url or post.author_handle,
    }
    identities = resolution.extract_identities(payload)
    if not identities:
        return False

    matches = resolution.find_people(identities)
    if len(matches) != 1:
        # Không khớp, hoặc khớp nhiều người. Cả hai đều để nguyên: gộp nhầm hai
        # con người tệ hơn nhiều so với bỏ lỡ một tín hiệu.
        if len(matches) > 1:
            log.info("Bài %s khớp %d người, để người xử lý", post.pk, len(matches))
        return False

    post.person = next(iter(matches.values()))["person"]
    return True


def _make_signals(post, result):
    """Một tín hiệu cho mỗi nghiệp vụ vượt ngưỡng."""
    made = []
    for domain, threshold in THRESHOLDS.items():
        score = result.score(domain)
        if score < threshold:
            continue

        signal, created = Signal.objects.get_or_create(
            person=post.person, domain=domain,
            signal_type=SIGNAL_TYPES[domain],
            source=post.provider,
            observed_at=post.posted_at or post.created_at or timezone.now(),
            defaults={
                "confidence": score,
                # Bằng chứng là bắt buộc về mặt thiết kế (Nguyên tắc 4): không
                # có nó thì không giải thích được vì sao đề xuất gọi người này.
                "evidence": _evidence(post, result),
            })
        if not created and signal.confidence < score:
            signal.confidence = score
            signal.evidence = _evidence(post, result)
            signal.save(update_fields=["confidence", "evidence"])
        made.append(signal)
    return made


def _evidence(post, result):
    return {
        "post_id": post.pk,
        "url": post.url,
        "community": post.community.name if post.community_id else "",
        # Trích nguyên văn, không tóm tắt: người đọc phải tự kiểm được.
        "excerpt": post.content[:500],
        "reason": result.reason,
        "role": result.role,
        "location": result.location,
        "scored_by": "keyword" if result.fallback else "llm",
    }


def history_note(person):
    """Câu để recruiter đọc: người này đã có mặt trong kho từ bao giờ.

    Đây chính là câu chốt của Social Radar — *"từng ứng tuyển 9 tháng trước, và
    vừa có tín hiệu tìm việc"*. Nó chỉ có nghĩa khi khớp được người đã có, nên
    hàm này trả chuỗi rỗng chứ không bịa ra một câu chung chung.
    """
    if person is None:
        return ""
    record = person.source_records.order_by("first_seen_at").first()
    if record is None:
        return ""

    # Đọc nguồn từ payload trước, cột `source` chỉ là bản sao để tra cứu nhanh
    # và do endpoint đồng bộ điền — bản ghi tạo bằng đường khác sẽ để trống nó.
    payload = record.payload or {}
    source = payload.get("source") or record.source
    applied = str(payload.get("applied_ts") or "")[:10]
    if not applied:
        return "Đã có hồ sơ trong kho ứng viên."

    try:
        then = timezone.datetime.strptime(applied, "%Y-%m-%d").date()
    except ValueError:
        return "Đã có hồ sơ trong kho ứng viên."

    months = max(0, (timezone.now().date() - then).days // 30)
    return (f"Từng ứng tuyển {_how_long_ago(months)} "
            f"qua {source or 'một nguồn tuyển dụng'}, "
            f"và vừa có tín hiệu trên mạng xã hội.")


def _how_long_ago(months):
    """"41 tháng trước" là cách máy nói. Câu này hiện thẳng ra màn hình."""
    if months < 1:
        return "gần đây"
    if months < 24:
        return f"{months} tháng trước"
    years = months // 12
    return f"hơn {years} năm trước"
