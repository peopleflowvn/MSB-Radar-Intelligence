# -*- coding: utf-8 -*-
"""Che thông tin liên hệ và hạn mức mở khoá (Master Plan mục 27).

Bài toán không phải "giấu dữ liệu khỏi người có quyền". Người dùng ở đây **có**
quyền xem — họ là recruiter và RM đang làm đúng việc của mình. Bài toán là:

    Một tài khoản hợp lệ có thể lặng lẽ rút cả kho liên hệ ra ngoài
    chỉ bằng cách cuộn qua vài trang danh sách.

Nên hai cơ chế, giải hai việc khác nhau:

    CHE MẶC ĐỊNH   Danh sách không bao giờ trả về email/SĐT đầy đủ. Cuộn 500
                   hồ sơ cũng không thu được gì. Đây là thứ chặn *khối lượng*.
    HẠN MỨC + LOG  Muốn xem đầy đủ thì phải bấm mở khoá, và mỗi lượt bị đếm
                   cùng ghi vết. Đây là thứ chặn *ý đồ* — và trả lời được câu
                   hỏi tuân thủ "ai đã lấy số của người này".

## Vì sao che ở tầng dữ liệu, không phải tầng giao diện

Ẩn trên React chỉ là lớp trải nghiệm. Bất kỳ ai mở DevTools cũng đọc được
nguyên văn phản hồi API. Nên `mask_*()` được gọi ngay trong serializer, và
API danh sách **không có tham số nào** để yêu cầu dữ liệu chưa che — muốn đầy
đủ thì phải đi qua đúng một cửa là endpoint mở khoá.

## Vì sao không che theo ngữ cảnh người dùng trong danh sách

Cách khác là truyền `request.user` vào mọi serializer rồi quyết định che hay
không. Cách đó hỏng theo kiểu tệ nhất: chỉ cần **một** chỗ khởi tạo serializer
quên truyền context là chỗ đó rò toàn bộ, im lặng, và không test nào phát hiện
trừ khi có người nghĩ tới đúng endpoint ấy. Che vô điều kiện thì không có
đường rò nào cả.
"""
import re
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from . import roles

#: Hạn mức mở khoá mặc định theo vai trò. `None` = không giới hạn.
#:
#: Vì sao RM thấp hơn Recruiter: recruiter làm việc theo lô (sàng một đợt ứng
#: viên cho một vị trí), còn RM làm việc theo từng khách. RM cần 15 số một ngày
#: là bình thường; RM cần 200 số một ngày là chuyện khác.
#:
#: Vì sao Manager vẫn có hạn mức thay vì không giới hạn: một chốt kiểm soát chỉ
#: áp cho cấp dưới thì không phải chốt kiểm soát. Ai cần hơn thì cấp
#: `ContactUnlockPolicy` riêng — và việc cấp đó tự nó là một dấu vết.
DEFAULT_DAILY_QUOTA = {
    roles.ADMIN: None,
    roles.MANAGER: 50,
    roles.RECRUITER: 30,
    roles.RB_SALES: 15,
    roles.HIRING_MANAGER: 10,
}

#: Hạn mức cho tài khoản không khớp vai trò nào ở trên.
FALLBACK_QUOTA = 5


class QuotaExceeded(Exception):
    """Đã dùng hết hạn mức mở khoá trong ngày."""

    def __init__(self, used, limit):
        self.used = used
        self.limit = limit
        super().__init__(f"Đã dùng {used}/{limit} lượt mở khoá hôm nay.")


# ------------------------------------------------------------------ che dữ liệu

def mask_email(value):
    """`nguyen.van.an@gmail.com` → `nguyen.v***@gmail.com`.

    Giữ lại tên miền vì nó không định danh ai, mà lại giúp người dùng nhận ra
    hồ sơ nào là hồ sơ nào khi đối chiếu.
    """
    text = str(value or "").strip()
    if not text:
        return ""
    if "@" not in text:
        # Không đúng khuôn email thì vẫn phải che, không được trả nguyên văn.
        return _mask_tail(text, keep=3)

    local, _, domain = text.partition("@")
    return f"{_mask_tail(local, keep=8)}@{domain}"


def mask_phone(value):
    """`0975219309` → `097****309`."""
    text = str(value or "").strip()
    if not text:
        return ""
    if len(text) <= 4:
        # Quá ngắn để giữ lại gì: che hết còn hơn trả về gần như nguyên vẹn.
        return "*" * len(text)
    return f"{text[:3]}{'*' * max(3, len(text) - 6)}{text[-3:]}"


def _mask_tail(text, keep):
    """Giữ `keep` ký tự đầu, thay phần còn lại bằng `***`.

    Luôn che ít nhất một ký tự: một hàm "che" trả về đúng chuỗi gốc là một lỗ
    rò im lặng, vì chỗ gọi tưởng đã che rồi.
    """
    if len(text) <= 1:
        return "*"
    keep = min(keep, len(text) - 1)
    return f"{text[:keep]}***"


#: Số điện thoại Việt Nam và email trong văn bản tự do.
#:
#: Cố ý rộng tay: bắt nhầm một dãy số không phải điện thoại chỉ làm trích dẫn
#: khó đọc hơn một chút; bỏ sót một số thật là để lộ liên hệ ở đúng chỗ không ai
#: nghĩ tới mà đi kiểm.
#: Bản đầu là `(?:\+?84|0)\d[\d\s.\-]{7,13}\d` — đòi CHỮ SỐ ngay sau đầu số, nên
#: `(+84) 987 654 321` trượt hoàn toàn: sau `84` là `)` chứ không phải số. Dạng
#: ấy không hiếm, nó là dạng người ta gõ khi viết cho người nước ngoài đọc. Bài
#: `accounts/tests_leak_surfaces.py` bắt được bằng cách bỏ hết dấu ngăn rồi mới
#: soi — che mà vẫn đọc ra số qua khoảng trắng thì không phải che.
_PHONE_IN_TEXT = re.compile(
    r"(?:\(\s*\+?84\s*\)|\+?84|0)"   # đầu số: (+84) · +84 · 84 · 0
    r"[\s.\-]*"                      # dấu ngăn NGAY SAU đầu số — chỗ từng hở
    r"\d[\d\s.\-]{6,13}\d"           # phần thân
)
_EMAIL_IN_TEXT = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")


def redact_contacts(text):
    """Che email và số điện thoại nằm trong **văn bản tự do**.

    Che theo trường (`mask_email`, `mask_phone`) không đủ. Bằng chứng của một
    đề xuất chứa trích dẫn nguyên văn bài đăng, và người ta thường tự viết số
    điện thoại vào bài — *"Em cần vay 500 triệu mua nhà, LH 0901234567"*. Trích
    dẫn đó hiện thẳng trên thẻ «Cơ hội hôm nay», nên nếu không che ở đây thì
    toàn bộ hạn mức mở khoá bị đi vòng qua bằng một đường không ai nghĩ tới.

    Cùng lý do áp cho mọi chỗ hiển thị lại nội dung người dùng nhập.
    """
    cleaned = _EMAIL_IN_TEXT.sub(lambda m: mask_email(m.group(0)), str(text or ""))
    return _PHONE_IN_TEXT.sub(lambda m: mask_phone(m.group(0)), cleaned)


def masked_contact(person):
    """Cặp (email, SĐT) đã che, dùng chung cho mọi serializer trả danh sách."""
    return {
        "primary_email": mask_email(person.primary_email),
        "primary_phone": mask_phone(person.primary_phone),
        "contact_masked": bool(person.primary_email or person.primary_phone),
    }


# ------------------------------------------------------------------ hạn mức

def quota_for(user):
    """Hạn mức mở khoá mỗi ngày của một người. `None` = không giới hạn."""
    from .models import ContactUnlockPolicy

    if user is None or not getattr(user, "pk", None):
        return 0
    if getattr(user, "is_superuser", False):
        return None

    policy = ContactUnlockPolicy.objects.filter(user=user).first()
    if policy is not None:
        if policy.is_unlimited:
            return None
        if policy.custom_daily_quota is not None:
            return policy.custom_daily_quota

    owned = roles.roles_of(user) & set(DEFAULT_DAILY_QUOTA)
    if not owned:
        return FALLBACK_QUOTA

    limits = [DEFAULT_DAILY_QUOTA[name] for name in owned]
    if any(limit is None for limit in limits):
        return None
    # Kiêm nhiều vai trò thì lấy mức cao nhất — cộng dồn sẽ tạo ra hạn mức
    # không ai chủ ý cấp.
    return max(limits)


def used_today(user, now=None):
    """Số lượt đã mở khoá kể từ 00:00 hôm nay."""
    from .models import ContactUnlockLog

    return ContactUnlockLog.objects.filter(
        user=user, unlocked_at__gte=_start_of_day(now)).count()


def remaining(user, now=None):
    """Số lượt còn lại. `None` = không giới hạn."""
    limit = quota_for(user)
    if limit is None:
        return None
    return max(0, limit - used_today(user, now=now))


def is_unlocked(user, person, now=None):
    """Người này đã mở khoá liên hệ của hồ sơ đó trong hôm nay chưa?

    Tách ra khỏi `unlock()` vì có chỗ chỉ cần HỎI mà không muốn tính phí: xem
    nguyên văn CV (`talent.views.document_text`) phải che liên hệ khi chưa mở
    khoá, nhưng nếu người dùng đã trả một lượt cho hồ sơ này rồi thì che nữa là
    vô nghĩa — họ đã thấy số điện thoại đó rồi.
    """
    from .models import ContactUnlockLog

    if user is None or not getattr(user, "pk", None) or person is None:
        return False
    if getattr(user, "is_superuser", False):
        return True
    return ContactUnlockLog.objects.filter(
        user=user, person=person,
        unlocked_at__gte=_start_of_day(now or timezone.now())).exists()


@transaction.atomic
def unlock(user, person, domain="", ip="", now=None):
    """Mở khoá liên hệ của một người. Trả `(contact, remaining, charged)`.

    Ném `QuotaExceeded` khi hết hạn mức.

    **Không tính phí hai lần trong ngày cho cùng một người.** Mở lại hồ sơ vừa
    xem cách đây năm phút mà mất thêm một lượt sẽ khiến người dùng học cách
    chụp màn hình lại toàn bộ danh sách ngay lần đầu — đúng hành vi mà cả cơ
    chế này sinh ra để chặn.
    """
    from .models import ContactUnlockLog

    now = now or timezone.now()
    already = ContactUnlockLog.objects.filter(
        user=user, person=person, unlocked_at__gte=_start_of_day(now)).exists()

    if not already:
        limit = quota_for(user)
        if limit is not None:
            used = used_today(user, now=now)
            # Ghi chú về tranh chấp đồng thời: hai yêu cầu cùng lúc từ CÙNG một
            # tài khoản có thể cùng vượt qua chỗ kiểm này và vượt hạn mức vài
            # lượt. Chấp nhận có chủ đích — khoá bảng để chống lại chính điều
            # đó là cái giá quá đắt, và bản thân việc một tài khoản bắn song
            # song đã là thứ nhật ký này sinh ra để phát hiện.
            if used >= limit:
                raise QuotaExceeded(used, limit)

        ContactUnlockLog.objects.create(
            user=user, user_name=str(user)[:150],
            person=person, person_name=(person.display_name or "")[:200],
            domain=domain[:20], ip=str(ip or "")[:64], unlocked_at=now)

    return (
        {"primary_email": person.primary_email,
         "primary_phone": person.primary_phone},
        remaining(user, now=now),
        not already,
    )


def _start_of_day(now=None):
    """00:00 hôm nay theo múi giờ đang cấu hình.

    Dùng giờ địa phương chứ không phải UTC: hạn mức "mỗi ngày" phải reset lúc
    nửa đêm theo giờ người dùng, không phải 7 giờ sáng.
    """
    now = now or timezone.now()
    local = timezone.localtime(now)
    midnight = local.replace(hour=0, minute=0, second=0, microsecond=0)
    return midnight if timezone.is_aware(midnight) else midnight - timedelta(0)
