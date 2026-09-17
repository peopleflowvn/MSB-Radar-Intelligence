# RB Radar

**Phase:** 12 (nền tảng) · 13 (Social Radar cho RB) · 14 (Growth Engine) — hoàn thành
**Master Plan:** mục 25, 32, 33, 34, 35
**Vị trí:** `server/rb/`, `web/src/RB.tsx`

---

## 1. Đây là chỗ Nguyên tắc 2 thành code

```text
Person                     con người — dùng chung, KHÔNG sao chép
├── TalentProfile          góc nhìn tuyển dụng      (Phase 6)
└── RBProfile              góc nhìn bán lẻ          (Phase 12)
```

`RBProfile` **không có** trường tên, email hay số điện thoại. Chép sang đây là
tự tay tạo ra bài toán *"hai bản ghi cùng một người lệch nhau"* mà cả dự án này
sinh ra để giải. Liên hệ luôn đọc từ `Person`, và có một bài kiểm thử canh đúng
điều đó:

```python
def test_KHONG_chep_du_lieu_nguoi_sang_ho_so_ban_le(self):
    truong = {f.name for f in RBProfile._meta.get_fields()}
    for cam in ("display_name", "email", "phone", ...):
        self.assertNotIn(cam, truong)
```

**Vì sao tách khỏi `TalentProfile` thay vì thêm cột:** hai nghiệp vụ có vòng đời
khác hẳn. `lead_status` của bán lẻ và trạng thái quan hệ tuyển dụng không cùng
một trục — Master Plan mục 16 nói rõ không ép hai nghiệp vụ dùng chung một
pipeline.

---

## 2. Quan tâm ≠ Cơ hội

| | Là gì | Sinh ra từ |
|---|---|---|
| `ProductInterest` | thứ ta **quan sát được** | tín hiệu, CV, RM ghi tay |
| `OpportunitySuggestion` | thứ Radar **đề xuất RM xem xét** | quan tâm + đủ điểm ưu tiên |
| `RBOpportunity` | việc RM **quyết định theo đuổi** | RM bấm nhận đề xuất |

Trộn ba thứ này thì danh sách việc cần làm của RM đầy những thứ chưa ai định
làm. Một người có thể quan tâm ba nhóm sản phẩm mà không sinh cơ hội nào.

`ProductInterest` **chỉ nâng mức tin cậy, không hạ**: một bài mới nhắc thoáng
qua không được xoá đi bằng chứng mạnh hơn từ lần trước.

---

## 3. Gợi ý sản phẩm KHÔNG gọi LLM

```python
routing.suggest_products("Sắp đi Nhật, nên đổi tiền hay dùng thẻ?")
# → Ngoại tệ (0.70) · Thẻ tín dụng (0.36) · Bảo hiểm (0.36)
```

Danh mục sản phẩm ngân hàng là **hữu hạn và có tên gọi cố định**, còn từ vựng
khách dùng để nói về chúng cũng hữu hạn. Một bảng từ khoá đọc được, sửa được và
giải thích được ăn đứt một lượt gọi mô hình ở đây — và quan trọng hơn, nó
**không bao giờ gợi ý một sản phẩm MSB không bán**.

Ba ràng buộc trong bảng đó:

* **Sản phẩm đi kèm có tin cậy thấp hơn hẳn** và ghi rõ `"suy ra từ nhu cầu
  chính"`. Đi nước ngoài kéo theo thẻ và bảo hiểm — nhưng đó là suy luận của hệ
  thống, không phải điều khách viết ra.
* **Tối đa 3 nhóm.** Gợi ý sáu thứ cùng lúc thì RM không biết bắt đầu từ đâu, và
  lời chào sẽ nghe như rao hàng.
* **Không chắc hơn tín hiệu gốc.** Gợi ý sản phẩm không thể tự tin hơn chính
  tín hiệu đã sinh ra nó.

Nhu cầu được nói **bằng lời của khách**, không phải tên sản phẩm: *"Đang tính
mua hoặc sửa nhà"*, không phải *"Vay mua nhà"*.

---

## 4. Ngưỡng của bán lẻ cao hơn tuyển dụng

```python
THRESHOLDS = {"talent": 0.5, "rb": 0.7}      # social/pipeline.py
MIN_CONFIDENCE = 0.5                          # rb/routing.py
```

Gọi nhầm một người không tìm việc chỉ tốn 2 phút. Nhắn tin mời vay tiền cho
người không hỏi là chuyện khác hẳn — về mặt cảm nhận và về mặt tuân thủ.

---

## 5. Đóng cơ hội phải ghi lý do

API trả 400 nếu thiếu. Một cơ hội bị đóng im lặng sẽ được hệ thống đề xuất lại
vào tháng sau, và khách hàng nhận **đúng lời chào đã từ chối**.

Cùng khuôn với "trả ứng viên về kho" bên tuyển dụng, và cố ý giống nhau: hai vai
trò khác nhau nhưng cùng một nhịp làm việc, nên không bắt ai học hai giao diện.

Đổi trạng thái cơ hội cũng cập nhật `RBProfile.lead_status`, nhưng trạng thái hồ
sơ được **tổng hợp từ toàn bộ cơ hội**. Một sản phẩm không thành không được hạ
khách đã chuyển đổi ở sản phẩm khác.

Workspace `/rb` không trình bày mỗi cơ hội như một biểu mẫu CRM. Nó gom cơ hội
và lịch quan hệ thành một inbox theo người: một khách chỉ có một thẻ, các sản
phẩm còn lại nằm trong chi tiết. Ba khu vực duy nhất là **Việc cần xử lý**,
**Pipeline khách hàng** và **Danh sách khách hàng**.

---

## 6. Social Radar nối vào đây

```text
Bài "cần vay 500 triệu mua nhà"
   ↓  social/intent.py       rb: 0.85
   ↓  social/pipeline.py     people.Signal(domain=rb)
   ↓  rb/routing.route_signal()
ProductInterest + RBOpportunity → hộp thư RM
```

Trước Phase 12, tín hiệu `rb` sinh ra rồi **nằm im** vì không nghiệp vụ nào
nhận. Đó là kiểu "đã làm xong" mà thực ra chưa dùng được.

`social/pipeline.py` import `rb.routing` **bên trong hàm**, không ở đầu file:
Social Radar là năng lực dùng chung (mục 26), nó không được phụ thuộc cứng vào
một nghiệp vụ tiêu thụ cụ thể.

---

## 7. Quyền

| Vai trò | RB Radar |
|---|---|
| RB Sales | ✅ nghiệp vụ gốc |
| Manager, Admin | ✅ |
| Recruiter, Hiring Manager | ❌ |

RB Sales **đọc được** dữ liệu tuyển dụng theo quyết định 19/08/2026, nhưng đó là
truy cập **liên nghiệp vụ** và bị `AccessLog` đánh dấu riêng. Chiều ngược lại —
recruiter đọc hồ sơ bán lẻ — chưa được mở, và mở nó là một quyết định chính sách
chứ không phải một dòng code.

---

## 8. API

| Đường dẫn | Việc |
|---|---|
| `GET /api/v1/rb/tasks/` | inbox hợp nhất theo khách, có KPI, tìm kiếm, lọc nhóm và phân trang |
| `GET /api/v1/rb/opportunities/` | danh sách cơ hội cho pipeline, có phân trang |
| `POST /api/v1/rb/opportunities/bulk/` | cập nhật hàng loạt theo giao dịch tất-cả-hoặc-không |
| `GET/PATCH /api/v1/rb/opportunities/{id}/` | nhận việc, đổi trạng thái, đóng kèm lý do |
| `GET /api/v1/rb/people/{id}/` | hồ sơ bán lẻ (tạo sẵn nếu chưa có) |
| `PATCH /api/v1/rb/people/{id}/profile/` | cập nhật nghề nghiệp, phân khúc, việc tiếp theo |
| `GET /api/v1/rb/people/{id}/interests/` | quan tâm sản phẩm |
| `POST /api/v1/rb/suggest/` | dán một câu khách nói, xem gợi ý sản phẩm |
| `POST …/opportunities/{id}/draft/` | AI soạn lời chào (`channel`: `message` \| `call_script`) |
| `POST …/opportunities/{id}/sent/` | RM xác nhận đã gửi và lưu đúng bản cuối trong cùng giao dịch |

---

## 9. Soạn lời chào theo ngữ cảnh (Master Plan mục 33)

`rb/outreach.py` — bản song sinh của `hiring/outreach.py`, giữ đúng nguyên tắc
gốc: **AI chỉ được nhắc lại thứ đã có trong hồ sơ.**

"Hồ sơ" ở đây hẹp hơn bên tuyển dụng — không có CV, chỉ có `RBOpportunity.need`
(nhu cầu nói bằng lời khách), `evidence.excerpt` (trích nguyên văn bài viết) và
`RBProfile` (nghề nghiệp, đơn vị công tác). Càng ít dữ kiện thì càng dễ bịa, nên
ba ràng buộc trong prompt còn quan trọng hơn bên tuyển dụng:

* **Không hứa lãi suất, hạn mức, hay điều khoản cụ thể** — RM chốt việc đó trực
  tiếp, AI không thay được.
* **Không nói lộ nguồn tin.** Nội dung không được nhắc rằng thông tin đến từ
  việc theo dõi mạng xã hội — nói như RM chủ động liên hệ vì đúng nhu cầu, không
  phải "chúng tôi thấy bạn đăng...".
* **Hệ thống không tự gửi.** `POST .../sent/` chỉ ghi nhận RM đã gửi, và đổi
  `RBProfile.lead_status` giống hệt cách `_touch_profile` đã làm cho luồng đổi
  trạng thái cơ hội.

Chạy thật với Gemini (bài "cần vay 500 triệu mua nhà"):

> *Chào anh An, em là RM từ MSB. Em được biết anh đang quan tâm giải pháp vay
> 500 triệu để mua nhà... Chiều nay em gọi hỗ trợ anh phương án tính lịch trả
> nợ cụ thể nhé?*

Không cụt, không hứa số cụ thể, không lộ nguồn — và dùng đúng cơ chế chống cắt
cụt đã sửa ở `ai/providers.py` (`reasoning_effort="none"`, kiểm `truncated`).

---

## 10. RB Growth Engine — máy đề xuất, người quyết định

**Phase:** 14 · **Master Plan:** mục 33, 34, 35 · **Vị trí:** `rb/scoring.py`,
`rb/suggestions.py`

### 10.1. Vì sao thêm một trạm dừng

Trước Phase 14, `routing.route_signal()` biến **mọi** tín hiệu đủ ngưỡng thành
`RBOpportunity` ngay. Hệ quả: hộp thư của RM đầy những việc chưa ai quyết định
làm, và chỉ số "cơ hội đang mở" mất hết ý nghĩa vì nó đếm lẫn cả thứ máy đoán
lẫn thứ người đã nhận.

```text
Signal → ProductInterest → OpportunitySuggestion → RM ACCEPT → RBOpportunity
```

Ranh giới ở đây là ranh giới **trách nhiệm**, không phải kỹ thuật:

| | Ai nói | Nói gì |
|---|---|---|
| `OpportunitySuggestion` | máy | "người này có vẻ đáng gọi, đây là bằng chứng" |
| `RBOpportunity` | người | "tôi nhận việc này" |

`suggestions.accept()` là hàm **duy nhất** sinh `RBOpportunity` từ đề xuất, và
nó luôn đòi `actor` — không có giá trị mặc định, không có đường tắt cho tác vụ
nền. Muốn hệ thống tự nhận việc thay RM thì phải sửa chữ ký hàm đó, và lúc ấy
việc đó sẽ hiện ra trong code review chứ không lặng lẽ xảy ra.

`routing.create_opportunities()` **vẫn còn nguyên** cho luồng RM tự tạo cơ hội
từ Profile 360 — ở đó người đã quyết định rồi, không cần trạm dừng nữa.

### 10.2. Năm chiều điểm, không phải một "AI Lead Score"

```text
Fit           Người này có nằm trong khẩu vị sản phẩm không?
Need          Có bằng chứng họ đang cần không?
Timing        Bây giờ có phải lúc nên gọi không?
Reachability  Gọi có gặp được không?
Value         Nếu trúng thì đáng bao nhiêu?
```

Bốn chiều đầu nói về *khả năng thành công*. Chiều thứ năm nói về *độ đáng làm* —
hai câu hỏi khác nhau. Một cơ hội thẻ tín dụng dễ chốt 90% vẫn có thể đáng làm
sau một cơ hội vay mua nhà chỉ 40%, vì thời gian của RM là hữu hạn. Trộn chúng
vào một điểm duy nhất sẽ giấu mất đánh đổi đó.

```text
Priority = Fit×0.25 + Need×0.25 + Timing×0.25 + Reachability×0.15 + Value×0.10
           rồi NHÂN với strategic_weight của nhóm sản phẩm
```

Hệ số chiến lược **nhân** chứ không cộng: sản phẩm đang được đẩy mạnh phải nổi
lên trong cả danh sách, không chỉ nhích vài điểm.

**LLM không sinh ra bất kỳ con số nào ở đây.** Một "AI Lead Score = 87" không
giải thích được là thứ RM sẽ ngừng tin sau khoảng ba lần gọi trượt — và chính
việc phản bác được từng chiều mới làm nên độ tin cậy. Mỗi hàm chấm trả về
`(điểm, [lý do])`; các lý do được gộp vào `evidence["why"]` và hiển thị nguyên
văn ở mục **VÌ SAO BÂY GIỜ** trên thẻ.

### 10.3. Hai ngưỡng, và vì sao Need có ngưỡng riêng

```python
MIN_PRIORITY = 40.0   # điểm tổng
MIN_NEED     = 50.0   # riêng chiều Need, kế thừa routing.MIN_CONFIDENCE
```

Bốn chiều kia có thể **cứu** một nhu cầu mơ hồ: người có hồ sơ đẹp, dễ liên hệ,
tín hiệu vừa phát sinh hôm qua, sản phẩm giá trị cao — chỉ mỗi việc là ta không
thật sự biết họ có cần hay không — vẫn dễ dàng vượt 40 điểm tổng. Gọi cho người
đó là gọi cho một người không hỏi gì. Need là chiều duy nhất không được bù trừ.

### 10.4. Chưa có số điện thoại ≠ khách từ chối

| Tình huống | Điểm Reachability | Hệ quả |
|---|---|---|
| Cờ **DNC** | `0` | **Không tạo đề xuất nào** |
| Chưa có SĐT/email | `NO_CONTACT_SCORE = 15` | Vẫn tạo, hành động = `ASK_FOR_INFORMATION` |
| Có SĐT + email | tới `100` | Xếp hạng bình thường |

Gộp hai dòng đầu (cho cả hai về 0) là bỏ mất đúng nhóm khách đáng giá nhất của
Social Radar: người vừa lộ nhu cầu rõ ràng trên mạng xã hội nhưng ta chưa có số.
Việc cần làm với họ là *đi xin số*, không phải bỏ qua.

`recommend_action()` nhận `has_contact` như một tham số riêng chứ không suy ra
từ điểm — điểm là thang liên tục có thể chỉnh, còn "có kênh liên hệ hay không"
là sự thật nhị phân. Suy cái sau từ cái trước nghĩa là mỗi lần ai đó tinh chỉnh
`NO_CONTACT_SCORE` thì hành động đề xuất lặng lẽ đổi theo.

### 10.5. Giá trị sản phẩm là cấu hình, không phải hằng số

`ProductValueConfig` là một bảng, không phải hằng số trong code như
`PRODUCT_CHOICES`. Danh mục sản phẩm đổi vài năm một lần; *giá trị kinh tế* của
từng nhóm đổi theo từng quý.

Quan trọng hơn: đây là dữ liệu **chưa được kiểm chứng**. Đội thi không có số
biên lợi nhuận thật của MSB, và bịa một con số VNĐ cụ thể rồi đem đi thi là tự
tạo ra một câu hỏi không trả lời được trước hội đồng. Nên mặc định dùng thang
định tính (Thấp/Trung bình/Cao/Rất cao); khi có số thật thì nhập `value_weight`
qua trang quản trị và nó tự động thắng thang định tính — không cần sửa code.

### 10.6. Next Best Action

```text
CALL_NOW · SEND_MESSAGE · ASK_FOR_INFORMATION · FOLLOW_UP
WAIT · REACTIVATE · INVITE_MEETING · CLOSE
```

Mã hành động do business logic quyết định. LLM được phép soạn *nội dung* cho
hành động đã chọn, nhưng không được chọn nó — chọn sai hành động là chuyện
nghiệp vụ, không phải chuyện ngôn ngữ.

### 10.7. Theo dõi kết quả — khép vòng lặp

`OpportunityOutcome` trả lời câu mà `outreach_sent_at` không trả lời được:
**gửi rồi thì sao**.

```text
NO_RESPONSE · READ · REPLIED · INTERESTED · MAYBE_LATER · NOT_INTERESTED
WRONG_PRODUCT · ALREADY_USING · NEED_CONSULTATION · MEETING_BOOKED · CONVERTED
```

Chỉ 4 kết quả cho phép gợi ý lại (`REACTIVATABLE`): `NO_RESPONSE`,
`MAYBE_LATER`, `NEED_CONSULTATION`, `WRONG_PRODUCT`. `NOT_INTERESTED` và
`ALREADY_USING` cố ý **không** nằm trong đó — chào lại người đã nói không là
cách nhanh nhất để mất khách.

### 10.8. API

| Endpoint | Việc |
|---|---|
| `GET /api/v1/rb/today/` | Cơ hội hôm nay + tóm tắt theo nhóm |
| `POST /api/v1/rb/suggestions/<id>/action/` | `accept` · `snooze` · `dismiss` |
| `GET,POST /api/v1/rb/opportunities/<id>/outcomes/` | Ghi nhận kết quả tiếp cận |

`dismiss` **bắt buộc kèm lý do** (400 nếu thiếu) — cùng nguyên tắc với
`RBOpportunity.close_reason`: một đề xuất bị bỏ im lặng sẽ được sinh lại y hệt
vào tháng sau.

---

## 11. Cá nhân hoá theo khai báo của RM

**Model:** `accounts.UserWorkProfile` · **Chấm:** `rb/scoring.py::personalize()`
**API:** `GET,PUT /api/v1/rb/work-profile/`

### 11.1. Bài toán

Radar chấm một cơ hội theo giá trị khách quan: nhu cầu rõ tới đâu, còn nóng
không, có gọi được không. Nhưng *"cơ hội tốt"* và *"cơ hội tốt **cho tôi**"* là
hai câu khác nhau. Một khoản vay mua nhà ở Đà Nẵng có thể là đề xuất mạnh nhất
hệ thống mà vẫn vô dụng với RM phụ trách Hà Nội đang chạy chỉ tiêu thẻ tín dụng.

RM tự khai:

```text
Địa bàn phụ trách        ["Hà Nội", "Bắc Ninh"]
Sản phẩm trọng tâm       ["mortgage", "credit_card"]
Phân khúc nhắm tới       ["affluent", "priority"]
Số việc/ngày xử lý nổi   20   ← thành số dòng mặc định của danh sách
Ghi chú tự do            "Phụ trách khu công nghiệp phía Bắc,
                          khách chủ yếu là chủ xưởng."
```

### 11.2. Vì sao KHÔNG gộp vào `priority_score`

Đây là quyết định kiến trúc quan trọng nhất của tính năng này. Điểm lưu trong
`OpportunitySuggestion` giữ nguyên nghĩa khách quan; cá nhân hoá tính **lúc
đọc** và trả về như một điểm riêng.

| Nếu gộp vào điểm lưu | Hệ quả |
|---|---|
| Điểm pha sở thích người xem | Tỷ lệ chấp nhận của RM A và RM B không còn so được — mọi chỉ số ở `rb/metrics.py` mất nghĩa |
| Một đề xuất có nhiều điểm | Câu hỏi *"vì sao đề xuất này 82 điểm"* không còn một câu trả lời, mà thành *"còn tuỳ ai đang đăng nhập"* |
| Khai báo đổi → điểm cũ đổi | RM sửa địa bàn hôm nay viết lại điểm của đề xuất sinh tháng trước |

Nên thẻ trả về **cả hai**:

```json
{ "priority_score": 71.2, "personalized_score": 79.2,
  "personalized_why": ["Nằm trong địa bàn bạn phụ trách"],
  "territory": "in", "handoff_to": null, "is_discovery": false }
```

### 11.3. Giới hạn ±20 điểm

```python
PERSONALIZATION_CAP = 20.0
MATCH_FOCUS_PRODUCT = +12    MATCH_REGION = +8
MATCH_SEGMENT       = +5     MISS_REGION  = -10
```

Cá nhân hoá để **sắp xếp lại** những cơ hội đều đáng làm, không phải để đẩy một
cơ hội yếu lên đầu chỉ vì nó trúng sản phẩm đang được giao chỉ tiêu. Một khoản
vay có nhu cầu mơ hồ vẫn phải xếp sau một khoản vay nhu cầu rõ ràng — kể cả khi
RM đang chạy đúng chỉ tiêu nhóm đó. Không có trần thì tính năng này biến thành
đường vòng để lách `MIN_NEED`.

### 11.4. Ba chi tiết dễ làm sai

**Xếp lại trên tập rộng hơn `limit`.** `todays_best()` lấy `limit × 3` dòng rồi
mới xếp lại và cắt. Nếu chỉ lấy đúng top-20 rồi xếp lại thì cơ hội trúng địa bàn
nằm ở hạng 21 không bao giờ hiện ra — tức là cá nhân hoá không làm được đúng
việc nó sinh ra để làm.

**Không biết khách ở đâu thì không phạt.** Thiếu `Person.location` là lỗ hổng dữ
liệu của hệ thống, không phải bằng chứng khách nằm ngoài địa bàn. Phạt ở đây sẽ
đẩy toàn bộ nhóm hồ sơ thiếu thông tin xuống đáy — mà đó thường lại là nhóm mới
thu về từ Social Radar.

**Ghi chú tự do KHÔNG tham gia vào bất kỳ con số nào.** Nó chỉ được đưa vào
prompt sinh `reasoning_summary` — ảnh hưởng tới *lời giải thích*, không ảnh
hưởng tới *thứ hạng*. Nếu để văn bản tự do lái điểm số thì không ai kiểm được vì
sao thứ tự đổi, và người dùng sẽ học cách "viết cho hệ thống thích" thay vì mô tả
đúng công việc mình làm.

### 11.5. Cá nhân hoá được xếp lại, KHÔNG được loại bỏ

Đây là nguyên tắc quan trọng nhất của cả mục 11, và nó chống lại chính mặt trái
của tính năng này: càng khai kỹ, RM càng chỉ nhìn thấy thứ họ đã biết mình muốn
nhìn. Lời khai biến thành cái lồng, và Radar — vốn sinh ra để *"phát hiện thứ
người dùng không biết để đi tìm"* — biến thành một cái bộ lọc.

Ba cơ chế giữ điều đó, mỗi cái canh một kiểu hỏng khác nhau:

**a. Suất khám phá 20%** (`DISCOVERY_RATIO`). Bốn phần năm danh sách xếp theo
điểm cá nhân hoá; một phần năm còn lại xếp thuần theo **điểm khách quan**, bất
kể có khớp khai báo hay không, và được đánh dấu `is_discovery` để giao diện nói
rõ *"Ngoài vùng bạn phụ trách — đáng xem"*. Xếp phần này theo điểm cá nhân hoá
sẽ biến nó thành phần đuôi của cùng một danh sách, tức là không khám phá gì cả.

Bỏ phần này thì ba thứ hỏng cùng lúc: RM không bao giờ thấy cơ hội lớn ngoài địa
bàn; quản lý không bao giờ phát hiện việc phân địa bàn đang sai; hệ thống không
có cách nào biết lời khai đã cũ.

**b. Ngoài địa bàn thì ĐỊNH TUYẾN, không đánh rơi.** Bản đầu trừ 10 điểm cho
khách ngoài địa bàn. Đó là sai hướng: khách Đà Nẵng có nhu cầu vay 5 tỷ bị trừ
điểm → tụt hạng → không ai gọi → **ngân hàng mất khách**.

Nay `MISS_REGION = -4` (nhẹ, vì đúng là việc này nhiều khả năng không phải của
tôi), kèm `territory = "out"` và `handoff_to` chỉ đúng RM đang phụ trách khu vực
đó. Khách được giữ lại trong hệ thống, chỉ đổi người xử lý. `handoff_to` là
**gợi ý**, không tự chuyển — chuyển việc cho người khác là quyết định của con
người, cùng nguyên tắc với `accept()`.

`territory` có ba giá trị chứ không phải cờ đúng/sai: `in` · `out` · `unknown`.
Gộp `unknown` vào `out` sẽ đối xử mọi hồ sơ thiếu `location` như nằm ngoài địa
bàn — mà đó thường lại là nhóm mới thu về từ Social Radar.

**c. Suy khai báo từ hành vi, để form không bao giờ trống**
(`observed_work_profile()`). Rủi ro thực tế lớn nhất của khai báo thủ công là
**không ai khai** — và một tính năng chỉ chạy khi người dùng chịu điền form là
một tính năng chết.

Hệ thống đã ghi sẵn đủ dữ liệu để tự suy ra: RM nhận cơ hội ở đâu, chốt được sản
phẩm nào. Đó là *sở thích bộc lộ qua hành vi* — chính xác hơn lời khai và tốn 0
công sức. `GET /rb/work-profile/` trả về nó ở khoá `observed`, **tách riêng**
khỏi khai báo thật để người dùng phân biệt được đâu là mình khai, đâu là máy
đoán.

Ba ràng buộc:

```text
Dưới 3 việc đã làm      → im lặng (confident=False). Đoán địa bàn từ hai cơ hội
                          là cách nhanh nhất khiến người dùng mất tin.
Dưới 15% tổng số việc   → không tính. Một cơ hội lẻ ở Cần Thơ không biến
                          Cần Thơ thành địa bàn của ai cả.
Không bao giờ tự lưu    → chỉ điền sẵn, người bấm xác nhận.
```

Sản phẩm **chốt được** được đẩy lên trước sản phẩm chỉ được giao: nhận 20 cơ hội
thẻ mà chỉ chốt được bảo hiểm thì trọng tâm thật là bảo hiểm.

Tự học tự đổi khai báo là việc của giai đoạn sau (Master Plan mục 20, P2) — làm
sớm thì RM không còn hiểu vì sao danh sách của mình đổi.

### 11.6. Quyền

`GET,PUT /api/v1/rb/work-profile/` chỉ thao tác trên `request.user` — không có
tham số nào cho phép đọc hoặc sửa khai báo của người khác. Địa bàn và chỉ tiêu
của một RM là chuyện giữa họ và quản lý của họ.

Khoá `(user, domain)` cùng khuôn với `people.Relationship` khoá `(person,
domain)`: một Manager kiêm cả hai nghiệp vụ có hai hồ sơ, và trọng tâm tuyển
dụng không lẫn với trọng tâm bán lẻ.

---

## 12. Tìm prospect bằng ngôn ngữ tự nhiên

**Master Plan:** mục 16 · **Vị trí:** `rb/prospects.py` · **API:** `POST /api/v1/rb/prospects/`

Khác với mục 10 — nơi Radar **chủ động đẩy** cơ hội tới RM — mục này phục vụ lúc
RM **chủ động hỏi**. Hai luồng bổ sung nhau: *"hôm nay tôi nên gọi ai"* và
*"tìm cho tôi nhóm người thế này"* là hai câu hỏi khác nhau.

```text
"Tìm 20 quản lý ở Hà Nội có contact, quan tâm thẻ tín dụng"
    ↓
tiêu chí (hiện ra, sửa được) → tìm người → chấm 5 chiều → giải thích
```

### 12.1. Ba đường bóc tách, luôn có đáy tất định

```text
1. Prospect Agent trên GreenNode AgentBase   (nếu MSB_AGENT_ENDPOINT được đặt)
2. LLM qua ai/router                         (cùng mô hình, chạy tại Hub)
3. Dò từ khoá tất định                       (luôn chạy được)
```

Đường nào phục vụ được ghi trong `criteria_from` — người vận hành cần biết
đường nào đang chạy khi kết quả trông lạ.

Vì sao làm được cả ba: agent có thể chưa deploy, có thể đang restart. Một sản
phẩm phụ thuộc cứng vào một endpoint bên ngoài là sản phẩm không demo được khi
endpoint đó chập.

### 12.2. Hub không tin agent chỉ vì đó là agent của mình

`_merge()` lọc lại đầu ra của **mọi** đường bóc tách, kể cả đường qua agent.
Agent đã lọc một lần rồi, nhưng một phiên bản agent cũ hơn, hoặc một endpoint bị
trỏ nhầm, đều trả về thứ Hub không hiểu.

### 12.3. DNC là ràng buộc, không phải bộ lọc

`search()` luôn loại người đã bật cờ Không liên hệ — kể cả khi RM hỏi đích danh
nhóm đó. Không có tham số nào tắt được điều này.

### 12.4. Dùng lại đúng công thức chấm điểm

`_score()` gọi thẳng `rb/scoring.py`. Không có công thức thứ hai: hai nơi tính
điểm là hai nơi sẽ lệch nhau, và lúc đó không ai giải thích được vì sao cùng một
người có hai điểm khác nhau ở hai màn hình.

Lấy rộng hơn `limit` rồi mới chấm và cắt — xếp theo `updated_at` rồi cắt trước
khi chấm sẽ trả về nhóm được sửa gần đây nhất, không phải nhóm phù hợp nhất.

---

## 13. Còn thiếu

* Tìm kiếm khách hàng theo bộ lọc riêng của bán lẻ (mục 25.2).
* Giao diện React cho "Cơ hội hôm nay" — API đã xong, màn hình chưa.
* Phân khúc khách hàng còn nhập tay, chưa suy ra từ dữ liệu.
* Lead Recipes, Reactivation Radar tự động, Lookalike Prospects (P1).
* Chỉ số acceptance/conversion cho vòng lặp đề xuất (mục 50).
* Hồ sơ công việc cho **tuyển dụng** (`domain="talent"`) — model đã sẵn sàng,
  chưa nối vào Talent Search.
* Ghi chú tự do chưa được đưa vào prompt `reasoning_summary` (đã thiết kế chỗ
  cắm, chưa nối).
