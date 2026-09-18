# -*- coding: utf-8 -*-
"""Vòng đời đề xuất cơ hội (Master Plan mục 33, 34).

    Signal → ProductInterest → OpportunitySuggestion → RM ACCEPT → RBOpportunity

Module này giữ đúng một ranh giới, và nó là ranh giới quan trọng nhất của cả RB
Radar: **máy đề xuất, người quyết định.**

Cụ thể là `accept()` — hàm duy nhất trong toàn hệ thống sinh ra `RBOpportunity`
từ một đề xuất — luôn đòi một `actor`. Không có tham số mặc định, không có
đường tắt cho tác vụ nền. Nếu sau này ai đó muốn hệ thống tự nhận cơ hội thay
RM thì phải sửa chữ ký hàm này, và lúc đó việc đó sẽ hiện ra trong code review
chứ không lặng lẽ xảy ra.

So với `routing.create_opportunities()` (vẫn giữ nguyên, dùng cho luồng RM tự
tạo cơ hội thủ công), luồng ở đây thêm một trạm dừng. Cái giá phải trả là RM
bấm thêm một nút; cái nhận lại là hộp thư cơ hội chỉ chứa việc đã có người
nhận, và chỉ số "đang xử lý" nói đúng thứ nó tên.
"""
import logging
from datetime import timedelta

from django.db import IntegrityError, transaction
from django.utils import timezone
from people.models import Relationship, Signal

from . import scoring
from .models import OpportunitySuggestion, RBOpportunity

log = logging.getLogger(__name__)

#: Tỷ lệ danh sách dành cho cơ hội mạnh nằm NGOÀI khai báo của RM.
#:
#: 20% là điểm cân bằng giữa hai rủi ro ngược nhau: quá thấp thì cá nhân hoá
#: bịt mất tầm nhìn của RM (xem `_with_discovery_slots`); quá cao thì danh sách
#: loãng, RM thấy toàn việc không phải của mình và ngừng tin cả màn hình.
DISCOVERY_RATIO = 0.2


def build_suggestion(person, product, interest=None, signals=(), need_summary="",
                     now=None):
    """Chấm điểm 5 chiều và dựng (chưa lưu) một đề xuất.

    Tách khỏi `create_or_update()` để test được phần chấm điểm mà không cần
    chạm CSDL, và để màn hình "xem thử" gọi được mà không tạo rác.
    """
    now = now or timezone.now()
    profile = getattr(person, "rb_profile", None)
    # `Relationship.domain` dùng chung bộ mã với `Signal` — xem model đó.
    relationship = Relationship.objects.filter(
        person=person, domain=Signal.DOMAIN_RB).first()

    fit, fit_why = scoring.score_fit(person, product, profile=profile)
    need, need_why = scoring.score_need(interest=interest, signals=signals)

    observed = None
    if signals:
        observed = max(s.observed_at for s in signals)
    elif interest is not None:
        observed = interest.observed_at
    timing, timing_why = scoring.score_timing(observed, now=now,
                                              talent_profile=getattr(person, "talent_profile", None))

    reach, reach_why = scoring.score_reachability(person, profile=profile,
                                                  relationship=relationship)
    value, value_why, strategic = scoring.score_value(product)

    priority = scoring.priority_score(fit, need, timing, reach, value,
                                      strategic_weight=strategic)

    has_open = RBOpportunity.objects.filter(
        person=person, product=product,
        status__in=RBOpportunity.OPEN_STATUSES).exists()
    previous_outcome = _last_outcome(person, product)

    action = scoring.recommend_action(
        {"fit": fit, "need": need, "timing": timing,
         "reachability": reach, "value": value, "priority": priority},
        has_contact=bool(person.primary_phone or person.primary_email),
        has_open_opportunity=has_open, previous_outcome=previous_outcome)

    # `why` gộp lý do của cả năm chiều theo đúng thứ tự trọng số. Đây là thứ
    # màn hình "Cơ hội hôm nay" hiển thị ở mục VÌ SAO BÂY GIỜ — nên nó phải
    # đọc được bởi người không biết công thức, không phải là dump kỹ thuật.
    evidence = {
        "why": need_why + timing_why + fit_why + reach_why + value_why,
        "scores": {"fit": fit, "need": need, "timing": timing,
                   "reachability": reach, "value": value},
        "weights": dict(scoring.WEIGHTS),
        "strategic_weight": strategic,
        "has_open_opportunity": has_open,
    }
    if previous_outcome:
        evidence["previous_outcome"] = previous_outcome

    suggestion = OpportunitySuggestion(
        person=person, product=product,
        need_summary=(need_summary or _need_from(interest, signals))[:300],
        evidence=evidence,
        fit_score=fit, need_score=need, timing_score=timing,
        reachability_score=reach, value_score=value,
        priority_score=priority,
        # `confidence` là mức tin vào chính bằng chứng, KHÁC với `priority_score`
        # là mức đáng ưu tiên. Một nhu cầu chắc chắn nhưng giá trị thấp thì
        # confidence cao mà priority thấp — trộn hai thứ này là cách nhanh nhất
        # để RM hiểu sai danh sách.
        confidence=round(need / 100.0, 3),
        recommended_action=action,
        expires_at=now + timedelta(days=scoring.DEFAULT_TTL_DAYS))
    return suggestion


@transaction.atomic
def create_or_update(person, product, interest=None, signals=(), need_summary="",
                     owner=None, now=None):
    """Tạo đề xuất, hoặc cập nhật cái đang chờ nếu đã có.

    Trả `(suggestion, created)`, hoặc `(None, False)` nếu không đủ điểm.

    Không xếp chồng đề xuất: tín hiệu thứ hai về cùng một nhu cầu phải làm cái
    đang có **mạnh lên**, chứ không tạo thêm một dòng nữa trong danh sách của
    RM. Đây là bài học rút ra từ chính `RBOpportunity` — nếu không chặn, một
    người hay đăng bài sẽ chiếm hết màn hình.
    """
    draft = build_suggestion(person, product, interest=interest, signals=signals,
                             need_summary=need_summary, now=now)

    if draft.reachability_score <= 0:
        # Chỉ xảy ra với cờ DNC (thiếu liên hệ vẫn được `NO_CONTACT_SCORE`).
        # Khách đã nói đừng liên hệ thì không có điểm số nào bù lại được.
        log.info("Bỏ qua đề xuất %s cho person=%s: khách đã bật cờ DNC",
                 product, person.pk)
        return None, False

    if draft.need_score < scoring.MIN_NEED:
        # Ngưỡng không bù trừ được — xem `scoring.MIN_NEED`.
        log.info("Bỏ qua đề xuất %s cho person=%s: nhu cầu %.1f dưới ngưỡng %.1f",
                 product, person.pk, draft.need_score, scoring.MIN_NEED)
        return None, False

    if draft.priority_score < scoring.MIN_PRIORITY:
        log.info("Bỏ qua đề xuất %s cho person=%s: điểm %.1f dưới ngưỡng %.1f",
                 product, person.pk, draft.priority_score, scoring.MIN_PRIORITY)
        return None, False

    existing = (OpportunitySuggestion.objects
                .select_for_update()
                .filter(person=person, product=product,
                        status__in=OpportunitySuggestion.ACTIVE_STATUSES)
                .first())

    if existing is not None:
        _refresh(existing, draft, signals)
        return existing, False

    if owner is not None:
        draft.owner_suggestion = owner
    try:
        # Điểm lưu (savepoint) riêng cho lần ghi này là **bắt buộc**, không phải
        # trang trí: `create_or_update` đã nằm trong `atomic`, và trên PostgreSQL
        # một `IntegrityError` làm hỏng cả transaction — mọi truy vấn sau đó
        # trong cùng block sẽ ném `current transaction is aborted`, kể cả câu
        # đọc lại ngay bên dưới. SQLite bỏ qua chuyện này, nên lỗi sẽ không hiện
        # ra lúc chạy test mà chỉ hiện khi chạy thật.
        #
        # `routing.create_opportunities()` đã làm đúng cách này từ trước; giữ
        # nguyên khuôn đó ở đây.
        with transaction.atomic():
            draft.save()
    except IntegrityError:
        # Hai tín hiệu về cùng một người + sản phẩm tới đồng thời. Ràng buộc
        # CSDL đã chặn; đọc lại cái vừa thắng và cập nhật nó.
        existing = OpportunitySuggestion.objects.filter(
            person=person, product=product,
            status__in=OpportunitySuggestion.ACTIVE_STATUSES).first()
        if existing is None:
            raise
        _refresh(existing, draft, signals)
        return existing, False

    if signals:
        draft.source_signals.set(signals)
    return draft, True


def _refresh(existing, draft, signals):
    """Cập nhật đề xuất đang chờ bằng điểm mới. Chỉ nâng, không hạ.

    Vì sao chỉ nâng: một tín hiệu mới yếu hơn không có nghĩa nhu cầu cũ đã biến
    mất — cùng lý do với `routing.record_interests()`. Nhưng Timing thì LUÔN
    cập nhật, vì tín hiệu mới đúng là làm cơ hội nóng trở lại.
    """
    changed = ["timing_score", "priority_score", "updated_at"]
    existing.timing_score = draft.timing_score

    for field in ("fit_score", "need_score", "reachability_score", "value_score"):
        if getattr(draft, field) > getattr(existing, field):
            setattr(existing, field, getattr(draft, field))
            changed.append(field)

    existing.priority_score = scoring.priority_score(
        existing.fit_score, existing.need_score, existing.timing_score,
        existing.reachability_score, existing.value_score,
        strategic_weight=(draft.evidence or {}).get("strategic_weight", 1.0))
    existing.evidence = draft.evidence
    existing.recommended_action = draft.recommended_action
    existing.confidence = max(existing.confidence, draft.confidence)
    existing.expires_at = draft.expires_at
    changed += ["evidence", "recommended_action", "confidence", "expires_at"]

    if existing.status == OpportunitySuggestion.STATUS_SNOOZED:
        # Tín hiệu mới đánh thức đề xuất đang ngủ. Nếu không làm thế thì "để
        # sau" trở thành "bỏ qua vĩnh viễn" mà RM không hề chọn thế.
        existing.status = OpportunitySuggestion.STATUS_NEW
        existing.snoozed_until = None
        changed += ["status", "snoozed_until"]

    existing.save(update_fields=list(dict.fromkeys(changed)))
    if signals:
        existing.source_signals.add(*signals)


@transaction.atomic
def accept(suggestion, actor, priority="normal"):
    """RM nhận đề xuất → sinh `RBOpportunity`. Trả `(opportunity, created)`.

    `actor` là bắt buộc và không có giá trị mặc định — xem docstring module.
    """
    if actor is None:
        raise ValueError("Nhận cơ hội phải có người nhận.")

    locked = (OpportunitySuggestion.objects
              .select_for_update()
              .get(pk=suggestion.pk))
    if locked.status == OpportunitySuggestion.STATUS_CONVERTED:
        # Hai RM bấm nhận cùng lúc. Người sau nhận lại đúng cơ hội của người
        # trước chứ không tạo bản sao — cùng nguyên tắc với claim hàng loạt bên
        # `/hunts`.
        return locked.converted_opportunity, False

    existing = RBOpportunity.objects.filter(
        person=locked.person, product=locked.product,
        status__in=RBOpportunity.OPEN_STATUSES).first()
    if existing is not None:
        opportunity, created = existing, False
    else:
        opportunity = RBOpportunity.objects.create(
            person=locked.person, product=locked.product,
            need=locked.need_summary,
            confidence=locked.confidence,
            # Chuyển nguyên bằng chứng sang cơ hội: RM mở cơ hội ra sáu tuần sau
            # vẫn phải trả lời được "vì sao tôi nhận việc này".
            evidence=dict(locked.evidence or {}, from_suggestion=locked.pk),
            suggested_action=locked.get_recommended_action_display(),
            signal=locked.source_signals.first(),
            assigned_to=actor, status=RBOpportunity.STATUS_ACCEPTED,
            priority=priority)
        created = True

    locked.status = OpportunitySuggestion.STATUS_CONVERTED
    locked.converted_opportunity = opportunity
    locked.reviewed_by = actor
    locked.save(update_fields=["status", "converted_opportunity", "reviewed_by",
                               "updated_at"])
    return opportunity, created


def snooze(suggestion, actor, until=None, days=14):
    """Để sau. Đề xuất biến khỏi danh sách hôm nay nhưng không mất."""
    suggestion.status = OpportunitySuggestion.STATUS_SNOOZED
    suggestion.snoozed_until = until or (timezone.now() + timedelta(days=days))
    suggestion.reviewed_by = actor
    suggestion.save(update_fields=["status", "snoozed_until", "reviewed_by",
                                   "updated_at"])
    return suggestion


def dismiss(suggestion, actor, reason=""):
    """Bỏ qua, kèm lý do.

    Lý do không phải thủ tục hành chính: nó là dữ liệu đầu vào cho lần chấm
    điểm sau. "Sai sản phẩm" và "khách không có nhu cầu" dẫn tới hai hành vi
    khác hẳn nhau của Radar ở lần tín hiệu tiếp theo.
    """
    suggestion.status = OpportunitySuggestion.STATUS_DISMISSED
    suggestion.dismiss_reason = str(reason or "")[:300]
    suggestion.reviewed_by = actor
    suggestion.save(update_fields=["status", "dismiss_reason", "reviewed_by",
                                   "updated_at"])
    return suggestion


def expire_stale(now=None):
    """Đánh dấu hết hạn các đề xuất quá `expires_at`. Trả số dòng đã đổi.

    Chạy được nhiều lần, không đổi kết quả (idempotent) — dự định gọi từ tác vụ
    định kỳ, nhưng cũng an toàn khi gọi từ chính màn hình danh sách.
    """
    now = now or timezone.now()
    return (OpportunitySuggestion.objects
            .filter(status__in=OpportunitySuggestion.ACTIVE_STATUSES,
                    expires_at__lt=now)
            .update(status=OpportunitySuggestion.STATUS_EXPIRED, updated_at=now))


def wake_snoozed(now=None):
    """Đánh thức các đề xuất đã hết hạn 'để sau'. Trả số dòng đã đổi."""
    now = now or timezone.now()
    return (OpportunitySuggestion.objects
            .filter(status=OpportunitySuggestion.STATUS_SNOOZED,
                    snoozed_until__lte=now)
            .update(status=OpportunitySuggestion.STATUS_NEW,
                    snoozed_until=None, updated_at=now))


def todays_best(user=None, limit=20, product="", now=None):
    """Danh sách "Cơ hội hôm nay" (Master Plan mục 13).

    Dọn dẹp trước khi truy vấn: nếu không, RM sẽ thấy đề xuất đã hết hạn nằm
    đầu danh sách chỉ vì tác vụ nền chưa kịp chạy.

    `product` là tham số của **truy vấn**, không phải bộ lọc trên kết quả. Lọc
    sau khi đã cắt `limit` sẽ trả về vài dòng trong khi còn hàng chục đề xuất
    đúng nhóm sản phẩm đó nằm ngay dưới ngưỡng cắt.
    """
    now = now or timezone.now()
    expire_stale(now=now)
    wake_snoozed(now=now)

    queryset = (OpportunitySuggestion.objects
                .filter(status__in=(OpportunitySuggestion.STATUS_NEW,
                                    OpportunitySuggestion.STATUS_REVIEWED))
                # `person__rb_profile` có mặt ở đây vì thẻ hiển thị nghề nghiệp:
                # thiếu nó thì mỗi thẻ tốn thêm một truy vấn.
                .select_related("person", "person__rb_profile")
                .prefetch_related("source_signals")
                .order_by("-priority_score", "-created_at"))
    if product:
        queryset = queryset.filter(product=product)
    if user is not None:
        # Chưa gán ai thì mọi RM đều thấy — danh sách trống vì đề xuất nằm ở
        # người khác là cách chắc chắn để RM ngừng mở màn hình này.
        from django.db.models import Q
        queryset = queryset.filter(Q(owner_suggestion=user)
                                   | Q(owner_suggestion__isnull=True))

    if user is None:
        return queryset[:limit]

    profile = work_profile_for(user)
    if profile is None:
        return queryset[:limit]

    # Cá nhân hoá phải xếp lại trên một tập RỘNG HƠN `limit`, không phải trên
    # đúng `limit` dòng đầu: nếu chỉ lấy top-20 rồi mới xếp lại thì cơ hội trúng
    # địa bàn và trúng sản phẩm của RM nằm ở hạng 21 sẽ không bao giờ hiện ra —
    # tức là cá nhân hoá không làm được đúng việc nó sinh ra để làm.
    rows = list(queryset[:max(limit * 3, limit)])
    coverage = _region_coverage(exclude_user=user)

    for row in rows:
        adjusted, why = scoring.personalize(row, profile)
        # Gắn kèm để tầng hiển thị đọc được, KHÔNG ghi đè `priority_score`.
        row.personalized_score = adjusted
        row.personalized_why = why
        row.territory = scoring.territory_of(profile, row.person)
        row.is_discovery = False
        row.handoff_to = (_handoff_candidate(row.person, coverage)
                          if row.territory == scoring.TERRITORY_OUT else None)

    rows.sort(key=lambda r: (-r.personalized_score, -r.priority_score))
    return _with_discovery_slots(rows, limit)


def _with_discovery_slots(rows, limit):
    """Giữ lại một phần danh sách cho cơ hội mạnh **ngoài** khai báo của RM.

    Đây là chỗ giữ đúng Nguyên tắc 4 — *"Radar phát hiện thứ người dùng không
    biết để đi tìm"*. Nếu chỉ xếp theo điểm cá nhân hoá thì càng khai kỹ, RM
    càng chỉ nhìn thấy thứ họ đã biết mình muốn nhìn: lời khai biến thành cái
    lồng, và Radar thành cái bộ lọc.

    Ba thứ hỏng cùng lúc nếu bỏ phần này:
      • RM không bao giờ thấy cơ hội lớn nằm ngoài địa bàn;
      • quản lý không bao giờ phát hiện việc phân địa bàn đang sai;
      • hệ thống không có cách nào biết lời khai đã cũ.
    """
    if len(rows) <= limit:
        return rows[:limit]

    quota = max(1, int(round(limit * DISCOVERY_RATIO)))
    keep = limit - quota
    chosen = rows[:keep]
    chosen_ids = {row.pk for row in chosen}

    # Suất khám phá xếp theo điểm KHÁCH QUAN, cố tình bỏ qua cá nhân hoá — đó
    # chính là điều làm nó thành "khám phá" chứ không phải phần đuôi của cùng
    # một danh sách.
    rest = sorted((row for row in rows if row.pk not in chosen_ids),
                  key=lambda r: -r.priority_score)
    for row in rest[:quota]:
        row.is_discovery = True
        chosen.append(row)
    return chosen


def _region_coverage(exclude_user=None):
    """{khu vực đã chuẩn hoá: [(user_id, tên hiển thị)]} từ khai báo của mọi RM."""
    from accounts.models import UserWorkProfile

    coverage = {}
    rows = (UserWorkProfile.objects
            .filter(domain=UserWorkProfile.DOMAIN_RB, active=True)
            .exclude(regions=[])
            .select_related("user"))
    for profile in rows:
        if exclude_user is not None and profile.user_id == exclude_user.pk:
            continue
        for region in profile.regions or []:
            key = scoring._normalize(region)
            if not key:
                continue
            name = profile.user.get_full_name() or profile.user.get_username()
            coverage.setdefault(key, []).append(
                {"user_id": profile.user_id, "name": name, "region": region})
    return coverage


def _handoff_candidate(person, coverage):
    """RM nào phụ trách khu vực của khách này. `None` nếu không ai khai.

    Trả về **gợi ý**, không tự chuyển. Chuyển việc cho người khác là quyết định
    của con người — cùng nguyên tắc với `accept()`.
    """
    location = scoring._normalize(getattr(person, "location", ""))
    if not location or not coverage:
        return None
    for region, owners in coverage.items():
        if region in location or location in region:
            return owners[0]
    return None


def work_profile_for(user, domain=None):
    """Hồ sơ công việc bán lẻ của một người dùng. `None` nếu chưa khai báo."""
    from accounts.models import UserWorkProfile

    if user is None or not getattr(user, "pk", None):
        return None
    return UserWorkProfile.objects.filter(
        user=user, domain=domain or UserWorkProfile.DOMAIN_RB, active=True).first()


def summarize(queryset):
    """Các con số ở đầu màn hình "Cơ hội hôm nay"."""
    rows = list(queryset)
    return {
        "total": len(rows),
        "high_priority": sum(1 for r in rows if r.priority_score >= 70),
        "strong_product_fit": sum(1 for r in rows if r.fit_score >= 70),
        "call_now": sum(1 for r in rows
                        if r.recommended_action == OpportunitySuggestion.ACTION_CALL_NOW),
        "reactivation": sum(1 for r in rows
                            if r.recommended_action == OpportunitySuggestion.ACTION_REACTIVATE),
        "fresh_signals": sum(1 for r in rows if r.timing_score >= 100),
    }


def from_signal(signal, owner=None):
    """Tín hiệu tài chính → đề xuất. Đây là chỗ Social Radar nối vào RB Radar.

    Thay thế đường `routing.route_signal()` đi thẳng tới `RBOpportunity`. Vẫn
    ghi `ProductInterest` như cũ — quan tâm sản phẩm là quan sát, và quan sát
    thì không cần ai phê duyệt.
    """
    from . import routing

    evidence = signal.evidence or {}
    text = " ".join(str(evidence.get(key) or "")
                    for key in ("excerpt", "reason", "role"))
    product_suggestions = routing.suggest_products(text,
                                                   base_confidence=signal.confidence)
    if not product_suggestions:
        return []

    interests = routing.record_interests(
        signal.person, product_suggestions, source=signal.source,
        evidence=evidence, observed_at=signal.observed_at)
    by_product = {row.product: row for row in interests}

    made = []
    for item in product_suggestions:
        suggestion, _created = create_or_update(
            signal.person, item.product,
            interest=by_product.get(item.product),
            signals=[signal], need_summary=item.need, owner=owner)
        if suggestion is not None:
            made.append(suggestion)
    return made


def _need_from(interest, signals):
    if interest is not None:
        matched = (interest.evidence or {}).get("matched") or []
        if matched:
            return f"Quan tâm {interest.get_product_display()}"
    for signal in signals or ():
        reason = (signal.evidence or {}).get("reason")
        if reason:
            return str(reason)
    return ""


def _last_outcome(person, product):
    """Kết quả tiếp cận gần nhất cho đúng người + đúng sản phẩm."""
    from .models import OpportunityOutcome

    row = (OpportunityOutcome.objects
           .filter(person=person, opportunity__product=product)
           .order_by("-response_at")
           .values_list("outcome", flat=True)
           .first())
    return row or ""


# ------------------------------------------- SUY RA KHAI BÁO TỪ HÀNH VI THẬT

#: Số việc tối thiểu trước khi dám kết luận điều gì về thói quen của một RM.
#: Dưới ngưỡng này thì im lặng: đoán địa bàn từ hai cơ hội rồi điền sẵn vào form
#: là cách nhanh nhất khiến người dùng mất tin vào toàn bộ tính năng.
MIN_OBSERVATIONS = 3

#: Chỉ giữ khu vực/sản phẩm chiếm ít nhất ngần này trong tổng số việc đã làm.
#: Một cơ hội lẻ ở Cần Thơ không biến Cần Thơ thành địa bàn của ai cả.
OBSERVATION_SHARE = 0.15


def observed_work_profile(user):
    """Suy ra địa bàn và sản phẩm trọng tâm từ việc RM **đã thực sự làm**.

    Vì sao cần: rủi ro lớn nhất của khai báo thủ công là **không ai khai**. Một
    tính năng chỉ chạy khi người dùng chịu điền form là một tính năng chết, và
    lúc đó cá nhân hoá không giúp được ai.

    Nhưng hệ thống đã ghi sẵn đủ dữ liệu để tự suy ra: RM nhận cơ hội ở đâu,
    chốt được sản phẩm nào. Đó là **sở thích bộc lộ qua hành vi** — chính xác
    hơn lời khai, và tốn 0 công sức của người dùng.

    Trả về gợi ý để **điền sẵn** vào form, không tự lưu. Ranh giới giữ nguyên
    như mọi chỗ khác trong module này: máy quan sát và đề xuất, người xác nhận.
    Tự học tự đổi khai báo là việc của giai đoạn sau (Master Plan mục 20, P2) —
    làm sớm thì RM không còn hiểu vì sao danh sách của mình đổi.
    """
    from .models import OpportunityOutcome

    owned = (RBOpportunity.objects
             .filter(assigned_to=user)
             .select_related("person")
             .only("product", "person__location"))
    rows = list(owned[:500])
    if len(rows) < MIN_OBSERVATIONS:
        return {"regions": [], "focus_products": [], "sample_size": len(rows),
                "confident": False}

    regions = _dominant([row.person.location for row in rows], len(rows))
    products = _dominant([row.product for row in rows], len(rows))

    # Sản phẩm CHỐT ĐƯỢC nói nhiều hơn sản phẩm được giao: nếu RM nhận 20 cơ hội
    # thẻ mà chỉ chốt được bảo hiểm thì trọng tâm thật của họ là bảo hiểm.
    converted = list(OpportunityOutcome.objects
                     .filter(created_by=user,
                             outcome=OpportunityOutcome.OUTCOME_CONVERTED)
                     .select_related("opportunity")
                     .values_list("opportunity__product", flat=True)[:200])
    if len(converted) >= MIN_OBSERVATIONS:
        # Đẩy lên đầu, kể cả khi sản phẩm đó ĐÃ có trong danh sách. Bản đầu chỉ
        # thêm khi còn thiếu (`if product not in products`) — nên sản phẩm chốt
        # được nhiều nhất vẫn nằm nguyên chỗ cũ, và cả đoạn này thành vô dụng
        # đúng trong trường hợp nó cần chạy nhất.
        #
        # Duyệt ngược để sản phẩm chốt nhiều nhất kết thúc ở vị trí đầu tiên.
        for product in reversed(_dominant(converted, len(converted))):
            if product in products:
                products.remove(product)
            products.insert(0, product)

    return {"regions": regions, "focus_products": products,
            "sample_size": len(rows), "confident": True}


def _dominant(values, total):
    """Các giá trị chiếm ít nhất `OBSERVATION_SHARE` tổng số, xếp theo tần suất."""
    counts = {}
    for value in values:
        text = str(value or "").strip()
        if text:
            counts[text] = counts.get(text, 0) + 1
    floor = max(1, total * OBSERVATION_SHARE)
    kept = [(name, hits) for name, hits in counts.items() if hits >= floor]
    kept.sort(key=lambda item: (-item[1], item[0]))
    return [name for name, _hits in kept[:5]]
