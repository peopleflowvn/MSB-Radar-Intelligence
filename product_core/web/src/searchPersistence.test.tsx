import "@testing-library/jest-dom/vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { SearchStateProvider, useSearchFilterState } from "./searchPersistence";

function FilterHarness() {
  const state = useSearchFilterState();
  return <div>
    <span data-testid="query">{state.applied.q || ""}</span>
    <span data-testid="page">{state.page}</span>
    <span data-testid="history">{state.history.length}</span>
    <button onClick={() => {
      const filters = { q: "Java", location: "Hà Nội", order: "relevance" };
      state.setDraft(filters);
      state.setApplied(filters);
      state.setHasSearched(true);
      state.setPage(2);
      state.setScrollY(640);
      state.rememberFilter(filters);
    }}>lọc</button>
  </div>;
}

// `SearchStateProvider` wraps children in `AiChatProvider`, which now reads
// the signed-in username via `useQuery` — needs a `QueryClientProvider`
// ancestor, same as every other test that renders it (see AiSearch.test.tsx).
function renderHarness() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <SearchStateProvider><FilterHarness /></SearchStateProvider>
    </QueryClientProvider>,
  );
}

describe("trạng thái bộ lọc Talent", () => {
  beforeEach(() => localStorage.clear());
  afterEach(cleanup);

  it("giữ bộ lọc, trang kết quả và lịch sử sau khi provider được dựng lại", async () => {
    const first = renderHarness();
    fireEvent.click(screen.getByRole("button", { name: "lọc" }));
    expect(screen.getByTestId("query")).toHaveTextContent("Java");
    expect(screen.getByTestId("page")).toHaveTextContent("2");
    expect(screen.getByTestId("history")).toHaveTextContent("1");
    await waitFor(() => expect(localStorage.getItem("msb-radar-talent-filter-state-v1")).toContain("Java"));

    first.unmount();
    renderHarness();
    expect(screen.getByTestId("query")).toHaveTextContent("Java");
    expect(screen.getByTestId("page")).toHaveTextContent("2");
    expect(screen.getByTestId("history")).toHaveTextContent("1");
  });
});

describe("phục hồi thẻ ứng viên từ snapshot DB", () => {
  it("trích xuất đúng danh sách people từ metadata.result_snapshot.items khi tải lại luồng chat", async () => {
    const { extractAnswerPeople } = await import("./searchPersistence");
    const metadata = {
      answer_engine: true,
      result_snapshot: {
        kind: "answer",
        count: 2,
        items: [
          { id: 892, name: "Hà My Cao", why: "Chuyên viên chính Quan hệ khách hàng" },
          { id: 1011, name: "Nguyễn Thị Thanh Thư", why: "Chuyên viên cao cấp" },
        ],
      },
      cv_citations: [
        { n: 1, person_id: 892, document_id: 539, name: "Hà My Cao", snippet: "VPBank" },
      ],
    };

    const people = extractAnswerPeople(metadata);
    expect(people).toHaveLength(2);
    expect(people[0]).toMatchObject({
      person_id: 892,
      name: "Hà My Cao",
      why: "Chuyên viên chính Quan hệ khách hàng",
    });
    expect(people[1]).toMatchObject({
      person_id: 1011,
      name: "Nguyễn Thị Thanh Thư",
    });
  });

  it("trích xuất đúng danh sách prospect từ metadata.result_snapshot.items cho RB", async () => {
    const { extractProspectAnswerPeople } = await import("./searchPersistence");
    const metadata = {
      answer_engine: true,
      result_snapshot: {
        kind: "answer",
        count: 1,
        items: [
          { id: 456, name: "Công ty ABC", why: "Có nhu cầu vay vốn", priority_score: 85 },
        ],
      },
    };

    const prospects = extractProspectAnswerPeople(metadata);
    expect(prospects).toHaveLength(1);
    expect(prospects[0]).toMatchObject({
      person_id: 456,
      name: "Công ty ABC",
      why: "Có nhu cầu vay vốn",
      priority_score: 85,
    });
  });
});

