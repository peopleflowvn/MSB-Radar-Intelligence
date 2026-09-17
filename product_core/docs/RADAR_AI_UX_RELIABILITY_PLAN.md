# Kế hoạch cải tiến trải nghiệm Radar AI

**Ngày lập:** 2026-09-09  
**Phạm vi:** Talent Radar, luồng hỏi đáp và tìm kiếm ứng viên bằng AI  
**Mục tiêu:** Radar tiếp tục xử lý khi người dùng chuyển tab hoặc rời màn hình, thể hiện trạng thái chờ rõ ràng, nhớ đúng người và file đang được nói tới, và phục hồi được một lượt đang chạy mà không tạo câu trả lời trùng.

## 1. Kết luận từ trải nghiệm hiện tại

Hai ảnh người dùng cung cấp cho thấy hai lỗi độc lập:

1. Tin nhắn `Đã nhận yêu cầu — Radar đang phân tích…` có thể đứng yên, không cho biết Radar còn chạy, đã mất kết nối hay đã lỗi.
2. Radar đã diễn giải đúng yêu cầu “lấy hồ sơ Nguyễn Tiến Đạt và phân tích chi tiết” trong phần mở đầu, nhưng câu trả lời cuối lại hỏi người dùng muốn làm gì với ai. Như vậy bước hiểu yêu cầu và bước thực thi không dùng chung một đối tượng đã được giải định danh.

Đối chiếu code hiện tại cho thấy:

- `AiSearch.tsx` chủ động hủy stream khi component bị tháo khỏi màn hình và khi tab ẩn quá 2,5 giây. Sau đó giao diện chỉ thử phục hồi kết quả trong khoảng 13 giây. Nếu tác vụ lâu hơn hoặc worker chưa ghi kết quả, giao diện kết luận lỗi dù máy chủ có thể vẫn đang chạy.
- State hội thoại đã được đưa ra ngoài route, nên chuyển trang trong cùng phiên thường không mất toàn bộ lịch sử. Tuy nhiên lượt đang chạy vẫn do `AiSearch` sở hữu; việc component bị tháo sẽ hủy kết nối.
- Backend Talent đã có `client_turn_id`, `AnswerRun`, background runner và endpoint lấy lại kết quả. Đây là nền tảng tốt để sửa theo hướng tăng dần, không cần viết lại toàn bộ Answer Engine.
- Tin nhắn đang chờ khởi tạo sẵn một chuỗi tĩnh. Vì đã có chữ, nhánh ba chấm chờ trong UI không được dùng; người dùng chỉ thấy một thẻ đứng yên giống ảnh.
- File đính kèm hiện là `File[]` trong bộ nhớ JavaScript. Khi gửi, backend bóc văn bản rồi ghép thẳng vào câu hỏi. Không có bản ghi attachment bền vững gắn với tin nhắn/lượt chạy.
- Giao diện chỉ chấp nhận PDF, Office và file văn bản; chưa chấp nhận PNG/JPEG/WebP. Vì vậy ảnh chưa có một đường xử lý chính thức.
- Khi mở lại hội thoại, API chỉ trả nội dung và metadata của tin nhắn; không có attachment để dựng lại thumbnail, nội dung đã trích xuất hoặc tham chiếu “ảnh vừa gửi”.
- Lịch sử tạm do giao diện gửi lên chỉ lấy câu trả lời của AI và để trống câu hỏi. Backend có lịch sử bền sau khi lượt được ghi, nhưng khoảng thời gian trước khi ghi xong và các lượt phục hồi có thể tạo ngữ cảnh thiếu.

## 2. Nguyên tắc thiết kế

1. **Lượt chạy thuộc về máy chủ.** Kết nối stream chỉ là kênh theo dõi; mất kết nối không đồng nghĩa hủy tác vụ.
2. **Mọi lượt có một mã bền vững.** Cùng `client_turn_id` chỉ được chạy một lần và chỉ tạo một cặp tin nhắn hỏi/đáp.
3. **Chuyển tab không phải lệnh Dừng.** Chỉ nút Dừng mới được phép hủy tác vụ.
4. **Trạng thái chờ phải phản ánh trạng thái thật.** Không dùng phần trăm giả; hiển thị bước đang thực hiện, thời gian đã chờ và tình trạng kết nối.
5. **Ngữ cảnh tham chiếu phải có cấu trúc.** Người, danh sách kết quả và file đính kèm cần có ID; không dựa hoàn toàn vào việc model đoán từ văn bản.
6. **Ảnh/CV là dữ liệu có quyền truy cập.** Lưu riêng tư, kiểm tra quyền ở mọi lần đọc và không đưa URL lưu trữ công khai vào lịch sử.

## 3. P0 — Lượt chạy không dừng khi chuyển tab

### 3.1. Hợp nhất vòng đời lượt chạy

Mở rộng cơ chế `AnswerRun` thành nguồn trạng thái bền cho toàn bộ lượt Talent:

- Lưu `user`, `surface`, `thread_id`, `client_turn_id`, trạng thái, bước hiện tại, heartbeat, thời hạn, lỗi công khai và thời điểm hoàn tất.
- Trạng thái chuẩn: `queued`, `understanding`, `retrieving`, `reading`, `composing`, `verifying`, `completed`, `failed`, `timed_out`, `cancelled`.
- Worker nhận quyền xử lý bằng claim trong cơ sở dữ liệu. Retry hoặc kết nối lại với cùng mã lượt chỉ theo dõi lượt cũ, không gọi model lần hai.
- Ghi câu hỏi và attachment reference trước khi bắt đầu xử lý. Ghi câu trả lời cuối cùng theo cùng mã lượt.
- Cập nhật heartbeat và bước thực hiện trong lúc Answer Engine chạy.

Trong giai đoạn đầu có thể tái sử dụng runner hiện tại. Trước khi mở rộng tải lớn, cần chuyển quyền sở hữu job từ thread trong tiến trình web sang worker/queue bền đang được hệ thống vận hành hỗ trợ; tiến trình web khởi động lại không được làm mất tác vụ đã nhận.

### 3.2. Tách submit khỏi stream

Thay luồng POST giữ kết nối dài bằng ba thao tác rõ ràng:

1. `POST /talent/turns/` nhận câu hỏi, thread và attachment ID; trả ngay `202` cùng `client_turn_id`.
2. `GET /talent/turns/{id}/events` stream các sự kiện từ lượt đã tồn tại. Kết nối có thể ngắt và nối lại bằng sequence/`Last-Event-ID`.
3. `GET /talent/turns/{id}` trả snapshot mới nhất và câu trả lời hoàn chỉnh nếu đã xong.

Endpoint hiện tại được giữ tương thích trong thời gian chuyển đổi, nhưng frontend mới không để request POST dài trở thành chủ sở hữu tác vụ.

### 3.3. Đưa trạng thái lượt đang chạy ra khỏi component

- Quản lý active turn trong `SearchStateProvider`, cùng cấp với state hội thoại, thay vì trong `AiSearch`.
- Lưu tối thiểu `thread_id`, `client_turn_id`, trạng thái và thời điểm bắt đầu vào `sessionStorage` hoặc IndexedDB. Không lưu binary file tại đây; chỉ lưu attachment ID.
- Khi đổi route, UI có thể ngừng render nhưng bộ điều phối lượt vẫn theo dõi hoặc kết nối lại khi cần.
- Khi tải lại trang hoặc quay lại tab, gọi snapshot endpoint và nối lại stream nếu lượt còn chạy.
- Loại bỏ hành vi coi `visibilitychange` là lý do abort. Khi tab hiện lại, đồng bộ snapshot ngay.
- Nút **Dừng** gọi endpoint cancel rõ ràng; chỉ thay trạng thái UI sau khi máy chủ xác nhận hoặc báo tác vụ đã hoàn tất.

### 3.4. Tiêu chí nghiệm thu P0

- Gửi một câu hỏi mất 30–90 giây, chuyển sang tab trình duyệt khác 20 giây rồi quay lại: câu trả lời tiếp tục chạy hoặc hiện kết quả hoàn chỉnh.
- Từ Talent chuyển sang hồ sơ một ứng viên rồi quay lại: giữ nguyên lượt, các bước và phần nội dung đã nhận.
- Tải lại trang giữa lúc chạy: trong tối đa 2 giây UI dựng lại trạng thái “đang xử lý” và cuối cùng nhận đúng kết quả.
- Mất mạng 15 giây rồi có mạng lại: tự phục hồi, không bắt người dùng gửi lại.
- Mỗi kịch bản trên chỉ có một model execution, một user message và một assistant message cho cùng `client_turn_id`.
- Khởi động lại một web process không làm mất lượt đã được queue nhận.

## 4. P0 — Trải nghiệm chờ có phản hồi và có thể tin được

### 4.1. Thẻ trạng thái đang làm việc

Thay chuỗi tĩnh bằng một thẻ trạng thái sống:

- Avatar có vòng sáng nhẹ; ba chấm chuyển động hoặc shimmer ở dòng bước hiện tại.
- Hiển thị nhãn bước lấy từ trạng thái backend, ví dụ: “Đang hiểu yêu cầu”, “Đang tìm trong kho ứng viên”, “Đang đọc 6 hồ sơ”, “Đang kiểm tra dẫn chứng”, “Đang soạn câu trả lời”.
- Hiển thị thời gian đã chờ, nhưng không hiển thị phần trăm khi backend không có tổng công việc đáng tin cậy.
- Có dòng bảo đảm: “Bạn có thể chuyển tab, Radar vẫn tiếp tục xử lý.”
- Giữ các bước đã xong với dấu kiểm; bước hiện tại có animation.
- Khi bắt đầu có nội dung, giữ timeline thu gọn phía trên và stream câu trả lời bên dưới.

### 4.2. Thông điệp theo thời gian

- 0–3 giây: hiệu ứng nhận yêu cầu và bước hiện tại.
- Sau 8 giây: thêm chi tiết thật từ backend, như số hồ sơ đang đọc nếu có.
- Sau 20 giây: “Yêu cầu này cần đọc nhiều bằng chứng hơn bình thường. Radar vẫn đang làm.”
- Mất kết nối: “Đã mất kết nối hiển thị, tác vụ vẫn chạy trên máy chủ — đang kết nối lại.”
- Quá deadline: hiển thị nguyên nhân công khai và hai hành động `Thử lại` / `Thu hẹp yêu cầu`; không để thẻ pending vô hạn.

### 4.3. Khả năng tiếp cận

- `aria-live="polite"` cho thay đổi bước, không đọc lại toàn bộ nội dung.
- Tôn trọng `prefers-reduced-motion` và thay animation bằng trạng thái tĩnh có dấu hiệu rõ.
- Animation không làm thay đổi chiều cao liên tục hoặc kéo trang xuống khi người dùng đang đọc.

### 4.4. Tiêu chí nghiệm thu chờ

- Không còn trường hợp thẻ `Đã nhận yêu cầu — Radar đang phân tích…` đứng yên quá 5 giây mà không có bước, heartbeat hoặc lỗi.
- Người dùng luôn phân biệt được bốn tình trạng: đang xử lý, mất kết nối nhưng còn chạy, đã hoàn tất, đã lỗi.
- Test với giảm chuyển động, bàn phím và trình đọc màn hình đạt các hành vi trên.

## 5. P0 — File và ảnh trở thành ngữ cảnh bền vững

### 5.1. Upload trước, gửi câu hỏi sau

Tạo `AssistantAttachment` hoặc mô hình tương đương, gồm:

- chủ sở hữu, thread, message/turn, tên file, MIME, kích thước, checksum;
- storage key riêng tư, trạng thái quét/đọc/OCR/vision;
- văn bản đã trích xuất hoặc mô tả ảnh có cấu trúc;
- extractor/model/version, lỗi công khai, thời điểm tạo và chính sách lưu giữ.

Luồng UI:

1. Người dùng chọn file/ảnh.
2. UI upload và nhận `attachment_id`; chip hiển thị `Đang tải` → `Đã đọc` hoặc lỗi cụ thể.
3. Khi gửi câu hỏi, payload chỉ tham chiếu các ID đã upload thành công.
4. Backend kiểm tra quyền sở hữu và gắn attachment vào user message trước khi chạy AI.

Không dùng blob URL hoặc đối tượng `File` làm nguồn sự thật của lịch sử.

### 5.2. Hỗ trợ ảnh

- Cho phép PNG, JPEG và WebP với giới hạn kích thước và pixel phù hợp.
- Nếu model vision được cấu hình, gửi ảnh cùng câu hỏi dưới dạng multimodal input có kiểm soát.
- Nếu không có vision, chạy OCR và mô tả bố cục; nói rõ phần nào đọc được và phần nào không.
- Ảnh CV/JD cần đi qua cùng chính sách PII, quyền đọc CV, retention và audit như tài liệu hiện tại.
- UI hiển thị thumbnail đã được cấp quyền, tên file và trạng thái xử lý; mở lại hội thoại vẫn thấy attachment.

### 5.3. Đưa attachment vào projection hội thoại

- Projection của lượt hiện tại chứa attachment ID, loại, nội dung trích xuất/mô tả và provenance.
- Projection các lượt sau chỉ mang các attachment liên quan trong cùng thread, theo ngân sách context rõ ràng.
- Các cụm “ảnh vừa gửi”, “CV này”, “ứng viên trong ảnh” được giải định danh bằng attachment gần nhất trước khi gọi planner.
- Nếu có nhiều ảnh có thể được nhắc tới, Radar hiển thị lựa chọn bằng thumbnail thay vì đoán.
- Tạo chat mới phải cắt hoàn toàn attachment scope; người dùng khác không thể đoán ID để đọc.

### 5.4. Tiêu chí nghiệm thu attachment

- Đính kèm ảnh và hỏi trong cùng một lượt: câu trả lời dùng được nội dung ảnh và dẫn rõ nguồn là ảnh nào.
- Chuyển tab trong lúc ảnh đang được đọc rồi quay lại: trạng thái và kết quả vẫn tiếp tục.
- Hỏi tiếp “phân tích kỹ ứng viên trong ảnh vừa gửi” mà không upload lại: Radar dùng đúng attachment.
- Reload và mở lại hội thoại: thumbnail/chip, trạng thái và tham chiếu vẫn còn.
- Chat mới và tài khoản khác không truy cập được attachment cũ.
- File không hỗ trợ, ảnh mờ hoặc OCR lỗi có thông báo cụ thể, không im lặng bỏ file khỏi context.

## 6. P0 — Nhớ đúng ứng viên trong câu hỏi tiếp theo

### 6.1. Một hợp đồng target dùng chung

Trước khi tạo preamble, chạy bước `resolve_targets` có đầu ra cấu trúc:

- `person_ids` và tên đã chuẩn hóa;
- nguồn tham chiếu: tên trực tiếp, thứ tự trong kết quả trước, pronoun hoặc attachment;
- mức chắc chắn và danh sách trùng tên cần phân biệt;
- hành động dự kiến: mở hồ sơ, phân tích, so sánh hay tạo nội dung.

Planner, preamble, retrieval và executor phải nhận cùng đối tượng này. Preamble chỉ được nói “đang lấy hồ sơ Nguyễn Tiến Đạt” khi executor đã có một `person_id` hợp lệ và người dùng có quyền đọc.

### 6.2. Quy tắc xử lý

- Một tên khớp đúng một người trong kết quả vừa rồi: đọc thẳng hồ sơ đó, không tìm lại toàn kho.
- Nhiều người trùng tên: đưa thẻ lựa chọn có dữ kiện phân biệt như chức danh/công ty gần nhất.
- Không có tên trong kết quả trước nhưng có một khớp chắc chắn trong kho: báo đang dùng hồ sơ nào rồi thực hiện.
- Không có khớp: nói không tìm thấy và gợi ý cách xác định; không hỏi lại “làm gì với ai” khi câu hỏi đã đủ rõ.
- “Lấy hồ sơ … và phân tích chi tiết” phải vào nhánh phân tích Person 360 dựa trên bằng chứng, không bị coi thành một action chung không xác định.

### 6.3. Tiêu chí nghiệm thu theo ảnh lỗi

Với một lượt trước có Nguyễn Tiến Đạt, câu tiếp theo `lấy hồ sơ của Nguyễn Tiến Đạt và phân tích chi tiết` phải:

- chọn đúng `person_id` từ kết quả trước;
- hiển thị target đã chọn nhất quán trong preamble và trace công khai;
- đọc hồ sơ có quyền truy cập và trả phân tích có dẫn chứng;
- nếu hồ sơ thiếu dữ liệu, nói rõ phần thiếu nhưng không quên người đang được hỏi;
- không phát câu “Bạn nói rõ hơn giúp tôi cần làm gì với ai không?”.

## 7. P1 — Khôi phục, lỗi và điều khiển của người dùng

- Nút `Thử lại` dùng cùng câu hỏi, attachment và thread nhưng tạo execution attempt mới dưới cùng logical turn; UI không nhân đôi tin nhắn.
- Nút `Dừng` hiển thị trạng thái “Đang dừng” cho tới khi server xác nhận.
- Cho phép gửi câu hỏi mới trong khi lượt cũ chạy theo một trong hai chính sách đã định: xếp hàng trong cùng thread hoặc tạo nhánh. Giai đoạn đầu nên xếp hàng để dễ hiểu.
- Khi lỗi, giữ phần nội dung và nguồn đã nhận; hiển thị mã hỗ trợ ngắn gắn với turn để vận hành tra log.
- Không đưa exception, tên provider nội bộ hoặc chi tiết hạ tầng vào thông báo cho recruiter/RM.

## 8. Đo lường và quan sát

Thêm dashboard theo surface và phiên bản frontend/backend:

- tỷ lệ lượt hoàn tất;
- tỷ lệ lượt hoàn tất sau khi tab bị ẩn hoặc route thay đổi;
- `time_to_first_status`, `time_to_first_answer`, tổng thời gian;
- tỷ lệ pending quá deadline và stuck-turn;
- số reconnect, tỷ lệ resume thành công, số execution trùng;
- tỷ lệ attachment upload/read thành công theo MIME;
- tỷ lệ follow-up giải đúng person/attachment, tỷ lệ phải hỏi phân biệt;
- tỷ lệ người dùng dừng, thử lại, bỏ cuộc và đánh giá 👍/👎;
- lỗi theo bước `understanding/retrieving/reading/composing/verifying`.

Mỗi event cần có `client_turn_id`, `thread_id`, stage, attempt và mã lỗi, nhưng log không chứa toàn văn CV, ảnh hoặc PII không cần thiết.

## 9. Kế hoạch kiểm thử

### Backend

- Claim/idempotency đồng thời từ hai web process.
- Disconnect subscriber không hủy worker.
- Reconnect từ sequence cũ nhận đủ trạng thái còn thiếu và kết quả cuối.
- Restart web process và restart worker có recovery theo lease.
- Cancel, timeout, retry và persist lỗi ở từng bước.
- Attachment ownership, MIME thực, checksum, retention và truy cập chéo tài khoản.
- Entity resolution cho tên trực tiếp, trùng tên, thứ tự, đại từ và attachment.

### Frontend

- Unmount/remount `AiSearch` trong lúc lượt chạy.
- `visibilitychange`, offline/online, reload và mở hội thoại từ sidebar.
- Không tạo message hoặc request trùng khi React render lại.
- Timeline chờ, reconnect, timeout, cancel và reduced motion.
- Upload ảnh/tài liệu, reload, follow-up dùng “ảnh vừa gửi”.

### Nghiệm thu trình duyệt thật

Chạy Playwright hoặc kịch bản tương đương trên Chrome/Edge desktop và mobile emulation. Bắt buộc có các kịch bản từ hai ảnh lỗi và dùng model thật trên một tập CV kiểm thử đã được phê duyệt. Unit test mock model không đủ để xác nhận trải nghiệm này.

## 10. Trình tự triển khai

### Đợt 1 — P0.1: bền hóa lượt chạy và phục hồi

- Schema trạng thái lượt, submit/snapshot/events/cancel API.
- Active-turn coordinator ngoài route.
- Bỏ abort do chuyển tab, reconnect vô thời hạn trong deadline server.
- Test đổi route, ẩn tab, reload và idempotency.

**Điều kiện phát hành:** toàn bộ tiêu chí mục 3.4 đạt trên staging.

### Đợt 2 — P0.2: trạng thái chờ

- Timeline và animation có reduced-motion.
- Heartbeat, elapsed time, reconnect/error states.
- Telemetry thời gian và stuck-turn.

**Điều kiện phát hành:** không còn pending tĩnh; dashboard phân biệt được running/disconnected/failed.

### Đợt 3 — P0.3: attachment và ảnh bền vững

- Attachment model, private upload, extraction/OCR/vision và UI thumbnail.
- Projection theo attachment ID và follow-up resolution.
- Security, retention và reload tests.

**Điều kiện phát hành:** toàn bộ tiêu chí mục 5.4 đạt, gồm kiểm tra chéo tài khoản.

### Đợt 4 — P0.4: target resolution nhất quán

- Structured target contract trước planner/preamble.
- Person 360 route cho yêu cầu phân tích tên cụ thể.
- Bộ eval câu hỏi tiếp theo và trường hợp trùng tên.

**Điều kiện phát hành:** kịch bản Nguyễn Tiến Đạt và bộ follow-up eval đạt ngưỡng; không có preamble/executor disagreement.

### Đợt 5 — P1 và tối ưu

- Queue nhiều câu hỏi, retry UX, lỗi vận hành và dashboard sản phẩm.
- Đo dữ liệu thật 1–2 tuần, ưu tiên tiếp theo theo abandonment và feedback.

## 11. Rollout và rollback

- Đặt các phần mới sau feature flags: durable turns, waiting card, durable attachments, structured targets.
- Canary theo nhóm người dùng nội bộ trước, sau đó recruiter/RM thử nghiệm có kiểm soát.
- Trong canary, giữ endpoint cũ làm fallback đọc; không chạy đồng thời hai engine cho cùng lượt.
- Rollback UI không được xóa `AnswerRun`, message hoặc attachment đã tạo; phiên bản cũ vẫn đọc được nội dung văn bản cuối.
- Chỉ mở rộng khi không tăng duplicate run, lỗi quyền hoặc P95 thời gian phản hồi ngoài ngưỡng đã chốt.

## 12. Definition of Done chung

Kế hoạch chỉ được coi là hoàn thành khi có đủ bốn loại bằng chứng:

1. Test tự động backend/frontend đạt.
2. Nghiệm thu trình duyệt thật cho chuyển tab, đổi route, reload, ảnh và follow-up người cụ thể.
3. Dashboard production cho thấy resume, stuck-turn, attachment và target resolution.
4. Recruiter/RM phổ thông hoàn thành kịch bản mà không cần biết cách viết prompt chuyên nghiệp, và không gặp lại hai lỗi trong ảnh.

