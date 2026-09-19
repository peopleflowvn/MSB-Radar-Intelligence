import "@testing-library/jest-dom/vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import AiSearch from "./AiSearch";
import { AnswerStreamEvent, api } from "./api";
import { CustomThemeProvider } from "./CustomThemeContext";
import { SearchStateProvider } from "./searchPersistence";

beforeEach(() => {
  sessionStorage.clear();
  vi.spyOn(api, "conversations").mockResolvedValue({ results: [] });
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

function renderSearch() {
  const client = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <CustomThemeProvider>
        <MemoryRouter>
          <SearchStateProvider>
            <AiSearch />
          </SearchStateProvider>
        </MemoryRouter>
      </CustomThemeProvider>
    </QueryClientProvider>,
  );
}

function fakeAsk(events: AnswerStreamEvent[]) {
  return vi.spyOn(api, "talentAsk").mockImplementation(async function* () {
    for (const event of events) yield event;
  });
}

const SOURCE = {
  n: 1, person_id: 7, name: "Nguyễn An", document_id: 42, ordinal: 0,
  snippet: "chuyên viên quan hệ khách hàng cá nhân",
};

function ask(question: string) {
  fireEvent.change(screen.getByPlaceholderText(/Mô tả người cần tìm/), {
    target: { value: question },
  });
  fireEvent.click(screen.getByRole("button", { name: "Gửi yêu cầu phân tích" }));
}

describe("Answer Engine trên giao diện", () => {
  it("mọi câu hỏi đi qua /ask/, không còn nhánh tìm kiếm theo tiêu chí", async () => {
    const askSpy = fakeAsk([
      { event: "stage", data: { stage: "plan", text: "Đang hiểu câu hỏi" } },
      { event: "answer", data: { text: "Nguyễn An làm quan hệ khách hàng [1]." } },
      { event: "done", data: {
        answer: "Nguyễn An làm quan hệ khách hàng [1].",
        citations: [SOURCE], people: [], provider: "greennode", model: "v4-pro" } },
    ]);
    renderSearch();

    ask("ai làm quan hệ khách hàng?");

    expect(await screen.findByText(/Nguyễn An làm quan hệ khách hàng/)).toBeInTheDocument();
    expect(askSpy).toHaveBeenCalledTimes(1);
    // Đường cũ đã gỡ hẳn khỏi client, không còn gì để gọi nhầm sang.
    expect("aiSearch" in api).toBe(false);
  });

  it("giữ lại và hiển thị thời gian xử lý sau khi trả lời xong", async () => {
    fakeAsk([{ event: "done", data: {
      answer: "Đã phân tích xong.", citations: [], people: [],
      trace: { ms_total: 2468 }, duration_ms: 2468,
    } }]);
    renderSearch();

    ask("phân tích giúp tôi");

    expect(await screen.findByText("Hoàn tất trong 2.5 giây")).toBeInTheDocument();
  });

  it("hiện trạng thái từng chặng trong lúc chưa có chữ nào", async () => {
    fakeAsk([
      { event: "stage", data: { stage: "judge", text: "Đã đọc 30 hồ sơ, 4 hồ sơ phù hợp" } },
    ]);
    renderSearch();

    ask("ai học cao đẳng?");

    expect(await screen.findByText("Đã đọc 30 hồ sơ, 4 hồ sơ phù hợp")).toBeInTheDocument();
  });

  it("[n] trong câu chữ bấm được và mở đúng đoạn CV gốc", async () => {
    fakeAsk([
      { event: "done", data: {
        answer: "Nguyễn An phù hợp [1].", citations: [SOURCE], people: [] } },
    ]);
    const docText = vi.spyOn(api, "documentText").mockResolvedValue({
      id: 42, text: "Nguyễn An — chuyên viên quan hệ khách hàng cá nhân tại ACB.",
    } as never);
    renderSearch();

    ask("ai phù hợp?");

    const citation = await screen.findByRole("button", { name: "1" });
    fireEvent.click(citation);

    await waitFor(() => expect(docText).toHaveBeenCalledWith(42));
    expect(await screen.findByText(/Đoạn được trích/)).toBeInTheDocument();
  });

  it("câu hỏi tra internet hiện nguồn ngoài, tách khỏi trích dẫn CV", async () => {
    fakeAsk([
      { event: "stage", data: { stage: "web", text: "Đang tra trên internet" } },
      { event: "done", data: {
        answer: "Lãi suất huy động quanh 5%/năm.", citations: [], people: [],
        web_sources: [{ title: "Ngân hàng Nhà nước", url: "https://sbv.gov.vn" }] } },
    ]);
    renderSearch();

    ask("lãi suất huy động hiện nay?");

    const toggle = await screen.findByText("🌐 Nguồn trên internet");
    expect(toggle).toBeInTheDocument();
    fireEvent.click(toggle);
    const link = screen.getByRole("link", { name: "Ngân hàng Nhà nước" });
    expect(link).toHaveAttribute("href", "https://sbv.gov.vn");
  });

  it("trả lời xong thì mọi bước đều tick xong, không còn bước nào đang chạy", async () => {
    // Máy chủ gửi bước cuối ở trạng thái `active` rồi kết thúc bằng `done` —
    // KHÔNG có chunk đóng riêng cho nó. Trước đây thẻ tiến trình đứng lại ở
    // "2/3 bước" kèm vòng xoay bên cạnh câu trả lời đã hiện đủ.
    fakeAsk([
      { event: "step", data: { label: "Hiểu yêu cầu", state: "done" } },
      { event: "step", data: { label: "Tra trên internet", state: "active" } },
      { event: "step", data: { label: "Soạn câu trả lời", state: "active" } },
      { event: "answer", data: { text: "Chào anh/chị!" } },
      { event: "done", data: { answer: "Chào anh/chị!", citations: [], people: [] } },
    ]);
    const { container } = renderSearch();

    ask("xin chào");

    expect(await screen.findByText(/Chào anh\/chị!/)).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getByText(/Quá trình xử lý \(3\/3 bước\)/)).toBeInTheDocument();
    });
    expect(container.querySelectorAll(".step-spinner-icon")).toHaveLength(0);
    expect(container.querySelectorAll(".radar-step-item.step-active")).toHaveLength(0);
    expect(screen.getByText("Chi tiết ▾")).toBeInTheDocument();
    fireEvent.click(screen.getByText("Chi tiết ▾"));
    expect(screen.getByText("Thu gọn ▲")).toBeInTheDocument();
    fireEvent.click(screen.getByText("Thu gọn ▲"));
    expect(screen.getByText("Chi tiết ▾")).toBeInTheDocument();
  });

  it("trích dẫn gộp [1,2] thành hai nút bấm riêng", async () => {
    const second = { ...SOURCE, n: 2, document_id: 43, snippet: "tư vấn khách hàng" };
    fakeAsk([
      { event: "done", data: {
        answer: "Hai người này đều hợp [1,2].",
        citations: [SOURCE, second], people: [] } },
    ]);
    renderSearch();

    ask("ai phù hợp?");

    // Mỗi số là một nguồn khác nhau — gộp vào một nút thì chỉ mở được nguồn đầu.
    expect(await screen.findByRole("button", { name: "1" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "2" })).toBeInTheDocument();
  });

  it("không còn thẻ ứng viên: người chỉ hiện thành chip mở hồ sơ", async () => {
    fakeAsk([
      { event: "done", data: {
        answer: "Có 1 hồ sơ [1].", citations: [SOURCE],
        people: [{ person_id: 7, name: "Nguyễn An", why: "khớp",
                   attributes: { "năm sinh": "1995" }, citations: [1] }] } },
    ]);
    const { container } = renderSearch();

    ask("ai phù hợp?");

    expect(await screen.findByText("Hồ sơ phù hợp")).toBeInTheDocument();
    expect(screen.getByText(/năm sinh: 1995/)).toBeInTheDocument();
    // Không còn điểm %, không còn nút thêm vào chiến dịch — tức là hết thẻ.
    expect(container.querySelector(".ai-card")).toBeNull();
    expect(container.querySelector(".criteria")).toBeNull();
  });

  it("người gần đúng nằm ở nhóm riêng và hiện điều còn thiếu, không hiện như kết quả", async () => {
    fakeAsk([
      { event: "done", data: {
        answer: "Không ai đạt đủ.", citations: [],
        people: [{ person_id: 8, name: "Lương Hữu Duy", why: "Thực tập Data Analyst",
                   gap: "chưa đủ 3 năm kinh nghiệm", judgement_status: "SUGGESTION",
                   attributes: {}, citations: [],
                   profile: { title: "Data Analyst Intern", company: "ABC" } }] } },
    ]);
    renderSearch();

    ask("Tìm Senior Data Analyst");

    expect(await screen.findByText("Gần phù hợp — chưa đạt đủ tiêu chí")).toBeInTheDocument();
    expect(screen.queryByText("Hồ sơ phù hợp")).not.toBeInTheDocument();
    expect(screen.getByText("Còn thiếu: chưa đủ 3 năm kinh nghiệm")).toBeInTheDocument();
    expect(screen.getByText("Data Analyst Intern · ABC")).toBeInTheDocument();
    expect(screen.queryByText("Hồ sơ đối soát trong kho nhân tài")).not.toBeInTheDocument();
  });

  it("gửi tệp đính kèm kèm câu hỏi", async () => {
    const askSpy = fakeAsk([{ event: "done", data: { answer: "Đã đọc JD.", citations: [], people: [] } }]);
    const { container } = renderSearch();

    const file = new File(["Cần Python ngân hàng"], "yeu-cau.txt", { type: "text/plain" });
    const input = container.querySelector('input[type="file"]') as HTMLInputElement;
    fireEvent.change(input, { target: { files: [file] } });
    ask("Tìm người hợp JD này");

    await waitFor(() => expect(askSpy).toHaveBeenCalledWith(
      expect.objectContaining({ q: "Tìm người hợp JD này", files: [file] }),
      expect.anything(),
    ));
    expect(screen.getByText(/yeu-cau.txt/)).toBeInTheDocument();
  });

  it("nhận ảnh dán từ clipboard (paste Ctrl+V) làm tệp đính kèm", async () => {
    renderSearch();
    const textarea = screen.getByPlaceholderText(/Mô tả người cần tìm/);

    const imageFile = new File(["fake-image-data"], "anh-chup-man-hinh.png", { type: "image/png" });
    const pasteEvent = new Event("paste", { bubbles: true, cancelable: true });
    Object.defineProperty(pasteEvent, "clipboardData", {
      value: {
        items: [
          {
            type: "image/png",
            kind: "file",
            getAsFile: () => imageFile,
          },
        ],
        files: [imageFile],
      },
    });

    fireEvent(textarea, pasteEvent);
    expect(await screen.findByText(/anh-chup-man-hinh\.png/)).toBeInTheDocument();
  });

  it("có nút đánh giá câu trả lời và gửi được", async () => {
    fakeAsk([{ event: "done", data: {
      answer: "Có 1 hồ sơ [1].", citations: [SOURCE], people: [] } }]);
    const feedback = vi.spyOn(api, "aiFeedback").mockResolvedValue({ ok: true });
    renderSearch();

    ask("ai phù hợp?");

    const thumbUp = await screen.findByTitle("Dùng được");
    fireEvent.click(thumbUp);

    await waitFor(() => expect(feedback).toHaveBeenCalledWith(
      expect.objectContaining({ rating: "up", question: "ai phù hợp?",
                                answer: "Có 1 hồ sơ [1]." })));
    expect(await screen.findByText(/Cảm ơn phản hồi/)).toBeInTheDocument();
  });

  it("lỗi giữa chừng vẫn giữ phần chữ đã nhận và báo rõ", async () => {
    vi.spyOn(api, "talentAsk").mockImplementation(async function* () {
      yield { event: "answer", data: { text: "Có 2 hồ sơ" } } as AnswerStreamEvent;
      throw new Error("mất kết nối");
    });
    // Stream đứt → thử lấy lại kết quả trước khi báo hỏng. Ở đây coi như không
    // lấy được (404) — sau khi thử xong mới hiện "Mất kết nối".
    vi.spyOn(api, "talentAskTurn").mockRejectedValue(new Error("404"));
    renderSearch();

    ask("ai phù hợp?");

    expect(await screen.findByText(/Có 2 hồ sơ/)).toBeInTheDocument();
    expect(
      await screen.findByText(/Mất kết nối khi đang trả lời/, undefined, { timeout: 20000 }),
    ).toBeInTheDocument();
  }, 25000);

  it("stream đứt nhưng máy chủ đã lưu → lấy lại được câu trả lời đầy đủ", async () => {
    vi.spyOn(api, "talentAsk").mockImplementation(async function* () {
      yield { event: "answer", data: { text: "Một phần" } } as AnswerStreamEvent;
      throw new Error("mất kết nối");
    });
    vi.spyOn(api, "talentAskTurn")
      .mockResolvedValueOnce({ state: "running" })
      .mockResolvedValue({
        state: "done",
        answer: "Câu trả lời đầy đủ đã lấy lại được.",
        citations: [],
        people: [],
        trace: { ms_total: 1800 },
        duration_ms: 1800,
      });
    renderSearch();

    ask("ai phù hợp?");

    expect(
      await screen.findByText(/Câu trả lời đầy đủ đã lấy lại được/, undefined, { timeout: 10000 }),
    ).toBeInTheDocument();
    expect(screen.queryByText(/Mất kết nối/)).not.toBeInTheDocument();
    expect(screen.getByText("Hoàn tất trong 1.8 giây")).toBeInTheDocument();
  }, 15000);

  it("giữ nguyên hội thoại khi component bị gỡ rồi dựng lại", async () => {
    fakeAsk([{ event: "done", data: {
      answer: "Chưa có hồ sơ nào thoả yêu cầu này.", citations: [], people: [] } }]);
    const client = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
    function Wrapper({ show }: { show: boolean }) {
      return (
        <QueryClientProvider client={client}>
          <CustomThemeProvider>
            <MemoryRouter>
              <SearchStateProvider>{show ? <AiSearch /> : <div>Trang hồ sơ</div>}</SearchStateProvider>
            </MemoryRouter>
          </CustomThemeProvider>
        </QueryClientProvider>
      );
    }

    const { rerender } = render(<Wrapper show />);
    fireEvent.click(screen.getByRole("button", { name: /Senior Data Analyst/ }));
    expect(await screen.findByText(/Chưa có hồ sơ nào thoả/)).toBeInTheDocument();

    rerender(<Wrapper show={false} />);
    expect(screen.getByText("Trang hồ sơ")).toBeInTheDocument();

    rerender(<Wrapper show />);
    expect(screen.getByText(/Chưa có hồ sơ nào thoả/)).toBeInTheDocument();
  });

  it("không hủy lượt đang chạy khi component bị gỡ", async () => {
    let release!: () => void;
    const gate = new Promise<void>((resolve) => { release = resolve; });
    const askSpy = vi.spyOn(api, "talentAsk").mockImplementation(async function* () {
      yield { event: "step", data: { label: "Đang đọc hồ sơ", state: "active" } } as AnswerStreamEvent;
      await gate;
      yield { event: "done", data: { answer: "Đã hoàn tất sau khi quay lại.", citations: [], people: [] } } as AnswerStreamEvent;
    });
    const client = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
    function Wrapper({ show }: { show: boolean }) {
      return <QueryClientProvider client={client}><CustomThemeProvider><MemoryRouter>
        <SearchStateProvider>{show ? <AiSearch /> : <div>Trang hồ sơ</div>}</SearchStateProvider>
      </MemoryRouter></CustomThemeProvider></QueryClientProvider>;
    }
    const { rerender } = render(<Wrapper show />);
    ask("phân tích hồ sơ Nguyễn An");
    expect((await screen.findAllByText("Đang đọc hồ sơ")).length).toBeGreaterThan(0);
    rerender(<Wrapper show={false} />);
    release();
    rerender(<Wrapper show />);
    expect(await screen.findByText("Đã hoàn tất sau khi quay lại.")).toBeInTheDocument();
    expect(askSpy).toHaveBeenCalledTimes(1);
  });

  it("thẻ chờ cho biết có thể chuyển tab", async () => {
    let release!: () => void;
    const gate = new Promise<void>((resolve) => { release = resolve; });
    vi.spyOn(api, "talentAsk").mockImplementation(async function* () {
      await gate;
      yield { event: "done", data: { answer: "xong", citations: [], people: [] } } as AnswerStreamEvent;
    });
    renderSearch();
    ask("tìm ứng viên Java");
    expect(await screen.findByText("Bạn có thể chuyển tab, Radar vẫn tiếp tục xử lý.")).toBeInTheDocument();
    // StepTimeline hiện đếm giây bằng nhãn ngắn "Ns" (component gộp Bước +
    // Đếm giây + Trạng thái), không còn chữ "giây" như thẻ chờ cũ.
    expect(await screen.findByText(/^\d+s$/)).toBeInTheDocument();
    release();
  });

  it("câu đếm cũng hiện mô hình AI đã viết câu trả lời", async () => {
    fakeAsk([{ event: "done", data: {
      answer: "Kho có 1.075 hồ sơ.", citations: [], people: [], provider: "greennode", model: "test-model",
      trace: { compose: { deterministic: false } },
    } }]);
    renderSearch();
    ask("kho có bao nhiêu hồ sơ?");
    expect(await screen.findByText("Kho có 1.075 hồ sơ.")).toBeInTheDocument();
    expect(screen.queryByText("Tính trực tiếp từ dữ liệu")).not.toBeInTheDocument();
  });

  it("cảnh báo khi câu trả lời là fallback kể cả model đã được thử", async () => {
    fakeAsk([{ event: "done", data: {
      answer: "Bản trả lời dự phòng.", citations: [], people: [],
      provider: "greennode", model: "deepseek-v4-pro",
      trace: { compose: { fallback: true } },
    } }]);
    renderSearch();
    ask("tìm ứng viên");
    expect(await screen.findByText("AI chưa hoàn tất đầy đủ")).toBeInTheDocument();
    expect(screen.queryByText(/greennode\/deepseek-v4-pro/)).not.toBeInTheDocument();
  });
});
