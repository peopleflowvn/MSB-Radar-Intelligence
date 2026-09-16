# -*- coding: utf-8 -*-
"""Growth Answer Engine — trả lời câu hỏi tìm khách hàng tiềm năng có dẫn chứng.

Thay cho `rb/prospects.py`, vốn ép mọi câu hỏi vào **tám khoá JSON cố định** rồi
lọc bằng `Q(icontains)` — đúng kiến trúc mà `talent/answer/` sinh ra để thay thế.
Hệ quả đo được của bộ cũ: hỏi "khách nào có dấu hiệu chuẩn bị mua nhà" thì
"dấu hiệu chuẩn bị mua nhà" không rơi vào khoá nào và biến mất im lặng, RM nhận
về một danh sách lọc theo tỉnh.

Dùng chung khung với Talent (`core/answer/`): RRF, verify, cache, runner, steps.
Năm chặng cũng giống. Nhưng **không phải Talent đổi từ "ứng viên" sang "khách
hàng"** — năm chỗ khác nhau về bản chất, và mỗi chỗ là một quyết định sản phẩm:

1. **Bằng chứng động, có trục thời gian.** Talent đọc CV: tĩnh, mô tả quá khứ,
   một CV hai năm trước vẫn nói đúng người đó từng làm gì. Growth đọc tín hiệu:
   bài đăng, quan tâm sản phẩm, kết quả tiếp cận — tất cả đều có thời điểm và
   **mất giá theo thời gian**. "Đang hỏi vay mua nhà" ba ngày trước và tám tháng
   trước là hai chuyện khác nhau. Nên độ mới nằm TRONG phép hợp nhất
   (`retrieve.py`), không phải một bộ lọc bật/tắt.

2. **Câu hỏi luôn ngầm chứa ưu tiên.** Talent hỏi "ai thoả tiêu chí". Growth hỏi
   "ai đáng gọi" — kể cả khi câu chữ không nói vậy. Nên ④ xếp theo
   `rb/scoring.py::priority_score` (fit × need × timing × reachability × value),
   không phải theo độ liên quan truy hồi.

3. **Đầu ra là hành động.** Ở Talent, `action` là công dân hạng hai. Ở đây nó là
   sản phẩm: chào nhóm sản phẩm nào, vì sao, và bước tiếp theo — do CODE chọn
   (`scoring.recommend_action`), LLM chỉ viết lời.

4. **Ràng buộc tuân thủ ngược chiều và nặng hơn.** `do_not_contact` là chặn
   tuyệt đối, không phải bộ lọc; `sales_owner` để RM không giẫm chân nhau; cơ
   hội đang mở phải hiện ra thay vì bị chào lại. Những thứ này áp ở ② chứ không
   ở ⑤ — một ràng buộc tuân thủ nằm trong prompt là một ràng buộc chưa có.

5. **Hai shape không tồn tại bên Talent:** `portfolio` (câu về chính danh mục
   của RM) và `whitespace` (khách chưa ai chăm).
"""
from .engine import AnswerResult, answer, stream_answer   # noqa: F401
from .plan import ProspectPlan                            # noqa: F401
