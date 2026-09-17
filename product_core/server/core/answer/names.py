# -*- coding: utf-8 -*-
"""Nhận ra TÊN NGƯỜI trong câu hỏi và khớp vào một bảng tên. Dùng chung mọi domain.

Truy hồi ngữ nghĩa + cắt top-N là không tất định: cùng câu "so sánh A và B" lần
này lọt cả hai, lần sau rớt một (ảnh test Talent 04/09). Với câu neo vào một cái
TÊN, đó là lỗi: tên là định danh, không phải gợi ý ngữ nghĩa. Nên người được gọi
đích danh phải được GHIM vào pool đọc sâu bất kể điểm truy hồi.

Khớp tên đã bỏ dấu KHÔNG phải định danh mạnh (ở VN "Nguyễn Văn A" trùng hàng
nghìn người) — chỉ để ghim cho ③ đọc; ③ vẫn là chỗ phán đoán.

Vì sao ở `core`: không phần nào ở đây biết đối tượng là ứng viên hay khách hàng.
Mỗi domain truyền vào bảng tên của QUẦN THỂ của nó (`Person.applicants()` bên
Talent, `rb.answer.population.customers()` bên Growth) — khớp tên trên toàn bảng
`Person` sẽ ghim nhầm ứng viên vào câu hỏi về khách hàng và ngược lại.
"""
from __future__ import annotations

import re

from people.normalize import normalize_name

#: Từ chức năng hay lẫn vào truy vấn nhưng KHÔNG phải một phần của tên.
STOP = {
    "ung", "vien", "ứng", "viên", "ho", "so", "hồ", "sơ", "nguoi", "người",
    "candidate", "review", "danh", "gia", "đánh", "giá", "so", "sanh", "sánh",
    "compare", "va", "và", "voi", "với", "cho", "vi", "tri", "vị", "trí",
    "list", "profile", "cv", "the", "of", "and",
}
#: KHÔNG thêm "hang", "anh", "chi" dù chúng hay đi cùng "khách hàng", "anh/chị":
#: sau khi bỏ dấu chúng là TÊN thật (Hằng, Anh, Chi) — "Mai Anh" sẽ bị cắt còn
#: một từ và không bao giờ khớp được nữa.

#: Họ Việt phổ biến — một cụm bắt đầu bằng họ thì nhiều khả năng là tên người.
SURNAMES = {
    "nguyen", "tran", "le", "pham", "hoang", "huynh", "phan", "vu", "vo",
    "dang", "bui", "do", "ho", "ngo", "duong", "ly", "dinh", "mai", "trinh",
    "dao", "cao", "lam", "ha", "chu", "ta", "kieu", "ninh", "luu", "truong",
}


def phrases(query_plan, *, stop=STOP):
    """Cụm ứng-viên-là-tên (đã bỏ dấu) từ `search_queries` và `information_need`."""
    raw = list(getattr(query_plan, "search_queries", []) or [])
    need = getattr(query_plan, "information_need", "") or ""
    # "so sánh A và B" → tách theo " và ", " với ", dấu phẩy.
    for chunk in re.split(r"\s+(?:và|voi|với|,|;)\s+", need):
        raw.append(chunk)
    seen, out = set(), []
    for text in raw:
        cleaned = re.sub(r"[^\w\sÀ-ỹ]", " ", str(text or "")).strip()
        toks = [t for t in cleaned.split() if normalize_name(t) not in stop]
        if not (2 <= len(toks) <= 5):
            continue
        folded = normalize_name(" ".join(toks))
        if not folded or folded in seen:
            continue
        # Không phải cụm nào 2–5 từ cũng là tên: chỉ nhận khi bắt đầu bằng một
        # họ Việt, hoặc mọi token đều viết hoa chữ đầu (kiểu người ta gõ tên).
        first = folded.split()[0]
        looks_name = first in SURNAMES or all(
            w[:1].isupper() for w in toks if w[:1].isalpha())
        if looks_name:
            seen.add(folded)
            out.append(folded)
    return out


def match(query_plan, name_rows, *, question="", limit=6, stop=STOP):
    """`[person_id]` khớp tên. `name_rows` là iterable `(person_id, display_name)`.

    Hai cách khớp, theo thứ tự tin cậy: họ tên đầy đủ (≥ 2 từ) xuất hiện NGUYÊN
    CỤM trong câu hỏi; rồi cụm-là-tên của kế hoạch khớp tập từ với tên hồ sơ
    (cho phép hồ sơ có tên đệm dài hơn, hoặc ngược lại).
    """
    folded_names = phrases(query_plan, stop=stop)
    if not folded_names and not question:
        return []
    index = {}
    for pid, name in name_rows:
        index.setdefault(normalize_name(name), []).append(pid)

    hits, seen = [], set()
    original = " " + re.sub(r"[?.!,;:]", " ", normalize_name(question)) + " "
    for name, pids in index.items():
        if len(name.split()) >= 2 and (" " + name + " ") in original:
            for pid in pids:
                if pid not in seen:
                    seen.add(pid)
                    hits.append(pid)
    for folded in folded_names:
        want = set(folded.split())
        for key, pids in index.items():
            key_tokens = set(key.split())
            if want <= key_tokens or key_tokens <= want:
                for pid in pids:
                    if pid not in seen:
                        seen.add(pid)
                        hits.append(pid)
        if len(hits) >= limit:
            break
    return hits[:limit]
