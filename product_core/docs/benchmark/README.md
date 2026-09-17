# Benchmark & bộ nhãn — Radar AI

Thư mục này giữ các **artifact đo lường** cho Master Plan §16. Chúng được commit
vào repo vì gate của các giai đoạn sau so sánh trực tiếp với chúng.

## Cấu trúc

```
docs/benchmark/
├── README.md                     ← file này
├── search_queries.sample.jsonl   ← mẫu 15 truy vấn; thay bằng truy vấn thật của recruiter/RM
├── extraction_gold.schema.json   ← schema JSON cho một dòng nhãn extraction
├── baseline/                     ← output của `manage.py baseline_search` — CÓ commit (chỉ ID + điểm)
└── label_batch/<UTC>/            ← output của `manage.py export_label_batch` — .gitignore
    ├── manifest.json
    ├── worksheet.jsonl           ← người gán nhãn điền khoá "gold" ở đây
    └── worksheet.csv
```

> **PII:** `worksheet.*` chứa toàn văn CV thật nên `docs/benchmark/label_batch/`
> nằm trong `.gitignore` (quy tắc repo: không commit dữ liệu ứng viên thật). Bộ
> nhãn vàng đã điền được lưu ở nơi nội bộ theo chính sách dữ liệu của đội, không
> đẩy lên GitHub. `search_queries.jsonl` (truy vấn thật, có thể lộ chiến lược
> tuyển dụng) cũng bị ignore — chỉ file `.sample` được commit.

## 1. Bộ nhãn extraction (theo field) — Master Plan §16.1

**Mục đích:** đo precision/recall/F1 của AI-fill-gaps theo *từng field*, không dùng
một con số chung.

**Quy trình:**

1. `python manage.py export_label_batch --count 150 --seed 42`
2. Nghiệp vụ mở `worksheet.jsonl` (hoặc `.csv`), đọc `cv_text`, điền khoá `gold`:
   - đúng giá trị nếu CV nêu rõ;
   - `""` nếu đã đọc kỹ và CV **không** có thông tin đó (khác với chưa xem);
   - với `skills` / `languages` / `certifications`: phân tách bằng dấu `;`.
3. Không sửa `current_derived` — đó là ảnh Hub suy ra hiện tại, để đối chiếu.
4. Lưu lại theo chính sách dữ liệu nội bộ (**không** commit lên GitHub — xem cảnh
   báo PII ở trên).

**Quy mô:** khởi điểm 150–200 CV, đa nguồn, cả CV tiếng Việt lẫn tiếng Anh.
Gate Giai đoạn 3 cần tối thiểu 50 CV đã gán nhãn.

**Đồng thuận giữa người gán nhãn:** ít nhất 20 CV được hai người gán độc lập; ghi
lại tỷ lệ khớp theo field. Field nào khớp < 80% thì làm rõ hướng dẫn trước khi gán tiếp.

## 2. Bộ nhãn search (theo truy vấn) — Master Plan §16.2

**Mục đích:** đo Recall@20/@50 và Precision@10/@20 của tìm kiếm, so với baseline.

**Đây là artifact khác hẳn bộ nhãn extraction** và tốn công hơn:

1. Thu 30–50 truy vấn thật recruiter/RM đã gõ (lấy từ `TalentAIAnalysis.question`
   hoặc phỏng vấn trực tiếp). Ghi vào `search_queries.jsonl` theo mẫu.
2. Với mỗi truy vấn: chạy `baseline_search --mode ai`, rồi nghiệp vụ phán quyết
   từng ứng viên trả về là **relevant / không liên quan** (nhị phân; thang 0–2
   nếu có thời gian). Lưu phán quyết cạnh truy vấn.
3. Để bắt được ứng viên phù hợp bị *bỏ sót*, pool phán quyết nên gộp kết quả của
   nhiều cấu hình (baseline structured + baseline ai), không chỉ một danh sách.

Gate Giai đoạn 0 cần tối thiểu 15 truy vấn có phán quyết.

## 3. Baseline — chạy TRƯỚC khi sửa search

```
python manage.py baseline_search --queries docs/benchmark/search_queries.sample.jsonl --mode structured
python manage.py baseline_search --queries docs/benchmark/search_queries.sample.jsonl --mode ai
```

Sau khi Giai đoạn 4 thay đổi retrieval thì **không dựng lại được** baseline này.
Chạy sớm, commit output trong `baseline/`, ghi rõ `git_rev` trong file.
