# Nhập liệu ứng viên thủ công (Intake)

**Phạm vi:** thêm nguồn dữ liệu ứng viên **ngoài luồng Edge** — nhập hàng loạt từ
Excel/CSV và kéo‑thả nhiều CV — mà không phá các bảo đảm của People Core.

**Nguyên tắc chốt:** không có bảng phẳng mới. Mỗi dòng nhập vào trở thành một
`core.SourceRecord` đi qua **đúng** pipeline Edge (bàn nhận → `people.resolution`
→ `talent.derive`). Dữ liệu nhập tay vì thế thừa hưởng: raw bất biến (Master Plan
§2.2), gộp theo định danh mạnh + hàng chờ `IdentityConflict` không tự gộp (§2.4),
`curated` thắng suy diễn (§2.3), provenance qua `source_kind` (§5).

---

## 1. Kiến trúc

```text
File Excel/CSV  ─┐
Nhiều CV ────────┤→  intake.ImportBatch / ImportRow   (bàn dựng, có thể xoá)
                 │        │  validate: định dạng · dedupe Identity · trùng trong tệp
                 │        ▼
                 └──  commit  →  core.SourceRecord   (Edge "hub-manual")
                                     │  people.ingest.resolve_record
                                     ▼
                                 people.Person  →  talent.derive → TalentProfile
                                 (+ core.documents nếu dòng có CV)
```

- `intake/` là app Django mới. `ImportBatch`/`ImportRow` chỉ là **bản nháp**: sau
  commit chúng còn giá trị lịch sử, nguồn sự thật là `SourceRecord`.
- Một hàng `Edge` dành riêng `edge_id="hub-manual"` (tạo tự động ở lần commit đầu)
  để khoá duy nhất `(edge, entity_type, entity_key)` của bàn nhận vẫn áp dụng và
  để giao diện Vận hành Edge nhìn thấy nguồn này.
- Phần chèn/cập nhật/khử trùng dùng chung với Edge:
  `core.ingest.upsert_source_record()` (tách ra từ `core.views._ingest`).

## 2. entity_key và tính idempotent

```text
entity_key = "intake|" + slug(nguồn) + "|" + <định danh chính>
định danh chính = email chuẩn hoá → nếu trống thì phone → nếu trống thì linkedin
```

- Không có định danh nào ⇒ dòng `invalid`. Không tạo `Person` (khớp
  `resolution.SKIPPED`) — một dòng chỉ có tên sẽ đẻ Person rác trùng tên.
- Nạp lại đúng người từ cùng một nguồn ⇒ cùng `entity_key` ⇒
  `upsert_source_record` thấy bản ghi cũ:
  - `content_hash` không đổi → `duplicate`, chỉ đóng dấu `last_seen_at`, `revision`
    giữ nguyên;
  - có trường đổi → `updated`, `revision +1`, `status` về `pending`, `derive` chạy
    lại (curated vẫn được bảo vệ).
- `content_hash` **chỉ** tính trên trường nghiệp vụ + `source` + `source_kind`. Id
  lô và người nhập nằm ở `ImportRow`/`ImportBatch`, **không** vào payload — nếu vào
  thì cùng một người nhập ở lô khác sẽ trông như "đã đổi".

## 3. Từ vựng payload

`intake/fields.py::COLUMNS` ánh xạ tiêu đề cột (VN/EN/alias cũ) → khoá payload,
bám `edge/app/sync/payload.py::CANDIDATE_FIELDS`: `fullname, email, phone,
position, current_title, last_company, years_experience, job_level, education,
expected_salary, city, district, address, gender, birth_year, skills, linkedin,
labels, applied_at`(+`applied_ts`), `source`.

Trường Master Plan §4 chưa có ở Edge (`university, major, gpa, graduation_year,
certifications, achievements, language_proficiency, notice_period, career_goals,
industry, experience_summary, other_info`) vẫn được nhận và giữ nguyên trong
payload — `derive.py` chưa đọc, nhưng raw được bảo toàn cho Phase 2 / AI‑fill.

Provenance: `payload["source_kind"] = "import" | "bulk_cv"`;
`payload["source"]` = cột **Nguồn** của dòng, hoặc `source_label` của lô.

## 4. API (`/api/v1/intake/`, xác thực phiên, module `people_intake`)

Quyền theo **module `people_intake`** (label "Nhập liệu ứng viên"). Mặc định trong
code (`accounts.roles.ROLE_MODULES`) chỉ cấp cho **Admin** và **Vận hành Edge** —
giữ đúng hành vi trước khi có tính năng. Admin bật thêm cho vai trò khác
(Recruiter, Manager…) trong **Quản trị → Ma trận & Hoạt động → Ma trận Phân quyền
Vai trò theo Phân hệ** (`RoleModuleAccess` phủ lên ma trận mặc định; xem
`accounts.roles.modules_of`). Ô `Admin ↔ Quản trị hệ thống` bị khoá để không ai
tự khoá mình ra ngoài.


| Method & path | Việc |
|---|---|
| `GET  /template.xlsx` | File .xlsx mẫu: sheet dữ liệu + sheet hướng dẫn |
| `GET  /batches/` | 50 lô gần nhất |
| `POST /batches/` | multipart `file`+`kind=excel`+`source_label` → đọc, validate từng dòng, tạo `ImportBatch(draft)` + `ImportRow[]`. Hoặc JSON `kind=bulk_cv` → tạo lô rỗng |
| `GET  /batches/<id>/` | chi tiết lô kèm rows |
| `DELETE /batches/<id>/` | huỷ lô nháp + dọn CV tạm |
| `PATCH /batches/<id>/rows/<row_id>/` | `{fields:{key:val}}` sửa ô rồi validate lại; `{skip:true}` bỏ qua dòng |
| `POST /batches/<id>/cvs/` | multipart nhiều `files`. `excel`: ghép file ↔ dòng theo tên. `bulk_cv`: mỗi file → text (`talent.attachment_text.extract_file`) → AI bóc (`intake.extract`) → 1 dòng mới |
| `POST /batches/<id>/commit/` | `{dedup_strategy: skip|update}` → `intake.ingest.commit_batch` → tóm tắt |

`commit` gom lỗi theo **từng dòng** (`ImportRow.errors`), không bao giờ 500 cả lô.
`skip` = dòng `duplicate` bị bỏ qua; `update` = vẫn ghi, cập nhật bản ghi cũ.

## 5. Trích xuất CV bằng AI (luồng "nhiều CV")

`intake/extract.py`, task `candidate_intake_extraction` qua `ai.router.complete`
(GreenNode‑first, không dùng Vertex/Gemini). Bảo vệ theo Master Plan §21.4:

- văn bản CV bọc trong `<<<CV_TEXT_START>>> … <<<CV_TEXT_END>>>` và nêu rõ là DỮ
  LIỆU, không phải chỉ thị;
- không bật tool‑calling;
- chỉ nhận khoá thuộc allowlist `fields.PAYLOAD_KEYS`;
- lỗi AI ⇒ dòng vẫn được tạo (đánh dấu để người dùng sửa tay), lô chạy tiếp;
- kết quả là dữ liệu **đề xuất** — vẫn qua validate + dedupe + lưới xem trước.

Parsing/preview file CV do worker Hub sẵn có lo (`core.cv_parsing`,
`python manage.py parse_missing_cvs`) — không chạy trong request commit.

## 6. Giao diện

Tab **Nhập liệu** trong trang `/data` (`web/src/DataIntake.tsx`). Hai chế độ:

- **Từ Excel/CSV**: tải template → chọn nguồn → upload → lưới xem trước (chip
  valid/trùng/lỗi, ô sửa tại chỗ, nút bỏ qua từng dòng) → chọn cách xử lý dòng
  trùng → *Ghi vào hệ thống* → tóm tắt kèm link `/person/:id`.
- **Nhiều CV**: tạo lô → thả CV → mỗi CV thành một dòng do AI bóc → xem lại → ghi.

## 7. Giới hạn

- Excel/CSV: ≤ 10 MB, ≤ 5000 dòng/lần. CV: ≤ 200 file/lần, đuôi `.pdf/.doc/.docx/.txt`.
- Không tự gộp `Person`; xung đột định danh → `IdentityConflict` cho người xử lý.
- **CV tạm giữa `cvs/` và `commit/`** lưu ở `tempfile.gettempdir()/radar_intake`, xoá
  ngay khi commit/huỷ lô. Đúng cho Hub một container hiện tại. Khi Hub tách nhiều
  container/autoscale thì upload và commit có thể rơi vào container khác nhau —
  lúc đó chuyển staging sang object store (`core.storage.get_storage()`, prefix
  `intake-staging/`) kèm sweep file cũ > 24h.
- Chưa làm đợt này: form nhập 1 người + dán text; API/token đẩy từ hệ thống ngoài;
  `ExtractedFact`/Canonical Registry (Master Plan Phase 2).
