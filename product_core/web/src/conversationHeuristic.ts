// Heuristic phía client để quyết định gọi SSE (hội thoại/web) hay endpoint tìm kiếm.
// KHÔNG phải quyết định cuối — server có intent router riêng và vẫn tự định tuyến
// (`event: route`). Đây chỉ để tránh một vòng round-trip cho câu tìm người rõ ràng.
const SEARCH_WORDS =
  /\b(tìm|lọc|ứng viên|hồ sơ|nhân sự|khách hàng|candidate|cv|danh sách)\b/i;

// Câu hỏi kiến thức / tra cứu — nên để server (và có thể web search) xử lý.
const KNOWLEDGE_WORDS =
  /(tại sao|vì sao|như thế nào|là gì|là ai|bao nhiêu|khi nào|ở đâu|so sánh|giải thích|cho (tôi|mình) biết|tìm hiểu|thông tin về|xu hướng|mới nhất|hiện nay|năm 20\d\d|how |what |why |who |when )/i;

export function looksConversational(q: string): boolean {
  const t = q.trim().toLowerCase();
  if (KNOWLEDGE_WORDS.test(t)) return true;
  if (SEARCH_WORDS.test(t)) return false;
  return t.includes("?");
}
