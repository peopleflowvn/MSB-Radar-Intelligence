# Checklist đưa MSB Radar vào sử dụng

## 1. Đã được kiểm chứng tự động

- Chạy `scripts/quality_check.ps1` và chỉ triển khai khi tất cả bước đạt.
- Migration không còn thiếu.
- Edge tests, Django tests, Ruff, ESLint, TypeScript và production build đều đạt.
- `npm audit` không còn lỗ hổng đã biết.
- Ma trận API đã được kiểm tra cho Recruiter, RM, Manager, Admin và Edge Operator.

## 2. Dùng nội bộ trên máy local

1. Sao lưu `server/hub_dev.sqlite3`, thư mục file và state Edge.
2. Chạy `start_hub.bat`. Script sẽ kiểm tra Python/npm, Django và migration trước khi mở server.
3. Đăng nhập bằng từng vai trò cần dùng và đổi mật khẩu demo nếu còn tồn tại.
4. Không cho nhiều máy cùng ghi trực tiếp vào một file SQLite. Nếu có nhiều người dùng, triển khai PostgreSQL.

## 3. Triển khai nhiều người dùng

Trước khi mở truy cập:

- Cài Docker/Compose hoặc chuẩn bị PostgreSQL và Gunicorn tương đương.
- Sinh `SECRET_KEY` ngẫu nhiên ít nhất 50 ký tự; đổi key có thể làm mất khả năng giải mã API key AI đã lưu, nên đặt đúng ngay từ đầu.
- Đặt mật khẩu PostgreSQL mạnh.
- Điền tên miền vào `SITE_ADDRESS`, `ALLOWED_HOSTS` và HTTPS origin vào `CSRF_TRUSTED_ORIGINS`.
- Chạy `python manage.py check --deploy --fail-level WARNING` trong đúng môi trường production.
- Chạy `python manage.py migrate --no-input` và tạo tài khoản Admin đầu tiên.
- Thiết lập sao lưu PostgreSQL và volume `filestore` trước khi nhận dữ liệu thật.
- Xác minh chính sách lưu trữ, thời hạn lưu CV và quyền đọc dữ liệu với đơn vị tuân thủ.

## 4. Kiểm tra tích hợp bắt buộc bằng tài khoản thật

Unit test không thể chứng minh website bên thứ ba chưa đổi DOM hoặc phiên đăng nhập còn hiệu lực. Trước khi vận hành nguồn nào, dùng đúng tài khoản được cấp phép để smoke test:

- Đăng nhập và lấy một trang danh sách.
- Tải một CV thử, kiểm tra magic bytes và mở file.
- Đồng bộ bản ghi và file lên Hub.
- Mở Profile 360, tạo danh sách ứng viên và cập nhật trạng thái.
- Với RM, tạo một cơ hội thử, phân công, follow-up và đóng kèm lý do.

Provider không vượt qua smoke test phải để tắt; không coi unit test là xác nhận live.

## 5. Ngoài phạm vi phát hành hiện tại

- Collector Facebook tự động chưa có và không được giả lập bằng scraping khi chưa được phê duyệt.
- Phân quyền tầng bản ghi chi tiết giữa thành viên cùng nghiệp vụ được hoãn theo quyết định sản phẩm hiện tại.
- Hệ thống không tự gửi email/tin nhắn và không tự ra quyết định merge identity.
