import { describe, expect, it } from "vitest";
import { inferFollowUpQuestions } from "./followUpInference";
import { AnswerTurn } from "./AnswerView";

describe("followUpInference", () => {
  describe("Talent domain", () => {
    it("suggests search relaxation and equivalent skills when no candidates are found", () => {
      const turn: AnswerTurn<any> = {
        text: "Kho không có ai thoả mãn tiêu chí tìm kiếm này.",
        sources: [],
        people: [],
      };
      const suggestions = inferFollowUpQuestions(turn, {
        domain: "talent",
        question: "Tìm ứng viên Java 10 năm kinh nghiệm tại Hà Nội",
      });
      expect(suggestions.length).toBeGreaterThanOrEqual(2);
      expect(suggestions.some((s) => s.includes("Java") || s.includes("kinh nghiệm"))).toBe(true);
    });

    it("does NOT suggest comparison when user already asked for a comparison", () => {
      const turn: AnswerTurn<any> = {
        text: "Bảng so sánh năng lực của 2 ứng viên...",
        sources: [],
        people: [
          { person_id: 1, name: "Nguyễn Văn A" },
          { person_id: 2, name: "Trần Thị B" },
        ],
      };
      const suggestions = inferFollowUpQuestions(turn, {
        domain: "talent",
        question: "So sánh Nguyễn Văn A và Trần Thị B",
      });
      // Should propose next steps like picking lead or interview questions, not generic "Lập bảng so sánh"
      expect(suggestions.some((s) => s.includes("Lập bảng so sánh"))).toBe(false);
      expect(suggestions.some((s) => s.includes("Lead") || s.includes("phỏng vấn"))).toBe(true);
    });

    it("does NOT suggest drafting when user already asked to draft email", () => {
      const turn: AnswerTurn<any> = {
        text: "Kính gửi anh Nguyễn Văn A, Chúng tôi từ MSB...",
        sources: [],
        people: [{ person_id: 1, name: "Nguyễn Văn A" }],
      };
      const suggestions = inferFollowUpQuestions(turn, {
        domain: "talent",
        question: "Soạn thư mời phỏng vấn cho Nguyễn Văn A",
      });
      expect(suggestions.some((s) => s.includes("văn hóa MSB") || s.includes("đãi ngộ") || s.includes("phỏng vấn"))).toBe(true);
    });

    it("suggests comparison and skills probe when multiple candidates are returned", () => {
      const turn: AnswerTurn<any> = {
        text: "Tìm thấy 2 ứng viên phù hợp với yêu cầu React và Frontend.",
        sources: [],
        people: [
          { person_id: 1, name: "Lê Văn C" },
          { person_id: 2, name: "Phạm Văn D" },
        ],
      };
      const suggestions = inferFollowUpQuestions(turn, {
        domain: "talent",
        question: "Tìm ứng viên React",
      });
      expect(suggestions.some((s) => s.includes("Lê Văn C") && s.includes("Phạm Văn D"))).toBe(true);
      expect(suggestions.some((s) => s.includes("React") || s.includes("kinh nghiệm"))).toBe(true);
    });

    it("suggests breakdown distributions when count query is asked", () => {
      const turn: AnswerTurn<any> = {
        text: "Có 25 ứng viên thoả mãn.",
        sources: [],
        people: [],
      };
      const suggestions = inferFollowUpQuestions(turn, {
        domain: "talent",
        question: "Có bao nhiêu ứng viên Java trong kho?",
      });
      expect(suggestions.some((s) => s.includes("Phân bố") || s.includes("kỹ năng") || s.includes("tiêu biểu"))).toBe(true);
    });
  });

  describe("RB / Growth domain", () => {
    it("suggests loan-specific questions when query is about loan/mortgage", () => {
      const turn: AnswerTurn<any> = {
        text: "Khách hàng Nguyễn Văn X có nhu cầu vay mua nhà...",
        sources: [],
        people: [{ person_id: 10, name: "Nguyễn Văn X" }],
      };
      const suggestions = inferFollowUpQuestions(turn, {
        domain: "rb",
        question: "Khách nào cần vay mua nhà?",
      });
      expect(suggestions.some((s) => s.includes("vay") || s.includes("lãi suất"))).toBe(true);
    });

    it("suggests card-specific questions when query is about credit cards", () => {
      const turn: AnswerTurn<any> = {
        text: "Khách hàng Trần Thị Y có thói quen mua sắm qua thẻ...",
        sources: [],
        people: [{ person_id: 11, name: "Trần Thị Y" }],
      };
      const suggestions = inferFollowUpQuestions(turn, {
        domain: "rb",
        question: "Khách nào quan tâm thẻ tín dụng?",
      });
      expect(suggestions.some((s) => s.includes("thẻ") || s.includes("tín dụng") || s.includes("chi tiêu"))).toBe(true);
    });

    it("suggests signal scan extension when no customers are found", () => {
      const turn: AnswerTurn<any> = {
        text: "Chưa có khách hàng nào có đủ bằng chứng phù hợp.",
        sources: [],
        people: [],
      };
      const suggestions = inferFollowUpQuestions(turn, {
        domain: "rb",
        question: "Khách nào có số dư tiền gửi trên 5 tỷ?",
      });
      expect(suggestions.some((s) => s.includes("tín hiệu") || s.includes("tiêu chí lọc") || s.includes("giao dịch"))).toBe(true);
    });
  });
});
