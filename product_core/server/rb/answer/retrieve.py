# -*- coding: utf-8 -*-
"""② Truy hồi khách hàng tiềm năng — CODE thuần, không LLM.

## Khác Talent ở chỗ nào, và vì sao

Talent có một kho text lớn đã lập chỉ mục vector (`PersonSearchDocument`,
`CVChunk`), nên ② ở đó là *tìm trong một biển văn bản*. Growth thì ngược lại:
bằng chứng nằm rải trong nhiều bảng có cấu trúc, mỗi bảng đã có chỉ mục theo
thời gian, và **không bảng nào có vector**.

Nên ② ở đây không giả vờ làm truy hồi ngữ nghĩa. Nó làm đúng thứ dữ liệu cho
phép: dựng pool từ những đường ĐÃ CÓ CHỈ MỤC, rồi hợp nhất bằng RRF có trọng số.

    social    bài khách tự viết       `SocialPost(person, -posted_at)`
    signal    tín hiệu đã xử lý       `Signal(person, -observed_at)`
    interest  quan tâm sản phẩm       `ProductInterest(-observed_at)`
    outcome   kết quả tiếp cận trước  `OpportunityOutcome(-created_at)`
    profile   nền tĩnh                `RBProfile(lead_status, -updated_at)`

## Trọng số nhánh — đây là chỗ Growth khác Talent nhiều nhất

Bên Talent mọi nhánh ngang nhau, và đúng: một câu khớp trong CV không đáng tin
hơn hay kém một câu khớp khác. Ở đây thì KHÔNG ngang nhau, vì các nhánh khác
nhau về *bản chất bằng chứng*:

    lời khách tự nói ra   >  tín hiệu ta suy ra  >  thuộc tính hồ sơ

"Có ai cho vay mua chung cư không ạ" do chính khách viết là bằng chứng mạnh hơn
hẳn việc nghề nghiệp của họ khớp chữ "quản lý". Trọng số ghi lại đúng thứ tự đó,
và `core/answer/fusion.py` nhận nó như một tham số chứ không phải một trường hợp
đặc biệt.

## Độ mới nằm TRONG truy hồi, không phải một bộ lọc

`rb/prospects.py` cũ có `signal_recency_days` như một công tắc: hoặc lọc, hoặc
không. Nhưng tín hiệu mua hàng mất giá LIÊN TỤC, không phải rơi khỏi vách đá tại
ngày thứ 90. Nên mỗi nhánh xếp theo thời gian giảm dần và RRF lo phần còn lại —
một tín hiệu ba ngày trước tự nhiên đứng trên một tín hiệu tám tháng trước, mà
không ai phải chọn một con số ngày.

## Ràng buộc tuân thủ là CỔNG, không phải bộ lọc

`do_not_contact` và phạm vi theo RM áp ở đây, trước khi bất cứ thứ gì được xếp
hạng — và tuyệt đối không áp ở ⑤ bằng lời dặn trong prompt. Một ràng buộc tuân
thủ nằm trong prompt là một ràng buộc chưa có.
"""
from __future__ import annotations

import logging

from core.answer.fusion import reciprocal_rank_fusion
from django.db.models import Q
from django.utils import timezone
from people.models import Person, Signal

from . import evidence as evidence_stage
from .evidence import Candidate

log = logging.getLogger(__name__)

#: Trần số khách ĐỌC KỸ ở ③ (ngân sách token một lượt).
POOL = 60
#: Sàn — dưới mức này ③ không còn gì để loại, và câu "có ai … không?" cần mẫu
#: đủ rộng mới trả lời trung thực được.
MIN_POOL = 16
#: Trần tập khách được phép mỗi lượt (sau cổng tuân thủ và bộ lọc cứng).
MAX_ELIGIBLE = 5000
#: Trần mỗi nhánh. RRF cần dư ứng viên để xếp hạng khi kho lớn.
PER_BRANCH = 120

#: Trọng số theo BẢN CHẤT bằng chứng, không theo độ tiện của truy vấn.
#: Xem docstring module.
BRANCH_WEIGHTS = {
    # Gần NGHĨA với câu hỏi, trên chính bằng chứng khách viết/đã quan sát. Thấp
    # hơn `social` một chút: khớp nghĩa là xấp xỉ, còn khớp chữ trên lời khách là
    # bằng chứng trực tiếp — nhưng cao hơn mọi nhánh suy ra.
    "semantic": 1.3,
    "social": 1.4,      # chính lời khách viết ra
    "signal": 1.2,      # tín hiệu đã xử lý, vẫn là quan sát thật
    "interest": 1.0,    # suy ra có căn cứ
    "outcome": 0.9,     # chuyện đã xảy ra — mạnh, nhưng là quá khứ
    "profile": 0.6,     # thuộc tính tĩnh, yếu nhất
    # Hồ sơ CV: nền nghề nghiệp để SUY LUẬN nhu cầu, không phải lời khách nói ra.
    # Ngang `profile` — cùng là thuộc tính tĩnh, chỉ giàu chữ hơn.
    "cv": 0.6,
}


def _fold(text):
    from talent.vector_index import fold_text
    return fold_text(text)


def _terms(queries, *, limit=16, min_len=3):
    out = []
    for query in queries:
        for token in _fold(query).split():
            if len(token) >= min_len and token not in out:
                out.append(token)
    return out[:limit]


def pool_for(query_plan, cap=POOL):
    """Số khách mang sang ③, theo số hồ sơ RM thật sự muốn.

    ③ là chặng đắt nhất. Hỏi "5 khách đáng gọi nhất" mà đọc kỹ 60 hồ sơ để rồi
    hiển thị 5 là trả tiền cho 55 hồ sơ không ai nhìn.

    Câu TỔNG HỢP (`analyze`) lấy pool tối thiểu: câu trả lời thật nằm ở số liệu
    toàn kho, mấy hồ sơ truy hồi được chỉ là ví dụ minh hoạ.
    """
    if getattr(query_plan, "shape", "") == "analyze":
        return MIN_POOL
    limit = max(1, int(getattr(query_plan, "limit", 20) or 20))
    return max(MIN_POOL, min(cap, limit * 4))


# ------------------------------------------------------------------ cổng tuân thủ

def eligible_people(query_plan, *, user=None):
    """Tập người ĐƯỢC PHÉP xuất hiện, trước mọi việc xếp hạng.

    Trả một queryset `Person` đã áp:

    * loại người đã gộp;
    * **loại `do_not_contact`** — ràng buộc tuân thủ, áp kể cả khi RM hỏi đích
      danh nhóm đó;
    * phạm vi theo shape: `portfolio` giới hạn vào danh mục của chính RM,
      `whitespace` giới hạn vào khách chưa ai phụ trách;
    * các bộ lọc cứng mà ① bóc được.
    """
    from ..models import RBOpportunity

    from .population import customers, do_not_contact_ids

    # Khách hàng, không phải toàn bảng `Person` (dùng chung với ứng viên) — xem
    # `population.py` cho hai lỗi mà định nghĩa cũ gây ra.
    queryset = customers()

    # Không bao giờ được xuất hiện. Đặt ĐẦU TIÊN để không ai đọc nhầm nó như
    # một bộ lọc tuỳ chọn nằm lẫn giữa các bộ lọc khác.
    queryset = queryset.exclude(pk__in=do_not_contact_ids())

    shape = getattr(query_plan, "shape", "")
    if shape == "portfolio":
        # Đây là lần đầu trong hệ thống danh tính người hỏi ĐỔI TẬP KẾT QUẢ.
        # Không có user thì trả rỗng chứ KHÔNG lặng lẽ rơi về toàn kho: "khách
        # của tôi" mà trả khách của người khác là RM gọi nhầm người đồng nghiệp
        # đang chăm — hỏng đắt hơn nhiều so với một danh sách rỗng.
        if user is None or not getattr(user, "pk", None):
            log.warning("rb.answer.retrieve: shape=portfolio nhưng không có user")
            return queryset.none()
        queryset = queryset.filter(rb_profile__sales_owner_id=user.pk)
    elif shape == "whitespace":
        queryset = queryset.filter(rb_profile__sales_owner__isnull=True).exclude(
            rb_opportunities__status__in=RBOpportunity.OPEN_STATUSES)

    filters = dict(getattr(query_plan, "filters", None) or {})
    if filters.get("tinh_thanh"):
        from core.vn_locations import location_query_variants
        where = Q()
        for variant in location_query_variants(filters["tinh_thanh"]):
            where |= Q(location__icontains=variant)
        queryset = queryset.filter(where)
    if filters.get("phan_khuc"):
        queryset = queryset.filter(rb_profile__segment=filters["phan_khuc"])
    if filters.get("phai_co_lien_he"):
        queryset = queryset.exclude(primary_phone="", primary_email="")
    if filters.get("cap_bac"):
        from .. import scoring
        hints = (scoring.SENIOR_HINTS if filters["cap_bac"] == "manager"
                 else ["giám đốc", "ceo", "cfo", "cto", "founder", "chủ tịch",
                       "tổng giám đốc"])
        where = Q()
        for hint in hints:
            where |= Q(rb_profile__occupation__icontains=hint)
            # Không lọc theo `headline` (vị trí ứng tuyển) — ứng tuyển vị trí giám
            # đốc không làm người đó thành giám đốc. Chức danh trùng headline là
            # dữ liệu cũ ghi sai, cũng loại.
            where |= (Q(talent_profile__current_title__icontains=hint)
                      & ~Q(talent_profile__current_title=F("headline")))
            where |= Q(talent_profile__seniority__icontains=hint)
        queryset = queryset.filter(where)
    if filters.get("kinh_nghiem_tu"):
        try:
            min_exp = float(filters["kinh_nghiem_tu"])
            queryset = queryset.filter(
                Q(talent_profile__years_experience__gte=min_exp) |
                Q(talent_profile__years_experience__isnull=True)
            )
        except (ValueError, TypeError):
            pass
    if filters.get("loai_co_hoi_dang_mo"):
        queryset = queryset.exclude(
            rb_opportunities__status__in=RBOpportunity.OPEN_STATUSES)

    # `products` KHÔNG phải cổng. Cố ý không lọc theo nó ở đây.
    #
    # ① suy ra `san_pham` từ câu hỏi — đó là một SUY LUẬN về nhóm sản phẩm liên
    # quan, không phải một điều kiện RM nói ra. Lọc cứng theo
    # `rb_profile__interests__product` nghĩa là chỉ ai ĐÃ có `ProductInterest`
    # mới được xét, tức loại đúng người mà Growth tồn tại để tìm: khách tự viết
    # "em cần vay mua xe" nhưng hệ thống chưa kịp suy ra quan tâm nào. Lời khách
    # tự nói là bằng chứng MẠNH NHẤT (xem `BRANCH_WEIGHTS`), và một bộ lọc chặn
    # nó trước khi truy hồi là tái tạo nguyên lỗi của `rb/prospects.py`.
    #
    # `products` vẫn có tác dụng — ở nhánh `interest` (xếp hạng) và ở ④ (chọn
    # sản phẩm để chấm điểm), tức nó ĐẨY LÊN người có quan tâm rõ, chứ không
    # LOẠI người chưa có.

    days = filters.get("tin_hieu_trong_ngay") or 0
    if days:
        since = timezone.now() - timezone.timedelta(days=int(days))
        queryset = queryset.filter(signals__domain=Signal.DOMAIN_RB,
                                   signals__observed_at__gte=since)

    # `RBProfile` không bắt buộc: một người có hồ sơ CV (TalentProfile) hoặc mới
    # bắt được từ mạng xã hội chưa có hồ sơ bán lẻ vẫn là khách tiềm năng.
    # Chỉ đòi có RBProfile khi câu hỏi thật sự cần phân khúc bán lẻ cụ thể.
    if shape == "portfolio" or any(k in filters for k in ("phan_khuc",)):
        queryset = queryset.filter(rb_profile__isnull=False)
    return queryset.distinct()


# ----------------------------------------------------------------- các nhánh

def _social_ids(allowed_ids, terms, limit):
    from social.models import SocialPost

    queryset = (SocialPost.objects.filter(person_id__in=allowed_ids)
                .exclude(person__isnull=True))
    if terms:
        where = Q()
        for term in terms:
            where |= Q(content__icontains=term)
        queryset = queryset.filter(where)
    return list(queryset.order_by("-posted_at", "-created_at")
                .values_list("person_id", flat=True)[:limit])


def _signal_ids(allowed_ids, terms, limit):
    from django.db.models import TextField
    from django.db.models.functions import Cast

    queryset = Signal.objects.filter(person_id__in=allowed_ids,
                                     domain=Signal.DOMAIN_RB)
    if terms:
        # `evidence` là JSONField. `icontains` KHÔNG phải lookup hợp lệ của
        # JSONField (Django hiểu `contains` trên JSON là phép bao hàm JSON, ngữ
        # nghĩa khác hẳn, và trên jsonb thì `icontains` ném lỗi). Ép sang text
        # rồi mới khớp chữ — thô, nhưng đúng và chạy được trên cả PostgreSQL lẫn
        # SQLite. Xem "Giới hạn đã biết" ở `coverage()`.
        queryset = queryset.annotate(_evidence_text=Cast("evidence", TextField()))
        where = Q()
        for term in terms:
            where |= Q(signal_type__icontains=term)
            where |= Q(_evidence_text__icontains=term)
        queryset = queryset.filter(where)
    return list(queryset.order_by("-observed_at")
                .values_list("person_id", flat=True)[:limit])


def _interest_ids(allowed_ids, products, limit):
    from ..models import ProductInterest

    queryset = ProductInterest.objects.filter(profile__person_id__in=allowed_ids)
    if products:
        queryset = queryset.filter(product__in=products)
    # Xếp theo ĐỘ TIN CẬY trước, rồi mới độ mới: một quan tâm chắc chắn tháng
    # trước đáng hơn một suy đoán mơ hồ hôm qua.
    return list(queryset.order_by("-confidence", "-observed_at")
                .values_list("profile__person_id", flat=True)[:limit])


def _outcome_ids(allowed_ids, limit):
    """Người từng được tiếp cận và kết quả CHO PHÉP quay lại.

    Đây là Reactivation Radar: `MAYBE_LATER` và `NO_RESPONSE` là khách đáng gọi
    lại, còn `NOT_INTERESTED`/`ALREADY_USING` thì không — xem
    `rb/models.py::OpportunityOutcome.REACTIVATABLE`.
    """
    from ..models import OpportunityOutcome

    return list(OpportunityOutcome.objects
                .filter(person_id__in=allowed_ids,
                        outcome__in=OpportunityOutcome.REACTIVATABLE)
                .order_by("-created_at")
                .values_list("person_id", flat=True)[:limit])


def _profile_ids(allowed_ids, terms, limit):
    from ..models import RBProfile

    queryset = RBProfile.objects.filter(person_id__in=allowed_ids)
    if terms:
        where = Q()
        for term in terms:
            where |= Q(occupation__icontains=term)
            where |= Q(employer__icontains=term)
            where |= Q(interaction_summary__icontains=term)
        queryset = queryset.filter(where)
    return list(queryset.order_by("-updated_at")
                .values_list("person_id", flat=True)[:limit])


def _cv_ids(allowed_ids, queries, limit):
    """Khớp chữ trên hồ sơ CV, qua projection `PersonSearchDocument` của Talent.

    Là nhánh RIÊNG, không nhét vào `profile`: bản 18/09 nối kết quả CV vào đuôi
    `_profile_ids` nên hai nguồn khác bản chất bị tính chung một phiếu RRF, và
    phần CV được xếp theo SỐ NĂM KINH NGHIỆM — tức người thâm niên nhất kho luôn
    đứng đầu, bất kể có khớp câu hỏi hay không.

    Tìm trên `content_norm` (đã bỏ dấu) bằng full-text có chỉ mục GIN, xếp theo
    độ khớp. Bản cũ đem token đã BỎ DẤU ("giam", "doc") đi `icontains` trên cột
    CÒN DẤU ("Giám đốc") nên gần như không khớp đúng, chỉ khớp nhầm chuỗi con
    ("doc" trong "document"), và quét 11 cột không chỉ mục trên cả tập được
    phép — chậm theo kích thước kho.
    """
    from talent.models import CVChunk, PersonSearchDocument
    from talent.vector_index import fts_tokens

    tokens = fts_tokens(" ".join(queries or []), limit=24)
    if not tokens or not allowed_ids:
        return []
    # Projection trước (trường có cấu trúc: chức danh, công ty, kỹ năng, ngành),
    # rồi tới đoạn CV gốc — nơi duy nhất có ngoại ngữ, hình thức làm việc, sở
    # thích… mà projection không chép sang.
    out = []
    for model, field in ((PersonSearchDocument, "content_norm"), (CVChunk, "text_norm")):
        base = model.objects.filter(person_id__in=allowed_ids)
        for person_id in _ranked_fts(base, field, tokens, limit):
            if person_id not in out:
                out.append(person_id)
    return out[:limit]


def _ranked_fts(queryset, field, tokens, limit):
    """person_id khớp full-text, xếp theo độ khớp; SQLite lùi về icontains."""
    from django.db import connection

    if connection.vendor == "postgresql":
        from django.contrib.postgres.search import SearchQuery, SearchRank, SearchVector
        vector = SearchVector(field, config="simple")
        query = SearchQuery(" | ".join(tokens), config="simple", search_type="raw")
        rows = (queryset.annotate(_sv=vector).filter(_sv=query)
                .annotate(_rank=SearchRank(vector, query))
                .order_by("-_rank", "person_id"))
    else:
        where = Q()
        for token in tokens:
            if len(token) >= 3:
                where |= Q(**{f"{field}__icontains": token})
        if not where:
            return []
        rows = queryset.filter(where).order_by("person_id")
    # Một người nhiều đoạn khớp: lấy dư rồi bỏ trùng, giữ thứ hạng tốt nhất.
    return list(dict.fromkeys(rows.values_list("person_id", flat=True)[:limit * 3]))[:limit]


#: Số truy vấn của ① được đem đi tìm theo nghĩa — mỗi cái là một lời gọi embedding.
SEMANTIC_QUERIES = 3


class _DenseBranch:
    """Nhánh vector, TẮT cho cả lượt ngay khi lỗi lần đầu.

    Nhà cung cấp embedding chết mà vẫn thử đủ mọi truy vấn thì riêng phần chờ
    timeout đã ăn hết ngân sách của lượt — cùng lý do với
    `talent/answer/retrieve.py::_DenseBranch`.
    """

    def __init__(self):
        self.disabled = False

    def __call__(self, queries, allowed_ids, limit):
        from rb import evidence_index
        lists = []
        for query in queries[:SEMANTIC_QUERIES]:
            if self.disabled:
                break
            try:
                ids = evidence_index.dense_person_ids(query, allowed_ids, limit=limit)
            except Exception as exc:               # noqa: BLE001
                self.disabled = True
                log.warning("rb.answer.retrieve: tắt nhánh vector cho lượt này: %s", exc)
                break
            if ids:
                lists.append(ids)
        # Trộn xen kẽ các truy vấn thành MỘT danh sách: nhánh này là một nguồn
        # đồng thuận trong RRF, không phải ba — ba cách nói cùng một ý không được
        # tính là ba bằng chứng độc lập.
        merged, index = [], 0
        while any(index < len(ids) for ids in lists):
            for ids in lists:
                if index < len(ids) and ids[index] not in merged:
                    merged.append(ids[index])
            index += 1
        return merged[:limit]


def _prioritised(queryset):
    from django.db.models import BooleanField, Exists, ExpressionWrapper, OuterRef
    from social.models import SocialPost

    from ..models import RBProfile

    has_retail = ExpressionWrapper(
        Q(Exists(RBProfile.objects.filter(person_id=OuterRef("pk"))))
        | Q(Exists(Signal.objects.filter(person_id=OuterRef("pk"),
                                         domain=Signal.DOMAIN_RB)))
        | Q(Exists(SocialPost.objects.filter(person_id=OuterRef("pk")))),
        output_field=BooleanField())
    return (queryset.annotate(_has_retail=has_retail)
            .order_by("-_has_retail", "-updated_at", "-pk"))


def retrieve(query_plan, *, user=None, pool=None, pinned_ids=()):
    """`ProspectPlan` → danh sách `Candidate` xếp theo mức đáng xem giảm dần.

    `pinned_ids`: người phải CÓ trong kết quả bất kể điểm truy hồi — khách được
    gọi đích danh, hoặc nhóm của lượt trước. Không có họ thì "so sánh A và B"
    lần này ra, lần sau rớt một.

    Người ghim VẪN đi qua cổng tuân thủ. Đây là khác biệt cố ý so với Talent:
    ở đó ghim nghĩa là "đọc kỹ người này dù truy hồi không xếp cao"; ở đây
    `do_not_contact` phủ quyết cả việc RM hỏi đích danh.
    """
    pool = pool or pool_for(query_plan)
    pinned_ids = list(dict.fromkeys(int(p) for p in pinned_ids if p))

    allowed = eligible_people(query_plan, user=user)
    # Có `order_by`: cắt không thứ tự trên bảng lớn trả một tập con TUỲ Ý, khác
    # nhau giữa hai lần chạy. Mới nhất trước — khách mới tạo/cập nhật gần đây
    # có tín hiệu mới hơn. Chạm trần thì nói ra trong log thay vì im lặng.
    # Người có dấu vết bán lẻ (hồ sơ RB, tín hiệu RB, bài đăng) đứng TRƯỚC người
    # chỉ có CV. Từ khi `population.customers()` gộp cả kho CV, tập được phép dễ
    # vượt trần — cắt thuần theo `updated_at` thì một đợt nhập CV hàng loạt đẩy
    # văng đúng những khách có bằng chứng mạnh nhất ra khỏi lượt tìm.
    allowed_ids = list(_prioritised(allowed)
                       .values_list("pk", flat=True)[:MAX_ELIGIBLE + 1])
    if len(allowed_ids) > MAX_ELIGIBLE:
        log.warning("rb.answer.retrieve: tập khách được phép vượt %s, chỉ xét phần mới "
                    "nhất — tiêu chí quá rộng", MAX_ELIGIBLE)
        allowed_ids = allowed_ids[:MAX_ELIGIBLE]
    if pinned_ids:
        # Lọc người ghim qua đúng cổng đó — bằng một truy vấn riêng, vì họ có
        # thể không thoả các bộ lọc mềm của câu hỏi nhưng vẫn phải được đọc.
        from .population import customers, do_not_contact_ids
        gate = customers().filter(pk__in=pinned_ids).exclude(pk__in=do_not_contact_ids())
        pinned_ids = [pid for pid in pinned_ids
                      if pid in set(gate.values_list("pk", flat=True))]
        allowed_ids = list(dict.fromkeys(pinned_ids + allowed_ids))
    if not allowed_ids:
        return []

    terms = _terms(getattr(query_plan, "search_queries", None) or [])
    products = list(getattr(query_plan, "products", None) or [])

    from rb import evidence_index
    queries = list(getattr(query_plan, "search_queries", None) or [])
    if evidence_index.populated() and queries:
        # Chỉ mục có dữ liệu → cùng hai nhánh, nhưng full-text có chỉ mục GIN thay
        # cho `icontains` quét cả bảng bài đăng. Cùng nguồn, cùng trọng số: đổi
        # CÁCH tìm, không đổi cách TÍNH điểm, nên không đếm trùng bằng chứng.
        joined = " ".join(queries)
        social_ids = evidence_index.fts_person_ids(joined, allowed_ids, limit=PER_BRANCH,
                                                   sources=("social", "comment"))
        signal_ids = evidence_index.fts_person_ids(joined, allowed_ids, limit=PER_BRANCH,
                                                   sources=("signal",))
    else:
        social_ids = _social_ids(allowed_ids, terms, PER_BRANCH)
        signal_ids = _signal_ids(allowed_ids, terms, PER_BRANCH)

    branches = [
        ("semantic", _DenseBranch()(queries, allowed_ids, PER_BRANCH)),
        ("social", social_ids),
        ("signal", signal_ids),
        ("interest", _interest_ids(allowed_ids, products, PER_BRANCH)),
        ("outcome", _outcome_ids(allowed_ids, PER_BRANCH)),
        ("profile", _profile_ids(allowed_ids, terms, PER_BRANCH)),
        ("cv", _cv_ids(allowed_ids, queries, PER_BRANCH)),
    ]
    ranked, weights = [], []
    allowed_set = set(allowed_ids)
    for name, ids in branches:
        # Nhánh nào trả người NGOÀI tập đã qua cổng tuân thủ thì người đó bị bỏ ở
        # đây — bất kể nhánh đó có tự lọc hay không. Cổng DNC/phạm vi không được
        # phụ thuộc vào việc mọi nhánh, kể cả nhánh viết sau này, nhớ tôn trọng nó.
        ids = [pid for pid in ids if pid in allowed_set]
        # Giữ thứ tự, bỏ trùng: một người có sáu bài đăng khớp không được tính
        # sáu lần trong cùng một nhánh — đó là đếm bằng chứng, không phải đếm
        # nguồn đồng thuận, và RRF dựa vào vế sau.
        deduped = list(dict.fromkeys(ids))
        if deduped:
            ranked.append(deduped)
            weights.append(BRANCH_WEIGHTS.get(name, 1.0))

    if ranked:
        order, hits = reciprocal_rank_fusion(ranked, weights=weights)
    else:
        # Không nhánh nào khớp (câu hỏi quá lạ, hoặc kho chưa có tín hiệu nào).
        # Vẫn trả người thoả cổng, để ③ đọc và nói thật là không có bằng chứng —
        # khác hẳn với việc trả rỗng và để ⑤ kết luận "không có ai".
        order = [(pid, 0.0) for pid in allowed_ids[:pool]]
        hits = {}

    top_ids = [pid for pid, _score in order[:pool]]
    if pinned_ids:
        pin_set = set(pinned_ids)
        top_ids = pinned_ids + [pid for pid in top_ids if pid not in pin_set]
        top_ids = top_ids[:max(pool, len(pinned_ids))]
        pin_score = {pid: 1_000.0 - i for i, pid in enumerate(pinned_ids)}
        order = ([(pid, pin_score[pid]) for pid in pinned_ids]
                 + [(pid, s) for pid, s in order if pid not in pin_set])
        for pid in pinned_ids:
            hits.setdefault(pid, 1)

    if not top_ids:
        return []

    names = dict(Person.objects.filter(pk__in=top_ids)
                 .values_list("pk", "display_name"))
    passages = evidence_stage.passages_for(top_ids)

    # Độ sâu bằng chứng giảm dần theo thứ hạng — người đứng đầu là người ③ sẽ
    # thật sự chọn, đáng đọc kỹ; đuôi danh sách phần lớn bị loại.
    depth_cut = max(1, pool // 3)
    pinned_set = set(pinned_ids)
    candidates = []
    for rank, (person_id, score) in enumerate(order[:max(pool, len(pinned_ids))]):
        if person_id not in names:
            continue
        depth = (evidence_stage.PASSAGES_PER_PERSON if rank < depth_cut
                 else evidence_stage.TAIL_PASSAGES)
        rows = list(passages.get(person_id) or [])[:depth]
        if not rows and person_id not in pinned_set:
            continue
        candidates.append(Candidate(
            person_id=person_id, name=names.get(person_id) or f"#{person_id}",
            score=round(score, 6), hits=hits.get(person_id, 0), passages=rows))
    return candidates


def coverage():
    """Số liệu để trace nói thật về độ phủ, không hứa suông.

    ## Trạng thái tìm theo nghĩa (đọc trước khi tin vào recall)

    `semantic_retrieval` nói thật trạng thái của `rb/evidence_index.py`:

        INDEX_EMPTY          chưa chạy `rebuild_prospect_evidence_index`
        INDEX_NOT_EMBEDDED   có text, chưa có vector — full-text chạy, vector chưa
        ENABLED              có vector cho ít nhất một phần chỉ mục

    `chunks_embedded / chunks` là độ phủ thật. Vector chỉ chạy trên PostgreSQL +
    pgvector; môi trường khác chỉ có các nhánh khớp chữ.
    """
    from social.models import SocialPost
    from ..models import ProductInterest, RBProfile

    from rb import evidence_index
    index = evidence_index.coverage()
    return {
        **index,
        "profiles": RBProfile.objects.count(),
        "interests": ProductInterest.objects.count(),
        "signals": Signal.objects.filter(domain=Signal.DOMAIN_RB).count(),
        "social_posts_linked": SocialPost.objects.exclude(person__isnull=True).count(),
        "semantic_retrieval": ("ENABLED" if index["chunks_embedded"] else
                               "INDEX_NOT_EMBEDDED" if index["chunks"] else "INDEX_EMPTY"),
    }
