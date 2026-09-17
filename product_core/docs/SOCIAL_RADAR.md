# Social Radar

**Phase:** 10 (nền tảng) — hoàn thành · 11 (dùng cho Talent) — phần Hub xong,
còn thiếu bộ thu Facebook ở Edge
**Master Plan:** mục 26–35
**Vị trí:** `server/social/`, `web/src/Social.tsx`

---

## 1. Màn hình này trả lời hai câu

```text
1. Bài viết này có phải một cơ hội không?    → điểm ý định, đa nhãn
2. Ta đã biết người này chưa?                → khớp vào People Database
```

**Câu thứ hai mới là chỗ sản phẩm có giá trị.** Một bài *"em đang tìm việc"* trên
Facebook thì ai đọc cũng thấy. Biết rằng **người ấy từng nộp CV cho MSB 9 tháng
trước** thì chỉ hệ thống này biết — và đó là lý do để nhấc máy gọi.

```text
Bài đăng
   ↓  intent.detect()       chấm ý định theo từng nghiệp vụ
   ↓  _resolve_author()     khớp với người đã có trong kho
   ↓  people.Signal         tín hiệu, kèm bằng chứng trích nguyên văn
Cơ hội cho recruiter / RM
```

---

## 2. Vì sao KHÔNG có bảng `SocialSignal`

Master Plan mục 10 liệt kê cái tên đó. Không làm, và đây là lý do:

`people.Signal` đã là **hạ tầng tín hiệu dùng chung** cho mọi nghiệp vụ (mục 15),
còn Nguyên tắc 2 nói *một People Database dùng chung*. Đẻ thêm một bảng tín hiệu
song song nghĩa là màn hình Person 360 phải hợp nhất hai nguồn, và sớm muộn sẽ có
chỗ chỉ đọc một trong hai — thường là chỗ mới viết, đọc thiếu cái cũ.

Bài viết sinh ra `people.Signal` như mọi tín hiệu khác; `SocialPost` giữ phần
bằng chứng thô.

---

## 3. Điểm ý định là **đa nhãn**

```python
{"talent": 0.91, "rb": 0.07}     người đang tìm việc
{"talent": 0.72, "rb": 0.65}     vừa tìm việc vừa hỏi vay — có thật, hay gặp
{"talent": 0.02, "rb": 0.03}     không liên quan
```

Hai điểm **độc lập**, không cộng lại bằng 1. Ép về một nhãn duy nhất là bịa ra
một lựa chọn mà dữ liệu không có.

### Ngưỡng nằm ở tầng gọi, không nằm trong bộ chấm

```python
THRESHOLDS = {"talent": 0.5, "rb": 0.7}      # social/pipeline.py
```

Tuyển dụng nghe rộng được — gọi nhầm một người không tìm việc chỉ tốn 2 phút.
Bán lẻ phải chắc mới động vào — nhắn tin mời vay tiền cho người không hỏi là
chuyện khác hẳn về mặt cảm nhận và về mặt tuân thủ.

### Hai cái bẫy đã chặn sẵn

Chỗ nguy hiểm nhất của module này không phải kỹ thuật mà là **chấm nhầm phía**:

| Bài viết | Bẫy | Hậu quả nếu chấm nhầm |
|---|---|---|
| *"CÔNG TY ABC TUYỂN GẤP 5 Data Analyst"* | nhà tuyển dụng, không phải ứng viên | kho ứng viên đầy nhà tuyển dụng |
| *"Bên em hỗ trợ vay lãi suất thấp"* | môi giới, không phải khách hàng | danh sách khách hàng đầy người bán |

Cả prompt lẫn đường lui dò từ khoá đều có danh sách dấu hiệu "bên kia giao dịch"
và hạ điểm xuống dưới ngưỡng hành động khi gặp.

---

## 4. Không tự tạo `Person` mới từ một bài đăng

Bài viết cho ta cùng lắm là một số điện thoại và một cái tên hiển thị. Tạo
`Person` từ đó sẽ đổ vào People Database những hồ sơ rỗng mà không nghiệp vụ nào
dùng được — và làm hỏng chính chỉ số *"lượt ứng tuyển trên mỗi người"*.

Chỉ khi bài có **định danh mạnh** (số điện thoại/email chuẩn hoá được) **và**
khớp đúng **một** người đã có thì mới gắn. Khớp nhiều người thì để nguyên: gộp
nhầm hai con người tệ hơn nhiều so với bỏ lỡ một tín hiệu.

---

## 5. Liên hệ phải **có thật trong bài**

```python
contacts = {k: v for k, v in contacts.items() if _appears_in(v, text)}
```

Mô hình đôi khi "hoàn thiện" một số điện thoại thiếu chữ số. Một tin nhắn tuyển
dụng gửi tới người hoàn toàn vô can là chuyện không sửa lại được — nên số nào
không nằm nguyên văn trong bài thì bị loại, kể cả khi mô hình rất tự tin.

So sánh bỏ qua dấu cách và dấu chấm, để `090.123.4567` vẫn khớp `0901234567`.

---

## 6. Bối cảnh nhóm được đưa vào prompt

Cùng câu *"em cần tư vấn gấp"*:

* trong nhóm **Việc làm IT Hà Nội** → ý định tuyển dụng
* trong nhóm **Vay vốn ngân hàng** → ý định tài chính

`Community.topic` được ghép vào prompt (Master Plan mục 30 — *"group context"*).

---

## 7. Hai đường vào

| Đường | Dùng khi |
|---|---|
| `POST /api/v1/social/ingest/` | Edge gửi lô bài bắt được từ nhóm |
| `POST /api/v1/social/analyze/` | người dùng dán một bài vào xem thử |

Đường thứ hai **không phải đồ chơi**: nó cho phép demo Social Radar khi chưa có
adapter Facebook ở Edge, và là cách nhanh nhất để người nghiệp vụ kiểm chứng xem
AI chấm có đúng không, bằng chính những bài họ đọc hằng ngày.

**`analyze` mặc định KHÔNG lưu gì.** Người ta thử bằng bài viết của người thật,
và một nút "xem thử" mà âm thầm ghi dữ liệu cá nhân vào CSDL là thứ không nên
tồn tại trong hệ thống ngân hàng. Muốn lưu thì phải gửi `save: true`.

`ingest` chỉ chấm **bài mới**. Chấm lại cả lô mỗi lần Edge gửi sẽ đốt hạn mức
LLM vào những bài đã có câu trả lời.

---

## 8. API

| Đường dẫn | Việc |
|---|---|
| `POST /api/v1/social/analyze/` | dán một bài, xem ý định + khớp người |
| `POST /api/v1/social/ingest/` | Edge gửi lô bài (tối đa 100) |
| `GET /api/v1/social/posts/` | bài đáng chú ý (`?domain=talent`, `?linked=1`) |
| `POST …/posts/{id}/rescore/` | chấm lại một bài |
| `GET/POST /api/v1/social/communities/` | nhóm đang theo dõi |
| `GET /api/v1/social/accounts/` | tài khoản dùng để nghe |
| `GET/POST /api/v1/social/actions/` | nháp hành động (bình luận, nhắn tin, đăng tuyển) |

Quyền: module `social` — Recruiter, RB Sales và Admin vào được; Hiring Manager
thì không (mục 26: Social Radar là năng lực dùng chung của hai nghiệp vụ tiếp
xúc khách hàng).

---

## 9. Còn thiếu

* **Bộ thu Facebook ở Edge** (mục 27–29) — phần lớn công việc còn lại nằm đây.
  Hub đã sẵn sàng nhận: `ingest` là hợp đồng ổn định.
* `SocialAction` mới có mô hình và API (kể cả lựa chọn `KIND_SEED_POST`), chưa có
  màn hình soạn nội dung bằng AI cho **cả năm chế độ** mục 33 liệt kê (Recruitment
  Seeding — mục 31, Talent Engagement, RB Product Engagement, Follow-up, Inbox
  Draft) lẫn luồng Approve/Edit/Post của mục 34 — `social/views.py::action_list`
  hiện chỉ là CRUD chung, không có logic sinh nội dung. Audit Phase 15 xác nhận
  gộp riêng "Recruitment Seeding" (mục 31, phía Recruiter đăng bài) vào đây vì
  trước đó tài liệu chỉ nhắc mục 33–34 một cách chung chung, dễ đọc nhầm là chỉ
  còn thiếu phần RB.
* Theo dõi kết quả sau khi đăng (mục 35) — `SocialAction.outcome` để trống.
* ~~Phần dùng cho RB (mục 32) — chấm điểm đã có, chưa có màn hình cho RM~~ — **đã
  làm ở Phase 12–13** (`web/src/RB.tsx`, `rb/outreach.py`), xoá khỏi danh sách
  còn thiếu qua audit Phase 15.
