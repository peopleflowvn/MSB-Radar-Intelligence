# -*- coding: utf-8 -*-
"""Chấm điểm 5 chiều cho đề xuất cơ hội (Master Plan mục 14.2, 15).

Nguyên tắc bất di bất dịch của module này:

    **LLM không tạo ra bất kỳ con số nào ở đây.**

Vì sao: một "AI Lead Score = 87" không giải thích được là thứ RM sẽ ngừng tin
sau khoảng ba lần gọi trượt. Còn năm con số kèm lý do thì RM có thể phản bác
từng chiều một — và chính việc phản bác được mới làm nên độ tin cậy.

    Fit           Người này có nằm trong khẩu vị sản phẩm không?
    Need          Có bằng chứng họ đang cần không?
    Timing        Bây giờ có phải lúc nên gọi không?
    Reachability  Gọi có gặp được không?
    Value         Nếu trúng thì đáng bao nhiêu?

Bốn chiều đầu nói về *khả năng thành công*. Chiều thứ năm nói về *độ đáng làm* —
và đó là hai câu hỏi khác nhau. Một cơ hội thẻ tín dụng dễ chốt 90% vẫn có thể
đáng làm sau một cơ hội vay mua nhà chỉ 40%, vì thời gian của RM là hữu hạn.
Trộn chúng vào một điểm duy nhất sẽ giấu mất đánh đổi đó.

Mỗi hàm chấm trả về `(điểm, [lý do])`. Lý do là bắt buộc, không phải tuỳ chọn:
`evidence["why"]` trên đề xuất được lắp từ chính các chuỗi này, và màn hình
"Cơ hội hôm nay" hiển thị chúng nguyên văn ở mục **VÌ SAO BÂY GIỜ**.
"""
import logging

from accounts import privacy
from core.vn_locations import canonical_province
from django.utils import timezone

from .models import (PRODUCT_AUTO_LOAN, PRODUCT_CONSUMER_LOAN,
                     PRODUCT_CREDIT_CARD, PRODUCT_FX, PRODUCT_INSURANCE,
                     PRODUCT_INVESTMENT, PRODUCT_MORTGAGE, PRODUCT_PAYROLL,
                     PRODUCT_SAVINGS, OpportunitySuggestion, ProductValueConfig,
                     RBProfile)

log = logging.getLogger(__name__)

#: Trọng số công thức ưu tiên (Master Plan mục 15). Tổng = 1.0.
#:
#: Vì sao Fit/Need/Timing bằng nhau và cùng nặng nhất: thiếu bất kỳ cái nào
#: trong ba thứ đó thì cuộc gọi hỏng — đúng người sai lúc, đúng lúc sai người,
#: hay đúng cả hai mà không có nhu cầu đều dẫn tới cùng một kết quả.
#:
#: Vì sao Reachability nhẹ hơn: thiếu số điện thoại là trở ngại, không phải dấu
#: chấm hết — RM vẫn có thể tìm cách khác. Nhưng nó phải có mặt, nếu không danh
#: sách sẽ đầy những người hay nhất mà không ai gọi được.
#:
#: Vì sao Value nhẹ nhất: nó là chiều **kém chắc chắn nhất** trong năm chiều
#: (xem `ProductValueConfig`). Cho nó trọng số lớn nghĩa là để một con số chưa
#: kiểm chứng lái toàn bộ thứ tự ưu tiên.
WEIGHTS = {
    "fit": 0.25,
    "need": 0.25,
    "timing": 0.25,
    "reachability": 0.15,
    "value": 0.10,
}

#: Dưới ngưỡng này thì không tạo đề xuất. Cao hơn hẳn ngưỡng bên tuyển dụng vì
#: cùng lý do với `routing.MIN_CONFIDENCE`: mời khách vay tiền khi họ không hỏi
#: là chuyện khác hẳn về mặt cảm nhận.
MIN_PRIORITY = 40.0

#: Ngưỡng riêng cho chiều Need, kế thừa `routing.MIN_CONFIDENCE = 0.5`.
#:
#: Vì sao Need cần ngưỡng riêng thay vì để điểm tổng lo: bốn chiều kia có thể
#: **cứu** một nhu cầu mơ hồ. Một người có hồ sơ đẹp, dễ liên hệ, tín hiệu vừa
#: phát sinh hôm qua, sản phẩm giá trị cao — chỉ mỗi việc là ta không thật sự
#: biết họ có cần hay không — vẫn dễ dàng vượt 40 điểm tổng. Gọi cho người đó
#: là gọi cho một người không hỏi gì, và đó đúng là hành vi mà `MIN_CONFIDENCE`
#: sinh ra để chặn. Need là chiều duy nhất không được phép bù trừ.
MIN_NEED = 50.0

#: Điểm tiếp cận khi chưa có số điện thoại lẫn email. Thấp nhưng khác 0 —
#: xem `score_reachability()`.
NO_CONTACT_SCORE = 15.0

#: Đề xuất sống bao lâu nếu không ai đụng tới. Tín hiệu tài chính nguội nhanh.
DEFAULT_TTL_DAYS = 45


# ---------------------------------------------------------------- FIT

#: Nghề nghiệp/bối cảnh gợi ý mức thu nhập, dùng để chấm độ khớp sản phẩm.
#: Cố ý thô: đây là *dấu hiệu*, không phải thẩm định tín dụng. Thẩm định thật
#: nằm ở quy trình phê duyệt của ngân hàng, không phải ở màn hình gợi ý.
SENIOR_HINTS = ["giám đốc", "director", "trưởng phòng", "head of", "quản lý",
                "manager", "ceo", "cfo", "cto", "founder", "chủ tịch",
                "phó tổng", "tổng giám đốc"]
PROFESSIONAL_HINTS = ["senior", "lead", "chuyên viên", "kỹ sư", "engineer",
                      "bác sĩ", "luật sư", "kiến trúc sư", "tech lead"]

#: Sản phẩm nào cần mức thu nhập/vị thế nào. Không phải điều kiện phê duyệt —
#: chỉ là thứ tự ưu tiên khi RM có 20 người và 2 giờ.
PRODUCT_SENIORITY_FIT = {
    PRODUCT_INVESTMENT: "senior",       # quản lý gia sản cần vốn tích luỹ
    PRODUCT_MORTGAGE: "professional",   # vay mua nhà cần thu nhập ổn định
    PRODUCT_AUTO_LOAN: "professional",
    PRODUCT_CREDIT_CARD: "any",
    PRODUCT_SAVINGS: "any",
    PRODUCT_CONSUMER_LOAN: "any",
    PRODUCT_INSURANCE: "any",
    PRODUCT_FX: "any",
    PRODUCT_PAYROLL: "senior",          # quyết định chi lương là của cấp quản lý
}


def score_fit(person, product, profile=None):
    """Người này có nằm trong khẩu vị sản phẩm không? → (0..100, lý do)."""
    reasons = []
    score = 50.0                      # chưa biết gì thì trung tính, không phải 0

    profile = profile if profile is not None else getattr(person, "rb_profile", None)
    occupation = (getattr(profile, "occupation", "") or "").lower()
    employer = (getattr(profile, "employer", "") or "").lower()
    segment = getattr(profile, "segment", "") or ""

    required = PRODUCT_SENIORITY_FIT.get(product, "any")
    is_senior = any(hint in occupation for hint in SENIOR_HINTS)
    is_professional = is_senior or any(hint in occupation for hint in PROFESSIONAL_HINTS)

    if is_senior:
        score += 25
        reasons.append(f"Nghề nghiệp cấp quản lý: {profile.occupation}")
    elif is_professional:
        score += 15
        reasons.append(f"Nghề nghiệp chuyên môn: {profile.occupation}")
    elif occupation:
        reasons.append(f"Nghề nghiệp: {profile.occupation}")
    else:
        # Không biết nghề nghiệp là một khoảng trống thật, phải nói ra chứ không
        # được lẳng lặng cho điểm trung bình rồi để RM tưởng là đã kiểm tra.
        score -= 10
        reasons.append("Chưa biết nghề nghiệp — cần hỏi thêm")

    if required == "senior" and not is_senior:
        score -= 20
        reasons.append("Sản phẩm này thường hợp với cấp quản lý trở lên")
    elif required == "professional" and not is_professional:
        score -= 10
        reasons.append("Sản phẩm này cần thu nhập ổn định — chưa xác nhận được")

    if segment == RBProfile.SEGMENT_PRIORITY:
        score += 15
        reasons.append("Phân khúc Ưu tiên")
    elif segment == RBProfile.SEGMENT_AFFLUENT:
        score += 10
        reasons.append("Phân khúc Khá giả")

    if employer:
        score += 5
        reasons.append(f"Nơi làm việc: {profile.employer}")

    return _clamp(score), reasons


# ---------------------------------------------------------------- NEED

def score_need(interest=None, signals=(), evidence=None):
    """Có bằng chứng người này đang cần không? → (0..100, lý do).

    Nguồn bằng chứng mạnh nhất là chính lời khách nói ra (tín hiệu xã hội, câu
    hỏi trực tiếp). Suy luận từ hồ sơ yếu hơn hẳn, và phải hiện ra là suy luận.
    """
    reasons = []
    score = 0.0

    if interest is not None:
        # `ProductInterest.confidence` là 0..1 và đã được `routing` tính từ số
        # cụm từ khớp — dùng lại chứ không tính lại, để hai chỗ không lệch nhau.
        score = interest.confidence * 100
        matched = (interest.evidence or {}).get("matched") or []
        if matched and matched != ["suy ra từ nhu cầu chính"]:
            reasons.append("Khách nhắc tới: " + ", ".join(str(m) for m in matched[:3]))
        elif matched:
            reasons.append("Suy ra từ nhu cầu chính, khách chưa nói trực tiếp")

    signal_list = list(signals)
    if signal_list:
        strongest = max(s.confidence for s in signal_list)
        score = max(score, strongest * 100)
        if len(signal_list) > 1:
            # Nhiều tín hiệu độc lập cùng chỉ về một nhu cầu thì đáng tin hơn
            # một tín hiệu mạnh đơn lẻ — nhưng không được vượt trần.
            score = min(100.0, score + 5 * (len(signal_list) - 1))
            reasons.append(f"{len(signal_list)} tín hiệu độc lập cùng chỉ về nhu cầu này")
        excerpt = ""
        for signal in signal_list:
            excerpt = (signal.evidence or {}).get("excerpt") or ""
            if excerpt:
                break
        if excerpt:
            # Che liên hệ NẰM TRONG trích dẫn. Người ta thường tự viết số điện
            # thoại vào bài đăng, và trích dẫn này hiện thẳng trên thẻ «Cơ hội
            # hôm nay» — không che ở đây thì hạn mức mở khoá bị đi vòng qua
            # bằng một đường không ai nghĩ tới mà đi kiểm.
            reasons.append(f"Trích: “{privacy.redact_contacts(excerpt)[:120]}”")

    if not reasons:
        reasons.append("Chưa có bằng chứng nhu cầu rõ ràng")

    return _clamp(score), reasons


# ---------------------------------------------------------------- TIMING

#: Bậc thang tuổi tín hiệu (Master Plan mục 14.2): 7 ngày = 100, 30 = 70,
#: 90 = 30. Bậc thang chứ không phải hàm mũ liên tục vì RM cần đọc được: "trong
#: tuần này" và "tháng trước" là hai loại việc khác nhau, còn 6,4 ngày so với
#: 7,1 ngày thì không.
TIMING_BANDS = [
    (7, 100.0, "Tín hiệu trong 7 ngày qua"),
    (30, 70.0, "Tín hiệu trong 30 ngày qua"),
    (90, 40.0, "Tín hiệu trong 90 ngày qua"),
    (180, 20.0, "Tín hiệu cũ hơn 90 ngày"),
]


def score_timing(observed_at, now=None):
    """Bây giờ có phải lúc nên tiếp cận không? → (0..100, lý do)."""
    if observed_at is None:
        return 30.0, ["Không rõ thời điểm phát sinh nhu cầu"]

    now = now or timezone.now()
    age_days = max(0, (now - observed_at).days)

    for limit, score, label in TIMING_BANDS:
        if age_days <= limit:
            return score, [f"{label} ({age_days} ngày trước)"]
    return 10.0, [f"Tín hiệu đã {age_days} ngày — nhiều khả năng đã nguội"]


# ---------------------------------------------------------------- REACHABILITY

def score_reachability(person, profile=None, relationship=None):
    """Có gọi được không? → (0..100, lý do).

    Phân biệt hai thứ dễ bị gộp nhầm:

        DNC             điều kiện **chặn** — trả 0, và `suggestions.py` dựa vào
                        số 0 này để không tạo đề xuất nào cả.
        Chưa có liên hệ trở ngại, **không phải** dấu chấm hết — vẫn chấm điểm
                        thấp và để đề xuất đi tiếp.

    Gộp hai thứ này lại (cho cả hai về 0) là bỏ mất đúng nhóm khách đáng giá
    nhất của Social Radar: người vừa lộ nhu cầu rõ ràng trên mạng xã hội nhưng
    ta chưa có số. Việc cần làm với họ là *đi xin số* — đó là lý do
    `recommend_action()` trả `ASK_FOR_INFORMATION` cho đúng trường hợp này.
    """
    reasons = []

    if relationship is not None and getattr(relationship, "do_not_contact", False):
        return 0.0, ["Khách đã bật cờ Không liên hệ (DNC)"]

    score = 0.0
    if person.primary_phone:
        score += 55
        reasons.append("Có số điện thoại")
    if person.primary_email:
        score += 25
        reasons.append("Có email")
    if not reasons:
        return NO_CONTACT_SCORE, ["Chưa có số điện thoại hoặc email — cần xin thông tin liên hệ"]

    profile = profile if profile is not None else getattr(person, "rb_profile", None)
    last_contact = getattr(profile, "last_contact_at", None)
    if last_contact is not None:
        age_days = max(0, (timezone.now() - last_contact).days)
        if age_days < 7:
            # Vừa gọi tuần trước mà gọi tiếp là làm phiền, không phải chăm sóc.
            score -= 25
            reasons.append(f"Vừa liên hệ {age_days} ngày trước — nên giãn cách")
        elif age_days > 180:
            score += 10
            reasons.append("Đã lâu không liên hệ — quan hệ cần được làm ấm lại")
        else:
            score += 20
            reasons.append(f"Lần liên hệ gần nhất {age_days} ngày trước")
    else:
        reasons.append("Chưa từng liên hệ")

    return _clamp(score), reasons


# ---------------------------------------------------------------- VALUE

def score_value(product):
    """Nếu chốt được thì đáng bao nhiêu? → (0..100, lý do, hệ số chiến lược).

    Đọc từ `ProductValueConfig` chứ không từ hằng số trong code — lý do đầy đủ
    nằm trong docstring của model đó.
    """
    config = ProductValueConfig.objects.filter(product=product, active=True).first()
    if config is None:
        # Chưa cấu hình thì trung tính, và nói rõ là chưa cấu hình. Đoán bừa một
        # con số cao ở đây sẽ đẩy sản phẩm chưa ai xét lên đầu danh sách.
        return 50.0, ["Chưa cấu hình giá trị cho nhóm sản phẩm này"], 1.0

    score = config.effective_value_score
    if config.value_weight > 0:
        reason = f"Giá trị kỳ vọng đã cấu hình: {config.value_weight:.0f}"
    else:
        reason = f"Giá trị kỳ vọng: {config.get_value_band_display()}"

    reasons = [reason]
    if config.strategic_weight > 1.0:
        reasons.append(f"Sản phẩm đang được ưu tiên đẩy mạnh (×{config.strategic_weight:.2f})")
    return _clamp(score), reasons, config.strategic_weight


# ---------------------------------------------------------------- TỔNG HỢP

def priority_score(fit, need, timing, reachability, value, strategic_weight=1.0):
    """Điểm ưu tiên tất định. Đây là hàm duy nhất được phép sinh ra con số này.

    Hệ số chiến lược **nhân** vào cuối chứ không cộng: một sản phẩm đang được
    đẩy mạnh phải nổi lên trong cả danh sách chứ không chỉ nhích vài điểm, và
    nhân giữ nguyên thứ tự tương đối trong cùng nhóm sản phẩm.
    """
    base = (fit * WEIGHTS["fit"]
            + need * WEIGHTS["need"]
            + timing * WEIGHTS["timing"]
            + reachability * WEIGHTS["reachability"]
            + value * WEIGHTS["value"])
    return round(_clamp(base * strategic_weight), 2)


def recommend_action(suggestion_scores, has_contact=True,
                     has_open_opportunity=False, previous_outcome=""):
    """Next Best Action (Master Plan mục 34). Mã hành động do CODE quyết định.

    LLM được phép soạn *nội dung* cho hành động này, nhưng không được chọn nó —
    chọn sai hành động là chuyện nghiệp vụ, không phải chuyện ngôn ngữ.

    `has_contact` là tham số riêng chứ không suy ra từ `reachability`: điểm tiếp
    cận là một thang liên tục có thể chỉnh, còn "có kênh liên hệ hay không" là
    một sự thật nhị phân. Suy cái thứ hai từ cái thứ nhất nghĩa là mỗi lần ai đó
    tinh chỉnh `NO_CONTACT_SCORE` thì hành động đề xuất lặng lẽ đổi theo.
    """
    from .models import OpportunityOutcome

    reachability = suggestion_scores.get("reachability", 0)
    need = suggestion_scores.get("need", 0)
    timing = suggestion_scores.get("timing", 0)
    priority = suggestion_scores.get("priority", 0)

    if not has_contact or reachability <= 0:
        # Chưa có kênh liên hệ thì việc cần làm là đi xin thông tin — mọi hành
        # động khác (gọi, nhắn, hẹn gặp) đều chưa thực hiện được.
        return OpportunitySuggestion.ACTION_ASK_FOR_INFORMATION

    if previous_outcome and previous_outcome in OpportunityOutcome.REACTIVATABLE:
        return OpportunitySuggestion.ACTION_REACTIVATE

    if has_open_opportunity:
        return OpportunitySuggestion.ACTION_FOLLOW_UP

    if need >= 70 and timing >= 70 and reachability >= 55:
        # Nhu cầu rõ + còn nóng + gọi được = gọi ngay. Đây là trường hợp duy
        # nhất đáng cắt ngang việc khác của RM.
        return OpportunitySuggestion.ACTION_CALL_NOW

    if priority >= 70 and need >= 60:
        return OpportunitySuggestion.ACTION_INVITE_MEETING

    if timing < 40:
        return OpportunitySuggestion.ACTION_WAIT

    if need < 45:
        return OpportunitySuggestion.ACTION_ASK_FOR_INFORMATION

    return OpportunitySuggestion.ACTION_SEND_MESSAGE


# ------------------------------------------------- CÁ NHÂN HOÁ THEO NGƯỜI DÙNG

#: Mức cộng/trừ tối đa của cá nhân hoá, tính theo điểm tuyệt đối trên thang 100.
#:
#: Cố ý giới hạn ở ±20 chứ không để tự do: cá nhân hoá là để **sắp xếp lại**
#: những cơ hội đều đáng làm, không phải để đẩy một cơ hội yếu lên đầu chỉ vì nó
#: trúng sản phẩm đang được giao chỉ tiêu. Một khoản vay có nhu cầu mơ hồ vẫn
#: phải xếp sau một khoản vay nhu cầu rõ ràng, kể cả khi RM đang chạy chỉ tiêu
#: đúng nhóm sản phẩm đó.
PERSONALIZATION_CAP = 20.0

MATCH_FOCUS_PRODUCT = 12.0
MATCH_REGION = 8.0
MATCH_SEGMENT = 5.0

#: Phạt khi khách nằm ngoài địa bàn — **cố ý nhỏ**.
#:
#: Bản đầu để -10, và đó là sai hướng: khách Đà Nẵng có nhu cầu vay 5 tỷ bị trừ
#: điểm → tụt hạng → không ai gọi → **ngân hàng mất khách**. Trừ điểm nặng biến
#: một cơ hội cần *định tuyến* thành một cơ hội bị *đánh rơi*.
#:
#: Cách xử lý đúng gồm ba phần, và con số này chỉ là một phần ba:
#:   1. phạt nhẹ — vì đúng là việc này nhiều khả năng không phải của tôi;
#:   2. `territory_of()` gắn nhãn rõ + gợi ý RM phụ trách để chuyển giao;
#:   3. suất khám phá trong `todays_best()` bảo đảm cơ hội mạnh vẫn hiện ra.
MISS_REGION = -4.0

#: Kết quả đối chiếu địa bàn. Tách thành ba giá trị chứ không phải cờ đúng/sai:
#: "không biết khách ở đâu" khác hẳn "biết và nằm ngoài" — gộp lại thì mọi hồ sơ
#: thiếu dữ liệu bị đối xử như nằm ngoài địa bàn.
TERRITORY_IN = "in"
TERRITORY_OUT = "out"
TERRITORY_UNKNOWN = "unknown"


def territory_of(profile, person):
    """Khách này nằm trong hay ngoài địa bàn của người đang xem."""
    raw_regions = [str(r) for r in (getattr(profile, "regions", None) or []) if str(r).strip()]
    if not raw_regions:
        return TERRITORY_UNKNOWN

    raw_location = str(getattr(person, "location", "") or "")
    if not raw_location.strip():
        return TERRITORY_UNKNOWN

    location = _normalize(raw_location)
    # Chuẩn hoá bí danh tỉnh/thành ("TP.HCM" == "Hồ Chí Minh") trước khi so —
    # RM khai địa bàn theo cách viết này, khách trong hồ sơ lại ghi theo cách
    # viết khác; không chuẩn hoá thì đối chiếu địa bàn âm thầm khớp trượt dù
    # cùng một tỉnh/thành (xem core/vn_locations.py).
    canon_location = _normalize(canonical_province(raw_location))
    for raw_region in raw_regions:
        region = _normalize(raw_region)
        canon_region = _normalize(canonical_province(raw_region))
        if region in location or location in region or canon_region == canon_location:
            return TERRITORY_IN
    return TERRITORY_OUT


def personalize(suggestion, profile, person=None):
    """Điểm phù hợp với người đang xem → (điểm đã điều chỉnh, lý do).

    Trả về **điểm mới**, không ghi đè `suggestion.priority_score`. Lý do đầy đủ
    nằm trong docstring của `accounts.UserWorkProfile`; tóm tắt: điểm lưu phải
    giữ nghĩa khách quan để còn so sánh và kiểm toán được.

    `profile is None` (người dùng chưa khai báo gì) trả nguyên điểm gốc — hệ
    thống phải dùng được ngay khi chưa ai điền form nào.
    """
    base = suggestion.priority_score
    if profile is None or not profile.active:
        return base, []

    person = person or suggestion.person
    reasons = []
    delta = 0.0

    focus = list(profile.focus_products or [])
    if focus and suggestion.product in focus:
        delta += MATCH_FOCUS_PRODUCT
        reasons.append("Thuộc nhóm sản phẩm bạn đang phụ trách")

    territory = territory_of(profile, person)
    if territory == TERRITORY_IN:
        delta += MATCH_REGION
        reasons.append("Nằm trong địa bàn bạn phụ trách")
    elif territory == TERRITORY_OUT:
        delta += MISS_REGION
        reasons.append("Ngoài địa bàn bạn phụ trách — cân nhắc chuyển giao")
    elif profile.regions:
        # Không biết khách ở đâu thì không phạt: thiếu dữ liệu là lỗi của hệ
        # thống, không phải bằng chứng khách nằm ngoài địa bàn.
        reasons.append("Chưa rõ khu vực của khách")

    segments = list(profile.target_segments or [])
    if segments and person is not None:
        segment = getattr(getattr(person, "rb_profile", None), "segment", "")
        if segment and segment in segments:
            delta += MATCH_SEGMENT
            reasons.append("Đúng phân khúc khách hàng bạn nhắm tới")

    delta = max(-PERSONALIZATION_CAP, min(PERSONALIZATION_CAP, delta))
    return round(_clamp(base + delta), 2), reasons


def _normalize(text):
    """Bỏ dấu + chữ thường, để 'Hà Nội' khớp 'ha noi' và 'Hanoi'."""
    import unicodedata

    stripped = unicodedata.normalize("NFD", str(text or ""))
    stripped = "".join(ch for ch in stripped if unicodedata.category(ch) != "Mn")
    return stripped.replace("đ", "d").replace("Đ", "D").lower().strip()


def _clamp(value, low=0.0, high=100.0):
    return float(max(low, min(high, value)))
