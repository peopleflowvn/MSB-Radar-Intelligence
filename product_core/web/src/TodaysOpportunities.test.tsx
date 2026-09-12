import "@testing-library/jest-dom/vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it } from "vitest";
import TodaysOpportunities from "./TodaysOpportunities";
import { OpportunitySuggestionRow } from "./api";

/**
 * Thẻ "Cơ hội hôm nay" phải trả lời được ba câu trước khi RM bấm bất kỳ nút nào:
 * ai · vì sao bây giờ · nên làm gì. Thiếu câu giữa thì thẻ chỉ là một dòng
 * trong danh sách, và RM không có cơ sở để nhận hay bỏ.
 */

// Vitest cau hinh khong bat `globals`, nen auto-cleanup cua testing-library
// khong chay. Khong don thi DOM cong don qua tung bai va moi truy van deu bao
// "found multiple elements" — cung cach AiSearch.test.tsx da xu ly.
afterEach(() => {
  cleanup();
});

function suggestion(
  overrides: Partial<OpportunitySuggestionRow> = {},
): OpportunitySuggestionRow {
  return {
    id: 1,
    person: 7,
    person_name: "Nguyễn An",
    occupation: "Trưởng phòng kinh doanh",
    product: "mortgage",
    product_label: "Vay mua nhà",
    need_summary: "Đang tính mua nhà",
    why: ["Khách nhắc tới: mua nhà", "Tín hiệu trong 7 ngày qua (1 ngày trước)"],
    priority_score: 71.2,
    personalized_score: 79.2,
    personalized_why: ["Nằm trong địa bàn bạn phụ trách"],
    territory: "in",
    handoff_to: null,
    is_discovery: false,
    confidence: 0.9,
    value_band: "very_high",
    recommended_action: "CALL_NOW",
    action_label: "Gọi ngay",
    reasoning_summary: "",
    scores: { fit: 80, need: 90, timing: 100, reachability: 80, value: 100 },
    status: "new",
    status_label: "Mới",
    snoozed_until: null,
    created_at: "2026-08-29T08:00:00Z",
    expires_at: null,
    ...overrides,
  };
}

function renderList(rows: OpportunitySuggestionRow[]) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  // Nạp sẵn cache thay vì gọi mạng: bài kiểm này canh phần hiển thị, không
  // canh tầng API.
  client.setQueryData(["rb-today", ""], {
    summary: {
      total: rows.length,
      high_priority: 1,
      strong_product_fit: 1,
      call_now: 1,
      reactivation: 0,
      fresh_signals: 1,
    },
    results: rows,
  });
  client.setQueryData(["rb-work-profile"], {
    id: 1,
    domain: "rb",
    domain_label: "Bán lẻ",
    regions: [],
    focus_products: [],
    focus_job_families: [],
    target_segments: [],
    daily_capacity: 20,
    preferred_channels: [],
    notes: "",
    active: true,
    updated_at: "2026-08-29T08:00:00Z",
    observed: {
      regions: ["Hà Nội"],
      focus_products: ["mortgage"],
      sample_size: 5,
      confident: true,
    },
  });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <TodaysOpportunities />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("Cơ hội hôm nay", () => {
  it("thẻ nói rõ ai, vì sao bây giờ và nên làm gì", () => {
    renderList([suggestion()]);
    expect(screen.getByText("Nguyễn An")).toBeInTheDocument();
    expect(screen.getByText("VÌ SAO BÂY GIỜ")).toBeInTheDocument();
    expect(screen.getByText("Khách nhắc tới: mua nhà")).toBeInTheDocument();
    expect(screen.getByText("Gọi ngay")).toBeInTheDocument();
  });

  it("hiện cả điểm gốc khi đã cá nhân hoá", () => {
    // Điểm cá nhân hoá là của riêng người đang xem; điểm gốc mới là thứ so
    // sánh được giữa các RM. Giấu điểm gốc đi thì con số mất nghĩa.
    renderList([suggestion()]);
    expect(screen.getByText("79")).toBeInTheDocument();
    expect(screen.getByText("gốc 71")).toBeInTheDocument();
  });

  it("không hiện điểm gốc khi chưa cá nhân hoá", () => {
    renderList([suggestion({ personalized_score: 71.2 })]);
    expect(screen.queryByText(/gốc/)).not.toBeInTheDocument();
  });

  it("đánh dấu rõ thẻ nằm trong suất khám phá", () => {
    renderList([suggestion({ is_discovery: true, territory: "out" })]);
    expect(
      screen.getByText(/Ngoài vùng bạn phụ trách/),
    ).toBeInTheDocument();
  });

  it("gợi ý chuyển giao khi khách ngoài địa bàn", () => {
    renderList([
      suggestion({
        territory: "out",
        handoff_to: { user_id: 9, name: "RM Đà Nẵng", region: "Đà Nẵng" },
      }),
    ]);
    expect(screen.getByText("RM Đà Nẵng")).toBeInTheDocument();
  });

  it("bỏ qua mà không nêu lý do thì bị chặn", () => {
    // Cùng nguyên tắc với đóng cơ hội: một đề xuất bị bỏ im lặng sẽ được sinh
    // lại y hệt vào tháng sau.
    renderList([suggestion()]);
    fireEvent.click(screen.getByRole("button", { name: "Bỏ qua" }));
    fireEvent.click(screen.getByRole("button", { name: "Xác nhận bỏ qua" }));
    expect(screen.getByText(/Cho biết lý do bỏ qua/)).toBeInTheDocument();
  });

  it("xem được điểm từng chiều khi cần phản bác", () => {
    renderList([suggestion()]);
    fireEvent.click(screen.getByRole("button", { name: "Xem điểm" }));
    expect(screen.getByText("Rõ nhu cầu")).toBeInTheDocument();
    expect(screen.getByText("Đúng thời điểm")).toBeInTheDocument();
    expect(
      screen.getByText(/không phải do AI sinh ra/),
    ).toBeInTheDocument();
  });

  it("danh sách trống thì chỉ đường thay vì bỏ mặc", () => {
    renderList([]);
    expect(screen.getByText(/Social Radar/)).toBeInTheDocument();
  });

  it("gợi ý điền sẵn khai báo từ việc RM đã làm", () => {
    // Rủi ro lớn nhất của form khai báo là không ai điền.
    renderList([suggestion()]);
    fireEvent.click(
      screen.getByRole("button", { name: /Địa bàn & trọng tâm/ }),
    );
    expect(screen.getByText(/hệ thống thấy bạn/)).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Điền giúp tôi" }),
    ).toBeInTheDocument();
  });

  it("nói rõ ghi chú tự do không đổi thứ hạng", () => {
    renderList([suggestion()]);
    fireEvent.click(
      screen.getByRole("button", { name: /Địa bàn & trọng tâm/ }),
    );
    expect(
      screen.getByText(/không làm thay đổi điểm số hay/),
    ).toBeInTheDocument();
  });
});
