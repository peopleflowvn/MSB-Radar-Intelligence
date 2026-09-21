# Kinh nghiệm triển khai các kênh tuyển dụng (TopCV, VietnamWorks, CareerViet, Việc Làm 24h, ITViec, Joboko & JobsGO)

Tài liệu này là bản bàn giao kỹ thuật sống, được cập nhật sau quá trình triển khai và vận hành thực tế
các kênh tuyển dụng (TopCV, VietnamWorks, CareerViet, Việc Làm 24h, ITViec, Joboko, JobsGO...). Mục tiêu là duy trì một lõi dùng chung, ghi lại khác biệt bắt buộc của
từng nguồn và để các provider liên tục học các cơ chế ổn định đã chứng minh ở nguồn khác. Nội dung không
chỉ mô tả cách tải file mà bao phủ toàn bộ vòng đời: đăng nhập, khám phá dữ liệu, chuẩn hóa, tải số lượng
lớn, phục hồi lỗi, database, báo cáo, UI/UX, kiểm thử và vận hành định kỳ.

> Phạm vi: chỉ làm việc với dữ liệu mà tài khoản nhà tuyển dụng được phép truy cập và các
> chức năng tải CV do nền tảng cung cấp. Không tự động vượt captcha, OTP, giới hạn truy cập
> hoặc cơ chế bảo vệ của website.

## 1. Kiến trúc hiện tại có thể tái sử dụng

Phần lớn hệ thống không phụ thuộc TopCV và không nên viết lại:

- `app/engine.py`: điều phối quét trang, tải song song, dừng an toàn, KPI và checkpoint.
- `app/db.py`: SQLite, khóa chống trùng theo `(source, cv_id)`, tìm kiếm và báo cáo.
- `app/web_api.py`: cầu nối giao diện, tiến độ thời gian thực, hẹn giờ và thông báo.
- `app/exporter.py`: xuất Excel, CSV và ZIP.
- `app/providers/base.py`: hợp đồng chung cho provider.
- Giao diện tải, tiếp tục, thử lại lỗi, quản lý ứng viên và báo cáo.

Mỗi nguồn mới chỉ nên được triển khai như một provider. Không sao chép toàn bộ engine hoặc tạo một luồng tải riêng,
vì điều đó sẽ làm checkpoint, KPI và xử lý lỗi lệch nhau giữa các nguồn.

## 2. Hợp đồng provider cần đáp ứng

Mỗi provider (`topcv.py`, `vietnamworks.py`, `careerviet.py` và nguồn tương lai) phải kế thừa `Provider`:

```python
class VietnamWorksProvider(Provider):
    key = "vietnamworks"
    display_name = "VietnamWorks"
    website = "vietnamworks.com"
    available = True

    def connect(self): ...
    def total_count(self): ...
    def peek_first_page(self): ...
    def iter_pages(self, start_page=1, end_page=None, reverse=False): ...
    def download(self, cv_id): ...
    def close(self): ...
```

Quy ước trả về:

- `connect()` chuẩn bị phiên hợp lệ, cache trang đầu, tổng hồ sơ và tổng số trang.
- `total_count()` trả tổng số **lượt ứng tuyển**, không phải số người duy nhất.
- `peek_first_page()` trả dữ liệu đã chuẩn hóa và không gọi mạng thêm.
- `iter_pages()` yield `(page_number, normalized_items)` và hỗ trợ tải xuôi/tải ngược.
- `download()` trả `(bytes, ".pdf")` khi thành công hoặc `(None, "lý do")` khi thất bại.
- Mất phiên phải ném `LoginError`; không đánh dấu hàng loạt CV còn lại là lỗi tải.

Chữ ký abstract `Provider.iter_pages(start_page=1, end_page=None, reverse=False)` đã thống nhất với engine. Provider
mới phải giữ đúng chữ ký này để tải theo phạm vi, tiếp tục và tải ngược hoạt động nhất quán.

## 3. Chuẩn dữ liệu chung

Mỗi hồ sơ VietnamWorks phải được chuyển thành dict với các khóa sau:

| Trường | Yêu cầu |
|---|---|
| `source` | Luôn là `vietnamworks` |
| `cv_id` | ID ổn định của **lượt ứng tuyển**, bắt buộc chuyển sang chuỗi |
| `fullname` | Họ tên ứng viên |
| `email`, `phone` | Để chuỗi rỗng nếu nền tảng không trả về |
| `position` | Tên vị trí/công việc ứng tuyển |
| `campaign_id` | ID tin tuyển dụng hoặc chiến dịch |
| `applied_at` | Chuỗi ngày hiển thị cho người dùng |
| `applied_ts` | `YYYY-MM-DD HH:MM:SS` dùng để lọc và sắp xếp |
| `apply_source` | Kênh ứng tuyển nếu có |
| `status` | Trạng thái hồ sơ trên VietnamWorks |
| `gender`, `birth_year`, `experience` | Thông tin có sẵn; không tự suy đoán |
| `address`, `city`, `last_company` | Thông tin có sẵn; không tự suy đoán |
| `labels`, `note`, `is_viewed` | Chuẩn hóa về chuỗi/số như TopCV |
| `cv_url` | URL mở đúng hồ sơ trong trang nhà tuyển dụng |

Không dùng email hoặc số điện thoại làm khóa chính. Một người có thể ứng tuyển nhiều vị trí;
mỗi lượt ứng tuyển phải là một dòng riêng.

## 4. Bài học về đăng nhập và phiên làm việc

### Những gì đã hiệu quả với TopCV

- Dùng Chrome profile riêng để giữ cookie và phiên đăng nhập giữa các lần chạy.
- Ưu tiên phiên người dùng đã đăng nhập sẵn; không bắt chờ đủ thời gian cố định.
- Đọc trạng thái đăng nhập theo vòng lặp ngắn và chạy tiếp ngay khi phiên hợp lệ.
- Khi gặp captcha/OTP, đưa Chrome ra trước và để người dùng hoàn tất thủ công.
- Khi token hết hạn, làm mới phiên một lần có kiểm soát.
- Một lỗi đăng nhập phải dừng cả lượt chạy, thay vì biến mọi CV thành bản ghi lỗi.

### Áp dụng cho VietnamWorks

1. Khảo sát xem phiên nằm trong cookie, localStorage, sessionStorage hay kết hợp nhiều nơi.
2. Xác định dấu hiệu đăng nhập thành công bằng một trang/API yêu cầu quyền nhà tuyển dụng.
3. Chỉ nhận token sau khi đã kiểm tra token đó thực sự gọi API thành công.
4. Không giả lập dấu hiệu webdriver hoặc tự vượt captcha. Nếu website yêu cầu xác minh,
   chuyển sang luồng chờ người dùng với thông báo rõ ràng.
5. Không ghi token, cookie, mật khẩu hoặc nội dung phản hồi nhạy cảm vào log.
6. Dùng khóa riêng khi thao tác Selenium vì một driver không an toàn cho nhiều luồng.

Nên bổ sung cấu hình theo từng nguồn thay vì dùng chung `email/password`. Ví dụ:

```json
{
  "providers": {
    "topcv": {"email": "", "enabled": true},
    "vietnamworks": {"email": "", "enabled": false}
  }
}
```

Mật khẩu vẫn là dữ liệu nhạy cảm; về lâu dài nên chuyển sang Windows Credential Manager
thay vì lưu dạng chữ thường trong JSON.

## 5. Bài học khảo sát website trước khi viết provider

Không đoán endpoint dựa trên URL giao diện. Thực hiện trên tài khoản thử nghiệm hợp lệ:

1. Mở DevTools → Network và lọc `Fetch/XHR`.
2. Tải trang danh sách ứng viên, đổi trang, lọc công việc và ghi nhận request tương ứng.
3. Bấm tải CV thủ công trên một hồ sơ thử nghiệm.
4. Ghi lại phương thức, endpoint, query/body, header bắt buộc, kiểu phân trang và kiểu phản hồi.
5. Kiểm tra phản hồi tải là bytes trực tiếp, redirect, JSON chứa URL tạm hay file từ CDN.
6. Đăng xuất/đăng nhập lại để xác định token nào thay đổi và thời gian hết hạn.
7. Thử một CV bị gỡ, một CV Word, một CV PDF và tên file có tiếng Việt.

Chỉ ghi cấu trúc kỹ thuật cần thiết vào tài liệu phát triển. Không commit HAR, token, cookie,
email, mật khẩu hoặc dữ liệu ứng viên thật.

## 6. Chiến lược gọi mạng

Mô hình đã chứng minh hiệu quả ở TopCV:

1. Gọi API bằng `requests.Session` để đạt tốc độ cao.
2. Đồng bộ User-Agent, cookie và header xác thực từ phiên Chrome.
3. Retry có giới hạn cho lỗi mạng tạm thời và HTTP `429/502/503/504`.
4. Nếu `401`, làm mới phiên; nếu vẫn lỗi thì ném `LoginError`.
5. Nếu API nhanh trả kết quả bất thường, thử lại trong phiên Chrome thật.
6. Giới hạn fallback Selenium vì tất cả lượt này phải đi qua một driver lock và sẽ chậm.

Đối với VietnamWorks, cần xác định riêng:

- API danh sách có dùng page number, cursor hay infinite scroll.
- Có CSRF token, device ID hoặc header tenant/company hay không.
- URL tải file có thời hạn và có cần cookie ở domain CDN hay không.
- Giới hạn tốc độ thực tế và tín hiệu bị throttle.
- Một tài khoản có nhiều công ty/workspace thì khóa dữ liệu có cần thêm company ID hay không.

Không hard-code User-Agent hoặc phiên bản Chrome nếu có thể lấy trực tiếp từ driver.

## 7. Nhận diện và lưu file CV

Bài học từ TopCV: HTTP 200 không đồng nghĩa phản hồi là file CV. Website có thể trả HTML,
JSON, trang đăng nhập hoặc thông báo lỗi với mã 200.

Quy trình khuyến nghị:

- Kiểm tra magic bytes của PDF, DOC, DOCX/ZIP, RTF, PNG và JPEG.
- Cho phép BOM/phần đệm hợp lệ trước header; PDF có thể có header trong 1.024 byte đầu.
- Dùng `Content-Type` và `Content-Disposition` làm tín hiệu bổ sung, không phải tín hiệu duy nhất.
- Nếu phản hồi là JSON, kiểm tra có URL tải tạm hay không rồi tải URL đó trong đúng phiên.
- Theo redirect có kiểm soát và giữ cookie/header cần thiết theo domain.
- Không lưu HTML/JSON thành `.pdf` chỉ vì tên file hoặc header nói đó là PDF.
- Log mã HTTP, Content-Type và loại lỗi; không log toàn bộ nội dung phản hồi.
- Ghi file tạm rồi đổi tên nguyên tử nếu file lớn hoặc mạng không ổn định.

Tên file cuối cùng vẫn đi qua `safe_filename()` và mẫu tên chung của engine.

## 8. Phân trang, CV mới và checkpoint

### Quy tắc đã rút ra

- Không ghi checkpoint ngay khi vừa đưa tác vụ vào thread pool.
- Chỉ xác nhận hoàn tất trang sau khi toàn bộ CV của trang đã xử lý xong.
- Dừng giữa trang thì checkpoint vẫn trỏ vào trang đó; chạy lại sẽ bỏ qua CV đã thành công.
- Checkpoint phải lưu `start_page`, `end_page`, `next_page`, `reverse` và `has_more`.
- Tải ngược phải thực sự yield `end_page → start_page`, không chỉ đổi nhãn giao diện.
- “Đã xử lý” là số item hoàn tất trong lượt hiện tại; KPI kho dữ liệu là nhóm số riêng.

### Những điểm đã phải kiểm chứng trên VietnamWorks

- Thứ tự mặc định có luôn là mới nhất trước không.
- Danh sách có thay đổi vị trí khi hồ sơ được xem/cập nhật trạng thái không.
- Page size có cố định không; trang cuối có trả chính xác tổng số không.
- Cursor có hết hạn giữa lượt tải không.
- ID trong danh sách là candidate ID hay application ID.

Nếu VietnamWorks dùng cursor, không ép cursor thành số trang. Khi đó cần mở rộng checkpoint để
lưu cursor và nhãn tiến độ riêng theo provider, hoặc tạo abstraction `PageCheckpoint` chung.

## 9. Hiệu năng và độ ổn định

- Cache trang đầu trong `connect()` để không gọi lại chỉ nhằm tính tổng.
- Nạp tập ID đã tải vào bộ nhớ một lần, không query SQLite cho từng CV.
- Dùng session HTTP riêng theo thread; không chia sẻ một `requests.Session` không khóa.
- Commit SQLite theo trang/lô, không commit từng dòng.
- Gom log và tiến độ rồi đẩy UI theo nhịp; không gọi JavaScript cho từng thông tin phụ.
- Bắt đầu với concurrency thấp (2–4), đo tỷ lệ lỗi rồi mới tăng.
- Có backoff và jitter cho lỗi tạm thời; tôn trọng `Retry-After` nếu server trả về.
- Tách lỗi phiên đăng nhập khỏi lỗi một CV cụ thể.
- Luôn đóng driver/session và giải phóng lock trong `finally`.

Chỉ tối ưu sau khi có số liệu: thời gian lấy trang, thời gian tải file, tỷ lệ fallback browser,
tỷ lệ HTTP theo nhóm và thời gian ghi cơ sở dữ liệu. Không ghi dữ liệu nhận dạng ứng viên vào
telemetry hoặc log chẩn đoán.

## 10. Phân loại lỗi cho người dùng

Provider nên trả thông báo có hành động tiếp theo:

| Nhóm | Ví dụ | Hành động |
|---|---|---|
| Mất phiên | 401, chuyển về login | Dừng lượt chạy, yêu cầu đăng nhập lại |
| Cần xác minh | captcha, OTP | Mở Chrome và chờ người dùng |
| Giới hạn tốc độ | 429 | Backoff, giảm concurrency |
| Lỗi tạm thời | timeout, 502/503/504 | Retry có giới hạn |
| CV không còn | 404/410 hoặc mã nghiệp vụ tương ứng | Đánh dấu lỗi rõ ràng, cho phép thử lại |
| Nội dung sai | HTML/JSON thay cho file | Fallback browser hoặc URL tải tạm |
| Không có quyền | 403 nghiệp vụ | Báo quyền tài khoản/công ty, không retry vô hạn |

Không dùng một thông báo “không tải được” cho mọi trường hợp. Log kỹ thuật có thể chi tiết hơn,
nhưng thông báo UI phải ngắn và chỉ rõ người dùng cần làm gì.

## 11. Trình tự triển khai đã áp dụng và nên tái sử dụng

### Giai đoạn 1 — Khảo sát có kiểm soát

- Dùng tài khoản test và hồ sơ test.
- Lập bảng endpoint, schema, phân trang, xác thực và tải file.
- Xác định application ID ổn định.
- Lưu mẫu phản hồi đã ẩn danh vào fixtures kiểm thử, không lưu dữ liệu thật.

### Giai đoạn 2 — Provider tối thiểu

- Viết `connect()`, `_normalize()`, `total_count()` và `iter_pages()`.
- Chạy chỉ một trang và chưa bật tải file hàng loạt.
- Kiểm tra mapping dữ liệu, thời gian và khóa chống trùng.

### Giai đoạn 3 — Tải file và phục hồi phiên

- Viết đường tải nhanh qua HTTP.
- Thêm nhận diện file, redirect/URL tạm và fallback Chrome.
- Thêm refresh phiên, `LoginError`, retry/backoff.
- Thử PDF, DOC/DOCX, file lỗi và phiên hết hạn.

### Giai đoạn 4 — Tích hợp engine

- Bật `available = True` và đăng ký provider thật trong `ALL_PROVIDERS`.
- Kiểm tra tải tất cả, chỉ CV mới, thử lại lỗi, dừng/tiếp tục và tải ngược.
- Kiểm tra checkpoint tách biệt theo `source=vietnamworks`.
- Kiểm tra báo cáo và xuất dữ liệu khi nhiều nguồn cùng tồn tại.

### Giai đoạn 5 — Pilot và phát hành

- Chạy pilot với phạm vi nhỏ và concurrency thấp.
- So sánh số hồ sơ/file với giao diện VietnamWorks.
- Theo dõi tỷ lệ lỗi, tốc độ và captcha trong vài chu kỳ hẹn giờ.
- Viết hướng dẫn người dùng và migration cấu hình theo nguồn.
- Chỉ build EXE khi kiểm thử trên mã nguồn đã đạt và có yêu cầu phát hành.

## 12. Bộ kiểm thử bắt buộc

### Unit test

- Chuẩn hóa đầy đủ và thiếu trường.
- Chuyển đổi múi giờ/ngày ứng tuyển.
- Nhận diện PDF, DOC, DOCX, BOM/phần đệm và nội dung HTML/JSON giả.
- Phân trang xuôi/ngược.
- Phân loại 401/403/404/429/5xx.
- Không rò token/cookie trong lỗi và log.

### Contract test với fixtures ẩn danh

- Schema danh sách đúng với parser.
- Tổng số và trang cuối đúng.
- URL tải trực tiếp, redirect hoặc JSON URL đều xử lý đúng.
- Hồ sơ cùng người nhưng application ID khác không bị gộp.

### Integration test

- Tải phạm vi 2–3 trang.
- Dừng giữa trang rồi tiếp tục bằng một lần bấm.
- Tải ngược từ trang cuối.
- Phiên hết hạn giữa lượt chạy.
- Hai nguồn cùng ghi vào một database mà không trùng khóa.
- Hẹn giờ dùng đúng provider và gửi thông báo đúng nguồn.

### Kiểm thử thủ công trước khi bật chính thức

- Đối chiếu ít nhất 20 hồ sơ giữa ứng dụng và VietnamWorks.
- Mở thử mọi loại file đã tải.
- Kiểm tra tên tiếng Việt và đường dẫn dài.
- Kiểm tra trên mạng công ty/proxy và máy không có quyền quản trị.
- Kiểm tra log không chứa thông tin xác thực hoặc nội dung CV.

## 13. Những thay đổi kiến trúc nên làm trước hoặc cùng lúc

1. Cập nhật chữ ký `Provider.iter_pages(start_page, end_page, reverse)` trong base class.
2. Không fallback về TopCV khi `get_provider()` nhận key lạ; nên báo lỗi rõ ràng.
3. Tách tài khoản/cấu hình theo provider.
4. Cho hẹn giờ chọn một hoặc nhiều nguồn, đồng thời tránh hai lượt chạy chồng nhau.
5. Mở rộng checkpoint nếu VietnamWorks dùng cursor thay vì số trang.
6. Thêm test provider contract dùng chung cho mọi nguồn.
7. Tách bộ nhận diện file khỏi `topcv.py` thành tiện ích dùng chung.

## 14. Tiêu chí hoàn thành VietnamWorks

Tích hợp chỉ được coi là hoàn thành khi:

- Đăng nhập mới, dùng lại phiên và hết phiên đều có hành vi đúng.
- Tổng số, phân trang và dữ liệu chuẩn hóa được đối chiếu với giao diện thật.
- Tải được các định dạng CV phổ biến và không lưu trang lỗi thành file.
- Tải tất cả, CV mới, tải ngược, dừng/tiếp tục và thử lại lỗi đều hoạt động.
- KPI, log, báo cáo, xuất dữ liệu và thông báo hiển thị đúng nguồn VietnamWorks.
- Không có token, cookie, mật khẩu, HAR hoặc dữ liệu ứng viên trong Git.
- Smoke test và bộ test VietnamWorks đều đạt.
- Pilot thực tế không bỏ sót, không tải trùng và không tạo lưu lượng quá mức.

Tài liệu này cần được cập nhật khi quá trình khảo sát VietnamWorks xác nhận schema, kiểu phân
trang và cơ chế tải file thực tế. Những chi tiết chưa xác minh không được biến thành giả định
hard-code trong provider.

## 15. Kết quả khảo sát VietnamWorks đã xác nhận

Khảo sát trực tiếp ngày 10/08/2026 trên trang
`https://employer.vietnamworks.com/job/v3/candidates` xác nhận:

- Truy cập headless bị trả 403; Chrome thật với profile riêng hoạt động bình thường.
- Đăng nhập tại `/v2/login/`; phiên được giữ bằng cookie, trong đó `ONB_JWT` là Bearer
  token dùng cho các API phía sau.
- `GET /api/my-job` trả một tập vị trí dùng cho giao diện candidates mới, **không phải toàn bộ lịch sử job**;
  chỉ giữ endpoint này làm nguồn tương thích dự phòng.
- Ứng viên không có danh sách phẳng toàn công ty. API GraphQL bắt buộc truyền `jobId` và
  `currentPage`; kích thước trang quan sát được là 20 hồ sơ.
- Danh sách ứng viên trả `applicationId`, email, thời gian ứng tuyển, trạng thái, kinh
  nghiệm, công ty gần nhất và quyền `canDownload`.
- `applicationId` là khóa đúng của lượt ứng tuyển và được dùng làm `cv_id` trong GenSync.
- API chi tiết `detailApplicationAction` trả điện thoại, địa chỉ, ngày sinh, giới tính,
  học vấn, kỹ năng và metadata file đính kèm.
- `attachmentPath` là URL HTTPS đầy đủ nhưng không phải lúc nào gọi nền cũng tương đương
  nút tải trên giao diện. Một số `view-attach` trả 404 cho `requests` dù bấm tay vẫn tải được;
  phải truyền Referer trang chi tiết, thử fetch trong Chrome và cuối cùng điều hướng/click
  tải thật trong Chrome vào thư mục tạm.
- Không được hiểu mọi `attachmentPath` 404 là hồ sơ đã mất. Ứng viên điền CV trực tiếp trên
  form VietnamWorks có `isAttached = 0`; đường dẫn attachment có thể vẫn tồn tại nhưng trả 404.
  Nút tải tay dùng route `/v2/application/download/{resumeId}/{appTypeSource}/{applicationId}/1`
  để VietnamWorks kết xuất hồ sơ hệ thống thành PDF. Provider phải ưu tiên route này cho CV
  không đính kèm và dùng nó làm fallback sau attachment 404/403/nội dung giả file.
- Khi tải CV mới, phải quét trang 1 của mọi job còn có thể nhận ứng viên và các job vừa hết hạn trước khi xét
  điều kiện dừng; job hết hạn lâu năm được lấy từ catalog khi tải toàn bộ nhưng không cần làm chậm mọi lịch quét mới.
- Mô hình triển khai được chọn là “trang ảo”: mỗi trang ảo tương ứng một cặp
  `(jobId, candidatePage)`. Trang 1 của tất cả job được ưu tiên trước, sau đó mới tới
  trang 2, 3... của từng job.

Các con số tổng job và ứng viên là dữ liệu biến động theo tài khoản nên không hard-code.
Provider phải hợp nhất `job-list/graphql` với `/api/my-job`, chống trùng theo `jobId` rồi tự dựng danh sách trang ảo.

## 16. Chuẩn hóa dữ liệu chi tiết vào database

Các trường trùng ý nghĩa được dùng chung giữa TopCV và VietnamWorks: họ tên, email, điện thoại, vị trí,
mã tin, ngày ứng tuyển, nguồn ứng tuyển, trạng thái, giới tính, năm sinh, kinh nghiệm, địa chỉ, thành phố,
công ty gần nhất, nhãn, ghi chú và link xem CV.

Các trường có giá trị nhưng schema cũ chưa có được bổ sung bằng migration không phá hủy dữ liệu:

- số năm kinh nghiệm, quận/huyện, chức danh gần nhất, cấp bậc, học vấn, lương mong muốn và kỹ năng;
- mã ứng viên, mã hồ sơ, loại hồ sơ, tên file gốc và MIME của file;
- `detail_loaded` để chỉ mở chi tiết một lần cho hồ sơ cũ, tránh gọi API thừa ở các lần quét sau;
- `source_payload` lưu bản chụp JSON chi tiết của nguồn trong database (không xuất Excel mặc định), giúp
  không làm mất thuộc tính đặc thù và có thể ánh xạ thêm về sau mà không phải tải lại ngay.

Muốn làm giàu toàn bộ dữ liệu đã tải từ phiên bản cũ, chạy **Tải tất cả** một lần. Các CV đã có file sẽ
không bị tải lại; provider chỉ mở chi tiết những bản ghi chưa có `detail_loaded`, cập nhật database rồi bỏ qua.

## 17. Gia cố cho tải số lượng lớn

Provider VietnamWorks đã áp dụng các cơ chế ổn định từ TopCV theo đúng API thực tế của VietnamWorks:

- `jobAppType`/`applyType` từ từng lượt ứng tuyển được truyền vào query chi tiết, không hard-code một loại hồ sơ;
- khi API chính trả 401, chỉ một worker làm mới cookie/Bearer từ Chrome, các worker khác dùng phiên mới;
- retry có jitter, tôn trọng `Retry-After` và dùng bộ ngắt lỗi chung để toàn bộ worker cùng giảm nhịp khi
  gặp 408/429/502/503/504 liên tiếp;
- giới hạn riêng VietnamWorks tối đa 4 worker dù cấu hình chung cao hơn;
- GraphQL, danh sách việc làm và file CV có đường fallback qua phiên Chrome thật khi HTTP trực tiếp bị chặn;
- Bearer chỉ được gửi tới domain VietnamWorks đã tin cậy, không chuyển sang CDN ngoài domain;
- phản hồi HTML/JSON giả file bị loại bỏ dù server khai báo Content-Type là PDF;
- file được ghi vào `.part` cùng thư mục rồi `os.replace()` sang tên cuối để tránh file dở khi ứng dụng dừng;
- cuối lượt **Tải tất cả**, hai trang mới nhất của mỗi vị trí được đối soát lại để bắt hồ sơ mới hoặc bị
  dịch chuyển trong lúc quét dài;
- lịch tự động cho phép chọn riêng TopCV hoặc VietnamWorks và kiểm tra đúng tài khoản của nguồn đã chọn.

Smoke test có mô phỏng refresh 401, fallback 403, `Retry-After`, giới hạn domain Bearer, `appType`, HTML giả
PDF và ánh xạ chi tiết. Trước phát hành EXE vẫn phải chạy pilot thực tế tăng dần 20 → 100 → toàn bộ hồ sơ,
vì giới hạn tốc độ và chính sách phía VietnamWorks có thể thay đổi mà không báo trước.

## 18. Khám phá đầy đủ job từ giao diện quản lý cũ

Khảo sát trực tiếp xác nhận trang `/v2/job/default/index` gọi
`https://ms.vietnamworks.com/job-list/graphql`, operation `search`, với các loại:

- `online`, `inactive`, `expiry7day`, `expired`, `draft`, `virtual-job`;
- tab hết hạn truyền thêm `time=5` như URL `expired?filters[time]=5`;
- `jobList.total` là tổng job của tab; `data[].extraInfo` trả `totalApplication`,
  `numOfApplications`, `unreadApplication`, trạng thái và quyền xem ứng viên;
- mỗi job có `jobId` ổn định và giao diện liên kết tới `/job/v3/candidates?jobId=...`.

Triển khai mới hợp nhất tất cả tab và nguồn `/api/my-job`, chống trùng theo `jobId`, chỉ tạo trang tải ứng viên
cho job có tổng hồ sơ lớn hơn 0. Job cổ 2011–2012 đã bị xóa ứng viên và hiện `0/0` vẫn được ghi dấu trong
catalog cục bộ để không phải kiểm tra sâu lặp lại, nhưng không tạo task tải CV.

Catalog job được lưu nguyên tử trong `%LOCALAPPDATA%/GenSyncRadar/vietnamworks_job_catalog.json` và không
chứa dữ liệu ứng viên. Lượt **Tải tất cả** xây catalog expired; các lượt **CV mới** luôn làm mới các tab đang
hoạt động và có thể thăm dò giới hạn metadata expired khi catalog chưa hoàn chỉnh, nhưng không tạo task ứng viên
cho lịch sử quá cũ. Nếu một trang metadata lỗi tạm thời, provider giữ catalog gần nhất và dùng `/api/my-job`
làm fallback thay vì làm mất job đã biết.

Lưu ý đã xác nhận từ log: dùng sai mã `virtualJob` có thể làm GraphQL trả khoảng 10.000 job công khai không
thuộc nhà tuyển dụng; tất cả sẽ báo `Invalid job`. Provider phải dùng đúng `virtual-job` và chủ động loại mọi
cache có `job_status=virtualJob`. Đây là ví dụ điển hình cho việc tổng lớn bất thường phải được xem là lỗi phạm
vi dữ liệu, không phải tín hiệu để tăng tốc độ tải.

Nếu máy chưa có catalog đầy đủ, **CV mới** chỉ thăm dò tối đa 5 trang expired gần nhất để lịch hẹn không vô tình
biến thành lượt quét hàng nghìn job. Giao diện log sẽ yêu cầu chạy **Tải tất cả** một lần; lượt này xây catalog đầy
đủ, sau đó các lần tải mới chỉ làm mới phần thay đổi. Đây là bước khởi tạo bắt buộc để vừa đầy đủ lịch sử vừa giữ
tốc độ ổn định cho lịch chạy định kỳ.

## 19. Bảo vệ hệ thống khi backup lịch sử lần đầu

Lượt backup lịch sử tự áp dụng cấu hình bảo vệ riêng, không phụ thuộc việc người dùng đã đặt hiệu năng cao cho TopCV:

- tối đa 2 CV tải đồng thời;
- mọi request metadata/chi tiết/file dùng chung một bộ điều tiết, cách nhau tối thiểu 300 ms;
- mỗi CV nghỉ tối thiểu 650 ms có jitter và mỗi trang nghỉ tối thiểu 900 ms;
- HTTP 429/5xx vẫn kích hoạt `Retry-After`, exponential backoff và circuit breaker dùng chung;
- chỉ xác nhận checkpoint sau khi toàn bộ CV trong trang đã hoàn tất, nên có thể dừng rồi tiếp tục an toàn.

Các giới hạn này áp dụng cho **Tải tất cả** và **Thử lại CV lỗi**. Chế độ **CV mới** vẫn được phép dùng tối đa 4
luồng và nhịp nhẹ hơn, vì sau khi catalog/database đã ổn định thì số hồ sơ thực sự cần tải rất nhỏ.

## 20. Thứ tự lịch sử, điểm dừng và chế độ hồ sơ mới

`createdOn` của VietnamWorks thực tế có thể là Unix epoch mili-giây, không phải chuỗi ISO. Vì vậy:

- chuyển epoch giây, epoch mili-giây và ISO về timestamp số trước khi sắp xếp;
- mọi lượt lịch sử bình thường đi từ job mới nhất đến cũ nhất;
- trang ứng viên trong mỗi job yêu cầu `orderType=DESC` theo `createdOn`;
- không sắp xếp trực tiếp bằng chuỗi và không dùng `datetime.fromisoformat()` cho epoch.

Trong backup lần đầu, nếu 30 job liên tiếp có tổng hồ sơ trong metadata nhưng API ứng viên trả `Invalid job`,
coi đó là biên dữ liệu VietnamWorks không còn giữ. Lưu timestamp của job đầu chuỗi làm `history_cutoff_ts`,
dừng lượt hiện tại và bỏ qua toàn bộ vùng cũ hơn ở các lần backup sau. Một job hợp lệ xuất hiện giữa chuỗi phải
đặt lại bộ đếm; chỉ tính lỗi ở trang ứng viên đầu tiên của từng job để không đếm một job nhiều lần.

Chế độ **Hồ sơ mới** không duyệt toàn bộ catalog lịch sử. Nó chỉ dựng task cho job đang hoạt động, sắp hết hạn,
đang ẩn/nguồn tương thích hoặc vừa hết hạn gần đây; tuy vậy phải quét hết các trang của phạm vi này. Không dùng
`tổng trên nguồn - tổng trong database` để dừng sớm vì database có thể chứa hồ sơ lịch sử ngoài phạm vi hiện tại.
Engine vẫn chống trùng bằng `(source, applicationId)`, nên chỉ hồ sơ chưa có mới được tải.

## 21. Chuẩn ngày giờ và dữ liệu có giá trị

Hai nguồn dùng chung hai cột với hai mục đích khác nhau:

- `applied_at`: chuỗi hiển thị `DD/MM/YYYY HH:MM`, giống TopCV;
- `applied_ts`: giờ Việt Nam UTC+7 dạng `YYYY-MM-DD HH:MM:SS`, dành cho lọc, báo cáo và sắp xếp.

VietnamWorks trả ISO UTC như `2026-08-10T07:32:47.000Z`; phải cộng đúng 7 giờ, không dựa vào timezone máy.
Migration khi mở database chuyển các bản ghi VietnamWorks cũ sang chuẩn hiển thị mới mà không thay đổi ý nghĩa
thời điểm. `applied_ts` luôn giữ định dạng có thể so sánh theo chuỗi và lập chỉ mục.

Các trường dùng chung đã ánh xạ gồm lương mong muốn, chức danh gần nhất, cấp bậc, học vấn, kỹ năng, kinh nghiệm,
công ty gần nhất, địa chỉ, trạng thái, nguồn chi tiết, mã candidate/resume và metadata file. `source_payload` giữ
JSON chi tiết gốc để không mất trường riêng của nền tảng, nhưng không xuất mặc định vì có dữ liệu cá nhân.

## 22. Cơ chế các provider học hỏi lẫn nhau

### Từ TopCV áp dụng sang VietnamWorks

- HTTP nhanh trước, Chrome fallback sau; nhận diện file bằng magic bytes thay vì tin HTTP 200/Content-Type.
- Thread-local session, driver lock, refresh phiên có khóa và `LoginError` dừng toàn lượt.
- Checkpoint sau khi hoàn tất trang, file `.part` + đổi tên nguyên tử và chống trùng trong database.
- Chuẩn ngày hiển thị riêng với timestamp nội bộ, cùng schema và engine/báo cáo.

### Từ VietnamWorks áp dụng ngược lại TopCV

- Các worker dùng chung một cửa sổ điều tiết request để không tạo burst dù mỗi thread có session riêng.
- Tôn trọng `Retry-After`, exponential backoff có jitter và circuit breaker dùng chung khi gặp 408/429/5xx.
- Phân biệt lỗi CV thật với khác biệt giữa request nền và thao tác tải trong Chrome.
- Theo dõi số lượng bất thường và phạm vi dữ liệu thay vì mặc nhiên tin metadata của endpoint.

TopCV hiện không cần catalog job hay ngưỡng 30 job vì API trả danh sách ứng viên phẳng theo trang, không phân
nhánh bắt buộc theo vị trí như VietnamWorks. Không nên sao chép cơ chế đặc thù này sang TopCV. Phần có lợi chung
là điều tiết/backoff đã được bổ sung vào TopCV; các lỗi 429/502/503/504 giờ làm chậm đồng bộ toàn bộ worker thay
vì từng worker tự retry và tiếp tục dồn tải lên máy chủ.

## 23. CareerViet: kết quả khảo sát và quyết định triển khai

CareerViet có cấu trúc gần TopCV hơn VietnamWorks: toàn bộ lượt ứng tuyển nằm trong một danh sách phẳng,
phân trang tại trang Quản lý hồ sơ. Vì vậy không dựng catalog job và không áp dụng ngưỡng job lịch sử như
VietnamWorks. Danh sách được đọc từ mới đến cũ để chế độ **Hồ sơ mới** sớm gặp ranh giới dữ liệu đã có.

Khóa chống trùng bắt buộc là `folder_resume_id`. Không dùng `resume_id` làm `cv_id`, vì cùng một hồ sơ cá nhân
có thể ứng tuyển nhiều việc làm. `resume_id`, `jobseeker_id` và `job_id` vẫn được giữ trong các cột dùng chung
`resume_id`, `candidate_id`, `campaign_id`.

Danh sách có sẵn email, kinh nghiệm, lương mong muốn, công việc/công ty gần nhất, học vấn, vị trí và trạng thái.
API chi tiết bổ sung điện thoại, địa chỉ, giới tính, kỹ năng và toàn bộ JSON gốc vào `source_payload`; nhờ đó
không mất trường riêng của CareerViet mà vẫn giữ schema báo cáo dùng chung.

Lần sao lưu đầu có thể gồm hàng chục nghìn lượt ứng tuyển. Provider giới hạn 2 worker, điều tiết chung request,
checkpoint từng trang, retry có backoff cho 408/429/502/503/504 và làm mới token khi gặp 401. Chế độ **Hồ sơ
mới** tối đa 4 worker nhưng vẫn có khoảng nghỉ. Tải từng PDF được chọn thay cho bulk export bất đồng bộ để mỗi
hồ sơ có trạng thái và retry độc lập.

Không lưu tài khoản, mật khẩu, token, cookie hoặc profile Chrome trong Git. Captcha/OTP (nếu có) do người dùng
hoàn tất trên Chrome; vòng chờ kiểm tra phiên mỗi 2 giây và chạy tiếp ngay khi đăng nhập thành công.

### Kinh nghiệm trao đổi giữa ba nguồn

- CareerViet kế thừa từ TopCV: feed phẳng mới nhất trước, cache trang đầu, magic-byte file và dừng sớm hồ sơ mới.
- CareerViet kế thừa từ VietnamWorks: thread-local session, refresh có khóa, điều tiết tải toàn cục và lưu payload gốc.
- TopCV/VietnamWorks tiếp tục dùng khóa nghiệp vụ là **lượt ứng tuyển**, không gộp nhầm người hoặc resume.
- Cơ chế danh mục job/30 job lỗi chỉ đúng với VietnamWorks; không sao chép sang feed phẳng TopCV/CareerViet.

## 24. Checklist khi thay đổi một provider

1. Kiểm tra thay đổi có nên đưa vào engine/base dùng chung hay chỉ thuộc provider đó.
2. Đối chiếu ít nhất một hồ sơ thành công, một hồ sơ không còn khả dụng và một phản hồi giả file.
3. Xác nhận ngày hiển thị, `applied_ts`, khóa chống trùng và toàn bộ trường chung trong database.
4. Kiểm tra request nhanh, browser fetch và thao tác Chrome thật theo đúng thứ tự fallback.
5. Mô phỏng 401, 403/404/422, 429 và 5xx; không retry vô hạn hoặc biến lỗi phiên thành lỗi hàng loạt.
6. Chạy unit test, provider contract và smoke test; không commit token, log, database, profile hay CV.

## 25. CareerViet: khởi động nhanh, phiên đăng nhập và phục hồi token

Trang quản lý hồ sơ CareerViet là ứng dụng Next.js nặng. Mở thẳng trang này chỉ để kiểm tra đăng nhập làm Chrome
khởi động chậm và dễ tạo cảm giác phần mềm bị treo. Cách đã chứng minh ổn định hơn:

1. Khởi động Chrome với profile riêng của CareerViet.
2. Mở endpoint cùng domain `/api/auth/employers/check`, vì endpoint nhẹ nhưng vẫn cho Chrome gửi cookie thật.
3. Đọc JSON ngay trong `document.body.innerText`, lấy access token và cookie từ chính phiên Chrome; không gọi lặp
   một request HTTP thứ hai nếu trình duyệt đã có kết quả hợp lệ.
4. Chỉ mở trang đăng nhập khi phiên không hợp lệ. Vòng chờ kiểm tra mỗi 2 giây và chạy tiếp ngay khi URL rời trang
   login hoặc cookie xác thực thay đổi; không bắt người dùng chờ đủ 5 phút.
5. Nếu có sẵn tài khoản cấu hình, đăng nhập bằng POST với `Origin` và `Referer` đúng; tuyệt đối không đưa tài khoản
   hoặc mật khẩu vào URL, lịch sử trình duyệt hay log.

Cookie trả về từ login/refresh phải được cài vào cả HTTP session và Chrome profile. Trước khi thêm cookie mới cần
xóa cookie cùng tên để tránh đồng thời tồn tại biến thể `careerviet.vn` và `.careerviet.vn`; Selenium có thể trả
cookie hết hạn sau cùng và vô tình ghi đè cookie mới. Mọi thay đổi token/cookie phải làm mới thread-local session.

Khi API nội bộ trả 401, chỉ một worker được refresh. Thứ tự phục hồi là:

- gọi refresh với `Origin`/`Referer` hợp lệ và đồng bộ `Set-Cookie`;
- đọc lại `/check` trong Chrome;
- kiểm tra token mới phải khác token vừa bị từ chối;
- nếu cookie nhìn có vẻ hợp lệ nhưng API vẫn bác token, đăng nhập lại đúng một lần;
- nếu vẫn thất bại, ném `LoginError` để dừng lượt chạy, không biến mọi CV còn lại thành lỗi tải.

Bài học chung: kiểm tra phiên bằng tài nguyên nhẹ nhất nhưng phải kiểm tra **quyền gọi API thật**, không chỉ nhìn URL,
cookie tồn tại hay trang giao diện đã render.

## 26. VietnamWorks: phân biệt file đính kèm và CV do hệ thống xuất

HTTP 404 từ `attachmentPath` không luôn có nghĩa hồ sơ đã bị xóa. VietnamWorks có hai loại hồ sơ tải được:

- ứng viên có file đính kèm: nút tải dùng đường dẫn attachment/CDN;
- ứng viên điền trực tiếp form VietnamWorks: không có file upload, nút tải tạo một bản PDF từ dữ liệu trong hệ thống.

Với loại thứ hai, website dùng tuyến `/v2/application/download/{resumeId}/{appTypeSource}/{applicationId}/1`.
Provider phải giữ đủ `resume_id`, application ID và `appTypeSource`, chuẩn hóa nguồn số như `1.0` thành `1`, rồi
URL-encode từng thành phần. Không được kết luận “không có CV” chỉ vì `isAttached=false` hoặc attachment trả 404.

Chuỗi fallback đúng cho mỗi URL là:

1. HTTP session nhanh với cookie/header đúng;
2. `fetch` trong Chrome thật;
3. điều hướng hoặc bấm nút tải trong Chrome với thư mục download tạm;
4. kiểm tra magic bytes trước khi chấp nhận file.

Nếu attachment 403/404, vẫn phải thử tuyến xuất CV hệ thống. Với hồ sơ không đính kèm, điều hướng thẳng export URL,
không tìm và bấm nhầm liên kết `view-attach`. File hệ thống thành công được ghi metadata tên file/MIME phù hợp. HTML,
JSON, trang login hay thông báo lỗi không được lưu giả thành PDF dù HTTP 200 hoặc Content-Type khai báo PDF.

Bài học áp dụng ngược cho các nguồn khác: trạng thái “không có file đính kèm” là thuộc tính của nguồn file, không
nhất thiết là trạng thái “không thể xuất hồ sơ”. Khi khảo sát provider mới phải kiểm tra cả nút download, preview,
print và export của website.

## 27. Chính sách điều tiết tải dùng chung cho mọi provider

Ngẫu nhiên hóa khoảng nghỉ được dùng để làm phẳng tải và tránh burst do nhiều worker, không phải để vượt captcha,
che giấu tự động hóa hay mô phỏng chuột/bàn phím. Chính sách nằm tại `app/providers/base.py` để provider hiện tại và
provider tương lai cùng kế thừa:

| Tầng điều tiết | Biên jitter hiện tại | Mục đích |
|---|---:|---|
| Khoảng cách request dùng chung | ±25% | Không để metadata, detail và file từ nhiều worker dồn cùng thời điểm |
| Sau mỗi CV | ±30% | Phân tán nhịp tải file |
| Sau mỗi trang | ±20% | Tránh nhịp chuyển trang cố định |

Jitter luôn có biên giới hạn. `Retry-After`, shared backoff và circuit breaker là lớp riêng và luôn được ưu tiên;
không dùng jitter để rút ngắn thời gian server yêu cầu chờ. Các worker có session riêng nhưng phải đặt chỗ qua một
`_next_request_at` dùng chung dưới lock, nếu không mỗi thread tự ngủ vẫn có thể thức dậy và tạo burst cùng lúc.

Giới hạn vận hành hiện tại:

| Provider | Tải tất cả / thử lại lỗi | Hồ sơ mới |
|---|---|---|
| TopCV | 2 worker; tối thiểu 600 ms/CV, 800 ms/trang, request cơ sở 250 ms | tối đa 4 worker; 250 ms/CV, 350 ms/trang, request 80 ms |
| VietnamWorks | 2 worker; 650 ms/CV, 900 ms/trang, request 300 ms | tối đa 4 worker; 250 ms/CV, 400 ms/trang, request 100 ms |
| CareerViet | 2 worker; 600 ms/CV, 800 ms/trang, request 250 ms | tối đa 4 worker; 250 ms/CV, 350 ms/trang, request 80 ms |

Các con số là điểm xuất phát bảo thủ, không phải cam kết cố định của nền tảng. Chỉ điều chỉnh sau khi đo tỷ lệ 429,
5xx, timeout, refresh phiên, fallback Chrome và thời gian xử lý. Backup lần đầu phải ưu tiên khả năng dừng/tiếp tục
và tính đúng dữ liệu hơn tốc độ đỉnh; lượt hồ sơ mới hằng ngày có thể nhanh hơn vì phạm vi nhỏ và chống trùng đã ổn định.

## 28. Dữ liệu lớn, database, báo cáo và UI/UX

Ba nguồn cùng ghi vào một schema, nhưng khóa duy nhất phải đại diện **lượt ứng tuyển**:

- TopCV: ID lượt ứng tuyển do TopCV cung cấp;
- VietnamWorks: application/entry ID, không dùng candidate ID;
- CareerViet: `folder_resume_id`, không dùng `resume_id`.

Những trường dùng chung phải map về cột chung trước: họ tên, email, điện thoại, vị trí, campaign/job, thời gian ứng
tuyển, trạng thái, nguồn, giới tính, năm sinh, kinh nghiệm, địa chỉ, công ty/chức danh gần nhất, học vấn, kỹ năng,
lương mong muốn và metadata file. Trường chưa có cột chung được bổ sung bằng migration không phá hủy dữ liệu;
`source_payload` giữ JSON gốc để không mất thuộc tính riêng và phục vụ ánh xạ về sau, nhưng không hiển thị/xuất mặc
định vì chứa dữ liệu cá nhân.

Thời gian phải có hai biểu diễn thống nhất:

- `applied_at`: `DD/MM/YYYY HH:MM` cho giao diện;
- `applied_ts`: `YYYY-MM-DD HH:MM:SS` theo UTC+7 cho lọc, sắp xếp, chỉ mục và báo cáo.

Không trộn chuỗi ISO, epoch và định dạng hiển thị trong cùng một cột. Mọi parser phải hỗ trợ ISO UTC, epoch giây,
epoch mili-giây và chuỗi nguồn; sau đó chuẩn hóa trước khi ghi DB.

Khi dữ liệu tăng lớn:

- phân trang ở database, không tải “full data” lên UI;
- giới hạn lựa chọn số dòng/trang, bỏ tùy chọn xem toàn bộ;
- lập chỉ mục cho source, position/campaign, applied timestamp, trạng thái và khóa chống trùng;
- dùng truy vấn aggregate cho KPI/báo cáo, không lấy toàn bộ dòng rồi tính bằng JavaScript;
- debounce tìm kiếm và hiển thị loading chuyên nghiệp nếu truy vấn chưa xong;
- batch log/progress theo nhịp để giao diện không bị nghẽn bởi từng sự kiện nhỏ;
- tổng ở menu là tổng database và độc lập với provider đang tải.

Báo cáo phải mặc định có “Tất cả nguồn”, chỉ hiển thị các kênh thực sự hỗ trợ, và bộ lọc nguồn/vị trí/thời gian chỉ
có hiệu lực sau nút **Áp dụng**. Trạng thái provider đang chạy không được âm thầm trở thành bộ lọc báo cáo. Các phễu
thời gian hữu ích gồm hôm nay, 7/30/90 ngày, tháng/quý/năm hiện tại và khoảng tùy chọn; tất cả phải dựa trên
`applied_ts` chuẩn hóa. Cần kiểm thử dữ liệu hỗn hợp cả ba nguồn, không chỉ database chỉ có TopCV.

## 29. Quy trình chuẩn để thêm nguồn tuyển dụng tiếp theo

### Khảo sát

1. Xác định mô hình dữ liệu là feed phẳng như TopCV/CareerViet hay catalog job như VietnamWorks.
2. Xác định khóa lượt ứng tuyển ổn định và phân biệt candidate, resume, application, job.
3. Quan sát Network khi đổi trang, mở chi tiết, tải file, export hồ sơ và refresh phiên.
4. Kiểm tra thứ tự mới/cũ, page/cursor, phạm vi job, tab ẩn/hết hạn và biên dữ liệu lịch sử.
5. Ghi fixtures đã ẩn danh; không commit HAR, CV thật, cookie, token hay tài khoản.

### Triển khai

1. Kế thừa `Provider`; tái dùng engine, DB, checkpoint, jitter và báo cáo chung.
2. Cache trang đầu trong `connect()`, chuẩn hóa item trước khi yield và giữ payload gốc.
3. Dùng HTTP nhanh trước, browser fetch sau, thao tác Chrome thật cuối cùng.
4. Dùng thread-local session; driver, refresh và bộ điều tiết phải có lock.
5. Phân loại rõ lỗi phiên, quyền, giới hạn tốc độ, lỗi tạm thời, hồ sơ không còn và nội dung giả file.
6. Chỉ checkpoint sau khi trang hoàn tất; file ghi `.part` rồi đổi tên nguyên tử.

### Kiểm thử và phát hành

1. Unit test parser, ngày giờ, jitter, magic bytes, khóa chống trùng và mọi nhánh fallback.
2. Contract test 401, 403, 404/410/422, 429, 5xx, `Retry-After`, token refresh và phiên hết hạn.
3. Pilot theo nấc nhỏ → vừa → toàn bộ; đối chiếu số ứng viên/file với giao diện nguồn.
4. Chạy smoke test và biên dịch toàn bộ mã trước khi commit.
5. Chỉ stage/push file nguồn và tài liệu cần thiết; không commit DB, log, CV, profile, credential hoặc build artifact.
6. Không tự động build EXE; chỉ build khi có yêu cầu phát hành rõ ràng.

## 31. Việc Làm 24h: Kết quả khảo sát, bài học thực tế và xử lý sự cố

### Đăng nhập và nhận diện Form SPA (Single Page Application)
- **Đặc điểm**: Giao diện Nhà tuyển dụng của Việc Làm 24h (`https://ntd.vieclam24h.vn`) xây dựng trên các framework UI hiện đại (React/Vue). Các ô nhập liệu Email và Mật khẩu **không có thuộc tính `name`** chuẩn (như `name="email"` hay `name="password"`).
- **Lỗi phát sinh**: Bộ điền form tự động truyền thống dựa vào `find_element(By.NAME, "email")` bị kẹt 100% thời gian, dẫn đến hết thời gian chờ (`_wait_login`) và báo lỗi đăng nhập.
- **Giải pháp**: Xây dựng cơ chế fallback đa lớp (Multi-Selector Fallback):
  1. Tìm theo `placeholder` (ví dụ `placeholder*="email"`, `placeholder*="mật khẩu"`, `placeholder*="Nhập email"`);
  2. Tìm theo `type` (ví dụ `input[type="email"]`, `input[type="password"]`);
  3. Tìm nút Đăng nhập bằng XPath text `//button[contains(text(),'Đăng nhập')]` thay vì phụ thuộc class CSS động.

### Xác thực phiên và khôi phục Cookie
- Phiên đăng nhập được duy trì qua Cookie `re_access_token` và URL bảng tin `https://ntd.vieclam24h.vn/bang-tin.html`.
- Khi khởi động Chrome với profile riêng (`vieclam24h_profile`), ưu tiên kiểm tra xem trình duyệt đã sẵn sàng ở trạng thái đã đăng nhập hay chưa (bằng cách kiểm tra URL và Cookie `re_access_token`). Nếu đã có phiên, bỏ qua hoàn toàn các bước tự động mở form/điền tài khoản để tối ưu thời gian khởi động.

### Bài học đồng bộ UI/UX khi thêm Provider mới
- **Tránh sót tuỳ chọn ở Frontend**: Khi thêm một nguồn mới vào hệ thống backend, bắt buộc phải rà soát và cập nhật đồng bộ các vị trí thẻ UI trên Frontend (`index.html` & `app.js`):
  1. Thẻ `<select id="report-source">` trong tab **Báo cáo** phải bổ sung `<option value="vieclam24h">Việc Làm 24h</option>`.
  2. Thẻ chọn nguồn trong tab **Tải CV** và bộ lọc tab **Ứng viên**.
- **Hiểu đúng báo cáo tổng hợp DB (DB Aggregation)**: Khi một cơ sở dữ liệu mới khởi tạo hoặc chỉ mới cào dữ liệu từ 1 nguồn (ví dụ chỉ có 264 CV từ Việc Làm 24h), báo cáo tổng quan "Tất cả nguồn" sẽ gom toàn bộ và trả về 100% số liệu nguồn đó. Đây là kết quả truy vấn chính xác của Database, không phải lỗi logic phần mềm.

## 32. Đánh giá ảnh hưởng và điều chỉnh cho các trang khác (TopCV, VietnamWorks, CareerViet)

Từ kinh nghiệm thực tế triển khai Việc Làm 24h, cần rà soát và điều chỉnh các provider còn lại theo các tiêu chí sau:

1. **Nâng cấp bộ Selector Đăng nhập linh hoạt cho TopCV, VietnamWorks, CareerViet**:
   - Các nền tảng tuyển dụng liên tục cập nhật giao diện frontend (chuyển sang Next.js, Vue, React) làm thay đổi hoặc mất thuộc tính `name` trên thẻ `<input>`.
   - **Hành động điều chỉnh**: Rà soát hàm `_do_login()` trong `topcv.py`, `vietnamworks.py`, và `careerviet.py`. Chuyển sang dùng mảng các Selector dự phòng linh hoạt (kết hợp `name`, `type`, và `placeholder` hỗ trợ cả Tiếng Việt và Tiếng Anh) tương tự như đã làm ở `vieclam24h.py`.

2. **Quy trình Checklist kiểm thử UI/UX bắt buộc khi thêm bất kỳ Provider mới nào**:
   - [ ] **Config**: Thêm biến email, password, profile_dir vào `AppConfig` (`app/config.py`).
   - [ ] **Provider**: Đã kế thừa `Provider`, có `key`, `display_name`, `connect()`, `iter_pages()`, `download()`.
   - [ ] **Tab Tải CV**: Thêm provider vào danh sách chọn nguồn tải chính.
   - [ ] **Tab Cấu hình**: Thêm form nhập Email/Password riêng cho provider (hoặc thiết kế lại tối ưu diện tích).
   - [ ] **Tab Ứng viên**: Thêm option nguồn vào dropdown lọc ứng viên.
   - [ ] **Tab Báo cáo**: Thêm option nguồn vào dropdown `<select id="report-source">`.

## 33. ITViec: Kết quả khảo sát, cơ chế phân trang và tải CV

### Khảo sát trực tiếp ngày 11/08/2026
- **Trang đăng nhập**: `https://itviec.com/customer/login`
  - Input Email: `id="customer_email"`, `placeholder="Email"`, class `form-control`.
  - Input Password: `id="customer_password"`, `placeholder="Password"`, class `form-control`.
  - Nút Đăng nhập: button class `ibtn ibtn-primary ibtn-lg w-100` với text `Sign in`.
- **Dấu hiệu nhận biết đã đăng nhập**:
  - Trang chuyển hướng về `https://itviec.com/customer/job-applications`.
  - Tiêu đề trang: `Applications | ITviec Customer Admin`.
  - Có logo và menu quản trị dành riêng cho Nhà tuyển dụng (Customer Header).
- **Cấu trúc danh sách ứng viên (Job Applications)**:
  - Dạng bảng phẳng (Flat List) liệt kê tất cả lượt ứng tuyển across jobs.
  - Các trường dữ liệu chính: Họ tên (Name), Nhãn kinh nghiệm (e.g., Experienced), Email, Số điện thoại, Vị trí ứng tuyển (Job), Thời điểm nộp (Submitted time dạng `DD-MM-YYYY HH:MM`), Data Consent, Recruitment Stage (Applied/Pass Screening/Interview...).
  - **Khóa duy nhất (`cv_id`)**: Chuỗi UUID đại diện cho `application_id` được trỏ trong link chi tiết (ví dụ `58239aa7-e5db-4585-9650-8be13bad5411`).
- **Phân trang**:
  - Hỗ trợ tham số URL phân trang dạng `?page=N` (ví dụ `/customer/job-applications?page=2`).
  - Hỗ trợ tham số số lượng hồ sơ trên 1 trang `per=N` (ví dụ `?page=1&per=100`).
- **Cơ chế Tải CV**:
  - URL tải trực tiếp từng CV: `/customer/job-applications/<application_id>/downloads`.
  - Hỗ trợ tải hàng loạt CV: `/customer/bulk-cv-downloads?from_tab=all`.
  - Hỗ trợ xuất danh sách ứng viên dạng Excel: `/customer/toggle-download-cvs`.

### Đánh giá kiến trúc triển khai cho ITViec
- ITViec có mô hình danh sách phẳng và phân trang theo số trang (`page=1, 2...`) rất tương đồng với TopCV và CareerViet.
- Không cần dựng Catalog Job như VietnamWorks.
- Đã có đầy đủ thông tin kỹ thuật để tiến hành xây dựng `ITViecProvider` (`app/providers/itviec.py`).

## 34. Những nguyên tắc không được đánh đổi

- Chỉ truy cập dữ liệu mà tài khoản nhà tuyển dụng được phép sử dụng.
- Không tự động vượt captcha/OTP, không sửa dấu hiệu trình duyệt để che giấu bot và không né giới hạn truy cập.
- Không coi tốc độ cao nhất là tiêu chí duy nhất; ưu tiên dữ liệu đúng, không trùng, có thể tiếp tục và không quá tải nguồn.
- Không tin duy nhất HTTP status, Content-Type, tổng metadata hoặc một endpoint; luôn kiểm tra nội dung và có đối soát.
- Không để một lỗi đăng nhập/phiên tạo hàng nghìn bản ghi tải lỗi.
- Không sao chép cơ chế đặc thù giữa provider nếu mô hình dữ liệu khác nhau.
- Mọi cải tiến có ích chung phải đưa về base/engine; khác biệt nghiệp vụ phải nằm trong provider.
- Tài liệu này phải được cập nhật cùng thay đổi kiến trúc để lần phát triển nguồn mới không lặp lại lỗi cũ.

## 35. Phạm vi tài khoản khi chống trùng và tải CV mới

Số hồ sơ trên website chỉ được so sánh với số bản ghi trong database của **cùng nguồn và cùng tài khoản**.
Không dùng tổng theo `source` cho chế độ “Chỉ CV mới”, vì một tài khoản khác có thể có số hồ sơ bằng hoặc nhỏ hơn
tài khoản cũ nhưng vẫn là toàn bộ dữ liệu mới đối với tài khoản đó.

- Khóa chống trùng là `(source, account, cv_id)`, không còn là `(source, cv_id)`.
- `count`, tập ID đã tải, tập ID đã ghi nhận, thử lại lỗi và kiểm tra file đều phải lọc theo tài khoản hiện hành.
- Checkpoint phải tách theo nguồn và mã băm tài khoản; không tiếp tục phạm vi trang của tài khoản cũ.
- Chrome profile phải tách theo nguồn và mã băm tài khoản để cookie tài khoản cũ không bị gán cho email cấu hình mới.
- Tên thư mục profile/checkpoint không chứa email dạng rõ; chỉ dùng mã băm ổn định.
- Báo cáo tổng hợp vẫn có thể cộng nhiều tài khoản, nhưng phải cho phép lọc theo cột `account`.
- Migration database cũ phải giữ nguyên dữ liệu và chuyển khóa chính không phá hủy. Bản ghi legacy chưa có
  `account` chỉ được backfill một lần khi nguồn chưa có bất kỳ tài khoản đã nhận diện nào.

Khi đổi tài khoản lần đầu sau nâng cấp, người dùng có thể phải đăng nhập lại do profile mới được tách riêng. Đây là
hành vi chủ đích để bảo đảm dữ liệu của hai tài khoản không bị trộn.

### Mở profile để thao tác thủ công

Tab Cấu hình cung cấp nút **Mở trình duyệt** riêng cho từng nguồn. Nút này mở Chrome thường bằng đúng profile của
nguồn và tài khoản đã lưu, không gắn WebDriver, để người dùng đăng nhập/logout, chỉnh thiết lập tài khoản hoặc quản lý
cookie/cache bằng chức năng chính thức của Chrome và website. Không mở profile thủ công trong lúc đang đồng bộ và
phải đóng cửa sổ đó trước khi bắt đầu tải CV để tránh hai tiến trình cùng khóa profile.

Ràng buộc này phải được thực thi ở cả UI và backend: đang đồng bộ thì từ chối nút mở trình duyệt; khi bắt đầu đồng bộ
mà phát hiện Chrome đang giữ profile, trả trạng thái yêu cầu xác nhận. Chỉ đóng các PID Chrome khớp chính xác đường
dẫn profile sau khi người dùng đồng ý; nếu hủy thì không đóng Chrome và không khởi động lượt đồng bộ.

Thao tác thật giúp duy trì cookie/phiên hợp lệ và xử lý captcha/OTP đúng quy trình, nhưng không được mô tả như cách
“nuôi uy tín”, giả lập hành vi hay né cơ chế bảo vệ của website. Không tự động tạo lịch sử duyệt web hoặc tương tác giả.



# 4. KINH NGHIỆM TRIỂN KHAI VỚI ITVIEC

## 4.1. Kiến trúc trang và Khó khăn cơ bản
ITViec là một kênh tuyển dụng tập trung mảng IT. Qua khảo sát thực tế trên tài khoản `tuyendung@tntalent.vn` (Role Employer), ITViec sử dụng kiến trúc trang (DOM) truyền thống cho phần hiển thị dữ liệu thay vì trả về JSON qua API. 
* **Cấu trúc dữ liệu dạng "Phẳng" (Flat feed)**: Tương tự Việc Làm 24h, ITViec gộp chung toàn bộ hồ sơ ứng tuyển từ mọi tin đăng vào một danh sách duy nhất tại `/customer/job-applications`. Điều này thuận lợi hơn TopCV/VietnamWorks (phải lặp qua từng tin tuyển dụng).
* **Không bọc API JSON rõ ràng**: Các dữ liệu ứng viên không được trả về gọn gàng bằng JSON qua XHR. Phải phân tích (parse) trực tiếp mã HTML để bóc tách thông tin.

## 4.2. Cấu trúc URL và Pagination
- **Đường dẫn danh sách ứng viên**: `https://itviec.com/customer/job-applications?page=N&per=100` (N là số trang, tối đa 100 CV một trang).
- **Trang chi tiết ứng viên**: `https://itviec.com/customer/job-applications/<application_id>` (với ID là một chuỗi UUID).
- **Endpoint tải CV gốc**: `https://itviec.com/customer/job-applications/<application_id>/downloads`. Điều hướng tới đây sẽ trực tiếp tải file về.

## 4.3. Bóc tách thông tin (Parsing HTML)
Vì phải bóc tách bằng DOM Parser từ HTML trả về nên có sự rủi ro nếu ITviec đổi giao diện. Phương án bóc tách an toàn (như đã chạy JS phân tích DOM thành công):
* **ID Ứng viên**: Lấy UUID từ link chi tiết ứng viên.
* **Họ tên**: Lấy trực tiếp từ textContent của thẻ `a` dẫn tới trang chi tiết ứng viên.
* **Vị trí (Job Title)**: Lấy từ thẻ `a` dẫn tới `/customer/jobs/`.
* **Email, SĐT, Ngày ứng tuyển**: Vì nằm lẫn trong text của row, dùng **Regex** quét text của toàn bộ thẻ row là cách "nồi đồng cối đá" nhất:
  * Email: `/[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}/`
  * SĐT: `/0\d{9,10}/`
  * Ngày ứng tuyển: `/\d{2}-\d{2}-\d{4} \d{2}:\d{2}/`

## 4.4. Kịch bản Đăng nhập (Login)
Sử dụng email/password qua `/customer/login`. Sau khi đăng nhập thành công, session/cookies sẽ được lưu vào Chrome Profile `itviec_profile`. Nhờ đó, Provider chỉ cần kiểm tra xem `https://itviec.com/customer/job-applications` có chuyển hướng về login hay không, nếu không thì phiên còn sống.

## Hoàn thiện vận hành phiên bản 2.4.0

- Mật khẩu của năm nhà cung cấp không còn được trả về giao diện hoặc ghi dạng rõ trong
  `cauhinh.json`. Ứng dụng mã hóa bằng Windows DPAPI và lưu trong LocalAppData của đúng
  tài khoản Windows. Khi nâng cấp, mật khẩu dạng rõ cũ được di chuyển tự động.
- Trang Cấu hình có một nút mở trình duyệt dùng chung kèm lựa chọn nguồn. Mỗi
  nguồn/tài khoản vẫn dùng profile riêng; không dùng chung một profile cho mọi trang vì
  logout, cookie lỗi hoặc profile lock của một trang sẽ ảnh hưởng các trang còn lại.
- Không cho mở profile thủ công khi đang đồng bộ. Nếu bắt đầu đồng bộ khi profile đang
  mở, giao diện phải xin xác nhận đóng; lịch tự động chỉ bỏ qua chu kỳ và thông báo,
  tuyệt đối không tự đóng phiên người dùng.
- Lịch chạy hỗ trợ đủ TopCV, VietnamWorks, CareerViet, Việc Làm 24h và ITViec. Kiểm tra
  cấu hình thực hiện theo nguồn được chọn, không còn bắt buộc TopCV cho toàn ứng dụng.
- Database ghi `schema_version`, chạy `PRAGMA quick_check`, và tạo bản sao
  `.pre-schema-v2.bak` trước migration khóa tài khoản. Trang Cấu hình có kiểm tra sức
  khỏe, sao lưu chủ động, và xóa dữ liệu cá nhân theo nguồn/tài khoản/khoảng ngày với
  câu xác nhận bắt buộc.
- File cấu hình được ghi nguyên tử và có `.bak` để phục hồi. Dependency runtime được
  khóa phiên bản; bộ kiểm tra chất lượng nằm tại `scripts/quality_check.ps1`.

Hai quyết định phạm vi hiện tại: vẫn giữ SQLite tại vị trí do người dùng cấu hình (kể
cả Google Drive), và không tự gán tài khoản cho dữ liệu được nhập từ Excel cũ.

### SQLite trong thư mục đồng bộ cloud

Khi database nằm trong Google Drive/OneDrive/Dropbox, không dùng WAL. Ba file DB,
`-wal` và `-shm` có thể được dịch vụ cloud đồng bộ ở những thời điểm khác nhau, khiến
kết nối thứ hai báo `database disk image is malformed` dù `quick_check` của DB chính
vẫn tốt. MSB Radar Edge dùng journal `DELETE` và `synchronous=FULL` cho đường dẫn cloud;
đường dẫn ổ cứng thông thường tiếp tục dùng WAL. Việc đổi journal cần đóng toàn bộ phiên
ứng dụng trước rồi mở lại. Lỗi mở DB trong worker phải được trả về UI, không để thread
chết làm giao diện mắc kẹt ở trạng thái đang tải.

Ngoài journal, phải tắt `mmap` trên filesystem cloud và đóng connection cache của giao
diện trước khi engine mở connection ghi. `quick_check` chạy độc lập không đủ chứng minh
hai connection đồng thời đang nhìn cùng một ảnh nhất quán của file Google Drive.

Đóng connection trước khi bắt đầu vẫn chưa đủ: mọi API được webview poll định kỳ như
`get_stats()` và `get_checkpoint()` cũng phải trả snapshot RAM trong suốt lượt tải. Nếu
một API lén mở lại connection đọc, journal `DELETE` có thể giữ shared lock đúng lúc
worker commit; nhiều worker với timeout dài sẽ khuếch đại một xung đột ngắn thành hàng
chục phút. API cần cờ sở hữu độc quyền để chặn cả connection cache còn sẵn, đồng thời
cập nhật KPI realtime từ event ứng viên đã upsert thay vì query lại file cloud.

### Form đăng nhập VietnamWorks

Nút submit của trang đăng nhập có thể vẫn `disabled` sau Selenium `send_keys` nếu state
validation phía client chưa nhận đủ sự kiện. Sau khi điền phải phát `input`, `change`,
`blur`, chờ nút vừa hiển thị vừa enabled rồi mới click. Nếu form đổi hoặc vẫn disabled,
không cưỡng ép click và không kết thúc lượt chạy: chuyển sang chờ người dùng đăng nhập/
xác minh thủ công trên Chrome, sau đó tự đọc cookie và chạy tiếp.

### Đọc danh sách ứng viên trong lúc đồng bộ

Với DB trên cloud, không mở lại connection SQLite từ tab Dữ liệu ứng viên khi engine
đang ghi. API trả snapshot trang đã cache và đánh dấu `stale`; giao diện thông báo sẽ cập
nhật sau khi đồng bộ xong. Danh sách Ẩn/Hiện Cột phải bao phủ toàn bộ `EXPORT_COLUMNS`,
nhưng chỉ các trường vận hành quan trọng được chọn mặc định để bảng vẫn gọn và nhanh.

### Cảnh báo và lịch sử ứng tuyển

Nhận diện một người bằng email đã chuẩn hóa hoặc số điện thoại chỉ giữ chữ số, sau đó
tổng hợp số lần xuất hiện, các vị trí, nguồn và lịch sử ứng tuyển trên mọi provider.
Cảnh báo bổ sung gồm thiếu thông tin liên hệ và CV chưa có file/tải lỗi. Bảng chỉ hiển
thị nhãn ngắn như `🔁 3 lần`, `Thiếu LH`, `Lỗi CV`; click để xem đầy đủ. Excel/CSV phải
ghi toàn bộ nội dung chi tiết vào cột `Cảnh báo ứng viên`, không chỉ ghi nhãn ngắn.

### Trải nghiệm lọc Dữ liệu ứng viên

Tìm kiếm nhanh nằm thành hàng riêng và dò trên toàn bộ trường chuẩn hóa/nội bộ, không
chỉ tên, email, điện thoại và vị trí. Các điều kiện chi tiết nằm ở hàng dưới. Tài khoản
là dropdown lấy từ dữ liệu thật, có số bản ghi và thu hẹp theo Nguồn đang chọn. Sau mỗi
lần lọc phải hiện tổng số kết quả, phạm vi đang áp dụng và lưu ý hữu ích (snapshot khi
đồng bộ, không có kết quả, số cảnh báo trên trang, phạm vi tìm kiếm toàn trường).
Phần kết quả còn phải phân rã toàn bộ tập lọc theo từng kênh và từng năm ứng tuyển;
không được thống kê chỉ trên trang phân trang hiện tại. Ngày thiếu/không chuẩn gom vào
`Không rõ năm` để tổng các nhóm luôn khớp tổng kết quả.

### Cập nhật gần real-time khi đồng bộ

Engine phát bản ghi vừa xử lý qua callback bộ nhớ; `web_api` gom lô cùng nhịp UI và
cập nhật snapshot trang đầu, tổng kết quả, thống kê nguồn/năm mà không mở connection
SQLite thứ hai. Webview nhận batch khoảng dưới một giây và render lại nếu đang ở trang
đầu, sắp xếp ngày mới nhất. Bộ lọc được kiểm tra trên payload trong RAM. Trang khác hoặc
kiểu sắp xếp khác chỉ nhận ghi chú tiến độ; khi lượt chạy kết thúc luôn đọc lại DB để
đối chiếu chính xác tuyệt đối.

### Multi-filter, tìm kiếm thông minh và tải file CV

Nguồn và tài khoản nhận danh sách nhiều giá trị, sinh SQL `IN` có placeholder thay vì
ghép chuỗi. Tìm kiếm nhanh dùng FTS5 `unicode61 remove_diacritics=2`, ghép các token bằng
AND và prefix, vì vậy `nguyen van` tìm được `Nguyễn Văn` mà không quét `LIKE` trên hơn
40 cột. Chỉ mục được dựng một lần và trigger tự cập nhật theo candidates. Nút Tải CV
không dựa vào thuộc tính `download` của data URL trong WebView; gọi backend mở Save As
và sao chép file gốc. Modal cảnh báo dùng từng thẻ màu/icon theo nhóm lặp, lịch sử,
liên hệ và lỗi file; lịch sử dài phải ngắt dòng.

Hai bộ lọc nhiều lựa chọn phải được render thành dropdown nổi có checkbox, không dùng
`select multiple` dạng hộp lớn vì làm vỡ lưới điều kiện. Checkbox đầu bảng chỉ chọn trang hiện tại;
checkbox từng dòng được lưu theo khóa ghép `source + account + cv_id`, và khi có lựa chọn thì thao tác
xuất chỉ lấy đúng các dòng đã tích. Modal chi tiết dùng chung định nghĩa trường với Ẩn/Hiện cột:
các cột đang bật xuất hiện trước, trường bổ sung nằm trong vùng mở rộng, riêng cảnh báo luôn hiển thị
đầy đủ ở đầu modal.

Tìm kiếm nhanh hỗ trợ Boolean Search với toán tử viết hoa `AND`, `OR`, `NOT` và cụm từ chính xác
trong dấu ngoặc kép; nhiều từ không ghi toán tử vẫn mặc định là `AND`. Cú pháp được biên dịch thành
FTS5 an toàn thay vì đưa nguyên chuỗi người dùng vào `MATCH`. Lịch sử ứng tuyển trong cảnh báo phải
được parse theo ngày thực, sắp mới nhất trước và đánh số. Modal CV nằm trên modal chi tiết; mở CV
không đóng chi tiết để khi tắt CV người dùng trở lại đúng hồ sơ đang xem.

Khi một người ứng tuyển nhiều lần, payload cảnh báo phải kèm lịch sử có cấu trúc của từng lần
(`source`, `account`, `cv_id`, ngày, vị trí, `filename`, trạng thái tải), không chỉ một chuỗi mô tả.
Chi tiết ứng viên và modal cảnh báo dùng danh sách này để mở đúng từng file CV; lần chưa có file phải
hiển thị rõ thay vì tạo nút chết. Khu vực tìm kiếm dùng một hàng input/nút riêng, lưới điều kiện có
chiều cao control thống nhất và hàng hành động riêng. Typography ưu tiên font hệ thống Segoe UI để
chữ ổn định, sắc nét trên Windows và không phụ thuộc việc tải Google Fonts.

### Báo cáo đa chiều

Bộ lọc Báo cáo dùng cùng dropdown checkbox với Dữ liệu ứng viên cho Nguồn và Tài khoản; Vị trí
tuyển dụng còn có tìm kiếm không dấu trong dropdown và cho chọn nhiều. Tất cả truy vấn thống kê phải
nhận danh sách bằng SQL `IN`, không chỉ lọc bảng nhưng để KPI/biểu đồ dùng phạm vi khác nhau.

KPI ứng viên sau lọc trùng là số nhóm liên thông qua email hoặc điện thoại chuẩn hóa; cách nối nhóm
này xử lý được cả trường hợp một hồ sơ có email và điện thoại nhưng hồ sơ khác chỉ có một trong hai.
Hiệu quả kênh phải phân rã số lượng/tỷ lệ theo tài khoản trong từng nguồn. Xu hướng trả chuỗi Tổng và
chuỗi riêng từng nguồn trên cùng trục thời gian. Không hiển thị biểu đồ loại hồ sơ và trạng thái tuyển
dụng khi chúng không giúp quyết định vận hành.

### Cấu hình đa tài khoản và hàng đợi lịch

Tài khoản là thực thể riêng gồm `id`, nguồn, email, tên gợi nhớ và trạng thái bật/tắt; mật khẩu từng
tài khoản lưu bằng DPAPI với khóa `account:<id>`, không nằm trong JSON. Cấu hình một tài khoản/kênh
cũ được tự chuyển sang danh sách khi đọc file. Runtime tạo bản cấu hình tương thích cho từng tài khoản
để không phải sửa contract của từng provider; profile tiếp tục được tách bằng hash email.

Một lượt tải theo nguồn tạo hàng đợi các tài khoản đang bật và chạy tuần tự, tổng hợp kết quả cuối
cùng. Trước khi chạy phải kiểm tra tất cả profile trong hàng đợi và chỉ đóng khi người dùng xác nhận.
Lịch tự động nhận nhiều nguồn, chạy lần lượt từng nguồn; trong mỗi nguồn lại lần lượt từng tài khoản.
Cách này tránh nhiều Chrome tranh tài nguyên, SQLite có nhiều writer và các website nhận lưu lượng
đăng nhập/tải đồng thời bất thường.

### Lock SQLite trong lượt backup dài

Không giữ transaction SQLite mở trong lúc các worker còn tải mạng. Sau khi khởi tạo/migration xong,
connection chạy autocommit để mỗi `upsert` và mỗi khóa checkpoint là transaction rất ngắn; đặc biệt
quan trọng với journal `DELETE` trên Google Drive. Ghi dữ liệu và checkpoint retry có backoff khi gặp
`database is locked`, nhưng có giới hạn để không treo vô hạn. Nếu phép đọc tổng cuối lượt thất bại,
kết quả dùng `stored_done` đã cập nhật realtime thay vì báo 0 giả; không cộng thêm `new` vì các CV mới
đã nằm trong `stored_done`, nếu cộng sẽ đếm đôi. Chỉ tăng bộ đếm CV mới
sau khi upsert thành công, vì vậy khi chạy lại có thể bỏ qua phần đã ghi và phục hồi phần còn thiếu.

Checkpoint của một trang phải ghi tất cả khóa trong một transaction, không tạo tám
transaction liên tiếp. Lỗi checkpoint do cloud bận không được hủy cả lượt: giữ checkpoint
cũ để lần **Tiếp tục** quét lại trang an toàn. Ngược lại, nếu ghi ứng viên vẫn thất bại sau
giới hạn retry, engine chỉ báo một lỗi và dừng ở trang chưa xác nhận, không để các worker
tiếp tục tạo hàng trăm lỗi. File CV đã đổi tên nguyên tử nhưng chưa kịp upsert được nhận
lại ở lần chạy sau khi bytes trùng khớp, tránh lưu thêm bản sao.

### Lịch tự động độc lập và trạng thái dữ liệu

Không dùng một bộ nguồn/chế độ/chu kỳ chung cho toàn ứng dụng. Mỗi lịch là một thực thể có `id`, tên,
nguồn, phạm vi tài khoản, chế độ, thời điểm bắt đầu, chu kỳ, trạng thái bật/tắt và kết quả lần chạy cuối.
Các lịch đến hạn được đưa vào một hàng đợi duy nhất; nguồn và tài khoản trong từng lịch cũng chạy tuần
tự để không tranh Chrome profile hoặc SQLite. Không chọn tài khoản trong lịch có nghĩa là dùng toàn bộ
tài khoản đang bật thuộc các nguồn đã chọn. Chu kỳ tối thiểu 15 phút để tránh tạo lưu lượng bất thường.

Khối sức khỏe dữ liệu chỉ nên tự kiểm tra và nêu việc người dùng cần xử lý: database lỗi, dung lượng thấp,
chưa có backup hoặc Chrome profile còn mở. Các thao tác kỹ thuật như kiểm tra thủ công, sao lưu và xóa
dữ liệu đặt trong vùng Bảo trì nâng cao, không chiếm diện tích của luồng cấu hình hằng ngày.

### Thống kê giao diện trong lúc đồng bộ

Badge tổng hồ sơ trên menu phải dùng tổng snapshot đầu lượt cộng số bản ghi `is_new` nhận qua hàng đợi
UI, rồi đối soát lại database khi lượt tải kết thúc. Không gọi lại truy vấn tổng chỉ để tạo cảm giác
real-time. Tổng trong Dữ liệu ứng viên có thể nhỏ hơn badge khi người dùng đang áp dụng bộ lọc; khi bộ
lọc mặc định, hai số phải khớp.

Báo cáo không chạy chuỗi truy vấn tổng hợp trong lúc engine đang ghi CV. Nếu đã có snapshot đúng bộ lọc
thì hiển thị snapshot kèm nhãn dữ liệu gần nhất; nếu chưa có thì kết thúc loading ngay và báo sẽ tổng hợp
sau lượt tải. Khi tải xong, báo cáo đang mở được làm mới tự động.

Dropdown nhiều lựa chọn có nội dung dài phải khóa cuộn theo chiều dọc, không tạo thanh cuộn ngang;
checkbox giữ kích thước cố định và nhãn được xuống dòng từ đầu. Bộ lọc Báo cáo chỉ giữ các chiều có ý
nghĩa chung giữa các nhà cung cấp: nguồn, tài khoản, vị trí và thời gian; bốn điều kiện nằm cùng một hàng
trên màn hình rộng. Không đưa “Loại hồ sơ” mang tính riêng của một nguồn vào bộ lọc chung.

### Phục hồi CV tải lỗi theo đúng định danh

Chế độ tải lại lỗi lấy đúng các bản ghi chưa ở trạng thái `Đã tải` theo nguồn và tài khoản, không quét
lại danh sách. Sau lần tải bằng dữ liệu cũ thất bại, engine chỉ thử lần hai khi provider có
`refresh_failed_item(item)` an toàn theo đúng định danh. VietnamWorks tải lại chi tiết bằng
`application_id`; CareerViet dùng `resume_id` và `folder_resume_id`. TopCV và ITViec vốn tải trực tiếp
bằng `cv_id`, có refresh phiên/fallback trình duyệt trong chính hàm tải. Provider không có đường tra cứu
đích danh phải trả `False`; tuyệt đối không tự quét toàn bộ lịch sử dưới tên gọi “tải lại lỗi”. Log cần
phân biệt rõ bước làm mới link và giữ cả nguyên nhân mới nhất lẫn lỗi link cũ khi lần hai vẫn thất bại.

### Thiết kế dữ liệu hướng tới một triệu hồ sơ

Bảng `candidates` là bảng lõi ổn định, không tiếp tục thêm cột cho mỗi phiên bản CV parser. Kết quả
parser/AI/đánh giá được lưu tại `candidate_extensions` theo khóa hồ sơ + `namespace` +
`schema_version`, payload JSON và thời điểm cập nhật. Một ứng viên có thể đồng thời mang nhiều namespace
(`cv_parser`, `ranking`, `screening`...) mà không làm bảng lõi rộng thêm hoặc buộc migration toàn bộ.

Các đường xuất CSV/XLSX phải dùng `iter_query()`/`fetchmany()` theo batch và OpenPyXL `write_only`; không
`fetchall()` rồi nhân đôi thành danh sách dict. Cảnh báo ứng viên được tính từng batch 300 dòng để giới
hạn số biến SQL và đỉnh RAM. Không cho export đồng thời với lượt đồng bộ. ZIP kèm file là ngoại lệ cần
duyệt file vật lý và hiện vẫn dành cho tập đã lọc/chọn hợp lý, không phải phương tiện sao lưu một triệu CV.

Workload tải lại lỗi dùng index ghép `(source, account, dl_status, applied_ts)`. Báo cáo cùng bộ lọc được
cache ngắn 30 giây và cache bị xóa sau lượt đồng bộ; trong lúc đồng bộ chỉ trả snapshot. Các index cần
được chọn theo truy vấn thực tế, không thêm index cho mọi trường parser vì sẽ làm mỗi lần ghi CV chậm và
database phình lớn.

### Cấu hình vận hành thông minh

“Trạng thái dữ liệu” là bảng điều khiển hành động, không phải nơi đổ thông số kỹ thuật. Nó hiển thị số
hồ sơ, kích thước database, số CV lỗi, tuổi backup; chỉ tạo danh sách “Việc nên làm” khi backup quá 7
ngày/chưa có, dung lượng thấp, có CV lỗi hoặc Chrome profile đang mở. Kiểm tra sâu và backup phải tự
hoãn khi engine đang đồng bộ để không tranh database. Sau lượt tải, trạng thái được làm mới tự động.

Hẹn giờ có một công tắc vận hành toàn cục có hiệu lực ngay và nhiều lịch độc lập. Mỗi thẻ lịch phải cho
thấy kênh, số tài khoản thực tế, chế độ, chu kỳ, lần chạy tiếp/theo cuối, lỗi cấu hình; hỗ trợ bật/tắt
riêng và “Chạy ngay”. Form dùng dropdown checkbox giống phần lọc, preset chu kỳ và validation trước khi
lưu. Phạm vi lịch chồng nhau không chạy song song: giao diện cảnh báo và scheduler xếp hàng. Trạng thái
“Hoàn tất” chỉ được ghi sau khi nhận kết quả lượt tải, kèm số lỗi thật. Khi không còn lịch bật, scheduler
tự dừng thay vì giữ một thread chờ vô hạn.

## 36. Joboko (`em-vn.joboko.com`): khảo sát thật và toàn bộ chạy qua trình duyệt

Khảo sát trực tiếp 2026-09 trên tài khoản `tuyendungnoibo@msb.com.vn` cho thấy bản viết đầu tiên (suy
đoán selector từ trang công khai, không đăng nhập được) sai gần như toàn bộ — chỉ đúng sau khi tự đăng
nhập và khảo sát trực tiếp trang thật. Bài học quy trình: **không bao giờ suy đoán cấu trúc site cần
đăng nhập chỉ từ trang công khai hoặc từ kinh nghiệm ở nguồn khác**; phải tự đăng nhập bằng tài khoản
thật, dùng script khảo sát ném-đi (không phải file trong `app/`) để đọc DOM thật trước khi viết provider.

- **Danh sách `/cv`** = ứng viên đã ứng tuyển vào tin của MSB (đúng mô hình ATS như các nguồn khác,
  không phải kho tìm kiếm tính điểm).
- **Toàn bộ chạy qua trình duyệt, không dùng được `requests`**: phân trang là JavaScript thuần
  (`?page=N` bị lờ đi hoàn toàn, phải bấm `li.page-item` trong DOM); nút "Tải CV" cũng chỉ là JavaScript
  (`a.btn-download-file`, `href="#"`) — không có URL tải thật để gọi trực tiếp, phải bấm nút rồi bắt file
  bằng CDP `Page.setDownloadBehavior`. Vì vậy `concurrency_limit() == 1` (một trình duyệt xử lý tuần tự).
- **Chạy ẩn được** (`joboko_headless` mặc định `True`) — khác JobsGO, Cloudflare/anti-bot không chặn
  headless Chrome ở Joboko. Tự bật cửa sổ khi phát hiện cần đăng nhập lại, trừ khi người dùng ép ẩn
  toàn cục.
- **Điểm chưa tối ưu đã biết**: mỗi khi `download()` điều hướng sang trang chi tiết rồi quay lại danh
  sách, trang danh sách RESET về trang 1 (site không nhớ vị trí phân trang qua URL/session) —
  `iter_pages` phải bấm lại từ đầu mỗi lần, tốn O(số trang²) lượt bấm cho một lượt quét đầy đủ. Với quy
  mô hiện tại (~90 hồ sơ / 9 trang) không đáng kể; nếu tài khoản phát sinh hàng nghìn hồ sơ nên tối ưu
  lại cách quay về danh sách (ví dụ mở tab mới cho trang chi tiết thay vì điều hướng đè).
- **Giả định chưa kiểm chứng độc lập**: danh sách được cho là sắp mới nhất trước (dựa vào mã hồ sơ giảm
  dần theo thứ tự xuất hiện — bằng chứng gián tiếp, không phải xác nhận trực tiếp từ tài liệu/API). Chế
  độ "Chỉ tải CV mới" dựa vào giả định này để dừng sớm; nếu sau này Joboko không sắp mới-nhất-trước, chế
  độ này có thể bỏ sót hồ sơ mới nằm không phải ở đầu danh sách.

## 37. JobsGO (`employer.jobsgo.vn`): Cloudflare Bot Management và mô hình lai trình duyệt + HTTP

Khảo sát trực tiếp 2026-09 trên tài khoản `tuyendung@msb.com.vn`.

- **Trang đăng nhập thật là `/site/login`** (KHÔNG phải `/login` — bản đầu đoán sai, người dùng phát
  hiện lại trên môi trường thật mới sửa đúng `LOGIN_URL` trong `jobsgo.py`). Bài học: dù đã khảo sát kỹ,
  vẫn nên xác nhận URL đăng nhập bằng cách quan sát trực tiếp thanh địa chỉ khi bấm nút "Đăng nhập" trên
  trang chủ, không suy ra từ URL trang chủ hay từ quy ước của nguồn khác.
- **Đứng sau Cloudflare Bot Management**: `requests` bị chặn dù dùng đúng cookie phiên + User-Agent
  thật (403 "Just a moment..."), và **Chrome headless cũng bị chặn** (đã thử trực tiếp: chỉ khác mỗi cờ
  `--headless=new` là bị chặn, mọi thứ khác giữ nguyên). Vì vậy `headless` bị khoá cứng = `False` trong
  `_browser_cfg()` — không có tuỳ chọn bật ẩn cho kênh này, khác Joboko.
- **Nhưng phân trang là URL thật** (`?page=N&per-page=100`, điều hướng thẳng được, không cần bấm) —
  nhanh hơn Joboko nhiều. 100 hồ sơ/trang, tổng ứng viên lấy từ chuỗi "N Ứng viên" trên trang.
- **Tải file KHÔNG cần trình duyệt cho phần nặng nhất**: nút "Tải xuống" gọi qua
  `/tool/download?...&l=<url-encoded>` (chính endpoint này VẪN bị Cloudflare chặn nếu gọi trực tiếp),
  nhưng tham số `l` giải mã ra là **link CDN thẳng** (`media.jobsgo.vn/uploads/cv/...` hoặc
  `jobsgo.vn/uploads/cv_gen/...`) **không có Cloudflare** — `requests.get()` thẳng vào đó, không cần
  cookie, trả về file thật (200, `%PDF-1.4`). Vẫn phải mở trang chi tiết bằng trình duyệt một lần để lấy
  được link `l=` này (trang chi tiết cũng sau Cloudflare). Bài học chung cho các nguồn tương lai: dù
  trang chính bị Cloudflare chặn `requests`, vẫn phải giải mã các tham số kiểu `l=`/`url=`/`file=` trong
  nút tải trước khi kết luận "phải tải toàn bộ qua trình duyệt" — endpoint proxy và endpoint file cuối
  cùng có thể nằm ở hai lớp bảo vệ khác nhau.
- **Cấu trúc DOM dễ làm sai**: link tin tuyển dụng (`a.text-grey.text-bold[href*="/job/detail/"]`) đứng
  TRƯỚC cả một CỤM ứng viên đã ứng tuyển vào tin đó trong tài liệu, không lặp lại trong từng dòng ứng
  viên. Bản đầu giả định "mỗi dòng ứng viên có thể leo cha lên để tìm tin tuyển dụng của nó" — sai, ra
  `position`/`campaign_id` rỗng 100% dù unit test (tự bịa HTML tối giản) vẫn xanh. Phải duyệt phẳng
  `soup.find_all("a", href=True)` theo đúng thứ tự tài liệu, giữ "ngữ cảnh hiện tại" (tin đang xét) khi
  gặp marker, gán cho các dòng ứng viên theo sau — không leo cha từ mỗi dòng riêng lẻ. Đã sửa và có test
  hồi quy tái tạo đúng cấu trúc nhóm thật (`test_parse_items_groups_candidates_under_job_link`).
- `cv_id` ghép từ `cid-jid` (cả hai đều là chuỗi base64 mờ hoá) vì một ứng viên có thể ứng tuyển nhiều
  tin — mỗi cặp cid/jid là một lượt ứng tuyển riêng, đúng mô hình "lượt ứng tuyển" chung của toàn hệ
  thống.
- **Giả định chưa kiểm chứng**: thứ tự sắp xếp danh sách theo mới-nhất-trước chưa được xác nhận trực
  tiếp (id dạng base64 mờ hoá nên không suy ra được từ giá trị id như Joboko) — cùng rủi ro với "Chỉ tải
  CV mới" đã nêu ở mục Joboko.

### 37.1. Sự cố thật đã gặp và cách khắc phục dứt điểm (2026-09-05)

Một lượt tải thật báo hai vấn đề trên cùng một lô:

**(a) "Chưa đính kèm CV" sai cho hồ sơ khai trực tiếp trên form.** Bản đầu dùng cờ `_has_file` (đọc từ
sự hiện diện của `a.files-link` trên trang danh sách, tương tự cách VietnamWorks/Việc Làm 24h báo "chưa
có file") để **bỏ qua hẳn** việc mở trang chi tiết khi cờ này là `False` — coi đó là dấu hiệu chắc chắn
"không có CV". Sai với 2 ứng viên thật ("Nguyễn Văn Tú", "Đặng Nguyễn Hoài Linh"): CV của họ là loại
khai trực tiếp trên form (site tự sinh PDF từ dữ liệu, không phải file người dùng tải lên) — giống hệt
cơ chế đã ghi nhận ở VietnamWorks (mục 26 — *"HTTP 404 từ `attachmentPath` không luôn có nghĩa hồ sơ đã
bị xóa"*). Trang chi tiết JobsGO vẫn có nút "Tải xuống" hoạt động thật dù danh sách báo "0 file".
→ **Sửa**: bỏ hẳn việc dùng `_has_file` để chặn `download()`. Cờ này giờ chỉ dùng để hiển thị trên UI,
không còn quyết định có mở trang chi tiết hay không — luôn mở trang chi tiết và tìm nút tải thật.

**(b) HTTP 403 chập chờn cho hồ sơ vẫn hiển thị bình thường trên web** (ứng viên "Anh Hoang"). Bằng
chứng thu thập được cho thấy hai nguyên nhân cộng hưởng (không chắc chắn 100% nhưng đủ mạnh để sửa theo
hướng phòng thủ ở cả hai):
  1. Một hồ sơ có thể có **nhiều nút "Tải xuống"** trỏ tới các host CDN khác nhau (ví dụ hồ sơ đã tải
     lên nhiều file + có thêm một bản CV tự sinh) — độ tin cậy của từng host khác nhau, nút đầu tiên có
     thể trả 403 trong khi một nút khác cho cùng hồ sơ vẫn trả 200.
  2. Đọc HTML ngay sau khi điều hướng sang trang chi tiết có thể xảy ra trước khi cụm nút tải dựng xong
     (đua thời gian render phía client) — chỉ đọc được MỘT phần các link `l=` đã giải mã, mất mất những
     nút xuất hiện muộn hơn.
→ **Sửa**: thêm bước `_wait_download_buttons()` chờ cụm nút "Tải xuống" xuất hiện trong DOM trước khi
đọc HTML; hàm trích xuất (`_extract_cdn_urls()`) giờ trả về **TẤT CẢ** link CDN đã giải mã theo đúng thứ
tự ưu tiên (`.btn-download-cv` trước, `.btn-download` sau, cuối cùng là `a[href^="/tool/download"]`
chung, đã khử trùng lặp) thay vì chỉ lấy link đầu tiên; `download()` thử lần lượt từng link cho tới khi
có link trả HTTP 200 kèm nội dung được `sniff_ext` nhận diện đúng là file CV; nếu tất cả link `requests`
đều thất bại, rơi về phương án cuối `_click_download_button()` — bấm thẳng nút "Tải xuống" thật trong
Chrome và bắt file qua CDP `Page.setDownloadBehavior` (cùng kỹ thuật đã dùng cho toàn bộ Joboko).

Đã kiểm chứng bằng test mới trong `test_jobsgo_provider.py`
(`test_extract_cdn_urls_returns_all_in_priority_order_deduped`, `test_download_ignores_has_file_flag`)
tái tạo đúng hai kịch bản lỗi thật; 274 test toàn repo xanh, `smoke_test.py` OK, `ruff check` sạch.

### 37.2. Vòng 2 (2026-09-05, cùng ngày): fix trên vẫn chưa đủ — hai nguyên nhân sâu hơn

Sau khi phát hành vòng sửa ở mục 37.1, người dùng chạy thật lại gặp lại đúng 2 kiểu lỗi trên 3 hồ sơ
khác — chứng tỏ giả thuyết ở vòng 1 (chỉ là do đọc HTML quá sớm/nhiều host CDN) đúng một phần nhưng
chưa trúng nguyên nhân gốc. Khảo sát trực tiếp lại (đăng nhập lại bằng đúng tài khoản, dump HTML/JS
thật của 3 trang chi tiết bị lỗi) mới lộ ra 2 cơ chế cụ thể:

**(a) "Không tìm thấy nút 'Tải xuống'" — AJAX sinh CV mất 9-13 giây, không phải tức thời.** Với hồ sơ
khai trực tiếp trên form, nút `.btn-download-cv` có mặt NGAY trong HTML đầu tiên (href="#" placeholder,
class không có gì báo "đang tải"), rồi trang tự chạy:
```js
$.ajax({ url: 'https://employer.jobsgo.vn/dashboard/get-cv-file?cid=...&jid=...' })
  .done(function(data) {
    if (data) {
      $('.btn-download-cv').attr('href', '/tool/download?...&l=' + encodeURI(data) + '&t=...')
                            .removeClass('disabled');
    }
  });
```
Đo trực tiếp trên 2 hồ sơ thật: AJAX này mất **8.8 giây** và **12.9 giây** để hoàn tất. Bản vá vòng 1 chỉ
chờ "phần tử có tồn tại trong DOM" (`_wait_download_buttons` cũ) — mà phần tử placeholder này LUÔN tồn
tại ngay từ đầu, nên hàm chờ trả về ngay lập tức, đọc phải href="#" chưa được gán, kết luận sai "không có
nút". Bài học: **chờ phần tử tồn tại và chờ phần tử SẴN SÀNG (có dữ liệu thật) là hai việc khác nhau** —
với trang có AJAX gán thuộc tính sau khi render xong, phải chờ đúng thuộc tính cần dùng đổi giá trị (ở
đây: `href` chứa `tool/download` và `l=`), không phải chờ selector khớp. Sửa: `_wait_download_buttons`
đổi từ tìm phần tử sang polling thuộc tính `href` thật, tăng thời gian chờ lên 25 giây (có biên an toàn
so với 12.9s đo được).

**(b) HTTP 403 vẫn còn dù đã thử "mọi đường" — vì phương án cuối bấm NHẦM nút.** Một hồ sơ đã có file tải
lên (không cần AJAX sinh CV) có thể vẫn hiển thị CẢ HAI nút cùng lúc: `.btn-download-cv` (href="#" —
không dùng ở luồng này, chỉ tồn tại như phần tử chung của mọi trang chi tiết) VÀ `.btn-download` (href
thật, trỏ `/tool/download?...`). `_click_download_button` (phương án cuối, bấm thật trong Chrome) chọn
nút theo THỨ TỰ SELECTOR ưu tiên mà không kiểm tra href có thật hay không — chọn trúng `.btn-download-cv`
href="#" trước, bấm vào đó không tải gì cả (không có handler JS nào gắn với href rỗng), rồi chờ đủ 30
giây tìm file trong thư mục tải mà không thấy, trả về thất bại — khiến lỗi hiển thị cho người dùng vẫn là
"HTTP 403" của lần thử `requests` trước đó (vì phương án cuối thất bại âm thầm, không có lỗi riêng để ghi
đè). Sửa: `_click_download_button` giờ duyệt TẤT CẢ phần tử của TẤT CẢ selector, chỉ chọn phần tử có
`href` chứa `tool/download` (bỏ qua mọi placeholder "#"), thay vì dừng ở phần tử đầu tiên khớp selector
bất kể href.

**Bài học chung rút ra từ vòng 2 này (khác biệt với vòng 1):** một trang chi tiết có thể chứa NHIỀU phần
tử "trông giống nút tải" cùng lúc — có phần tử luôn hiện diện làm placeholder không hoạt động, có phần tử
mới là nút thật. Suy luận "phần tử khớp selector nghĩa là nút đó dùng được" là chưa đủ ở JobsGO; phải luôn
kiểm tra thuộc tính quyết định hành vi thật (ở đây là `href`) trước khi vừa dùng để trích link vừa dùng để
chọn bấm. Đã kiểm chứng lại bằng cách tải thật cả 3 hồ sơ đã báo lỗi (dùng lại phiên Chrome đã đăng nhập
sẵn, không đăng nhập lại) — cả 3 tải thành công (2 PDF tự sinh + 1 DOCX vốn được coi nhầm là XLSX vì đuôi
file trên CDN sai, `sniff_ext` đọc đúng nội dung thật). Thêm test hồi quy
`test_wait_download_buttons_returns_once_href_is_real`,
`test_click_download_button_skips_placeholder_href`,
`test_click_download_button_returns_false_when_all_hrefs_are_placeholders` trong
`test_jobsgo_provider.py`; 277 test toàn repo xanh, `smoke_test.py` OK, `ruff check` sạch.

## 38. Bài học chung: cờ "chưa có file" ở trang danh sách không đáng tin để chặn hành động ở trang chi tiết

Sự cố ở mục 37.1(a) là biến thể mới của bài học đã ghi ở mục 26 cho VietnamWorks, nay lặp lại với JobsGO
— đủ để nâng thành nguyên tắc chung cho **mọi provider hiện tại và tương lai**: trạng thái "không có file
đính kèm" ở trang danh sách (`_has_file`, `isAttached`, `a.files-link`...) chỉ là thuộc tính của NGUỒN
FILE (có ai tải file lên hay không), không phải là trạng thái "không thể xuất được hồ sơ". Nhiều nền
tảng tuyển dụng (VietnamWorks, JobsGO, và có thể cả nguồn tương lai) hỗ trợ ứng viên khai trực tiếp trên
form và tự sinh PDF từ dữ liệu đó khi bấm "Tải xuống" — hồ sơ dạng này luôn báo "0 file" ở danh sách
nhưng vẫn tải được ở trang chi tiết.

**Quy tắc bắt buộc khi khảo sát/triển khai provider mới hoặc sửa provider cũ**: không dùng bất kỳ cờ nào
đọc được từ trang danh sách để bỏ qua việc mở trang chi tiết/gọi endpoint tải — luôn thử tải thật ở
đúng đường người dùng đi (nút "Tải xuống"/"Xem CV"/"Export" trên trang chi tiết), chỉ báo lỗi "không có
CV" sau khi đã thử và xác nhận không có nút tải nào hoạt động. Khi khảo sát một trang mới, phải kiểm tra
cả nút download, preview, print và export — không dừng ở việc đọc cờ hiển thị trên danh sách.

## 39. Bài học chung: regex trích trường từ text đã nối bằng dấu cách phải tách theo cấu trúc, không gộp lớp ký tự

Khi viết `_parse_items` cho JobsGO, số điện thoại trích được có lúc thừa một chữ số ở cuối (`09012345671`
thay vì `0901234567` đúng). Nguyên nhân: `BeautifulSoup.get_text(" ", strip=True)` nối text của nhiều
node con bằng ĐÚNG MỘT dấu cách, dòng ứng viên có cấu trúc kiểu `"...0901234567 1 file"` (số điện thoại
rồi tới nhãn bắt đầu bằng chữ số ngay sau, cách nhau một dấu cách). Regex cũ dùng MỘT lớp ký tự gộp
chung số và dấu cách kiểu `[\d .()-]{8,14}` — phần định lượng ăn luôn qua dấu cách sang chữ số đầu của từ
tiếp theo, kết quả số điện thoại bị nối thêm số không liên quan mà không có gì báo lỗi.

Cách vá đã thử (lần 1 không đủ, lần 2 mới đúng):

- *Lần 1 (không đủ)*: chuẩn hoá rồi CHỈ kiểm độ dài (9-11 số). Sai vì lỗi nuốt thường chỉ thừa ĐÚNG MỘT
  chữ số — `0901234567` (10 số, đúng) bị nuốt thành `09012345675` (11 số) vẫn rơi vừa khít vào khoảng
  hợp lệ 9-11, không bị lọc ra.
- *Lần 2 (đúng, đang dùng ở cả 3 nơi)*: thay lớp ký tự gộp bằng PHÉP HOẶC hai nhánh —
  ```
  (?<!\d)(?:\+?84|0)(?:\d{8,10}|\d{2,4}(?:[ .\-]\d{2,4}){1,3})(?!\d)
  ```
  - Nhánh 1 `\d{8,10}`: dãy số liền nhau — không thể bắc cầu qua dấu cách vì dấu cách không nằm trong
    lớp `\d`, tự dừng đúng ranh giới thật.
  - Nhánh 2: số được hiển thị chia nhóm bằng dấu cách/chấm/gạch thật (`"090 123 4567"`) — mỗi nhóm sau
    dấu cách bắt buộc ≥2 chữ số, nên MỘT chữ số lẻ loi đứng sau dấu cách (chính là kiểu rác gây lỗi)
    không khớp được vào nhánh này.
  - Đây là vá CẤU TRÚC (regex tự nhiên dừng đúng chỗ), mạnh hơn hẳn vá theo kiểu lọc sau:
    `"0901234567 5 years experience"` trả đúng `"0901234567"`, không phải chuỗi rỗng do bị từ chối.
  - Vẫn giữ bước chuẩn hoá + kiểm độ dài 9-11 sau đó làm lưới an toàn thứ hai, không phải cơ chế chặn
    chính.

Đã áp dụng ở cả 3 provider: `joboko.py`, `jobsgo.py` (nơi phát hiện lỗi), và `itviec.py`
(`_extract_phone` — trước đó dùng `[\d .()-]{8,14}` cùng lớp lỗi, sửa ngay khi audit lại vì rủi ro dùng
sai số điện thoại để gọi ứng viên là nghiêm trọng, dù chưa có bằng chứng lỗi này thật sự xảy ra trên dữ
liệu ITViec). Cả 3 nơi có test hồi quy tái tạo đúng kịch bản nuốt số
(`test_itviec_provider.py::test_extract_phone_does_not_swallow_digit_of_next_word`,
tương ứng trong `test_joboko_provider.py` và `test_jobsgo_provider.py`).

**Quy tắc chung khi thêm nguồn mới**: bất cứ khi nào viết/soát một regex trích trường có độ dài biến
thiên (số điện thoại, mã số...) từ text đã NỐI BẰNG DẤU CÁCH từ nhiều node DOM
(`get_text(" ", strip=True)`), KHÔNG dùng một lớp ký tự gộp chung "nội dung cần lấy" với "dấu phân cách
được phép" — luôn tách thành phép HOẶC giữa "dãy liền nhau" và "các nhóm ≥2 ký tự nối bằng đúng một dấu
phân cách", để một ký tự rác lẻ loi đứng sau dấu cách không khớp được vào nhánh nhóm. Copy nguyên mẫu
`_PHONE_RE` ở trên khi thêm provider mới thay vì viết lại từ đầu.

## 40. Hẹn giờ tải CV: audit và vá 3 rủi ro khi vận hành đa tài khoản, đa nhà cung cấp (2026-09-05)

Với 7 nhà cung cấp (nhiều cái phụ thuộc Chrome thật + Cloudflare, khác hẳn TopCV thời chỉ có 1 nguồn),
audit lại `web_api.py`'s `start_schedule()` lộ ra 3 rủi ro vận hành thật, dù kiến trúc tuần tự (từng
lịch → từng nguồn → từng tài khoản, để tránh tranh Chrome profile/SQLite) vẫn đúng và nên giữ nguyên.

### 40.1. Không có watchdog cho lượt tải theo lịch bị treo

Đồng bộ Hub (`sync/service.py`) đã có `STALE_RUN_SECONDS=600` để tự huỷ nếu treo quá 10 phút; luồng
tải CV theo lịch (`_engine_thread`) thì không có gì tương đương. `set_page_load_timeout(45)` trong
`browser.py` chỉ chặn được kiểu "trang tải chậm bình thường" — nếu chromedriver/Chrome bị deadlock thật
sự ở tầng driver (không phải timeout trang), lệnh Selenium tiếp theo có thể không bao giờ tự trả lời,
`is_downloading()` mãi là `True`, chặn TOÀN BỘ lịch còn lại (mọi nhà cung cấp, mọi tài khoản) vô thời
hạn — không tự phục hồi, không cảnh báo, phải người dùng phát hiện và khởi động lại app.

**Đã vá**: `Api._force_recover_stuck_download(source)` (web_api.py) — gọi khi một nguồn đã chạy quá
`SCHEDULED_JOB_MAX_MINUTES` (180 phút) mà `is_downloading()` vẫn `True`. Thứ tự khôi phục:
1. `stop_download()` — yêu cầu dừng hợp tác (best-effort, có thể lỗi nếu engine ở trạng thái lạ; vẫn
   phải tiếp tục bước 2 dù bước này lỗi).
2. Ép đóng Chrome của **mọi tài khoản** thuộc nguồn đó (`close_profile_browser`, không chỉ tài khoản
   đang chạy — scheduler không biết chính xác tài khoản nào trong hàng đợi tuần tự đang treo) để lệnh
   Selenium đang treo gặp lỗi kết nối và tự thoát.
3. Chờ thêm `SCHEDULED_JOB_KILL_GRACE_SECONDS` (90 giây) để luồng tải tự kết thúc.
4. Nếu vẫn còn sống sau đó (Python không thể ép kill một thread an toàn) — coi là không thể phục hồi:
   **tắt hẳn hẹn giờ** (`schedule_enabled=False`, dừng vòng lặp), ghi log lỗi rõ ràng yêu cầu khởi động
   lại phần mềm, thay vì tiếp tục vòng lặp trong trạng thái không chắc chắn (có thể có 2 luồng cùng ghi
   SQLite). Nếu khôi phục được (bước 3 thành công), lịch vẫn tiếp tục bình thường cho nguồn/lịch tiếp
   theo, chỉ đánh dấu lượt này lỗi.

### 40.2. Lịch lỗi liên tiếp không có cơ chế giãn cách

Đồng bộ Hub có `_fail_streak`/cooldown giãn dần khi lỗi liên tiếp; lịch tải CV trước đây không có — một
lịch sai mật khẩu/tài khoản bị khoá cứ đúng `interval_min` lại thử lại đều đặn mãi mãi, dội liên tục vào
một tài khoản/site đang lỗi mà không bao giờ tự nới ra.

**Đã vá**: mỗi job lưu thêm `fail_streak` (số lần lỗi liên tiếp gần nhất), reset về 0 khi chạy thành
công hoặc khi người dùng chủ động sửa/lưu lại lịch (coi như khởi đầu mới — vd sau khi cập nhật mật
khẩu). Khi tính giờ chạy tiếp theo, nếu `fail_streak > 0` thì cộng thêm một khoảng nghỉ
`min(SCHEDULE_MAX_BACKOFF_MINUTES=360, interval_min * fail_streak)` phút kể từ hiện tại, đứng trước mốc
lưới thường nếu mốc đó gần hơn — tối đa giãn tới 6 tiếng, không phải vô hạn (vẫn thử lại định kỳ phòng
trường hợp vấn đề đã được khắc phục).

### 40.3. `interval_min` tính từ lúc lượt trước KẾT THÚC → trôi giờ nếu một lượt chạy lâu

Bản cũ: `next_run = datetime.now() + interval` tính ngay sau khi lượt vừa xong. Nếu một lượt kéo dài
(vd JobsGO quét toàn bộ hồ sơ mất hàng giờ do `concurrency_limit()==1` + không headless), giờ chạy kế
tiếp trôi dần theo thời gian lượt đó chạy, không còn cố định theo đồng hồ như người dùng cấu hình.

**Đã vá**: `Api._grid_next_run(anchor, interval_minutes, now)` (staticmethod) tính giờ chạy tiếp theo
trên một **lưới cố định** `anchor + k*interval` (anchor = mốc `start_time` gốc, parse một lần khi bật
lịch hoặc khi lịch được lưu lại) — không tính từ lúc lượt trước kết thúc. Nếu lỡ mất một hoặc nhiều
nhịp (lượt trước chạy lâu hơn cả interval), nhảy thẳng tới nhịp gần nhất còn ở tương lai, không dồn chạy
bù liên tiếp nhiều lần. `Api._next_schedule_run(job_id, job, now)` kết hợp kết quả lưới này với phần
giãn cách lỗi ở mục 40.2 (lấy mốc muộn hơn giữa hai cái). Mốc gốc (`_scheduler_job_anchor`) được làm mới
khi người dùng lưu lại một lịch đang bật (đổi `start_time`/`interval_min`) để không dùng nhầm lưới cũ.

### Kiểm chứng

`tests/test_schedule_timing.py` (9 test) — xác nhận lưới cố định không trôi giờ khi một lượt chạy lâu,
nhảy đúng nhịp khi lỡ nhiều nhịp, và backoff cộng đúng/kẹp đúng trần. `tests/test_schedule_watchdog.py`
(3 test, dùng `Api.__new__(Api)` + mock — không khởi động Chrome thật) — xác nhận đóng Chrome của mọi
tài khoản thuộc nguồn, vẫn tiếp tục đóng dù `stop_download()` lỗi, và trả `False` đúng khi luồng không
bao giờ dừng trong thời gian chờ. 289 test toàn repo xanh, `smoke_test.py` OK, `ruff check` sạch.

**How to apply**: các con số `SCHEDULED_JOB_MAX_MINUTES`, `SCHEDULED_JOB_KILL_GRACE_SECONDS`,
`SCHEDULE_MAX_BACKOFF_MINUTES` (đầu `web_api.py`) là điểm khởi đầu bảo thủ, không phải cam kết cố định —
chỉnh sau khi có dữ liệu vận hành thật (tần suất treo thực tế, thời gian một lượt "Tải tất cả" hợp lý
nhất cho từng nguồn). Nếu thêm nguồn tuyển dụng thứ 8 phụ thuộc Chrome, không cần sửa gì ở tầng hẹn giờ —
watchdog/backoff/lưới giờ đều là logic dùng chung, không đặc thù theo provider.

## 41. Trường chỉ có trên trang chi tiết ứng viên (nơi làm việc mong muốn, tình trạng hôn nhân...) — 2026-09-05

Trang chi tiết ứng viên của mỗi nhà cung cấp có nhiều trường KHÔNG nằm trong file CV và KHÔNG nằm trong
danh sách — hữu ích cho tuyển dụng (sàng lọc theo khu vực, tình trạng hôn nhân...). Trước đây chỉ
VietnamWorks/CareerViet mới mở trang/API chi tiết (5 nguồn còn lại chỉ đọc danh sách rồi tải thẳng file).

### 41.1. Mỗi nơi gọi tên MỘT KIỂU — không dò bằng một bộ từ khóa

Khảo sát thực tế (người dùng gửi ảnh chụp): "nơi làm việc mong muốn" mỗi site đặt tên khác hẳn nhau,
nên dò bằng từ khóa `"mong muốn"`/`"khu vực"` trượt hết. Bảng đối chiếu:

| Nguồn | Nhãn thật | Vị trí |
|---|---|---|
| TopCV | **"Sẵn sàng di chuyển (Hồ Chí Minh)"** | sidebar "Thông tin bổ sung từ ứng viên" |
| Việc Làm 24h | **"Địa điểm làm việc mong muốn"** | mục "Thông tin ứng viên" trang chi tiết |
| VietnamWorks | **"Nơi làm việc mong muốn"** (+ "Tình trạng hôn nhân", "Mức lương hiện tại", "Cấp bậc mong muốn", "Trình độ ngoại ngữ") | panel "Thông tin chung" |
| CareerViet | **"Địa điểm"** (+ "Cấp bậc mong muốn", "Ngành nghề mong muốn", "Hình thức", "Ngoại ngữ", "Quốc gia") | tab "Chi Tiết Hồ Sơ" → "Thông tin nghề nghiệp" |
| JobsGO | **"Làm việc tại"** | mục "Thông Tin Cơ Bản" (trang chi tiết provider đã mở sẵn để tải CV) |
| ITViec | (KHÔNG có — đã kiểm HTML render đầy đủ 219KB, 0 dấu vết) | — |
| Joboko | (KHÔNG có — đã kiểm HTML thật, 0 dấu vết) | — |

**Bài học**: với dữ liệu form của nền tảng tuyển dụng, KHÔNG đoán tên trường bằng một bộ từ khóa chung.
Phải xem ảnh chụp/HTML thật của trang chi tiết từng site, lập bảng nhãn→cột trước khi viết parser.

### 41.2. Cột DB mới (migration không phá dữ liệu)

Thêm vào `_SCHEMA` + `_FIELDS` (`db.py`): `desired_location`, `desired_level`, `desired_position`,
`job_type`, `marital_status`, `foreign_language`, `current_salary` — đều TEXT, nullable.
`_migrate_candidate_columns` tự ALTER bù cho DB cũ.

**Bẫy đã gặp và sửa**: `_migrate_account_key` (nâng khóa `(source,cv_id)` → `(source,account,cv_id)` cho
DB rất cũ) có một `CREATE TABLE candidates(...)` **viết cứng inline** — bản sao schema đã lạc hậu. Khi
thêm cột mới vào `_FIELDS`, `_migrate_candidate_columns` chạy TRƯỚC sẽ thêm cột vào bảng cũ, rồi
`_migrate_account_key` chép dữ liệu bằng danh sách cột của bảng cũ (đã gồm cột mới) vào bảng inline (chưa
có cột mới) → lỗi "no such column" → migration hỏng, `rows=0`. Sửa: gọi `Database._migrate_candidate_columns(conn)`
NGAY SAU `CREATE TABLE` inline (và lọc `copy_columns` theo cột bảng mới thực có) để bảng mới luôn đủ cột
`_FIELDS` trước khi INSERT. Nếu sau này lại thêm cột, KHÔNG cần sửa bản inline nữa.

### 41.3. Cách lấy dữ liệu theo từng nguồn (cấu trúc DOM đã xác nhận từ HTML lưu về)

- **JobsGO — XONG, kiểm chứng 4/4 hồ sơ thật**: `download()` vốn đã mở trang chi tiết để tìm nút tải —
  bóc thêm ngay tại đó. Cấu trúc thật: `<li><strong>Nhãn:</strong><span>giá trị</span></li>` — lấy đúng
  `<span>` anh em ngay sau `<strong>` (KHÔNG `get_text` cả trang — sẽ dính chữ trên nút "Tải").
  `_LABEL_TO_FIELD`: "Làm việc tại"→`desired_location`, "Địa chỉ"→`address`, "Năm sinh"→`birth_year`,
  "Giới tính"→`gender`. Thêm `supports_detail_enrichment=True` + `enrich()` (`_apply_detail_fields` dùng
  chung, đặt `detail_loaded=1`) để "Tải tất cả" bổ sung hồ sơ cũ.
- **VietnamWorks — XONG (theo HTML lưu về)**: query GraphQL đang dùng **không** trả các trường này (đã
  kiểm 45 key). Panel "Thông tin chung" là **server-render trong DOM trang** `/v3/application/detail/
  {jobId}/{appId}` (KHÔNG có `__NEXT_DATA__`/apollo). Cấu trúc: `<div class="discriptions"><div class=
  "titleContent">Nhãn</div><div class="valueContent">Giá trị</div></div>`, có bản `viewPC` rồi
  `viewMobile` lặp lại → chỉ lấy lần đầu mỗi nhãn. `_scrape_general_panel(item)` mở `cv_url` bằng
  `driver` (dưới `_driver_lock`, best-effort, nuốt mọi lỗi), gọi ở cuối `_load_detail` (nên chạy cả
  đường `download()` lẫn `enrich()`). `_PANEL_MAP`: "Nơi làm việc mong muốn"→`desired_location`, "Tình
  trạng hôn nhân"→`marital_status`, "Cấp bậc mong muốn"→`desired_level`, "Trình độ ngoại
  ngữ"→`foreign_language`, "Mức lương hiện tại"→`current_salary`; các nhãn khác chỉ điền khi GraphQL để
  trống. **Đánh đổi**: mỗi hồ sơ VNW giờ tốn thêm 1 lần mở trang bằng trình duyệt (serialize qua
  `_driver_lock`) — chậm hơn đường `requests`+GraphQL thuần cũ; chấp nhận vì người dùng đã đồng ý và
  engine chặn chạy lại bằng `detail_loaded`.
- **TopCV — XONG (theo HTML lưu về)**: sidebar "Thông tin bổ sung từ ứng viên" trên trang chi tiết CV
  (Vue SPA — `requests` chỉ lấy khung rỗng, phải render qua Chrome). Cấu trúc: `<div class=
  "relocation-label"><div class="info"><span class="text">Sẵn sàng di chuyển</span> <span class="more">
  (Hồ Chí Minh)</span></div></div>`. `_scrape_relocation(item)` lấy text `.relocation-label .info` rồi
  regex `\(([^)]+)\)` → `desired_location`. Thêm `supports_detail_enrichment=True` + `enrich()`; cũng gọi
  ở đầu `download()` khi `not item.get("detail_loaded")`. Cùng đánh đổi tốc độ như VNW.
- **CareerViet — XONG (key JSON đã xác nhận bằng dump `detail` thật 2026-09-05)**: HTML lưu về là trang
  UI nhưng provider lấy qua **API JSON** `DETAIL_API/{resume_id}/detail`, key khác nhãn UI. Key thật:
  `resume_districts` (danh sách `[{location_name, districts:[{district_name_vn}]}]` → `_format_districts`
  ghép "Tỉnh (quận...)")→`desired_location`; **`resume_level_name_vn`** (đây là cấp bậc MONG MUỐN;
  `resume_present_level_name_vn` mới là hiện tại — code cũ dùng cái sau cho `job_level` là đúng)
  →`desired_level`; `resume_industries[].industry_name_vn`→`desired_position`;
  `resume_languages[].certification`→`foreign_language`; `jobseeker_marital`(_name_vn)→`marital_status`.
  **"Hình thức" (job_type) BỎ** — không có key nào rõ ràng trong 94 key `detail` (nghi là bitmask
  `resume_type="0000"`, không giải mã).
- **Việc Làm 24h — XONG (key `row` list-API đã xác nhận 2026-09-05)**: list-API `row` CÓ SẴN
  `desired_location` (top-level, là **danh sách province_id dạng SỐ**), `seeker_info.marital_status`
  (mã 1/2/3), `resume_info.level` (mã). API KHÔNG trả tên tỉnh, KHÔNG có endpoint từ điển
  (`/mix/fe/location/*` đều 404). Giải: `_load_province_map()` bóc mảng `provinces`
  (`[{id, code, name}]`) từ `__NEXT_DATA__` của trang quản trị (đã mở sẵn trong `connect()`), cache
  `{id: name}`; `_resolve_desired_location(row)` đổi list id → tên. `_MARITAL_MAP = {1:"Độc thân",
  2:"Đã kết hôn", 3:"Khác"}` (hardcode enum nhỏ cố định). `desired_level` (mã `resume_info.level`) BỎ —
  chưa có bảng tra tin cậy. Không cần mở trang chi tiết — mọi thứ có trong `row`.
- **ITViec, Joboko — FALLBACK từ CV (đã làm)**: xác nhận lại từ HTML lưu về — 0 dấu vết trường này trên
  trang. `cv_parser._desired_location_from_cv(text)` bắt nhãn "địa điểm/nơi làm việc mong muốn" trong
  text CV; `db.finish_document_v2` điền `candidates.desired_location` từ `fields["desired_location"]`
  **chỉ khi cột đang trống** (không đè giá trị đã bóc từ trang chi tiết của nguồn khác). Best-effort —
  chỉ có nếu ứng viên tự ghi trong CV.

### 41.4. Rủi ro vận hành đã gặp khi khảo sát

Chạy nhiều script Selenium mở/đóng Chrome dồn dập trong thời gian ngắn làm **rớt phiên đăng nhập thật**
của VietnamWorks/ITViec/CareerViet (đang dùng tốt bỗng bị đòi xác minh lại). Mỗi lần vậy là một lượt
đăng nhập thật vào tài khoản MSB. **Bài học**: khi cần khảo sát nhiều site, xin người dùng lưu sẵn HTML
một trang chi tiết mỗi site (Ctrl+S → "Webpage, HTML Only") rồi dựng parser offline, thay vì tự động hoá
nhiều phiên liên tiếp. Việc `download()` của JobsGO/Joboko vốn đã mở trang chi tiết là ngoại lệ an toàn
(không phát sinh phiên mới).

**Mật khẩu trong kho DPAPI có thể đã cũ.** Khi được người dùng đưa mật khẩu mới cho CareerViet
và Việc Làm 24h (không chép vào tài liệu), đăng nhập tự động THÀNH CÔNG ngay — trong khi các lần
trước dùng mật khẩu trong kho bí mật đều rớt phiên. Nghĩa là mật khẩu lưu trong ứng dụng cho 2 tài
khoản này đã lỗi thời. Nếu người dùng báo "đăng nhập tự động cứ đòi xác minh", nghi phạm đầu tiên là
mật khẩu trong tab Cấu hình đã cũ — bảo họ nhập lại. (Không tự ý sửa kho bí mật.)

### 41.5. Bảng trạng thái tổng (2026-09-05)

| Nguồn | Trường lấy được | Cách | Kiểm chứng |
|---|---|---|---|
| JobsGO | desired_location, address, birth_year, gender | DOM `<li><strong>Nhãn:</strong><span>` khi `download()` mở trang | 4/4 hồ sơ thật |
| VietnamWorks | desired_location, marital_status, desired_level, foreign_language, current_salary (+ điền bù các trường GraphQL để trống) | DOM panel `div.discriptions` — `_scrape_general_panel` mở `cv_url` trong `_load_detail` | Cấu trúc từ HTML lưu về + unit test |
| TopCV | desired_location | Selenium `.relocation-label .info` → regex `\(...\)` — `_scrape_relocation` | Cấu trúc từ HTML lưu về + unit test |
| CareerViet | desired_location, desired_level, desired_position, foreign_language, marital_status | Key JSON `detail` đã dump thật | Unit test theo dump thật |
| Việc Làm 24h | desired_location, marital_status | `row` list-API + bảng tra `provinces` từ `__NEXT_DATA__` | Khảo sát live + unit test |
| ITViec, Joboko | desired_location (best-effort) | `cv_parser` bắt nhãn trong text CV, điền khi cột trống | Unit test regex |

### 41.6. Vòng 3 (2026-09-06): chuẩn hoá địa danh + sửa timing SPA + đồng bộ Hub

**Bug timing (người dùng test thấy TopCV/VNW không ghi nhận trường mới):** `_scrape_relocation`
(TopCV, Vue) và `_scrape_general_panel` (VNW, React/ant-tabs) đọc DOM ngay sau `safe_get` (chờ 2.5s) —
SPA render bất đồng bộ nên panel chưa dựng xong → bóc rỗng. **Sửa:** thêm vòng poll (tới 20s) chờ mốc
DOM ổn định xuất hiện (`div.discriptions`/`titleContent` cho VNW; `.relocation-label .info` có text,
hoặc `.campaign-box` đã dựng = ứng viên không khai cho TopCV) rồi mới đọc. Bài học chung: **mọi lần bóc
DOM từ trang SPA phải poll chờ mốc render, không tin `time.sleep` cố định** (cùng lớp bug với JobsGO
mục 37.2 và Joboko mục 36).

**Vieclam24h `_load_province_map` gia cố:** không chỉ đọc `page_source` một lần (sau login trình duyệt
có thể ở trang khác) — chủ động mở lại `MANAGER_URL` và poll tới 15s cho tới khi `__NEXT_DATA__` có
mảng `"provinces"`.

**`app/geo.py` — danh mục 63 tỉnh/thành + so khớp linh hoạt:**
- `canonical_province(text)` → tên chuẩn nếu `text` LÀ một tỉnh (nhận "TP.HCM", "tp hcm", "Sài Gòn",
  "HCM", "Ho Chi Minh City", "Nha Trang"→"Khánh Hòa", "Vũng Tàu"→"Bà Rịa - Vũng Tàu"...; bỏ dấu, cắt
  đuôi "(Tất cả quận/huyện)"/": Ngũ Hành Sơn").
- `find_provinces(text)` → mọi tỉnh xuất hiện trong text (khớp dài trước để "Vũng Tàu" không nuốt
  "Bà Rịa - Vũng Tàu"), dùng quét text CV.
- `normalize_location(raw)` → nếu nhận ra tỉnh thì trả tên chuẩn (nối `, `), không thì trả chuỗi gọn.
- **Áp vào**: TopCV/VNW/JobsGO/Vieclam24h chuẩn hoá giá trị bóc từ web qua `normalize_location`;
  CareerViet chuẩn hoá `location_name` trong `_format_districts` (giữ đuôi quận/huyện).

**`cv_parser._desired_location_from_cv` 2 bước:** (1) có nhãn "địa điểm/nơi làm việc mong muốn" → lấy
chuỗi sau, `normalize_location`. (2) không có nhãn → `find_provinces(cả text CV)` lấy 2 tỉnh đầu (kém
tin hơn, có thể trúng nơi ở hiện tại). **Thứ tự ưu tiên: web trang chi tiết > nhãn trong CV > quét
tỉnh trong CV** — `db.finish_document_v2` chỉ điền `desired_location` khi cột đang trống.

**Chạy ẩn (headless):** cờ `AppConfig.headless` VỐN CÓ nhưng **không có ô chọn trên giao diện** nên
luôn kẹt = `False` → người dùng test thấy "không chạy ẩn". Đã thêm ô `#cfg-headless` ("Chạy ẩn cửa sổ
Chrome") ở tab Cấu hình (index.html + `loadConfig`/`saveConfig` trong app.js; `save_config` vốn lưu mọi
key có trên `_cfg`). Áp cho TopCV/CareerViet/Việc Làm 24h/ITViec (đọc `cfg.headless`).
**VietnamWorks + JobsGO ép `headless=False`** trong `_browser_cfg()` — site trả 403 cho headless
(VNW mục 15, JobsGO mục 37).

### 41.8. Vòng 4 (2026-09-06): người dùng test TopCV vẫn không ra địa điểm — gia cố + log chẩn đoán

Không tái hiện được offline (trang chi tiết CV TopCV là SPA/modal, phải render qua Chrome đăng nhập
thật). Đã:
- **Dùng `get_attribute("textContent")`** thay `.text` (Selenium `.text` trả rỗng nếu phần tử đang ẩn
  / chưa hiện hẳn).
- **Chờ 25s + grace 5s sau khi trang chi tiết đã dựng** (`.campaign-box`/`.cv-preview`/`iframe`) rồi mới
  bỏ cuộc — `.relocation-label` có thể render sau khối CV vài giây.
- **Phát hiện redirect về đăng nhập** (`/app/login`, `/v2/login`) → bỏ qua, ghi log, không treo.
- **Log chẩn đoán bắt buộc**: `_scrape_relocation`/`_scrape_general_panel` giờ luôn `self.log(...)` một
  dòng "ⓘ" cho biết: bóc được giá trị gì, hoặc "trang chi tiết không có mục 'Sẵn sàng di chuyển' (text
  đọc được: ...)", hoặc "chuyển về đăng nhập". Chạy tải một hồ sơ rồi đọc dòng ⓘ trong nhật ký để biết
  đúng nguyên nhân (thiếu quyền / modal không mở bằng URL trực tiếp / ứng viên không khai / đã OK).

**Nếu log báo "không có mục ... (text đọc được: '')"** nghĩa là điều hướng thẳng `cv_url` không dựng
được sidebar (modal chỉ mở qua thao tác JS từ danh sách, không phải route) → phải đổi cách: mở trang
danh sách rồi click vào hồ sơ, hoặc tìm API JSON của trang chi tiết. Chưa xác nhận được cho tới khi có
log thật.

### 41.9. Vòng 5 (2026-09-06): VNW panel ra 0 trường vì NHÃN TIẾNG ANH

Log thật của người dùng:
```
ⓘ VietnamWorks: panel 15 khối, 0 trường, KHÔNG có 'Nơi làm việc mong muốn'.
Nhãn thấy: ['Current position', 'Current Job Level', 'Latest company', 'Years of experience',
'Expected salary', 'Expected job level', 'Birthday', 'Gender', 'Martial status', 'Home address',
'Expected job location', 'Highest education', 'Languages']
```
Panel **render bình thường (15 khối)** — nhưng tài khoản đang để **giao diện tiếng Anh**, `_PANEL_MAP`
chỉ có nhãn tiếng Việt nên khớp 0. **Sửa:** map cả EN lẫn VI, key hạ chữ thường, tra hạ chữ thường
(`title.get_text().lower().rstrip(":")`). Nhãn EN đã xác nhận: "Expected job location"→`desired_location`,
"Martial status" (VNW **gõ sai chính tả**, đúng ra "Marital")→`marital_status`, "Expected job
level"→`desired_level`, "Languages"→`foreign_language`, "Current salary"→`current_salary`. Thêm
placeholder rỗng EN vào `_PANEL_SKIP_VALUES` ("Add number", "Not updated", "N/A", "None"...).

**Bài học:** VietnamWorks employer có nút chuyển VI/EN rất dễ bấm nhầm — MỌI parser bóc theo nhãn hiển
thị của VNW phải map cả hai ngôn ngữ. Các nguồn khác: TopCV bóc theo cấu trúc + phần trong ngoặc
(`normalize_location` lo phần tên) nên không phụ thuộc ngôn ngữ; CareerViet/Vieclam24h dùng dữ liệu có
cấu trúc (key JSON / province_id) nên cũng độc lập ngôn ngữ.

Một dòng lỗi khác trong log — `panel KHÔNG dựng sau 30s (URL .../v3/candidate/search?...)` kèm
"VietnamWorks không cho phép tải hồ sơ này" — là hồ sơ `canDownload=false`, `cv_url` redirect về trang
tìm kiếm. Đúng hành vi, đã log và bỏ qua, không phải bug.

### 41.10. Vòng 6 (2026-09-06): scrape + upsert ĐÚNG nhưng modal chi tiết vẫn "—"

Người dùng tải VNW, log xác nhận `ⓘ VietnamWorks: panel 15 khối → nơi làm việc mong muốn = Hà Nội
(14 trường)` cho 10 hồ sơ; query trực tiếp `du_lieu_ung_vien.db` cho thấy `desired_location='Hà Nội'`,
`marital_status='Maried'`, `detail_loaded=1` — **dữ liệu đã nằm trong DB**. Nhưng modal "Xem chi tiết
ứng viên" trên Edge vẫn hiện `—` cho mọi trường mới.

**Nguyên nhân:** `openCandidateDetail(c)` render từ `c` — chính là **dòng trong snapshot bảng danh
sách** (`res.items` của lần `loadCandidates()` gần nhất). Khi engine đang tải/parsing và `db_path` nằm
trong thư mục cloud (`is_cloud_synced_path`), `get_candidates` **cố tình trả cache "stale"** (tránh mở
connection thứ hai + render nghìn dòng). Cache đó là ảnh chụp TRƯỚC khi enrich, nên `c.desired_location`
rỗng. Riêng hồ sơ "đã có → bỏ qua" mà được enrich thêm (`engine._process_one` nhánh `cv_id in
done_ids`) thì **không** `publish()` realtime → cache frontend không bao giờ được vá cho nhóm này.

**Sửa:** thêm API `Api.get_candidate_detail(source, account, cv_id)` — đọc **lẻ đúng một dòng** bằng
`db.get_candidate` (`SELECT * ... WHERE source=? AND cv_id=? [AND account=?]`), KHÔNG chặn theo cờ
downloading/parsing (một dòng theo khoá định danh thì nhẹ, an toàn cả trên ổ cloud; lỗi khoá file
chốc lát → trả `ok:false`, JS tự lùi về dữ liệu bảng). `openCandidateDetail` gọi API này đầu tiên rồi
`c = {...c, ...fresh.candidate}` (giữ lại `alerts`/`alerts_short`/`applications` do backend tính riêng
ở `get_candidates`, không có trong bảng `candidates`).

**Bài học:** modal chi tiết KHÔNG được tin dòng từ snapshot danh sách khi có đường "trả cache stale
lúc đồng bộ". Bất kỳ trường nào chỉ điền sau enrich (`detail_loaded`) đều phải đọc lại từ DB tại thời
điểm mở modal. Bảng danh sách tự lành ở lần `loadCandidates()` không-bận kế tiếp; chỉ modal cần đọc
tươi ngay.

### 41.11. Vòng 7 (2026-09-06): JobsGO & Joboko bỏ sót vị trí ứng tuyển + trường trên trang chi tiết

Người dùng phát hiện 2 kênh mới lấy CV về nhưng `position` (vị trí ứng tuyển) TRỐNG — kiểm DB:
JobsGO 0/43, Joboko 0/58. Đây là trường ATS quan trọng nhất.

**JobsGO**
- *Vì sao mất `position`:* danh sách nhóm ứng viên theo tin qua link tiêu đề (`a.text-grey.text-bold`
  + `/job/detail/<id>`) đứng TRƯỚC cụm — selector này đã lệch với site hiện tại nên `current_position`
  luôn rỗng. **Không đoán lại selector danh sách** (không có HTML danh sách lưu về).
- *Nguồn tin cậy = trang chi tiết:* `<div class="candidate-position">` ở header hồ sơ (NGOÀI mục
  "Thông Tin Cơ Bản" nên vòng `<strong>` cũ không chạm) = vị trí ứng tuyển. `_parse_detail_fields`
  nay lấy thêm: `position` ← `.candidate-position`; `current_title` + `last_company` ← `#tab-qua-trinh
  .resume-item` đầu (`h4` + `small`); `education` ← `#tab-hoc-van .resume-item` đầu (bỏ placeholder
  "Chưa có thông tin học vấn" — thêm vào `_EMPTY_VALUES`).
- *`campaign_id`:* `jid` (mã tin đã mã hoá) LUÔN có trong href danh sách → `_parse_items` set
  `campaign_id = current_campaign or jid`. Không phụ thuộc link tiêu đề.
- Trang chi tiết JobsGO KHÔNG có: học vấn có cấu trúc thường trống, không có mã tin dạng số, không có
  link `/job/detail`. Mục "Thông Tin Cơ Bản" chỉ có: Năm sinh, SĐT, Email, Giới tính, Làm việc tại,
  Địa chỉ, Loại tệp, Tóm tắt, Cập nhật (đã lấy 4 trường hữu ích).

**Joboko**
- Trang chi tiết `xem-ho-so-...` KHÔNG có block thông tin cấu trúc nào — toàn bộ CV là PDF trong
  `iframe.file-cv` (`f3-vn.joboko.com/WaterMark/....pdf`). Dữ liệu ứng tuyển nằm trong **biến JS**
  `var jbkCVInfo = '{...}'` (JSON) ở một `<script>`: `IdJob` (mã tin), `IdCamp`, `TxtNote` =
  `"Ứng viên <tên> ứng tuyển việc làm <VỊ TRÍ>"`.
- Thêm `supports_detail_enrichment=True` + `enrich()` + `_parse_detail_fields()` (regex
  `jbkCVInfo\s*=\s*'(\{.*?\})'` → `json.loads` → `position` từ `TxtNote` sau cụm "ứng tuyển việc làm",
  `campaign_id` từ `IdJob`). `download()` cũng gọi `_apply_detail_fields` khi trang đã mở.
- `jid` trong href danh sách (`?src=1&jid=6654362&...`) = `IdJob` → `_parse_items` set `campaign_id`
  ngay từ danh sách, không cần mở chi tiết.
- Các trường khác (địa điểm, năm sinh, học vấn, kinh nghiệm) chỉ có trong PDF → để `cv_parser` +
  `geo.py` lo sau khi tải, giống ITViec.
- Hồ sơ cũ (58 dòng `detail_loaded=NULL`): lần "Tải tất cả" kế tiếp engine gọi `enrich()` cho từng
  hồ sơ (nhánh `cv_id in done_ids`) rồi `db.upsert` → tự backfill `position`/`campaign_id`.

5 trường liên quan (`position`, `campaign_id`, `current_title`, `last_company`, `education`) ĐÃ có sẵn
trong `CANDIDATE_FIELDS` (sync) → không đổi `payload_hash`, không ép đồng bộ lại.

### 41.7. Đồng bộ lên Hub (2026-09-06)

- **Edge**: thêm 7 trường vào `CANDIDATE_FIELDS` (`sync/payload.py`). Tác dụng phụ có chủ đích:
  `payload_hash` đổi cho MỌI hồ sơ → lần đồng bộ kế tiếp gửi lại toàn bộ kho một lần (tự backfill).
- **Hub**: `TalentProfile` + 7 cột (`0010_...`); `talent/derive.py::SIMPLE_FIELDS` + 7 mapping (cắt
  theo `max_length` của cột — Postgres từ chối chuỗi quá dài); 2 `Meta.fields` trong
  `talent/serializers.py` + 7. Data query được qua ORM + hiện ở Person 360.
- **Answer Engine**: `structured_match._match_ids_for_phrase` thêm nhánh khớp
  `TalentProfile.desired_location`/`.location` khi câu có tín hiệu địa điểm (`_LOCATION_HINTS`) +
  `_CITY_ALIASES` cho vài thành phố lớn ("Sài Gòn"/"HCM"→"ho chi minh"). `corpus.py` thêm khối thống kê
  `noi_lam_viec_mong_muon`. Các trường mong muốn khác (level/position/job_type/marital/language) hiện
  CHỈ query được qua ORM, CHƯA nối vào bộ so khớp NLP — pass sau nếu cần.
