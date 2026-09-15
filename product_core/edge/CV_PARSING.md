# Bóc nội dung CV để tìm kiếm

## Cơ chế vận hành

- CV mới được xếp một vé vào hàng đợi ngay khi file được lưu thành công.
- Parsing tự chạy sau khi lượt tải kết thúc, không tranh CPU, ổ đĩa và quyền ghi database với Chrome.
- Backdate và CV mới dùng chung bảng `candidate_documents`; hàng đợi tồn tại qua lần đóng/mở ứng dụng và bản ghi đang chạy dở tự trở lại trạng thái chờ.
- Boolean Search tìm đồng thời dữ liệu hồ sơ và toàn bộ text trong `candidate_document_search` (FTS5).

## Backdate

Vào **Cấu hình → Nội dung CV & tìm kiếm**, chọn **Bóc nội dung CV cũ chưa parse**. Hệ thống chỉ xếp các CV đã tải có file nhưng chưa parse thành công hoặc parser đã đổi phiên bản. Có thể dừng sau file hiện tại và tiếp tục vào lần sau.

## Định dạng và OCR

Hỗ trợ PDF, ảnh PNG/JPG/TIFF, DOCX, PPTX, XLSX/XLSM, TXT, CSV, Markdown và RTF. PDF được đọc lớp text trước; nếu lượng text thấp, hệ thống dùng Tesseract OCR khi Tesseract cùng gói ngôn ngữ `vie`/`eng` đã có trên máy. Nếu OCR chưa sẵn sàng, CV được đánh dấu `needs_ocr` cùng lỗi cụ thể để xử lý lại sau, không coi là đã hoàn tất. Các định dạng Office cũ DOC/XLS/PPT được chuyển đổi bằng LibreOffice headless khi máy có LibreOffice; nếu thiếu, giao diện ghi rõ dependency cần cài.

Mặc định mỗi file được giới hạn 50 MB, 30 trang PDF và 200.000 ô bảng tính. Backdate xếp hàng theo lô 500 bản ghi; parsing dùng một worker và không được chạy đồng thời với tải CV, backup, xóa dữ liệu hoặc tổng hợp báo cáo lớn. Metadata và text CV nằm trong cùng một FTS5 corpus nên biểu thức như `Java AND Kubernetes` vẫn khớp khi `Java` nằm ở vị trí tuyển dụng còn `Kubernetes` chỉ có trong CV.

Khuyến nghị giữ chế độ mặc định **parse sau lượt tải**. Không chạy backdate đồng thời với tải CV.
