# HACKATHON SCORECARD — MSB Radar

**Mục tiêu:** Giải Nhất · Best Use of GreenNode · Best Pitch
**Hạn nộp:** EOD 23/09/2026 · **Hackday:** 25/09/2026
**Cập nhật gần nhất:** 30/08/2026 (sau audit tích hợp)
**Nhịp cập nhật:** 2–3 ngày/lần (Master Plan §46)

> Bảng này tồn tại để trả lời đúng một câu hỏi, mỗi lần mở ra:
> **Hôm nay còn lý do nào để giám khảo chấm dưới điểm tối đa?**
>
> Không phải nơi liệt kê tính năng đã làm. Một dòng chỉ được chuyển sang ✅ khi
> có **bằng chứng kiểm được** — không phải khi code đã viết xong.

---

## 0. HAI DÒNG CÓ THỂ XOÁ SỔ MỌI DÒNG KHÁC

Hai mục này không được chấm điểm Reach/Impact/Confident. Chúng chỉ có
đạt/không đạt, và không đạt thì mọi công sức còn lại bằng 0.

| # | Hạng mục | Hạn | Trạng thái | Ghi chú |
|---|---|---|---|---|
| 0.1 | **Đăng ký Luma cá nhân** cho từng thành viên (kể cả thi Solo) | EOD 12/09 | ✅ **Đã xác nhận** (30/08) | — |
| 0.2 | **Tư cách dự thi**: là CBNV MSB / TNEX / TNTALENT tại thời điểm dự thi | — | ✅ **Đã xác nhận** (30/08) | — |
| 0.3 | Chốt danh sách thành viên đội | EOD 12/09 | ⬜ | |
| 0.4 | Nộp đủ 3 hạng mục: Demo link · Git repo · Pitch deck PDF | EOD 23/09 | ⬜ | Thiếu 1 = loại. |

---

## 1. REACH

**Mục tiêu điểm:** 3/3 — *Đối tượng hưởng lợi · quy mô · tần suất phát sinh nhu cầu*

| Hạng mục | Bằng chứng cần có | Hiện trạng | Việc còn lại |
|---|---|---|---|
| Người dùng mục tiêu rõ ràng, có số ước tính | Slide + README nói rõ bao nhiêu Recruiter/RM hưởng lợi | ⬜ Chưa có con số | Ước tính quy mô đội tuyển dụng + đội RM bán lẻ |
| Bài toán tuyển dụng đã được xác thực | Trải nghiệm vận hành thật + phỏng vấn 3–5 người dùng | 🟡 Có bối cảnh thật, chưa có phỏng vấn ghi lại | Chạy validation trước 10/09 (§26) |
| Một People Core phục vụ cả hai nghiệp vụ | Cùng `Person` cho Talent và RB, không nhân bản | ✅ **Đã có** — `people.Person` + `TalentProfile`/`RBProfile`, có test canh không chép trường | — |
| Tần suất sử dụng hàng ngày | Recruiter mở `/hunts`, RM mở "Cơ hội hôm nay" mỗi ngày | ✅ **Đã có** — `/rb` mở ra là màn hình Cơ hội hôm nay | — |

---

## 2. IMPACT

**Mục tiêu điểm:** 3/3 — *AEV · cải thiện quy trình · phù hợp chiến lược*

> **Nguyên tắc tuyệt đối: không bịa số.** Mẫu nhỏ thì ghi rõ
> *"Controlled Hackathon Benchmark, n=…"*. Một con số đẹp không kiểm được sẽ
> thành câu hỏi không trả lời nổi trong phần Q&A.

| Chỉ số | Cách đo | Hiện trạng | Việc còn lại |
|---|---|---|---|
| Tỷ lệ thu thập & tập trung CV | Bản ghi thu được / bản ghi có thể thu, trên mẫu có kiểm soát | ⬜ Chưa đo | **Mẫu số không có sẵn** — phải đối chiếu tay trên mẫu nhỏ, không lấy từ dashboard |
| Thời gian tới shortlist dùng được | Thủ công vs Radar, cùng một nhu cầu tuyển | ⬜ Chưa đo | **Phương pháp đã có** — `docs/HACKATHON_METRICS.md` §3.1, cần người chạy |
| Tỷ lệ tái sử dụng hồ sơ cũ | Bao nhiêu hồ sơ cũ được tìm lại | ⬜ Chưa đo | Phương pháp §3.3; seed đã có nhân vật 3 nguồn |
| Hợp nhất nguồn → Person | 3 lượt ứng tuyển → 1 người | ✅ **Đo và trưng được** — `core/capture.py`, hiện trên Dashboard. Demo: 1 người / 3 nền tảng | — |
| Acceptance@10 | Recruiter/HM đánh dấu top 10 hữu ích/không | ⬜ Chưa đo | Phương pháp §3.2 — người đánh giá **không** được là người viết hệ thống |
| Tỷ lệ RM chấp nhận đề xuất | Accepted / tổng đề xuất | 🟡 **Dữ liệu đã ghi được** (`OpportunitySuggestion.status`) | Viết truy vấn chỉ số + đưa vào `rb/metrics.py` |
| Đề xuất khớp địa bàn/trọng tâm RM | So `personalized_score` với `priority_score` | 🟡 **Cơ chế đã có** (`UserWorkProfile`) | Cần RM khai báo thật trong lúc validation |
| Kết quả tiếp cận có cấu trúc | Phân bố `OpportunityOutcome.outcome` | 🟡 **Model đã có**, chưa có chỉ số | Bổ sung vào `rb/metrics.py` |

---

## 3. CONFIDENT

**Mục tiêu điểm:** 3/3 — *pain point đã xác thực · chất lượng demo · hàm lượng AI · thuyết trình*

| Hạng mục | Hiện trạng | Việc còn lại |
|---|---|---|
| Sản phẩm chạy được, tái lập từ repo | ✅ `README` có hướng dẫn; `seed_demo --reset` chạy thật qua pipeline thật | Kiểm lại bằng clone sạch |
| Bộ test | ✅ **904 backend + 221 edge + 18 agent + 21 web** (backend 714 → +190; edge 190 → +31) | Giữ không tụt |
| Lint / typecheck / build | ✅ ruff sạch; `scripts/quality_check.ps1` bao cả web | — |
| **CI (GitHub Actions)** | ✅ **Đã có** — 4 job: server (Python 3.9+3.11), web, edge (Windows), rà bí mật | Xác nhận xanh sau lần push đầu |
| AI có fallback tất định, nói rõ trạng thái | ✅ `ai/router.py` + fallback từ khoá ở mọi luồng LLM | — |
| Giải thích được (FACT/INFERENCE/UNKNOWN) | ✅ Talent đã có; ✅ RB có `evidence["why"]` 5 chiều | — |
| **Che PII + hạn mức mở khoá liên hệ** | ✅ **Đã có** — che vô điều kiện ở mọi đường ra kể cả CSV; hạn mức theo vai trò; `ContactUnlockLog` | — |
| RM không xem được file CV gốc | ✅ **Đã chặn** qua `RequiresRecruiting`, có test canh | — |
| Nhật ký truy cập dữ liệu cá nhân | ✅ `accounts.AccessLog` ghi xem/tìm/tải/xuất | — |
| Demo chạy 10 lần liên tiếp không lỗi | 🟡 **Hero flow có test tự động** cho cả Talent lẫn RB | Vẫn cần diễn tập tay 10 lần |
| Video dự phòng | ⬜ Chưa quay | Phase W4 |
| **Deploy trên GreenNode AgentBase** | 🟡 **Agent đã sẵn sàng**, chưa deploy | Cần IAM credentials + Ví Tổng của đội |

---

## 4. BEST USE OF GREENNODE

**Giá trị giải:** 10.000.000 VNĐ (ngang Giải Ba)
**Giám khảo riêng:** chuyên gia GreenNode chấm *"cách khai thác GreenNode AI Platform và chất lượng thiết kế AI Agent"*

| Hạng mục | Hiện trạng | Việc còn lại |
|---|---|---|
| GreenNode là provider mặc định | ✅ **Đã có** — `DEFAULT_ORDER[0] = "greennode"`, có cơ chế chống tuột khỏi chuỗi fallback | — |
| Ít nhất 2 luồng người dùng thấy được dùng GreenNode | ✅ Talent JD-parse + Social intent + RB agent | Xác nhận chạy live trong demo |
| Quan sát được: calls/latency/success/fallback theo từng provider | ✅ **Đã có** — `GET /ai/usage/` tách theo provider, có `fallback_calls`, độ trễ chỉ tính lượt thành công | — |
| **Agent chạy thật trên AgentBase, có public endpoint** | 🟡 **Code sẵn sàng** (`agent/`, 18 test, Docker build trong CI) | **Chạy lệnh deploy** — cần tài khoản GreenNode của đội |
| Container đúng hợp đồng Runtime (cổng 8080 + `GET /health`) | ✅ **Đã có** — `agent/`, có test canh cổng và `/health` | — |
| `docs/GREENNODE.md` vẽ rõ ranh giới 3 khối | ✅ **Đã viết** — theo đúng khung Intelligence/Capabilities/Runtime của BTC | — |
| Kiến trúc split-cloud được nói rõ trong deck | ❌ Chưa | Slide 4/7 |
| CI/CD tự động lên AgentBase | ⬜ Chưa | CI nền đã có; thêm job deploy sau Task 8.5 |

---

## 5. BEST PITCH

| Hạng mục | Hiện trạng | Việc còn lại |
|---|---|---|
| Vấn đề hiểu được trong <20 giây | 🟡 Câu chuyện "Pre-ATS Data Black Hole" đã rõ trên giấy | Rút thành 1 câu nói |
| Đúng 1 persona chính trong demo | ⬜ | Chốt: Recruiter |
| Demo chạy đúng thời lượng | ⬜ | Dựng bản 3 phút + 5 phút |
| Đúng 3–5 con số impact | ⬜ Chưa có số | Phụ thuộc mục 2 |
| 1 câu về GreenNode | ✅ **Đã chốt** — `docs/GREENNODE.md` mục 9 | Thêm câu Runtime sau Task 8.5 |
| 1 câu về moat kỹ thuật | ✅ "Thu thập đa nguồn tự động trước ATS" | — |
| Khoảnh khắc mở rộng sang RB | ✅ **Diễn được đầu-cuối** — Social signal → đề xuất → WHY NOW → RM nhận | Diễn tập cho khớp thời lượng |
| Câu kết thuộc lòng | ✅ Đã chốt: *"Đúng người · Đúng nhu cầu · Đúng thời điểm"* | Học thuộc |
| Ngân hàng câu hỏi Q&A | ⬜ | Phase W4 |
| Trình bày được khi demo hỏng | ⬜ | Cần video dự phòng |

---

## 6. NGÂN SÁCH GREENNODE

| Hạng mục | Trạng thái | Ghi chú |
|---|---|---|
| Ví Tổng còn ≥ 2.000.000 VNĐ | ⬜ Chưa theo dõi | Ví Tổng về 0 = container sập, kể cả giữa Hackday |
| Chuyển sang ví MaaS theo từng đợt nhỏ | ⬜ | **Chuyển là không hoàn lại được** |
| Ước tính token cho 1 lượt demo × 10 lần diễn tập + 1 lần thi thật | ⬜ | Làm trước Phase W4 |

---

## 7. NHẬT KÝ CẬP NHẬT

### 29/08/2026 — Ngày 0

**Đã xong hôm nay:**
- Re-baseline: 714 test pass, ruff sạch (mốc không được để tụt).
- Rà toàn bộ mã nguồn đối chiếu từng tuyên bố P0 trong kế hoạch — kết quả ở §52
  của `MSB_RADAR_WINNING_MASTER_DEVELOPMENT_PLAN_V4.md`.
- Đọc Hacker Guide BTC lần đầu → phát hiện điều kiện giải Best Use of GreenNode
  là *"được xây dựng trên GreenNode AI Platform"*, không chỉ gọi API. Nâng việc
  deploy AgentBase từ tuỳ chọn lên P0 (Task 8.5).
- **RB Growth Engine (Task 3–5, 7):** `OpportunitySuggestion` +
  `ProductValueConfig` + `OpportunityOutcome`, chấm điểm 5 chiều tất định,
  Next Best Action, API Cơ hội hôm nay, nối lại Social → đề xuất.
  **765 test pass (+51).**

**Bổ sung buổi chiều — tự soát + cá nhân hoá:**
- **Tự soát code vừa viết, tìm ra 3 lỗi thật:**
  1. `IntegrityError` bị bắt ngay trong `atomic` — chạy đúng trên SQLite (test)
     nhưng **hỏng trên PostgreSQL** (transaction bị huỷ, mọi truy vấn sau đó
     ném lỗi). Tức là sẽ hỏng đúng lúc chạy thật. Đã sửa bằng savepoint lồng,
     theo đúng khuôn `routing.create_opportunities()` đã dùng từ trước.
  2. Lọc theo sản phẩm ở `/rb/today/` chạy **sau** khi đã cắt `limit` — hỏi 20
     dòng vay mua nhà thì có thể chỉ nhận 2. Đã đưa vào truy vấn.
  3. Thiếu `select_related("person__rb_profile")` → mỗi thẻ tốn thêm 1 truy vấn.
- **Cá nhân hoá theo khai báo của RM** (`accounts.UserWorkProfile`): địa bàn,
  sản phẩm trọng tâm, phân khúc, ghi chú tự do. Điểm gốc **không bị ghi đè** —
  cá nhân hoá tính lúc đọc, giới hạn ±20 điểm, trả về cùng lý do.
  **785 test pass (+20).**

**Bổ sung — chống lại mặt trái của cá nhân hoá:**
Sau khi rà lại, lớp cá nhân hoá vừa xây đang **chống lại Nguyên tắc 4** của
chính kế hoạch (*"Radar phát hiện thứ người dùng không biết để đi tìm"*): trừ
điểm nặng khách ngoài địa bàn → tụt hạng → không ai gọi → mất khách. Đã sửa
theo ba ràng buộc, nay là nguyên tắc bắt buộc trong kế hoạch (§57.1):
- **Suất khám phá 20%** xếp theo điểm khách quan, đánh dấu rõ trên thẻ.
- **Ngoài địa bàn → định tuyến**: phạt giảm còn -4, kèm `handoff_to` chỉ đúng
  RM phụ trách khu vực đó. Khách không bị đánh rơi, chỉ đổi người xử lý.
- **Điền sẵn form từ hành vi thật** (`observed_work_profile`) — xử lý rủi ro
  lớn nhất là *không ai khai*. Im lặng khi dưới 3 quan sát; không bao giờ tự lưu.
- `daily_capacity` nay là số dòng mặc định thật, không còn là trường trang trí.

Quyết định: **không làm lịch sử hội thoại kiểu ChatGPT** (§57.3) — kéo sản phẩm
về phía "chatbot" mà §3 đã loại trừ, và tạo kho PII mới nằm ngoài lớp kiểm soát
P0-H đang xây. **803 test pass (+18).**

**Bổ sung — màn hình "Cơ hội hôm nay" (React):**
Backend đã đủ nhưng không có UI thì không demo được. Nay đã có
`web/src/TodaysOpportunities.tsx`, đặt làm **tab mặc định** của `/rb`:
- Thẻ theo đúng thứ tự RM cần đọc: AI · NHU CẦU · **VÌ SAO BÂY GIỜ** · GIÁ TRỊ
  · VIỆC NÊN LÀM. Chi tiết 5 chiều điểm nằm trong phần gấp.
- Hiện **cả hai điểm** khi đã cá nhân hoá (`79` kèm `gốc 71`) — giấu điểm gốc
  đi thì con số mất nghĩa so sánh.
- Thẻ khám phá viền đứt + nhãn *"Ngoài vùng bạn phụ trách — đáng xem"*.
- Thẻ ngoài địa bàn hiện gợi ý chuyển giao kèm tên RM phụ trách.
- Bỏ qua bắt buộc nêu lý do (chặn ngay ở UI).
- Panel khai báo có nút **"Điền giúp tôi"** từ dữ liệu quan sát được.
**Frontend: 14 test pass · lint sạch · typecheck sạch · build thành công.**

**Bổ sung — P0-H và P0-I đã đóng:**
- **P0-H che PII**: che vô điều kiện ở **mọi** đường ra (talent search/detail/
  export, rb people/opportunities/export/today, hiring hunts). Xuất CSV cũng
  che — đó là lúc dữ liệu rời khỏi hệ thống. `POST /auth/contact-unlock/<id>/`
  là cửa duy nhất trả liên hệ đầy đủ, có đếm hạn mức và ghi vết.
  `ChoDuongVongTest` đi qua từng đường một để không hở endpoint nào.
- **P0-I CI**: `.github/workflows/ci.yml` với 4 job. Edge chạy trên
  **windows-latest** vì pywebview/pythonnet/DPAPI không cài được trên Linux.
  Server chạy ma trận Python 3.9 (dev) + 3.11 (Dockerfile — thứ thật sự deploy).
  Job **rà bí mật** riêng vì lộ khoá là điều kiện **loại ngay** theo thể lệ, đã
  thử với dữ liệu bẩn giả để chắc chắn nó bắt được chứ không chỉ luôn báo xanh.

**Bổ sung — P0-A số liệu thu thập:**
`core/capture.py` + `GET /hub/capture/` + bảng trên Dashboard. Ba câu trả lời:
nguồn nào đang chảy · bao nhiêu lượt gộp về một người · bóc tách CV có được không.

Cố ý **không** tính "tỷ lệ thu thập thành công": mẫu số không tồn tại (Hub không
biết TopCV còn bao nhiêu hồ sơ nó chưa thấy). Một tỷ lệ bịa đặt sẽ sụp ngay ở
câu hỏi đầu tiên của giám khảo.

Trong lúc làm phát hiện **lỗi có sẵn ở `seed_demo`**: nó ghi thẳng `SourceRecord`
mà bỏ bước "nhấc trường từ payload ra cột" mà đường đồng bộ thật luôn làm. Hệ
quả là **mọi** màn hình nhóm theo nguồn đều hiện "Không rõ nguồn" với dữ liệu
demo — kể cả màn hình `Data` đã có từ trước. Đã sửa bằng cách dùng chung
`PROMOTED_COLUMNS` với `SyncRecordSerializer`. Sau khi sửa, demo hiện đúng:
**1 người / 3 nền tảng**, TopCV 3 · VietnamWorks 3 · CareerViet 2 · ITviec 2.

**Bổ sung — bằng chứng GreenNode:**
- `GET /ai/usage/` nay tách **theo từng nhà cung cấp**: calls, failed,
  `success_rate`, `avg_latency_ms`, cộng `fallback_calls`. Độ trễ chỉ tính lượt
  **thành công** — lượt timeout luôn bằng đúng ngưỡng chờ, gộp vào sẽ làm nhà
  cung cấp *hay hỏng* trông như *chậm đều đặn*.
- `docs/GREENNODE.md` trình bày theo đúng khung **Intelligence / Capabilities /
  Runtime** của Hacker Guide, bằng đúng từ vựng đó — để hội đồng không phải tự
  dịch kiến trúc sang tiêu chí của họ. Có sơ đồ 3 khối split-cloud và ghi rõ
  hợp đồng Runtime (cổng 8080 + `/health`) mà Hub hiện **chưa** khớp.

**Bổ sung — Task 8.5 agent service:**
`agent/` — FastAPI, cổng **8080**, `GET /health`, `POST /invocations`. Đúng hợp
đồng Runtime của AgentBase, có test canh cả hai điều kiện đó (sai thì container
không bao giờ lên `ACTIVE`, và lỗi chỉ lộ sau khi đã build + push xong).

Ranh giới: agent làm **hiểu ngôn ngữ** (bóc tách câu hỏi, diễn giải kết quả),
Hub giữ **chấm điểm và quyết định**. Agent không nhân đôi logic chấm điểm — có
bài test canh danh mục sản phẩm của agent không lệch khỏi Hub.

Đã kiểm chạy thật qua HTTP (không chỉ TestClient): bóc tách đúng cả 5 tiêu chí
từ *"Tìm 20 quản lý ở Hà Nội có contact, quan tâm thẻ tín dụng"*.

CI thêm job `agent`: test + ruff + **docker build** — image hỏng bị bắt tại CI
chứ không phải giữa lúc deploy, lúc đó đã tiêu Ví Tổng rồi.

**Việc còn lại cần người thật:** chạy lệnh deploy. Không tự động hoá được và
không nên — nó tiêu tiền từ Ví Tổng và cần IAM credentials của đội.

**Bổ sung — `docs/HACKATHON_METRICS.md`:**
Phương pháp đo, không phải số liệu. Phân biệt rõ ba loại và bắt buộc nói rõ
loại nào là loại nào trên slide:

```text
A. Đếm được từ hệ thống   /hub/capture/, /ai/usage/   — không tranh cãi được
B. Đo có kiểm soát        bài đo tay, mẫu nhỏ         — "n=…, đo ngày …"
C. Ước tính (AEV)         suy ra từ A và B            — phải gọi đúng tên
```

Sai lầm chết người cần tránh: trình bày loại C như loại A. Mọi ô kết quả **để
trống** cho tới khi có người chạy phép đo thật — ô trống là trung thực, ô điền
bừa là rủi ro bị hỏi vặn.

Nêu rõ một cái bẫy phương pháp: cùng một người làm nhánh thủ công trước rồi mới
làm nhánh Radar sẽ nhanh hơn ở lần hai chỉ vì đã quen JD — phải đảo thứ tự.

**Bổ sung — Task 6 tìm prospect bằng ngôn ngữ tự nhiên (§16, P0):**
Lỗ hổng P0 cuối cùng còn sót. `rb/prospects.py` + `POST /rb/prospects/`.

Điểm đáng nói nhất: bước bóc tách **uỷ quyền sang Prospect Agent trên AgentBase**
khi `MSB_AGENT_ENDPOINT` được đặt — nghĩa là agent đã deploy sẽ **thật sự phục
vụ sản phẩm**, không phải một endpoint trưng bày cho giám khảo xem. Agent hỏng
thì rơi xuống LLM tại Hub, rồi xuống dò từ khoá. `criteria_from` cho biết đường
nào đang phục vụ.

Hub **lọc lại** đầu ra của agent dù đó là agent của chính mình: một phiên bản cũ
hoặc một endpoint trỏ nhầm đều trả về thứ Hub không hiểu.

DNC là **ràng buộc**, không phải bộ lọc — không tham số nào tắt được.

**Bổ sung — audit tích hợp Edge ↔ Hub:**
Phát hiện nghiêm trọng nhất của cả dự án: **`edge/app/sync/` chưa từng được gọi**.
Có client, runner, payload, có test — nhưng không bộ lập lịch, không cầu nối JS,
không màn hình. Edge thu CV về SQLite rồi dừng. Luận điểm trung tâm của bài thi
không có đường chạy.

Đã nối đủ: `app/sync/service.py` + 8 phương thức js_api + tab **Đồng bộ Hub**
trong giao diện + bộ lập lịch + dừng sạch khi đóng ứng dụng.

Chín lỗi tích hợp khác đã vá — tất cả đều gây **mất dữ liệu**, không phải lỗi
thẩm mỹ: một bản ghi hỏng giết cả lô 50; chỉ 1000 CV mới nhất đồng bộ được;
`resolve_pending` đói sau ~500 bản ghi; hai Person cùng file thì một bên mất
file vĩnh viễn; `merge()` crash đúng tình huống hay gặp nhất; lỗi CSDL tạm thời
bị coi là vĩnh viễn; khoá bị thu hồi chôn cả lô; khoá sai khuôn bị đánh dấu "đã
gửi" trong khi Hub chưa nhận gì; file quá lớn và mã băm cũ thử lại 8 lần vô ích.

Lỗ hổng PII cuối cũng đã vá: `/hub/source-records/` trả liên hệ thô cho vai trò
Vận hành Edge, 200 dòng mỗi lần, có tìm kiếm theo email.

**Bổ sung — hero flow RB có test tự động (§28):**
`core/tests_hero_flow.py::RbHeroFlowTest` chạy đúng đường demo phút 2:50–3:25:
bài đăng → ý định → Person → đề xuất → **VÌ SAO BÂY GIỜ** → RM nhận → cơ hội →
ghi nhận kết quả. Dùng đúng `seed_demo` mà ngày demo dùng.

Bài này **bắt được ngay một lỗ rò PII thật**: trích dẫn bài đăng trong `why`
chứa nguyên số điện thoại người dùng dán vào. Lớp che chỉ phủ trường
`primary_phone`, không phủ văn bản tự do — nên hạn mức mở khoá bị đi vòng qua
bằng một đường không ai nghĩ tới mà đi kiểm. Đã thêm `privacy.redact_contacts()`.

Đây đúng là lý do §28 yêu cầu hero test: không phải để kiểm từng mảnh (mỗi mảnh
đã có test riêng), mà để kiểm **cả chuỗi nối được với nhau** — và loại lỗi đó
chỉ vỡ ra lúc bấm thật.

**Rủi ro lớn nhất đang mở:**
1. Mục 0.1 và 0.2 chưa ai xác nhận — có thể xoá sổ toàn bộ phần còn lại.
2. Chưa có CI và chưa có lớp che PII — hai dòng ❌ nặng nhất ở Confident.
3. Task 8.5 (AgentBase) chưa bắt đầu, mà nó là điều kiện của một giải cụ thể.

**Việc tiếp theo theo thứ tự — toàn bộ đều CẦN NGƯỜI THẬT, không phải code:**
1. **Xác nhận mục 0.1 / 0.2** — đăng ký Luma + tư cách CBNV. Chặn mọi thứ khác.
2. **Deploy agent lên AgentBase** — code sẵn sàng, cần IAM credentials + Ví Tổng.
3. **Chạy benchmark có kiểm soát** — phương pháp đã có ở
   `docs/HACKATHON_METRICS.md`, cần 3–5 recruiter và 2–3 RM thật.
4. **Diễn tập demo 10 lần liên tiếp** + quay video dự phòng (Phase W4).
5. Dựng pitch deck từ scorecard này.

Phần kỹ thuật P0 đã đóng. Từ đây trở đi giá trị nằm ở **bằng chứng và diễn
tập**, không nằm ở thêm tính năng — đúng như Nguyên tắc 6 của kế hoạch:
*Proof beats features.*

---

## Ký hiệu

| | |
|---|---|
| ✅ | Đã có bằng chứng kiểm được |
| 🟡 | Có một phần / có cơ chế nhưng chưa trưng ra được |
| ⬜ | Chưa làm |
| ❌ | Chưa làm **và** là rào cản cho một mục tiêu giải cụ thể |
