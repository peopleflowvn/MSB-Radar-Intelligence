# -*- coding: utf-8 -*-
"""④ Sắp xếp + cắt — tất định, bằng CODE. Không có LLM ở chặng này.

## Vì sao Growth không xếp theo độ liên quan

Bên Talent, ④ xếp theo `sort_by` mà người dùng xin, mặc định là độ liên quan
truy hồi. Ở đây mặc định đó SAI. Không ai mở Growth Radar để đọc một danh sách
xếp theo độ khớp chữ — RM mở nó để biết **gọi ai trước**, và hai thứ đó khác
nhau: một khách khớp hoàn hảo nhưng không có số điện thoại, đã có RM khác chăm,
và tín hiệu từ tám tháng trước thì không phải người nên gọi đầu tiên.

Nên mặc định là `rb/scoring.py::priority_score` — công thức năm chiều đã có sẵn
và đang chạy ở Hộp thư cơ hội:

    fit × need × timing × reachability × value  (× hệ số chiến lược)

Dùng lại đúng hàm đó, không viết công thức thứ hai. Hai công thức lệch nhau thì
Radar nói "khách này ưu tiên cao" ở màn hình này và "ưu tiên thấp" ở màn hình
kia, và không ai giải thích được.

## Hai bộ lọc CỨNG chạy trước khi xếp hạng

    da_tu_choi   ③ đọc được lời từ chối trong `[outcome]` → LOẠI. Không phải hạ
                 điểm: chào lại người vừa nói không là mất khách, không phải một
                 kết quả kém tối ưu.
    do_not_contact  đã chặn ở ②; kiểm lại ở đây là lưới thứ hai, vì đây là chỗ
                 CUỐI CÙNG trước khi một cái tên đi ra ngoài.

## `timing` lấy từ bằng chứng, không từ `ProductInterest.observed_at`

`rb/suggestions.py` chấm `timing` theo thời điểm của quan tâm sản phẩm. Ở đây ③
vừa đọc bằng chứng thật và biết cái MỚI NHẤT là bao giờ — kể cả khi nó là một
bài đăng chưa kịp sinh ra `ProductInterest` nào. Dùng số mới hơn là đúng hơn.
"""
from __future__ import annotations

import logging

from django.utils import timezone

log = logging.getLogger(__name__)

#: Ngưỡng tin cậy tối thiểu để một người được coi là "thoả". Dưới mức này vẫn
#: được giữ làm `near_miss` — RM cần thấy "có mấy người gần đúng" thay vì một
#: danh sách rỗng không giải thích được.
MIN_CONFIDENCE = 0.35


def _fold(text):
    from talent.vector_index import fold_text
    return fold_text(text)


def _match_key(extracted, key):
    """Tìm thuộc tính đã bóc theo tên gần đúng ("sản phẩm quan tâm" ~ "san pham")."""
    target = _fold(key)
    if not target:
        return None
    for name, value in (extracted or {}).items():
        folded = _fold(name)
        if folded == target or target in folded or folded in target:
            return value
    return None


def _sortable(value):
    """Giá trị so sánh được, hoặc None. Số ưu tiên hơn chữ."""
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    import re
    match = re.search(r"-?\d+(?:[.,]\d+)?", str(value))
    if match:
        try:
            return float(match.group(0).replace(",", "."))
        except ValueError:
            return None
    return _fold(value) or None


def priority_for(judgement, query_plan, *, person_cache=None):
    """Điểm ưu tiên năm chiều cho một phán đoán.

    Trả `(điểm, [lý do], sản phẩm, {chiều: điểm})`. Trả cả từng chiều chứ không
    chỉ tổng: ⑤ cần chúng để chọn hành động (`scoring.recommend_action` quyết
    theo `need`/`timing`/`reachability` RIÊNG), và tính lại ở ⑤ là hai nơi cùng
    tính một con số — đúng thứ `rb/scoring.py` nói không được có.

    Đọc từ `rb/scoring.py` — không có công thức thứ hai trong hệ thống này.
    """
    from people.models import Person, Signal
    from .. import scoring

    cache = person_cache if person_cache is not None else {}
    person = cache.get(judgement.person_id)
    if person is None:
        person = (Person.objects.filter(pk=judgement.person_id)
                  .select_related("rb_profile")
                  .prefetch_related("relationships", "rb_profile__interests").first())
        cache[judgement.person_id] = person
    if person is None:
        return 0.0, ["Không còn tìm thấy hồ sơ"], "", {}

    profile = getattr(person, "rb_profile", None)
    interests = list(profile.interests.all()) if profile is not None else []

    wanted = list(getattr(query_plan, "products", None) or [])
    if wanted:
        product = wanted[0]
    elif interests:
        product = max(interests, key=lambda row: row.confidence).product
    else:
        product = "consumer_loan"

    interest = next((row for row in interests if row.product == product), None)
    relationship = next((row for row in person.relationships.all()
                         if row.domain == Signal.DOMAIN_RB), None)

    fit, fit_why = scoring.score_fit(person, product, profile=profile)
    need, need_why = scoring.score_need(interest=interest)

    # `timing` từ bằng chứng ③ vừa đọc, không từ `interest.observed_at`: ③ thấy
    # được cả những tín hiệu chưa kịp sinh ra `ProductInterest`. Xem docstring.
    observed = None
    if judgement.freshest_days is not None:
        observed = timezone.now() - timezone.timedelta(days=int(judgement.freshest_days))
    elif interest is not None:
        observed = interest.observed_at
    timing, timing_why = scoring.score_timing(observed)

    reach, reach_why = scoring.score_reachability(person, profile=profile,
                                                  relationship=relationship)
    value, value_why, strategic = scoring.score_value(product)
    score = scoring.priority_score(fit, need, timing, reach, value,
                                   strategic_weight=strategic)
    dimensions = {"fit": fit, "need": need, "timing": timing,
                  "reachability": reach, "value": value}
    return (score, (need_why + fit_why + reach_why + timing_why + value_why),
            product, dimensions)


def aggregate(query_plan, judgements, *, user=None):
    """`[Judgement]` → `(chosen, near_misses, stats)`.

    `chosen`      người sẽ được ⑤ viết về, đã sắp và cắt theo `limit`.
    `near_misses` người gần đúng — để ⑤ nói được "còn N người gần khớp" thay vì
                  im lặng.
    `stats`       số liệu để ⑤ nói thật về phạm vi đã xét.
    """
    from people.models import Relationship, Signal

    judgements = list(judgements)
    stats = {"judged": len(judgements), "relevant": 0, "shown": 0,
             "declined_filtered": 0, "dnc_filtered": 0, "read_failed": False}

    # --- Bộ lọc CỨNG, trước mọi việc xếp hạng ------------------------------
    #
    # Lưới DNC thứ hai. ② đã chặn, nhưng giữa ② và đây có cache sáu tiếng: một
    # khách bật cờ Không liên hệ sáng nay vẫn nằm trong phán đoán đã lưu từ tối
    # qua. Vân tay kho có đổi khi `Relationship` đổi — nhưng đây là chỗ CUỐI CÙNG
    # trước khi một cái tên đi ra ngoài, và một ràng buộc tuân thủ không được
    # phụ thuộc vào việc vân tay cache có tình cờ bắt được thay đổi hay không.
    blocked = set(Relationship.objects.filter(
        person_id__in=[row.person_id for row in judgements],
        domain=Signal.DOMAIN_RB, do_not_contact=True).values_list("person_id", flat=True))

    kept = []
    for row in judgements:
        if row.person_id in blocked:
            stats["dnc_filtered"] += 1
            continue
        if row.declined:
            stats["declined_filtered"] += 1
            continue
        kept.append(row)

    relevant = [row for row in kept
                if row.relevant and row.confidence >= MIN_CONFIDENCE]
    near = [row for row in kept
            if row not in relevant and (row.relevant or row.confidence >= 0.2)]
    stats["relevant"] = len(relevant)

    # --- Xếp hạng ----------------------------------------------------------
    person_cache = {}
    priorities = {}
    for row in relevant:
        score, why, product, dimensions = priority_for(row, query_plan,
                                                       person_cache=person_cache)
        priorities[row.person_id] = {"score": score, "why": why, "product": product,
                                     "dimensions": dimensions}

    sort_by = dict(getattr(query_plan, "sort_by", None) or {})
    key = sort_by.get("key") or ""
    if key:
        # RM nói rõ thứ tự → tôn trọng, và nói ra là đã sắp theo cái gì.
        descending = sort_by.get("dir", "desc") != "asc"
        with_value = [(r, _sortable(_match_key(r.extracted, key))) for r in relevant]
        have = [(r, v) for r, v in with_value if v is not None]
        missing = [r for r, v in with_value if v is None]
        try:
            have.sort(key=lambda item: item[1], reverse=descending)
        except TypeError:
            # Trộn số với chữ trong cùng một cột — so sánh trên dạng chuỗi để
            # vẫn tất định, thay vì ném lỗi giữa lượt.
            have.sort(key=lambda item: str(item[1]), reverse=descending)
        # Người KHÔNG bóc được giá trị xuống cuối, giữ thứ tự ưu tiên giữa họ:
        # không có dữ liệu không phải là "giá trị nhỏ nhất".
        missing.sort(key=lambda r: -priorities.get(r.person_id, {}).get("score", 0.0))
        ordered = [r for r, _ in have] + missing
        stats["sorted_by"] = {"key": key, "dir": sort_by.get("dir", "desc"),
                              "with_value": len(have), "without_value": len(missing)}
    else:
        # Mặc định: mức đáng gọi. Xem docstring module.
        ordered = sorted(
            relevant,
            key=lambda r: (-priorities.get(r.person_id, {}).get("score", 0.0),
                           -r.confidence, r.person_id))
        stats["sorted_by"] = {"key": "priority_score", "dir": "desc"}

    limit = max(1, int(getattr(query_plan, "limit", 20) or 20))
    chosen = ordered[:limit]
    stats["shown"] = len(chosen)

    # Gắn điểm + lý do vào từng người để ⑤ và giao diện dùng chung một con số.
    for row in chosen:
        detail = priorities.get(row.person_id) or {}
        row.criteria = [{"priority_score": detail.get("score", 0.0),
                         "product": detail.get("product", ""),
                         "dimensions": detail.get("dimensions", {}),
                         "why": detail.get("why", [])}]

    near_misses = sorted(near, key=lambda r: -r.confidence)[:5]
    return chosen, near_misses, stats


def enough(chosen, stats, query_plan):
    """Kết quả đã đủ chưa, hay nên nới điều kiện rồi tìm lại.

    "Đủ" không phải "đầy `limit`". Một câu hỏi hẹp trả về đúng ba người là câu
    trả lời tốt; nới thêm chỉ làm loãng. Chỉ nới khi kết quả mỏng tới mức RM
    không làm gì được với nó.
    """
    if stats.get("read_failed"):
        return True                                # nới cũng vô ích, ③ đang hỏng
    limit = max(1, int(getattr(query_plan, "limit", 20) or 20))
    if len(chosen) >= min(3, limit):
        return True
    # ③ đã đọc nhiều mà vẫn không ai thoả ⇒ điều kiện thật sự hẹp, không phải
    # truy hồi hụt. Nới nữa chỉ tốn thêm một vòng ③ để ra cùng kết luận.
    return stats.get("judged", 0) >= 24 and stats.get("relevant", 0) == 0
