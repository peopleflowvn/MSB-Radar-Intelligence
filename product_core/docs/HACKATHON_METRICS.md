# Đo lường tác động — MSB Radar

**Master Plan:** mục 23–26 · **Hạn hoàn thành:** trước 14/09/2026

> **Quy tắc số một của tài liệu này: KHÔNG BỊA SỐ.**
>
> Một con số đẹp không kiểm chứng được sẽ thành câu hỏi không trả lời nổi trong
> phần Q&A, và mất nhiều điểm hơn hẳn so với việc trung thực nói *"mẫu nhỏ,
> n=5"*. Tiêu chí Impact chấm **bằng chứng**, không chấm độ lớn của con số.
>
> Mọi ô trong tài liệu này để trống cho tới khi có người thật chạy phép đo thật.
> Ô trống là trung thực; ô điền bừa là rủi ro bị hỏi vặn.

---

## 1. Ba loại số, ba mức tin cậy khác nhau

Phải phân biệt rõ, và phải **nói rõ trên slide** loại nào là loại nào:

| Loại | Nguồn | Dùng được để nói gì |
|---|---|---|
| **A. Đếm được từ hệ thống** | `GET /hub/capture/`, `GET /ai/usage/` | Sự thật về dữ liệu đang có. Không tranh cãi được. |
| **B. Đo có kiểm soát** | Bài đo tay, mẫu nhỏ, có phương pháp | *"Trên mẫu n=…, Radar nhanh hơn X lần"* |
| **C. Ước tính** | Suy ra từ A và B | Phải gọi đúng tên là **ước tính**, kèm giả định |

Sai lầm cần tránh: trình bày loại C như loại A. Giám khảo ngân hàng sẽ hỏi
nguồn số, và trả lời *"chúng tôi ước tính"* sau khi đã nói như thể đo được là
mất niềm tin cho toàn bộ phần còn lại.

---

## 2. Loại A — số đếm được ngay hôm nay

Lấy trực tiếp từ hệ thống, không cần chuẩn bị gì:

```bash
# Năng lực thu thập và hợp nhất
curl -s .../api/v1/hub/capture/ | jq

# Bằng chứng dùng GreenNode
curl -s .../api/v1/ai/usage/ | jq
```

| Chỉ số | Nguồn | Giá trị (điền khi chốt demo) |
|---|---|---|
| Bản ghi nguồn đã nhận | `capture.consolidation.source_records` | |
| Hợp nhất thành người | `capture.consolidation.unique_people` | |
| Người đến từ nhiều nền tảng | `capture.consolidation.multi_source_people` | |
| Nhiều nguồn nhất cho một người | `capture.consolidation.max_sources_for_one_person` | |
| Lượt hồ sơ / người | `capture.consolidation.records_per_person` | |
| Bóc tách CV thành công | `capture.parsing.success_rate` | |
| Lượt gọi GreenNode | `ai_usage.by_provider[greennode].calls` | |
| Tỷ lệ thành công GreenNode | `…success_rate` | |
| Độ trễ trung bình GreenNode | `…avg_latency_ms` | |
| Lượt phải dùng dự phòng | `ai_usage.fallback_calls` | |

**Cảnh báo:** với dữ liệu demo (`seed_demo`), các số này mô tả **dữ liệu giả
lập**, phải nói rõ điều đó. Chúng chứng minh *cơ chế chạy được*, không chứng
minh *quy mô thật*.

---

## 3. Loại B — bài đo có kiểm soát

### 3.1. Thời gian tới shortlist dùng được

**Câu hỏi:** cùng một nhu cầu tuyển dụng, recruiter mất bao lâu để có danh sách
5 ứng viên đáng gọi?

**Cách làm:**

```text
Chuẩn bị    1 JD thật (dùng JD Hero: Senior Data Analyst, Hà Nội, SQL/Python)
            Cùng một kho dữ liệu cho cả hai nhánh

Nhánh THỦ CÔNG   recruiter tìm bằng công cụ đang dùng hằng ngày
                 bấm giờ từ lúc nhận JD tới lúc có 5 hồ sơ đã đọc qua
                 ghi lại: số hồ sơ phải mở, số hồ sơ bị loại

Nhánh RADAR      cùng recruiter đó, cùng JD, dùng MSB Radar
                 bấm giờ y hệt

Lặp lại     ≥ 3 recruiter × 1 JD, hoặc 1 recruiter × 3 JD khác nhau
```

**Bẫy phải tránh:** cùng một người làm nhánh thủ công **trước** rồi mới làm
nhánh Radar sẽ nhanh hơn ở lần hai chỉ vì đã quen JD. Đảo thứ tự giữa các người
tham gia, hoặc dùng JD khác nhau cho hai nhánh của cùng một người.

| Người | JD | Thủ công (phút) | Radar (phút) | Hồ sơ phải mở (TC/Radar) |
|---|---|---|---|---|
| | | | | |

### 3.2. Acceptance@10

**Câu hỏi:** trong 10 kết quả đầu Radar trả về, bao nhiêu cái recruiter thấy
đáng gọi?

Người đánh giá **không được** là người viết hệ thống. Đưa danh sách 10 hồ sơ
(đã ẩn điểm) cho recruiter, hỏi từng cái: *đáng gọi / không đáng gọi / không rõ*.

| Người đánh giá | JD | Đáng gọi | Không | Không rõ |
|---|---|---|---|---|
| | | | | |

### 3.3. Tỷ lệ tái sử dụng hồ sơ cũ

**Câu hỏi:** trong kết quả tìm kiếm, bao nhiêu hồ sơ đến từ lần ứng tuyển **cũ
hơn 12 tháng** — tức là những hồ sơ mà nếu không có Hub thì gần như không tìm
lại được?

Đếm được từ hệ thống, nhưng thuộc loại B vì cần một truy vấn có chủ đích, không
phải một con số sẵn trên dashboard.

### 3.4. RB — tỷ lệ chấp nhận đề xuất

**Câu hỏi:** cho RM xem 10 đề xuất, họ sẽ nhận bao nhiêu?

Quan trọng: hỏi **lý do từ chối** cho từng cái bị bỏ. Lý do có giá trị hơn tỷ
lệ — *"sai sản phẩm"* và *"khách này tôi đã chăm rồi"* dẫn tới hai cách sửa
hoàn toàn khác nhau.

| RM | Đề xuất xem | Nhận | Bỏ | Lý do bỏ hay gặp nhất |
|---|---|---|---|---|
| | | | | |

### 3.5. Độ chính xác tín hiệu (Signal Precision)

Cho người có nghiệp vụ xem 20 tín hiệu Social Radar phát hiện, hỏi:
*tín hiệu này có thật sự cho thấy nhu cầu tài chính không?*

---

## 4. Loại C — ước tính giá trị kinh tế (AEV)

Tiêu chí Impact của BTC nhắc tới **AEV — Annual Economic Value**. Đây bắt buộc
là ước tính, và phải trình bày đúng như vậy.

**Khung tính, mọi biến phải ghi rõ nguồn:**

```text
AEV(tuyển dụng) = số vị trí tuyển/năm
                × giờ tiết kiệm mỗi vị trí        ← từ mục 3.1
                × chi phí giờ công recruiter      ← GIẢ ĐỊNH, ghi rõ
```

```text
AEV(bán lẻ) = số RM
            × số cơ hội thêm mỗi RM/tháng          ← từ mục 3.4
            × 12
            × tỷ lệ chuyển đổi                     ← GIẢ ĐỊNH, ghi rõ
            × giá trị trung bình một khách          ← GIẢ ĐỊNH, ghi rõ
```

**Quy tắc trình bày:** mỗi giả định phải hiện trên slide hoặc trong phần phụ
lục, kèm chữ *"giả định"*. Một AEV kèm giả định minh bạch mạnh hơn nhiều so với
một con số lớn không ai kiểm được — và nó biến câu hỏi vặn của giám khảo thành
một cuộc thảo luận thay vì một cú vấp.

**Không dùng số liệu tài chính thật của MSB** mà đội không được phép công bố.
Thể lệ cấm, và đó là điều kiện loại.

---

## 5. Chọn đúng 3–5 số cho pitch

Kế hoạch (§43) yêu cầu **đúng 3–5 chỉ số**, không hơn. Đề xuất:

```text
1. Hợp nhất đa nguồn      "N lượt hồ sơ từ M nền tảng → 1 con người"   [A]
2. Thời gian tới shortlist "từ X phút xuống Y phút"                    [B]
3. Tái sử dụng hồ sơ cũ    "Z% kết quả đến từ hồ sơ >12 tháng"         [B]
4. RB chấp nhận đề xuất    "RM nhận K/10 đề xuất"                      [B]
```

Số 1 là số **không thể tranh cãi** và cũng là số kể đúng câu chuyện trung tâm.
Nếu chỉ được nói một con số, nói số đó.

---

## 6. Nhật ký thực hiện

| Ngày | Phép đo | Người chạy | Kết quả | Ghi chú |
|---|---|---|---|---|
| | | | | |

---

## 7. Nhãn bắt buộc khi trình bày

Mọi số loại B đi kèm nhãn này, không có ngoại lệ:

> **Controlled Hackathon Benchmark — n=…, đo ngày …/09/2026**

Mọi số chạy trên dữ liệu `seed_demo` đi kèm:

> **Dữ liệu giả lập — chứng minh cơ chế, không phải quy mô thật**
