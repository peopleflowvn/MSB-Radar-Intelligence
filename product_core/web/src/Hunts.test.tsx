import "@testing-library/jest-dom/vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { Candidate } from "./Hunts";
import { HuntCandidateRow } from "./api";

const row: HuntCandidateRow = {
  person_id: 7,
  display_name: "Nguyễn An",
  headline: "Data Engineer",
  primary_email: "an@example.com",
  primary_phone: "0901234567",
  state: "pending",
  state_label: "Mới trong danh sách",
  stage_color: "#64748b",
  sla_due_at: null,
  is_overdue: false,
  note: "",
  priority: "normal",
  next_action_at: null,
  assigned_to: null,
  assigned_to_name: "",
  status_events: [],
  return_reason: "",
  outreach_draft: "",
  outreach_sent_at: null,
  updated_at: "2026-08-22T10:00:00Z",
};

describe("Candidate work card", () => {
  it("hiện DNC, cảnh báo luồng khác và không cho soạn thư", () => {
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    render(
      <QueryClientProvider client={client}>
        <MemoryRouter>
          <Candidate
            hunt={{ id: 1, title: "Data Q3", message: "", status: "in_progress" }}
            row={row}
            owners={[]}
            stages={[]}
            relationship={{
              state: "do_not_contact",
              owner: "Recruiter A",
              owner_id: 2,
              interest_level: 0,
              next_action: "",
              next_action_at: null,
              do_not_contact: true,
            }}
            otherWorklists={[{
              hunt_id: 2,
              title: "Data Q4",
              state: "contacting",
              state_label: "Đang tiếp cận",
              assigned_to_name: "Recruiter B",
            }]}
          />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    expect(screen.getByText("🚫 Không liên hệ")).toBeInTheDocument();
    expect(screen.getByText(/Đồng thời trong 1 luồng khác/)).toBeInTheDocument();
    expect(screen.getByText(/Data Q4/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Soạn thư/ })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Nhận xử lý" })).toBeEnabled();
  });
});
