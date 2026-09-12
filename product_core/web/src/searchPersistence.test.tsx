import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { SearchStateProvider, useTalentFilterState } from "./searchPersistence";

function FilterHarness() {
  const state = useTalentFilterState();
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

describe("trạng thái bộ lọc Talent", () => {
  beforeEach(() => localStorage.clear());
  afterEach(cleanup);

  it("giữ bộ lọc, trang kết quả và lịch sử sau khi provider được dựng lại", async () => {
    const first = render(<SearchStateProvider><FilterHarness /></SearchStateProvider>);
    fireEvent.click(screen.getByRole("button", { name: "lọc" }));
    expect(screen.getByTestId("query")).toHaveTextContent("Java");
    expect(screen.getByTestId("page")).toHaveTextContent("2");
    expect(screen.getByTestId("history")).toHaveTextContent("1");
    await waitFor(() => expect(localStorage.getItem("msb-radar-talent-filter-state-v1")).toContain("Java"));

    first.unmount();
    render(<SearchStateProvider><FilterHarness /></SearchStateProvider>);
    expect(screen.getByTestId("query")).toHaveTextContent("Java");
    expect(screen.getByTestId("page")).toHaveTextContent("2");
    expect(screen.getByTestId("history")).toHaveTextContent("1");
  });
});
