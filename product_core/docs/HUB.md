# MSB Radar Hub

**Phase:** 3 (Hub Bootstrap) — hoàn thành
**Phạm vi:** auth, health, đăng ký Edge, trang quản trị, nhận dữ liệu đồng bộ.
**Chưa có:** Person / Identity / Signal — đó là Phase 4 (People Core).

---

## 1. Ngăn xếp

| Thành phần | Lựa chọn | Lý do |
|---|---|---|
| Backend | Django 4.2 LTS + DRF 3.14 | 4.2 là bản cuối còn hỗ trợ Python 3.9 — cùng runtime với Edge, nên một máy dev chạy được cả hai |
| CSDL | PostgreSQL 16 (thật) / SQLite (dev) | Chọn theo `DATABASE_URL`; dev chạy được mà không cần cài Postgres |
| Frontend | React 18 + TypeScript + Vite 6 + TanStack Query | Master Plan mục 6 |
| Web server | Caddy 2 | Tự xin và gia hạn TLS |
| Đóng gói | Docker Compose | Master Plan mục 45 |

Hub chạy Python 3.11 trong container; Edge ở lại 3.9 vì phụ thuộc pywebview/pythonnet
trên Windows. Hai runtime tách rời một cách có chủ đích.

---

## 2. Mô hình dữ liệu Phase 3

```text
Edge          một bản cài MSB Radar Edge trên máy đơn vị
  └── EdgeApiKey   nhiều khoá cùng lúc, để xoay khoá không phải dừng đồng bộ
SourceRecord  bàn nhận dữ liệu thô từ Edge
```

`SourceRecord` **là bàn nhận, không phải mô hình miền.** Nó cố ý ngu ngốc: nhận, khử
trùng lặp, lưu bền vững. Phân giải Person, gộp định danh, sinh Signal là Phase 4–5 và
sẽ **đọc từ bảng này**.

Tách như vậy có hai cái lợi cụ thể: Edge đồng bộ được ngay từ bây giờ, và khi logic
phân giải thay đổi thì chạy lại được trên dữ liệu đã nhận — không phải xin Edge gửi lại.

---

## 3. Bảo mật

### Khoá API chỉ lưu hash

Hub **không bao giờ** lưu khoá thô, giống nguyên tắc với mật khẩu. Khoá thô hiện đúng
một lần lúc cấp trong trang quản trị; mất thì cấp khoá khác.

Dùng sha256 trần chứ không phải PBKDF2/bcrypt — có chủ đích: khoá là 32 byte ngẫu nhiên
từ `secrets.token_urlsafe`, không phải mật khẩu người nghĩ ra, nên không có gì để tấn
công từ điển. Ngược lại, hàm băm chậm sẽ phải chạy trên **mọi** yêu cầu đồng bộ.

### Edge không phải người dùng

Edge là máy: không tài khoản, không phiên, không vào được trang quản trị. Vì vậy
`request.user` vẫn là `None` còn Edge đã xác thực nằm ở `request.auth` — đúng ngữ nghĩa
DRF cho khoá máy-với-máy.

Hệ quả: `IsAuthenticated` mặc định của DRF **không** dùng được cho endpoint của Edge
(nó xét `request.user`), nên có `IsAuthenticatedEdge` riêng. Và ngược lại, khoá API của
Edge **không** mở được endpoint quản trị — có test khẳng định điều này.

### Mặc định đóng

`DEFAULT_PERMISSION_CLASSES = [IsAuthenticated]`. Quên khai quyền cho một view thì view
đó bị chặn, chứ không phải bị lộ.

### Khoá bị chép sang máy khác

Một khoá gắn với đúng một `edge_id`. Đăng ký lại bằng `edge_id` khác trả **409**, không
âm thầm cướp danh tính — dấu hiệu gần như chắc chắn là khoá bị dùng lại trên máy thứ hai.

### SECRET_KEY

Chỉ có mặc định khi `DEBUG=True`. Chạy thật mà thiếu thì nổ ngay lúc khởi động, không
âm thầm chạy bằng khoá ai cũng biết.

---

## 4. Hub không tin Edge

Edge chạy trên máy văn phòng, có thể là bản cũ, bản lỗi, bản đang thử nghiệm.

| Tình huống | Cách xử lý |
|---|---|
| `entity_type` lạ | 400 — chỉ chấp nhận danh sách trắng |
| Thiếu `entity_key` | 400 |
| Giá trị quá dài | **Cắt cho vừa cột**, không từ chối — payload đầy đủ vẫn lưu nguyên vẹn |
| Trường lạ | **Giữ trong payload** — Edge bản mới không buộc Hub phát hành lại |
| Lô quá lớn | 413 |
| Một bản ghi hỏng | Chỉ bản ghi đó `rejected`; cả lô vẫn được xử lý |

**Hash nội dung do Hub tự tính, không lấy từ Edge.** Đây là cơ sở phân biệt `duplicate`
với `updated`; tin vào hash bên gửi nghĩa là một Edge lỗi có thể khiến Hub bỏ qua dữ
liệu đã thay đổi thật.

Một bản ghi hỏng **không được** kéo cả lô trả 500 — nếu không Edge sẽ gửi lại toàn bộ,
kể cả những bản đã lưu thành công.

---

## 5. Chạy trên máy

```powershell
cd server
pip install -r requirements.txt
$env:DEBUG="True"
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

CSDL là `server/hub_dev.sqlite3` khi chưa đặt `DATABASE_URL`.

Cấp khoá cho một Edge: vào `/admin/` → **Các Edge** → tạo bản ghi → chọn nó → hành động
**Cấp khoá API mới**. Khoá hiện một lần; chép ngay vào cấu hình Hub của Edge.

Frontend:

```powershell
cd web
npm install
npm run dev        # http://localhost:5173, proxy /api sang :8000
```

> ⚠️ **`npm install` không chạy được trong thư mục Google Drive.** Xem mục 7.

Chạy test:

```powershell
cd server
python manage.py test core        # 98 test
```

---

## 6. Triển khai

```bash
cp .env.example .env      # điền SECRET_KEY, POSTGRES_PASSWORD, SITE_ADDRESS
cd web && npm ci && npm run build && cd ..
docker compose up -d --build
docker compose exec hub python manage.py createsuperuser
```

`web/dist` được Caddy mount trực tiếp — không có container Node nào chạy trong môi
trường thật, tiết kiệm RAM trên VPS nhỏ.

`SECURE_PROXY_SSL_HEADER` đã đặt sẵn: Caddy kết thúc TLS rồi chuyển tiếp HTTP, thiếu
dòng đó Django tưởng mọi yêu cầu đều là HTTP và rơi vào vòng lặp chuyển hướng.

---

## 7. Ba nơi lưu dự án — đừng lẫn vai trò

Dự án **đã chuyển sang ổ cục bộ** ngày 19/08/2026.

| Nơi | Vai trò | Chứa gì |
|---|---|---|
| `D:\Project\MSB_Radar` | **Làm việc.** Nguồn sự thật. | Tất cả |
| GitHub | Chia sẻ, nộp bài hackathon | Chỉ những gì đã commit |
| `G:\My Drive\Project\MSB_Radar` | Sao lưu đầy đủ | Tất cả, **gồm cả bí mật và dữ liệu thật** |

Google Drive là nơi duy nhất giữ những thứ không được lên GitHub: `.env`,
`cauhinh.json`, CSDL ứng viên, file CV.

Đồng bộ ngược về Drive sau khi làm xong việc:

```powershell
.\scripts\sync_to_drive.ps1 -DryRun     # xem trước
.\scripts\sync_to_drive.ps1             # thực hiện
```

Script loại trừ `node_modules` và các thư mục cache — chúng dựng lại được từ
`package-lock.json`, và chính chúng là thứ Drive không chịu nổi. Nhưng **`.git` được
sao lưu**, nên bản trên Drive là một repo khôi phục được nguyên vẹn chứ không phải
một đống file rời.

### Vì sao phải chuyển

`npm install` trong `G:\My Drive\...` **thất bại**: lần đầu lỗi `EBADF: bad file
descriptor`, lần hai chạy quá 10 phút chưa xong. Nguyên nhân giống hệt lý do Edge cố ý
đặt profile Chrome ngoài thư mục đồng bộ — hàng chục nghìn file nhỏ trên một ổ ảo.

Đối chiếu sau khi chuyển sang ổ cục bộ: `npm install` **56 giây**, `tsc` sạch,
`vite build` ra 187 KB (59,5 KB gzip). Bộ test Edge cũng nhanh hơn — 12,2s so với 20,3s.

> **`.ps1` phải lưu kèm BOM UTF-8.** Windows PowerShell 5.1 đọc file script theo bảng
> mã ANSI khi không có BOM, nên mọi dấu tiếng Việt trong script sẽ làm hỏng bộ phân
> tích cú pháp. `sync_to_drive.ps1` đã lưu đúng.

---

## 8. Trạng thái các tính năng

Tất cả các hạng mục đồng bộ và mở rộng đã được hoàn thành:

- [x] ~~Đăng nhập ngay trên giao diện React~~ — Phase 5B, `docs/ACCESS_CONTROL.md`
- [x] ~~Lịch tự động gọi `runner.drain()` phía Edge theo `hub_sync_interval_min`~~ — `edge/app/sync/service.py::SyncService.start_auto`
- [x] ~~Tab cấu hình Hub trên giao diện Edge~~ — `edge/app/web/` + `web_api.py::save_hub_config`
- [x] ~~Đồng bộ document (file CV)~~ — Phase 5, xem mục 6.1
- [x] ~~Cloudflare R2 cho file (Master Plan mục 44)~~ — `server/core/storage.py::R2Storage`
- [x] ~~Vai trò và phân quyền theo module (Master Plan mục 38)~~ — Phase 5B, `docs/ACCESS_CONTROL.md`

