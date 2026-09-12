# -*- coding: utf-8 -*-
"""Tìm kiếm Talent (Master Plan mục 19.3, 43).

Kiến trúc theo mục 43: PostgreSQL + index + full-text + trigram + bộ lọc có cấu trúc.
**Chưa dùng vector search** — chỉ thêm nếu đo được rằng truy hồi ngữ nghĩa thật sự tốt
hơn, đúng như kế hoạch yêu cầu.

Một chỗ phải xử lý: dev chạy SQLite, thật chạy PostgreSQL. Toàn bộ **bộ lọc có cấu
trúc** (kỹ năng, nơi ở, số năm kinh nghiệm, chủ sở hữu, nhãn…) giống hệt nhau ở hai
backend vì chúng là truy vấn quan hệ thuần. Chỉ phần **tìm chữ tự do** là khác:

    PostgreSQL   full-text search có xếp hạng
    SQLite       icontains trên các trường chính

Khác biệt gói gọn trong đúng một hàm (`_free_text`). Kết quả trên PostgreSQL mới là
kết quả chuẩn; SQLite đủ dùng để phát triển và chạy test.
"""
import re
from functools import reduce
from operator import or_

from core.vn_locations import location_query_variants
from django.conf import settings
from django.db import connection
from django.db.models import Count, Q
from people.models import Person
from people.normalize import normalize_name

from .boolean_parser import BooleanQueryParser

# Các trường được quét khi tìm chữ tự do (bao gồm cả nội dung chi tiết CV trích xuất).
TEXT_FIELDS = (
    "display_name",
    "normalized_name",
    "primary_email",
    "primary_phone",
    "talent_profile__current_title",
    "talent_profile__current_company",
    "talent_profile__education",
    "talent_profile__summary",
    "talent_profile__skills",
    "search_document__content_norm",
    "documents__parsed_text",
    "documents__primary_text_version__text",
    "rb_profile__occupation",
    "rb_profile__employer",
    "rb_profile__interaction_summary",
)

MAX_LIMIT = 200

# Truy hồi mềm: pool tối thiểu để bộ chấm điểm luôn có gì đó để xếp hạng.
SOFT_MIN_POOL = 30


def is_postgres():
    return connection.vendor == "postgresql"


def _soft_retrieval(ai_mode):
    return bool(ai_mode) and bool(getattr(settings, "TALENT_SOFT_RETRIEVAL", True))


def _recall_terms(*, skills, title, location, company, text):
    """Q gộp OR mọi tín hiệu — để MỞ RỘNG pool trong soft mode, không loại cứng."""
    parts = []
    for skill in _as_list(skills):
        parts.append(Q(talent_profile__skills__icontains=skill) |
                     Q(documents__parsed_text__icontains=skill) |
                     Q(documents__primary_text_version__text__icontains=skill) |
                     Q(talent_profile__summary__icontains=skill))
    if title and str(title).strip():
        for word in re.split(r"[^\w]+", str(title)):
            if len(word) >= 3:
                parts.append(Q(talent_profile__current_title__icontains=word) |
                             Q(talent_profile__summary__icontains=word) |
                             Q(documents__parsed_text__icontains=word))
    if location and str(location).strip():
        for variant in (location_query_variants(str(location)) or [str(location)]):
            parts.append(Q(talent_profile__location__icontains=variant) |
                         Q(location__icontains=variant))
    if company and str(company).strip():
        parts.append(Q(talent_profile__current_company__icontains=company) |
                     Q(talent_profile__industries__icontains=company) |
                     Q(documents__parsed_text__icontains=company))
    if text and str(text).strip():
        needle = str(text).strip()
        parts.append(reduce(or_, (Q(**{f"{f}__icontains": needle}) for f in TEXT_FIELDS)))
    return reduce(or_, parts) if parts else None


def search(
    *,
    text="",
    skills=None,
    location="",
    title="",
    company="",
    desired_location="",
    seniority="",
    education="",
    job_type="",
    foreign_language="",
    owner=None,
    tags=None,
    pool=None,
    min_years=None,
    max_years=None,
    source="",
    relationship_state="",
    product_interest="",
    lead_status="",
    has_open_opportunity=None,
    has_email=None,
    has_phone=None,
    order="relevance",
    limit=50,
    offset=0,
    max_limit=MAX_LIMIT,
    ai_mode=False,
    canonical_codes=None,
):
    """Tìm Person theo tiêu chí tuyển dụng hỗ trợ cú pháp Boolean Search thông minh.

    Hỗ trợ: AND, OR, NOT, dấu trừ '-', cụm từ trong ngoặc kép "", nhóm ngoặc đơn ().
    `ai_mode`: Khi bật, dùng truy hồi mềm (soft retrieval) để nới lỏng bộ lọc SQL,
    cho phép scoring.py và semantic.py chấm điểm và xếp hạng chính xác thay vì
    bị SQL lọc cứng loại bỏ các ứng viên tiềm năng.
    """
    queryset = _base_queryset()
    soft = _soft_retrieval(ai_mode)

    if text and text.strip() and not soft:
        if BooleanQueryParser.has_syntax(text):
            queryset = queryset.filter(BooleanQueryParser.parse_to_q(text, TEXT_FIELDS,
                                                                      whole_words=True))
        else:
            queryset = _free_text(queryset, text)

    # Boolean Search cho Kỹ năng — quét cả TalentProfile.skills lẫn Document.parsed_text
    if skills and not soft:
        if isinstance(skills, str):
            # Nếu chuỗi có chứa OR, AND, NOT, hoặc dấu ngoặc
            if any(kw in skills.upper() for kw in (' OR ', ' AND ', ' NOT ', '(', ')', '"')):
                skills_q = BooleanQueryParser.parse_to_q(
                    skills, ["talent_profile__skills", "documents__parsed_text",
                             "documents__primary_text_version__text"], whole_words=True)
                if skills_q:
                    queryset = queryset.filter(skills_q)
            else:
                # Xử lý dấu phẩy truyền thống
                for skill in _as_list(skills):
                    if ai_mode:
                        queryset = queryset.filter(
                            Q(talent_profile__skills__icontains=skill) |
                            Q(documents__parsed_text__icontains=skill) |
                            Q(documents__primary_text_version__text__icontains=skill) |
                            Q(talent_profile__summary__icontains=skill)
                        )
                    else:
                        queryset = queryset.filter(BooleanQueryParser.parse_to_q(
                            skill, ["talent_profile__skills", "documents__parsed_text",
                                    "documents__primary_text_version__text"], whole_words=True))
        elif isinstance(skills, (list, tuple)):
            if ai_mode:
                # Retrieval needs recall: require at least one requested skill here,
                # then let scoring measure 1/N, 2/N...  The old AND loop discarded a
                # strong 4/5 candidate before ranking ever saw the CV.
                skill_q = Q()
                for skill in skills:
                    item = str(skill).strip()
                    if item:
                        skill_q |= (Q(talent_profile__skills__icontains=item) |
                                    Q(documents__parsed_text__icontains=item) |
                                    Q(documents__primary_text_version__text__icontains=item) |
                                    Q(talent_profile__summary__icontains=item))
                if skill_q:
                    queryset = queryset.filter(skill_q)
            else:
                for skill in skills:
                    if str(skill).strip():
                        item = str(skill).strip()
                        queryset = queryset.filter(BooleanQueryParser.parse_to_q(
                            item, ["talent_profile__skills", "documents__parsed_text",
                                   "documents__primary_text_version__text"], whole_words=True))

    # Boolean Search cho Địa điểm
    if location and location.strip() and not soft:
        # Khớp mọi cách viết của cùng một nơi ("Hồ Chí Minh" lẫn "Sài Gòn") —
        # không thì khác cách viết giữa câu hỏi và dữ liệu đã lưu làm mất
        # đúng người đang có (xem core/vn_locations.py). Chỉ mở rộng khi đây
        # là MỘT địa danh đơn giản — người dùng đã tự gõ biểu thức Boolean
        # (AND/OR/NOT/ngoặc kép) thì giữ nguyên, không đè lên cú pháp của họ.
        has_boolean_syntax = bool(re.search(r'\b(and|or|not)\b|["()]', location, re.IGNORECASE))
        if has_boolean_syntax:
            expanded = location
        else:
            variants = location_query_variants(location)
            expanded = " OR ".join(f'"{v}"' for v in variants) if variants else location
        loc_q = BooleanQueryParser.parse_to_q(expanded, ["talent_profile__location", "location"])
        if loc_q:
            queryset = queryset.filter(loc_q)

    # Boolean Search cho Chức danh
    if title and title.strip() and not soft:
        if ai_mode:
            # Trong AI mode, nếu đã có bộ lọc khác (kỹ năng, địa điểm, kinh nghiệm)
            # thì nới lỏng title để semantic.py chấm độ tương đương mà không bị SQL loại bỏ.
            has_other_filters = bool(skills or location or company or min_years is not None)
            if not has_other_filters:
                title_q = BooleanQueryParser.parse_to_q(
                    title,
                    ["talent_profile__current_title", "talent_profile__summary",
                     "documents__parsed_text"]
                     + ["documents__primary_text_version__text"]
                )
                if title_q:
                    queryset = queryset.filter(title_q)
        else:
            title_q = BooleanQueryParser.parse_to_q(title, "talent_profile__current_title")
            if title_q:
                queryset = queryset.filter(title_q)

    # Boolean Search cho Công ty / Lĩnh vực
    if company and company.strip() and not soft:
        company_q = BooleanQueryParser.parse_to_q(
            company,
            ["talent_profile__current_company", "talent_profile__industries",
             "documents__parsed_text"]
             + ["documents__primary_text_version__text"]
        )
        if company_q:
            queryset = queryset.filter(company_q)

    for value, fields in (
        (desired_location, ["talent_profile__desired_location"]),
        (seniority, ["talent_profile__seniority", "talent_profile__desired_level"]),
        (education, ["talent_profile__education"]),
        (job_type, ["talent_profile__job_type"]),
        (foreign_language, ["talent_profile__foreign_language"]),
    ):
        if value and str(value).strip() and not soft:
            condition = BooleanQueryParser.parse_to_q(str(value), fields, whole_words=True)
            if condition:
                queryset = queryset.filter(condition)

    # Bộ lọc canonical (Master Plan §8.1, §18 bước 8): khi câu hỏi đã được nối
    # sang mã chuẩn, lọc theo mã trên `ExtractedFact` accepted + hiện hành. Không
    # có fact nào ⇒ không lọc (fallback về các điều kiện text ở trên trong thời
    # gian migration). Trong ai_mode chỉ áp cho địa điểm — giữ recall cho phần còn lại.
    for field, codes in (canonical_codes or {}).items():
        codes = [c for c in (codes or []) if c]
        if not codes:
            continue
        if ai_mode and field not in ("city", "location_interest"):
            continue
        if not Person.objects.filter(
                facts__field=field, facts__canonical_code__in=codes,
                facts__status="accepted", facts__is_current=True).exists():
            continue
        queryset = queryset.filter(
            facts__field=field, facts__canonical_code__in=codes,
            facts__status="accepted", facts__is_current=True).distinct()

    if owner is not None:
        queryset = queryset.filter(talent_profile__owner=owner)

    tag_list = _as_list(tags)
    if tag_list:
        # Nhãn cũng AND: chọn hai nhãn nghĩa là muốn người có cả hai.
        for tag in tag_list:
            queryset = queryset.filter(talent_profile__tags__slug=tag)

    if pool is not None:
        queryset = queryset.filter(pool_memberships__pool=pool)

    if min_years is not None and not soft:
        queryset = queryset.filter(talent_profile__years_experience__gte=min_years)
    if max_years is not None and not soft:
        queryset = queryset.filter(talent_profile__years_experience__lte=max_years)

    if source:
        queryset = queryset.filter(source_records__source=source)
    if relationship_state:
        queryset = queryset.filter(relationships__domain="talent",
                                   relationships__state=relationship_state)
    if product_interest:
        queryset = queryset.filter(rb_profile__interests__product=product_interest)
    if lead_status:
        queryset = queryset.filter(rb_profile__lead_status=lead_status)
    if has_open_opportunity is True:
        queryset = queryset.filter(
            rb_opportunities__status__in=("new", "accepted", "contacting"))
    elif has_open_opportunity is False:
        queryset = queryset.exclude(
            rb_opportunities__status__in=("new", "accepted", "contacting"))

    # Khả năng liên hệ được (Master Plan mục 23): hồ sơ không có cách liên lạc nào
    # thì recruiter không dùng được, dù khớp đến đâu. Đây là ràng buộc thật của
    # người dùng, KHÔNG nới kể cả soft mode.
    if has_email:
        queryset = queryset.exclude(primary_email="")
    if has_phone:
        queryset = queryset.exclude(primary_phone="")

    if soft:
        # Truy hồi mềm: OR mọi tín hiệu để mở rộng pool; nếu vẫn mỏng thì bù bằng
        # hồ sơ mới nhất. scoring.py + AI mới là chỗ chọn và xếp hạng.
        recall = _recall_terms(skills=skills, title=title, location=location,
                               company=company, text=text)
        matched = queryset.filter(recall).distinct() if recall is not None else queryset
        if matched.count() < SOFT_MIN_POOL:
            extra = queryset.order_by("-talent_profile__last_source_at",
                                      "-updated_at")[:SOFT_MIN_POOL]
            ids = set(matched.values_list("pk", flat=True)) | {p.pk for p in extra}
            queryset = _base_queryset().filter(pk__in=ids)
        else:
            queryset = matched

    total = queryset.count()
    queryset = _order(queryset, order, text)

    limit = max(1, min(int(limit), max_limit))
    offset = max(0, int(offset))
    return total, list(queryset[offset:offset + limit])


def _base_queryset():
    # Chỉ người ĐÃ TỪNG ỨNG TUYỂN. Người tham chiếu bóc từ CV của người khác
    # cũng là Person thật nhưng chưa nộp hồ sơ nào — hiện họ ở đây thì recruiter
    # thấy một "ứng viên" rỗng không có CV, không có lượt ứng tuyển. Bán hàng
    # (`rb/prospects.py`) vẫn thấy đủ cả hai nhóm.
    return (Person.applicants()
            .select_related("talent_profile", "rb_profile")
            .prefetch_related("documents__primary_text_version",
                              "talent_profile__tags",
                              "rb_profile__interests", "rb_opportunities",
                              "relationships",
                              "hunt_candidates__assigned_to",
                              "hunt_candidates__hunt_request__hiring_need")
            .annotate(source_count_value=Count("source_records", distinct=True))
            .distinct())


def load_people(person_ids):
    """Hydrate semantic hits with the same relations used by structured search."""
    ids = [int(value) for value in person_ids if value]
    if not ids:
        return []
    order = {person_id: position for position, person_id in enumerate(ids)}
    rows = list(_base_queryset().filter(pk__in=ids))
    rows.sort(key=lambda person: order.get(person.pk, len(order)))
    return rows


def _free_text(queryset, text):
    """Phần duy nhất khác nhau giữa PostgreSQL và SQLite."""
    text = str(text or "").strip()
    if not text:
        return queryset

    if is_postgres():
        from django.contrib.postgres.search import SearchQuery, SearchRank, SearchVector
        vector = (
            SearchVector("display_name", "normalized_name", weight="A", config="simple")
            + SearchVector("talent_profile__current_title", "talent_profile__skills",
                           weight="A", config="simple")
            + SearchVector("talent_profile__current_company", "talent_profile__education",
                           weight="B", config="simple")
            + SearchVector("talent_profile__summary", weight="C", config="simple")
            + SearchVector("search_document__content_norm", weight="C", config="simple")
            + SearchVector("documents__parsed_text",
                           "documents__primary_text_version__text", weight="D", config="simple")
        )
        query = SearchQuery(text, config="simple", search_type="websearch")
        return (queryset.annotate(rank=SearchRank(vector, query, cover_density=True))
                .filter(rank__gt=0.0))

    # SQLite: khớp theo TỪ, không phải chuỗi con.
    #
    # `icontains` sẽ làm tìm "An" (tên riêng rất phổ biến) khớp cả "Analyst" —
    # và tệ hơn, nó khiến nhánh dev hành xử khác hẳn nhánh thật: PostgreSQL
    # SearchQuery khớp theo lexeme nên "An" không bao giờ khớp "Analyst".
    # Dùng biên từ để hai backend cho cùng ngữ nghĩa.
    #
    # `iregex` không dùng được index, nhưng đây chỉ là nhánh SQLite dành cho phát
    # triển và test; nhánh thật chạy PostgreSQL với index full-text.
    condition = Q()
    for needle in {text, normalize_name(text)}:
        if not needle:
            continue
        # re.escape: chuỗi tìm kiếm đến từ người dùng, không được để nó là regex.
        pattern = r"\b" + re.escape(needle) + r"\b"
        for field in TEXT_FIELDS:
            condition |= Q(**{f"{field}__iregex": pattern})
    return queryset.filter(condition)


def _order(queryset, order, text):
    if (order == "relevance" and text and is_postgres()
            and "rank" in getattr(queryset.query, "annotations", {})):
        return queryset.order_by("-rank", "-talent_profile__last_source_at")
    if order == "name":
        return queryset.order_by("display_name")
    if order == "oldest":
        return queryset.order_by("talent_profile__last_source_at")
    # Mặc định: hồ sơ mới nhất trước. Với recruiter, độ tươi là tín hiệu mạnh —
    # người vừa nộp CV tuần trước đang tìm việc, người nộp ba năm trước thì chưa chắc.
    return queryset.order_by("-talent_profile__last_source_at", "-updated_at")


def facets(queryset=None):
    """Đếm theo từng nhóm, để giao diện hiện số bên cạnh mỗi bộ lọc."""
    from django.db.models import Count

    from .models import Tag
    base = queryset if queryset is not None else Person.applicants()
    return {
        "by_source": list(
            base.values("source_records__source")
            .annotate(count=Count("id", distinct=True))
            .exclude(source_records__source=None)
            .order_by("-count")),
        "by_location": list(
            base.exclude(talent_profile__location="")
            .values("talent_profile__location")
            .annotate(count=Count("id", distinct=True))
            .order_by("-count")[:20]),
        "tags": list(
            Tag.objects.annotate(count=Count("talents"))
            .filter(count__gt=0).values("slug", "name", "count").order_by("-count")[:30]),
    }


def _as_list(value):
    if value is None:
        return []
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    return [str(item).strip() for item in value if str(item).strip()]
