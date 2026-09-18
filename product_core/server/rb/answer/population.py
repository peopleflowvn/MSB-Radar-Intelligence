# -*- coding: utf-8 -*-
"""Ai là "khách hàng" trong Growth Radar — định nghĩa DUY NHẤT.

`Person` là bảng dùng chung với Talent: phần lớn dòng trong đó là ứng viên tuyển
dụng không có một mẩu dữ liệu bán lẻ nào. Trước module này, ② của Growth lấy tập
"được phép" từ TOÀN BỘ `Person` rồi cắt `[:5000]` không `order_by`: khi bảng lớn,
ứng viên tuyển dụng CHIẾM CHỖ trong trần đó và đẩy khách thật ra ngoài, và phần
bị cắt là tuỳ ý giữa hai lần chạy. (Ứng viên không lọt vào kết quả cuối — không
có bằng chứng bán lẻ thì `retrieve` bỏ qua — nhưng họ đã ăn mất chỗ của người
có.) Phép đếm cũng cần đúng mẫu số này: "kho có bao nhiêu khách" không được đếm
cả ứng viên.

Khách hàng = người chưa bị gộp, có ÍT NHẤT MỘT trong:

    hồ sơ bán lẻ (`RBProfile`)
    tín hiệu domain bán lẻ (`Signal.domain = rb`)
    bài mạng xã hội đã gắn người (`SocialPost.person`)

Dùng `pk__in` với truy vấn con thay vì JOIN: không nhân dòng, không cần
`distinct()`, và `count()` ra đúng số người.
"""
from django.db.models import Q


def customers():
    from people.models import Person, Signal
    from social.models import SocialPost
    from talent.models import TalentProfile

    from ..models import RBProfile

    return Person.objects.filter(merged_into__isnull=True).filter(
        Q(pk__in=RBProfile.objects.values("person_id"))
        | Q(pk__in=Signal.objects.filter(domain=Signal.DOMAIN_RB).values("person_id"))
        | Q(pk__in=SocialPost.objects.exclude(person__isnull=True).values("person_id"))
        | Q(pk__in=TalentProfile.objects.values("person_id")))


def do_not_contact_ids():
    from people.models import Relationship, Signal
    return Relationship.objects.filter(domain=Signal.DOMAIN_RB,
                                       do_not_contact=True).values("person_id")


def scope_queryset(shape, user=None):
    """Khách trong PHẠM VI của câu hỏi — KỂ CẢ khách yêu cầu không liên hệ.

    Dùng làm mẫu số cho thống kê và phép đếm ("trên tổng N khách"). KHÔNG dùng để
    chọn người đưa ra ngoài: việc đó đi qua `retrieve.eligible_people`, nơi có
    cổng tuân thủ.
    """
    from ..models import RBOpportunity

    queryset = customers()
    if shape == "portfolio":
        if user is None or not getattr(user, "pk", None):
            return queryset.none()
        return queryset.filter(rb_profile__sales_owner_id=user.pk)
    if shape == "whitespace":
        return (queryset.filter(rb_profile__sales_owner__isnull=True)
                .exclude(pk__in=RBOpportunity.objects.filter(
                    status__in=RBOpportunity.OPEN_STATUSES).values("person_id")))
    return queryset
