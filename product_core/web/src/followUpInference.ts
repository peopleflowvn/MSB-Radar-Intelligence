import { AnswerTurn } from "./AnswerView";

export interface InferFollowUpOptions {
  domain?: "talent" | "rb" | "general";
  question?: string;
}

// Trích xuất các thực thể / từ khóa quan trọng từ câu hỏi và câu trả lời
const SKILL_KEYWORDS = [
  "Java", "Python", "React", "Nodejs", "Node.js", "Golang", "Go", ".NET", "C#", "PHP",
  "DevOps", "Cloud", "AWS", "Azure", "GCP", "Kubernetes", "Docker", "Data", "AI", "Machine Learning",
  "SQL", "Oracle", "Postgres", "Tester", "QA", "QC", "BA", "Business Analyst", "Product Owner", "Scrum Master",
  "Mobile", "iOS", "Android", "Flutter", "Frontend", "Backend", "Fullstack", "Security", "An toàn thông tin",
  "Microservices", "System Architect", "Kiến trúc sư"
];

const BANKING_KEYWORDS = [
  "Tín dụng", "Thẩm định", "Quản trị rủi ro", "Risk", "Kế toán", "Kiểm toán", "Giao dịch viên", "GDV",
  "Thanh toán quốc tế", "Ngoại hối", "Treasury", "SME", "KHDN", "KHCN", "Doanh nghiệp", "Bán lẻ",
  "Vận hành", "Thu hồi nợ", "Core Banking", "T24", "Thẻ"
];

const LOCATION_KEYWORDS = [
  "Hà Nội", "Hà nội", "HN", "TP.HCM", "TPHCM", "Hồ Chí Minh", "Sài Gòn", "Đà Nẵng",
  "Hải Phòng", "Cần Thơ", "Bình Dương", "Đồng Nai"
];

const SENIORITY_KEYWORDS = [
  "Senior", "Lead", "Trưởng nhóm", "Trưởng phòng", "Giám đốc", "Manager", "Tech Lead", "Principal", "Junior", "Fresher"
];

const RB_PRODUCT_KEYWORDS = [
  { key: "loan", label: "Vay mua nhà/kinh doanh", terms: ["vay", "mua nhà", "thế chấp", "kinh doanh", "thấu chi", "giải ngân", "lãi suất vay", "hạn mức vay"] },
  { key: "card", label: "Thẻ tín dụng", terms: ["thẻ", "credit", "tín dụng", "cashback", "hoàn tiền", "hạn mức thẻ", "chi tiêu thẻ"] },
  { key: "savings", label: "Tiết kiệm & CASA", terms: ["tiết kiệm", "gửi tiền", "casa", "tiền gửi", "lãi suất", "thanh toán", "dư nợ", "tài khoản"] },
  { key: "insurance", label: "Bảo hiểm & Đầu tư", terms: ["bảo hiểm", "bancassurance", "wealth", "đầu tư", "chứng chỉ quỹ", "bảo an", "nhân thọ"] },
];

function extractMatchingKeywords(text: string, list: string[]): string[] {
  const lower = text.toLowerCase();
  const matched: string[] = [];
  for (const item of list) {
    const itemLower = item.toLowerCase();
    const regex = new RegExp(`\\b${itemLower.replace(/[-/\\^$*+?.()|[\]{}]/g, "\\$&")}\\b`, "i");
    if (regex.test(lower) || lower.includes(itemLower)) {
      matched.push(item);
    }
  }
  return matched;
}

function detectRbProduct(text: string): string | null {
  const lower = text.toLowerCase();
  for (const prod of RB_PRODUCT_KEYWORDS) {
    if (prod.terms.some((term) => lower.includes(term))) {
      return prod.key;
    }
  }
  return null;
}

function isComparisonQuery(text: string): boolean {
  return /so sánh|đối chiếu|khác nhau|bảng so sánh|ai hơn|ai tốt hơn|compare/i.test(text);
}

function isDraftQuery(text: string): boolean {
  return /soạn|viết thư|gửi mail|thư mời|email|kịch bản|tin nhắn|sms|gửi thư|bản nháp/i.test(text);
}

function isCountOrStatsQuery(text: string): boolean {
  return /bao nhiêu|thống kê|tổng số|tỷ lệ|phân bố|đếm|tổng cộng/i.test(text);
}

function isDetailOrProbeQuery(text: string): boolean {
  return /kinh nghiệm của|chi tiết về|profile của|điểm mạnh của|hồ sơ của|thông tin về/i.test(text);
}

function isMissingOrEmptyAnswer(text: string): boolean {
  return /không tìm thấy|kho không có|chưa có hồ sơ|chưa có khách hàng|không có kết quả|nới điều kiện|không có ai thoả|không có dữ liệu|0 hồ sơ/i.test(text);
}

/**
 * Suy luận thông minh bộ câu hỏi tiếp theo dựa trên ngữ cảnh câu hỏi, kết quả trả lời và danh sách đối tượng.
 */
export function inferFollowUpQuestions<TPerson = any>(
  turn: AnswerTurn<TPerson>,
  options?: InferFollowUpOptions,
): string[] {
  const domain = options?.domain ?? "talent";
  const question = (options?.question || "").trim();
  const answerText = (turn.text || "").trim();
  const people = (turn.people || []) as unknown as Array<{ person_id?: number; name?: string; display_name?: string }>;
  const peopleCount = people.length;
  const p1Name = people[0]?.name || people[0]?.display_name || "";
  const p2Name = people[1]?.name || people[1]?.display_name || "";

  const qLower = question.toLowerCase();
  const aLower = answerText.toLowerCase();

  const emptyResult = isMissingOrEmptyAnswer(answerText) || (peopleCount === 0 && (qLower.includes("tìm") || qLower.includes("ai")));
  const isComparison = isComparisonQuery(question);
  const isDraft = isDraftQuery(question);
  const isCount = isCountOrStatsQuery(question) || (turn.trace as any)?.count?.exact;
  const isDetail = isDetailOrProbeQuery(question);
  const hasWebSources = (turn.webSources && turn.webSources.length > 0) || (turn.sources && turn.sources.some((s) => (s as any).url));

  // --- TẬP LUẬT CHO TALENT SEARCH (TUYỂN DỤNG & NHÂN TÀI) ---
  if (domain === "talent") {
    const skills = extractMatchingKeywords(question + " " + answerText, [...SKILL_KEYWORDS, ...BANKING_KEYWORDS]);
    const locations = extractMatchingKeywords(question + " " + answerText, LOCATION_KEYWORDS);
    const seniorities = extractMatchingKeywords(question, SENIORITY_KEYWORDS);

    // 1. Kết quả trống / Không tìm thấy ứng viên phù hợp
    if (emptyResult) {
      const qSkills = extractMatchingKeywords(question, [...SKILL_KEYWORDS, ...BANKING_KEYWORDS]);
      const suggestions: string[] = [];
      if (qSkills.length > 0 && locations.length > 0) {
        suggestions.push(`Tìm ứng viên có kỹ năng tương đương hoặc chuyển đổi sang ${qSkills[0]}`);
        suggestions.push(`Nới lỏng tiêu chí số năm kinh nghiệm để tìm thêm ứng viên tiềm năng`);
        suggestions.push(`Tìm ứng viên ${qSkills[0]} tại các địa bàn lân cận hoặc chấp nhận làm việc linh hoạt`);
      } else if (qSkills.length > 0) {
        suggestions.push(`Tìm ứng viên có kỹ năng tương đương hoặc chuyển đổi sang ${qSkills[0]}`);
        suggestions.push("Nới lỏng tiêu chí số năm kinh nghiệm để tìm thêm ứng viên tiềm năng");
        suggestions.push("Mở rộng tìm kiếm sang các vị trí/chức danh công việc tương tự");
      } else {
        suggestions.push("Nới lỏng tiêu chí số năm kinh nghiệm để tìm thêm ứng viên tiềm năng");
        suggestions.push("Mở rộng tìm kiếm sang các vị trí/chức danh công việc tương tự");
        suggestions.push("Đề xuất điều chỉnh bộ tiêu chí tuyển dụng dựa trên dữ liệu hiện có trong kho");
      }
      return suggestions.slice(0, 3);
    }

    // 2. Người dùng vừa yêu cầu So Sánh
    if (isComparison) {
      const suggestions: string[] = [];
      if (p1Name && p2Name) {
        suggestions.push(`Đánh giá xem giữa ${p1Name} và ${p2Name}, ai phù hợp làm Lead hơn?`);
        suggestions.push(`Soạn bộ câu hỏi phỏng vấn để đánh giá sâu sự khác biệt giữa hai người`);
        suggestions.push(`Soạn thư mời phỏng vấn cho ${p1Name}`);
      } else if (p1Name) {
        suggestions.push(`Đánh giá ai là người có tiềm năng nhất trong nhóm trên?`);
        suggestions.push(`Soạn câu hỏi phỏng vấn kỹ thuật cho ${p1Name}`);
        suggestions.push(`Soạn thư mời phỏng vấn cho ${p1Name}`);
      } else {
        suggestions.push("Ai là ứng viên có số năm kinh nghiệm thực chiến nhiều nhất?");
        suggestions.push("Soạn câu hỏi phỏng vấn để kiểm tra điểm còn khuyết của các ứng viên");
        suggestions.push("Soạn thư mời phỏng vấn cho ứng viên tiềm năng nhất");
      }
      return suggestions.slice(0, 3);
    }

    // 3. Người dùng vừa yêu cầu Soạn thư / Email / Kịch bản
    if (isDraft) {
      const targetName = p1Name || "ứng viên";
      return [
        "Chỉnh sửa thư theo tông giọng trang trọng và nhấn mạnh văn hóa MSB",
        "Bổ sung thông tin về chế độ đãi ngộ, phụ cấp và địa điểm làm việc",
        `Lên danh sách các câu hỏi phỏng vấn chuyên sâu cho ${targetName}`,
      ];
    }

    // 4. Người dùng hỏi thống kê / số lượng
    if (isCount) {
      return [
        "Phân bố ứng viên theo số năm kinh nghiệm và trình độ học vấn",
        "Top các kỹ năng và chứng chỉ phổ biến nhất trong nhóm này",
        "Liệt kê danh sách chi tiết các ứng viên tiêu biểu nhất",
      ];
    }

    // 5. Tìm thấy nhiều ứng viên (>= 2)
    if (peopleCount > 1) {
      const suggestions: string[] = [];

      // So sánh: nêu tên cụ thể nếu có
      if (p1Name && p2Name) {
        suggestions.push(`📊 Lập bảng so sánh chi tiết giữa ${p1Name} và ${p2Name}`);
      } else {
        suggestions.push("📊 Lập bảng so sánh chi tiết các ứng viên này");
      }

      // Đào sâu chuyên môn / địa bàn / cấp bậc
      if (locations.length > 0) {
        suggestions.push(`Ai trong số các ứng viên này đang ở khu vực ${locations[0]}?`);
      } else if (skills.length > 0) {
        suggestions.push(`Ai trong số đó có kinh nghiệm ${skills[0]} thực chiến sâu nhất?`);
      } else if (seniorities.length > 0) {
        suggestions.push(`Ai có năng lực đảm nhiệm vị trí ${seniorities[0]} tốt hơn?`);
      } else if (qLower.includes("ngân hàng") || aLower.includes("ngân hàng")) {
        suggestions.push("Ai trong số đó từng làm việc tại các Ngân hàng lớn?");
      } else {
        suggestions.push("Ai trong số đó có nhiều năm kinh nghiệm quản lý/lead team nhất?");
      }

      // Hành động tiếp theo linh hoạt
      if (p1Name) {
        suggestions.push(`Soạn bộ câu hỏi phỏng vấn kỹ thuật cho ${p1Name}`);
      } else {
        suggestions.push("Soạn thư mời phỏng vấn cho ứng viên phù hợp nhất");
      }
      return suggestions.slice(0, 3);
    }

    // 6. Tìm thấy đúng 1 ứng viên hoặc hỏi chi tiết 1 người
    if (peopleCount === 1 || isDetail) {
      const target = p1Name || "ứng viên này";
      return [
        `Tóm tắt điểm mạnh nổi bật và các dự án tiêu biểu của ${target}`,
        `Soạn bộ câu hỏi phỏng vấn chuyên môn dành riêng cho ${target}`,
        `Tìm thêm các ứng viên khác trong kho có profile tương đương ${target}`,
      ];
    }

    // 7. Tra cứu thông tin bên ngoài / Web / Chính sách
    if (hasWebSources) {
      return [
        "Chính sách và tiêu chuẩn này áp dụng thế nào tại MSB?",
        "So sánh quy định này với mặt bằng chung các ngân hàng TMCP",
        "Tóm tắt các điểm quan trọng cần lưu ý khi triển khai",
      ];
    }

    // Mặc định cho Talent
    return [
      skills.length > 0
        ? `Có hồ sơ ứng viên ${skills[0]} nào khác liên quan không?`
        : "Gợi ý thêm tiêu chí tìm kiếm mở rộng trong kho",
      locations.length > 0
        ? `Thống kê số lượng ứng viên tại ${locations[0]}`
        : "Thống kê số lượng ứng viên theo từng khu vực",
      "Đề xuất bộ câu hỏi phỏng vấn đánh giá năng lực cho vị trí này",
    ];
  }

  // --- TẬP LUẬT CHO GROWTH RADAR (KHAI THÁC KHÁCH HÀNG & BÁN CHÉO) ---
  if (domain === "rb") {
    // 1. Kết quả trống / Không tìm thấy khách hàng
    if (emptyResult) {
      return [
        "Quét thêm các tín hiệu nhu cầu tài chính trong 30 ngày gần đây",
        "Gợi ý tiêu chí lọc khách hàng tiềm năng cho các sản phẩm tài chính khác",
        "Khách hàng nào có lịch sử giao dịch gần khớp nhất với điều kiện?",
      ];
    }

    // 2. Người dùng vừa yêu cầu Soạn kịch bản / Tin nhắn
    if (isDraft) {
      const targetName = p1Name || "khách hàng";
      return [
        "Rút gọn kịch bản để thực hiện cuộc gọi tư vấn nhanh trong 2-3 phút",
        "Bổ sung các phương án xử lý từ chối và giải đáp thắc mắc thường gặp",
        `Lên lịch nhắc việc và kế hoạch chăm sóc tiếp theo cho ${targetName}`,
      ];
    }

    // 3. Người dùng vừa yêu cầu So sánh
    if (isComparison) {
      return [
        p1Name ? `Khách nào có khả năng chốt hợp đồng và giải ngân nhanh hơn (${p1Name})?` : "Khách hàng nào có tiềm năng chuyển đổi cao nhất?",
        "Đề xuất gói giải pháp tài chính riêng biệt cho từng khách hàng",
        p1Name ? `Soạn tin nhắn tiếp cận cho ${p1Name}` : "Soạn tin nhắn tiếp cận khách hàng ưu tiên",
      ];
    }

    // 4. Nhận diện theo sản phẩm cụ thể
    const product = detectRbProduct(question + " " + answerText);
    if (product === "loan") {
      const target = p1Name || "khách hàng";
      return [
        `Đánh giá nhu cầu vốn và khả năng trả nợ của ${target}`,
        "Tư vấn gói lãi suất vay ưu đãi và thời hạn phù hợp nhất của MSB",
        `Soạn kịch bản gọi tư vấn gói vay cho ${target}`,
      ];
    }
    if (product === "card") {
      const target = p1Name || "khách hàng";
      return [
        `Khách nào có thói quen chi tiêu và điểm tín nhiệm tốt nhất để cấp thẻ?`,
        "Gợi ý dòng thẻ tín dụng MSB kèm ưu đãi hoàn tiền phù hợp nhất cho khách",
        `Soạn tin nhắn giới thiệu mở thẻ tín dụng cho ${target}`,
      ];
    }
    if (product === "savings") {
      const target = p1Name || "khách hàng";
      return [
        `Khách nào có số dư tiền gửi nhàn rỗi lớn cần tư vấn kỳ hạn tối ưu?`,
        "Gợi ý giải pháp tài khoản thanh toán và gói ưu đãi CASA cho khách",
        `Soạn tin nhắn tư vấn chương trình lãi suất tiết kiệm ưu đãi cho ${target}`,
      ];
    }
    if (product === "insurance") {
      const target = p1Name || "khách hàng";
      return [
        `Phân tích nhu cầu bảo hiểm và tích lũy tài chính cho ${target}`,
        "Gợi ý gói bảo an kết hợp đầu tư tối ưu cho khách",
        `Soạn kịch bản tiếp cận tư vấn bảo hiểm cho ${target}`,
      ];
    }

    // 5. Tìm thấy nhiều khách hàng (>= 2)
    if (peopleCount > 1) {
      return [
        "Khách nào có điểm ưu tiên cao nhất, nên liên hệ trước?",
        p1Name && p2Name
          ? `📊 Lập bảng so sánh nhu cầu và khả năng tiếp cận giữa ${p1Name} và ${p2Name}`
          : "📊 Lập bảng so sánh chi tiết các khách hàng này",
        p1Name ? `Soạn tin nhắn tiếp cận cho ${p1Name}` : "Soạn kịch bản gọi điện tiếp cận",
      ];
    }

    // 6. Tìm thấy đúng 1 khách hàng
    if (peopleCount === 1) {
      const target = p1Name || "khách hàng này";
      return [
        `Tóm tắt các tín hiệu hành vi và lý do nên ưu tiên tiếp cận ${target}`,
        `Soạn kịch bản gọi điện tiếp cận ${target}`,
        `Tìm thêm khách hàng tương tự ${target}`,
      ];
    }

    // 7. Thống kê / Tra cứu web
    if (isCount) {
      return [
        "Phân khúc khách hàng tiềm năng theo từng địa bàn và chi nhánh phụ trách",
        "Tỷ lệ khách hàng đã có tương tác so với khách hàng mới là bao nhiêu?",
        "Danh sách top khách hàng có điểm tiềm năng khai thác cao nhất",
      ];
    }
    if (hasWebSources) {
      return [
        "Chính sách sản phẩm và lãi suất mới nhất của MSB hiện tại ra sao?",
        "So sánh ưu đãi của MSB so với các ngân hàng đối thủ trên thị trường",
      ];
    }

    return [
      "Gợi ý thêm tiêu chí tìm kiếm mở rộng trong danh bạ",
      "Có khách hàng nào khác liên quan không?",
      "Quét thêm các cơ hội bán chéo sản phẩm hôm nay",
    ];
  }

  // --- GENERAL DOMAIN ---
  if (hasWebSources) {
    return [
      "Tóm tắt các ý chính quan trọng nhất",
      "Chính sách này áp dụng thế nào tại MSB?",
      "Có quy định hoặc thông tư liên quan nào mới hơn không?",
    ];
  }
  return [
    "Giải thích chi tiết hơn về nội dung trên",
    "Gợi ý các bước triển khai tiếp theo",
    "Có ví dụ hoặc trường hợp thực tế tương tự không?",
  ];
}
