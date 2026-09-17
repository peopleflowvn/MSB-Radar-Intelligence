# Vận hành & Báo cáo

**Phase:** 15 — hoàn thành
**Master Plan:** mục 15, 50
**Vị trí:** `server/reports/`, `web/src/Dashboard.tsx`

---

## 1. Bốn thứ, một trang

Trước phase này, "hệ thống có đang khoẻ không" nằm rải rác:

```text
core.views_ui.summary       đồng bộ Edge
ai.views.usage_summary      chi phí AI
hiring.metrics.collect      chỉ số Talent      (Phase 8)
rb.metrics.collect          chỉ số RB          (Phase 15, mới)
agents (Phase 14)           quan sát agent     (chưa có nơi hiện ra)
```

Một quản trị viên muốn biết tình hình phải mở năm chỗ. `reports/overview.py`
gộp cả năm vào một lệnh gọi, và **không tính lại logic của chỗ nào** — chỉ gọi
và gộp. Sai công thức ở một chỗ thì mọi nơi dùng nó cùng sai theo, dễ phát
hiện; tính lại ở đây một lần nữa thì tạo ra khả năng hai nơi ra hai con số khác
nhau cho cùng một câu hỏi — chuyện tệ hơn cả không có dashboard.

---

## 2. `rb/metrics.py` — bốn chỉ số mới cho bán lẻ

Cùng nguyên tắc với `hiring/metrics.py` (Phase 8): **chưa có dữ liệu thì trả
`None`, không trả 0.**

| Chỉ số | Trả lời câu hỏi |
|---|---|
| Chốt thành công | Trong số cơ hội đã đóng, bao nhiêu thành công? |
| Cơ hội từ tín hiệu mạng xã hội | Có thật đến từ việc nghe được nhu cầu, hay toàn RM tự gõ tay? |
| Thời gian tới liên hệ đầu tiên | Từ lúc có cơ hội tới lúc RM thật sự gửi gì đó (trung vị). |
| Cơ hội có kết quả | Vòng lặp có khép được không, hay cơ hội nằm mãi không ai đụng tới? |

Chỉ số thứ hai đáng nói riêng: nó là chỉ số **duy nhất trong cả dự án** đo trực
tiếp giá trị của đường nối Social Radar → RB Radar (`social/pipeline.py`
`_route_to_rb`, Phase 13). Nếu con số này bằng 0 thì toàn bộ phần Social Radar
cho bán lẻ chỉ là hạ tầng chưa ai dùng — và người xem dashboard biết ngay,
không phải suy đoán.

---

## 3. Quan sát Agent Runtime lên dashboard

`reports/overview.py::_agents()` đọc trực tiếp `agents.models.AgentRun` (Phase
14): tổng số lượt chạy, tỉ lệ lỗi, thời gian trung vị, và số lượt theo từng
agent. Đây là lần đầu tiên số liệu Phase 14 có chỗ để hiện ra — trước đó nó chỉ
nằm trong CSDL, không ai xem được ngoài truy vấn tay.

---

## 4. Quyền: `reports` khác `talent`/`rb`

Trang vận hành hiện **cả số Talent lẫn số RB trên cùng một màn hình**. Cấp cho
Recruiter hay RB Sales sẽ cho họ thấy số của nghiệp vụ kia theo một đường vòng
mà quyết định 19/08 (RB Sales đọc Talent) không hề tính tới.

```python
ROLE_MODULES = {
    ADMIN: {..., MODULE_REPORTS},
    MANAGER: {MODULE_TALENT, MODULE_RB, MODULE_REPORTS},
    # Recruiter, Hiring Manager, RB Sales: KHÔNG có MODULE_REPORTS
}
```

Chỉ Admin và Manager — hai vai trò duy nhất mà lý do tồn tại là nhìn xuyên suốt
nhiều nghiệp vụ.

---

## 5. Saved Views — lưu bộ lọc, không lưu kết quả

```python
class SavedView(models.Model):
    owner, module, name, filters: JSONField
```

Cố ý **không** lưu sẵn danh sách người/cơ hội tại thời điểm lưu. Mở lại một
view đã lưu nghĩa là chạy lại đúng bộ lọc đó trên dữ liệu **mới nhất**, không
phải xem ảnh chụp cũ — một "view đã lưu" mà không cập nhật theo dữ liệu mới thì
vô dụng hơn cả không lưu.

Một model dùng chung cho cả hai module (`talent`, `rb`) — không có bảng riêng
cho từng loại bộ lọc, vì cả hai đều lọc bằng query string, cùng một khái niệm.

**Quyền theo `module` trong dữ liệu, không theo `RequiresReports`.** Một
recruiter lưu bộ lọc Talent hoàn toàn không cần vào được trang vận hành —
`POST /api/v1/reports/saved-views/` tự kiểm `roles.can_access(user, module)`
cho đúng module được yêu cầu lưu.

---

## 6. Exports — file tải về phải khớp đúng màn hình đang xem

```python
def _search_kwargs(params): ...          # talent/views.py
def _opportunity_queryset(request): ...  # rb/views.py
```

Cả `talent_search` (xem) và `talent_search_export` (xuất) dùng **chung một
hàm** dựng bộ lọc từ query param — không viết hai lần. Viết hai lần thì sớm
muộn cũng lệch nhau: một bên thêm bộ lọc mới, bên kia quên, và người dùng xuất
ra một file khác với thứ họ đang nhìn trên màn hình mà không ai nhận ra. Cùng
cách làm cho `rb.opportunity_list` / `rb.opportunity_export`.

Hai chi tiết kỹ thuật nhỏ nhưng tốn công nếu bỏ sót:

* **BOM ở đầu file** (`﻿`) — không có, Excel trên Windows đọc nhầm bảng mã
  và ra chữ vỡ. Cùng nguyên nhân từng gây lỗi khi ghi `.env`/`.ps1`, giờ chặn
  trước ở đầu ra thay vì để người dùng tự mở Excel rồi phát hiện.
* **`EXPORT_LIMIT = 5000`** — trần một lượt xuất, đủ rộng cho quy mô demo, đủ
  hẹp để một cú bấm nhầm "xuất hết" không khoá CSDL.

Kiểm chứng thật: lọc `skills=SQL` trên màn hình ra 6 người → xuất CSV → mở lại
bằng `urllib` với đúng cookie phiên → file có BOM, đúng 6 dòng, đúng cột, đúng
người đã lọc.

---

## 7. API

| Đường dẫn | Việc |
|---|---|
| `GET /api/v1/reports/overview/` | trang vận hành gộp — chỉ Admin/Manager |
| `GET/POST /api/v1/reports/saved-views/` | bộ lọc đã lưu của người dùng hiện tại |
| `POST/DELETE /api/v1/reports/saved-views/{id}/` | mở lại (POST) hoặc xoá (DELETE) |
| `GET /api/v1/talent/search/export/` | CSV — cùng tham số với `/talent/search/` |
| `GET /api/v1/rb/opportunities/export/` | CSV — cùng tham số với `/rb/opportunities/` |
| `GET /api/v1/rb/metrics/` | bốn chỉ số RB |

---

## 8. Còn thiếu

* Saved Views cho RB Radar — mô hình đã dùng chung được, nhưng giao diện RB
  chưa có ô "Lưu bộ lọc này" (Talent Radar có, vì đó là màn hình có bộ lọc có
  cấu trúc phong phú nhất).
* Report theo lịch (mục 15 nói "Reports" — hiện chỉ có dashboard xem trực
  tiếp, chưa có báo cáo định kỳ gửi qua email).
* Xuất CSV chưa xuất kèm được cột tuỳ chọn — cố định một bộ cột cho mỗi loại.
