import "@testing-library/jest-dom/vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { EdgeConnections } from "./Data";
import { api, EdgeAdminRow } from "./api";

/**
 * Trang tự phục vụ tạo Edge + cấp/thu hồi khoá — nền tảng để triển khai cho
 * một doanh nghiệp khác mà không đụng vào code.
 *
 * Hai điều bài này canh kỹ nhất:
 * 1. Người xem thường (không quản lý) KHÔNG thấy nút tạo/cấp/thu hồi — chỉ
 *    quản trị viên mới sinh được thông tin xác thực.
 * 2. Khoá thô chỉ hiện đúng một lần, ngay sau khi cấp.
 */

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

function edgeRow(overrides: Partial<EdgeAdminRow> = {}): EdgeAdminRow {
  return {
    id: 1,
    label: "Máy phòng Tuyển dụng",
    edge_id: "abc-123",
    hostname: "TUYENDUNG-PC01",
    app_version: "3.0.0",
    is_active: true,
    registered_at: "2026-08-01T00:00:00Z",
    last_seen_at: "2026-08-30T00:00:00Z",
    created_at: "2026-08-01T00:00:00Z",
    api_keys: [],
    record_count: 42,
    ...overrides,
  };
}

function renderPage(rows: EdgeAdminRow[], canManage: boolean) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  client.setQueryData(["edge-admin-list"], { results: rows });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <EdgeConnections canManage={canManage} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("Kết nối Edge", () => {
  it("người xem thường không thấy nút tạo Edge", () => {
    renderPage([edgeRow()], false);
    expect(
      screen.queryByPlaceholderText(/Tên gọi Edge mới/),
    ).not.toBeInTheDocument();
  });

  it("người xem thường không thấy nút cấp/thu hồi khoá", () => {
    renderPage(
      [edgeRow({ api_keys: [{ id: 9, name: "", prefix: "abcd1234", created_at: "2026-08-01T00:00:00Z", last_used_at: null, revoked_at: null, is_active: true }] })],
      false,
    );
    expect(screen.queryByText("+ Cấp khoá mới")).not.toBeInTheDocument();
    expect(screen.queryByText("Thu hồi")).not.toBeInTheDocument();
    expect(screen.queryByText("Tắt")).not.toBeInTheDocument();
  });

  it("quản trị viên thấy đủ nút thao tác", () => {
    renderPage([edgeRow()], true);
    expect(screen.getByPlaceholderText(/Tên gọi Edge mới/)).toBeInTheDocument();
    expect(screen.getByText("+ Cấp khoá mới")).toBeInTheDocument();
    expect(screen.getByText("Tắt")).toBeInTheDocument();
  });

  it("tạo Edge mới", async () => {
    vi.spyOn(api, "edgeAdminCreate").mockResolvedValue(edgeRow({ id: 2, label: "Máy mới" }));
    renderPage([], true);

    fireEvent.change(screen.getByPlaceholderText(/Tên gọi Edge mới/), {
      target: { value: "Máy mới" },
    });
    fireEvent.click(screen.getByText("Tạo Edge"));

    await waitFor(() => expect(api.edgeAdminCreate).toHaveBeenCalledWith("Máy mới"));
  });

  it("cấp khoá xong hiện khoá thô đúng một lần và có nút đóng lại", async () => {
    vi.spyOn(api, "edgeAdminIssueKey").mockResolvedValue({
      id: 5, name: "", prefix: "xyz12345",
      created_at: "2026-08-30T00:00:00Z", last_used_at: null, revoked_at: null,
      is_active: true, api_key: "khoa-tho-day-du-chi-hien-mot-lan",
    });
    renderPage([edgeRow()], true);

    fireEvent.click(screen.getByText("+ Cấp khoá mới"));
    fireEvent.click(screen.getByText("Xác nhận cấp khoá"));

    await waitFor(() =>
      expect(screen.getByText("khoa-tho-day-du-chi-hien-mot-lan")).toBeInTheDocument(),
    );
    expect(screen.getByText("Chép khoá ngay — sẽ không hiện lại")).toBeInTheDocument();

    fireEvent.click(screen.getByText("Đã chép, đóng lại"));
    expect(
      screen.queryByText("khoa-tho-day-du-chi-hien-mot-lan"),
    ).not.toBeInTheDocument();
  });

  it("thu hồi khoá gọi đúng API", async () => {
    vi.spyOn(api, "edgeAdminRevokeKey").mockResolvedValue({
      id: 9, name: "", prefix: "abcd1234", created_at: "2026-08-01T00:00:00Z",
      last_used_at: null, revoked_at: "2026-08-30T00:00:00Z", is_active: false,
    });
    renderPage(
      [edgeRow({ api_keys: [{ id: 9, name: "Đợt 1", prefix: "abcd1234", created_at: "2026-08-01T00:00:00Z", last_used_at: null, revoked_at: null, is_active: true }] })],
      true,
    );

    fireEvent.click(screen.getByText("Thu hồi"));
    await waitFor(() => expect(api.edgeAdminRevokeKey).toHaveBeenCalledWith(9));
  });

  it("khoá đã thu hồi không còn nút Thu hồi", () => {
    renderPage(
      [edgeRow({ api_keys: [{ id: 9, name: "", prefix: "abcd1234", created_at: "2026-08-01T00:00:00Z", last_used_at: null, revoked_at: "2026-08-02T00:00:00Z", is_active: false }] })],
      true,
    );
    expect(screen.getByText("đã thu hồi")).toBeInTheDocument();
    expect(screen.queryByText("Thu hồi")).not.toBeInTheDocument();
  });

  it("chưa có Edge nào thì chỉ đường theo đúng vai trò", () => {
    renderPage([], false);
    expect(screen.getByText(/Nhờ quản trị viên tạo Edge/)).toBeInTheDocument();
  });

  it("người xem thường không thấy nút sửa/xoá Edge", () => {
    renderPage([edgeRow()], false);
    expect(screen.queryByText("✏️ Sửa tên")).not.toBeInTheDocument();
    expect(screen.queryByText("🗑️ Xóa Edge")).not.toBeInTheDocument();
  });

  it("quản trị viên thấy nút sửa tên và xoá Edge", () => {
    renderPage([edgeRow()], true);
    expect(screen.getByText("✏️ Sửa tên")).toBeInTheDocument();
    expect(screen.getByText("🗑️ Xóa Edge")).toBeInTheDocument();
  });

  it("đổi tên Edge gọi đúng API", async () => {
    const updateEdge = vi.spyOn(api, "edgeAdminUpdate").mockResolvedValue(
      edgeRow({ label: "Máy đổi tên" }),
    );
    renderPage([edgeRow()], true);

    fireEvent.click(screen.getByText("✏️ Sửa tên"));
    fireEvent.change(screen.getByPlaceholderText(/Tên gọi mới của Edge/), {
      target: { value: "Máy đổi tên" },
    });
    fireEvent.click(screen.getByText("Lưu tên mới"));

    await waitFor(() =>
      expect(updateEdge).toHaveBeenCalledWith(1, { label: "Máy đổi tên" }),
    );
  });


  it("đồng ý xoá thì gọi API xoá Edge", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    const deleteEdge = vi.spyOn(api, "edgeAdminDelete");
    deleteEdge.mockResolvedValue({ deleted: true });
    renderPage([edgeRow({ record_count: 0 })], true);

    fireEvent.click(screen.getByText("🗑️ Xóa Edge"));
    await waitFor(() => {
      expect(deleteEdge).toHaveBeenCalledWith(1);
    });
  });

  it("không đồng ý thì không xoá Edge", () => {
    vi.spyOn(window, "confirm").mockReturnValue(false);
    const del = vi.spyOn(api, "edgeAdminDelete");
    del.mockResolvedValue({ deleted: true });
    renderPage([edgeRow({ record_count: 0 })], true);

    fireEvent.click(screen.getByText("🗑️ Xóa Edge"));
    expect(del).not.toHaveBeenCalled();
  });

  it("Edge đã nạp dữ liệu thì nút xoá bị khoá — bắt buộc dùng Tắt thay vì xoá", () => {
    renderPage([edgeRow({ record_count: 3 })], true);
    expect(screen.getByText("🗑️ Xóa Edge")).toBeDisabled();
  });

  it("Edge chưa nạp dữ liệu thì được phép xoá", () => {
    renderPage([edgeRow({ record_count: 0 })], true);
    expect(screen.getByText("🗑️ Xóa Edge")).toBeEnabled();
  });
});
