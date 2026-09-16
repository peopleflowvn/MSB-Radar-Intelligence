# -*- coding: utf-8 -*-
"""Hợp nhất nhiều danh sách xếp hạng thành một. Dùng chung mọi domain.

Reciprocal Rank Fusion: mỗi nhánh truy hồi (vector hồ sơ, vector đoạn văn bản,
full-text, và ở Growth thêm nhánh tín hiệu) trả về một danh sách người đã xếp
hạng. RRF cộng `1/(k + thứ_hạng)` qua các danh sách, nên:

* không nhánh nào chiếm pool chỉ vì nó chạy trước hoặc trả nhiều kết quả hơn;
* người được NHIỀU nhánh cùng gọi tên sẽ nổi lên, kể cả khi không nhánh nào xếp
  họ hạng nhất — đó chính là tín hiệu ta muốn;
* điểm thô của từng nhánh (cosine, BM25, độ mới) không cần cùng thang đo, vì chỉ
  THỨ HẠNG được dùng. Đây là lý do RRF hợp với việc ghép các nhánh khác bản chất.

**Vì sao không phụ thuộc nghiệp vụ:** hàm chỉ nhận các danh sách khoá (id người)
và trả về thứ tự. Nó không biết khoá đó trỏ tới ứng viên hay khách hàng tiềm
năng, cũng không biết vì sao một nhánh xếp hạng như vậy.
"""
from __future__ import annotations

#: Hằng làm mềm của RRF. k lớn thì chênh lệch giữa hạng 1 và hạng 10 nhỏ lại,
#: tức tin vào SỐ NHÁNH đồng thuận hơn là tin vào thứ hạng trong một nhánh.
#: 60 là giá trị gốc của bài báo RRF và là mặc định của cả hai domain.
DEFAULT_K = 60


def reciprocal_rank_fusion(ranked_lists, k=DEFAULT_K, weights=None):
    """Trả `(order, hits)`.

    `order`  list `(key, score)` giảm dần theo điểm hợp nhất.
    `hits`   dict `key → số nhánh chạm tới key này` — dùng để biết một người nổi
             lên nhờ đồng thuận nhiều nhánh hay chỉ nhờ một nhánh duy nhất.

    `weights`: hệ số cho từng danh sách, cùng thứ tự với `ranked_lists`. Bỏ
    trống thì mọi nhánh ngang nhau — đúng cho Talent. Growth cần nó vì các nhánh
    ở đó KHÔNG ngang nhau: một tín hiệu mua hàng quan sát được tuần trước đáng
    tin hơn một dòng nghề nghiệp khớp chữ.
    """
    scores, hits = {}, {}
    for index, ranked in enumerate(ranked_lists):
        weight = 1.0 if weights is None else float(weights[index])
        for rank, key in enumerate(ranked, start=1):
            scores[key] = scores.get(key, 0.0) + weight / (k + rank)
            hits[key] = hits.get(key, 0) + 1
    # Khoá chỉ là tie-break SAU điểm liên quan. Không có nó thì thứ tự chèn vào
    # cơ sở dữ liệu quyết định ai vào pool đọc sâu — cùng một câu hỏi cho hai
    # kết quả khác nhau giữa hai lần chạy.
    order = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))
    return order, hits
