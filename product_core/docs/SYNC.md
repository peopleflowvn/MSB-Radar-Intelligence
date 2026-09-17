# Đồng bộ Edge → Hub

**Phase:** 2 (Edge Sync Foundation) — hoàn thành
**Phạm vi:** Edge biết xếp hàng, gửi đi, ghi nhận kết quả. **Không có nghiệp vụ Hub nào ở đây.**

Gộp Person, phân giải định danh, chấm điểm cơ hội đều thuộc về Hub (Phase 4–5).
Edge chỉ báo cáo những gì nó thu thập được.

---

## 1. Các thành phần

```text
app/db.py              bảng sync_outbox + các phép toán hàng đợi
app/sync/identity.py   edge_id — định danh bản cài Edge này
app/sync/payload.py    bản ghi Edge -> payload gửi đi, hash nội dung
app/sync/client.py     gọi HTTP tới Hub, phân loại lỗi
app/sync/runner.py     quét, gửi lô, ghi nhận kết quả
```

Luồng:

```text
candidates (SQLite)
      ↓  runner.scan_candidates()   — chỉ xếp hàng bản ghi thật sự đổi
sync_outbox
      ↓  db.claim_sync_batch()      — đánh dấu inflight trong 1 transaction
runner.push_once()
      ↓  client.push_batch()        — HTTP POST /api/v1/edge/sync/
Hub
      ↓  kết quả theo TỪNG bản ghi
db.finish_sync() / db.fail_sync()
```

---

## 2. Mẫu outbox

`sync_outbox` giữ **đúng một hàng cho mỗi thực thể**, không phải nhật ký nối thêm mãi.
Bảng vì thế bị chặn trên bởi *số thực thể*, không phải *số lần thay đổi*.

| Cột | Vai trò |
|---|---|
| `entity_type`, `entity_key` | UNIQUE. Với ứng tuyển: `source\|account\|cv_id` — đúng khoá chính của `candidates` |
| `payload_hash` | sha256 của payload đã chuẩn hoá. Đổi = nội dung đổi = xếp lại hàng |
| `status` | `pending` → `inflight` → `synced` / `failed` |
| `attempts`, `next_attempt_at` | Backoff luỹ thừa có jitter, chặn trên 1 giờ, tối đa 8 lượt |
| `hub_id` | Id Hub trả về, để đối chiếu về sau |

**Outbox không giữ payload.** Payload được dựng lại từ CSDL tại thời điểm gửi
(`runner._rebuild_payload`), vì dữ liệu ứng viên có thể được làm giàu sau khi xếp hàng
(parsing CV, tự điền liên hệ) và bản mới nhất luôn đáng gửi hơn bản đã đóng băng.

**Không có khoá ngoại tới `candidates`** — cố ý. Outbox sẽ còn mang document, signal,
social post; và phải sống sót đủ lâu để báo cáo kết quả kể cả khi ứng viên đã bị xoá
cục bộ (bên gửi tự bỏ qua và đánh dấu xong, để hàng mồ côi không chặn hàng đợi).

---

## 3. Ba tính chất Master Plan mục 9 yêu cầu

### Idempotent

`payload_hash` được tính trên **payload đã chuẩn hoá**, không phải trên hàng CSDL thô:

- danh sách trường gửi đi là **tường minh** (`payload.CANDIDATE_FIELDS`), nên thêm cột
  nội bộ vào `candidates` không âm thầm làm mọi bản ghi có vẻ đã đổi;
- `None` và `""` cho **cùng một hash** (SQLite trả `None`, JSON trả `null`);
- `edge_id` **không** tham gia hash — tạo lại danh tính Edge không được làm mọi thứ
  trông như đã thay đổi.

Kết quả: quét lại toàn bộ CSDL là thao tác rẻ và không sinh rác. Đã kiểm chứng trên
2000 bản ghi — lần quét thứ hai xếp hàng **0** bản ghi.

`idempotency_key` gửi kèm mỗi bản ghi gồm cả content hash, nên gửi lại đúng nội dung cũ
là no-op ở phía Hub, còn nội dung đã sửa vẫn được nhận như một bản cập nhật.

### Retryable

Phân loại lỗi quyết định có thử lại hay không:

| Tình huống | Lớp lỗi | Thử lại? |
|---|---|---|
| Mất mạng, DNS, timeout | `HubUnavailable` | Có |
| HTTP 5xx, 429 | `HubUnavailable` | Có |
| HTTP 401/403 | `HubAuthError` | **Không** — chỉ người dùng sửa được |
| HTTP 4xx khác (kể cả 404) | `HubError` | **Không** — sai cấu hình/dữ liệu, thử lại vô ích |
| Hub trả `retry` / `conflict` | — | Có |
| Hub không nhắc tới bản ghi | — | Có — thà gửi thừa còn hơn âm thầm mất dữ liệu |

Backoff: `30s × 2^(attempts-1)`, jitter ±25%, chặn trên 1 giờ, tối đa 8 lượt rồi
chuyển `failed`. Jitter tránh việc nhiều Edge cùng mất mạng rồi gọi Hub lại đúng cùng lúc.

`failed` **không phải ngõ cụt**: `enqueue_sync()` xếp lại hàng đó khi nội dung đổi, và
`requeue_failed_sync()` phục vụ nút thử lại trên giao diện.

`drain()` dừng ngay khi cả một lô thất bại — không đấm liên tục vào một Hub đang sập.

### Resume-able

Toàn bộ trạng thái nằm trong SQLite. Tắt máy giữa chừng để lại hàng ở `inflight` mà
không còn ai gửi; `recover_sync_queue()` (gọi khi mở CSDL trong `web_api._open_db`)
trả chúng về `pending`. Không có bước này thì chúng kẹt vĩnh viễn.

---

## 4. edge_id

Nằm ở `%LOCALAPPDATA%\MSBRadar\edge_identity.json`, **không** ở `cauhinh.json`.

Hệ quả cố ý: chép cả thư mục ứng dụng sang máy khác sẽ sinh `edge_id` mới — đúng, vì
đó là một Edge khác. Nếu để trong `cauhinh.json` thì hai máy sẽ cùng khai một danh tính
và Hub không phân biệt được nguồn dữ liệu.

Không đọc/ghi được đĩa vẫn trả về một danh tính dùng trong bộ nhớ: mất khả năng đồng bộ
không được phép làm hỏng việc thu thập CV, vốn là chức năng cốt lõi.

---

## 5. Hợp đồng API mà Hub sẽ phải hiện thực

Đây là phía Edge đã sẵn sàng. Hub (Phase 3) cần cung cấp:

```text
GET  /api/v1/edge/health/     kiểm tra Hub sống + API key hợp lệ
POST /api/v1/edge/register/   khai báo Edge, idempotent theo edge_id
POST /api/v1/edge/sync/       nhận lô bản ghi
```

Header mọi yêu cầu:

```text
Authorization: Bearer <api_key>
X-Edge-Id: <edge_id>
Content-Type: application/json
```

Thân yêu cầu `/sync/`:

```json
{
  "edge_id": "…",
  "records": [
    {
      "entity_type": "source_record",
      "entity_key": "topcv|ta@msb.com.vn|12345",
      "idempotency_key": "…",
      "edge_id": "…",
      "source": "topcv", "account": "…", "cv_id": "12345",
      "fullname": "…", "email": "…", "phone": "…", "position": "…"
    }
  ]
}
```

Thân phản hồi — **kết quả theo TỪNG bản ghi**, không phải một trạng thái chung cho cả lô:

```json
{
  "results": [
    { "entity_key": "topcv|ta@msb.com.vn|12345", "status": "accepted", "id": "hub-uuid" }
  ]
}
```

Trạng thái Hub được phép trả (khớp Master Plan mục 37):

| status | Edge hiểu là |
|---|---|
| `accepted`, `duplicate`, `updated` | Xong |
| `retry`, `conflict` | Hẹn lại với backoff |
| khác | Lỗi vĩnh viễn, chuyển `failed` |

Một bản ghi hỏng **không được** kéo cả lô phải gửi lại — nếu không, một hàng lỗi vĩnh
viễn sẽ chặn hàng đợi mãi mãi.

### Producer ngoài Edge

Bàn nhận `SourceRecord` nay còn nhận dữ liệu từ **luồng nhập liệu thủ công của Hub**
(Excel/CSV, nhiều CV) — ghi qua một Edge dành riêng `edge_id="hub-manual"`, dùng chung
`core.ingest.upsert_source_record` với endpoint này. Xem `docs/PEOPLE_INTAKE.md`.

---

## 6. Cấu hình

| Khoá | Nơi lưu | Mặc định |
|---|---|---|
| `hub_url` | `cauhinh.json` | `""` |
| `hub_sync_enabled` | `cauhinh.json` | `false` |
| `hub_sync_interval_min` | `cauhinh.json` | `15` |
| `hub_batch_size` | `cauhinh.json` | `50` |
| API key | **DPAPI** (`cfg.hub_api_key()`) | — |

API key đi qua kho bí mật giống mọi mật khẩu khác; `save()` loại nó khỏi `cauhinh.json`.

---

## 6.1. Đồng bộ file CV — hai pha

**Bài toán:** cùng một người ứng tuyển nhiều lần ở nhiều thời điểm sẽ nộp **nhiều file
CV khác nhau**. Phải ghi nhận tất cả (Master Plan mục 14: "CV v1, CV v2, CV v3…").

**Ràng buộc:** kho CV ~20.000 hồ sơ × ~200 KB ≈ **4 GB**. Gửi kèm file trong mỗi lô
đồng bộ nghĩa là mỗi lần quét lại đẩy lại toàn bộ 4 GB đó qua đường truyền văn phòng.

```text
Pha 1   Edge gửi METADATA (sha256, tên file, cỡ, text đã bóc tách) trong lô
        đồng bộ bình thường → Hub tạo Document, trả `needs_file`
Pha 2   Edge CHỈ tải nội dung của những file Hub báo là chưa có
```

Vì kho file đánh địa chỉ theo nội dung, Hub trả lời "đã có" tức thì. **Một CV không
đổi thì vĩnh viễn không bao giờ được gửi lại.**

### Phiên bản tự sinh ra từ mã băm

Không có trường "version" nào phải tự tăng:

| Tình huống | Kết quả |
|---|---|
| Cùng file gửi từ TopCV và VietnamWorks | Cùng sha256 → **một** Document, gắn với **hai** SourceRecord |
| Ứng viên sửa CV rồi nộp lại | sha256 khác → Document **mới** |

Thứ tự phiên bản suy từ `observed_at` = **ngày ứng tuyển**, không phải lúc Hub nhận.
Một CV cũ đồng bộ muộn vẫn nằm đúng chỗ trong dòng thời gian. `version_number()` tính
lúc đọc chứ không lưu — số đã lưu sẽ sai ngay khi có bản cũ chen vào giữa.

Khi cùng một file đến từ hai lượt ứng tuyển, giữ **mốc sớm nhất**: đó là lần đầu phiên
bản CV ấy xuất hiện.

### Hai điểm bảo vệ

**Hub tự băm lại, không tin Edge.** Không kiểm thì một Edge lỗi có thể ghi nội dung của
người này dưới mã băm của người khác — và vì kho đánh địa chỉ theo nội dung, sai lệch
đó lan sang mọi Document dùng chung mã băm ấy.

**Edge chặn thoát thư mục** khi dựng đường dẫn file: `filename` đến từ CSDL, vốn được
điền từ dữ liệu của nhà cung cấp.

### Khoá kết quả là CẶP (entity_type, entity_key)

File CV **dùng chung `entity_key`** với lượt ứng tuyển mang nó — nhờ vậy Hub tìm được
bản ghi nguồn và qua đó là Person. Hệ quả: kết quả trả về phải kèm `entity_type`, nếu
không hai loại sẽ ghi đè kết quả của nhau trong hàng đợi của Edge.

### Khử trùng trong phạm vi một lô

Hub tính `needs_file` cho cả lô **trước khi** có lượt tải nào, nên chưa thể biết một nội
dung sắp được tải lên bởi bản ghi khác trong cùng lô. Edge tự nhớ các mã băm đã tải
trong lô. Một người nộp cùng CV cho hai cổng là chuyện thường, và ở lần đồng bộ đầu
20 nghìn hồ sơ thì rất hay gặp.

### Đã kiểm chứng đầu cuối

1 người, 3 lượt ứng tuyển, 3 file (2 nội dung khác nhau):

```text
Hub:  1 Person, 2 Document
      v1: 2023-03-01, có file, 1 lượt ứng tuyển
      v2: 2025-06-01, có file, 2 lượt ứng tuyển   ← file dùng chung
Tải lên: 2 (không phải 3)
Đồng bộ lại: tải lên 0
Kho file: 2 file
```

---

## 7. Còn thiếu

- [x] ~~Hub Django + 3 endpoint~~ (Phase 3)
- [x] ~~Đồng bộ document (file CV)~~ — xem mục 6.1
- [ ] Giao diện Edge: tab cấu hình Hub, nút Kiểm tra kết nối, bảng trạng thái đồng bộ — audit Phase 15
  xác nhận `edge/app/web/` vẫn chưa có màn hình này
- [ ] Lịch tự động gọi `runner.drain()` theo `hub_sync_interval_min` — audit Phase 15 xác nhận trường
  này vẫn nằm trong `edge/app/config.py` nhưng không có vòng lặp/scheduler nào đọc nó; đồng bộ hiện chỉ
  chạy khi người dùng tự bấm
- [ ] Endpoint tải file CV về từ Hub (có kiểm tra quyền) — Phase 5B
- [ ] Đồng bộ ảnh đại diện và tài liệu đính kèm khác


---

## 10. Nối đường dây vào ứng dụng (30/08/2026)

Một đợt rà soát tích hợp phát hiện: `app/sync/` đầy đủ và có test — client,
runner, payload đều đúng — nhưng **không có ai gọi**. Toàn bộ mã đồng bộ là mã
chết đối với ứng dụng đang chạy. Edge thu CV về SQLite rồi dừng ở đó.

`grep` toàn bộ mã ứng dụng chỉ tìm thấy đúng một lời gọi (`recover_sync_queue`
lúc mở CSDL). Không bộ lập lịch, không cầu nối JS, không màn hình. `config.py`
đã có sẵn `hub_sync_enabled` và `hub_sync_interval_min` — hai trường trỏ tới một
bộ lập lịch chưa từng được viết.

Test đơn vị của `runner` không phát hiện được điều đó vì chúng gọi thẳng
`runner`. Chỉ bài kiểm **đường dây** mới bắt được, và nay nó tồn tại ở
`tests/test_sync_service.py::WiringTest`.

### 10.1. `app/sync/service.py`

Ranh giới: `runner` biết **cách** gửi một lô, `service` biết **khi nào** gửi.

```text
get_sync_status        trạng thái đủ để giao diện vẽ, không cần gọi thêm
test_hub_connection    nút Kiểm tra kết nối — không gửi dữ liệu ứng viên nào
register_edge_with_hub khai báo máy này, idempotent theo edge_id
sync_now(full)         một lượt ngay; full=True quét lại toàn bộ kho
retry_failed_sync      xếp lại bản ghi đã bị đánh dấu thất bại
start_auto_sync        bật định kỳ, chạy ngay một lượt rồi mới vào chu kỳ
stop_auto_sync
save_hub_config        địa chỉ + API key (qua DPAPI) + tần suất
```

Ba nguyên tắc:

* **Đồng bộ không bao giờ làm hỏng việc thu thập.** Mọi lỗi bị nuốt và ghi nhật
  ký. Mất kết nối Hub vẫn phải tải CV về được.
* **Một lượt tại một thời điểm.** Hai luồng cùng `claim_sync_batch()` tranh nhau
  cùng những hàng đó mà không nhanh hơn.
* **Không tự bật.** Một công cụ gửi dữ liệu ứng viên ra khỏi máy mà tự bật là
  thứ không được phép tồn tại trong ngân hàng.

### 10.2. Các lỗi tích hợp đã sửa cùng đợt

| Lỗi | Hệ quả nếu không sửa |
|---|---|
| Kiểm cả lô một lượt (`is_valid(raise_exception=True)`) | Một bản ghi hỏng → HTTP 400 cho **cả 50**, Edge đánh dấu toàn bộ `failed` vĩnh viễn. Mâu thuẫn trực tiếp với mục 5 của chính tài liệu này. |
| `scan_documents` không phân trang | Chỉ 1000 CV mới nhất được đồng bộ; với kho ~20.000 thì 19.000 file **không bao giờ** tới Hub, mà hàng đợi vẫn trống nên không ai biết. |
| `resolve_pending` xếp theo `pk` | Sau ~500 bản ghi không phân giải được, **không bản ghi mới nào** còn được xử lý. Nay xếp theo `resolve_attempted_at` để hàng đợi xoay vòng. |
| Khử trùng trong lô theo sha256 | Hai Person chưa gộp cùng một file → Edge tải một lần, đánh dấu cả hai đã gửi, Person còn lại mất file **vĩnh viễn**. Nay Hub tự trỏ tới nội dung đã có trong kho. |
| `merge()` dùng `documents.update()` | `IntegrityError` khi hai Person chung một CV — đúng tình huống hay gặp nhất khi gộp. |
| Lỗi CSDL tạm thời trả `rejected` | `rejected` là vĩnh viễn ở phía Edge; một lần nghẽn thoáng qua làm mất hẳn bản ghi. Nay trả `retry`. |
| Kích thước lô không kẹp ở Edge | Sửa `cauhinh.json` thành 1000 → mọi lô 413 → thất bại vĩnh viễn. Nay kẹp ở 200. |

### 10.3. Màn hình Hub trong Edge

Tab **Đồng bộ Hub** (`app/web/index.html` + `app/web/app.js`):

```text
Trạng thái hàng đợi   chờ gửi · đang gửi · đã lên Hub · thất bại
                      + kết quả lượt gần nhất
Kết nối               địa chỉ Hub · API key · mã máy (chỉ đọc)
                      Lưu · Kiểm tra kết nối · Khai báo máy
Đồng bộ tự động       tần suất, bật/tắt — mặc định TẮT
Nút                   Đồng bộ ngay · Đồng bộ lại từ đầu · Thử lại bản ghi lỗi
```

Hai chi tiết dễ làm sai:

**Ô API key trống nghĩa là "giữ khoá đang có"**, không phải "xoá khoá". Ô mật
khẩu luôn hiện trống vì không bao giờ đọc ngược khoá ra được; coi trống là xoá
sẽ khiến người dùng mất kết nối mỗi lần bấm Lưu để đổi tần suất.

**Bật đồng bộ tự động thì lưu tần suất trước.** Người dùng đổi số trong ô rồi
bấm Bật mà không bấm Lưu sẽ thấy nó chạy theo giá trị cũ.

`tests/test_sync_service.py::ScreenTest` canh tên phương thức giữa JS và Python
không lệch nhau — lệch thì nút bấm im lặng không phản hồi, và không có lỗi nào
hiện ra.

### 10.4. Còn lại

* Không có thương lượng phiên bản giao thức giữa Edge và Hub. Edge mới gửi
  `entity_type` lạ tới Hub cũ vẫn hỏng, nhưng nay chỉ hỏng **bản ghi đó** chứ
  không hỏng cả lô.
* `DATA_UPLOAD_MAX_MEMORY_SIZE` không áp cho body do DRF đọc (DRF đọc
  `request.stream`, không phải `request.body`), nên hai endpoint Edge thực tế
  không có trần kích thước request ngoài giới hạn lô và giới hạn file.
