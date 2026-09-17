# BASELINE — GenSync Radar → MSB Radar

**Ngày lập:** 19/08/2026
**Phase:** 0 (Baseline local) + 1 (Fork project)
**Mục đích:** Ghi lại chính xác trạng thái đang chạy được của GenSync Radar tại thời điểm fork,
để mọi thay đổi ở các phase sau đều có mốc so sánh non-regression.

---

## 1. Nguồn fork

| Hạng mục | Giá trị |
|---|---|
| Đường dẫn nguồn | `G:\My Drive\Project\GenSync Radar\GenSync_Radar` |
| Git remote nguồn | `https://github.com/peopleflowvn/GenSync-Radar.git` |
| Branch | `main` |
| Commit HEAD lúc fork | `5793585` — *fix(browser): allow slow first Chrome driver setup* |
| Working tree | Sạch (`git status --short` không trả về gì) |
| Phiên bản sản phẩm | GenSync Radar v2.5.1 |
| Đường dẫn đích | `G:\My Drive\Project\MSB_Radar` |

**Không clone git history.** Xem mục 7 (Bảo mật) để biết lý do bắt buộc.

---

## 2. Môi trường chạy được xác nhận

| Thành phần | Phiên bản |
|---|---|
| Python | 3.9.6 (`C:\Users\tungl\AppData\Local\Programs\Python\Python39`) |
| pip | 25.1.1 |
| pytest | 8.2.1 |
| ruff | 0.12.12 |
| OS | Windows 11 Home Single Language 10.0.26200 |

Runtime dependencies (`edge/requirements.txt`):

```text
pywebview==6.2.1            pythonnet==3.0.5
undetected-chromedriver==3.5.5   selenium==4.36.0
requests==2.32.5           urllib3==2.6.3
openpyxl==3.1.2            PyMuPDF==1.26.3
python-docx==1.2.0         pyinstaller==6.16.0
```

Ràng buộc đã biết: Requests/urllib3 còn 3 CVE được miễn trừ có tên
(`PYSEC-2026-2275`, `PYSEC-2026-141`, `PYSEC-2026-142`) vì bản vá cuối yêu cầu Python ≥ 3.10.
Khi nâng runtime lên 3.10+, bỏ miễn trừ và nâng Requests ≥ 2.33.0, urllib3 ≥ 2.7.0.

---

## 3. Kết quả baseline

| Kiểm tra | Nguồn (GenSync) | Sau fork + rebrand (MSB Radar Edge) |
|---|---|---|
| `python -m compileall app tests` | OK | OK |
| `python -m pytest -q` | **106 passed** / 9.43s | **120 passed** / 6.88s (106 kế thừa + 14 test mới cho migration state) |
| `python -m ruff check app tests` | OK | All checks passed |
| Build EXE (`build_exe.py`) | *chưa chạy — xem mục 8* | *chưa chạy* |

Số file nguồn được đưa sang: **63** (toàn bộ file được git theo dõi, trừ `chrome_profile/`).

---

## 4. Kiến trúc nguồn (nay là `edge/`)

Một giao diện duy nhất: PyWebView khởi động từ `main.py` → `app/web_api.py` → tài nguyên `app/web/`.
Giao diện Tk cũ đã bị loại bỏ từ trước.

| Module | Dòng/KB | Vai trò |
|---|---|---|
| `app/web_api.py` | ~94 KB | Biên API **duy nhất** giữa giao diện JS và nghiệp vụ (`js_api` của PyWebView) |
| `app/db.py` | ~93 KB | SQLite: schema, migration, backup, kiểm tra toàn vẹn, FTS5 |
| `app/engine.py` | ~33 KB | Điều phối tải: checkpoint, đồng thời, retry |
| `app/browser.py` | ~18 KB | Vòng đời Chrome/profile (thủ công + tự động) |
| `app/config.py` | ~19 KB | Cấu hình công khai, đường dẫn state |
| `app/cv_parser.py` | ~18 KB | Bóc tách CV đa định dạng + OCR |
| `app/secrets.py` | ~3 KB | Bí mật cục bộ qua Windows DPAPI |
| `app/state_paths.py` | ~4 KB | **Mới.** Nguồn sự thật về thư mục state cục bộ + chuyển đổi từ GenSync (§5.1) |
| `app/exporter.py` | ~8 KB | Xuất Excel/CSV |
| `app/lockfile.py`, `app/notifier.py`, `app/prerequisites.py`, `app/about.py` | — | Khoá tiến trình, toast Windows, kiểm tra WebView2/.NET, nội dung trợ giúp |
| `app/web/{index.html,app.js,styles.css}` | 157 + 194 + 125 KB | Toàn bộ giao diện (vanilla, không build step) |

### Providers

`app/providers/base.py` định nghĩa lớp trừu tượng `Provider`. Thêm nguồn mới = 3 hàm
(`connect()` / `iter_pages()` / `download()`) + khai báo trong `providers/__init__.py`.
Phần còn lại (tải song song, chống trùng, ghi DB, giao diện, hẹn giờ) dùng lại được ngay.

| Provider | File | Kích thước |
|---|---|---|
| TopCV | `topcv.py` | 35 KB |
| VietnamWorks | `vietnamworks.py` | 49 KB |
| CareerViet | `careerviet.py` | 36 KB |
| Việc Làm 24h | `vieclam24h.py` | 24 KB |
| ITViec | `itviec.py` | 19 KB |

**Đây là khuôn mẫu để thêm Facebook Provider ở Phase 10** — không cần phát minh cơ chế mới.

### Schema SQLite (`SCHEMA_VERSION = 5`)

| Bảng | Khoá chính | Ghi chú |
|---|---|---|
| `candidates` | `(source, account, cv_id)` | 40 cột; đây là hạt nhân sẽ map sang `SourceRecord` của Hub |
| `candidate_search` | FTS5 ảo | `unicode61 remove_diacritics 2`, đồng bộ qua trigger |
| `candidate_documents` | `(source, account, cv_id)` | Trạng thái parse, `full_text`, `file_hash`, `quality_score`, `needs_ocr` |
| `candidate_contacts` | `(source, account, cv_id)` | `email_key` / `phone_key` đã chuẩn hoá — **hạ tầng identity resolution đã có sẵn** |
| `candidate_extensions` | `(source, account, cv_id, namespace)` | Payload JSON có versioning — **chỗ gắn sync state mà không đổi schema lõi** |
| `meta` | `key` | Gồm cả `SCHEMA_VERSION` |
| `app_logs` | `id` | Log ứng dụng |

Ba quan sát quan trọng cho Phase 2/5:

1. `candidate_contacts` đã chuẩn hoá email (lowercase+trim) và phone (bỏ ký tự phân cách)
   bằng trigger SQL. Logic identity resolution ở Hub nên **thống nhất với quy tắc này**
   (lưu ý: phone hiện chưa chuẩn hoá về E.164 như mục 12 của Master Plan yêu cầu).
2. `candidate_extensions` cho phép thêm namespace `sync` (trạng thái đồng bộ, `edge_id`,
   `hub_person_id`) mà **không cần migration bảng `candidates`** → đường an toàn nhất cho Phase 2.
3. Khoá chính là bộ ba `(source, account, cv_id)`, tức là **cùng một người ứng tuyển ở 2 nguồn
   = 2 hàng**. Đây chính xác là bài toán mà `Person` của Hub sinh ra để giải.

---

## 5. Những gì đã đổi khi fork (Phase 1 — rebrand only)

### Đã đổi (hiển thị + metadata đóng gói)

| Hạng mục | Cũ | Mới |
|---|---|---|
| `app/version.py` `APP_NAME` | `GenSync Radar` | `MSB Radar Edge` |
| `app/version.py` `APP_VERSION` | `2.5.1` | `3.0.0` |
| Tên EXE (`build_exe.py` `NAME`) | `GenSyncRadar` | `MSBRadarEdge` |
| Thư mục build mặc định | `D:\GenSyncGen` | `D:\MSBRadarBuild` |
| Thư mục backup DB | `GenSync_Backup` / `gensync_*.db` | `MSB_Radar_Backup` / `msbradar_*.db` |
| Chuỗi hiển thị UI, toast, tài liệu | GenSync Radar | MSB Radar Edge |

`APP_VERSION` **bắt buộc là chuỗi số thuần `x.y.z`** — `build_exe.py:241` chuyển nó thành
tuple `filevers` cho VSVersionInfo. Không thêm hậu tố `-alpha`/`-rc`, sẽ vỡ build.

### Định danh runtime — đã tách khỏi GenSync (commit thứ 2)

Phase 1 ban đầu cố ý giữ nguyên các định danh này, sau đó tách hẳn trong một commit
riêng có cơ chế migration và test đi kèm.

| Định danh | Cũ | Mới | Cách chuyển |
|---|---|---|---|
| Thư mục state cục bộ | `%LOCALAPPDATA%\GenSyncRadar\` | `%LOCALAPPDATA%\MSBRadar\` | `app/state_paths.py` — xem §5.1 |
| Env probe/build | `GENSYNC_*` (6 biến) | `MSB_RADAR_*` | Đổi thẳng; chỉ `build_exe.py` đặt và đọc |
| Env toast | `CVHUB_TOAST_TITLE/MSG` | `MSB_RADAR_TOAST_TITLE/MSG` | Đổi thẳng; nội bộ `notifier.py` |
| Mô tả DPAPI | `"GenSync Radar"` | `"MSB Radar Edge"` | Đổi thẳng — an toàn, xem bên dưới |
| localStorage key | `gensync_*` | `msb_radar_*` | Helper `LS` trong `app.js`, tự chép key cũ |
| Prefix thư mục tạm | `gensync_cv_`, `gensync_ocr_`, `gensync-vnw-`, `gensync_probe_` | `msbradar_*` | Đổi thẳng; vòng đời trong một lần chạy |
| Keyframe CSS | `gensync-shake` | `msb-radar-shake` | Đổi thẳng |

**Vì sao đổi mô tả DPAPI là an toàn:** `CryptProtectData(pDataIn, szDataDescr, pOptionalEntropy, …)`
— chuỗi `"GenSync Radar"` nằm ở tham số **thứ 2 = `szDataDescr` (mô tả)**, không phải
`pOptionalEntropy` (tham số thứ 3, đang là `None`). Mô tả không tham gia vào khoá giải mã,
nên `secrets.json` đã mã hoá từ trước vẫn giải mã được bình thường.

Còn cố ý giữ tên GenSync (đúng như thiết kế): `LEGACY_STATE_FOLDERS`, `LEGACY_PREFIX`,
`version.BASE_PRODUCT` — đây là các mỏ neo để nhận ra và chuyển đổi bản cũ.

---

## 5.1. Cơ chế chuyển state cục bộ

`edge/app/state_paths.py` là nguồn sự thật duy nhất về nơi lưu state cục bộ:
kho bí mật DPAPI, 5 profile Chrome của các provider, `tessdata` OCR, catalog job VietnamWorks.

Quy mô thật đo được trên máy dev: **2,88 GB / 18.876 file**.

Module tách bạch hai việc, **không được gộp lại**:

| Hàm | Vai trò | Chạm đĩa? |
|---|---|---|
| `local_state_dir()` / `resolve_state_dir()` | Giải quyết đường dẫn đang có hiệu lực (mới nếu có, không thì cũ) | Không |
| `migrate_legacy_state()` | Thực sự di chuyển thư mục | Có |

**Vì sao tách:** nếu để việc di chuyển xảy ra như side effect của `import app.config`,
thì chỉ cần chạy `pytest` là đã dời mất 2,88 GB profile Chrome thật của người dùng.
Do đó `migrate_legacy_state()` **chỉ được gọi tường minh từ `main.py:migrate_local_state()`**
lúc khởi động, trước khi bất kỳ thành phần nào đọc kho bí mật hay mở profile.

**Vì sao dùng `os.rename` chứ không copy:** hai thư mục luôn cùng ổ đĩa nên đổi tên là
thao tác tức thì và nguyên tử — không có trạng thái chuyển dở dang. Copy 2,88 GB lúc
khởi động sẽ mất vài phút và nhân đôi dung lượng đĩa.

Các bảo đảm, mỗi cái có test tương ứng trong `tests/test_state_paths.py` (14 test):

```text
Chưa có state cũ          → không tạo gì, không lỗi
Có state cũ               → chuyển, giữ nguyên nội dung, để lại ghi chú chỉ đường
Đã có state mới           → không đụng vào state cũ, không ghi đè
Gọi lại lần hai           → không di chuyển gì thêm
os.rename ném OSError     → giữ nguyên hiện trạng, phiên này dùng tiếp thư mục cũ,
   (Chrome đang giữ file)   lần khởi động sau tự thử lại
MSB_RADAR_STATE_MIGRATION=off → bỏ qua hoàn toàn (chạy song song bản GenSync cũ)
```

`config.refresh_state_paths()` gán lại `SECRET_PATH` sau khi di chuyển. Các hàm khác
đọc `SECRET_PATH` qua global lúc chạy nên chỉ cần gán một chỗ là toàn ứng dụng thấy
đường dẫn mới.

**Hệ quả cần biết:** sau lần chạy MSB Radar Edge đầu tiên, **GenSync Radar bản cũ sẽ
mất toàn bộ phiên đăng nhập** (state đã dời sang chỗ mới). Đây là chủ đích — mục tiêu
là tách hẳn. Nếu cần chạy song song trong giai đoạn chuyển tiếp, đặt
`MSB_RADAR_STATE_MIGRATION=off` trước khi mở ứng dụng.

**Thay đổi hành vi duy nhất:** khi không có biến `LOCALAPPDATA` (Linux/dev), profile
Chrome chuyển từ `app_dir()/chrome_profile` sang `app_dir()/MSBRadar/chrome_profile`.
Trên Windows `LOCALAPPDATA` luôn tồn tại nên nhánh này không xảy ra khi chạy thật.

---

## 6. Cấu trúc repo sau Phase 1

```text
MSB_Radar/
├── edge/          ← toàn bộ GenSync Radar (63 file), đã rebrand, 106 test pass
│   ├── main.py            app/            tests/
│   ├── build_exe.py       scripts/        pyproject.toml
├── server/        ← trống — Django Hub (Phase 3)
├── web/           ← trống — React/Vite (Phase 3)
├── docs/          ← BASELINE.md + tài liệu kiến trúc
├── scripts/       ← quality_check cấp monorepo
├── .gitignore
├── README.md
└── MSB_RADAR_MASTER_DEVELOPMENT_PLAN_V2.md
```

Đặt code kế thừa vào `edge/` **ngay từ commit đầu** thay vì để ở gốc rồi di chuyển sau:
lúc này chi phí bằng 0 (mọi đường dẫn tương đối di chuyển cùng nhau, test xác nhận ngay),
còn nếu để đến Phase 3 thì sẽ là một commit dời file lớn chồng lên code đang phát triển.

---

## 7. ⚠️ BẢO MẬT — phát hiện ở repo nguồn

Hai vấn đề tồn tại trong repo GenSync Radar. Chúng **đã được chặn không lan sang MSB Radar**,
nhưng vẫn còn nguyên ở repo gốc trên GitHub và cần xử lý riêng.

### 7.1. `chrome_profile/` đang được git theo dõi

990 trong tổng số 1053 file được theo dõi thuộc `chrome_profile/`. `.gitignore` có dòng
`chrome_profile/` nhưng gitignore **không có tác dụng với file đã được add từ trước**.
Thư mục này chứa cookie phiên, cache và dữ liệu đăng nhập của trình duyệt dùng để vào
các cổng tuyển dụng.

### 7.2. `cauhinh.json` đã từng được commit kèm mật khẩu dạng văn bản thuần

Có mặt trong 3 commit: `82528fc`, `a360349`, `d6506a1`. Nội dung gồm email tài khoản tuyển
dụng nội bộ MSB và mật khẩu không mã hoá.

### Xử lý ở MSB Radar

- Fork bằng cách **liệt kê file theo dõi rồi copy có chọn lọc**, loại bỏ `chrome_profile/`
  — không dùng `git clone`.
- **Khởi tạo git repo mới, không mang theo history** → mật khẩu trong 3 commit cũ không
  đi vào repo mới.
- `.gitignore` cấp monorepo chặn `chrome_profile/`, `*_profile/`, `cauhinh*.json`, `*.db`,
  `*.log`, `CV/`, `.env*` ngay từ commit đầu tiên.

### Việc cần làm ở repo GenSync Radar (ngoài phạm vi dự án này)

1. Đổi mật khẩu tài khoản tuyển dụng đã lộ.
2. `git rm -r --cached chrome_profile` rồi commit.
3. Cân nhắc rewrite history (`git filter-repo`) nếu repo từng public hoặc có nhiều người truy cập.

---

## 8. Việc chưa làm / cần xác nhận thủ công

| Hạng mục | Trạng thái | Ghi chú |
|---|---|---|
| Build EXE | **Chưa chạy** | `python build_exe.py` cần PyInstaller đóng gói đầy đủ (~vài phút, tạo file lớn). Chạy trước lần phát hành đầu tiên. |
| Khởi động ứng dụng thật | **Chưa chạy** | Cần mở cửa sổ PyWebView, không tự động hoá được trong phiên này. |
| Kết nối thật tới 5 provider | **Chưa chạy** | Theo `ARCHITECTURE.md`, test kết nối thật không chạy tự động vì tạo phiên đăng nhập / CAPTCHA / khoá profile. Cần pilot thủ công từng tài khoản. |
| `pip-audit` | **Chưa chạy** | Nằm trong `scripts/quality_check.ps1`, cần mạng. |
| `build_icon.py` | Sẽ lỗi | Cần file logo MSB Radar (`MSB-Radar-Icon.png`) đặt cạnh thư mục repo. |

### Lỗi có sẵn trong GenSync Radar (không phải regression)

CSDL rất cũ — **25 cột, chưa có cột `account`, chưa có `schema_version`, chỉ có 2 bảng** —
không mở được: `sqlite3.OperationalError: no such column: account`. Nguyên nhân: các
trigger trong `_SCHEMA` tham chiếu `new.account` và được tạo **trước** khi
`_migrate_account_key()` kịp thêm cột.

Đã kiểm chứng bằng cách mở cùng file đó bằng **code GenSync Radar gốc** — lỗi y hệt.
Đây là lỗi có sẵn, không do việc fork gây ra. File gặp lỗi
(`GenSync Radar\du_lieu_ung_vien.db`, 20.556 ứng viên) là bản mồ côi nằm ở thư mục
ngoài, không phải CSDL đang dùng.

Chỉ cần xử lý nếu có máy nào còn chạy bản GenSync Radar rất cũ. Backlog:
`fix(db): migrate pre-account databases before installing contact triggers`.

---

## 9. Mốc so sánh cho các phase sau

Trước và sau **mọi** thay đổi ở `edge/`, chạy:

```powershell
cd edge
python -m compileall -q app tests
python -m pytest -q          # kỳ vọng: 106 passed (hoặc nhiều hơn, không ít hơn)
python -m ruff check app tests
```

Số test **không được giảm**. Bất kỳ test nào chuyển sang skip/fail đều là regression
cho tới khi được giải thích rõ trong commit message.
