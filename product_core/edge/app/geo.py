# -*- coding: utf-8 -*-
"""Danh mục tỉnh/thành phố Việt Nam + so khớp linh hoạt.

Dùng để CHUẨN HOÁ "nơi làm việc mong muốn" về tên tỉnh/thành chuẩn (nhiều nguồn
viết mỗi kiểu: "TP.HCM", "tp hcm", "Sài Gòn", "HCM"...) và để QUÉT text CV tìm
địa danh khi trang chi tiết không cho được trường này.

Cố ý dùng danh sách 63 tỉnh truyền thống: dữ liệu CV và trang tuyển dụng còn
dùng tên cũ nhiều năm nữa. So khớp bỏ dấu, không phân biệt hoa thường.
"""
import re
import unicodedata

#: {tên chuẩn: (các cách viết khác — sẽ được bỏ dấu khi so khớp)}
#: Chỉ liệt kê alias khi nó KHÁC phần bỏ dấu của tên chuẩn (viết tắt, tên gọi
#: khác). Biến thể chỉ khác dấu được xử lý tự động.
_PROVINCES = {
    "An Giang": (),
    "Bà Rịa - Vũng Tàu": ("Ba Ria Vung Tau", "BRVT", "Vũng Tàu", "Vung Tau", "Bà Rịa"),
    "Bắc Giang": (),
    "Bắc Kạn": ("Bac Can",),
    "Bạc Liêu": (),
    "Bắc Ninh": (),
    "Bến Tre": (),
    "Bình Định": ("Quy Nhơn", "Quy Nhon"),
    "Bình Dương": ("BD",),
    "Bình Phước": (),
    "Bình Thuận": ("Phan Thiết", "Phan Thiet"),
    "Cà Mau": (),
    "Cần Thơ": ("Can Tho", "CT"),
    "Cao Bằng": (),
    "Đà Nẵng": ("Da Nang", "Danang", "DN", "ĐN"),
    "Đắk Lắk": ("Dak Lak", "Daklak", "Buôn Ma Thuột", "Buon Ma Thuot", "Đăk Lăk"),
    "Đắk Nông": ("Dak Nong", "Đăk Nông"),
    "Điện Biên": (),
    "Đồng Nai": ("Biên Hòa", "Bien Hoa"),
    "Đồng Tháp": (),
    "Gia Lai": ("Pleiku",),
    "Hà Giang": (),
    "Hà Nam": (),
    "Hà Nội": ("Ha Noi", "Hanoi", "HN", "Thủ đô", "Thu do"),
    "Hà Tĩnh": (),
    "Hải Dương": (),
    "Hải Phòng": ("Hai Phong", "Haiphong", "HP"),
    "Hậu Giang": (),
    "Hòa Bình": ("Hoa Binh",),
    "Hưng Yên": (),
    "Khánh Hòa": ("Nha Trang", "Khanh Hoa"),
    "Kiên Giang": ("Rạch Giá", "Rach Gia", "Phú Quốc", "Phu Quoc"),
    "Kon Tum": (),
    "Lai Châu": (),
    "Lâm Đồng": ("Đà Lạt", "Da Lat", "Dalat"),
    "Lạng Sơn": (),
    "Lào Cai": ("Sa Pa", "Sapa"),
    "Long An": ("Tân An", "Tan An"),
    "Nam Định": (),
    "Nghệ An": ("Vinh",),
    "Ninh Bình": (),
    "Ninh Thuận": ("Phan Rang",),
    "Phú Thọ": ("Việt Trì", "Viet Tri"),
    "Phú Yên": ("Tuy Hòa", "Tuy Hoa"),
    "Quảng Bình": ("Đồng Hới", "Dong Hoi"),
    "Quảng Nam": ("Tam Kỳ", "Tam Ky", "Hội An", "Hoi An"),
    "Quảng Ngãi": (),
    "Quảng Ninh": ("Hạ Long", "Ha Long", "Halong", "Móng Cái", "Mong Cai"),
    "Quảng Trị": ("Đông Hà", "Dong Ha"),
    "Sóc Trăng": (),
    "Sơn La": (),
    "Tây Ninh": (),
    "Thái Bình": (),
    "Thái Nguyên": (),
    "Thanh Hóa": ("Thanh Hoa",),
    "Thừa Thiên Huế": ("Thua Thien Hue", "Huế", "Hue", "TT Huế", "TTH"),
    "Tiền Giang": ("Mỹ Tho", "My Tho"),
    "Hồ Chí Minh": ("TP HCM", "TPHCM", "TP.HCM", "TP. HCM", "HCM", "HCMC",
                    "Ho Chi Minh", "Ho Chi Minh City", "Sài Gòn", "Sai Gon",
                    "Saigon", "SG", "Thành phố Hồ Chí Minh"),
    "Trà Vinh": (),
    "Tuyên Quang": (),
    "Vĩnh Long": (),
    "Vĩnh Phúc": ("Vĩnh Yên", "Vinh Yen"),
    "Yên Bái": (),
}


def _fold(text):
    """Bỏ dấu tiếng Việt + hạ chữ thường + gộp khoảng trắng."""
    text = unicodedata.normalize("NFD", str(text or ""))
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    text = text.replace("đ", "d").replace("Đ", "d")
    return re.sub(r"\s+", " ", text.lower()).strip()


def _strip_admin_prefix(folded):
    """Bỏ tiền tố 'tp', 'thanh pho', 'tinh', 't.', 'tp.' ở đầu."""
    return re.sub(r"^(?:tp\.?|thanh pho|tinh|t\.)\s+", "", folded).strip()


# {biến thể đã bỏ dấu: tên chuẩn}. Dựng một lần lúc import.
_LOOKUP = {}
_MATCH_TERMS = []  # (regex đã biên dịch, tên chuẩn) - dài trước, để "vũng tàu" không nuốt "bà rịa - vũng tàu"
for _canonical, _aliases in _PROVINCES.items():
    _variants = {_fold(_canonical), _strip_admin_prefix(_fold(_canonical))}
    for _a in _aliases:
        _variants.add(_fold(_a))
    for _v in _variants:
        if _v:
            _LOOKUP.setdefault(_v, _canonical)
for _term in sorted(_LOOKUP, key=len, reverse=True):
    _MATCH_TERMS.append((re.compile(r"(?<![a-z0-9])" + re.escape(_term) + r"(?![a-z0-9])"),
                         _LOOKUP[_term]))


def canonical_province(text):
    """Tên tỉnh/thành chuẩn nếu `text` LÀ (hoặc bắt đầu bằng) một tỉnh đã biết,
    ngược lại trả '' — dùng để nhận diện một chuỗi đơn lẻ."""
    folded = _strip_admin_prefix(_fold(text))
    if folded in _LOOKUP:
        return _LOOKUP[folded]
    # "khanh hoa (tat ca quan/huyen)" -> tách phần đầu trước dấu ( , : ;
    head = re.split(r"[(,:;/-]", folded, 1)[0].strip()
    return _LOOKUP.get(head, "")


def find_provinces(text):
    """Mọi tỉnh/thành xuất hiện trong `text` (bỏ dấu, không phân biệt hoa
    thường), theo thứ tự xuất hiện, không trùng. Dùng để quét text CV."""
    folded = _fold(text)
    hits = []
    claimed = [False] * len(folded)
    for pattern, canonical in _MATCH_TERMS:  # dài trước
        for match in pattern.finditer(folded):
            if any(claimed[match.start():match.end()]):
                continue
            for i in range(match.start(), match.end()):
                claimed[i] = True
            hits.append((match.start(), canonical))
    seen, out = set(), []
    for _pos, canonical in sorted(hits):
        if canonical not in seen:
            seen.add(canonical)
            out.append(canonical)
    return out


def normalize_location(raw):
    """Chuẩn hoá một giá trị "nơi làm việc mong muốn" thô.

    - Nếu nhận ra một hoặc nhiều tỉnh/thành → trả tên chuẩn, nối bằng ", ".
    - Nếu không (vd chỉ có tên quận, hoặc text lạ) → trả lại chuỗi đã gọn.
    """
    raw = re.sub(r"\s+", " ", str(raw or "")).strip(" ,;|·-")
    if not raw:
        return ""
    provinces = find_provinces(raw)
    if provinces:
        return ", ".join(provinces)
    return raw[:150]
