# AI Talent Search

> **Phạm vi search/retrieval/evidence/answer:** nguồn thực thi chi tiết là `RADAR_AI_SEARCH_EXECUTION_BACKLOG.md` (ticket `SEARCH-*`). Khi hai tài liệu nói khác nhau về retrieval, evidence, completeness hay coverage, backlog đó thắng; tài liệu này giữ phần ngoài phạm vi ấy.

**Phase:** 7 — hoàn thành
**Master Plan:** mục 19.3, 22, 23, 42
**Vị trí:** `server/talent/{hiring_need,scoring,ai_search}.py`

---

## 1. Ranh giới: LLM làm gì, code làm gì

```text
1. hiring_need.parse()    LLM   dịch câu hỏi -> tiêu chí có cấu trúc
2. search.search()        CODE  truy hồi, đúng hàm Phase 6 đã dùng
3. semantic_index.search  CODE  truy hồi song ngữ trên toàn văn mọi CV đã bóc tách
4. scoring.score_person() CODE  chấm điểm nền có thể kiểm toán
5. ai_search.explain()    LLM   đọc evidence CV, chấm độ phù hợp và semantic rerank
```

**LLM không tự quyết toàn bộ điểm.** Điểm cuối kết hợp 40% điểm code có thể kiểm toán
và 60% `fit_score` ngữ nghĩa của LLM; giá trị LLM thiếu hoặc sai khuôn bị bỏ qua. Cách
này giữ một mốc ổn định nhưng cho AI xử lý cách viết Việt/Anh, từ đồng nghĩa và bằng
chứng kinh nghiệm không nằm trong trường dữ liệu chuẩn.

- Cùng một câu hỏi phải cho cùng một thứ tự. LLM thì không.
- Recruiter hỏi *"vì sao người này xếp trên người kia"* phải trả lời được bằng con số,
  không phải bằng *"model thấy vậy"*.
- Trọng số chỉnh được thì chỉnh được. Trực giác của model thì không.

**LLM chỉ được đọc FACT nghiệp vụ và các cửa sổ evidence liên quan.** Code quét toàn bộ
text đã bóc từ CV, chọn các vùng quanh title/skill/location/company cần tìm rồi giới hạn
prompt; vì vậy nội dung ở cuối CV không bị bỏ qua nhưng không nhét nguyên 40 CV vào một
request. Các fact còn gồm chức danh, kinh nghiệm, kỹ năng, ngành, học vấn, nơi ở và dữ liệu CRM an toàn cần cho gợi ý sản phẩm;
không truyền tên, email hoặc số điện thoại. Đây là thứ chặn
nó bịa ra lý do khớp trái với dữ liệu — thứ duy nhất nó có để kể chính là thứ hệ thống
đã khẳng định. Có test canh: prompt giải thích không được chứa email/điện thoại.

**Retrieval ưu tiên recall trước khi precision.** Skill trong AI mode dùng OR để hồ sơ
đạt 4/5 kỹ năng không bị SQL loại oan; pool chấm tăng lên 500 rồi hợp nhất với chỉ mục
semantic của toàn văn CV. Chỉ mục chuẩn hóa dấu, cách viết và các khái niệm Việt/Anh
(`data`/`dữ liệu`, `banking`/`ngân hàng`), vì vậy không phụ thuộc CV có cùng định dạng.
Sau đó code score và AI rerank mới cắt theo ngưỡng,
không chèn hồ sơ yếu chỉ để đủ 20 người.

Chỉ mục được cập nhật khi hồ sơ/CV thay đổi. Sau khi triển khai migration lần đầu cho
kho dữ liệu đã có, chạy `python manage.py rebuild_talent_semantic_index`; lệnh có thể
chạy lại an toàn vì dùng dấu vân tay nội dung và bỏ qua bản không đổi.

### Phản hồi nhanh hai giai đoạn

Giao diện gửi lượt `quick` để nhận tối đa 20 kết quả sơ bộ ngay sau khi AI hiểu nhu cầu
và truy hồi/chấm nền. Nó tự gửi tiếp chính bộ tiêu chí đã hiểu sang lượt `deep`, nên
không tốn thêm một lượt LLM để hiểu lại câu hỏi. Khi phân tích evidence hoàn tất, cùng
một tin nhắn được thay bằng thứ tự sâu; nếu provider lỗi, kết quả sơ bộ vẫn còn để dùng.

### Bộ nhớ hội thoại

Mỗi màn hình giữ một `conversation_id`. Server lưu riêng theo người dùng và màn hình,
đưa tối đa 8 lượt gần nhất vào prompt, đồng thời tóm tắt các lượt cũ hơn. Bản nhớ chỉ
chứa câu hỏi, câu trả lời và tiêu chí đã hiểu, không sao chép CV hay thông tin liên hệ.

### Một màn hình cho Recruiter và RM

Câu hỏi mẫu, tiêu chí và bộ lọc không mặc định người đang tìm là ứng viên hay khách hàng.
Cùng một kết quả có hai nhóm khuyến nghị bổ sung cho từng người:

- vị trí tuyển dụng phù hợp và chiến lược tiếp cận của Recruiter;
- sản phẩm ngân hàng phù hợp và chiến lược tiếp cận của RM.

Khuyến nghị chỉ là hỗ trợ khai thác; người dùng mở Person 360 và quyết định luồng nghiệp vụ sau.

### Cache phân tích dùng chung

`TalentAIAnalysis` lưu kết quả theo khóa gồm phiên bản thuật toán, câu hỏi đã chuẩn hóa và giới hạn
kết quả. Viết hoa/thường hoặc thừa khoảng trắng không tạo lượt AI mới. Bản ghi chỉ giữ `person_id`,
điểm, diễn giải và khuyến nghị; thông tin nhận dạng cá nhân không được sao chép vào cache.

Khi tìm lại, hệ thống lấy dữ liệu Person hiện hành rồi ghép với phân tích đã lưu, trả `cache_hit` và
`analyzed_at` để giao diện nói rõ nguồn và độ mới. Chỉ `force: true` từ nút **Phân tích lại bằng AI**
mới thay thế bản phân tích. Khóa hàng trong transaction ngăn hai người đồng thời trả token cho cùng
một câu hỏi; lượt đến sau nhận HTTP 409 và thử lại sau.

### Tài liệu đính kèm

Ô hỏi bằng lời nhận tối đa 5 tệp, mỗi tệp tối đa 10 MB: PDF, DOCX, XLSX, PPTX, TXT,
Markdown, CSV và JSON. Backend trích phần chữ cần thiết với trần 60.000 ký tự cho cả lượt,
không lưu file tạm thành hồ sơ hay tài liệu của Person. Dấu vân tay của nội dung đã trích là một
phần của khóa cache: cùng câu hỏi nhưng tài liệu khác phải phân tích riêng; cùng câu hỏi và cùng
nội dung tài liệu được dùng lại. Khi người dùng bấm phân tích lại trong phiên hiện tại, trình duyệt
gửi lại đúng các tệp của thông điệp đó.

### Ngoại lệ duy nhất: bước 3 — độ gần chức danh

Sáu trong bảy chiều là dữ kiện đo được: số năm kinh nghiệm, nơi ở, độ mới của hồ sơ.
Chức danh thì không — nó là câu hỏi về **ngôn ngữ**, và so khớp chuỗi trả lời sai đến
mức người dùng nhìn là biết:

```text
"BI Developer"                    vs "Data Analyst"  →  0.00
"Chuyên viên Phân tích Dữ liệu"   vs "Data Analyst"  →  0.00   (cùng một nghề!)
"Data Engineer"                   vs "Data Analyst"  →  0.50
```

Người thứ nhất làm báo cáo và dashboard cả ngày; người thứ hai là **đúng cái nghề đó
viết bằng tiếng Việt**. Recruiter thấy họ xếp bét bảng là thôi không tin cả bảng điểm —
và bảng điểm không ai tin thì phần giải thích công phu phía trên cũng vô ích.

Nên `talent/semantic.py` để LLM trả lời đúng câu *"hai nghề này có gần nhau không"*.
Ba ràng buộc khiến việc đó vẫn **không phải** "LLM chấm điểm":

| Ràng buộc | Vì sao cần |
|---|---|
| LLM chỉ thấy **cặp chức danh**, không thấy con người nào | không có đường nào thiên lệch theo tên, tuổi, trường học |
| Kết quả **lưu lại và tái dùng** (`TitleSimilarity`) | cùng tìm kiếm cho cùng thứ tự, mãi mãi — và hiệu chỉnh trọng số mới có nghĩa |
| Điểm tổng **vẫn là tổng có trọng số** của bảy chiều | có test canh: tính tay lại phải ra đúng con số hệ thống trả về |

Chấm thật với Gemini, `Data Analyst` làm chuẩn:

```text
1.00  Chuyên viên Phân tích Dữ liệu   tên gọi tiếng Việt của cùng vị trí
0.80  BI Developer                    cùng xây dashboard và trực quan hoá
0.60  Data Scientist                  cùng SQL/Python, nhưng thiên về mô hình dự báo
0.50  Business Analyst                cùng phân tích, nhưng thiên về quy trình nghiệp vụ
0.30  Chuyên viên Phân tích Tín dụng  cùng tư duy phân tích, khác lĩnh vực
0.10  Kế toán tổng hợp                chỉ chung việc làm với số liệu
```

Lý do nói về **việc phải làm**, không nói về chữ — đó là điều kiện trong prompt.

**Chi phí gần như bằng không sau vài lượt.** Khoá theo cặp chức danh chứ không theo con
người: kho 20 nghìn hồ sơ chỉ có vài trăm chức danh khác nhau. Một lượt tìm kiếm giải
quyết mọi cặp còn thiếu trong **đúng một** lời gọi; lượt tìm thứ hai tốn **0** lời gọi.

Không gọi được LLM thì lùi về so khớp chuỗi và **nói rõ trên màn hình là "mới so chữ"** —
im lặng ở đây sẽ khiến người đọc tưởng hệ thống đã hiểu nghề mà vẫn chấm thấp.

---

## 2. Chấm điểm

Bảy chiều, mỗi chiều trả về điểm 0..1 kèm bằng chứng:

| Chiều | Trọng số | Ghi chú |
|---|---|---|
| `skills` | 0.30 | Nặng nhất — recruiter lọc kỹ năng trước tiên |
| `title` | 0.18 | Khớp toàn phần hoặc theo từ |
| `experience` | 0.15 | Ngoài khoảng thì **giảm dần**, không loại thẳng |
| `location` | 0.12 | |
| `industry` | 0.08 | |
| `freshness` | 0.10 | **Luôn chấm** |
| `reachability` | 0.07 | **Luôn chấm** |

Chỉnh qua `settings.TALENT_SCORING_WEIGHTS`.

**Chỉ chấm chiều mà câu hỏi có nhắc tới.** Hỏi *"biết SQL"* mà bị trừ điểm vì không ở
Hà Nội — trong khi câu hỏi không hề nhắc nơi ở — là sai.

**Trừ hai chiều luôn được chấm:** một hồ sơ nguội ba năm hoặc không có cách liên hệ thì
recruiter không dùng được, bất kể khớp đến đâu (Master Plan mục 23).

**Thiếu kinh nghiệm thì giảm dần chứ không loại.** Thiếu nửa năm khác hẳn thiếu năm năm,
và recruiter thường vẫn muốn xem người sát ngưỡng.

**Khớp kỹ năng theo bao hàm hai chiều:** `SQL` khớp `T-SQL`; `Power BI` khớp `PowerBI`.
Kỹ năng được gõ tự do trong CV nên biến thể rất nhiều, và bỏ sót gây hại hơn khớp rộng.

---

## 3. Giải thích (Master Plan mục 19.3)

```text
DỮ LIỆU CHO BIẾT   FACT      do bộ chấm điểm sinh ra, không phải LLM
SUY LUẬN           INFERENCE LLM, chỉ được suy từ FACT
CHƯA BIẾT          UNKNOWN   dữ liệu không nói gì
NÊN LÀM TIẾP       ACTION    LLM
```

Một lượt gọi LLM cho cả nhóm 5 người, không phải 5 lượt: 5 × 5 giây = 25 giây là không
chấp nhận được.

**Không giải thích được vẫn trả kết quả.** FACT đã đủ để recruiter tự đánh giá; mất phần
diễn giải là mất một tiện ích, không phải mất chức năng.

---

## 4. Hỏng thì vẫn phải chạy

| Hỏng gì | Hệ quả |
|---|---|
| LLM không dịch được câu hỏi | Lùi về **dò từ khoá**, có báo trên tiến trình |
| LLM trả rác / JSON hỏng | Như trên |
| LLM bịa khoá lạ | Bị loại, ghi vào `dropped` |
| LLM trả số vô lý (`min_years: 999`) | Bị loại |
| `min_years > max_years` | Bỏ `max_years` — giữ lại thì không bao giờ có kết quả |
| Không giải thích được | Vẫn trả kết quả kèm FACT |

**Mất AI không được biến ô tìm kiếm thành ô hỏng.**

### Dò từ khoá — `talent/keywords.py`

Bản đầu lùi về **ném nguyên câu hỏi vào tìm-chữ-tự-do**. Nghe an toàn, thực tế
trả về **0 kết quả**: không hồ sơ nào chứa nguyên văn *"Tôi cần Data Analyst ở
Hà Nội biết SQL và Python"*. Đó là kiểu hỏng im lặng tệ nhất — hệ thống trông
như đang chạy, chỉ là không tìm thấy ai. Lỗi này bị bắt bằng ảnh chụp màn hình
lúc khoá Gemini dính giới hạn tốc độ, không phải bằng test.

Bản hiện tại dò **kỹ năng và nơi ở có thật trong CSDL**:

```python
skills, locations = keywords.vocabulary()      # lấy từ TalentProfile
found = [s for s in skills if s.lower() in question.lower()]
```

Từ vựng lấy từ chính dữ liệu chứ không viết cứng — danh sách viết cứng vừa
thiếu (công nghệ mới ra) vừa thừa (thứ không ai trong kho có). Lấy từ dữ liệu
thì tiêu chí rút ra **luôn là thứ tìm được người**, đúng mục đích của bước lùi.

Chỉ khi không dò được gì mới dùng cả câu làm `text`.

Cùng một module này được `hiring/jd.py` dùng lại khi đọc JD — hai chỗ gọi cùng
một mô hình cho cùng một việc thì lúc mô hình bận cũng phải lùi về cùng một chỗ.
Hai đường lui khác nhau nghĩa là một trong hai sẽ mục dần mà không ai biết.

Khoá miễn phí giới hạn ~15 lượt/phút và đã dính giới hạn **ba lần trong một
buổi** lúc dựng dự án. Đây không phải nhánh phòng xa hiếm gặp; nó sẽ chạy thật,
kể cả ngày demo.

---

## 5. Đo thật với Gemini

### Ba câu hỏi tiếng Việt tự nhiên

| Câu hỏi | AI hiểu | Kết quả |
|---|---|---|
| "Senior Data Analyst ở Hà Nội biết SQL và Python, trên 3 năm" | title, location, skills, min_years | 1 người, 100đ |
| "Ai đang làm về dữ liệu ở Hà Nội mà từng làm ngân hàng?" | title `Data`, location, company | 2 người |
| "Cần người biết Java làm backend" | skills `[Java]`, title `Backend` | 1 người |

Thời gian: **6–10 giây** một lượt tìm (hai lượt gọi LLM). Khoảng 350–600 token cho
bước dịch, 430–630 token cho bước giải thích.

### Bài học 1: người hỏi tiếng Việt, CV viết tiếng Anh

Bản prompt đầu dịch *"làm về dữ liệu"* thành `title: "dữ liệu"` → **0 kết quả**, vì CV
ghi `Data Analyst`. Đã bổ sung hướng dẫn chuyển sang thuật ngữ như CV dùng
(`"làm về dữ liệu"` → `Data`), và dùng phần **lõi ngắn** để khớp được nhiều biến thể.

Test giả không bắt được lỗi này — tôi tự viết câu trả lời của LLM nên nó luôn "đúng".
Chỉ chạy thật với câu hỏi tiếng Việt tự nhiên mới lộ ra.

### Bài học 2: ⚠️ khoá Gemini miễn phí bị giới hạn tốc độ

**15 lượt gọi trong một phút là đã bị HTTP 429** — đúng nhịp một buổi demo bấm tìm vài
lần liên tiếp.

Router chuyển sang nhà cung cấp dự phòng khi gặp 429, nhưng **chỉ có một khoá thì không
có chỗ để chuyển**. Đã thêm: khi mọi nhà cung cấp đều lỗi tạm thời, đợi 3 giây rồi thử
lại một vòng.

> **Trước ngày demo phải có ít nhất hai khoá.** Retry cứu được lỗi nhất thời, không cứu
> được hạn mức đã cạn.

---

## 6. Giao diện

**Hiện tiến trình agent** (Master Plan mục 42) — việc đã làm, **không** hiện
chain-of-thought. Có test canh. 6–10 giây màn hình đứng im trong lúc pitch sẽ trông
như treo.

**Hiện tiêu chí AI hiểu** thành chip. Người dùng phải thấy AI hiểu câu hỏi thành gì để
sửa được, thay vì đoán xem viết lại thế nào cho AI hiểu đúng.

**Nút "Vì sao lại điểm này?"** mở bảng từng chiều kèm điểm và trọng số — điểm số là con
số giải thích được, không phải hộp đen.

---

## 7. Còn thiếu

- [x] ~~`find_similar` (Master Plan mục 22)~~ — làm sau đó, không phải trong Phase 7: `talent/semantic.py`
  cho LLM chấm ĐỘ GẦN CHỨC DANH giữa từng cặp (chức danh cần, chức danh ứng viên), kết quả cache theo
  cặp trong `TitleSimilarity` — LLM không thấy cả người, chỉ thấy hai chuỗi chữ.
- [x] ~~Dán JD rồi phân tích (Master Plan mục 20)~~ — Phase 8, `hiring/jd.py`
- [x] ~~Calibration: HM chấm Good Fit / Not Fit rồi AI xếp lại (mục 21)~~ — Phase 8, `hiring/calibration.py`
  (chỉnh trọng số, không fine-tune mô hình — giữ đúng "LLM diễn giải, code quyết định")
- [ ] Truyền phát tiến trình qua SSE thay vì chờ xong mới hiện
- [ ] Chiều `relationship` và `signals` — chưa có dữ liệu để chấm (chưa được đưa vào `talent/scoring.py`)
- [ ] So sánh chất lượng giữa các nhà cung cấp (`.env` giờ có 5 khoá Gemini còn dùng được, nhưng OpenAI/
  Grok/Claude/GreenNode chưa đủ lượt gọi thật để so sánh)
