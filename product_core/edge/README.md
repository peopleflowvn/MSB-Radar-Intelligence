# MSB Radar Edge

Tự động tải CV ứng viên từ các trang tuyển dụng về máy, lưu thông tin vào cơ sở dữ liệu,
và cho phép tra cứu / lọc / xuất báo cáo ngay trong phần mềm.

**Đã hỗ trợ:** TopCV · VietnamWorks · CareerViet · Việc Làm 24h · ITViec

**Tác giả:** Lê Hoàng Tùng · tunglehoang.vn@gmail.com · [tunghr.io.vn](https://tunghr.io.vn)

> Bản phát hành là **gói ZIP portable** cho Windows 10 22H2/Windows 11 64-bit. Giải nén toàn bộ rồi chạy `MSBRadarEdge.exe`. Ngoài Google Chrome, người dùng không cần cài Python, WebView2, Tesseract, gói OCR tiếng Việt hoặc LibreOffice.

---

## 1. Dành cho người dùng (không cần biết lập trình)

Chỉ cần tải **một gói ZIP**, giải nén nguyên thư mục và mở `MSBRadarEdge.exe`. Máy cần có Google Chrome; các runtime còn lại đã được đóng kèm.

| Bước | Việc cần làm |
|------|--------------|
| 1 | Mở `MSBRadarEdge.exe` |
| 2 | Tab **Cấu hình** → nhập tài khoản của nguồn cần dùng, chọn thư mục lưu CV → **Lưu cấu hình** |
| 3 | Tab **Tải CV** → chọn **TopCV**, **VietnamWorks** hoặc **CareerViet** → **TẢI TẤT CẢ CV** ở lần đầu |
| 4 | Về sau bấm **CHỈ TẢI CV MỚI**, hoặc bật tab **Hẹn giờ** để tự chạy định kỳ |
| 5 | Có CV lỗi? Bấm **🔄 Thử lại CV lỗi** - chỉ gọi lại đúng các mã đang lỗi, không quét lại toàn bộ |
| 6 | Tab **Dữ liệu ứng viên** để tìm kiếm, lọc, mở CV và xuất Excel/CSV |
| 7 | Tab **Hẹn giờ** → khi chạy tự động tìm thấy CV mới, phần mềm hiện **thông báo Windows** ở góc màn hình - không cần mở cửa sổ lên xem. Có nút "Thử thông báo" để kiểm tra máy có hiển thị được không |

Hướng dẫn chi tiết nằm ngay trong phần mềm, tab **Hướng dẫn**.

### File phần mềm tạo ra (cạnh file .exe)
`cauhinh.json` (cấu hình) · `nhatky.log` (nhật ký) · `chrome_profile/` (phiên đăng nhập)
Cơ sở dữ liệu `.db` và thư mục CV nằm ở nơi bạn chọn trong tab Cấu hình. Mặc định (chưa
có `cauhinh.json`) là **ngay cạnh file .exe** — copy `MSBRadarEdge.exe` sang máy khác, ổ đĩa/
đường dẫn nào cũng được, tự chạy được ngay không cần sửa gì.

### Dùng trên nhiều máy (máy dự phòng / chia sẻ đồng nghiệp)
- **Máy chỉ xem** (an toàn nhất): trỏ Cấu hình về cùng thư mục Google Drive với máy
  chính, nhưng KHÔNG bấm tải / bật hẹn giờ trên máy đó — chỉ tra cứu, tìm kiếm, xuất báo cáo.
- **Máy dự phòng cũng tự tải được**: có thể bấm tải trên cả 2 máy, nhưng chỉ nên chạy
  MỘT máy tại một thời điểm. Phần mềm tự cảnh báo nếu phát hiện máy khác đang chạy trên
  cùng dữ liệu (dựa vào file `.khoa.json` cạnh cơ sở dữ liệu, tự hết hạn sau 5 phút không
  hoạt động) — đây là cảnh báo "cố gắng hết sức" (Google Drive đồng bộ có độ trễ), không
  thay thế được việc chủ động thống nhất chỉ 1 máy chạy tải tại 1 thời điểm.

---

## 2. Vì sao dùng cơ sở dữ liệu thay cho Excel?

Dữ liệu ứng viên **bản chất là một cơ sở dữ liệu**, nên phần mềm lưu bằng **SQLite**
(một file `.db` duy nhất, không cần cài đặt gì):

| | Excel (.xlsx) | CSV | **SQLite** |
|---|---|---|---|
| Ghi thêm 1 dòng | Ghi lại **toàn bộ** file | Ghi lại toàn bộ | Chỉ ghi 1 dòng |
| Tìm / lọc 30.000 dòng | Nạp hết vào bộ nhớ | Quét tuần tự | **Tức thì (có chỉ mục)** |
| Mất điện giữa chừng | Dễ hỏng / mất dữ liệu | Dễ mất | **An toàn (giao dịch)** |
| Đang mở file khi chạy | **Kẹt, không ghi được** | Kẹt | Không ảnh hưởng |
| Nhiều nguồn tuyển dụng | Khó gộp | Khó gộp | **Chung một kho** |

Excel/CSV vẫn dùng được — nhưng ở vai trò **xuất dữ liệu** khi cần gửi cho người khác
(nút *Xuất Excel* / *Xuất CSV*, xuất đúng phần đang lọc).

---

## 3. Dành cho lập trình viên

```bash
pip install -r requirements.txt
python main.py               # chạy trực tiếp
python tests/smoke_test.py   # BẮT BUỘC chạy OK trước khi đóng gói - bắt lỗi cú pháp,
                              # id giao diện thiếu, tên hàm API gọi sai, lỗi tầng dữ liệu
python build_exe.py          # đóng gói ra dist/MSBRadarEdge.exe
```

### Cấu trúc
```
TopCV_Downloader/
├── main.py                 Điểm khởi động
├── build_exe.py            Đóng gói .exe
└── app/
    ├── config.py           Cấu hình (JSON, chỉnh trên giao diện)
    ├── db.py               SQLite: lưu trữ, chống trùng, tìm kiếm, lọc
    ├── exporter.py         Xuất Excel / CSV
    ├── engine.py           Điều phối tải (đa luồng, dừng an toàn, tiến độ)
    ├── browser.py          Tiện ích Chrome dùng chung
    ├── gui.py              Giao diện (CustomTkinter + ttk.Treeview)
    ├── about.py            Nội dung giới thiệu & hướng dẫn
    └── providers/
        ├── base.py         Giao diện chung cho mọi nguồn tuyển dụng
        ├── topcv.py        Provider TopCV
        ├── vietnamworks.py Provider VietnamWorks
        ├── careerviet.py    Provider CareerViet
        └── __init__.py     Danh mục nguồn tuyển dụng
```

### Thêm một nguồn tuyển dụng mới
1. Tạo file trong `app/providers/`, viết lớp kế thừa `Provider`.
2. Cài đặt `connect()`, `total_count()`, `iter_pages()`, `download()`.
   `iter_pages()` trả về các dict theo đúng tên cột trong `app/db.py`.
3. Khai báo lớp đó vào `ALL_PROVIDERS` trong `app/providers/__init__.py`.

Toàn bộ phần tải song song, chống trùng, ghi dữ liệu, giao diện, hẹn giờ, tìm kiếm
và xuất báo cáo dùng lại được ngay — không phải sửa thêm.

### Khoá chống trùng
`(nguồn, mã CV)` — mã CV là **mỗi lượt ứng tuyển**, không phải mỗi người.
Ứng viên cũ nộp vào vị trí mới ⇒ mã mới ⇒ vẫn ghi nhận thành dòng riêng.

### Hiệu năng thực đo (TopCV, ~30.000 hồ sơ)
| Cách làm | Tốc độ | Ước tính |
|---|---|---|
| Mở từng trang CV rồi lấy file | ~18,8 s/CV | 6–7 ngày |
| Gọi API, 1 luồng | ~1,95 s/CV | ~16 giờ |
| **Gọi API, 4 luồng (mặc định)** | **~0,69 s/CV** | **~6 giờ** |

Một tỉ lệ nhỏ CV trả về lỗi `422` — ứng viên đã gỡ CV. Đây là giới hạn từ phía nguồn
tuyển dụng, phần mềm sẽ tự thử lại ở lần chạy sau.
