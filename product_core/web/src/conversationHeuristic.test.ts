import { describe, expect, it } from "vitest";
import { looksConversational } from "./conversationHeuristic";

describe("looksConversational", () => {
  it("treats explicit people-search phrasing as not conversational", () => {
    expect(looksConversational("Tìm ứng viên BA ở Hà Nội")).toBe(false);
    expect(looksConversational("lọc hồ sơ có SQL")).toBe(false);
    expect(looksConversational("danh sách khách hàng tiềm năng")).toBe(false);
  });

  it("routes knowledge / lookup questions to the assistant stream", () => {
    expect(looksConversational("Radar là ai?")).toBe(true);
    expect(looksConversational("xu hướng tuyển dụng fintech năm 2026")).toBe(true);
    expect(looksConversational("cho tôi biết lãi suất mới nhất")).toBe(true);
    expect(looksConversational("so sánh hai hồ sơ vừa rồi")).toBe(true);
  });

  it("falls back to the question mark for anything else", () => {
    expect(looksConversational("bảng lương ngành ngân hàng thế nào?")).toBe(true);
    expect(looksConversational("Nguyễn Văn A")).toBe(false);
  });
});
