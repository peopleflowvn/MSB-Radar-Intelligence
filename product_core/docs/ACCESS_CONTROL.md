# Phân quyền, danh tính và nhật ký truy cập

**Phase:** 5B bản tối thiểu — **đã hiện thực**
**Master Plan:** mục 38 là đặc tả, PHASE 5B là kế hoạch hiện thực
**Vị trí:** `server/accounts/`

---

## 1. Vì sao không để ở Phase 16

Bản kế hoạch đầu để `permissions` và `audit` trong Phase 16 (HARDENING) — cuối cùng,
sau cả Social Radar lẫn RB Radar. Đó là lỗi sắp xếp:

**Phase 8 và 9 được định nghĩa BỞI vai trò.** *Request Recruiter to Hunt* là CTA cốt
lõi của sản phẩm và nó là cuộc bàn giao **giữa hai vai trò**. Hiring Manager Workspace
và Recruiter Workspace là hai màn hình khác nhau vì hai vai trò khác nhau. Xây xong rồi
mới gắn vai trò = viết lại cả hai.

**Đây là dữ liệu cá nhân ứng viên, tại một ngân hàng.** "Ai đã xem CV của người này?"
là câu hỏi tuân thủ. Trả lời "sẽ thêm ở phase gia cố" trước Compliance của MSB là không
trả lời được. Với cuộc thi cũng vậy — khán giả là ngân hàng.

**Nợ kỹ thuật tích tụ mỗi ngày.** `Interaction.actor` từng là `CharField` tự do. Đã sửa
thành khoá ngoại tới `User` **ngay bây giờ**, khi chưa có dữ liệu thật nên gần như miễn
phí; sau Phase 9 thì là migration có rủi ro. Đây là phần duy nhất của Phase 5B đã làm.

---

## 2. Đã làm: `Interaction.actor`

```python
actor      = FK(User, null=True, on_delete=SET_NULL)   # ai làm
actor_name = CharField                                  # tên lúc đó
```

**`SET_NULL` chứ không `CASCADE`:** nhân viên nghỉ việc, tài khoản bị xoá, nhưng lịch
sử tương tác với ứng viên vẫn phải còn — nó là dữ liệu nghiệp vụ, không phải dữ liệu
của nhân viên đó.

**Vì sao có thêm `actor_name`:** đọc tên từ `actor` lúc hiển thị sẽ mất thông tin đúng
lúc cần nhất — khi tài khoản đã bị xoá. Tên được chụp lại tại thời điểm ghi, nên dòng
lịch sử vẫn đọc được vĩnh viễn.

---

## 3. Quyết định thiết kế: hai bảng, không phải một

Master Plan mục 17 liệt kê `viewed` là một Interaction. Nhưng gộp nhật ký truy cập vào
`Interaction` là sai:

| | `Interaction` | `AccessLog` |
|---|---|---|
| Là gì | Hành động có ý nghĩa nghiệp vụ | Mọi lượt đọc dữ liệu cá nhân |
| Ví dụ | shortlist, gọi điện, yêu cầu săn | mở hồ sơ, tìm kiếm, xuất Excel |
| Ai đọc | Recruiter, trên timeline Person 360 | Compliance, khi có yêu cầu |
| Khối lượng | Ít | Gấp hàng trăm lần |
| Thời hạn lưu | Vĩnh viễn | Có hạn |

Gộp lại thì timeline của recruiter chìm trong hàng nghìn dòng "đã xem", còn nhật ký
tuân thủ lẫn với ghi chú nghiệp vụ.

**Giải pháp:** hai bảng. `Interaction` vẫn giữ `viewed` nhưng **khử trùng lặp theo
phiên/ngày** để timeline đọc được; `AccessLog` ghi từng lượt đọc qua middleware.

`AccessLog` cần: ai, Person nào, lúc nào, từ IP nào, qua endpoint nào, và **có xuất dữ
liệu ra ngoài không** — xuất Excel/CSV phải đánh dấu riêng, vì đó là lúc dữ liệu rời
khỏi hệ thống và ra khỏi tầm kiểm soát.

---

## 4. Ba câu hỏi chính sách — cần MSB quyết

Đây là quyết định của tổ chức, không phải quyết định kỹ thuật. Tôi nêu đề xuất mặc định
nhưng **không tự quyết**.

### 4.1. Recruiter A có thấy ứng viên Recruiter B sở hữu không?

**Đề xuất: CÓ.** Nguyên tắc 2 của dự án là "một People Database, nhiều nghiệp vụ".
Che giấu lẫn nhau giữa các recruiter là phá chính lý do dự án tồn tại — mục đích là để
một ứng viên nộp CV ba năm trước không bị quên lãng.

Vẫn ghi nhật ký đầy đủ, nên "thấy được" không đồng nghĩa "không ai biết đã xem".

### 4.2. Hiring Manager thấy toàn bộ kho talent hay chỉ người liên quan nhu cầu của mình?

**Đề xuất: chỉ liên quan nhu cầu của mình.** HM không phải người làm tuyển dụng chuyên
trách; mở toàn kho là mở rộng phạm vi tiếp cận dữ liệu cá nhân vượt quá nhu cầu công
việc. Master Plan mục 20 cũng viết "HM không cần làm recruiter workflow".

### 4.3. RB Sales có thấy dữ liệu tuyển dụng không?

> **ĐÃ QUYẾT — 19/08/2026: CÓ.** Quyết định của chủ dự án (Lê Hoàng Tùng).
> Đề xuất ban đầu của tài liệu này là "không"; quyết định cuối cùng là "có".

Nghĩa là RB Radar được đọc Person và dữ liệu có nguồn gốc từ ứng tuyển. Shared Core
(mục 11, 25) vì thế hoạt động đúng như hình dung ban đầu — một Person, hai hồ sơ, cả
hai nghiệp vụ dùng chung.

**Rủi ro còn lại, ghi để có dấu vết:** người nộp CV ứng tuyển thường không được hỏi ý
kiến về việc dữ liệu đó dùng cho mục đích bán sản phẩm tài chính. Đây là vấn đề *giới
hạn mục đích sử dụng*, và nó nằm ngoài tầm quyết định kỹ thuật. Hai việc nên làm khi
có dịp — không chặn tiến độ hackathon:

1. Rà lại văn bản đồng ý/thông báo quyền riêng tư ở khâu nhận hồ sơ, xem có bao phủ
   mục đích này không.
2. Hỏi Compliance trước khi RB Radar được dùng ở quy mô thật (không phải demo).

**Hệ quả kỹ thuật của quyết định này — làm cho nhật ký quan trọng hơn, không phải ít đi.**
Truy cập liên nghiệp vụ chính là thứ kiểm toán viên sẽ soi đầu tiên. Vì vậy `AccessLog`
phải có cờ `cross_domain`: đánh dấu khi một người ở nghiệp vụ này đọc dữ liệu có nguồn
gốc từ nghiệp vụ kia. Có cờ đó thì trả lời được câu "RB đọc dữ liệu tuyển dụng bao
nhiêu lần, những ai" trong vài giây thay vì phải dò thủ công.

---

## 5. Phạm vi Phase 5B

### Bản tối thiểu — bắt buộc trước Phase 8

```text
Đăng nhập trên React (hiện đang mượn /admin/login/)
6 vai trò (mục 38) + phân quyền tầng module
AccessLog + middleware ghi mọi lượt đọc dữ liệu cá nhân
Đánh dấu riêng lượt xuất Excel/CSV
```

### Hoãn sau hackathon

```text
Phân quyền tầng bản ghi đầy đủ
SSO/LDAP với Active Directory của MSB
Ghi chú có lịch sử sửa
Chính sách thời hạn lưu trữ
```

~~Giao diện tra cứu nhật ký cho Compliance~~ — làm ở audit Phase 15 (21/08/2026), xem mục 7.

Mô hình `User` phải **không cản đường SSO** ngay từ đầu — đừng gắn chặt vào mật khẩu
cục bộ, dù hackathon chỉ dùng mật khẩu cục bộ.

### DoD bản tối thiểu — đã đạt

```text
✅ Không endpoint nào trả dữ liệu ứng viên cho người chưa đăng nhập
✅ Mỗi vai trò chỉ vào được module của mình
✅ Mọi lượt đọc hồ sơ ứng viên đều có một dòng AccessLog truy được về đúng một User
✅ Tải tài liệu được đánh dấu riêng (action=download)
✅ Xuất CSV/Excel được đánh dấu riêng (action=export), tách khỏi view/download
```

**Sửa qua audit Phase 15 (20/08/2026):** `WATCHED_PREFIXES` viết ra ở mục 5 chỉ có
`talent/` và `hub/` — khi RB Radar (Phase 12), Social Radar (Phase 11) và Hiring
(Phase 8) ra đời sau đó, không ai quay lại thêm tiền tố của chúng vào middleware, nên
dòng DoD "mọi lượt đọc hồ sơ đều có AccessLog" ở trên đã **sai trong thực tế** dù ba
nghiệp vụ này đều đọc Person qua People Core dùng chung — và endpoint xuất CSV mới của
Phase 15 (`talent-search-export`) cũng không được nhận diện là `export`, bị đếm nhầm
thành `list`. Đã thêm `/api/v1/rb/`, `/api/v1/social/`, `/api/v1/hiring/` vào
`WATCHED_PREFIXES`, phân loại action/module cho từng URL name của ba app đó, và thêm
`_default_module(path)` để một endpoint mới lỡ quên đăng ký tên vẫn được gán đúng module
theo tiền tố thay vì rơi về mặc định `talent` như trước. Xem `server/accounts/tests.py`
`AccessLogTest.test_doc_danh_sach_co_hoi_RB_duoc_ghi_dung_module` và các test lân cận.

---

## 6. Cách hiện thực — những chỗ đáng chú ý

### Vai trò lưu bằng Django Group, không phải trường `role`

Ba lý do: một người kiêm được nhiều vai trò (Group cho quan hệ nhiều-nhiều sẵn); giao
diện gán vai trò trong trang quản trị có sẵn; và không đẻ ra hệ thống phân quyền song
song bên cạnh hệ thống Django đã có.

Superuser luôn được tính là `admin`.

### Ghi nhật ký bằng middleware, không gọi tay trong view

Gọi tay nghĩa là mỗi endpoint mới lại có thể quên — và endpoint bị quên chính là
endpoint không ai biết đang bị dùng. **Nhật ký tuân thủ phải là mặc định, không phải
tuỳ chọn.**

Dùng `process_view` chứ không `__call__`: ở thời điểm đó Django đã phân giải URL nên
biết chính xác `person_id`/`document_id`. Đọc từ chuỗi đường dẫn thô sẽ vỡ ngay khi ai
đó đổi định dạng URL.

Nhật ký hỏng **không chặn người dùng làm việc**, nhưng để lại vết trong log hệ thống —
"không ghi được nhật ký truy cập" tự nó là sự cố cần biết.

### Ghi cả điều kiện tìm kiếm

Một lượt tìm trả về 500 hồ sơ là **500 lần dữ liệu cá nhân được nhìn thấy**. "Ai đã tìm
gì" quan trọng ngang "ai đã xem hồ sơ nào".

### Hai lỗi mà chỉ nhìn nhật ký thật mới thấy

Cả hai đều lọt qua test và chỉ lộ ra khi đọc nội dung nhật ký sau một phiên thao tác thật.

**1. Lượt bị chặn trông y hệt lượt thành công.** `process_view` chạy *trước* permission
class, nên request bị 403 vẫn được ghi — và ghi giống hệt một lượt đọc thành công. Một
nhật ký tuân thủ không phân biệt được *"đã đọc dữ liệu"* với *"bị chặn"* thì **gây hiểu
nhầm còn tệ hơn không ghi**. Đã thêm cờ `allowed`; lượt bị chặn vẫn được lưu (cố vào chỗ
không được phép là thông tin an ninh đáng giá) nhưng không tính vào `cross_domain`.

**2. Màn hình vận hành bị xếp nhầm vào Talent.** `hub-summary`, `hub-edges`,
`hub-source-records` nhìn theo góc *hạ tầng*, không phải góc *con người*. Xếp nhầm khiến
**mọi** lượt xem của Edge Operator bị đánh cờ liên nghiệp vụ — và cờ lúc nào cũng bật
thì mất hết ý nghĩa.

### Ẩn tab là tiện ích, không phải bảo mật

Giao diện ẩn tab người dùng không vào được, và chặn cả khi gõ thẳng URL. Nhưng đó chỉ để
họ không bấm vào rồi nhận 403 khó hiểu — **chặn thật nằm ở permission class phía máy chủ**,
có test khẳng định (`test_edge_operator_BI_CHAN_khoi_talent`).

Đăng xuất xoá toàn bộ cache phía trình duyệt: dữ liệu ứng viên của người vừa đăng xuất
không được nằm lại cho người đăng nhập sau đọc được.

### Nhật ký chỉ đọc

Trang quản trị không cho thêm/sửa/xoá `AccessLog`. Nhật ký tuân thủ mà sửa được thì
không còn là bằng chứng.

---

## 7. Trang Quản trị (bổ sung 21/08/2026)

Từ Phase 5B tới giờ, tạo tài khoản/gán vai trò chỉ làm được qua Django `/admin/`, và
`access-log/` + `access-log/summary/` có API từ đầu nhưng chưa ai xây màn hình đọc —
đúng hai mục "hoãn sau hackathon" ở mục 5. Audit Phase 15 chỉ ra đây là khoảng trống
thật: một quản trị viên không quen Django admin không có cách tự phục vụ, kể cả việc
đơn giản nhất là khoá một tài khoản.

### Module `admin_console` — tách khỏi `ai_settings`

Trước đó `access-log/` mượn tạm `MODULE_AI_SETTINGS` làm cổng "chỉ Admin" — đúng về
mặt kết quả (chỉ Admin có cả hai module) nhưng sai về mặt ý nghĩa: nhật ký truy cập
không liên quan gì tới cấu hình nhà cung cấp AI. Tách riêng `MODULE_ADMIN` ("admin_console")
để `ROLE_MODULES` đọc đúng ý: chỉ Admin, không nhà cung cấp AI nào ở đây.

### `server/accounts/views.py::user_list` / `user_detail`

```text
GET/POST /api/v1/auth/users/        danh sách + tạo tài khoản
PATCH    /api/v1/auth/users/{id}/   sửa tên, vai trò, khoá/mở, đặt lại mật khẩu
```

Không có endpoint xoá. Cùng lý do với `Interaction.actor` dùng `SET_NULL` thay vì
`CASCADE` (mục 2): một tài khoản có thể đứng tên trong hàng nghìn dòng `AccessLog`/
`Interaction` của nhiều năm trước — xoá tài khoản là xoá luôn khả năng tra lại "ai đã
làm việc này". Khoá tài khoản (`is_active=False`) đạt cùng mục đích nghiệp vụ (người
đó không đăng nhập được nữa) mà không xoá vết.

**Không tự khoá được chính mình** — chặn ở `user_detail`, trả 400. Không phải lỗ hổng
bảo mật lớn (Django admin vẫn còn đó), nhưng là một cách dễ tự khoá nhầm bằng một cú
click, và không có lý do gì để cho phép.

Mật khẩu mới đi qua `django.contrib.auth.password_validation.validate_password` —
đây là bề mặt tạo tài khoản *thật*, không phải dữ liệu test nội bộ, nên dùng validator
chuẩn của Django thay vì chấp nhận bất kỳ chuỗi nào.

### `web/src/Admin.tsx` — hai tab, chỉ Admin

`Người dùng & phân quyền` (tạo/sửa/khoá tài khoản, tick chọn vai trò) và `Nhật ký hệ
thống` (đọc `access-log/` + `access-log/summary/` đã có từ Phase 5B, thêm bộ lọc theo
người dùng/hành động/liên nghiệp vụ/xuất dữ liệu/bị chặn). Trang chỉ **đọc** AccessLog,
không có nút sửa/xoá — giữ đúng nguyên tắc "Nhật ký chỉ đọc" ở trên.

### `RoleModuleAccess` — Admin phủ lên ma trận module mặc định (01/09/2026)

`ROLE_MODULES` trong `accounts/roles.py` vẫn là **sàn an toàn viết trong code**. Bảng
`accounts.models.RoleModuleAccess` chứa các Ô `(vai trò, module)` mà Admin đã đổi so
với sàn: `allowed=True` cấp thêm, `allowed=False` thu hồi; Ô trùng mặc định thì không
lưu hàng nào. `roles.modules_of()` hợp nhất sàn + các hàng này.

- API: `GET/POST /api/v1/auth/role-modules/` (chỉ `admin_console`). GET trả ma trận
  đầy đủ kèm `enabled/is_default/changed/editable`; POST `{role, module, enabled}`
  bật/tắt một Ô.
- Ô trong `roles.LOCKED_GRANTS` (hiện: `admin ↔ admin_console`) không sửa được —
  chặn tự khoá mình khỏi trang quản trị. Ngoài ra `modules_of` luôn thêm lại
  `admin_console` cho vai trò `admin` bất kể bảng override có gì.
- Giao diện: `Admin.tsx` → tab **Ma trận & Hoạt động** → bảng tick roles × modules.
- Module đầu tiên dùng cơ chế này: `people_intake` (mặc định chỉ Admin + Edge Ops;
  Admin tự bật cho Recruiter/Manager). Xem `docs/PEOPLE_INTAKE.md`.

---

## 8. Ảnh hưởng tiến độ

Phase 5B là phần chèn thêm so với kế hoạch đầu và **có làm chặt tiến độ** — còn 35 ngày
cho 4 phase hero flow, giờ thành 5.

Đổi lại: chặn được việc phải viết lại Phase 8–9, và trả lời được câu hỏi tuân thủ mà
một ban giám khảo ngân hàng gần như chắc chắn sẽ hỏi.

**Nếu buộc phải cắt, cắt phân quyền tầng bản ghi — đừng cắt AccessLog.** Phân quyền
thiếu là bất tiện; không có nhật ký truy cập dữ liệu cá nhân là vấn đề khác hẳn về bản chất.


---

## 7. Che liên hệ và hạn mức mở khoá

**Phase:** 15 · **Master Plan:** mục 27 · **Vị trí:** `accounts/privacy.py`

### 7.1. Bài toán không phải "giấu dữ liệu khỏi người có quyền"

Người dùng ở đây **có** quyền xem — họ là recruiter và RM đang làm đúng việc của
mình. Bài toán là:

> Một tài khoản hợp lệ có thể lặng lẽ rút cả kho liên hệ ra ngoài chỉ bằng cách
> cuộn qua vài trang danh sách.

Hai cơ chế, giải hai việc khác nhau:

| | Giải việc gì |
|---|---|
| **Che mặc định** | Chặn *khối lượng*. Cuộn 500 hồ sơ cũng không thu được gì. |
| **Hạn mức + nhật ký** | Chặn *ý đồ*, và trả lời được câu hỏi tuân thủ "ai đã lấy số của người này". |

### 7.2. Che vô điều kiện, không che theo ngữ cảnh

Cách khác là truyền `request.user` vào mọi serializer rồi quyết định che hay
không. Cách đó hỏng theo kiểu tệ nhất: chỉ cần **một** chỗ khởi tạo serializer
quên truyền context là chỗ đó rò toàn bộ, im lặng, và không test nào phát hiện
trừ khi có người nghĩ tới đúng endpoint ấy.

Nên `mask_*()` được gọi vô điều kiện trong serializer, và API danh sách **không
có tham số nào** để xin dữ liệu chưa che.

Ẩn trên React không tính là che: bất kỳ ai mở DevTools cũng đọc được nguyên văn
phản hồi API.

### 7.3. Các đường ra đã được bịt

```text
GET  /talent/search/            đã che
GET  /talent/people/<id>/       đã che (Person 360)
GET  /talent/search/export/     đã che ← xuất file là lúc dữ liệu RỜI hệ thống
GET  /rb/people/                đã che
GET  /rb/people/<id>/           đã che
GET  /rb/opportunities/         đã che
GET  /rb/opportunities/export/  đã che
GET  /rb/today/                 đã che
GET  /hiring/hunts/             đã che
POST /auth/contact-unlock/<id>/ ← CỬA DUY NHẤT trả liên hệ đầy đủ
```

`accounts/tests_privacy.py::ChoDuongVongTest` đi qua từng đường trong danh sách
này. Một lớp bảo vệ chỉ cần hở đúng một endpoint là mất tác dụng hoàn toàn.

### 7.4. Hạn mức theo ngày

```text
Admin           không giới hạn
Manager         50/ngày   ← vẫn CÓ hạn mức
Recruiter       30/ngày
RB Sales        15/ngày
Hiring Manager  10/ngày
Không vai trò    5/ngày
```

**Vì sao RM thấp hơn Recruiter:** recruiter làm theo lô (sàng một đợt ứng viên
cho một vị trí), RM làm theo từng khách. RM cần 15 số một ngày là bình thường;
RM cần 200 số một ngày là chuyện khác.

**Vì sao Manager vẫn có hạn mức:** một chốt kiểm soát chỉ áp cho cấp dưới thì
không phải chốt kiểm soát. Ai cần hơn thì cấp `ContactUnlockPolicy` riêng — và
việc cấp đó tự nó là một dấu vết, có `reason` và `granted_by`.

Kiêm nhiều vai trò thì lấy **mức cao nhất**, không cộng dồn — cộng dồn tạo ra
hạn mức không ai chủ ý cấp.

### 7.5. Mở lại trong ngày không trừ thêm lượt

Mở lại hồ sơ vừa xem cách đây năm phút mà mất thêm một lượt sẽ khiến người dùng
học cách chụp màn hình lại toàn bộ danh sách ngay lần đầu — đúng hành vi mà cả
cơ chế này sinh ra để chặn.

Hạn mức reset lúc 00:00 **giờ địa phương**, không phải UTC.

Hết lượt thì trả **429**, không phải 403: người dùng không bị cấm, họ chỉ hết
lượt hôm nay. Trả 403 sẽ khiến họ tưởng mình mất quyền và đi hỏi quản trị viên.

### 7.6. `ContactUnlockLog` tách khỏi `AccessLog`

| | `AccessLog` | `ContactUnlockLog` |
|---|---|---|
| Trả lời | "ai đã **xem** hồ sơ này" | "ai đã **lấy số** của người này" |
| Khối lượng | Rất nhiều | Ít |
| Ai hỏi | Compliance khi rà soát | Compliance **đầu tiên** khi có sự cố rò rỉ |

Gộp lại thì mỗi lần cần trả lời câu thứ hai phải lọc qua hàng trăm nghìn dòng
của câu thứ nhất, và hạn mức hàng ngày phải đếm trên đúng bảng lớn đó.

### 7.7. RM không xem/tải được file CV gốc

`document_download` dùng `RequiresRecruiting` — chỉ Recruiter, Manager, Admin.
`rb_sales` nhận **403**, kể cả khi biết `document_id`. Đây là ranh giới đã có
từ trước; `CvFileBoundaryTest` canh để nó không bị nới ra một cách vô tình.

RM làm việc trên hồ sơ khách hàng do AI tóm tắt, không phải trên file CV gốc.


### 7.8. Che liên hệ trong **văn bản tự do**

Che theo trường không đủ. Bằng chứng của một đề xuất chứa trích dẫn nguyên văn
bài đăng, và người ta thường tự viết số điện thoại vào bài:

```text
"Em cần vay 500 triệu mua nhà, ai tư vấn giúp em với. LH 0901234567"
```

Trích dẫn đó hiện thẳng ở mục **VÌ SAO BÂY GIỜ** trên thẻ «Cơ hội hôm nay». Không
che ở đây thì toàn bộ hạn mức mở khoá bị đi vòng qua bằng một đường không ai
nghĩ tới mà đi kiểm — và đúng là nó đã lọt, cho tới khi bài kiểm hero flow RB
bắt được.

`privacy.redact_contacts()` che email và số điện thoại nằm trong văn bản, cố ý
rộng tay: bắt nhầm một dãy số không phải điện thoại chỉ làm trích dẫn khó đọc
hơn một chút; bỏ sót một số thật là để lộ liên hệ ở chỗ không ai kiểm.

Áp cho mọi chỗ hiển thị lại nội dung người dùng nhập.
