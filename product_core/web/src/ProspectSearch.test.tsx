import "@testing-library/jest-dom/vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import ProspectSearch from "./ProspectSearch";
import { AnswerStreamEvent, api } from "./api";
import { CustomThemeProvider } from "./CustomThemeContext";
import { SearchStateProvider } from "./searchPersistence";

/**
 * Growth Radar dùng CHUNG một "cỗ máy" chat AI với Talent Radar (`AiSearch`)
 * — xem `CopilotChat.tsx`. Điều bài này canh kỹ nhất vẫn là **tiêu chí luôn
 * hiện ra**: không có kế hoạch thì RM không biết hệ thống hiểu câu hỏi thế
 * nào và không sửa được khi hiểu sai.
 */

beforeEach(() => {
  sessionStorage.clear();
  vi.spyOn(api, "conversations").mockResolvedValue({ results: [] });
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

function renderSearch() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <CustomThemeProvider>
        <MemoryRouter>
          <SearchStateProvider>
            <ProspectSearch />
          </SearchStateProvider>
        </MemoryRouter>
      </CustomThemeProvider>
    </QueryClientProvider>,
  );
}

function fakeRbAsk(events: AnswerStreamEvent[]) {
  return vi.spyOn(api, "rbAsk").mockImplementation(async function* () {
    for (const event of events) yield event;
  });
}

function ask(question: string) {
  fireEvent.change(screen.getByPlaceholderText(/Mô tả chân dung/), {
    target: { value: question },
  });
  fireEvent.click(screen.getByRole("button", { name: "Tìm khách hàng" }));
}

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

const fullTurn: AnswerStreamEvent[] = [
  { event: "step", data: { label: "Hiểu yêu cầu", state: "done" } },
  { event: "preamble", data: { text: "Mình hiểu bạn cần…", plan: PLAN } },
  { event: "step", data: { label: "Tìm khách hàng", state: "active" } },
  { event: "answer", data: { text: "1. **Trần Thị Bình** cần vay mua xe [1]." } },
  { event: "done", data: {
    answer: "1. **Trần Thị Bình** cần vay mua xe [1].",
    people: [PERSON], provider: "gemini", model: "m1", trace: { plan: PLAN } } },
];

describe("Hỏi bằng lời với AI — màn hình chào mừng", () => {
  it("gợi ý câu hỏi mẫu khi chưa hỏi gì", () => {
    renderSearch();
    expect(screen.getByText(/quan tâm thẻ tín dụng/)).toBeInTheDocument();
  });
});

describe("Growth Answer Engine — đường chính", () => {
  it("câu tìm khách đi engine mới, không còn gọi engine 8-khoá cũ", async () => {
    const stream = fakeRbAsk(fullTurn);
    const legacy = vi.spyOn(api, "rbProspects");
    const { container } = renderSearch();
    ask("khách nào cần vay mua xe");
    expect((await screen.findAllByText("Trần Thị Bình")).length).toBeGreaterThan(0);
    expect(stream).toHaveBeenCalledTimes(1);
    // Đường 8-khoá cũ vẫn tồn tại trong api.ts nhưng ProspectSearch không còn
    // gọi tới nó — RB giờ đi cùng một cỗ máy Answer Engine với Talent.
    expect(legacy).not.toHaveBeenCalled();
    // Tên nhắc trong câu chữ tự thành liên kết (tính năng vốn chỉ Talent có) —
    // phải trỏ về ngữ cảnh RB, không lẫn sang Talent (khác "← Quay lại" & tab).
    const inlineMention = container.querySelector("a.chat-person-link");
    expect(inlineMention).toHaveAttribute("href", "/person/42?from=rb");
  });

  it("vẫn hiện cách hệ thống hiểu câu hỏi — ràng buộc 'tiêu chí luôn hiện ra'", async () => {
    fakeRbAsk(fullTurn);
    renderSearch();
    ask("khách nào cần vay mua xe");
    expect(await screen.findByText(/Hệ thống hiểu câu hỏi/)).toBeInTheDocument();
    expect(screen.getByText("Phạm vi: Toàn kho khách hàng")).toBeInTheDocument();
    expect(screen.getByText("Bắt buộc: có nhu cầu vay mua xe")).toBeInTheDocument();
  });

  it("kế hoạch hiện NGAY từ preamble, trước khi có danh sách", async () => {
    // Dừng ở preamble: chưa có `done`, chưa có khách nào.
    fakeRbAsk(fullTurn.slice(0, 2));
    renderSearch();
    ask("khách nào cần vay mua xe");
    expect(await screen.findByText("Bắt buộc: có nhu cầu vay mua xe")).toBeInTheDocument();
    expect(screen.queryByText("Trần Thị Bình")).not.toBeInTheDocument();
  });

  it("hiện hành động do hệ thống chọn, độ mới của tín hiệu và điểm ưu tiên", async () => {
    fakeRbAsk(fullTurn);
    renderSearch();
    ask("khách nào cần vay mua xe");
    expect(await screen.findByText(/→ Gọi ngay/)).toBeInTheDocument();
    expect(screen.getByText(/tín hiệu 4 ngày trước/)).toBeInTheDocument();
    expect(screen.getByText("81")).toBeInTheDocument();
    expect(screen.getByText(/Tự viết cần vay mua xe điện 4 ngày trước/)).toBeInTheDocument();
  });

  it("đánh dấu người đã có cơ hội đang mở", async () => {
    fakeRbAsk([
      ...fullTurn.slice(0, 4),
      { event: "done", data: {
        answer: "1. **Trần Thị Bình** cần vay mua xe [1].",
        people: [{ ...PERSON, has_open_opportunity: true }], trace: { plan: PLAN } } },
    ]);
    renderSearch();
    ask("khách nào cần vay mua xe");
    expect(await screen.findByText("Đã có cơ hội mở")).toBeInTheDocument();
  });

  it("nói đúng thứ tự đang sắp: mức đáng ưu tiên, không phải độ khớp chữ", async () => {
    fakeRbAsk(fullTurn);
    renderSearch();
    ask("khách nào cần vay mua xe");
    expect(await screen.findByText(/xếp theo mức đáng ưu tiên liên hệ/)).toBeInTheDocument();
  });

  it("cảnh báo khi kế hoạch là dự phòng (mô hình không hiểu được câu hỏi)", async () => {
    fakeRbAsk([
      { event: "preamble", data: { text: "…", plan: { ...PLAN, fallback: true } } },
      { event: "done", data: { answer: "Đoán theo từ khoá.", people: [],
        trace: { plan: { ...PLAN, fallback: true } } } },
    ]);
    renderSearch();
    ask("khách nào cần vay mua xe");
    expect(await screen.findByText("Dự phòng (đoán theo từ khoá)")).toBeInTheDocument();
  });

  it("không có ai khớp thì chỉ đường thay vì bỏ mặc", async () => {
    fakeRbAsk([
      { event: "preamble", data: { text: "…", plan: PLAN } },
      { event: "done", data: { answer: "Chưa tìm thấy ai.", people: [], trace: { plan: PLAN } } },
    ]);
    renderSearch();
    ask("khách nào cần vay mua xe");
    expect(await screen.findByText(/Thử điều chỉnh câu hỏi mô tả/)).toBeInTheDocument();
  });

  it("bản sửa sau kiểm trích dẫn THAY bản cũ, không nối thêm", async () => {
    fakeRbAsk([
      { event: "preamble", data: { text: "…", plan: PLAN } },
      { event: "answer", data: { text: "Bản nháp thiếu nguồn." } },
      { event: "revision", data: { text: "Bản đã sửa có nguồn [1]." } },
      { event: "done", data: { answer: "Bản đã sửa có nguồn [1].", people: [PERSON],
        trace: { plan: PLAN } } },
    ]);
    renderSearch();
    ask("khách nào cần vay mua xe");
    expect(await screen.findByText(/Bản đã sửa có nguồn/)).toBeInTheDocument();
    expect(screen.queryByText(/Bản nháp thiếu nguồn/)).not.toBeInTheDocument();
  });

  it("câu hội thoại cũng đi MỘT đường qua engine, nguồn web vẫn hiện", async () => {
    const stream = fakeRbAsk([
      { event: "answer", data: { text: "Radar hỗ trợ RM tìm khách hàng." } },
      { event: "done", data: {
        answer: "Radar hỗ trợ RM tìm khách hàng.",
        web_sources: [{ title: "Trang MSB", url: "https://msb.com.vn" }] } },
    ]);
    renderSearch();
    ask("Radar là gì?");
    expect(await screen.findByText("Radar hỗ trợ RM tìm khách hàng.")).toBeInTheDocument();
    expect(screen.getByText("Trang MSB")).toBeInTheDocument();
    expect(stream).toHaveBeenCalledTimes(1);
    // Không có kế hoạch = không phải lượt tìm kiếm: không hiện thẻ tiêu chí
    // rỗng hay ô "chưa có khách nào" dưới một câu chào hỏi thuần tuý.
    expect(screen.queryByText(/Hệ thống hiểu câu hỏi/)).not.toBeInTheDocument();
  });
});

describe("Growth Answer Engine — hội thoại tích luỹ & khôi phục", () => {
  it("hội thoại tích luỹ nhiều lượt, câu hỏi tiếp theo gửi kèm lượt trước", async () => {
    const stream = fakeRbAsk(fullTurn);
    renderSearch();
    ask("khách nào cần vay mua xe");
    await waitFor(() => expect(stream).toHaveBeenCalledTimes(1));
    expect(stream.mock.calls[0][0].q).toBe("khách nào cần vay mua xe");

    fireEvent.change(screen.getByPlaceholderText(/Mô tả chân dung/), {
      target: { value: "vậy còn ở Hà Nội thì sao" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Gửi câu hỏi" }));

    await waitFor(() => expect(stream).toHaveBeenCalledTimes(2));
    expect(stream.mock.calls[1][0].q).toBe("vậy còn ở Hà Nội thì sao");
    expect(stream.mock.calls[1][0].history).toEqual([
      expect.objectContaining({
        criteria: {},
        question: "khách nào cần vay mua xe",
        answer: "1. **Trần Thị Bình** cần vay mua xe [1].",
      }),
    ]);
    // Cả hai lượt hỏi/đáp đều còn hiện trong luồng chat — không bị ghi đè
    // mất lượt trước (khác hẳn "một câu hỏi/một câu trả lời" của bản cũ).
    expect(screen.getByText("khách nào cần vay mua xe")).toBeInTheDocument();
    expect(screen.getByText("vậy còn ở Hà Nội thì sao")).toBeInTheDocument();
  });

  it("giữ nguyên kết quả khi component bị gỡ rồi dựng lại (mô phỏng bấm vào hồ sơ rồi quay lại)", async () => {
    fakeRbAsk(fullTurn);
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });

    function Wrapper({ show }: { show: boolean }) {
      return (
        <QueryClientProvider client={client}>
          <CustomThemeProvider>
            <MemoryRouter>
              <SearchStateProvider>{show ? <ProspectSearch /> : <div>Trang hồ sơ</div>}</SearchStateProvider>
            </MemoryRouter>
          </CustomThemeProvider>
        </QueryClientProvider>
      );
    }

    const { rerender } = render(<Wrapper show />);
    fireEvent.change(screen.getByPlaceholderText(/Mô tả chân dung/), {
      target: { value: "khách nào cần vay mua xe" },
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
    expect(screen.getAllByText("Trần Thị Bình").length).toBeGreaterThan(0);
  });

  it("không huỷ lượt đang chạy khi component bị gỡ", async () => {
    let release!: () => void;
    const gate = new Promise<void>((resolve) => { release = resolve; });
    const stream = vi.spyOn(api, "rbAsk").mockImplementation(async function* () {
      yield { event: "step", data: { label: "Đang đọc tín hiệu", state: "active" } } as AnswerStreamEvent;
      await gate;
      yield { event: "done", data: { answer: "Đã hoàn tất sau khi quay lại.", people: [] } } as AnswerStreamEvent;
    });
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    function Wrapper({ show }: { show: boolean }) {
      return <QueryClientProvider client={client}><CustomThemeProvider><MemoryRouter>
        <SearchStateProvider>{show ? <ProspectSearch /> : <div>Trang hồ sơ</div>}</SearchStateProvider>
      </MemoryRouter></CustomThemeProvider></QueryClientProvider>;
    }
    const { rerender } = render(<Wrapper show />);
    ask("khách nào cần vay mua xe");
    expect((await screen.findAllByText("Đang đọc tín hiệu")).length).toBeGreaterThan(0);
    rerender(<Wrapper show={false} />);
    release();
    rerender(<Wrapper show />);
    expect(await screen.findByText("Đã hoàn tất sau khi quay lại.")).toBeInTheDocument();
    expect(stream).toHaveBeenCalledTimes(1);
  });
});

describe("Growth Answer Engine — phục hồi khi mất kết nối", () => {
  it("lỗi giữa chừng vẫn giữ phần chữ đã nhận và báo rõ, KHÔNG rơi về engine 8-khoá cũ", async () => {
    vi.spyOn(api, "rbAsk").mockImplementation(async function* () {
      yield { event: "answer", data: { text: "Đang viết dở" } } as AnswerStreamEvent;
      throw new Error("mất kết nối");
    });
    // Stream đứt → thử lấy lại kết quả trước khi báo hỏng. Ở đây coi như không
    // lấy được (404) — sau khi thử xong mới hiện "Mất kết nối".
    vi.spyOn(api, "rbAskTurn").mockRejectedValue(new Error("404"));
    renderSearch();

    ask("khách nào cần vay mua xe");

    expect(await screen.findByText(/Đang viết dở/)).toBeInTheDocument();
    expect(
      await screen.findByText(/Mất kết nối khi đang trả lời/, undefined, { timeout: 20000 }),
    ).toBeInTheDocument();
  }, 25000);

  it("stream đứt nhưng máy chủ đã lưu → lấy lại được câu trả lời đầy đủ", async () => {
    vi.spyOn(api, "rbAsk").mockImplementation(async function* () {
      yield { event: "answer", data: { text: "Một phần" } } as AnswerStreamEvent;
      throw new Error("mất kết nối");
    });
    vi.spyOn(api, "rbAskTurn")
      .mockResolvedValueOnce({ state: "running" })
      .mockResolvedValue({
        state: "done",
        answer: "Câu trả lời đầy đủ đã lấy lại được.",
        people: [],
        trace: { ms_total: 1800 },
        duration_ms: 1800,
      });
    renderSearch();

    ask("khách nào cần vay mua xe");

    expect(
      await screen.findByText(/Câu trả lời đầy đủ đã lấy lại được/, undefined, { timeout: 10000 }),
    ).toBeInTheDocument();
    expect(screen.queryByText(/Mất kết nối/)).not.toBeInTheDocument();
  }, 15000);
});

describe("Growth Answer Engine — lượt câu lệnh", () => {
  it("bản nháp hiện thành văn bản, KHÔNG thành thẻ khách điểm 0 hay thẻ tiêu chí", async () => {
    fakeRbAsk([
      { event: "step", data: { label: "Thực hiện yêu cầu", state: "done" } },
      { event: "answer", data: { text: "Đã soạn 1 bản nháp tin nhắn. Chưa gửi cho ai" } },
      { event: "done", data: {
        answer: "Đã soạn 1 bản nháp tin nhắn. Chưa gửi cho ai",
        people: [{ ...PERSON, person_id: 5, name: "Khách Năm" }],
        trace: { plan: PLAN, mode: "draft_message", keeps_last_result: true } } },
    ]);
    renderSearch();
    ask("soạn tin cho khách đầu tiên");
    expect(await screen.findByText(/Chưa gửi cho ai/)).toBeInTheDocument();
    expect(screen.queryByText(/Hệ thống hiểu câu hỏi/)).not.toBeInTheDocument();
    expect(screen.queryByText("Khách Năm")).not.toBeInTheDocument();
  });
});

describe("Growth Answer Engine — lượt đếm", () => {
  it("đếm chính xác hiện con số, KHÔNG kèm ô 'chưa có khách nào'", async () => {
    fakeRbAsk([
      { event: "preamble", data: { text: "…", plan: { shape: "count" } } },
      { event: "answer", data: { text: "Có **12** khách hàng thoả: ở Hà Nội." } },
      { event: "done", data: {
        answer: "Có **12** khách hàng thoả: ở Hà Nội.", people: [],
        trace: { plan: { shape: "count" }, count: { exact: true } } } },
    ]);
    renderSearch();
    ask("bao nhiêu khách ở Hà Nội");
    // Markdown tách "**12**" thành phần tử riêng — tìm đúng con số.
    expect(await screen.findByText("12")).toBeInTheDocument();
    expect(screen.queryByText(/Chưa có khách hàng nào có đủ bằng chứng/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Hệ thống hiểu câu hỏi/)).not.toBeInTheDocument();
  });
});
