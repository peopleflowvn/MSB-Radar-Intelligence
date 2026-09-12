# -*- coding: utf-8 -*-
"""Chuẩn hoá tên tỉnh/thành hay gặp trong tìm kiếm (Talent Radar, RB Radar).

Người hỏi gõ nhiều cách khác nhau cho cùng một nơi — "Sài Gòn", "TP.HCM",
"tphcm" đều là Hồ Chí Minh — còn `Person.location` lưu một dạng cố định (hoặc
chính người hỏi lần sau lại gõ khác lần trước). Không chuẩn hoá thì lọc theo
địa danh **bỏ sót đúng những người đang có trong kho**, chỉ vì khác cách viết —
một lỗi im lặng: hệ thống vẫn chạy, chỉ trả về ít hơn nó nên trả.

Cố ý CHỈ liệt kê các tỉnh/thành hay xuất hiện trong dữ liệu tuyển dụng/khách
hàng ngân hàng (khớp với `CITIES` trong agent/app.py) — không cần đủ 63 tỉnh
thành: tỉnh nhỏ hơn không nhận ra được vẫn đi tiếp NGUYÊN VĂN, không biến mất.
"""
import re
import unicodedata


def _strip_diacritics(text):
    normalized = unicodedata.normalize("NFD", text)
    return "".join(ch for ch in normalized if unicodedata.category(ch) != "Mn")


def _normalize_key(text):
    """Bỏ dấu, bỏ khoảng trắng/dấu câu, chữ thường — để so khớp không phân
    biệt "TP.HCM" với "tp hcm" với "TPHCM"."""
    return re.sub(r"[^a-z0-9]", "", _strip_diacritics(str(text or "")).lower())


# dạng chuẩn -> mọi cách viết thường gặp khác (đã qua _normalize_key nên chỉ
# cần liệt kê dạng dễ đọc nhất, không cần lo dấu/hoa-thường/khoảng trắng).
ALIASES = {
    "Hồ Chí Minh": ["ho chi minh", "hcm", "tp hcm", "tphcm", "tp.hcm", "sai gon",
                    "saigon", "sg", "thanh pho ho chi minh", "hcmc"],
    "Hà Nội": ["ha noi", "hn"],
    "Đà Nẵng": ["da nang", "dn"],
    "Cần Thơ": ["can tho"],
    "Hải Phòng": ["hai phong", "hp"],
    "Bình Dương": ["binh duong"],
    "Đồng Nai": ["dong nai"],
    "Bắc Ninh": ["bac ninh"],
    "Quảng Ninh": ["quang ninh"],
    "Khánh Hoà": ["khanh hoa", "khanh hoà", "nha trang"],
    "Huế": ["hue", "thua thien hue"],
    "Vũng Tàu": ["vung tau", "ba ria vung tau", "brvt"],
}

_LOOKUP = {}
for _canonical, _variants in ALIASES.items():
    _LOOKUP[_normalize_key(_canonical)] = _canonical
    for _variant in _variants:
        _LOOKUP[_normalize_key(_variant)] = _canonical

# District-only addresses are common in CVs.  They still carry province-level
# information and must not be treated as unknown locations.
_HCM_DISTRICTS = {
    *(f"quan{i}" for i in range(1, 13)), "quanbinhthanh", "quanbinhtan",
    "quangovap", "quantanbinh", "quantanphu", "quanphunhuan", "quanthuduc",
    "thanhphothuduc", "huyenbinhchanh", "huyenhocmon", "huyencuchi",
    "huyennhabe", "huyencangio", "district1", "district2", "district3",
    "district4", "district5", "district6", "district7", "district8",
    "district9", "district10", "district11", "district12",
}
_HANOI_DISTRICTS = {
    "quanbadinh", "quanhoankiem", "quanhaibatrung", "quandongda", "quantayho",
    "quancaugiay", "quanthanhxuan", "quanhoangmai", "quanlongbien", "quannamtuliem",
    "quanbactuliem", "quanhadong", "huyendonganh", "huyengialam", "huyenthanhtri",
}


def canonical_province(text):
    """Dạng chuẩn nếu nhận ra được; nguyên văn (đã strip) nếu không.

    Trả về nguyên văn khi không nhận ra — KHÔNG phải lỗi, chỉ là tỉnh/thành
    ngoài danh sách phổ biến ở trên, và tiêu chí không được phép biến mất chỉ
    vì hàm này chưa biết tới nó.
    """
    cleaned = str(text or "").strip()
    if not cleaned:
        return cleaned
    key = _normalize_key(cleaned)
    if key in _HCM_DISTRICTS:
        return "Hồ Chí Minh"
    if key in _HANOI_DISTRICTS:
        return "Hà Nội"
    return _LOOKUP.get(key, cleaned)


def location_query_variants(text):
    """Mọi cách viết của cùng một nơi — dùng khi LỌC theo location.

    Dữ liệu trong kho có thể được ghi bằng một dạng khác với dạng chuẩn vừa
    suy ra (ví dụ Edge cũ ghi "Sài Gòn" trước khi có quy ước chung) — lọc chỉ
    theo một dạng bỏ sót người thật đang có. Trả rỗng nếu đầu vào rỗng.
    """
    canonical = canonical_province(text)
    if not canonical:
        return []
    variants = {canonical, *ALIASES.get(canonical, [])}
    return sorted(v for v in variants if v)
