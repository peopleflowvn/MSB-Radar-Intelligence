# -*- coding: utf-8 -*-
"""Nguồn bằng chứng của Growth — bản tương ứng của `CVChunk` bên Talent.

Talent có một nguồn lớn và tĩnh: text CV đã bóc tách. Growth thì ngược lại —
nhiều nguồn nhỏ, mỗi nguồn có **thời điểm**, và giá trị giảm dần theo thời gian:

    social      `SocialPost.content` — chính lời khách viết ra. Mạnh nhất, vì nó
                là ý định tự khách nói, không phải ta suy ra.
    comment     `SocialComment.content` dưới bài của họ.
    signal      `Signal.evidence` (domain rb) — tín hiệu đã được xử lý.
    interest    `ProductInterest.evidence` — vì sao tin là họ quan tâm.
    outcome     `OpportunityOutcome` — chuyện THẬT đã xảy ra khi RM liên hệ.
                Quý nhất trong tất cả và hay bị bỏ quên: "đã nói không quan tâm
                tháng trước" phải chặn được một đề xuất chào lại.
    profile     nghề nghiệp, nơi làm việc, tóm tắt tương tác — nền tĩnh.

## Vì sao mỗi đoạn phải mang `observed_at`

Đây là khác biệt lớn nhất so với Talent. Một đoạn CV không "cũ đi" — người ta
từng làm ở ngân hàng ACB thì mãi mãi từng làm. Một tín hiệu mua hàng thì có: nó
mô tả một TRẠNG THÁI nhất thời. Không mang theo thời điểm thì ③ không phân biệt
được "đang cần" với "từng cần", và Radar sẽ giục RM gọi một người đã mua nhà từ
năm ngoái.

## Che liên hệ — vẫn che, dù RM được phép xem

Giống Talent, và không phải vì cùng lý do. Ở đây RM CÓ quyền xem số điện thoại
khách (qua hạn mức `accounts.privacy.unlock`). Nhưng mô hình không cần số điện
thoại để phán đoán ai đáng gọi, mà một bài đăng công khai thường chứa số của
NHIỀU người — người đăng lẫn người bình luận. Che tại đây thì cả lớp lỗi "⑤ chép
lại số điện thoại của một người thứ ba" biến mất, thay vì phải rào bằng lời dặn
trong prompt.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from accounts import privacy
from django.utils import timezone
from people.models import Signal

log = logging.getLogger(__name__)

#: Độ dài tối đa một đoạn bằng chứng.
PASSAGE_CHARS = 700
#: Số đoạn cho người xếp đầu — những người ③ thật sự sẽ chọn.
PASSAGES_PER_PERSON = 5
#: Số đoạn cho phần đuôi danh sách. Đủ để ③ nhận ra ai lạc đề.
TAIL_PASSAGES = 2

#: Thứ tự ưu tiên khi một người có nhiều loại bằng chứng hơn số đoạn cho phép.
#: `outcome` đứng đầu có chủ đích: nó là điều ĐÃ XẢY RA, và bỏ nó đi để nhường
#: chỗ cho một bài đăng cũ là cách chắc chắn để chào lại người vừa từ chối.
SOURCE_RANK = {"outcome": 0, "social": 1, "comment": 2, "signal": 3,
               "interest": 4, "profile": 5}


def clean_passage(text, *, limit=PASSAGE_CHARS):
    """Gộp khoảng trắng, cắt độ dài, và che email/số điện thoại. Xem docstring module."""
    return privacy.redact_contacts(" ".join(str(text or "").split())[:limit])


@dataclass
class Passage:
    """Một mẩu bằng chứng về một người, luôn kèm nguồn gốc và thời điểm."""

    person_id: int
    text: str
    source: str                      # social | comment | signal | interest | outcome | profile
    observed_at: object = None       # datetime hoặc None khi là nền tĩnh
    #: Khoá để người dùng bấm vào xem nguyên bản. `url` cho bài mạng xã hội,
    #: `(model, pk)` cho bản ghi nội bộ.
    url: str = ""
    ref: str = ""

    def age_days(self, now=None):
        """Bao nhiêu ngày trước. `None` (nền tĩnh) coi như rất cũ, KHÔNG phải mới.

        Hướng làm tròn này là cố ý: một mẩu dữ liệu không biết thời điểm không
        được hưởng lợi thế của dữ liệu mới. Đoán sai theo chiều "mới" khiến
        Radar giục RM gọi dựa trên một thứ có thể đã cũ hai năm.
        """
        if self.observed_at is None:
            return None
        return max(0, ((now or timezone.now()) - self.observed_at).days)

    def as_dict(self):
        return {"snippet": self.text, "source": self.source, "url": self.url,
                "ref": self.ref,
                "observed_at": self.observed_at.isoformat() if self.observed_at else None}


@dataclass
class Candidate:
    """Một khách hàng tiềm năng đã được truy hồi, kèm bằng chứng để ③ đọc."""

    person_id: int
    name: str
    score: float = 0.0
    hits: int = 0                    # số nhánh truy hồi chạm tới người này
    passages: list = field(default_factory=list)

    def evidence_text(self, limit=PASSAGES_PER_PERSON):
        return [p.text for p in self.passages[:limit]]

    def freshest_days(self, now=None):
        """Tín hiệu MỚI NHẤT bao nhiêu ngày — đầu vào cho chiều `timing`."""
        ages = [p.age_days(now) for p in self.passages]
        known = [a for a in ages if a is not None]
        return min(known) if known else None


#: Số bài mạng xã hội mới nhất lấy cho MỖI người.
POSTS_PER_PERSON = 6


def _social_passages(person_ids, now, depth=1):
    from social.models import SocialComment, SocialPost

    # Cắt theo TỪNG NGƯỜI, không cắt trên danh sách đã trộn. Sắp toàn cục theo
    # độ mới rồi lấy N đầu tiên thì một khách hàng hay đăng bài sẽ ăn hết hạn
    # mức và những người còn lại vào ③ với zero bằng chứng — bị loại vì im
    # lặng, không phải vì không phù hợp.
    rows = (SocialPost.objects.filter(person_id__in=person_ids)
            .only("id", "person_id", "content", "posted_at", "created_at", "url")
            .order_by("person_id", "-posted_at", "-created_at"))
    out, per_person, owner_of_post = [], {}, {}
    for post in rows.iterator(chunk_size=500):
        taken = per_person.get(post.person_id, 0)
        if taken >= POSTS_PER_PERSON * depth:
            continue
        per_person[post.person_id] = taken + 1
        owner_of_post[post.pk] = post.person_id
        out.append(Passage(post.person_id, clean_passage(post.content), "social",
                           observed_at=post.posted_at or post.created_at,
                           url=post.url, ref=f"socialpost:{post.pk}"))
    if owner_of_post:
        comments = (SocialComment.objects.filter(post_id__in=list(owner_of_post))
                    .only("id", "post_id", "content", "posted_at", "created_at")
                    .order_by("post_id", "-posted_at", "-id"))
        per_post = {}
        for comment in comments.iterator(chunk_size=500):
            taken = per_post.get(comment.post_id, 0)
            if taken >= 2 * depth:
                continue
            per_post[comment.post_id] = taken + 1
            out.append(Passage(owner_of_post[comment.post_id],
                               clean_passage(comment.content), "comment",
                               observed_at=comment.posted_at or comment.created_at,
                               ref=f"socialcomment:{comment.pk}"))
    return out


def _signal_passages(person_ids, now, depth=1):
    rows = (Signal.objects.filter(person_id__in=person_ids, domain=Signal.DOMAIN_RB)
            .only("id", "person_id", "signal_type", "evidence", "observed_at", "source")
            .order_by("-observed_at")[:len(person_ids) * 6 * depth])
    out = []
    for signal in rows:
        evidence = signal.evidence if isinstance(signal.evidence, dict) else {}
        # `evidence` là JSON tự do theo từng nguồn. Ghép mọi giá trị dạng chữ
        # thay vì bám vào một khoá cố định: khoá cố định sẽ im lặng bỏ qua mọi
        # nguồn mới mà không ai biết.
        body = " ".join(str(v) for v in evidence.values()
                        if isinstance(v, str) and v.strip())
        text = f"[{signal.signal_type}] {body}".strip()
        if body:
            out.append(Passage(signal.person_id, clean_passage(text), "signal",
                               observed_at=signal.observed_at,
                               ref=f"signal:{signal.pk}"))
    return out


def _interest_passages(person_ids, now, depth=1):
    from ..models import ProductInterest, PRODUCT_LABELS

    rows = (ProductInterest.objects.filter(profile__person_id__in=person_ids)
            .select_related("profile")
            .order_by("-observed_at")[:len(person_ids) * 4 * depth])
    out = []
    for interest in rows:
        evidence = interest.evidence if isinstance(interest.evidence, dict) else {}
        body = " ".join(str(v) for v in evidence.values()
                        if isinstance(v, str) and v.strip())
        label = PRODUCT_LABELS.get(interest.product, interest.product)
        text = (f"Quan tâm {label} (tin cậy {round(interest.confidence * 100)}%"
                f"{', nguồn ' + interest.source if interest.source else ''}). {body}")
        out.append(Passage(interest.profile.person_id, clean_passage(text), "interest",
                           observed_at=interest.observed_at,
                           ref=f"interest:{interest.pk}"))
    return out


def _outcome_passages(person_ids, now, depth=1):
    """Chuyện THẬT đã xảy ra khi RM liên hệ — quý nhất, và hay bị bỏ quên.

    Không có nó thì Radar chào lại đúng người vừa nói "không quan tâm" tuần
    trước, và đó là cách nhanh nhất để mất khách (xem
    `rb/models.py::OpportunityOutcome.REACTIVATABLE`).
    """
    from ..models import OpportunityOutcome, PRODUCT_LABELS

    rows = (OpportunityOutcome.objects
            .filter(person_id__in=person_ids)
            .select_related("opportunity")
            .order_by("-created_at")[:len(person_ids) * 3 * depth])
    out = []
    for row in rows:
        label = PRODUCT_LABELS.get(row.opportunity.product, row.opportunity.product)
        note = row.note or ""
        text = (f"Đã tiếp cận về {label}: {row.get_outcome_display()}"
                f"{' — ' + note if note else ''}.")
        out.append(Passage(row.person_id, clean_passage(text), "outcome",
                           observed_at=row.created_at,
                           ref=f"outcome:{row.pk}"))
    return out


def _profile_passages(person_ids, now, depth=1):
    """Nền tĩnh: nghề nghiệp, nơi làm việc, tóm tắt tương tác.

    `observed_at=None` có chủ đích — đây là dữ liệu mô tả, không phải một sự kiện
    quan sát được tại một thời điểm, nên nó không được cạnh tranh với tín hiệu
    thật ở chiều độ mới.
    """
    from ..models import RBProfile

    rows = (RBProfile.objects.filter(person_id__in=person_ids)
            .select_related("person")
            .only("person_id", "occupation", "employer", "segment",
                  "lead_status", "interaction_summary"))
    out = []
    for profile in rows:
        parts = [profile.person.display_name]
        if profile.occupation:
            parts.append(f"nghề nghiệp {profile.occupation}")
        if profile.employer:
            parts.append(f"tại {profile.employer}")
        if profile.segment:
            parts.append(f"phân khúc {profile.get_segment_display()}")
        parts.append(f"trạng thái {profile.get_lead_status_display()}")
        if profile.interaction_summary:
            parts.append(profile.interaction_summary)
        out.append(Passage(profile.person_id, clean_passage(", ".join(parts)),
                           "profile", observed_at=None,
                           ref=f"rbprofile:{profile.person_id}"))
    return out


#: TÊN hàm, tra lúc gọi — không giữ tham chiếu hàm. Giữ tham chiếu thì
#: `mock.patch.object(evidence, "_social_passages", ...)` không bao giờ có tác
#: dụng, và test "một nguồn hỏng không làm mù cả lượt" xanh mà chưa từng làm
#: hỏng nguồn nào (đúng chuyện đã xảy ra trước bản sửa này).
_SOURCES = ("_outcome_passages", "_social_passages", "_signal_passages",
            "_interest_passages", "_profile_passages")


def gather(person_ids, *, now=None, depth=1):
    """`{person_id: [Passage, ...]}` — MỌI bằng chứng lấy được, chưa sắp, chưa cắt.

    Dùng chung bởi `passages_for` (③ đọc) và `rb/evidence_index.py` (lập chỉ mục
    tìm theo nghĩa). Một hàm gom duy nhất nghĩa là thứ được tìm thấy và thứ được
    đọc luôn là cùng một nội dung, đã che liên hệ theo cùng một cách.

    `depth` nhân trần số bản ghi mỗi nguồn. ③ chỉ cần vài đoạn mới nhất
    (`depth=1`); chỉ mục tìm theo nghĩa cần cả lịch sử, vì một nhu cầu nói ra
    từ ba tháng trước vẫn phải tìm thấy được — việc nó đã cũ là chuyện của xếp
    hạng, không phải của việc có tồn tại hay không.
    """
    person_ids = [int(p) for p in person_ids if p]
    if not person_ids:
        return {}
    now = now or timezone.now()

    gathered = []
    for name in _SOURCES:
        source = globals()[name]
        try:
            gathered.extend(source(person_ids, now, depth))
        except Exception:                          # noqa: BLE001
            # Một nguồn hỏng không được làm mù cả lượt: thà trả lời với bốn
            # nguồn còn lại và nói rõ, hơn là không trả lời gì.
            log.warning("rb.answer.evidence: nguồn %s hỏng, bỏ qua",
                        getattr(source, "__name__", "?"), exc_info=True)

    by_person: dict[int, list] = {pid: [] for pid in person_ids}
    for passage in gathered:
        if passage.person_id in by_person and passage.text:
            by_person[passage.person_id].append(passage)
    return by_person


def passages_for(person_ids, *, per_person=PASSAGES_PER_PERSON, now=None):
    """`{person_id: [Passage, ...]}` — bằng chứng để ③ đọc và trích dẫn.

    Sắp theo (loại nguồn, độ mới) rồi cắt: một người có 40 bài đăng không được
    đẩy kết quả tiếp cận của chính họ ra khỏi tầm nhìn của ③.
    """
    now = now or timezone.now()
    by_person = gather(person_ids, now=now)
    for pid, items in by_person.items():
        items.sort(key=lambda p: (SOURCE_RANK.get(p.source, 9),
                                  p.age_days(now) if p.age_days(now) is not None else 10**6))
        by_person[pid] = items[:per_person]
    return by_person
