# Gói đo — đưa thẳng cho recruiter/RM (mục 3, kế hoạch hackathon)

Tài liệu này là **bản cầm tay** để chạy bài đo Loại B ở `docs/HACKATHON_METRICS.md`
mục 3 — không lặp lại lý do (đọc ở đó), chỉ có phần **làm gì, theo thứ tự nào,
ghi vào đâu**. Người chạy bài đo không cần đọc gì khác ngoài file này.

> Quy tắc số một vẫn giữ nguyên: **KHÔNG BỊA SỐ**. Ô nào chưa đo thì để trống.

---

## 0. Trước khi bắt đầu — lấy số Loại A (không cần người, chạy 1 lệnh)

```bash
cd server && python manage.py benchmark_report
```

In ra đúng bảng mục 2 của `HACKATHON_METRICS.md` (bản ghi nguồn, hợp nhất,
bóc tách CV, lượt gọi GreenNode...) và một số tham chiếu nền cho mục 3.3 —
sao chép thẳng, không gõ tay, không tính nhầm.

**Chạy trên seed_demo → nhớ ghi nhãn "dữ liệu giả lập" khi trình bày.** Chạy
trên dữ liệu Edge thật thì đây mới là số Loại A thật.

---

## 1. JD Hero — dùng chung cho mục 3.1 và 3.2

```
Vị trí:      Senior Data Analyst
Nơi làm:     Hà Nội
Yêu cầu:     SQL, Python, ≥ 3 năm kinh nghiệm phân tích dữ liệu
Ưu tiên:     có kinh nghiệm ngành tài chính/ngân hàng, biết trực quan hoá
             (Tableau/Power BI), tiếng Anh giao tiếp
```

Dùng nguyên văn JD này cho mọi người tham gia — đổi JD giữa chừng làm hai
nhánh không còn so sánh được.

---

## 2. Mục 3.1 — Thời gian tới shortlist dùng được

**Người tham gia:** ≥ 3 recruiter × 1 JD, HOẶC 1 recruiter × 3 JD khác nhau
(nếu chỉ có một người, đổi JD giữa các lượt — xem bẫy bên dưới).

**Thứ tự — BẮT BUỘC đảo giữa người tham gia, không làm THỦ CÔNG trước cho tất
cả rồi mới RADAR:**

| Người tham gia # | Làm trước | Làm sau |
|---|---|---|
| 1 | Thủ công | Radar |
| 2 | Radar | Thủ công |
| 3 | Thủ công | Radar |

**Mỗi nhánh, ghi lại:**
1. Bấm giờ bắt đầu ngay khi nhận JD.
2. Dừng giờ khi có **5 hồ sơ đã đọc qua, sẵn sàng gọi**.
3. Đếm: tổng số hồ sơ phải MỞ để chọn ra 5 (không phải chỉ đếm 5 cái được chọn).

| Người | JD | Nhánh | Phút | Hồ sơ phải mở |
|---|---|---|---|---|
| | | Thủ công | | |
| | | Radar | | |

Dán kết quả vào bảng mục 3.1 của `HACKATHON_METRICS.md`.

---

## 3. Mục 3.2 — Acceptance@10

**Người đánh giá KHÔNG được là người viết hệ thống** (recruiter/RM thật, chưa
từng thấy code).

1. Dùng JD Hero ở trên, chạy tìm kiếm trên Radar, lấy 10 kết quả đầu.
2. **Ẩn điểm số** trước khi đưa cho người đánh giá (che cột điểm, hoặc export
   danh sách không kèm điểm).
3. Hỏi từng hồ sơ: **đáng gọi / không đáng gọi / không rõ**.

| Người đánh giá | JD | Đáng gọi | Không | Không rõ |
|---|---|---|---|---|
| | | | | |

---

## 4. Mục 3.4 — RB: tỷ lệ chấp nhận đề xuất

1. Chọn một RM, mở "Cơ hội hôm nay" (Master Plan mục 28).
2. Cho xem đúng 10 đề xuất liên tiếp — không chọn lọc trước.
3. Với **mỗi đề xuất bị bỏ**, hỏi ngay lý do (đừng gộp lại hỏi cuối buổi — lý
   do nhớ ngay lúc đó chính xác hơn nhớ lại sau).

| RM | Đề xuất xem | Nhận | Bỏ | Lý do bỏ (từng cái) |
|---|---|---|---|---|
| | 10 | | | |

---

## 5. Mục 3.5 — Độ chính xác tín hiệu (Social Radar)

1. Lấy 20 tín hiệu Social Radar mới nhất phát hiện được.
2. Cho người có nghiệp vụ (RM/quản lý bán lẻ) xem, hỏi từng cái: **"tín hiệu
   này có thật sự cho thấy nhu cầu tài chính không?"**

| # | Tín hiệu (tóm tắt) | Đúng nhu cầu? |
|---|---|---|
| 1 | | |
| … | | |
| 20 | | |

---

## 6. Sau khi đo xong

1. Copy toàn bộ số vừa ghi vào bảng tương ứng trong `docs/HACKATHON_METRICS.md`
   (mục 3 + mục 6 "Nhật ký thực hiện" — ghi ngày, ai chạy, kết quả, ghi chú).
2. Mọi số ở đây khi lên slide phải kèm đúng nhãn mục 7 của tài liệu đó:
   > **Controlled Hackathon Benchmark — n=…, đo ngày …/09/2026**
3. Nếu mẫu nhỏ (n=1, n=2...) — nói thẳng là mẫu nhỏ. Trung thực về cỡ mẫu
   mạnh hơn một con số đẹp không ai kiểm chứng được.
