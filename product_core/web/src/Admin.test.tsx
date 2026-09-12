import "@testing-library/jest-dom/vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { BulkCreatePanel } from "./Admin";
import { api } from "./api";

/**
 * Tạo tài khoản hàng loạt qua file .xlsx — bài này canh kỹ nhất:
 * 1. Link tải file mẫu trỏ đúng endpoint.
 * 2. Tải file lên gọi đúng API với đúng file.
 * 3. Mật khẩu tự sinh của dòng "created" hiện ra; dòng "rejected" hiện lý do.
 */

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

function renderPanel() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <BulkCreatePanel onDone={() => {}} />
    </QueryClientProvider>,
  );
}

describe("Tạo hàng loạt tài khoản", () => {
  it("link tải file mẫu trỏ đúng endpoint", () => {
    renderPanel();
    const link = screen.getByRole("link", { name: /Tải file mẫu/ }) as HTMLAnchorElement;
    expect(link.getAttribute("href")).toBe("/api/v1/auth/users/bulk-template/");
  });

  it("chọn file rồi tải lên gọi đúng API", async () => {
    vi.spyOn(api, "userBulkCreate").mockResolvedValue({
      created: 1,
      total: 1,
      results: [{ row: 2, username: "nguyenvana", status: "created", password: "khoa-tam-thoi" }],
    });
    renderPanel();

    const file = new File(["ban chinh la file .xlsx nhi phan, noi dung khong quan trong trong test nay"], "mau.xlsx", {
      type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    });
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    fireEvent.change(input, { target: { files: [file] } });

    fireEvent.click(screen.getByText(/Tải lên/));

    await waitFor(() => expect(api.userBulkCreate).toHaveBeenCalledWith(file));
    expect(await screen.findByText("khoa-tam-thoi")).toBeInTheDocument();
  });

  it("dòng bị từ chối hiện lý do, không hiện mật khẩu", async () => {
    vi.spyOn(api, "userBulkCreate").mockResolvedValue({
      created: 0,
      total: 1,
      results: [
        { row: 2, username: "trung_ten", status: "rejected", detail: "Tên đăng nhập đã tồn tại." },
      ],
    });
    renderPanel();

    const file = new File(["a"], "mau.xlsx", {
      type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    });
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    fireEvent.change(input, { target: { files: [file] } });
    fireEvent.click(screen.getByText(/Tải lên/));

    expect(await screen.findByText("Tên đăng nhập đã tồn tại.")).toBeInTheDocument();
    expect(screen.getByText("bị từ chối")).toBeInTheDocument();
  });

  it("tải kết quả xuất đúng username/họ tên/mật khẩu của dòng đã tạo, bỏ dòng bị từ chối", async () => {
    vi.spyOn(api, "userBulkCreate").mockResolvedValue({
      created: 1,
      total: 2,
      results: [
        { row: 2, username: "trung_ten", status: "rejected", detail: "Tên đăng nhập đã tồn tại." },
        {
          row: 3,
          username: "nguyenvana",
          full_name: "Nguyễn Văn A",
          status: "created",
          password: "khoa-tam-thoi",
        },
      ],
    });

    let createdBlob: Blob | null = null;
    const originalCreateObjectURL = URL.createObjectURL;
    const originalRevokeObjectURL = URL.revokeObjectURL;
    URL.createObjectURL = vi.fn((blob: Blob) => {
      createdBlob = blob;
      return "blob:mock";
    });
    URL.revokeObjectURL = vi.fn();

    renderPanel();
    const file = new File(["a"], "mau.xlsx", {
      type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    });
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    fireEvent.change(input, { target: { files: [file] } });
    fireEvent.click(screen.getByText(/Tải lên/));
    await screen.findByText("khoa-tam-thoi");

    fireEvent.click(screen.getByText(/Tải kết quả/));

    expect(createdBlob).not.toBeNull();
    const content = await new Promise<string>((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(String(reader.result));
      reader.onerror = reject;
      reader.readAsText(createdBlob as unknown as Blob);
    });
    expect(content).toContain("nguyenvana");
    expect(content).toContain("Nguyễn Văn A");
    expect(content).toContain("khoa-tam-thoi");
    expect(content).not.toContain("trung_ten");

    URL.createObjectURL = originalCreateObjectURL;
    URL.revokeObjectURL = originalRevokeObjectURL;
  });
});
