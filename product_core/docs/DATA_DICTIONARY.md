# Data Dictionary — People Intelligence

**Trạng thái:** bản nháp Giai đoạn 0 (Master Plan §15). Cột *entity sở hữu* và
*nguồn ưu tiên* đã chốt theo model hiện có; cột *alias key Edge* dựng từ code
(`people/resolution.py`, `talent/derive.py`) và **phải đối chiếu lại với payload
Edge thật của từng provider trước khi coi là hợp đồng**.

**Điều kiện hoàn thành Giai đoạn 0:** bảng này được duyệt bằng mẫu payload thật.

---

## 1. Cách dùng

- Mỗi field nghiệp vụ có đúng **một entity sở hữu**. AI ghi `ExtractedFact` (Giai
  đoạn 2), không ghi thẳng vào các bảng dưới đây.
- *Nguồn ưu tiên* theo Master Plan §2.3: `curated` > `edge` (payload có cấu trúc)
  > `cv_text` (evidence trong CV đã parsing) > `ai` (suy luận đạt ngưỡng) >
  để trống / review.
- *Auto-accept*: field an toàn, độ tin cậy cao, không thuộc `curated_fields` thì
  được nhận tự động; còn lại vào review queue.
- *Mức nhạy cảm*: `S0` công khai nghiệp vụ · `S1` PII thường · `S2` PII định danh
  mạnh (email/phone/DOB) · `S3` nhạy cảm, được dùng khi có quyền và có nguồn (giới tính).

---

## 2. Bản đồ entity sở hữu

| Entity | Model | Vai trò |
|---|---|---|
| Person | `people.Person` | Một con người. Ảnh nhanh các trường hay dùng. |
| Identity | `people.Identity` | Định danh mạnh (email/phone/URL/mã ứng viên). |
| Document | `people.Document` | Từng CV; nhiều bản theo thời gian. |
| ParsedTextVersion | `people.ParsedTextVersion` | Text CV đã parsing, dedupe theo hash. |
| TalentProfile | `talent.TalentProfile` | Góc nhìn tuyển dụng của Person. |
| RBProfile | `rb.RBProfile` | Góc nhìn bán lẻ của Person. |
| ProductInterest | `rb.ProductInterest` | Quan tâm sản phẩm, có evidence + confidence. |
| Relationship | `people.Relationship` | Trạng thái quan hệ theo domain. |
| SourceRecord | `core.SourceRecord` | Bàn nhận payload Edge, bất biến. |
| *ExtractedFact* | *chưa có — Giai đoạn 2* | Mọi giá trị AI/edge suy ra + provenance. |
| *EducationRecord / WorkExperience* | *chưa có — Giai đoạn 2+* | Nhiều dòng học vấn / kinh nghiệm. |
| *TalentPreference* | *chưa có — Giai đoạn 2+* | Nhu cầu nghề nghiệp (tách khỏi profile). |
| *PersonAddress* | *chưa có — Giai đoạn 2+* | Địa chỉ có cấu trúc (country/province/city/district). |

> Hôm nay `TalentProfile` giữ phẳng `location`, `education`, `expected_salary`,
> `skills`, `industries`. Master Plan §4 yêu cầu tách sang bảng nhiều dòng; cột
> "entity sở hữu (đích)" dưới đây ghi nơi field sẽ về sau Giai đoạn 2.

---

## 3. Từ điển field

### 3.1. Định danh con người

| Field | Kiểu | Enum / khoảng | Nhạy cảm | Entity sở hữu (hiện tại → đích) | Nguồn ưu tiên | Auto-accept | Ghi chú |
|---|---|---|---|---|---|---|---|
| full_name | text | — | S1 | `Person.display_name` | edge > cv_text > curated | có | `normalized_name` = bỏ dấu, chỉ gợi ý trùng. Tên **không** phải định danh mạnh. |
| email | text | RFC-ish | S2 | `Identity(kind=email)` + ảnh `Person.primary_email` | edge > cv_text | có | Unique `(kind,value)`. Xung đột định danh → `IdentityConflict`, không tự gộp. |
| phone | text | E.164 sau chuẩn hoá | S2 | `Identity(kind=phone)` + `Person.primary_phone` | edge > cv_text | có | Hai người có thể chung số → conflict queue. |
| gender | enum | `nam` / `nữ` / `""` | **S3** | *hồ sơ nhân khẩu học — chưa có* | curated > edge > cv_text | theo RBAC | Không suy từ tên; được dùng làm bối cảnh/tiêu chí khi có nguồn và người dùng quyết định cuối cùng. |
| date_of_birth | date | `YYYY-MM-DD` / `YYYY` | S2 | *hồ sơ nhân khẩu học — chưa có* | edge > cv_text | không | Review vì nhạy cảm. |
| linkedin / facebook | url | — | S1 | `Identity(kind=linkedin/facebook)` | edge > cv_text | có | Chuẩn hoá URL trước khi so khớp. |
| provider_person_id | text | — | S1 | `Identity(kind=provider_person_id)` | edge | có | Khoá `source:candidate_id`. |

### 3.2. Địa chỉ & địa lý

| Field | Kiểu | Enum / khoảng | Nhạy cảm | Entity sở hữu (hiện tại → đích) | Nguồn ưu tiên | Auto-accept | Ghi chú |
|---|---|---|---|---|---|---|---|
| current_address | text | — | S1 | `TalentProfile.location` → `PersonAddress` | curated > edge > cv_text | không | Địa chỉ hiện tại ≠ location interest. |
| city / province / district / country | code + raw | Canonical Registry §6.1 | S0 | → `PersonAddress` (4 cấp + raw) | edge > cv_text > ai | có (code khớp registry) | Tìm kiếm dùng **code**, không dùng label. Alias `HCM/TP.HCM/Sài Gòn` → `VN-SG`. |

### 3.3. Nhu cầu nghề nghiệp

| Field | Kiểu | Enum / khoảng | Nhạy cảm | Entity sở hữu (hiện tại → đích) | Nguồn ưu tiên | Auto-accept | Ghi chú |
|---|---|---|---|---|---|---|---|
| expected_salary | text → {amount, currency, period} | ≥ 0 | S1 | `TalentProfile.expected_salary` → `TalentPreference` | curated > edge > cv_text | không | Lương trong một lần ứng tuyển ≠ preference hiện tại — giữ theo ngữ cảnh (§7.3). |
| notice_period | text → ngày | ≥ 0 | S0 | → `TalentPreference` | edge > cv_text | có | |
| location_interest | code[] | Canonical §6.1 | S0 | → `TalentPreference` | curated > cv_text > edge | có | Khác `current_address`. |
| job_title_interest | text → title code | Canonical §6.2 | S0 | → `TalentPreference` | curated > cv_text | có | |
| career_goals / work_environment | text | — | S0 | → `TalentPreference` | cv_text > ai | không | Tóm tắt AI cần review. |

### 3.4. Học vấn

| Field | Kiểu | Enum / khoảng | Nhạy cảm | Entity sở hữu (hiện tại → đích) | Nguồn ưu tiên | Auto-accept | Ghi chú |
|---|---|---|---|---|---|---|---|
| education_level | code | `Cử nhân`/`Thạc sĩ`/`Tiến sĩ`/`Cao đẳng`/`Trung cấp`/`THPT` | S0 | `TalentProfile.education` (phẳng) → `EducationRecord` | edge > cv_text > ai | có (code) | `Bachelor`/`Cử nhân`/`Đại học` → cùng code, giữ raw. |
| university | code | Canonical §6.2 | S0 | → `EducationRecord` (nhiều dòng) | cv_text > edge | có | |
| major | text → code | Canonical §6.2 | S0 | → `EducationRecord` | cv_text > edge | có | |
| graduation_year | int | 1950..năm hiện tại + 1 | S0 | → `EducationRecord` | cv_text > edge | có | |
| gpa | number/text | 0..4 hoặc 0..10 | S0 | → `EducationRecord` | cv_text | không | Nhiều thang điểm — review. |

### 3.5. Kinh nghiệm

| Field | Kiểu | Enum / khoảng | Nhạy cảm | Entity sở hữu (hiện tại → đích) | Nguồn ưu tiên | Auto-accept | Ghi chú |
|---|---|---|---|---|---|---|---|
| current_title | text → title code | Canonical §6.2 | S0 | `TalentProfile.current_title` | curated > edge > cv_text | có | "job applied" ≠ "current job" (§7.3). |
| current_company | text → company code | Canonical §6.2 | S0 | `TalentProfile.current_company` | curated > cv_text > edge | có | Ưu tiên evidence mới nhất còn hợp lệ. |
| seniority | code | `intern`/`junior`/`mid`/`senior`/`lead`/`manager`/`director`/`exec` | S0 | `TalentProfile.seniority` | edge(`job_level`) > cv_text > ai | có | |
| years_experience | float | 0..60 | S0 | `TalentProfile.years_experience` | edge > cv_text > ai | có | Regex `"3 năm"/"5 years"`. |
| experience_summary | text | — | S0 | `TalentProfile.summary` | ai (từ cv_text) | không | Tóm tắt AI → review. |
| work_experience[] | rows | — | S0 | → `WorkExperience` (company, title, from, to, is_current) | cv_text > edge | không | Bitemporal (§21.1). |

### 3.6. Năng lực

| Field | Kiểu | Enum / khoảng | Nhạy cảm | Entity sở hữu (hiện tại → đích) | Nguồn ưu tiên | Auto-accept | Ghi chú |
|---|---|---|---|---|---|---|---|
| skills | code[] | Canonical §6.2 | S0 | `TalentProfile.skills` (JSON) → bảng nhiều dòng | edge ∪ cv_text (hợp nhất) | có (code) | Kỹ năng cũ không tự mất — hợp nhất qua nhiều CV (§7.3). `PowerBI/Power BI` → cùng code. |
| industries | code[] | Canonical §6.2 | S0 | `TalentProfile.industries` (JSON) | edge ∪ cv_text | có | |
| achievements | text[] | — | S0 | → bảng nhiều dòng | cv_text | không | |
| certifications | code[] | Canonical §6.2 | S0 | → bảng nhiều dòng | cv_text > edge | có (code) | |
| language_proficiency | rows {lang code, level CEFR-ish} | Canonical §6.2 | S0 | → bảng nhiều dòng | cv_text | không | |

### 3.7. Liên kết & CV

| Field | Kiểu | Nhạy cảm | Entity sở hữu | Nguồn ưu tiên | Ghi chú |
|---|---|---|---|---|---|
| portfolio / website | url | S1 | `Identity` / `PersonLink` (chưa có) | edge > cv_text | |
| cv_url / cv_file_name | text | S1 | `Document.storage_key` / `Document.filename` | edge | `storage_key` trống = Edge chưa tải file lên. |
| cv_parsed_text | text | S1 | `Document.best_text` (`primary_text_version` hoặc `parsed_text`) | edge (parser) | **Không parsing lại nếu đã có** (§2.1). |

### 3.8. Tuyển dụng (thuộc lần ứng tuyển, KHÔNG thuộc Person)

| Field | Kiểu | Nhạy cảm | Entity sở hữu (đích) | Nguồn ưu tiên | Ghi chú |
|---|---|---|---|---|---|
| applied_position | text | S0 | `Application`/`Candidacy` (chưa có) — nay đọc từ `SourceRecord.position` | edge | Thường **không** có trong CV. |
| applied_date | datetime | S0 | → `Application` — nay `SourceRecord` payload `applied_ts` | edge | Dùng timestamp nguồn, **không** dùng ngày Hub nhận (§7.3). |
| requisition_id | text | S0 | → `Application` | edge | |
| stage | code | danh mục nghiệp vụ | S0 | → `Application` | edge | AI không tự đổi stage (§2.4). |
| source / source_detail | code | Canonical §6.2 (#9) | S0 | `SourceRecord.source` / `Document.source` | edge | |

### 3.9. Quản lý tuyển dụng & bán hàng

| Field | Kiểu | Nhạy cảm | Entity sở hữu | Nguồn ưu tiên | Ghi chú |
|---|---|---|---|---|---|
| assigned_owner | FK user | S0 | `TalentProfile.owner` / `Relationship.owner_user` | curated | AI không gán. |
| recruiter_assessment | text | S1 | `Relationship.notes` / assessment (chưa tách) | **curated only** | AI **không** ghi đè (§2.4). |
| tags | m2m | S0 | `TalentProfile.tags` (`talent.Tag`) | curated | |
| relationship_state | enum | `people.Relationship.TALENT_STATES` / `RB_STATES` | S0 | `Relationship.state` | curated | Không dùng chung enum giữa hai domain. |
| lead_status | enum | `cold/warm/interested/qualified/converted/dormant` | S0 | `RBProfile.lead_status` | curated | |
| segment | enum | `mass/affluent/priority` | S1 | `RBProfile.segment` | curated > ai | Review. |
| product_interest | enum + confidence + evidence | `rb.PRODUCT_CHOICES` (9 giá trị) | S1 | `rb.ProductInterest` | cv_text/signal > ai | Luôn kèm evidence. AI không tạo `RBOpportunity` thật từ suy đoán (§2.4). |
| opportunity_amount / win_probability / close_date | number / % / date | S1 | `rb.RBOpportunity` | curated | Không thuộc ứng viên. |
| other_information | text | S1 | `ExtractedFact` có nguồn hoặc note có chủ sở hữu | cv_text | **Không** phải ô chứa mọi thứ. |

---

## 4. Alias key trong payload Edge

`intel/edge_mapper.py:PAYLOAD_KEYS` là hợp đồng thật. Cột "Ghi chú" bên dưới ghi
theo payload **thật** đã lấy.

### 4.1. TopCV (Edge `topcv`) — đã đối chiếu 01/09/2026

Toàn bộ payload key TopCV gửi (từ `SourceRecord.payload` production):

```
city district address gender birth_year          -> hầu hết RỖNG ở lô đầu (14 hồ sơ)
education job_level last_company current_title    -> RỖNG
expected_salary years_experience experience skills -> RỖNG
labels resume_id profile_type candidate_id        -> RỖNG
fullname email phone                              -> có
position                                          -> VỊ TRÍ ỨNG TUYỂN (kèm mã req, vd "… - MSB - 3K061")
applied_ts (ISO)  applied_at (dd/mm/yyyy HH:MM)   -> có
cv_url cv_id status account campaign_id apply_source first_seen entity_key -> metadata
```

**Kết luận quan trọng:** với TopCV, `position` = **vị trí ứng tuyển**, không phải
chức danh hiện tại (`current_title` là khoá riêng, đang rỗng). `edge_mapper` đã
map `position` → `applied_position` **only**. Chức danh/kỹ năng/học vấn/kinh
nghiệm hiện đều chỉ lấy được từ **text CV** (chưa parse) — AI-fill-gaps sẽ phụ
trách khi có `Document.best_text`.

| Field nghiệp vụ | Khoá payload (edge_mapper) | Ghi chú |
|---|---|---|
| full_name | `fullname`, `full_name`, `name` | TopCV: `fullname`; hoa/thường lộn xộn → `resolution` chuẩn hoá display_name |
| email | `email` | TopCV đôi khi 2 email phân tách phẩy → `resolution.normalize_email` xử lý |
| phone | `phone`, `mobile` | |
| gender | `gender` | TopCV có khoá, đang rỗng |
| date_of_birth | `date_of_birth`, `birth_year`, `dob` | `birth_year` (4 chữ số) → `YYYY-01-01` |
| current_title | `current_title` | **KHÔNG** lấy `position` |
| current_company | `last_company`, `current_company`, `company` | |
| seniority | `job_level`, `seniority` | |
| education_level | `education`, `education_level` | |
| expected_salary | `expected_salary`, `salary_expectation` | |
| city | `city`, `address`, `district`, `location` | TopCV thêm `district` |
| years_experience | `years_experience`, `experience` | chuỗi tự do, regex năm |
| skills | `skills` | tách theo `, ; \| / \n` |
| applied_position | `position`, `applied_position` | TopCV: `position` |
| applied_date | `applied_ts`, `applied_date`, `applied_at` | `applied_at` = `dd/mm/yyyy HH:MM` |
| source | `source` | |

### 4.2. Chưa đối chiếu

- [ ] VietnamWorks, ITviec, LinkedIn, `hub-manual` — lấy payload mẫu khi có nguồn thật.
- [ ] Khi lô TopCV có CV parse xong: kiểm chứng AI-fill từ `best_text`.
- [ ] Chốt đơn vị lương + cách viết địa danh của từng provider.

---

## 5. Quy tắc nguồn, độ mới và xung đột (Master Plan §2.3, §7.3, §21.1)

- **Con người thắng máy:** field trong `TalentProfile.curated_fields` miễn nhiễm
  mọi cập nhật tự động (edge lẫn AI).
- **Thời gian hiệu lực:** fact mang `valid_from` / `valid_to` / `is_current`.
  "Ứng tuyển 01/08/2026", "làm ở A 2022–2024", "đang làm ở B" là ba fact khác
  nhau, không hợp nhất thành một giá trị không thời gian.
- **Quy tắc "hiện hành" theo field:**
  - `current_company` / `current_title`: evidence mới nhất còn hợp lệ.
  - `skills` / `industries` / `certifications`: hợp nhất (không xoá cái cũ).
  - `current_address` vs `location_interest`: hai field riêng.
  - `expected_salary` (application) vs `TalentPreference`: giữ cả hai theo ngữ cảnh.
- **Xung đột định danh:** email→A, phone→B ⇒ `IdentityConflict` status `open`,
  **không tự gộp**.
- **Xung đột giá trị:** hai CV lệch địa chỉ ⇒ giữ cả hai fact, `status=conflict`,
  đẩy review; câu trả lời AI phải nêu rõ mâu thuẫn (Master Plan §21.8).
