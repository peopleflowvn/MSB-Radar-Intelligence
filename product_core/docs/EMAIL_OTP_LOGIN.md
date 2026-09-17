# Đăng nhập Email OTP qua Resend

Radar có ba loại đăng nhập: `local` (username/mật khẩu), `tntalent` và `msb`
(mã 6 số gửi email). User Email OTP phải được tạo trước, active, gán đúng role
và có `username` hoặc trường email là email nhận thư.

Màn hình login chỉ có một ô username/email. Domain nằm trong danh sách OTP của
admin tự chuyển sang gửi/nhập mã; mọi username/email khác chuyển sang nhập mật
khẩu local. Tài khoản local có thể dùng **Quên mật khẩu** để nhận mã 6 số tại
email đã gắn với user và đặt mật khẩu mới.

## Cấu hình trên Hub

Đăng nhập bằng admin Radar, vào **Quản trị → Email OTP** và nhập:

- Resend API key dạng `re_...` với quyền `sending_access`;
- Email người gửi thuộc domain đã xác minh trong Resend;
- Tên hiển thị, Reply-to (nếu có), tiêu đề;
- domain Email OTP được phép cho TNTalent và MSB, thời gian chờ gửi lại và số lần thử;
- sau cùng bật **Đăng nhập Email OTP**.

API key được mã hóa trong database bằng khóa `SECRET_KEY` của Hub, không hiện lại
trên API/UI và không được đưa vào `.env`. Không đổi `SECRET_KEY` khi chưa có kế
hoạch chuyển đổi vì key đã lưu sẽ không giải mã được.

## Việc cần làm trên Resend

1. Tạo Resend account, thêm domain gửi mail (khuyến nghị một subdomain như
   `notify.example.com`).
2. Thêm các DNS SPF/DKIM Resend cung cấp và chờ domain Verified.
3. Tạo API key chỉ có `sending_access`.
4. Dùng bất kỳ email thuộc domain đã verify làm From trong Hub.
5. Tạo một user TNTalent và một user MSB thử nghiệm, rồi xác nhận nhận/thử mã.

Không cần nhận email inbound hay quyền Microsoft Entra. Domain gửi phải được
xác minh; không dùng `resend.dev` để gửi cho toàn bộ nhân sự.

## Webhook và hộp thư trong Hub

Vào **Quản trị → Email OTP → Webhook & Hộp thư Resend**, copy URL webhook Hub
hiển thị. Trong Resend, tạo Webhook dùng URL đó và chọn tối thiểu:

- `email.received` để Hub nhận thư inbound;
- `email.sent`, `email.delivered`, `email.bounced`, `email.failed` để theo dõi trạng thái gửi.

Sao chép **Signing Secret** (`whsec_...`) từ webhook Resend vào Hub, bật **Lưu
email inbound vào Hộp thư Hub**, rồi lưu cấu hình. Hub xác minh chữ ký Svix trên
raw payload, chống webhook lặp theo `svix-id`, sau đó mới lưu event. Với
`email.received`, Hub lấy text/HTML/headers/metadata đính kèm bằng Receiving API
và hiển thị phần text ở mục **Hộp thư Resend**.

Webhook không tự tạo một địa chỉ nhận thư. Trên Resend phải bật Receiving cho
domain/subdomain, hoặc dùng địa chỉ `*.resend.app`, rồi thiết lập MX nếu dùng
domain riêng. Nội dung inbound có thể chứa dữ liệu cá nhân; chỉ admin Radar xem
được và cần áp dụng chính sách lưu giữ dữ liệu phù hợp.

## Template OTP

Admin chỉnh HTML template tại **Quản trị → Email OTP**. Chỉ ba biến được thay:
`{{code}}`, `{{expires_minutes}}`, `{{app_name}}`. Không đặt mã OTP cố định
trong template. Template được dùng cho mọi email OTP tiếp theo.

## Bảo mật vận hành

- OTP có 6 số, hết hạn cố định sau 10 phút, chỉ dùng một lần.
- Mã chỉ lưu HMAC; log không chứa mã hoặc API key.
- Hub giới hạn gửi lại mặc định 60 giây và tối đa 5 lần nhập sai.
- Tài khoản, đổi mật khẩu hoặc loại đăng nhập vẫn thu hồi session cũ.
- Phiên đăng nhập tồn tại một tuần kể từ lúc xác thực; dùng HTTPS production và chỉ cấp quyền admin Hub cho người cần cấu hình.
