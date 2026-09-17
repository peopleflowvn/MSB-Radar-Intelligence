# BASELINE — MSB AI Hackathon 2026

**Ngày lập:** 29–30/08/2026 · **Master Plan:** §48 Task 1
**Mốc trước khi bắt đầu:** `e8ae56a5feb81c2620ae50c5a35fb9462e10ba5d`
**Mốc hiện tại:** `1169acfa18fd11e8324081a12a570baa03d2032e`
**Nhánh:** `feat/rb-growth-engine`

> Tài liệu này ghi lại **mốc so sánh non-regression** cho giai đoạn Hackathon,
> giống vai trò của `docs/BASELINE.md` cho giai đoạn fork. Mọi thay đổi từ đây
> tới ngày nộp phải đối chiếu với các con số dưới đây; số test **không được
> giảm**, và bất kỳ test nào chuyển sang skip/fail đều là regression cho tới khi
> có người giải thích rõ trong commit message.

---

## 1. Chất lượng tại mốc bắt đầu và mốc hiện tại

| Hệ thống con | Khi bắt đầu (`e8ae56a`) | Hiện tại (`1169acf`) |
|---|---|---|
| Hub — Django test | 714 pass | **882 pass** |
| Hub — ruff | sạch | sạch |
| Hub — migration còn thiếu | không | không |
| Giao diện — vitest | 11 pass | **14 pass** |
| Giao diện — tsc · eslint · build | sạch | sạch |
| Edge — pytest | 190 pass | **190 pass** (không tụt) |
| Edge — ruff | sạch | sạch |
| Agent — pytest | *chưa tồn tại* | **18 pass** |

Test Hub theo ứng dụng tại mốc hiện tại:

```text
rb       190      talent   134      ai       123      core     117
accounts  92      hiring    87      people    51      social    48
reports   18      agents    13
```

---

## 2. Những gì đã thay đổi trong giai đoạn này

| Commit | Hạng mục kế hoạch | Nội dung |
|---|---|---|
| `9ca97fa` | Task 3–5, 7 | RB Growth Engine: `OpportunitySuggestion`, chấm 5 chiều, cá nhân hoá, màn hình Cơ hội hôm nay |
| `feb0641` | P0-H | Che PII mặc định, hạn mức mở khoá, `ContactUnlockLog` |
| `2b98132` | P0-I | CI 5 job (server · web · edge · agent · rà bí mật) |
| `c126a08` | P0-A | Đo thu thập/hợp nhất; sửa lỗi `seed_demo` bỏ bước promote cột |
| `025d0a9` | P0-E | Quan sát AI theo từng provider; `docs/GREENNODE.md` |
| `4d24279` | Task 8.5 | Prospect Agent đúng hợp đồng AgentBase |
| `5e48e6f` | P0-F | Phương pháp đo tác động |
| `1169acf` | Task 6 | Tìm prospect bằng ngôn ngữ tự nhiên |

---

## 3. Đổi hợp đồng — thứ người khác cần biết

Ba thay đổi làm đổi hành vi mà mã gọi bên ngoài có thể phụ thuộc vào:

**`routing.route_signal()` trả `OpportunitySuggestion`, không còn trả
`RBOpportunity`.** Tín hiệu tài chính không sinh cơ hội ngay nữa; RM phải bấm
nhận. `routing.create_opportunities()` vẫn còn nguyên cho luồng RM tự tạo cơ hội
từ Profile 360.

**Mọi API danh sách trả email/SĐT đã che.** Không có tham số nào xin dữ liệu
chưa che. Cửa duy nhất là `POST /auth/contact-unlock/<id>/`, có đếm hạn mức và
ghi vết. Xuất CSV cũng che.

**`seed_demo` nay điền các cột được promote từ payload.** Trước đó dữ liệu demo
khác dữ liệu thật ở đúng chỗ khó nhận ra nhất — mọi màn hình nhóm theo nguồn
hiện "Không rõ nguồn".

---

## 4. Cách tái lập mốc này

```powershell
git checkout 1169acf

cd server
python -m pip install -r requirements.txt
python manage.py migrate
python manage.py seed_demo --reset
python manage.py test            # kỳ vọng 882 pass
python -m ruff check .

cd ..\web
npm ci
npm test && npm run typecheck && npm run lint && npm run build

cd ..\agent
python -m pip install -r requirements.txt pytest
python -m pytest tests -q        # kỳ vọng 18 pass

cd ..\edge
python -m pip install -r requirements-dev.txt
python -m pytest -q              # kỳ vọng 190 pass, KHÔNG được ít hơn
```

Hoặc chạy một lệnh: `.\scripts\quality_check.ps1`

---

## 5. Dữ liệu demo tại mốc này

Sau `python manage.py seed_demo --reset`:

```text
10 lượt ứng tuyển → 8 người   (2 lượt gộp vào người đã có)
1 người đến từ 3 nền tảng     ← khoảnh khắc "ba lượt hồ sơ, một con người"
TopCV 3 · VietnamWorks 3 · CareerViet 2 · ITviec 2
10 file CV
Tài khoản: admin · tuyendung · truongbophan · sales · vanhanh · quanly
Mật khẩu: mat-khau-demo-1234
```

Nhân vật chính: **Nguyễn Văn An** — TopCV 2023 (Data Analyst, 2 năm) →
VietnamWorks 2025 (Senior, 4 năm) → CareerViet 2026 (Senior, Power BI).
`core/tests_capture.py::SeedDemoCaptureTest` canh nhân vật này không biến mất.

---

## 6. Việc còn lại — không phải code

Phần kỹ thuật P0 đã đóng. Danh sách đầy đủ và trạng thái ở
`docs/HACKATHON_SCORECARD.md`. Tóm tắt:

1. Xác nhận đăng ký Luma (hạn 12/09) và tư cách CBNV — **chặn mọi thứ khác**.
2. Deploy agent lên AgentBase — cần IAM credentials + Ví Tổng của đội.
3. Chạy benchmark có kiểm soát — phương pháp ở `docs/HACKATHON_METRICS.md`.
4. Diễn tập demo 10 lần liên tiếp + quay video dự phòng.
5. Dựng pitch deck.
