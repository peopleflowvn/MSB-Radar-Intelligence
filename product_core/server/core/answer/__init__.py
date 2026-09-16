# -*- coding: utf-8 -*-
"""Khung chung của Answer Engine — phần KHÔNG phụ thuộc nghiệp vụ.

Talent Radar (`talent/answer/`) và Growth Radar (`rb/answer/`) đều chạy cùng một
dây chuyền năm chặng:

    ① plan → ② retrieve → ③ judge → ④ aggregate → ⑤ compose

Nhưng chỉ có phần *khung* là dùng chung được. Ranh giới đặt ở đây:

**Dùng chung** (trong gói này) — những thứ đúng bất kể đang tìm ứng viên hay
tìm khách hàng tiềm năng:

    fusion    hợp nhất nhiều danh sách xếp hạng (RRF), tie-break ổn định
    verify    đối chiếu bài viết với dữ liệu đã chốt ở ④ + vòng yêu cầu viết lại
    cache     vân tay (thực thi · quyền · kho · ngữ cảnh) và vòng đời mục cache
    runner    chạy một lượt trong luồng riêng, sống sót khi client rớt
    steps     khuôn sự kiện tiến trình đẩy ra giao diện

**Không dùng chung** (mỗi domain tự giữ) — những thứ chỉ đúng với một nghiệp vụ:
prompt của ①, nguồn bằng chứng và cách truy hồi của ②, tiêu chí phán đoán của ③,
thứ tự ưu tiên của ④, giọng văn và khuôn trình bày của ⑤.

Nguyên tắc phân chia: *một module chỉ vào đây khi nó không cần biết đối tượng
đang được tìm là ai.* Nhét phần nghiệp vụ vào đây bằng cờ `if domain == ...` là
làm hỏng chính lý do tách gói.
"""
