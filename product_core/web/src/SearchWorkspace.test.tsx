import "@testing-library/jest-dom/vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import SearchWorkspace from "./SearchWorkspace";
import { api, Session } from "./api";
import { CustomThemeProvider } from "./CustomThemeContext";
import { SearchStateProvider } from "./searchPersistence";

function session(overrides: Partial<Extract<Session, { authenticated: true }>>): Session {
  return {
    authenticated: true, id: 1, username: "u", full_name: "U", is_superuser: false,
    roles: [], role_labels: [], modules: [], ...overrides,
  };
}

beforeEach(() => {
  localStorage.clear();
  sessionStorage.clear();
  vi.spyOn(api, "conversations").mockResolvedValue({ results: [] });
  vi.spyOn(api, "talentFacets").mockResolvedValue({} as never);
  vi.spyOn(api, "filterHistory").mockResolvedValue({ results: [] } as never);
  vi.spyOn(api, "pools").mockResolvedValue([] as never);
  vi.spyOn(api, "savedViews").mockResolvedValue({ results: [] } as never);
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

function renderAt(url: string, me: Session) {
  vi.spyOn(api, "me").mockResolvedValue(me);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <CustomThemeProvider>
        <MemoryRouter initialEntries={[url]}>
          <SearchStateProvider>
            <SearchWorkspace />
          </SearchStateProvider>
        </MemoryRouter>
      </CustomThemeProvider>
    </QueryClientProvider>,
  );
}

describe("SearchWorkspace — quyền", () => {
  it("máy chủ báo không đọc được CV thì không hiện thanh chuyển góc nhìn", async () => {
    renderAt("/search", session({
      roles: ["rb_sales"], modules: ["talent", "rb"], can_read_cv: false,
    }));
    // Gợi ý mẫu của trợ lý Khách hàng — tức đang ở góc nhìn Khách hàng.
    expect(await screen.findByText("Vay mua nhà & An cư")).toBeInTheDocument();
    expect(screen.queryByText("Góc nhìn Tuyển dụng")).not.toBeInTheDocument();
  });

  it("chỉ có module rb thì ẩn hẳn tab Bộ lọc — hai endpoint của nó đòi module talent", async () => {
    renderAt("/search?tab=filter", session({ roles: ["rb_sales"], modules: ["rb"] }));
    // Gợi ý mẫu của trợ lý Khách hàng — tức đang ở góc nhìn Khách hàng.
    expect(await screen.findByText("Vay mua nhà & An cư")).toBeInTheDocument();
    expect(screen.queryByText("⚙️ Bộ lọc đa chiều")).not.toBeInTheDocument();
  });

  it("không có module nào thì báo chưa được cấp quyền", async () => {
    renderAt("/search", session({ modules: [] }));
    expect(await screen.findByText(/chưa được cấp quyền tra cứu/)).toBeInTheDocument();
  });
});

describe("SearchWorkspace — đổi góc nhìn trong bộ lọc", () => {
  it("xoá nhóm đang lọc và duyệt đúng cỡ trang của từng góc nhìn", async () => {
    // Bộ lọc đã chạy từ trước, đang lọc theo nhóm #5 của nghiệp vụ Tuyển dụng.
    localStorage.setItem("msb-radar-talent-filter-state-v1", JSON.stringify({
      draft: { pool: "5", order: "relevance" },
      applied: { pool: "5", order: "relevance" },
      hasSearched: true,
    }));
    const search = vi.spyOn(api, "talentSearch").mockResolvedValue({ count: 0, results: [] });

    renderAt("/search?tab=filter&perspective=recruiter", session({
      roles: ["admin"], modules: ["talent", "rb"], can_read_cv: true,
    }));
    await waitFor(() => expect(search).toHaveBeenCalled());
    expect(search).toHaveBeenLastCalledWith(expect.objectContaining({ pool: "5" }), 50, 0);

    fireEvent.click(await screen.findByText("Góc nhìn Khách hàng"));

    // Cùng id nhưng là một nhóm khác ở nghiệp vụ kia — phải bỏ, và trang 30.
    await waitFor(() =>
      expect(search).toHaveBeenLastCalledWith(expect.objectContaining({ pool: "" }), 30, 0));
  });
});

const CARD = {
  id: 7, display_name: "Nguyễn An", primary_email: "", primary_phone: "", headline: "Trưởng phòng",
  location: "Hà Nội", needs_review: false, talent: null, source_count: 1,
  active_worklists: [], updated_at: "2026-09-18T00:00:00Z",
};

describe("SearchFilterWorkspace — thao tác trên kết quả", () => {
  function prospectFilter(applied: Record<string, string>, draft: Record<string, string>) {
    localStorage.setItem("msb-radar-talent-filter-state-v1", JSON.stringify({
      draft, applied, hasSearched: true,
    }));
    vi.spyOn(api, "talentSearch").mockResolvedValue({ count: 1, results: [CARD] } as never);
    renderAt("/search?tab=filter&perspective=prospect", session({
      roles: ["rb_sales"], modules: ["talent", "rb"], can_read_cv: false,
    }));
  }

  it("tạo cơ hội theo sản phẩm của bộ lọc ĐÃ ÁP, không theo bản nháp đang gõ dở", async () => {
    const create = vi.spyOn(api, "rbOpportunityCreate").mockResolvedValue({} as never);
    prospectFilter({ product: "mortgage" }, { product: "fx" });

    fireEvent.click(await screen.findByText("⚡ Tạo cơ hội"));
    await waitFor(() => expect(create).toHaveBeenCalledTimes(1));
    expect(create.mock.calls[0][0]).toEqual(expect.objectContaining({ person_id: 7, product: "mortgage" }));
  });

  it("thao tác hàng loạt báo đúng số hỏng thay vì số đã chọn", async () => {
    vi.spyOn(api, "rbOpportunityCreate").mockRejectedValue(new Error("403"));
    prospectFilter({}, {});

    fireEvent.click(await screen.findByTitle("Chọn khách hàng này"));
    fireEvent.click(await screen.findByText("⚡ Tạo cơ hội hàng loạt"));
    expect(await screen.findByText(/Đã tạo 0 cơ hội.*1 hồ sơ không xử lý được/)).toBeInTheDocument();
  });
});
