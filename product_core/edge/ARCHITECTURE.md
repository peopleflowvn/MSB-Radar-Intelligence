# Kiến trúc MSB Radar Edge

Ứng dụng chỉ có một giao diện được hỗ trợ: PyWebView khởi động từ `main.py`, gọi
`app/web_api.py`, và hiển thị tài nguyên trong `app/web/`. Giao diện Tk cũ đã được loại
bỏ để tránh duy trì hai luồng cấu hình và đồng bộ khác nhau.

- `app/providers/`: khác biệt đăng nhập, liệt kê và tải của từng kênh.
- `app/engine.py`: điều phối dùng chung, checkpoint và tải đồng thời.
- `app/db.py`: lưu trữ, migration, sao lưu và kiểm tra toàn vẹn.
- `app/config.py`, `app/secrets.py`: cấu hình công khai và bí mật DPAPI cục bộ.
- `app/browser.py`: vòng đời Chrome/profile cho cả thao tác tay và tự động.
- `app/web_api.py`: biên API duy nhất giữa giao diện và nghiệp vụ.

Kiểm tra bắt buộc cho thay đổi nguồn nằm trong `scripts/quality_check.ps1`. Kiểm thử
kết nối thật với website không chạy tự động trong CI vì có thể tạo phiên đăng nhập,
captcha hoặc khóa profile; thực hiện pilot thủ công trên từng tài khoản qua nút trình
duyệt chung trước khi bật lịch tự động.

Runtime hiện còn hỗ trợ Python 3.9. Audit dependency có một ngoại lệ định danh
`PYSEC-2026-2275`, `PYSEC-2026-141` và `PYSEC-2026-142`: bản sửa cuối của
Requests/urllib3 yêu cầu
Python 3.10 trở lên. Khi nâng runtime lên Python 3.10+, bỏ hai ngoại lệ, nâng Requests
lên ít nhất 2.33.0 và urllib3 lên ít nhất 2.7.0.
