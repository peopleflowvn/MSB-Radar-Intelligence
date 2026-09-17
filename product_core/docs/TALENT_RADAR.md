# Talent Radar — Central Database

**Phase:** 6 — hoàn thành
**Master Plan:** mục 19.2, 19.3, 24, 43
**Vị trí:** `server/talent/`

---

## 1. TalentProfile là gì

`Person` là con người. `TalentProfile` là **góc nhìn tuyển dụng** về con người đó.
RB Radar sẽ có `RBProfile` riêng gắn lên cùng một `Person`.

Đó chính là Nguyên tắc 2 — một People Database, nhiều nghiệp vụ — thể hiện bằng code:
không sao chép con người sang cơ sở dữ liệu thứ hai.

```text
Person
├── TalentProfile   ← Phase 6
│   ├── Tag         nhãn mô tả con người
│   └── Pool        nhóm do recruiter gom, mô tả việc đang làm với họ
└── RBProfile       ← Phase 12
```

**Tag khác Pool:** Tag mô tả *con người* ("python", "biết tiếng Nhật"). Pool mô tả
*việc đang làm với họ* ("Data Analyst Q4/2026", "Đã phỏng vấn chưa tuyển"). Pool có chủ
sở hữu; Tag thì dùng chung.

---

## 2. Suy diễn hồ sơ — hai quy tắc

Một người có thể có 5 lượt ứng tuyển ở 3 nguồn, trải dài 3 năm. `derive.py` gộp chúng
thành một góc nhìn duy nhất.

### Quy tắc 1: bản ghi mới nhất thắng

CV nộp tháng trước phản ánh hiện tại tốt hơn CV ba năm trước. Trường nào trống ở bản
mới thì lấy giá trị gần nhất còn có.

> **Sắp theo `applied_ts` trong payload, không theo lúc Hub nhận.** Một CV cũ tải về
> hôm nay vẫn là CV cũ. Đây là lỗi dễ mắc nhất ở module này và có test riêng canh.

**Ngoại lệ: kỹ năng được GỘP qua mọi bản ghi**, không chỉ lấy bản mới nhất. Người từng
dùng SQL ba năm trước thì vẫn biết SQL, dù CV mới không nhắc lại.

### Quy tắc 2: con người thắng máy

Trường nào recruiter đã sửa tay được ghi vào `curated_fields` và **không bao giờ bị ghi
đè**. Recruiter đã nói chuyện với ứng viên biết rõ hơn bất kỳ CV nào.

Nút *Suy lại* không phải nút hoàn tác — nó cập nhật những trường máy suy ra, giữ nguyên
những gì con người đã sửa.

Cùng nguyên tắc với `_refresh_snapshot()` ở People Core: dữ liệu mới không nhất thiết
đúng hơn dữ liệu đã có.

### Đọc dữ liệu bẩn

| Đầu vào | Kết quả |
|---|---|
| `"SQL, Python; Power BI"` | `["SQL", "Python", "Power BI"]` |
| `"Machine Learning"` | `["Machine Learning"]` — **không** tách theo khoảng trắng |
| `"3 năm"`, `"5 years"`, `"hơn 2 năm"`, `"2,5 năm"` | `3.0`, `5.0`, `2.0`, `2.5` |
| `"1990"` (gõ nhầm năm sinh vào ô kinh nghiệm) | `None` — chặn trên 60 năm |

---

## 3. Tìm kiếm

Theo Master Plan mục 43: PostgreSQL + index + full-text + bộ lọc có cấu trúc.
**Chưa dùng vector search** — chỉ thêm nếu đo được rằng nó thật sự tốt hơn.

### Dev chạy SQLite, thật chạy PostgreSQL

Toàn bộ **bộ lọc có cấu trúc** (kỹ năng, nơi ở, số năm, pool, nguồn, sản phẩm quan tâm,
trạng thái quan hệ khách hàng và cơ hội đang mở…) giống hệt
nhau ở hai backend vì chúng là truy vấn quan hệ thuần. Chỉ **tìm chữ tự do** là khác,
và khác biệt gói gọn trong đúng một hàm — `_free_text()`.

> **Một khiếm khuyết đã sửa:** bản đầu dùng `icontains`, khiến tìm `"An"` (tên riêng
> rất phổ biến) khớp cả `"An-alyst"`. Nghiêm trọng hơn là nó làm nhánh dev hành xử
> **khác hẳn** nhánh thật: PostgreSQL `SearchQuery` khớp theo lexeme nên `"An"` không
> bao giờ khớp `"Analyst"`. Đã đổi sang khớp theo **biên từ** (`\bAn\b`) để hai backend
> cho cùng ngữ nghĩa. Chuỗi tìm kiếm được `re.escape` — nó đến từ người dùng.

`iregex` không dùng được index, nhưng đó chỉ là nhánh SQLite cho dev; nhánh thật dùng
index full-text của PostgreSQL.

### Ngữ nghĩa bộ lọc

**Nhiều kỹ năng là AND, không phải OR.** Chọn "SQL" và "Python" nghĩa là muốn người
biết *cả hai*. Nhãn cũng vậy.

**Sắp xếp mặc định là độ tươi.** Với recruiter, người vừa nộp CV tuần trước đang tìm
việc; người nộp ba năm trước thì chưa chắc.

**Lọc theo khả năng liên hệ** (`has_email`, `has_phone`): hồ sơ không có cách liên lạc
nào thì recruiter không dùng được, dù khớp đến đâu (Master Plan mục 23).

### Đây là hợp đồng cho Phase 7

Tìm bằng ngôn ngữ tự nhiên (Phase 7) sẽ gọi lại **chính hàm này** sau khi LLM dịch câu
hỏi thành bộ tiêu chí có cấu trúc. Vì vậy tham số của `search()` chính là thứ Phase 7
phải sinh ra — không phải một đường tìm kiếm thứ hai song song.

---

## 4. Person 360

`GET /api/v1/talent/people/<id>/` gom mọi thứ về một con người vào **một** phản hồi:
danh tính, nguồn, tài liệu, dòng thời gian, tín hiệu, quan hệ, pool, hồ sơ tuyển dụng.

Một lời gọi thay vì bảy — đây là màn hình recruiter dừng lại lâu nhất nên độ trễ cảm
nhận rõ nhất.

Person đã gộp trả **301** kèm `redirect_to`, thay vì hiện một hồ sơ rỗng.

Tab **Kho CV** luôn ưu tiên preview file gốc ngay trên màn hình. Text trích xuất không chiếm diện
tích thường trực; người dùng mở modal khi cần, chọn giữa mọi kết quả parsing và nhận cảnh báo rõ
số lượt nộp, số file gốc, số nội dung khác nhau, số lượt trùng và số CV chưa parsing.

### Lượt xem được khử trùng lặp trong ngày

Không khử thì timeline sẽ toàn dòng "đã xem" và không còn đọc được.

Nhật ký truy cập đầy đủ phục vụ tuân thủ là `AccessLog` ở Phase 5B — **hai thứ khác
nhau**, xem [ACCESS_CONTROL.md §3](ACCESS_CONTROL.md).

---

## 5. API

| Endpoint | Việc |
|---|---|
| `GET /talent/search/` | Tìm kiếm theo bộ lọc |
| `POST /talent/ai-search/` | Hỏi bằng lời; dùng cache chung, `force: true` mới phân tích lại |
| `GET /talent/facets/` | Giá trị bộ lọc chung cho Recruiter và RM |
| `GET /talent/people/<id>/` | Person 360 |
| `PATCH /talent/people/<id>/profile/` | Sửa hồ sơ (đánh dấu curated) |
| `POST /talent/people/<id>/rederive/` | Suy lại từ nguồn |
| `POST|DELETE /talent/people/<id>/tags/` | Gắn / gỡ nhãn |
| `GET|POST /talent/tags/` | Danh sách / tạo nhãn |
| `GET|POST /talent/pools/` | Danh sách / tạo pool |
| `POST|DELETE /talent/pools/<id>/members/` | Thêm / bỏ thành viên |

Mọi endpoint yêu cầu đăng nhập. Khoá API của Edge **không** mở được — Edge thu thập dữ
liệu, không đọc kho talent.

Phân quyền theo vai trò là Phase 5B; hiện mọi người dùng đã đăng nhập đều xem được.

---

## 6. Đã kiểm chứng đầu cuối

Edge thật → HTTP thật → Hub → Person → TalentProfile → tìm kiếm. 5 lượt ứng tuyển của
3 người:

```text
3 nguồn của cùng một người            → 1 Person, 3 SourceRecord
Chức danh                             → "Senior Data Analyst" (từ CV mới nhất)
Kỹ năng                               → gộp từ cả 3 CV: Python, Airflow, Power BI, SQL, Excel
Kinh nghiệm "4 năm"                   → 4.0

Bộ lọc:  tất cả 3 · SQL 2 · SQL+Excel 1 · Hà Nội 2 · >5 năm 2 · Analyst+Hà Nội 1
Recruiter sửa chức danh → suy lại → vẫn giữ nguyên
```

---

## 7. Còn thiếu

- [x] ~~Giao diện React cho tìm kiếm và Person 360~~ — Phase 6, `web/src/Talent.tsx` + `Person360.tsx`
- [x] ~~Document gắn file CV thật~~ — Phase 5, Edge đã đồng bộ file
- [x] ~~`find_similar` (Master Plan mục 22)~~ — làm sau Phase 12, xem `docs/AI_TALENT_SEARCH.md` mục 7
- [x] ~~Chấm điểm khớp JD (mục 23)~~ — Phase 7/8, `talent/scoring.py` + `hiring/jd.py`
- [ ] Facet đếm số bên cạnh bộ lọc (`search.facets()` đã có, chưa nối vào API) — vẫn còn thiếu, xác
  nhận lại qua audit Phase 15
- [ ] Index PostgreSQL full-text — cần chạy trên Postgres thật để đo
