import "@testing-library/jest-dom/vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { CustomerTaskCard } from "./RB";
import { RBCustomerTaskRow } from "./api";

const row: RBCustomerTaskRow = {
  kind: "work",
  key: "customer:7",
  person_id: 7,
  display_name: "Nguyễn An",
  headline: "Chủ doanh nghiệp",
  primary_phone: "0901234567",
  primary_email: "an@example.com",
  due_at: "2026-08-22T08:00:00Z",
  is_overdue: true,
  relationship_due: true,
  relationship: {
    id: 2,
    state: "interested",
    owner: "RM A",
    owner_id: 3,
    interest_level: 4,
    next_action: "Gọi xác nhận",
    next_action_at: "2026-08-22T08:00:00Z",
    do_not_contact: false,
  },
  opportunity: {
    id: 11,
    person: 7,
    display_name: "Nguyễn An",
    primary_phone: "0901234567",
    primary_email: "an@example.com",
    product: "mortgage",
    product_label: "Vay mua nhà",
    need: "Cần vay mua căn hộ",
    confidence: 0.8,
    evidence: {},
    suggested_action: "",
    status: "accepted",
    status_label: "Đang xử lý",
    stage_color: "#2563eb",
    sla_due_at: null,
    is_overdue: false,
    assigned_to: 3,
    assigned_to_name: "RM A",
    priority: "high",
    next_action_at: null,
    note: "Ghi chú nội bộ",
    status_events: [],
    close_reason: "",
    outreach_draft: "",
    outreach_sent_at: null,
    other_active_owners: ["RM B"],
    stage_entered_at: "2026-08-21T08:00:00Z",
    created_at: "2026-08-21T08:00:00Z",
  },
  other_opportunities: [{
    id: 12,
    person: 7,
    display_name: "Nguyễn An",
    primary_phone: "0901234567",
    primary_email: "an@example.com",
    product: "credit_card",
    product_label: "Thẻ tín dụng",
    need: "",
    confidence: 0.6,
    evidence: {},
    suggested_action: "",
    status: "new",
    status_label: "Mới",
    stage_color: "#64748b",
    sla_due_at: null,
    is_overdue: false,
    assigned_to: 3,
    assigned_to_name: "RM A",
    priority: "normal",
    next_action_at: null,
    note: "",
    status_events: [],
    close_reason: "",
    outreach_draft: "",
    outreach_sent_at: null,
    other_active_owners: [],
    stage_entered_at: "2026-08-21T08:00:00Z",
    created_at: "2026-08-21T08:00:00Z",
  }],
};

describe("Customer task card", () => {
  it("gom nhu cầu và giấu trường CRM cho tới khi RM chọn cập nhật", () => {
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    render(
      <QueryClientProvider client={client}>
        <MemoryRouter>
          <CustomerTaskCard
            row={row}
            owners={[]}
            stages={[]}
            canManage={false}
            selected={false}
            onSelect={() => undefined}
          />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    expect(screen.getByText(/Vay mua nhà/)).toBeInTheDocument();
    expect(screen.getByText(/Thẻ tín dụng/)).toBeInTheDocument();
    expect(screen.getByText(/RM khác cũng đang xử lý/)).toBeInTheDocument();
    expect(screen.queryByPlaceholderText("Ghi chú xử lý")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Cập nhật/ }));
    expect(screen.getByPlaceholderText("Ghi chú tiến độ tiếp cận khách hàng...")).toBeInTheDocument();
    expect(screen.getByText("1 nhu cầu khác của khách")).toBeInTheDocument();
  });
});
