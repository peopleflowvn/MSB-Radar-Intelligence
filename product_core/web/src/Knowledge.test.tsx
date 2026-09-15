import "@testing-library/jest-dom/vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import Knowledge from "./Knowledge";
import { api, KnowledgeDocumentDetail, KnowledgeDocumentRow, KnowledgeListResponse } from "./api";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

function row(overrides: Partial<KnowledgeDocumentRow> = {}): KnowledgeDocumentRow {
  return {
    id: 1,
    title: "Quy trình nghỉ phép",
    category: "hr_policy",
    category_label: "Chính sách nhân sự",
    filename: "chinh-sach.txt",
    mime_type: "text/plain",
    file_size: 42,
    parse_status: "done",
    parse_status_label: "Đã xử lý",
    is_active: true,
    uploaded_by_name: "Admin",
    text_length: 120,
    created_at: "2026-09-15T00:00:00Z",
    updated_at: "2026-09-15T00:00:00Z",
    ...overrides,
  };
}

function renderPage(list: KnowledgeListResponse) {
  vi.spyOn(api, "knowledgeList").mockResolvedValue(list);
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <Knowledge />
    </QueryClientProvider>,
  );
}

describe("Tri thức nội bộ", () => {
  it("hiện danh sách tài liệu đã có", async () => {
    renderPage({
      results: [row()],
      categories: [{ value: "hr_policy", label: "Chính sách nhân sự" }],
    });
    expect(await screen.findByText("Quy trình nghỉ phép")).toBeInTheDocument();
    expect(screen.getByText("Đã xử lý")).toBeInTheDocument();
  });

  it("hiện thông báo trống khi chưa có tài liệu", async () => {
    renderPage({ results: [], categories: [] });
    expect(await screen.findByText(/Chưa có tài liệu nào/)).toBeInTheDocument();
  });

  it("mở panel tạo mới và tải file lên gọi đúng API", async () => {
    renderPage({ results: [], categories: [] });
    fireEvent.click(await screen.findByRole("button", { name: /Thêm tài liệu/ }));

    const uploadSpy = vi.spyOn(api, "knowledgeUpload").mockResolvedValue({
      ...row(), parsed_text: "noi dung",
    } as KnowledgeDocumentDetail);

    const titleInput = screen.getByPlaceholderText(/Quy trình nghỉ phép 2026/);
    fireEvent.change(titleInput, { target: { value: "Chính sách mới" } });

    const file = new File(["noi dung"], "chinh-sach.txt", { type: "text/plain" });
    const fileInput = document.querySelector('input[type="file"]') as HTMLInputElement;
    fireEvent.change(fileInput, { target: { files: [file] } });

    fireEvent.click(screen.getByRole("button", { name: "Lưu tài liệu" }));

    await waitFor(() => expect(uploadSpy).toHaveBeenCalledTimes(1));
    const [uploadedFile, fields] = uploadSpy.mock.calls[0];
    expect(uploadedFile.name).toBe("chinh-sach.txt");
    expect(fields.title).toBe("Chính sách mới");
  });

  it("chuyển sang nhập tay thì gọi knowledgeCreate với nội dung đã gõ", async () => {
    renderPage({ results: [], categories: [] });
    fireEvent.click(await screen.findByRole("button", { name: /Thêm tài liệu/ }));
    fireEvent.click(screen.getByRole("button", { name: /Nhập nội dung/ }));

    const createSpy = vi.spyOn(api, "knowledgeCreate").mockResolvedValue({
      ...row(), parsed_text: "noi dung nhap tay",
    } as KnowledgeDocumentDetail);

    fireEvent.change(screen.getByPlaceholderText(/Quy trình nghỉ phép 2026/), {
      target: { value: "Tieu de" },
    });
    fireEvent.change(screen.getByPlaceholderText(/Dán hoặc gõ nội dung/), {
      target: { value: "noi dung nhap tay" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Lưu tài liệu" }));

    await waitFor(() => expect(createSpy).toHaveBeenCalledWith(
      expect.objectContaining({ title: "Tieu de", parsed_text: "noi dung nhap tay" }),
    ));
  });

  it("bấm huy hiệu Đang bật/Đã tắt gọi knowledgeUpdate với is_active đảo ngược", async () => {
    renderPage({
      results: [row({ is_active: true })],
      categories: [{ value: "hr_policy", label: "Chính sách nhân sự" }],
    });
    const updateSpy = vi.spyOn(api, "knowledgeUpdate").mockResolvedValue(
      { ...row(), is_active: false, parsed_text: "" } as KnowledgeDocumentDetail,
    );
    fireEvent.click(await screen.findByRole("button", { name: "Đang bật" }));
    await waitFor(() => expect(updateSpy).toHaveBeenCalledWith(1, { is_active: false }));
  });

  it("xoá đòi xác nhận rồi mới gọi knowledgeDelete", async () => {
    renderPage({
      results: [row()],
      categories: [{ value: "hr_policy", label: "Chính sách nhân sự" }],
    });
    const deleteSpy = vi.spyOn(api, "knowledgeDelete").mockResolvedValue({ deleted: true });
    vi.spyOn(window, "confirm").mockReturnValue(true);

    fireEvent.click(await screen.findByRole("button", { name: "Xoá" }));
    await waitFor(() => expect(deleteSpy).toHaveBeenCalledWith(1));
  });

  it("không xoá khi người dùng huỷ xác nhận", async () => {
    renderPage({
      results: [row()],
      categories: [{ value: "hr_policy", label: "Chính sách nhân sự" }],
    });
    const deleteSpy = vi.spyOn(api, "knowledgeDelete").mockResolvedValue({ deleted: true });
    vi.spyOn(window, "confirm").mockReturnValue(false);

    fireEvent.click(await screen.findByRole("button", { name: "Xoá" }));
    expect(deleteSpy).not.toHaveBeenCalled();
  });

  it("lọc theo danh mục gọi knowledgeList với danh mục đã chọn", async () => {
    const listSpy = vi.spyOn(api, "knowledgeList").mockResolvedValue({
      results: [row()],
      categories: [{ value: "hr_policy", label: "Chính sách nhân sự" }],
    });
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    render(
      <QueryClientProvider client={client}>
        <Knowledge />
      </QueryClientProvider>,
    );
    fireEvent.click(await screen.findByRole("button", { name: "Chính sách nhân sự" }));
    await waitFor(() => expect(listSpy).toHaveBeenCalledWith("hr_policy"));
  });

  it("hiện cảnh báo khi tải file lên nhưng trích thất bại, không tự đóng panel", async () => {
    renderPage({ results: [], categories: [] });
    fireEvent.click(await screen.findByRole("button", { name: /Thêm tài liệu/ }));
    vi.spyOn(api, "knowledgeUpload").mockResolvedValue({
      ...row(), parsed_text: "", parse_status: "failed",
      warning: "Tệp không có nội dung chữ đọc được.",
    } as KnowledgeDocumentDetail & { warning: string });

    fireEvent.change(screen.getByPlaceholderText(/Quy trình nghỉ phép 2026/), {
      target: { value: "Tieu de" },
    });
    const file = new File([new Uint8Array([0, 1, 2])], "anh.bin");
    const fileInput = document.querySelector('input[type="file"]') as HTMLInputElement;
    fireEvent.change(fileInput, { target: { files: [file] } });
    fireEvent.click(screen.getByRole("button", { name: "Lưu tài liệu" }));

    expect(await screen.findByText(/Tệp không có nội dung chữ đọc được/)).toBeInTheDocument();
    // Panel vẫn mở — người dùng cần thấy cảnh báo và có thể sửa lại.
    expect(screen.getByRole("button", { name: "Lưu tài liệu" })).toBeInTheDocument();
  });
});
