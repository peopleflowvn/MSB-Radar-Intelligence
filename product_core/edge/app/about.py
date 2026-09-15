# -*- coding: utf-8 -*-
"""Nội dung giới thiệu, hướng dẫn và FAQ hiển thị trong ứng dụng."""

AUTHOR_NAME = "Lê Hoàng Tùng"
AUTHOR_EMAIL = "tunglehoang.vn@gmail.com"
AUTHOR_SITE = "tunghr.io.vn"
AUTHOR_SITE_URL = "https://tunghr.io.vn"

INTRO = """\
MSB Radar Edge giúp tải CV từ tài khoản tuyển dụng về máy, đồng thời lưu thông tin ứng viên
vào một kho dữ liệu thống nhất để tìm kiếm, lọc và xuất báo cáo. Phần mềm tự nhận biết hồ
sơ đã tải, hỗ trợ tiếp tục sau gián đoạn và có thể chạy định kỳ để lấy CV mới.

Hiện ứng dụng hỗ trợ TopCV, VietnamWorks và CareerViet trên cùng một kho dữ liệu ứng viên.
Các nguồn tuyển dụng khác sẽ được bổ sung trong những phiên bản tiếp theo."""

GUIDE = """\
## Bắt đầu sử dụng

### 1. Hoàn tất cấu hình

- Mở **Cấu hình**.
- Nhập tài khoản của nguồn tuyển dụng cần dùng và chọn thư mục lưu CV.
- Chọn nơi lưu cơ sở dữ liệu `.db`.
- Giữ mức tải song song mặc định nếu chưa cần tối ưu.
- Bấm **Lưu Cấu Hình** và chờ thông báo xác nhận từ MSB Radar Edge.

Thông tin đăng nhập và phiên Chrome chỉ được lưu trên máy đang sử dụng. Nếu nguồn tuyển dụng yêu cầu
captcha hoặc OTP, hãy hoàn tất trực tiếp trong cửa sổ Chrome; ứng dụng sẽ tự chạy tiếp.

### 2. Đồng bộ lần đầu

- Mở **Tải CV** và chọn TopCV, VietnamWorks hoặc CareerViet.
- Bấm **Tải tất cả CV** để đồng bộ kho hồ sơ lần đầu.
- Theo dõi tiến độ, số đã xử lý, số tải mới và số lỗi ngay trên màn hình.
- Có thể bấm **Dừng** bất cứ lúc nào. Sau đó dùng **Tiếp tục** để chạy từ trang gần nhất
  chưa hoàn tất; hồ sơ đã tải thành công sẽ được tự động bỏ qua.

Nếu muốn xử lý từ dữ liệu cũ nhất về mới nhất, chọn phạm vi trang và bật **Tải ngược**.

### 3. Vận hành hằng ngày

- Dùng **Chỉ tải CV mới** để kiểm tra nhanh các lượt ứng tuyển phát sinh.
- Dùng **Thử lại CV lỗi** để chỉ tải lại các hồ sơ chưa thành công.
- Không cần chạy lại toàn bộ danh sách sau mỗi lần mở ứng dụng.

Chế độ **Chỉ tải CV mới** bắt đầu từ trang mới nhất, bỏ qua hồ sơ đã tải và dừng sau khi
xác nhận đã đi qua vùng chỉ còn hồ sơ cũ.

### 4. Thiết lập hẹn giờ

Trong **Cấu hình**, thiết lập:

- **Tần suất lặp lại:** số phút giữa hai lần kiểm tra, tối thiểu 5 phút.
- **Chế độ quét:** nên chọn *Chỉ tải CV mới* để chạy nhanh và giảm tải cho nguồn tuyển dụng.
- **Giờ chạy lần đầu:** để trống để chạy ngay, hoặc nhập `HH:MM`.
- **Tự động bật khi mở:** dùng khi muốn lịch hoạt động lại sau mỗi lần mở ứng dụng.
- Bật công tắc hẹn giờ rồi bấm **Lưu Cấu Hình** để áp dụng tất cả thay đổi cùng lúc.

Ứng dụng phải đang mở để lịch hoạt động. Mỗi lần tìm thấy CV mới, MSB Radar Edge sẽ gửi
thông báo Windows. Có thể dùng **Thử Thông Báo Windows** để kiểm tra quyền thông báo.

### 5. Tra cứu và xuất dữ liệu

- Mở **Dữ liệu ứng viên** để tìm theo tên, email, điện thoại, vị trí hoặc mã CV.
- Dùng bộ lọc nguồn, vị trí, tình trạng tải và khoảng ngày để thu hẹp kết quả.
- Mở chi tiết ứng viên để xem hoặc mở file CV.
- Chọn các cột cần hiển thị trước khi xuất báo cáo.
- Xuất Excel/CSV cho dữ liệu bảng; xuất ZIP khi cần gửi kèm file CV.

### 6. Sử dụng trên nhiều máy

- Trỏ các máy về cùng thư mục CV và cùng file `.db` nếu cần dùng chung dữ liệu.
- Chỉ để **một máy tải CV tại một thời điểm**; các máy còn lại nên dùng để tra cứu.
- Chờ dịch vụ đồng bộ đám mây hoàn tất trước khi mở dữ liệu trên máy khác.
- Không sao chép `cauhinh.json` hoặc Chrome profile cho người khác; mỗi máy nên đăng nhập
  bằng tài khoản được cấp riêng.

## Câu hỏi thường gặp

### Tôi đã đổi tần suất nhưng lịch chưa thay đổi?

Hãy bấm **Lưu Cấu Hình**. Tất cả trường hẹn giờ chỉ được áp dụng cùng lúc sau thao tác này.
Nếu lịch đang chạy, thời điểm chạy tiếp theo sẽ được tính lại ngay theo chu kỳ mới.

### Vì sao bấm lưu nhưng không thấy thông báo Windows?

Kiểm tra **Focus Assist/Do not disturb** và quyền thông báo của Windows, sau đó bấm
**Thử Thông Báo Windows**. Ứng dụng vẫn hiển thị xác nhận ngay trong giao diện kể cả khi
Windows hoặc chính sách của công ty chặn toast.

### Chạy lại có tạo hồ sơ trùng không?

Không. Mỗi lượt ứng tuyển được nhận diện bằng nguồn và mã CV. Hồ sơ đã tải thành công sẽ
được bỏ qua. Một ứng viên nộp vào vị trí khác có mã lượt ứng tuyển mới nên vẫn được ghi nhận.

### “Chỉ tải CV mới” khác “Tải tất cả CV” thế nào?

**Tải tất cả CV** rà toàn bộ phạm vi và phù hợp cho lần đồng bộ đầu tiên. **Chỉ tải CV mới**
ưu tiên các trang mới nhất và dừng sớm khi không còn phát sinh mới, phù hợp để chạy hằng ngày.

### Vì sao có lỗi “nội dung tải về không phải file CV hợp lệ”?

TopCV đôi khi trả về trang lỗi, JSON hoặc một định dạng file có header không chuẩn thay vì
file CV. MSB Radar Edge kiểm tra đường tải nhanh rồi thử lại trong phiên Chrome. Hãy dùng
**Thử lại CV lỗi**; nếu vẫn tải tay được nhưng ứng dụng còn lỗi, gửi mã CV và dòng nhật ký
để kiểm tra đúng phản hồi mà TopCV đã trả về.

### Dừng giữa chừng thì tiếp tục thế nào?

Bấm **Tiếp tục** một lần. Ứng dụng lấy checkpoint gần nhất, giữ đúng phạm vi và chiều tải.
Nếu dừng giữa một trang, trang đó được quét lại để bảo đảm không bỏ sót, còn CV đã xong sẽ
được bỏ qua.

### Có nên tăng số CV tải song song?

Mức mặc định cân bằng giữa tốc độ và ổn định. Chỉ tăng dần khi mạng ổn định; mức quá cao có
thể khiến TopCV giới hạn tần suất, phát sinh captcha hoặc làm số lượt lỗi tăng.

### CV và dữ liệu được lưu ở đâu?

File CV nằm trong thư mục đã chọn. Thông tin ứng viên nằm trong file SQLite `.db`. Cấu hình
và nhật ký được lưu cục bộ theo thư mục ứng dụng; có thể xuất Excel/CSV bất cứ lúc nào.

### Cảnh báo máy khác đang chạy có nghĩa gì?

Một máy khác vừa cập nhật cùng cơ sở dữ liệu. Hãy dừng một trong hai máy và chỉ tiếp tục khi
chắc chắn không còn tiến trình tải khác để tránh xung đột dữ liệu hoặc phiên TopCV.
"""

NOTE = ("MSB Radar Edge chỉ truy cập dữ liệu thuộc tài khoản tuyển dụng của người dùng và "
        "sử dụng chức năng tải CV do nguồn tuyển dụng cung cấp.")
