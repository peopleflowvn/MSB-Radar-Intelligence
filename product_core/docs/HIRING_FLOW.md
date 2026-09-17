# Hiring Manager & bàn giao Recruiter

**Phase:** 8 (Hiring Manager) — hoàn thành · 9 (Recruiter workflow) — hoàn thành
**Master Plan:** mục 20, 21
**Vị trí:** `server/hiring/`, `web/src/Hiring.tsx`, `web/src/Hunts.tsx`

---

## 0. Dựng lại dữ liệu demo

```bash
python manage.py seed_demo --reset
```

Tạo 6 tài khoản theo vai trò (mật khẩu `mat-khau-demo-1234`) và 10 lượt ứng
tuyển → 8 người, trong đó Nguyễn Văn An xuất hiện 3 lần qua 3 nguồn và 3 năm để
làm rõ phần phân giải định danh.

Dữ liệu đi qua **đúng đường thật**: `SourceRecord` → `people.ingest` → `Person` +
`TalentProfile`. Không tạo thẳng `Person`, vì như thế là bỏ qua chính phần phân
giải định danh mà dự án tồn tại để làm.

`--reset` xoá ứng viên demo (nhận diện qua `edge_id`) **và toàn bộ vị trí
tuyển**. Hai lý do phải dọn cả vị trí: xoá người xong thì `Candidacy` bị xoá
theo, để lại những vị trí rỗng không ứng viên; và đó chính là chỗ các vị trí
sinh ra lúc diễn tập nằm lại, rồi hiện lên màn hình ngày demo.

Không dùng `flush` — người chạy lệnh này gần như luôn có dữ liệu khác trong cùng
CSDL, và một lệnh seed xoá sạch CSDL là cái bẫy. Dữ liệu của Edge khác không bị
đụng tới.

Bài kiểm thử Hero Flow (`core/tests_hero_flow.py`) dùng **đúng lệnh này**, nên
không có hai bộ dữ liệu lệch nhau.

---

## 1. Vòng làm việc

```text
HM hỏi bằng lời (Talent Radar)
        ↓  "Tạo vị trí tuyển từ tiêu chí này"
HM tạo vị trí / dán JD
        ↓  jd.parse_jd()      — AI rút tiêu chí, hỏng thì dò từ khoá
   tiêu chí tìm kiếm
        ↓  views._recall()    — chọn người ĐƯA VÀO XÉT (nới dần)
        ↓  scoring            — chấm điểm, xếp hạng
   danh sách đề xuất
        ↓  HM bấm Phù hợp / Không phù hợp / Shortlist
   Candidacy (kèm ảnh chụp điểm)
        ↓  calibration.calibrate()
   trọng số đã học → xếp lại
        ↓  **Nhờ recruiter săn**
   HuntRequest → hộp thư Recruiter
```

`Nhờ recruiter săn` là CTA cốt lõi của sản phẩm và là điểm bàn giao giữa hai vai
trò — cũng chính là lý do phân quyền (Phase 5B) phải làm xong trước phase này.

---

## 2. Ba mô hình

| Mô hình | Là gì | Vì sao tách riêng |
|---|---|---|
| `HiringNeed` | một vị trí đang tuyển | mang JD + tiêu chí + trọng số đã học |
| `Candidacy` | một Person được xét cho một vị trí | mang **đánh giá** của HM, khác `Pool` của Talent Radar |
| `HuntRequest` | một lần HM nhờ Recruiter | một vị trí nhờ săn nhiều lần, mỗi lần một nhóm, có thể giao người khác |

`Candidacy` cố ý **không** gộp vào `Pool`: Pool là nhóm recruiter tự gom để làm
việc; Candidacy gắn với một vị trí cụ thể và mang tín hiệu phù hợp/không phù hợp.
Gộp lại thì "đã xem người này cho vị trí A" lẫn với "đã bỏ vào nhóm B".

---

## 3. Hiệu chỉnh — học mà không fine-tuning

Master Plan mục 21 nói rõ: *"Không cần fine-tuning model."* Và thật sự không cần.
Điểm số vốn đã là tổ hợp có trọng số của các chiều tất định (`talent/scoring.py`),
nên "học từ phản hồi" rút gọn thành **chỉnh trọng số**:

```text
gap    = trung bình chiều X ở nhóm phù hợp − ở nhóm không phù hợp
factor = clamp(1 + gap, 0.4, 2.0)
w[X]   = w[X] × factor          rồi chuẩn hoá về tổng cũ
```

Ba tính chất khiến cách này hợp bài toán:

* **Giải thích được** — nói thành lời: *"bạn thiên về người khớp kỹ năng và ít
  quan tâm nơi ở."* Fine-tuning không nói được câu đó.
* **Tất định** — cùng phản hồi cho cùng trọng số.
* **Rẻ** — vài phép trung bình, không gọi LLM.

**Giới hạn phải biết:** chỉ chỉnh được mức quan trọng của **các chiều đã có**. HM
loại người vì lý do chưa chiều nào đo được ("công ty này quá nhỏ") thì không học
được — và không được giả vờ là học được.

### Vì sao Shortlist tính là tín hiệu dương

Thao tác tự nhiên nhất của HM là chấm *phù hợp* rồi đưa vào *shortlist*. Nếu chỉ
`good_fit` mới tính, thao tác đó **xoá** mất chính tín hiệu dương mà hiệu chỉnh
cần — HM càng dùng đúng thì hệ thống càng học được ít. Nên `shortlisted` được xếp
cùng nhóm dương (và là lời khen mạnh hơn).

### Ngưỡng tối thiểu

`MIN_PER_GROUP = 2` mỗi nhóm. Dưới mức đó, trung bình chỉ là nhiễu, mà chỉnh
trọng số theo nhiễu còn tệ hơn không chỉnh — nên API trả 400 kèm lời giải thích
thay vì im lặng chỉnh bừa.

---

## 4. `_recall()` — vì sao không dùng thẳng `talent.search()`

`search()` lọc **AND cứng**: đúng cho ô tìm kiếm, sai cho màn hình này.

Một JD đủ chi tiết (chức danh + 2 kỹ năng + nơi ở + số năm) lọc AND xong thường
còn 0–2 người. Khi ấy:

* HM **không có ai để đánh dấu "không phù hợp"** → hiệu chỉnh không có gì để học;
* người lệch một tiêu chí phụ (ở Đà Nẵng, thiếu 1 năm) biến mất hoàn toàn, dù
  chính họ mới là ứng viên đáng gọi.

Nên `_recall()` nới dần cho tới khi đủ `MIN_POOL = 40` người:

| Vòng | Bỏ bớt |
|---|---|
| 1 | (nguyên tiêu chí) |
| 2 | số năm kinh nghiệm |
| 3 | nơi ở |
| 4 | công ty/ngành, chỉ giữ 1 kỹ năng |
| 5 | mọi kỹ năng |
| 6 | chức danh và từ khoá |

Thứ tự cuối cùng do **điểm** quyết định, và điểm đã trừ sẵn những chiều mà họ
lệch. Tuyển chọn lo *ai được xét*; chấm điểm lo *ai đứng trước*.

### Vì sao con số ở đây khác ô tìm kiếm

AI Search báo 1 người, vị trí tuyển báo 8 — đúng ý đồ, nhưng nhìn qua thì giống
hệ thống đếm sai. Nên phản hồi trả kèm `strict_count`, và giao diện nói rõ:

> *8 ứng viên đề xuất — 1 người khớp đủ tiêu chí; 7 người lệch một vài tiêu chí
> nhưng vẫn đáng xem.*

---

## 5. Đường lui khi LLM bận

Khoá Gemini miễn phí giới hạn ~15 lượt/phút. Ngày demo mà dính giới hạn thì màn
hình trắng trơn là kịch bản tệ nhất. Nên `parse_jd()` có đường lui **dò từ khoá**:

* từ vựng kỹ năng và nơi ở lấy **từ chính CSDL** (`TalentProfile`), không viết
  cứng — nhờ vậy tiêu chí rút ra luôn là thứ tìm được người;
* số năm lấy **mốc nhỏ nhất** trong JD (JD hay nhắc nhiều mốc; đòi mốc cao nhất
  là loại oan);
* tên vị trí lấy dòng đầu JD.

Kết quả được đánh dấu `criteria_fallback=True` và **lưu vào CSDL**, không chỉ trả
một lần: HM mở lại vị trí ngày mai vẫn phải thấy cảnh báo, nếu không họ sẽ tin
nhầm vào bộ tiêu chí thô.

---

## 6. Dấu vết để lại

Mỗi đánh giá và mỗi lần nhờ săn đều ghi một `Interaction` lên timeline của
`Person` (`hm_good_fit`, `hm_not_fit`, `hm_shortlisted`, `hunt_requested`).

Đánh giá của HM là **dữ kiện nghiệp vụ về con người đó**, không chỉ về vị trí
này: lần sau ai mở hồ sơ ấy cũng thấy "từng được xét cho vị trí X".

---

## 7. Phía Recruiter (Phase 9)

### Hai tầng trạng thái

`HuntRequest.status` nói **recruiter đã nhận việc chưa**; `HuntCandidate.state`
nói **từng người đã liên hệ tới đâu**. Gộp làm một là mất thông tin: một yêu cầu
5 người luôn có người đã nhận lời, người chưa bắt máy, người từ chối.

```text
HuntRequest:    mới → nhận → đang làm → xong │ từ chối (kèm lý do)
HuntCandidate:  chưa liên hệ → đang liên hệ → đã phản hồi → quan tâm
                                            ↘ không quan tâm / không gọi được
                → chuyển cho HM  │  trả về kho (kèm lý do)
```

Xong hết người thì yêu cầu **tự đóng**. Chỉ tự đóng, không tự mở lại — mở lại là
quyết định có chủ ý của recruiter.

### Đồng bộ sang `Relationship`

Mỗi lần đổi trạng thái liên hệ, `people.Relationship` (domain `talent`) được cập
nhật theo `HuntCandidate.RELATIONSHIP_MAP`. Đó là thứ **người khác** nhìn thấy
khi mở hồ sơ ngoài luồng săn này; không đồng bộ thì hồ sơ vẫn hiện "chưa liên
hệ" trong khi thực tế đã bị gọi ba lần.

### Trả về kho bắt buộc có lý do

API trả 400 nếu thiếu. Một hồ sơ quay lại kho mà không ai biết vì sao thì lần
sau lại có người gọi lại từ đầu — và ứng viên nhận cuộc gọi thứ hai hỏi đúng câu
đã trả lời tháng trước.

### Thư tiếp cận

`hiring/outreach.py`. Nguyên tắc chi phối cả file: **AI chỉ được nhắc lại thứ đã
có trong hồ sơ.** Prompt dựng từ một danh sách dữ kiện đã kiểm chứng, và nói
thẳng với mô hình rằng ngoài danh sách đó thì không được thêm gì.

Thư đi ra ngoài, tới một người thật, mang tên MSB. Một câu bịa ("thấy anh vừa
hoàn thành dự án migration ở ngân hàng X") không chỉ sai — nó làm người nhận
biết ngay là thư máy, và hỏng luôn thiện cảm cho những lần sau.

Chỉ nêu **kỹ năng trùng với yêu cầu vị trí**: đó là lý do ta gọi họ, và cũng là
thứ khiến thư đọc như viết riêng chứ không phải gửi hàng loạt.

**Hệ thống không tự gửi.** `POST .../sent/` chỉ *ghi nhận* recruiter đã gửi.
Nhắn tin nhân danh MSB tới người thật cần quyết định của con người, và cần một
cuộc bàn về tuân thủ mà ta chưa có.

LLM bận thì trả **khung thư** điền sẵn dữ kiện, cố ý để ngỏ chỗ cần người viết
(`[Viết thêm: ...]`). Chặn recruiter giữa lúc đang làm việc là cái giá quá đắt
cho một lỗi tạm thời.

---

## 8. API

| Đường dẫn | Việc |
|---|---|
| `GET/POST /api/v1/hiring/needs/` | liệt kê / tạo vị trí (POST kèm `jd_text` thì rút tiêu chí luôn) |
| `GET/PATCH/DELETE /api/v1/hiring/needs/{id}/` | chi tiết |
| `POST …/{id}/parse-jd/` | đọc lại JD |
| `GET …/{id}/suggestions/` | ứng viên đề xuất, tạo `Candidacy` kèm ảnh chụp điểm |
| `POST …/{id}/mark/` | đánh dấu phù hợp / không phù hợp / shortlist |
| `POST …/{id}/calibrate/` | học trọng số (400 nếu chưa đủ phản hồi) |
| `POST …/{id}/calibrate/reset/` | bỏ hiệu chỉnh |
| `POST …/{id}/hunt/` | **nhờ recruiter săn** |
| `GET /api/v1/hiring/metrics/` | chỉ số hiệu quả (mục 50) |
| `GET /api/v1/hiring/hunts/` | hộp thư (`?open=1`, `?mine=1`) |
| `GET/PATCH /api/v1/hiring/hunts/{id}/` | nhận việc, đổi trạng thái, từ chối kèm lý do |
| `PATCH …/hunts/{id}/people/{person_id}/` | trạng thái liên hệ, ghi chú, trả về kho |
| `POST …/hunts/{id}/people/{person_id}/draft/` | AI soạn thư (`channel`: `message` \| `email`) |
| `POST …/hunts/{id}/people/{person_id}/sent/` | recruiter xác nhận đã gửi |

Toàn bộ yêu cầu quyền module `talent` (`RequiresTalent`).

---

## 9. Chỉ số hiệu quả (Master Plan mục 50)

`GET /api/v1/hiring/metrics/` — hiện ở đầu màn hình “Vị trí tuyển”.

| Chỉ số | Trả lời câu hỏi |
|---|---|
| Tái sử dụng hồ sơ cũ | Có thật là moi được người từ kho, hay chỉ lọc lại người vừa nộp tuần này? |
| Lượt ứng tuyển trên mỗi người | Một người nộp nhiều nơi có ra một hồ sơ không? |
| Trưởng bộ phận chấp nhận (top 10) | Đề xuất có đúng gu người tuyển không? |
| Thời gian tới shortlist đầu tiên | Nhanh hơn cách cũ bao nhiêu? |
| Yêu cầu săn có kết quả | Vòng lặp có khép được không, hay dừng ở giữa? |

Hai điều dễ làm sai và đã cố ý làm khác:

* **Chưa có dữ liệu thì trả `None`, không trả `0`.** Số 0 đọc như *“làm rồi mà
  kém”*; dấu `—` đọc đúng như nó là — *“chưa đủ dữ liệu để nói”*. Nhầm hai thứ
  này trong một buổi bảo vệ là tự bắn vào chân.
* **“Tái sử dụng hồ sơ cũ” tính theo `applied_ts`, không theo `first_seen_at`.**
  Cái sau là lúc Hub *nhận* bản ghi; đồng bộ cả kho lịch sử về trong một buổi sẽ
  khiến mọi hồ sơ trông như vừa nộp hôm nay và chỉ số cốt lõi luôn bằng 0.

Thời gian dùng **trung vị**, không trung bình: một vị trí bị bỏ quên nửa tháng
đủ kéo lệch trung bình tới mức vô nghĩa.

---

## 10. Còn thiếu

* Thông báo cho HM khi recruiter nhận / từ chối (hiện HM phải tự mở xem).
* HM chưa có màn hình xem ứng viên recruiter đã chuyển lại.
* Phân quyền tầng bản ghi: HM hiện thấy được mọi vị trí, không chỉ của mình
  (xem `docs/ACCESS_CONTROL.md` mục 5 — hoãn sau hackathon).
