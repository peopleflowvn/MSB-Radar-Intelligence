# Runbook ngày demo

**Dùng cho:** Submit 23/09/2026 · Hackday 26/09/2026, Hà Nội
**Đọc trước khi lên sân khấu. Không đọc trong lúc đang pitch.**

---

## 1. Chuẩn bị (làm tối hôm trước, không làm tại chỗ)

```powershell
# 1. Dựng lại dữ liệu demo — sạch, biết trước, tái lập được
cd D:\Project\MSB_Radar\server
python manage.py migrate
python manage.py seed_demo --reset

# 2. Chạy thử TOÀN BỘ đường demo bằng máy, không bằng tay
python manage.py test core.tests_hero_flow

# 3. Build giao diện (đừng dựa vào `npm run dev` lúc pitch)
cd ..\web
npm run build
```

Rồi **tự bấm lại một lượt đúng kịch bản mục 3**. Bài kiểm thử tự động không thay
được việc nhìn thấy màn hình.

### Tài khoản

| Tài khoản | Vai trò | Dùng để diễn |
|---|---|---|
| `truongbophan` | Trưởng bộ phận tuyển người | phần 1–4 của kịch bản |
| `tuyendung` | Chuyên viên Tuyển dụng | phần 5–6 |
| `admin` | Quản trị | dự phòng, vào `/admin/` |

Mật khẩu tất cả: `mat-khau-demo-1234`

> Đây là mật khẩu **demo**. Máy chủ thật phải đổi trước khi có dữ liệu thật —
> `seed_demo` cố ý không chạy được ngoài ý muốn vì nó là một lệnh phải gõ tay.

---

## 2. Kiểm tra 5 phút trước khi lên

| Kiểm | Cách | Nếu hỏng |
|---|---|---|
| Hub sống | mở `/api/v1/health/` | khởi động lại `runserver` |
| Có người trong kho | tab **Talent Radar** thấy 8 người | chạy lại `seed_demo --reset` |
| Khoá LLM còn hạn mức | tab **Cài đặt AI** → **Thử** | xem mục 5 — vẫn diễn được |
| Chỉ số hiện số, không hiện `—` | tab **Vị trí tuyển** | chạy lại kịch bản một lượt để sinh dữ liệu |

---

## 3. Kịch bản (7–8 phút)

**1. Bài toán** — *"Kho CV của MSB có hàng chục nghìn hồ sơ. Người ứng tuyển hai
năm trước, giờ đã đúng trình độ ta cần, nhưng không ai nhớ ra họ."*

**2. Hỏi bằng lời** — đăng nhập `truongbophan`, tab **Talent Radar**:

> *Tôi cần Data Analyst ở Hà Nội biết SQL và Python, ít nhất 3 năm*

Chỉ vào **hàng chip “AI hiểu là”** — nói rõ: *AI dịch câu hỏi thành tiêu chí, và
tiêu chí đó hiện ra để người dùng sửa, không phải một hộp đen.*

**3. Giải thích được** — chỉ vào khối **DỮ LIỆU CHO BIẾT / SUY LUẬN / CHƯA
BIẾT**. Câu chốt: **điểm phù hợp do code tất định tính, LLM chỉ diễn giải.** Mở
*“Vì sao lại điểm này?”* để cho thấy từng chiều và trọng số.

**4. Tạo vị trí và dạy hệ thống** — bấm **“Tạo vị trí tuyển từ tiêu chí này”**.
Chấm 2 người *Phù hợp*, 2 người *Không phù hợp*, rồi **“Học lại từ đánh giá”**.

Đọc to câu hệ thống trả về: *“Bạn thiên về hồ sơ mạnh ở kỹ năng — tăng trọng
số. Nơi ở không phải thứ bạn dựa vào — giảm trọng số.”*

> Điểm mạnh nhất của phần này: **không fine-tuning model nào cả.** Điểm vốn là
> tổng có trọng số của các chiều tất định, nên học từ phản hồi chỉ là chỉnh
> trọng số — giải thích được thành lời, và chạy trong vài mili giây.

**5. Bàn giao** — Shortlist 2 người → **“Nhờ recruiter săn”**.

**6. Phía Recruiter** — đăng xuất, đăng nhập `tuyendung`, tab **Yêu cầu săn**.
Nhận việc → **Soạn thư** → chỉ vào dòng chữ dưới ô soạn thảo:

> *AI chỉ nhắc lại dữ kiện có trong hồ sơ. Đọc lại trước khi gửi — thư này mang
> tên MSB và đi tới một người thật.*

Nhấn mạnh: **hệ thống không tự gửi.** Nút là *“Tôi đã gửi”*, không phải *“Gửi”*.

**7. Đóng vòng** — hai thao tác, đừng bỏ thao tác nào:

* Người thứ nhất: **“Chuyển cho HM”** — đây mới là lúc vòng lặp khép lại, và nó
  cũng là thứ làm chỉ số *“Yêu cầu săn có kết quả”* ở bước 8 khác 0.
* Người thứ hai: **“Trả về kho”** kèm lý do. Nói vì sao bắt buộc phải có lý do:
  *hồ sơ quay lại kho mà không ai biết vì sao thì tháng sau lại có người gọi lại
  từ đầu, và ứng viên nhận cuộc gọi thứ hai hỏi đúng câu đã trả lời rồi.*

Xong cả hai người thì yêu cầu săn **tự chuyển sang “Xong”** và **biến khỏi tab
“Cần xử lý”**. Đừng bối rối — bấm sang tab **“Tất cả”** để cho thấy nó nằm đó
với trạng thái *Xong*. Đó là ý đồ: hộp thư chỉ hiện việc còn phải làm.

**8. Con số** — quay lại tab **Vị trí tuyển**, chỉ vào hàng chỉ số. Chỉ số cốt
lõi là **Tái sử dụng hồ sơ cũ**: *nếu con số này thấp thì chúng tôi chỉ đang lọc
hồ sơ mới nhanh hơn, chứ không làm được việc gì mới.*

---

### Phần phụ (chỉ diễn nếu còn thời gian): Social Radar → RB Radar

Đây là **demo phụ trong Master Plan mục 49**, và nó chứng minh điều khó chứng
minh nhất bằng lời: *một People Database, nhiều nghiệp vụ.*

Đăng nhập `sales` (RB Sales — vai trò duy nhất thấy cả hai tab).

**1. Bài tìm việc.** Tab **Social Radar** → **Thử một bài** → ví dụ đầu tiên.

* AI chấm ý định **đa nhãn** — một bài có thể vừa là ứng viên vừa là khách hàng.
* Thử ví dụ thứ ba (bài đăng tuyển của công ty khác): điểm **thấp**. Hệ thống
  phân biệt được người tìm việc với người tuyển người — chấm nhầm chỗ này sẽ
  làm kho ứng viên đầy nhà tuyển dụng.
* **Câu chốt:** *"Từng ứng tuyển hơn 3 năm trước qua topcv, và vừa có tín hiệu
  trên mạng xã hội."* Một bài "em đang tìm việc" thì ai đọc cũng thấy; biết
  người ấy đã nộp CV cho MSB thì chỉ hệ thống này biết.

**2. Bài vay tiền — cùng một con người đó.** Ví dụ thứ hai:

> *Nhà em đang cần vay 500 triệu mua nhà, ngân hàng nào lãi suất tốt ạ?*

Điểm nhảy sang **Khách hàng cá nhân**, và vẫn khớp đúng người ấy. Sang tab
**RB Radar** → cơ hội **"Vay mua nhà"** đã nằm trong hộp thư, kèm trích nguyên
văn bài viết và việc nên làm tiếp.

Câu để nói: *"Cùng một con người. Tuyển dụng thấy một ứng viên, bán lẻ thấy một
khách hàng — nhưng chỉ có **một** hồ sơ, không phải hai cơ sở dữ liệu."*

**3. Nói rõ giới hạn.** **Bộ thu Facebook ở Edge chưa làm.** Đây là phần Hub,
dán tay để kiểm chứng. Đừng để ban giám khảo tự hiểu là đã có bot chạy.

> Cơ hội bán lẻ chỉ sinh ra khi bài được **lưu** (`save`), còn nút "Xem AI đọc
> ra gì" cố ý không lưu gì. Muốn diễn trọn phần 2 thì chuẩn bị sẵn một cơ hội
> trong hộp thư từ tối hôm trước.

---

## 4. Câu hỏi ban giám khảo sẽ hỏi

| Hỏi | Trả lời |
|---|---|
| *AI có tự quyết ai được tuyển không?* | Không. LLM không chấm điểm; nó chỉ dịch câu hỏi và diễn giải. Xem `docs/AI_TALENT_SEARCH.md` mục 1. |
| *Dữ liệu ứng viên có bị đưa cho bên thứ ba không?* | Bước giải thích chỉ gửi **dữ kiện đã rút ra**, không gửi hồ sơ thô. Đổi được sang GreenNode để dữ liệu không rời hạ tầng trong nước. |
| *Hai người trùng tên thì sao?* | Không tự gộp. Xung đột email/số điện thoại tạo `IDENTITY_CONFLICT` cho người xử lý — `docs/PEOPLE_CORE.md`. |
| *Ai xem được hồ sơ nào?* | 6 vai trò, chặn ở máy chủ, mọi lượt truy cập vào `AccessLog`, truy cập liên nghiệp vụ bị đánh dấu riêng — `docs/ACCESS_CONTROL.md`. |
| *Khoá LLM chết thì sao?* | Xoay nhiều khoá, chuyển nhà cung cấp, và cuối cùng lùi về dò từ khoá. Trần 25 giây cho cả lượt gọi. |
| *Vì sao không dùng vector search / RAG?* | Sẽ dùng khi có dữ liệu chứng minh cần. Hiện tiêu chí tuyển dụng là các trường có cấu trúc, mà truy vấn có cấu trúc thì **giải thích được** — đó là yêu cầu cứng của ngân hàng. |
| *Chạy được ở quy mô thật không?* | Edge chạy tại máy đơn vị (Hub không giữ cookie provider), Hub là Django + PostgreSQL. Con số hiện tại: 190 test Edge, 636 test Hub. |
| *Có theo dõi được hệ thống đang chạy ra sao không?* | Có — tab **Vận hành** (chỉ Admin/Manager): đồng bộ Edge, chi phí AI theo nhà cung cấp, và quan sát từng lượt chạy agent (bao lâu, lỗi bao nhiêu) — không phải chỉ tin vào "có vẻ chạy được". |
| *Dữ liệu tuyển dụng dùng cho bán hàng có được không?* | Đó là câu hỏi **chính sách**, không phải kỹ thuật. Hệ thống ghi lại mọi lượt truy cập liên nghiệp vụ để Compliance trả lời được câu "ai đã xem gì". Xem `docs/ACCESS_CONTROL.md` mục 4.3 — có 3 câu hỏi đang chờ MSB quyết. |
| *Sao không dùng một hồ sơ khách hàng riêng cho bán lẻ?* | Vì đó chính là bài toán. Hai bản ghi cùng một người sẽ lệch nhau, và không ai biết bản nào đúng. `RBProfile` cố ý **không có** trường tên/email/điện thoại. |

---

## 5. Khi sự cố xảy ra

### Mạng hội trường chậm hoặc chết

**Vẫn diễn được toàn bộ kịch bản.** Mọi bước gọi AI đều có đường lui dò từ khoá,
và trần thời gian là **25 giây** cho cả lượt gọi (`MSB_AI_BUDGET_SECONDS`).

Trên tiến trình sẽ hiện *“Không gọi được AI, dò theo từ khoá”* kèm những từ khoá
nhận ra được. **Đừng giấu — chỉ vào nó.** Đó là một điểm cộng, không phải một
lỗi: *hệ thống hỏng ra tiếng, và vẫn trả về người thật.*

Muốn chủ động chạy chế độ này (ví dụ khi mạng chập chờn hơn là chết hẳn), tắt
hết nhà cung cấp trong tab **Cài đặt AI**.

### Khoá Gemini bị giới hạn tốc độ

Xảy ra ở lượt gọi thứ ~15 trong một phút. Trên khoá miễn phí, **chuyện này gần
như chắc chắn xảy ra** nếu bấm thử nhiều lần trước khi lên.

* Chuẩn bị **ít nhất 2 khoá** trong tab **Cài đặt AI** — hệ thống tự xoay vòng.
* Hoặc đợi 60 giây rồi bấm lại.
* Hoặc cứ để nó lùi về dò từ khoá và nói như trên.

### Máy chủ trắng dữ liệu

```powershell
python manage.py seed_demo --reset
```

Xong trong vài giây. Chỉ xoá dữ liệu do chính lệnh này tạo ra, không đụng dữ
liệu khác.

### Giao diện lỗi trắng trang

Mở `F12` xem Console. Trường hợp hay gặp nhất là phiên đăng nhập hết hạn —
đăng xuất rồi đăng nhập lại. Có bản build tĩnh trong `web/dist/`, không phụ
thuộc `npm run dev`.

---

## 6. Không được làm khi đang demo

* **Không chạy `migrate` hay `seed_demo` giữa buổi.** Chuẩn bị từ tối hôm trước.
* **Không sửa cấu hình AI trên sân khấu.** Kiểm tra ở mục 2 rồi thôi.
* **Không mở `/admin/`** trừ khi có người hỏi thẳng về mô hình dữ liệu.
* **Không hứa tính năng chưa có.** Social Radar và RB Radar mới là kiến trúc,
  chưa cài đặt — nói đúng như vậy. Ban giám khảo ngân hàng nhớ rất kỹ những gì
  được hứa.
