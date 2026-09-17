# Cực trị toàn kho & trường có cấu trúc

Ngày 05/09/2026. Trả lời câu hỏi: *"embedding vector đã giải quyết tìm toàn kho
chưa? có cần parsing CV thành trường có nhãn khi vào hub không?"*

## 1. Vector search KHÔNG giải quyết cực trị

Vector search **có** quét toàn kho — nhưng nó trả lời một câu khác:

| Câu hỏi | Phép toán | Vector làm được? |
|---|---|---|
| "ai giống 'chuyên viên QHKH' nhất" | xếp hạng theo độ tương tự | ✅ đúng việc của nó |
| "ai **lớn tuổi nhất**" | lấy MAX(năm sinh) trên mọi người | ❌ |

Nhúng cụm *"lớn tuổi nhất"* thành vector rồi tìm → kéo về CV có chữ **gần
nghĩa** ("nhiều tuổi", "40 năm kinh nghiệm", "sinh năm 197x"). Đó là xấp xỉ mờ:
bỏ sót người sinh 1965 mà CV chỉ ghi `1965`, và không có gì đảm bảo người đầu
danh sách là người già **nhất**.

Cực trị = cần **giá trị** thuộc tính của **mọi** người, rồi `MAX()`/`MIN()`.
Đó là phép **tổng hợp trên dữ liệu**, khác lớp với truy hồi. Cùng nhóm với
"đếm bao nhiêu người ngành X", "phân bố theo tỉnh" — đều cần dữ liệu có cấu
trúc chứ không phải độ tương tự.

## 2. Đã làm (05/09) — lưới đỡ tất định, không cần bật extraction

`talent/answer/superlative.py` + fast-path trong `engine._pipeline`:

* Nhận diện câu "top-N theo thuộc tính X trên TOÀN kho, không lọc gì khác"
  (`sort_by` có, `must_have` rỗng, ≤1 `should_have`, có dấu "trong kho"/"nhất").
* Quét **một lần** qua mọi người (chưa gộp) có CV, bóc thuộc tính bằng **LUẬT**:
  * `số năm kinh nghiệm` → cột `TalentProfile.years_experience` (Edge/intake
    điền), thiếu thì ước từ mốc năm sớm nhất trong CV.
  * `năm sinh` / `tuổi` / `năm tốt nghiệp` → regex trên `Document.parsed_text`
    (dòng "Sinh năm 19xx", "Ngày sinh: dd/mm/yyyy" rất khuôn mẫu).
* Sắp toàn bộ, trả top-`limit` + **độ phủ**: "đã xét K/N hồ sơ có dữ liệu".
  ⑤ nói thẳng bao nhiêu người không xác định được (`missing_sort_value`).
* Không gọi LLM. Vài trăm mili-giây. Mở rộng tuyến tính khi kho lớn.
* Câu có tiêu chí nghề nghiệp ("java dev nhiều KN nhất") KHÔNG đi đường này —
  để truy hồi ngữ nghĩa + sắp trong pool lo (regex không lọc được kỹ năng).

**Giới hạn của lưới đỡ:** regex chỉ bắt được khi CV ghi năm sinh theo khuôn dễ
đoán. CV không ghi tuổi → người đó nằm ngoài `coverage_have`, và ⑤ nói rõ.

## 3. Đường đúng — parsing có nhãn lúc ingest (như bạn đề xuất)

Hạ tầng **đã tồn tại**, chỉ chưa bật + chưa nối:

| Có sẵn | Trạng thái |
|---|---|
| `intel/extraction.py` — Edge map → text CV → AI fill 14 trường | Tắt (`INTEL_AUTO_ENQUEUE_EXTRACTION=False`) |
| `ExtractedFact` — (field, normalized_value, canonical_code, confidence, is_current) | Bảng có, 90 fact (đều từ Edge, không phải AI) |
| `intel/field_rules.py` — 24 trường có nhãn + gate auto-accept | Đầy đủ |
| `intel/registry.py` — Canonical Registry chuẩn hoá (job_title, company, skill, industry, seniority, education…) | Có |
| `talent/search.py` — lọc + **sắp theo `years_experience`** trên toàn kho | Chạy, nhưng Answer Engine không gọi |

### Việc còn phải làm cho đường đúng

**P1 — Sửa + bật extraction ở ingest:**
* `_ai_extract` đang hỏng: prompt 12K ký tự → GreenNode timeout → rơi sang
  gemini → JSON cắt giữa chừng (xem `NGHIEM_THU_2026-09-04.md` §2). Sửa: chia
  CV nhỏ hơn, hoặc model đọc-dài rẻ, hoặc route sang model không cắt. Đo lại.
* Thêm `year_of_birth` (số năm, không nhạy như ngày đầy đủ) vào `_AI_FILLABLE`
  — hoặc trích bằng regex như §2, tất định, không tốn lượt AI.
* `INTEL_AUTO_ENQUEUE_EXTRACTION=True` + chạy `backfill_extraction` cho hồ sơ
  hiện có. **Cần bạn duyệt** — chi phí token cho toàn kho.

**P2 — Answer Engine đọc facts có cấu trúc:**
* Câu cực trị / lọc thuần → query `ExtractedFact`/`TalentProfile` `ORDER BY`
  trên TOÀN kho, bỏ ②③ (mở rộng `superlative.py` thành đọc-fact thay regex).
* Câu hybrid ("java dev nhiều KN nhất") → structured filter thu hẹp tập →
  vector xếp trong đó.
* Độ phủ thấp → nói rõ "sắp theo N/kho", như §2 đã làm.

**P3 — Regex fast-path cho trường khuôn mẫu** (năm sinh, năm tốt nghiệp, số năm
KN) chạy lúc ingest, đổ vào `ExtractedFact` với `source_kind=cv_text`,
`confidence` cao — rẻ, tất định, giảm tải cho bước AI.

## 3b. Đã làm tiếp (05/09 tối) — theo đúng chỉ đạo "phải rà soát toàn kho, phải parsing gán nhãn"

**P1 — sửa gốc bước AI, xác nhận trên production:**
* Bug thật: `_ai_extract` **thiếu `reasoning_effort="none"`** — cùng bẫy đã gặp
  nhiều lần trong phiên này. Model "nghĩ" hết ngân sách token (5000-6000 token
  sinh ra cho yêu cầu `max_tokens=1200`) thay vì viết JSON. Sửa: thêm
  `extra={"reasoning_effort": "none"}`, nâng `max_tokens` 1200→2000.
* Đo lại: 40s/lượt, JSON hỏng ~50% → **6,1-6,7s/lượt, JSON hợp lệ ổn định**.
* Backfill theo đúng cổng an toàn có sẵn (`backfill_extraction`: 50 → 500 →
  toàn kho, dừng nếu tỷ lệ lỗi > 5%): **0 lỗi trên 648+ lượt chạy**, đang xử lý
  nốt phần còn lại của 798 người.

**P3 — tự động cho MỌI đường ingest, không phải việc làm tay:**
* `people/ingest.py::resolve_record` là điểm chốt DUY NHẤT mọi nguồn dữ liệu
  (Edge sync, nhập tay, import lô) đều đi qua trước khi thành `Person`. Bật
  `INTEL_AUTO_ENQUEUE_EXTRACTION=1` ở đúng một chỗ là đủ cho mọi đường vào.
* Thêm service `extraction-worker` trong compose — rút hàng đợi `ExtractionJob`
  LIÊN TỤC, `restart: unless-stopped`, độc lập với `hub` (không có worker thì
  bật cờ chỉ chất job vào CSDL, không ai xử lý).

**P2 — Answer Engine dùng dữ liệu có cấu trúc, đúng yêu cầu "rà soát toàn kho
rồi mới phân tích":**
* `talent/answer/structured_match.py::must_have_pins()` — `must_have` (BẮT
  BUỘC, theo đúng nghĩa `plan.py`) quy về trường có cấu trúc
  (skills/industries/languages/certifications/years_experience/education_
  level/city/...) thì khớp trên **TOÀN kho bằng SQL**, không giới hạn ở pool
  ngữ nghĩa 60 người.
* CỐ Ý là GHIM (đảm bảo có mặt để ③ xét lại bằng LLM), KHÔNG PHẢI lọc loại trừ:
  backfill chưa xong 100% nên "chưa có ExtractedFact" không được hiểu nhầm
  thành "không có thuộc tính". Trần 40 người ghim thêm — khớp nhiều là tin tốt,
  không cần đọc hết bằng LLM (giữ ngân sách thời gian ~15-40s/câu).
* Xác nhận trên production bằng đúng đường HTTP thật (`/api/v1/talent/ask/`):
  câu "tìm ứng viên trên 3 năm KN ngành ngân hàng" → `structured_pins=40`, đọc
  kỹ 60 hồ sơ, lọc còn 18 phù hợp, trả lời 10 người có trích dẫn [n] — và ③ vẫn
  tự phát hiện một trường hợp mơ hồ về ngành thay vì tin mù vào ghim cấu trúc.

**Hai lỗi ngầm bắt được khi xác minh, cả hai đều cùng một hình dạng "code mới
đọc đúng chỗ tưởng là đúng nhưng thực ra sai":**
1. `superlative.py` đọc thẳng `Document.parsed_text` (cột thô, RỖNG 100% trên
   production) thay vì `Document.best_text` (property nối qua bảng
   `ParsedTextVersion`) — phủ 0/798, không lỗi không cảnh báo.
2. `structured_match.py` chỉ đọc `TalentProfile.years_experience` (cột cũ, ít
   dữ liệu) mà bỏ qua `ExtractedFact` field="years_experience" (nguồn AI mới) —
   "trên 3 năm KN" ra 0 người dù dữ liệu đã có.

Cả hai đã sửa + có test canh đúng hình dạng lỗi (dựng fixture giống thật, không
giống fixture cũ vô tình che mất bug).

## 4. Tóm tắt

| | Cực trị đúng trên toàn kho? |
|---|---|
| Trước 05/09 | Không — lấy từ pool ~40 người gần câu hỏi |
| Sau 05/09 (đã làm) | **Có, cho `năm sinh` / `tuổi` / `năm KN`** qua lưới đỡ regex + cột `years_experience`, kèm độ phủ trung thực. Pool cũng nâng 40→60 |
| Đường đúng (P1–P3) | Bật extraction có nhãn lúc ingest → mọi trường, mọi loại câu tổng hợp, không phụ thuộc CV ghi khuôn |
