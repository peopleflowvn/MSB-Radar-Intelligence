import "@testing-library/jest-dom/vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api, IdentityConflict, IntelRunsDashboard } from "./api";
import IntelPanel from "./IntelPanel";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

function renderPanel() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <IntelPanel />
    </QueryClientProvider>
  );
}

const baseDashboard: IntelRunsDashboard = {
  totals: {
    runs: 10, by_status: { done: 10 }, open_reviews: 2, proposed_aliases: 1,
    open_identity_conflicts: 0, accepted_facts: 20,
  },
  alerts: { reviews: false, aliases: false, conflicts: false },
  coverage_last_500: { edge: 5, profile: 2, cv_text: 1, ai: 1, ai_calls: 1, edge_reuse_ratio: 0.8 },
  recent: [],
};

describe("IntelPanel — dashboard alerts", () => {
  it("ẩn banner khi chưa vượt ngưỡng, hiện khi vượt và nhảy đúng tab", async () => {
    vi.spyOn(api, "intelRunsDashboard").mockResolvedValue(baseDashboard);
    renderPanel();
    await screen.findByText("📊 Tổng quan trích xuất");
    expect(screen.queryByText(/Hàng chờ đang phình to/)).not.toBeInTheDocument();
    cleanup();

    vi.spyOn(api, "intelRunsDashboard").mockResolvedValue({
      ...baseDashboard,
      totals: { ...baseDashboard.totals, open_reviews: 99 },
      alerts: { reviews: true, aliases: false, conflicts: false },
    });
    vi.spyOn(api, "intelReviewQueue").mockResolvedValue({ counts: {}, results: [] });
    renderPanel();
    const banner = await screen.findByText(/Hàng chờ đang phình to/);
    expect(banner).toBeInTheDocument();
    fireEvent.click(screen.getByText(/99 mục chờ duyệt/));
    expect(await screen.findByText("Không có mục nào chờ duyệt.")).toBeInTheDocument();
  });
});

describe("IntelPanel — Xung đột định danh", () => {
  const conflict: IdentityConflict = {
    id: 5,
    evidence: { identities: [{ kind: "phone", value: "0900000000" }], people: [] },
    source_record_id: "",
    created_at: "2026-08-01T00:00:00Z",
    people: [
      { id: 1, display_name: "Chị A", primary_email: "a@x.com", primary_phone: "0911111111", headline: "" },
      { id: 2, display_name: "Anh B", primary_email: "", primary_phone: "0900000000", headline: "" },
    ],
  };

  it("hiện thẻ xung đột và gọi đúng API khi Gộp / Bỏ qua, không có UI chọn nhiều", async () => {
    vi.spyOn(api, "intelRunsDashboard").mockResolvedValue(baseDashboard);
    vi.spyOn(api, "intelIdentityConflicts").mockResolvedValue({ results: [conflict] });
    const resolveSpy = vi.spyOn(api, "intelIdentityConflictResolve").mockResolvedValue({ ok: true, status: "merged" });

    renderPanel();
    fireEvent.click(screen.getByText("⚠️ Xung đột định danh"));
    expect(await screen.findByText(/Chị A/)).toBeInTheDocument();
    expect(screen.getByText(/Anh B/)).toBeInTheDocument();
    expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();

    fireEvent.click(screen.getByText("Gộp làm một người"));
    await waitFor(() => expect(resolveSpy).toHaveBeenCalledWith(5, "merge"));
  });
});

describe("IntelPanel — Alias: tạo mã mới", () => {
  it("gọi intelAliasNewEntry với đúng code/label đã nhập", async () => {
    vi.spyOn(api, "intelRunsDashboard").mockResolvedValue(baseDashboard);
    vi.spyOn(api, "intelAliasQueue").mockResolvedValue({
      results: [{ id: 7, namespace: "job_title", alias_norm: "ke toan noi bo moi",
                 alias_raw: "Kế toán nội bộ mới", source: "radar_ai", created_by: "", created_at: "" }],
    });
    const newEntrySpy = vi.spyOn(api, "intelAliasNewEntry").mockResolvedValue(
      { ok: true, status: "accepted", entry_code: "ke-toan-noi-bo" });

    renderPanel();
    fireEvent.click(screen.getByText("🏷️ Alias chưa nhận diện"));
    await screen.findByText("ke toan noi bo moi");

    fireEvent.click(screen.getByText("+ Tạo mã mới"));
    fireEvent.change(screen.getByPlaceholderText("mã (vd vietcombank)"), { target: { value: "ke-toan-noi-bo" } });
    fireEvent.change(screen.getByPlaceholderText("nhãn hiển thị (vd Vietcombank)"), { target: { value: "Kế toán nội bộ" } });
    fireEvent.click(screen.getByText("Tạo & nối"));

    await waitFor(() => expect(newEntrySpy).toHaveBeenCalledWith(7, "ke-toan-noi-bo", "Kế toán nội bộ"));
  });
});

describe("IntelPanel — duyệt hàng loạt", () => {
  it("chọn nhiều alias rồi Nối đã chọn gọi bulk API với đúng danh sách id", async () => {
    vi.spyOn(api, "intelRunsDashboard").mockResolvedValue(baseDashboard);
    vi.spyOn(api, "intelAliasQueue").mockResolvedValue({
      results: [
        { id: 1, namespace: "company", alias_norm: "vcb", alias_raw: "VCB", source: "", created_by: "", created_at: "" },
        { id: 2, namespace: "company", alias_norm: "vietcombank", alias_raw: "Vietcombank", source: "", created_by: "", created_at: "" },
      ],
    });
    const bulkSpy = vi.spyOn(api, "intelAliasBulkResolve").mockResolvedValue({ resolved: [1, 2], skipped: [] });

    renderPanel();
    fireEvent.click(screen.getByText("🏷️ Alias chưa nhận diện"));
    await screen.findByText("vcb");
    fireEvent.click(screen.getByText("Chọn tất cả"));

    fireEvent.change(screen.getByPlaceholderText("mã canonical chung"), { target: { value: "vietcombank" } });
    fireEvent.click(screen.getByText("Nối đã chọn vào mã này"));

    await waitFor(() => expect(bulkSpy).toHaveBeenCalledWith([1, 2], "accept", "vietcombank"));
  });

  it("chọn nhiều review item rồi Từ chối đã chọn gọi bulk API với đúng danh sách id", async () => {
    vi.spyOn(api, "intelRunsDashboard").mockResolvedValue(baseDashboard);
    vi.spyOn(api, "intelReviewQueue").mockResolvedValue({
      counts: {},
      results: [
        { id: 11, reason: "low_confidence", detail: "", person_id: 1, field: "city",
         fact: null, alias: null, created_at: "" },
        { id: 12, reason: "low_confidence", detail: "", person_id: 2, field: "city",
         fact: null, alias: null, created_at: "" },
      ],
    });
    const bulkSpy = vi.spyOn(api, "intelReviewBulkResolve").mockResolvedValue({ resolved: [11, 12], skipped: [] });

    renderPanel();
    fireEvent.click(screen.getByText("🔍 Hàng chờ duyệt"));
    await screen.findByText("Chọn tất cả");
    fireEvent.click(screen.getByText("Chọn tất cả"));
    fireEvent.click(screen.getByText("Từ chối đã chọn"));

    await waitFor(() => expect(bulkSpy).toHaveBeenCalledWith([11, 12], "reject"));
  });
});
