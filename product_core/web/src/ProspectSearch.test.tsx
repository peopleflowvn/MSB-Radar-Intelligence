import "@testing-library/jest-dom/vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import ProspectSearch from "./ProspectSearch";
import { api, ProspectResponse } from "./api";
import { SearchStateProvider } from "./searchPersistence";

/**
 * Điều bài này canh kỹ nhất: **tiêu chí luôn hiện ra**. Không có tiêu chí thì
 * RM không biết hệ thống hiểu câu hỏi thế nào và không sửa được khi hiểu sai —
 * đó là hộp đen, đúng thứ sản phẩm này cam kết không làm.
 */

beforeEach(() => {
  vi.spyOn(api, "conversations").mockResolvedValue({ results: [] });
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

function response(
  overrides: Partial<ProspectResponse> = {},
): ProspectResponse {
  return {
    question: "Tìm 20 quản lý ở Hà Nội",
    criteria: {
      location: "Hà Nội",
      seniority: "manager",
      products: ["credit_card"],
      segment: "",
      require_contact: true,
      exclude_open_opportunity: false,
      limit: 20,
      signal_recency_days: 0,
    },
    criteria_from: "agent",
    error: "",
    count: 1,
    results: [
      {
        person_id: 7,
        display_name: "Nguyễn Văn An",
        location: "Hà Nội",
        occupation: "Trưởng phòng kinh doanh",
        product: "credit_card",
        priority_score: 78.4,
        scores: { fit: 80, need: 70, timing: 100, reachability: 80, value: 50 },
        why: ["Khách nhắc tới: mở thẻ", "Tín hiệu trong 7 ngày qua"],
        has_open_opportunity: false,
      },
    ],
    ...overrides,
  };
}

function renderSearch() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <SearchStateProvider>
          <ProspectSearch />
        </SearchStateProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

/**
 * Đường DỰ PHÒNG: engine mới (`/rb/ask/`) hỏng trước khi trả chữ nào → giao diện
 * rơi về bộ lọc 8 khoá (`/rb/prospects/`). Ép `rbAsk` hỏng TƯỜNG MINH ở đây —
 * trước đây những test này chỉ qua được vì `fetch` thật trong jsdom tình cờ lỗi,
 * tức chúng canh đường dự phòng mà không ai biết.
 */
async function ask(body: ProspectResponse) {
  vi.spyOn(api, "rbAsk").mockImplementation(async function* () {
    throw new Error("engine mới không phản hồi");
  });
  vi.spyOn(api, "rbProspects").mockResolvedValue(body);
  renderSearch();
  fireEvent.change(screen.getByPlaceholderText(/Mô tả chân dung/), {
    target: { value: "Tìm 20 quản lý ở Hà Nội" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Tìm khách hàng" }));
  await waitFor(() =>
    expect(screen.getByText(/Hệ thống hiểu câu hỏi/)).toBeInTheDocument(),
  );
}

describe("Tìm khách bằng ngôn ngữ tự nhiên (đường dự phòng 8 khoá)", () => {
  it("gợi ý câu hỏi mẫu khi chưa hỏi gì", () => {
    renderSearch();
    expect(screen.getByText(/quan tâm thẻ tín dụng/)).toBeInTheDocument();
  });

  it("hiện tiêu chí đã bóc tách trước khi hiện kết quả", async () => {
    await ask(response());
    expect(screen.getByText("Khu vực: Hà Nội")).toBeInTheDocument();
    expect(screen.getByText("Cấp bậc: Quản lý")).toBeInTheDocument();
    expect(screen.getByText("Phải có liên hệ")).toBeInTheDocument();
  });

  it("nói rõ agent trên AgentBase đã bóc tách", async () => {
    // Khi kết quả trông lạ, người dùng cần biết đường nào đang phục vụ.
    await ask(response({ criteria_from: "agent" }));
    expect(screen.getByText("GreenNode AgentBase")).toBeInTheDocument();
  });

  it("cảnh báo khi đang chạy nhánh dự phòng", async () => {
    await ask(response({ criteria_from: "keyword" }));
    expect(screen.getByText("Dò từ khoá")).toBeInTheDocument();
    expect(screen.getByText(/kém tinh hơn/)).toBeInTheDocument();
  });

  it("ghi rõ đang dùng model nào khi có LLM tham gia", async () => {
    await ask(response({ criteria_from: "llm", provider: "greennode", model: "z-ai/glm-5.2-hackathon" }));
    expect(screen.getByText(/greennode\/z-ai\/glm-5\.2-hackathon/)).toBeInTheDocument();
  });

  it("không hiện tên model khi chỉ dò từ khoá (không mô hình nào tham gia)", async () => {
    await ask(response({ criteria_from: "keyword", provider: "", model: "" }));
    expect(screen.queryByText(/z-ai|greennode/)).not.toBeInTheDocument();
  });

  it("mỗi kết quả kèm điểm và lý do", async () => {
    await ask(response());
    expect(screen.getByText("Nguyễn Văn An")).toBeInTheDocument();
    expect(screen.getByText("78")).toBeInTheDocument();
    expect(screen.getByText("Khách nhắc tới: mở thẻ")).toBeInTheDocument();
  });

  it("không có ai khớp thì chỉ đường thay vì bỏ mặc", async () => {
    await ask(response({ count: 0, results: [] }));
    expect(screen.getByText(/nới bớt một điều kiện/)).toBeInTheDocument();
  });

  it("đánh dấu người đã có cơ hội đang mở", async () => {
    const body = response();
    body.results[0].has_open_opportunity = true;
    await ask(body);
    expect(screen.getByText("Đã có cơ hội mở")).toBeInTheDocument();
  });

  it("hội thoại tích luỹ nhiều lượt, câu hỏi tiếp theo gửi kèm tiêu chí lượt trước", async () => {
    const first = response();
    const second = response({
      question: "vậy còn ở Đà Nẵng thì sao",
      criteria: { ...first.criteria, location: "Đà Nẵng" },
    });
    const search = vi
      .spyOn(api, "rbProspects")
      .mockResolvedValueOnce(first)
      .mockResolvedValueOnce(second);
    renderSearch();

    fireEvent.change(screen.getByPlaceholderText(/Mô tả chân dung/), {
      target: { value: first.question },
    });
    fireEvent.click(screen.getByRole("button", { name: "Tìm khách hàng" }));
    await waitFor(() => expect(search).toHaveBeenCalledWith(first.question, [], expect.any(String), expect.any(String)));

    // Sau lượt đầu, giao diện chuyển sang luồng chat với ô nhập cố định bên
    // dưới — không còn ô "Hỏi bằng lời" ban đầu.
    fireEvent.change(screen.getByPlaceholderText(/Mô tả chân dung/), {
      target: { value: second.question },
    });
    fireEvent.click(screen.getByRole("button", { name: "Gửi câu hỏi" }));

    await waitFor(() =>
      expect(search).toHaveBeenLastCalledWith(second.question, [
        expect.objectContaining({ criteria: first.criteria, question: first.question,
          answer: expect.any(String) }),
      ], expect.any(String), expect.any(String)),
    );
    // Cả hai lượt hỏi/đáp đều còn hiện trong luồng chat — đúng "lịch sử trò
    // chuyện" như các chatbot AI khác, không bị ghi đè mất lượt trước.
    expect(screen.getByText(first.question)).toBeInTheDocument();
    expect(screen.getByText(second.question)).toBeInTheDocument();
  });

  it("giữ nguyên kết quả khi component bị gỡ rồi dựng lại (mô phỏng bấm vào hồ sơ rồi quay lại)", async () => {
    vi.spyOn(api, "rbProspects").mockResolvedValue(response());
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });

    function Wrapper({ show }: { show: boolean }) {
      return (
        <QueryClientProvider client={client}>
          <MemoryRouter>
            <SearchStateProvider>{show ? <ProspectSearch /> : <div>Trang hồ sơ</div>}</SearchStateProvider>
          </MemoryRouter>
        </QueryClientProvider>
      );
    }

    const { rerender } = render(<Wrapper show />);
    fireEvent.change(screen.getByPlaceholderText(/Mô tả chân dung/), {
      target: { value: "Tìm 20 quản lý ở Hà Nội" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Tìm khách hàng" }));
    await waitFor(() => expect(screen.getByText(/Hệ thống hiểu câu hỏi/)).toBeInTheDocument());

    // Gỡ ProspectSearch — đúng việc React Router làm khi điều hướng sang
    // /person/:id, NHƯNG SearchStateProvider (ở main.tsx, ngoài <Routes>)
    // vẫn còn sống.
    rerender(<Wrapper show={false} />);
    expect(screen.getByText("Trang hồ sơ")).toBeInTheDocument();

    // Dựng lại — như khi bấm "quay lại".
    rerender(<Wrapper show />);
    expect(screen.getByText(/Hệ thống hiểu câu hỏi/)).toBeInTheDocument();
    expect(screen.getByText("Nguyễn Văn An")).toBeInTheDocument();
  });

  it("câu hỏi hội thoại thì stream SSE, không gọi rbProspects", async () => {
    async function* fakeStream() {
      yield { event: "thinking" as const, data: { text: "Xác định phạm vi." } };
      yield { event: "answer" as const, data: { text: "Radar hỗ trợ RM tìm khách hàng." } };
      yield { event: "done" as const, data: { answer: "Radar hỗ trợ RM tìm khách hàng.",
        provider: "greennode", model: "m1" } };
    }
    const stream = vi.spyOn(api, "assistantStream").mockImplementation(fakeStream);
    const ask = vi.spyOn(api, "rbProspects");
    const client = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <MemoryRouter><SearchStateProvider><ProspectSearch /></SearchStateProvider></MemoryRouter>
      </QueryClientProvider>,
    );
    fireEvent.change(screen.getByPlaceholderText(/Mô tả chân dung/), {
      target: { value: "Radar là gì?" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Tìm khách hàng" }));
    expect(await screen.findByText("Radar hỗ trợ RM tìm khách hàng.")).toBeInTheDocument();
    expect(stream).toHaveBeenCalledTimes(1);
    expect(ask).not.toHaveBeenCalled();
  });
});

describe("Growth Answer Engine — đường chính", () => {
  const PLAN = {
    shape: "find_prospects",
    information_need: "khách cần vay mua xe",
    must_have: ["có nhu cầu vay mua xe"],
    products: ["auto_loan"],
    limit: 20,
  };
  const PERSON = {
    person_id: 42,
    name: "Trần Thị Bình",
    location: "Đà Nẵng",
    occupation: "Chủ cửa hàng",
    has_open_opportunity: false,
    reasons: ["Tự viết cần vay mua xe điện 4 ngày trước.", "Có liên hệ"],
    why: "Tự viết cần vay mua xe điện 4 ngày trước.",
    product: "auto_loan",
    priority_score: 81.2,
    scores: { fit: 70, need: 90, timing: 95, reachability: 80, value: 60 },
    need_kind: "nhu_cau",
    freshest_days: 4,
    action: "CALL_NOW",
    action_label: "Gọi ngay",
    sources: [1],
    url: "/person/42?from=rb",
  };

  async function askEngine(events: Array<{ event: string; data: Record<string, unknown> }>) {
    const stream = vi.spyOn(api, "rbAsk").mockImplementation(async function* () {
      for (const ev of events) yield ev as never;
    });
    const legacy = vi.spyOn(api, "rbProspects");
    renderSearch();
    fireEvent.change(screen.getByPlaceholderText(/Mô tả chân dung/), {
      target: { value: "khách nào cần vay mua xe" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Tìm khách hàng" }));
    return { stream, legacy };
  }

  const fullTurn = [
    { event: "step", data: { label: "Hiểu yêu cầu", state: "done" } },
    { event: "preamble", data: { text: "Mình hiểu bạn cần…", plan: PLAN } },
    { event: "step", data: { label: "Tìm khách hàng", state: "active" } },
    { event: "answer", data: { text: "1. **Trần Thị Bình** cần vay mua xe [1]." } },
    { event: "done", data: {
      answer: "1. **Trần Thị Bình** cần vay mua xe [1].",
      people: [PERSON], provider: "gemini", model: "m1", trace: { plan: PLAN } } },
  ];

  it("câu tìm khách đi engine mới, KHÔNG gọi bộ lọc 8 khoá", async () => {
    const { stream, legacy } = await askEngine(fullTurn);
    expect(await screen.findByText("Trần Thị Bình")).toBeInTheDocument();
    expect(stream).toHaveBeenCalledTimes(1);
    expect(legacy).not.toHaveBeenCalled();
  });

  it("vẫn hiện cách hệ thống hiểu câu hỏi — ràng buộc 'tiêu chí luôn hiện ra'", async () => {
    await askEngine(fullTurn);
    expect(await screen.findByText(/Hệ thống hiểu câu hỏi/)).toBeInTheDocument();
    expect(screen.getByText("Phạm vi: Toàn kho khách hàng")).toBeInTheDocument();
    expect(screen.getByText("Bắt buộc: có nhu cầu vay mua xe")).toBeInTheDocument();
  });

  it("kế hoạch hiện NGAY từ preamble, trước khi có danh sách", async () => {
    // Dừng ở preamble: chưa có `done`, chưa có khách nào.
    await askEngine(fullTurn.slice(0, 2));
    expect(await screen.findByText("Bắt buộc: có nhu cầu vay mua xe")).toBeInTheDocument();
    expect(screen.queryByText("Trần Thị Bình")).not.toBeInTheDocument();
  });

  it("hiện hành động do hệ thống chọn và độ mới của tín hiệu", async () => {
    await askEngine(fullTurn);
    expect(await screen.findByText(/→ Gọi ngay/)).toBeInTheDocument();
    expect(screen.getByText(/tín hiệu 4 ngày trước/)).toBeInTheDocument();
  });

  it("nói đúng thứ tự đang sắp: mức đáng ưu tiên, không phải độ khớp chữ", async () => {
    await askEngine(fullTurn);
    expect(await screen.findByText(/xếp theo mức đáng ưu tiên liên hệ/)).toBeInTheDocument();
  });

  it("bản sửa sau kiểm trích dẫn THAY bản cũ, không nối thêm", async () => {
    await askEngine([
      { event: "preamble", data: { text: "…", plan: PLAN } },
      { event: "answer", data: { text: "Bản nháp thiếu nguồn." } },
      { event: "revision", data: { text: "Bản đã sửa có nguồn [1]." } },
      { event: "done", data: { answer: "Bản đã sửa có nguồn [1].", people: [PERSON],
        trace: { plan: PLAN } } },
    ]);
    expect(await screen.findByText(/Bản đã sửa có nguồn/)).toBeInTheDocument();
    expect(screen.queryByText(/Bản nháp thiếu nguồn/)).not.toBeInTheDocument();
  });

  it("engine hỏng GIỮA CHỪNG (đã có chữ) thì giữ chữ, KHÔNG rơi về đường cũ", async () => {
    vi.spyOn(api, "rbAsk").mockImplementation(async function* () {
      yield { event: "answer", data: { text: "Đang viết dở" } } as never;
      throw new Error("mất kết nối");
    });
    const legacy = vi.spyOn(api, "rbProspects");
    renderSearch();
    fireEvent.change(screen.getByPlaceholderText(/Mô tả chân dung/), {
      target: { value: "khách nào cần vay mua xe" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Tìm khách hàng" }));
    expect(await screen.findByText(/Đang viết dở/)).toBeInTheDocument();
    expect(legacy).not.toHaveBeenCalled();
  });
});


describe("Growth Answer Engine — lượt câu lệnh", () => {
  it("bản nháp hiện thành văn bản, KHÔNG thành thẻ khách điểm 0 hay thẻ tiêu chí", async () => {
    vi.spyOn(api, "rbAsk").mockImplementation(async function* () {
      yield { event: "step", data: { label: "Thực hiện yêu cầu", state: "done" } } as never;
      yield { event: "answer", data: { text: "Đã soạn 1 bản nháp tin nhắn. Chưa gửi cho ai" } } as never;
      yield { event: "done", data: {
        answer: "Đã soạn 1 bản nháp tin nhắn. Chưa gửi cho ai",
        people: [{ person_id: 5, name: "Khách Năm", product: "fx", why: "" }],
        trace: { mode: "draft_message", keeps_last_result: true } } } as never;
    });
    const legacy = vi.spyOn(api, "rbProspects");
    renderSearch();
    fireEvent.change(screen.getByPlaceholderText(/Mô tả chân dung/), {
      target: { value: "soạn tin cho khách đầu tiên" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Tìm khách hàng" }));
    expect(await screen.findByText(/Chưa gửi cho ai/)).toBeInTheDocument();
    expect(screen.queryByText(/Hệ thống hiểu câu hỏi/)).not.toBeInTheDocument();
    expect(screen.queryByText("Khách Năm")).not.toBeInTheDocument();
    expect(legacy).not.toHaveBeenCalled();
  });
});
