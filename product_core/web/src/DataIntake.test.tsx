import "@testing-library/jest-dom/vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import DataIntake from "./DataIntake";
import { api, IntakeBatch, IntakeRow } from "./api";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

function mockRow(overrides: Partial<IntakeRow> = {}): IntakeRow {
  return {
    id: 101,
    row_number: 2,
    raw: { fullname: "Nguyễn Văn A", email: "a.nguyen@example.com" },
    fields: {
      fullname: "Nguyễn Văn A",
      email: "a.nguyen@example.com",
      phone: "0901234567",
      position: "Chuyên viên Phân tích",
      skills: "Python, SQL",
    },
    entity_key: "intake|su-kien-2026|a.nguyen@example.com",
    validation_status: "valid",
    errors: {},
    matched_person_id: null,
    matched_person_name: "",
    source_record_id: null,
    person_id: null,
    cv_filename: "nguyen_van_a.pdf",
    cv_sha256: "abc123sha",
    ai_extracted: true,
    ...overrides,
  };
}

function mockBatch(overrides: Partial<IntakeBatch> = {}): IntakeBatch {
  return {
    id: 1,
    kind: "excel",
    source_label: "Sự kiện Tech 2026",
    original_filename: "danh_sach_ung_vien.xlsx",
    status: "draft",
    row_count: 3,
    valid_count: 2,
    duplicate_count: 1,
    invalid_count: 0,
    committed_count: 0,
    error_count: 0,
    created_by_name: "Admin Tuyển Dụng",
    created_at: "2026-08-30T10:00:00Z",
    updated_at: "2026-08-30T10:00:00Z",
    rows: [
      mockRow({ id: 101, row_number: 2, validation_status: "valid" }),
      mockRow({
        id: 102,
        row_number: 3,
        fields: { fullname: "Trần Thị B", email: "b.tran@example.com", phone: "0912345678", position: "Dev", skills: "React" },
        validation_status: "duplicate",
        matched_person_id: 42,
        matched_person_name: "Trần Thị B",
        errors: { duplicate: "Đã có người này trong hệ thống." },
      }),
      mockRow({
        id: 103,
        row_number: 4,
        fields: { fullname: "Lê Văn C", email: "", phone: "", position: "Tester", skills: "" },
        validation_status: "invalid",
        errors: { identity: "Cần ít nhất Email, Số điện thoại hoặc LinkedIn để định danh." },
      }),
    ],
    ...overrides,
  };
}

function renderIntake(batches: IntakeBatch[] = []) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  client.setQueryData(["intake-batches"], { results: batches });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <DataIntake />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("DataIntake Component (Tab Nhập liệu)", () => {
  it("hiển thị giao diện khởi tạo nguồn và danh sách lô gần đây khi chưa mở lô", () => {
    const batch = mockBatch();
    renderIntake([batch]);

    expect(screen.getByText(/Nhập liệu Ứng viên & Bàn dựng dữ liệu/)).toBeInTheDocument();
    expect(screen.getByText("Từ bảng tính Excel / CSV")).toBeInTheDocument();
    expect(screen.getByText("Hàng loạt CV (AI Bóc tách)")).toBeInTheDocument();
    expect(screen.getByText("Tải file Excel mẫu (.xlsx)")).toBeInTheDocument();
    expect(screen.getByText("Các lô nhập liệu gần đây (1)")).toBeInTheDocument();
    expect(screen.getByText("Sự kiện Tech 2026")).toBeInTheDocument();
  });

  it("cho phép chuyển đổi giữa chế độ Excel và Hàng loạt CV", () => {
    renderIntake([]);

    const cvModeBtn = screen.getByText("Hàng loạt CV (AI Bóc tách)");
    fireEvent.click(cvModeBtn);

    expect(screen.getByText(/AI tự động trích xuất Họ tên, Email/)).toBeInTheDocument();
  });

  it("mở lô nháp hiển thị đầy đủ KPI ribbon, bàn dựng và bộ lọc trạng thái", async () => {
    const batch = mockBatch();
    vi.spyOn(api, "intakeBatch").mockResolvedValue(batch);

    renderIntake([batch]);

    const openBtn = screen.getByText("Tiếp tục xử lý");
    fireEvent.click(openBtn);

    await waitFor(() => {
      expect(screen.getByText("Lô #1 · Bảng tính Excel/CSV")).toBeInTheDocument();
    });

    expect(screen.getByText("Tổng ứng viên")).toBeInTheDocument();
    expect(screen.getByText("Hợp lệ (Mới)")).toBeInTheDocument();
    expect(screen.getAllByText(/Trùng lặp/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/Lỗi định danh/).length).toBeGreaterThan(0);

    // Row 1 & Row 2
    expect(screen.getByDisplayValue("Nguyễn Văn A")).toBeInTheDocument();
    expect(screen.getByDisplayValue("Trần Thị B")).toBeInTheDocument();
  });

  it("lọc theo chip trạng thái và tìm kiếm tức thì", async () => {
    const batch = mockBatch();
    vi.spyOn(api, "intakeBatch").mockResolvedValue(batch);

    renderIntake([batch]);
    fireEvent.click(screen.getByText("Tiếp tục xử lý"));

    await waitFor(() => {
      expect(screen.getByText("Lô #1 · Bảng tính Excel/CSV")).toBeInTheDocument();
    });

    // Lọc theo chip "Hợp lệ"
    const validChip = screen.getByRole("button", { name: /Hợp lệ/ });
    fireEvent.click(validChip);

    expect(screen.getByDisplayValue("Nguyễn Văn A")).toBeInTheDocument();
    expect(screen.queryByDisplayValue("Trần Thị B")).not.toBeInTheDocument();

    // Reset về Tất cả
    fireEvent.click(screen.getByRole("button", { name: /Tất cả/ }));
    expect(screen.getByDisplayValue("Trần Thị B")).toBeInTheDocument();

    // Tìm kiếm
    const searchInput = screen.getByPlaceholderText(/Tìm theo tên, email/);
    fireEvent.change(searchInput, { target: { value: "Nguyễn" } });
    expect(screen.getByDisplayValue("Nguyễn Văn A")).toBeInTheDocument();
    expect(screen.queryByDisplayValue("Trần Thị B")).not.toBeInTheDocument();
  });

  it("mở Drawer xem chi tiết dòng và thông tin trùng khớp với Person360", async () => {
    const batch = mockBatch();
    vi.spyOn(api, "intakeBatch").mockResolvedValue(batch);

    renderIntake([batch]);
    fireEvent.click(screen.getByText("Tiếp tục xử lý"));

    await waitFor(() => {
      expect(screen.getByText("Lô #1 · Bảng tính Excel/CSV")).toBeInTheDocument();
    });

    // Bấm nút xem chi tiết ở dòng 2 (Trần Thị B - Trùng lặp)
    const eyeButtons = screen.getAllByTitle("Xem chi tiết dòng");
    fireEvent.click(eyeButtons[1]);

    expect(screen.getByText("Chi tiết dòng #3")).toBeInTheDocument();
    expect(screen.getByText(/Khớp với hồ sơ đã có trong Radar Core/)).toBeInTheDocument();
    expect(screen.getByText("Mở hồ sơ Person360 trong tab mới")).toBeInTheDocument();

    // Đóng drawer
    fireEvent.click(screen.getByText("Đóng"));
    expect(screen.queryByText("Chi tiết dòng #3")).not.toBeInTheDocument();
  });

  it("thực hiện commit ghi dữ liệu vào Radar Core", async () => {
    const batch = mockBatch();
    const doneBatch = mockBatch({
      status: "done",
      committed_count: 2,
      commit_result: { committed: 2 },
    });

    vi.spyOn(api, "intakeBatch").mockResolvedValue(batch);
    vi.spyOn(api, "intakeCommit").mockResolvedValue(doneBatch);

    renderIntake([batch]);
    fireEvent.click(screen.getByText("Tiếp tục xử lý"));

    await waitFor(() => {
      expect(screen.getByText("Lô #1 · Bảng tính Excel/CSV")).toBeInTheDocument();
    });

    const commitBtn = screen.getByText(/Ghi 2 ứng viên vào hệ thống/);
    fireEvent.click(commitBtn);

    await waitFor(() => {
      expect(api.intakeCommit).toHaveBeenCalledWith(1, "skip");
    });
  });
});
