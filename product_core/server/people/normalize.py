# -*- coding: utf-8 -*-
"""Chuẩn hoá định danh trước khi so khớp.

Đây là nền của toàn bộ việc phân giải Person. Chuẩn hoá sai theo hướng lỏng thì
gộp nhầm hai người thành một — hỏng nặng và khó phát hiện. Chuẩn hoá sai theo
hướng chặt thì một người bị tách thành nhiều bản ghi — phiền nhưng còn sửa được.

Vì vậy mọi quy tắc ở đây thiên về CHẶT: thà bỏ sót một phép khớp còn hơn khớp nhầm.
"""
import re
import unicodedata

# Mã quốc gia Việt Nam. Dữ liệu tuyển dụng của MSB gần như toàn bộ là số VN;
# số nước ngoài được giữ nguyên dạng E.164 nếu người dùng đã nhập đủ dấu +.
VN_COUNTRY_CODE = "84"

# Đầu số di động VN hợp lệ sau khi bỏ số 0, theo từng nhà mạng.
# Gồm CẢ đầu số 09x nguyên bản lẫn đầu số 03x/07x/08x chuyển đổi từ 11 số năm 2018.
# Thiếu 09x là bỏ sót nhóm số phổ biến nhất — mọi số đó sẽ mất định danh điện thoại.
VN_MOBILE_PREFIXES = (
    "32", "33", "34", "35", "36", "37", "38", "39",      # Viettel (từ 016x)
    "86", "96", "97", "98",                              # Viettel
    "70", "76", "77", "78", "79",                        # Mobifone (từ 012x)
    "89", "90", "93",                                    # Mobifone
    "81", "82", "83", "84", "85",                        # Vinaphone (từ 012x)
    "88", "91", "94",                                    # Vinaphone
    "52", "56", "58", "92",                              # Vietnamobile
    "59", "99",                                          # Gmobile
    "87",                                                # Itelecom
)

# Đầu số di động cũ trước lần chuyển đổi 2018 -> đầu số mới.
# CV cũ trong kho vẫn còn số theo định dạng này; không quy đổi thì cùng một
# người sẽ có hai định danh điện thoại khác nhau.
VN_LEGACY_MOBILE_MAP = {
    "162": "32", "163": "33", "164": "34", "165": "35", "166": "36",
    "167": "37", "168": "38", "169": "39",
    "120": "70", "121": "79", "122": "77", "126": "76", "128": "78",
    "123": "83", "124": "84", "125": "85", "127": "81", "129": "82",
    "186": "56", "188": "58",
    "199": "59",
}

_EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s.]+(\.[^@\s.]+)+$")
_NON_DIGIT = re.compile(r"\D")
_WHITESPACE = re.compile(r"\s+")

# Edge nối nhiều giá trị liên hệ bằng ", " (xem edge/app/db.py::_merge_contact_values).
# KHÔNG tách theo khoảng trắng đơn ở đây: số điện thoại thật hay được viết
# "090 123 4567", tách theo dấu cách sẽ băm nó thành ba mẩu vô nghĩa.
_CONTACT_DELIMITERS = re.compile(r"[,;|/\n\r\t]+")

# Tên miền hộp thư cá nhân. Dùng để đoán "đâu là email của chính ứng viên" khi
# một ô chứa nhiều giá trị: email công ty trong CV hầu hết là của người tham
# chiếu (đã quan sát thật: @seabank.com.vn, @vpbank.com.vn, @agribank.com.vn
# nằm cùng ô với gmail của ứng viên).
PERSONAL_EMAIL_DOMAINS = frozenset({
    "gmail.com", "googlemail.com", "yahoo.com", "yahoo.com.vn", "outlook.com",
    "outlook.com.vn", "hotmail.com", "live.com", "icloud.com", "protonmail.com",
    "proton.me", "zoho.com", "mail.com", "yandex.com",
})


def split_contacts(value):
    """Tách một ô liên hệ có thể chứa nhiều giá trị thành danh sách chuỗi thô.

    Cần thiết vì Edge gộp mọi email/điện thoại bóc được từ CV vào MỘT ô. Trước
    khi có hàm này, `normalize_email("a@x.com, b@y.com")` trả rỗng (chuỗi có dấu
    phẩy không khớp `_EMAIL_PATTERN`) nên Hub im lặng vứt cả định danh — đo trên
    283 hồ sơ thật: 28 mất email, 32 mất điện thoại, 5 hồ sơ mất cả hai và không
    tạo được Person nào.
    """
    text = str(value or "").strip()
    if not text:
        return []
    return [part.strip() for part in _CONTACT_DELIMITERS.split(text) if part.strip()]


def split_emails(value):
    """Như `split_contacts` nhưng tách thêm theo khoảng trắng.

    An toàn với email vì địa chỉ email không bao giờ chứa khoảng trắng, và cần
    thiết vì text CV hay xuống dòng/thụt lề giữa các địa chỉ.
    """
    parts = []
    for chunk in split_contacts(value):
        parts.extend(token.strip(" .,;:<>()[]\"'") for token in chunk.split())
    return [part for part in parts if part]


def dedupe_emails(values):
    """Khử trùng lặp email, gộp cả bản BỊ CẮT CỤT vào bản đầy đủ.

    Bộ trích text PDF hay trả cùng một địa chỉ hai lần, một trong đó thiếu vài
    ký tự cuối — quan sát thật: `bichnguyen16042004@gmail.co` nằm cạnh
    `...@gmail.com`, `nguyenduong1212.job@gmail.c` cạnh `...@gmail.com`. Giữ cả
    hai sẽ đẻ ra một "người" thứ hai không tồn tại.

    CỐ Ý chỉ gộp khi một chuỗi là TIỀN TỐ của chuỗi kia. Gộp theo khoảng cách
    sửa (edit distance) nghe hấp dẫn hơn nhưng là chỗ sinh ra lỗi gộp nhầm:
    `an1@gmail.com` và `an2@gmail.com` chỉ khác một ký tự mà là hai người thật.
    Cặp `huyenane.147@` / `huyenanhle.147@` vì thế được giữ nguyên cả hai và để
    bước chấm điểm theo tên phân xử.
    """
    cleaned = []
    for value in values:
        text = str(value or "").strip().lower()
        if text and text not in cleaned:
            cleaned.append(text)
    kept = []
    for text in sorted(cleaned, key=len, reverse=True):
        if not any(longer.startswith(text) for longer in kept):
            kept.append(text)
    # Trả về theo đúng thứ tự xuất hiện ban đầu — thứ tự mang thông tin
    # (giá trị từ trang tuyển dụng được Edge nối trước giá trị bóc từ CV).
    return [text for text in cleaned if text in kept]


def normalize_email(value):
    """Chuẩn hoá email. Trả chuỗi rỗng nếu không phải email dùng được.

    Chỉ hạ chữ thường và cắt khoảng trắng. KHÔNG bỏ dấu chấm hay phần +tag như
    một số hệ thống làm với Gmail: quy tắc đó chỉ đúng với Gmail, và áp cho tên
    miền doanh nghiệp sẽ gộp nhầm hai hộp thư khác nhau thành một.
    """
    text = str(value or "").strip().lower()
    if not text or not _EMAIL_PATTERN.match(text):
        return ""
    return text


def normalize_phone(value, default_region=VN_COUNTRY_CODE):
    """Chuẩn hoá số điện thoại về E.164 (Master Plan mục 12). Rỗng nếu không hợp lệ.

    Master Plan yêu cầu E.164, còn Edge mới chỉ bỏ ký tự phân cách. Chênh lệch
    đó phải được xử lý ở đây, nếu không '0901234567' và '+84901234567' sẽ thành
    hai định danh khác nhau của cùng một người.
    """
    raw = str(value or "").strip()
    if not raw:
        return ""

    has_plus = raw.startswith("+")
    digits = _NON_DIGIT.sub("", raw)
    if not digits:
        return ""

    # Số nước ngoài đã ghi đủ dấu + và không phải mã VN: giữ nguyên, chỉ kiểm độ dài.
    if has_plus and not digits.startswith(VN_COUNTRY_CODE):
        return "+" + digits if 8 <= len(digits) <= 15 else ""

    if digits.startswith("00" + VN_COUNTRY_CODE):
        digits = digits[2:]
    if digits.startswith(VN_COUNTRY_CODE):
        national = digits[len(VN_COUNTRY_CODE):]
    elif digits.startswith("0"):
        national = digits[1:]
    else:
        national = digits

    national = _upgrade_legacy_prefix(national)

    # Di động VN sau chuẩn hoá luôn là 9 chữ số với đầu số hợp lệ. Số cố định có
    # độ dài khác và đầu số khác nên bị loại — cố ý: số tổng đài công ty dùng
    # chung cho nhiều người, lấy nó làm định danh sẽ gộp nhầm cả phòng thành một.
    if len(national) != 9 or not national.startswith(VN_MOBILE_PREFIXES):
        return ""
    return "+" + VN_COUNTRY_CODE + national


def _upgrade_legacy_prefix(national):
    """Quy đổi đầu số di động 11 số cũ (trước 2018) sang đầu số 10 số hiện hành."""
    if len(national) != 10:
        return national
    for old, new in VN_LEGACY_MOBILE_MAP.items():
        if national.startswith(old):
            return new + national[len(old):]
    return national


def normalize_name(value):
    """Chuẩn hoá tên để so sánh: bỏ dấu, hạ chữ thường, gộp khoảng trắng.

    CHỈ dùng để xếp hạng và gợi ý trùng lặp cho người xem, KHÔNG BAO GIỜ dùng
    làm định danh mạnh. Ở Việt Nam 'Nguyễn Văn A' có hàng nghìn người trùng tên;
    gộp Person theo tên là cách chắc chắn nhất để trộn lẫn hồ sơ hai người.
    """
    text = str(value or "").strip()
    if not text:
        return ""
    # NFD tách dấu thành ký tự tổ hợp riêng để lọc bỏ; đ/Đ không có dạng tổ hợp
    # nên phải thay tay.
    text = text.replace("đ", "d").replace("Đ", "D")
    decomposed = unicodedata.normalize("NFD", text)
    stripped = "".join(c for c in decomposed if unicodedata.category(c) != "Mn")
    return _WHITESPACE.sub(" ", stripped).strip().lower()


def email_matches_name(email, fullname):
    """Phần trước @ của email có mang tên người này không.

    Tín hiệu MẠNH NHẤT để tách email của ứng viên khỏi email người tham chiếu
    nằm cùng một ô: `nguyenhaiyen105@gmail.com` với 'Nguyễn Hải Yến' là của
    chính ứng viên, `thuy.pt@seabank.com.vn` cùng ô thì không.

    Chỉ dùng để CHẤM ĐIỂM chọn giá trị nào trong nhiều giá trị đã có sẵn —
    không bao giờ dùng làm định danh (xem `normalize_name`).
    """
    local = re.sub(r"[^a-z0-9]", "", str(email or "").lower().split("@")[0])
    letters = re.sub(r"\d", "", local)
    tokens = [token for token in normalize_name(fullname).split() if len(token) >= 2]
    if not letters or not tokens:
        return False
    joined = "".join(tokens)
    if joined and joined in letters:
        return True
    initials = "".join(token[0] for token in tokens)
    if len(initials) >= 3 and initials in letters:
        return True
    return sum(1 for token in tokens if token in letters) >= 2


def choose_primary_email(values, fullname=""):
    """Chọn ĐÚNG MỘT email làm định danh mạnh. Trả `(email, ambiguous)`.

    `ambiguous=True` nghĩa là phải đoán — người gọi nên bật `needs_review`.

    Vì sao chỉ một: gắn tất cả email trong ô làm định danh của ứng viên là cách
    chắc chắn nhất để gộp nhầm — hai ứng viên khác nhau cùng ghi một người tham
    chiếu sẽ dính vào chung một Person, và đó là kiểu hỏng gần như không gỡ được
    (xem docstring `people/resolution.py`).

    Thứ tự ưu tiên đã đo trên dữ liệu thật: khớp tên > hộp thư cá nhân > vị trí
    đầu. Riêng "vị trí đầu" một mình chỉ đúng 50% nên không bao giờ dùng đơn độc
    khi còn tín hiệu khác.
    """
    usable = [email for email in
              (normalize_email(value) for value in dedupe_emails(values)) if email]
    if not usable:
        return "", False
    if len(usable) == 1:
        return usable[0], False
    by_name = [email for email in usable if email_matches_name(email, fullname)]
    if len(by_name) == 1:
        return by_name[0], False
    pool = by_name or usable
    personal = [email for email in pool
                if email.rsplit("@", 1)[-1] in PERSONAL_EMAIL_DOMAINS]
    if len(personal) == 1:
        return personal[0], False
    return (personal or pool)[0], True


def choose_primary_phone(values):
    """Chọn ĐÚNG MỘT số điện thoại làm định danh mạnh. Trả `(số, ambiguous)`.

    Không có tín hiệu nào tương đương phép khớp tên của email, nên chỉ lấy giá
    trị hợp lệ đầu tiên — Edge nối giá trị lấy từ trang nhà tuyển dụng trước giá
    trị bóc từ CV, nên vị trí đầu là phỏng đoán tốt nhất đang có. Mọi số còn lại
    đi qua đường có bằng chứng (`ContactMention`), không tự gắn.
    """
    usable, seen = [], set()
    for value in split_contacts(values) if isinstance(values, str) else values:
        phone = normalize_phone(value)
        if phone and phone not in seen:
            seen.add(phone)
            usable.append(phone)
    if not usable:
        return "", False
    return usable[0], len(usable) > 1


def normalize_provider_person_id(source, external_id):
    """Định danh do chính nguồn tuyển dụng cấp, ví dụ candidate_id của TopCV.

    Chỉ có ý nghĩa trong phạm vi một nguồn: candidate_id 12345 của TopCV và của
    VietnamWorks là hai người khác nhau. Vì vậy khoá luôn kèm tên nguồn.
    """
    source_key = str(source or "").strip().lower()
    value = str(external_id or "").strip()
    if not source_key or not value:
        return ""
    return f"{source_key}:{value}"


def normalize_url_identity(value):
    """Chuẩn hoá URL hồ sơ mạng xã hội (LinkedIn, Facebook) thành khoá ổn định.

    Bỏ giao thức, www, tham số truy vấn và dấu / cuối — cùng một hồ sơ được chép
    từ nhiều chỗ sẽ ra nhiều biến thể URL của đúng một người.
    """
    text = str(value or "").strip().lower()
    if not text:
        return ""
    text = re.sub(r"^https?://", "", text)
    text = re.sub(r"^www\.", "", text)
    text = text.split("?")[0].split("#")[0].rstrip("/")
    return text if "/" in text else ""
