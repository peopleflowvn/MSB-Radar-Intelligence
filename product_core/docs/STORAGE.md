# Lưu trữ file

**Master Plan:** mục 44
**Vị trí:** `server/core/storage.py`

---

## 1. Quyết định: mặc định lưu trên VPS Oracle

Master Plan mục 44 ghi Cloudflare R2. Sau khi cân nhắc, **mặc định đổi thành ổ đĩa
VPS**, R2 giữ lại làm lựa chọn bật bằng cấu hình — cùng nguyên tắc với lớp LLM
provider: không khoá nghiệp vụ vào một nhà cung cấp.

### Vì sao đủ dùng

| | |
|---|---|
| Oracle Always Free | **200 GB** block storage |
| Kho CV hiện tại | ~20.000 hồ sơ |
| Cỡ trung bình một CV | ~200 KB |
| **Tổng ước tính** | **~4 GB** |

Còn thừa gấp 50 lần. Và vì đặt tên file theo **mã băm nội dung**, cùng một CV tải về
từ TopCV lẫn VietnamWorks chỉ chiếm một chỗ.

### Đánh đổi — phải biết rõ

| | `local` (mặc định) | `r2` |
|---|---|---|
| Thiết lập | Không cần gì | Tài khoản + 4 khoá |
| Nhân bản | **Không.** Một ổ đĩa duy nhất | Có |
| Sao lưu | **Việc của bạn** | Cloudflare lo |
| Phí ra mạng | Băng thông VPS | Miễn phí |
| Rủi ro lúc demo | Ít hơn — không phụ thuộc dịch vụ ngoài | Thêm một chỗ có thể hỏng |

**VPS hỏng là mất file.** Metadata trong PostgreSQL vẫn còn, nên biết mất những gì —
nhưng file thì không lấy lại được. Xem mục 4.

Chuyển sang R2 về sau chỉ là đổi biến môi trường cộng một lần chép dữ liệu; nghiệp vụ
không phải sửa dòng nào.

---

## 2. Cách đặt tên file

```text
filestore/
└── ab/
    └── cd/
        └── abcd…64-ky-tu-sha256.pdf
```

**Tên theo nội dung, không theo tên file gốc.** Tên gốc nằm trong metadata ở PostgreSQL.

Chia hai tầng thư mục theo 4 ký tự đầu của mã băm: 20 nghìn file trong **một** thư mục
làm mọi thao tác thư mục chậm thấy rõ trên ext4. Chia 256 nhánh giữ mỗi nhánh vài trăm file.

Ghi ra file `.part` rồi đổi tên: tiến trình chết giữa chừng sẽ không để lại một file
cụt mà mã băm nói là đầy đủ.

Khoá đến từ dữ liệu nên **có chốt chặn duyệt thư mục** — `../` bị chặn trước khi chạm
hệ thống file.

### Parsing bù trên Hub

Sau pha tải file, nếu Edge chưa gửi `parsed_text`, Hub trích lớp chữ và gọi tác vụ AI
`cv_parsing` để chuẩn hóa trung thực, sau đó lưu cả bản extractor và bản AI nếu chúng khác nhau.
Lỗi AI không làm upload Edge thất bại; trạng thái/lỗi nằm trên Document. Xử lý tồn đọng hoặc thử
lại các file lỗi bằng:

```bash
python manage.py parse_missing_cvs --limit 100
python manage.py parse_missing_cvs --limit 100 --retry-failed
```

---

## 3. Cấu hình

Mặc định không cần đặt gì. Trên VPS chỉ nên trỏ ra ngoài thư mục mã nguồn:

```bash
FILE_STORAGE_BACKEND=local
FILE_STORAGE_ROOT=/var/lib/msbradar/filestore
```

Chuyển sang R2:

```bash
FILE_STORAGE_BACKEND=r2
R2_BUCKET=msbradar-cv
R2_ACCOUNT_ID=...
R2_ACCESS_KEY=...
R2_SECRET_KEY=...
```

Backend `r2` cần `boto3` (`pip install boto3`) — cố ý **không** để trong
`requirements.txt` vì mặc định không dùng tới.

---

## 4. Sao lưu — bắt buộc khi dùng `local`

Đây là cái giá của việc chọn ổ đĩa VPS. Tối thiểu:

```bash
# CSDL: nhỏ, sao lưu thường xuyên
docker compose exec db pg_dump -U msbradar msbradar | gzip > /backup/db-$(date +%F).sql.gz

# File: lớn nhưng chỉ thêm chứ không sửa, nên rsync tăng dần là đủ
rsync -a --delete /var/lib/msbradar/filestore/ /backup/filestore/
```

Đưa `/backup` sang chỗ khác — cùng ổ đĩa với dữ liệu gốc thì không phải sao lưu.
Oracle Object Storage có 20 GB miễn phí, dùng làm đích sao lưu rất hợp.

---

## 5. Còn thiếu

- [x] ~~Edge chưa gửi file CV lên~~ — Phase 5, Edge đồng bộ file CV thật, không chỉ metadata nữa
- [x] ~~Endpoint tải file có kiểm tra quyền~~ — `talent/views.py::document_download` sau
  `@permission_classes([RequiresTalent])`, và mỗi lượt tải được `AccessLog` ghi riêng với
  `action=download` (xem `docs/ACCESS_CONTROL.md`)
- [ ] URL ký sẵn (presigned) khi chuyển sang R2, để không phải chuyển tiếp qua Django — `R2Storage` đã
  có trong `server/core/storage.py` nhưng file vẫn đi qua Django, chưa phát URL ký sẵn trực tiếp
- [ ] Cảnh báo khi ổ đĩa sắp đầy (`usage()` đã trả `disk_free_bytes`)

## Kho CV: preview, OCR và worker Hub

Edge chỉ chịu trách nhiệm đưa file gốc vào kho. Không gọi AI trong request Edge:
chạy worker Hub riêng để tạo preview, OCR CV scan và parsing bù an toàn.

```powershell
cd server
python manage.py parse_missing_cvs --loop --interval 20
```

Trong production, chạy lệnh này như một service riêng. Cấu hình `MSB_AI_PROVIDER_CV_OCR`
phải trỏ đến provider/model có hỗ trợ vision. PDF scan được render tối đa 10 trang rồi gửi
AI OCR; lỗi vẫn được lưu trên hồ sơ và có thể chạy lại bằng `--retry-failed`.

Preview inline chỉ cho PDF, ảnh và text thuần. File Office được Hub chuyển bằng LibreOffice
headless thành PDF, nên trình duyệt không được nhúng trực tiếp file Office hoặc MIME không tin cậy.
