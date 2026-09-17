import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import React, { useEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import {
  api,
  ApiError,
  HistoryTurn,
  ProspectAnswerPerson,
  ProspectAnswerPlan,
  ProspectCriteria,
  ProspectResponse,
  prospectRowFromAnswer,
  SavedView,
  SearchFilters,
  TalentCard,
  ToolCallTrace,
  WebSource,
} from "./api";
import { useCustomTheme } from "./CustomThemeContext";
import { ProspectChatMessage, useProspectChatState } from "./searchPersistence";
import { looksConversational } from "./conversationHeuristic";
import FormattedMarkdown from "./FormattedMarkdown";
import ThinkingProcess from "./ThinkingProcess";

/**
 * Tìm prospect bằng ngôn ngữ tự nhiên & Bộ lọc thông minh (RB Radar).
 *
 * Thiết kế tinh gọn, hiện đại và chuẩn mực:
 * 1. "✨ Hỏi & Tìm khách hàng với AI": Trợ lý Copilot thông minh với Hero Command Bar, Thẻ gợi ý nhanh & Thẻ kết quả đa chiều.
 * 2. "⚡ Bộ lọc Đa chiều & Danh bạ Khách hàng": Lọc đa chiều cho RM, hỗ trợ Saved Views, không tải sẵn 50 khách khi chưa tìm kiếm.
 */

const GOI_Y_RB = [
  {
    icon: "💳",
    title: "Thẻ tín dụng VIP",
    text: "Tìm 20 quản lý ở Hà Nội có contact, quan tâm thẻ tín dụng",
  },
  {
    icon: "🏡",
    title: "Vay mua nhà & BĐS",
    text: "Ai đang có nhu cầu vay mua nhà nhưng chưa có cơ hội đang mở",
  },
  {
    icon: "💎",
    title: "Khách hàng Ưu tiên (Priority)",
    text: "Tìm giám đốc ở Đà Nẵng có tín hiệu gần đây",
  },
  {
    icon: "📈",
    title: "Tiết kiệm & Đầu tư",
    text: "Tìm khách hàng cá nhân có dòng tiền nhàn rỗi quan tâm chứng chỉ tiền gửi hoặc đầu tư",
  },
];

const NGUON_TIEU_CHI: Record<string, { nhan: string; giai_thich: string }> = {
  agent: {
    nhan: "GreenNode AgentBase",
    giai_thich: "Câu hỏi được bóc tách bởi agent chạy trên GreenNode AgentBase.",
  },
  llm: {
    nhan: "GreenNode (tại Hub)",
    giai_thich: "Agent chưa sẵn sàng — Hub tự bóc tách bằng cùng mô hình.",
  },
  keyword: {
    nhan: "Dò từ khoá",
    giai_thich: "Không gọi được AI — đang dùng nhánh tất định. Kết quả kém tinh hơn.",
  },
};

const TEN_CHIEU: Record<keyof ProspectRowScores, string> = {
  fit: "Khớp hồ sơ",
  need: "Rõ nhu cầu",
  timing: "Đúng thời điểm",
  reachability: "Tiếp cận được",
  value: "Giá trị",
};

const PRODUCTS: Array<[string, string]> = [
  ["", "Tất cả sản phẩm"],
  ["mortgage", "Vay mua nhà"],
  ["credit_card", "Thẻ tín dụng"],
  ["savings", "Tiết kiệm"],
  ["investment", "Đầu tư"],
  ["insurance", "Bảo hiểm"],
  ["fx", "Ngoại tệ"],
  ["auto_loan", "Vay mua xe"],
  ["consumer_loan", "Vay tiêu dùng"],
  ["payroll", "Tài khoản lương"],
];

type ProspectRowScores = ProspectResponse["results"][number]["scores"];

function CriteriaChips({ criteria }: { criteria: ProspectCriteria }) {
  const chips: Array<{ icon: string; text: string }> = [];
  if (criteria.location) chips.push({ icon: "📍", text: `Khu vực: ${criteria.location}` });
  if (criteria.seniority)
    chips.push({
      icon: "👔",
      text: `Cấp bậc: ${criteria.seniority === "manager" ? "Quản lý" : "Cấp cao"}`,
    });
  if (criteria.segment) chips.push({ icon: "🎯", text: `Phân khúc: ${criteria.segment}` });
  if (criteria.products.length > 0)
    chips.push({ icon: "💼", text: `Sản phẩm: ${criteria.products.join(", ")}` });
  if (criteria.require_contact) chips.push({ icon: "📞", text: "Phải có liên hệ" });
  if (criteria.exclude_open_opportunity) chips.push({ icon: "🛡️", text: "Loại người đã có cơ hội mở" });
  if (criteria.signal_recency_days > 0)
    chips.push({ icon: "⏱️", text: `Tín hiệu trong ${criteria.signal_recency_days} ngày` });
  chips.push({ icon: "🔢", text: `Lấy tối đa ${criteria.limit}` });

  return (
    <div className="chips">
      {chips.map(({ icon, text }) => (
        <span className="chip" key={text}>
          <span style={{ fontSize: "12px" }}>{icon}</span> {text}
        </span>
      ))}
    </div>
  );
}

const PHAM_VI: Record<string, string> = {
  find_prospects: "Toàn kho khách hàng",
  portfolio: "Chỉ khách anh/chị đang phụ trách",
  whitespace: "Khách chưa ai phụ trách",
  analyze: "Tổng hợp toàn kho",
  count: "Đếm trong kho",
  compare: "So sánh khách đã nêu",
  followup: "Nhóm khách ở lượt trước",
};

/** Kế hoạch của Growth Answer Engine, cùng vai trò `CriteriaChips` cho engine cũ.
 *  Phạm vi đứng đầu: với Growth, phạm vi đổi TẬP KẾT QUẢ ("khách của tôi" khác
 *  "toàn kho"), nên hiểu nhầm phạm vi là lỗi RM cần nhìn thấy trước tiên. */
function PlanChips({ plan }: { plan?: ProspectAnswerPlan }) {
  const chips: Array<{ icon: string; text: string }> = [];
  if (!plan) {
    return <div className="chips"><span className="chip">Đang phân tích câu hỏi…</span></div>;
  }
  if (plan.shape && PHAM_VI[plan.shape]) chips.push({ icon: "🧭", text: `Phạm vi: ${PHAM_VI[plan.shape]}` });
  (plan.must_have ?? []).forEach((text) => chips.push({ icon: "✅", text: `Bắt buộc: ${text}` }));
  (plan.should_have ?? []).forEach((text) => chips.push({ icon: "➕", text: `Ưu tiên: ${text}` }));
  if (plan.products?.length) chips.push({ icon: "💼", text: `Sản phẩm: ${plan.products.join(", ")}` });
  const filters = plan.filters ?? {};
  if (filters.tinh_thanh) chips.push({ icon: "📍", text: `Khu vực: ${filters.tinh_thanh}` });
  if (filters.phan_khuc) chips.push({ icon: "🎯", text: `Phân khúc: ${filters.phan_khuc}` });
  if (filters.phai_co_lien_he) chips.push({ icon: "📞", text: "Phải có liên hệ" });
  if (filters.loai_co_hoi_dang_mo) chips.push({ icon: "🛡️", text: "Loại người đã có cơ hội mở" });
  if (filters.tin_hieu_trong_ngay) chips.push({ icon: "⏱️", text: `Tín hiệu trong ${filters.tin_hieu_trong_ngay} ngày` });
  if (plan.limit) chips.push({ icon: "🔢", text: `Lấy tối đa ${plan.limit}` });

  return (
    <div className="chips">
      {chips.map(({ icon, text }) => (
        <span className="chip" key={text}>
          <span style={{ fontSize: "12px" }}>{icon}</span> {text}
        </span>
      ))}
    </div>
  );
}

/** Thanh bộ lọc đã lưu dành cho RB (Saved Views) */
function RBSavedViewsBar({
  applied,
  onApply,
}: {
  applied: SearchFilters;
  onApply: (filters: SearchFilters) => void;
}) {
  const queryClient = useQueryClient();
  const [naming, setNaming] = useState(false);
  const [name, setName] = useState("");

  const views = useQuery({
    queryKey: ["saved-views", "rb"],
    queryFn: () => api.savedViews("rb"),
    retry: false,
  });

  function refresh() {
    queryClient.invalidateQueries({ queryKey: ["saved-views", "rb"] });
  }

  const save = useMutation({
    mutationFn: () =>
      api.saveView(
        "rb",
        name.trim(),
        applied as unknown as Record<string, unknown>,
      ),
    onSuccess: () => {
      setNaming(false);
      setName("");
      refresh();
    },
  });

  const remove = useMutation({
    mutationFn: (id: number) => api.deleteSavedView(id),
    onSuccess: refresh,
  });

  function apply(view: SavedView) {
    onApply(view.filters as SearchFilters);
    api.reopenSavedView(view.id).then(refresh);
  }

  const hasFilter = Object.keys(applied).some(
    (key) => key !== "order" && applied[key as keyof SearchFilters],
  );
  const rows = views.data?.results ?? [];

  if (rows.length === 0 && !naming && !hasFilter) return null;

  return (
    <div className="saved-views-modern" style={{ marginBottom: "16px" }}>
      <div className="saved-views-label">
        <span>🔖 Bộ lọc RB đã lưu:</span>
      </div>
      <div className="saved-views-chips">
        {rows.map((view) => (
          <span key={view.id} className="chip saved-view-chip-modern">
            <button
              type="button"
              className="link-view"
              onClick={() => apply(view)}
            >
              {view.name}
            </button>
            <button
              type="button"
              className="remove-btn"
              title="Xoá bộ lọc này"
              onClick={() => remove.mutate(view.id)}
            >
              ×
            </button>
          </span>
        ))}

        {naming ? (
          <span className="save-view-inline-input">
            <input
              className="input-text-compact"
              autoFocus
              placeholder="Tên bộ lọc..."
              value={name}
              onChange={(event) => setName(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter" && name.trim()) save.mutate();
                if (event.key === "Escape") setNaming(false);
              }}
            />
            <button
              type="button"
              className="btn btn-primary btn-sm"
              disabled={!name.trim() || save.isPending}
              onClick={() => save.mutate()}
            >
              Lưu
            </button>
            <button
              type="button"
              className="btn btn-ghost btn-sm"
              onClick={() => setNaming(false)}
            >
              Huỷ
            </button>
          </span>
        ) : (
          hasFilter && (
            <button
              type="button"
              className="btn-add-saved-view"
              onClick={() => setNaming(true)}
            >
              + Lưu bộ lọc này
            </button>
          )
        )}
      </div>
    </div>
  );
}

function Field({
  label,
  hint,
  icon,
  ...props
}: {
  label: string;
  hint?: string;
  icon?: string;
} & React.InputHTMLAttributes<HTMLInputElement>) {
  return (
    <div className="filter-col">
      <label className="filter-label">
        <span>
          {icon && <span className="field-icon">{icon}</span>} {label}
        </span>
      </label>
      <input className="input-text filter-input" {...props} />
      {hint && <small className="filter-hint">{hint}</small>}
    </div>
  );
}

export default function ProspectSearch({ initialMode = "ai" }: { initialMode?: "ai" | "loc" }) {
  const qc = useQueryClient();
  const [searchParams] = useSearchParams();
  const tabParam = searchParams.get("tab");
  const { maskSensitiveData, appName, radarAvatarUrl, radarAvatarEmoji } = useCustomTheme();
  const [mode, setMode] = useState<"ai" | "loc">(
    tabParam === "filter" ? "loc" : initialMode
  );
  const [inputText, setInputText] = useState("");
  const { messages, setMessages, threadId, resetConversation, refreshConversations } = useProspectChatState();
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const streamAbortRef = useRef<AbortController | null>(null);
  useEffect(() => () => streamAbortRef.current?.abort(), []);
  const [creatingFor, setCreatingFor] = useState<number | null>(null);
  const [createdMsg, setCreatedMsg] = useState<string | null>(null);
  const [aiViewMode, setAiViewMode] = useState<"cards" | "table">("cards");
  const [isAsking, setIsAsking] = useState(false);
  const [showScrollBottom, setShowScrollBottom] = useState(false);

  useEffect(() => {
    if (tabParam === "filter") {
      setMode("loc");
    } else if (tabParam === "prospects") {
      setMode("ai");
    }
  }, [tabParam]);

  const handleStopGenerating = () => {
    if (streamAbortRef.current) {
      streamAbortRef.current.abort();
    }
    setIsAsking(false);
    setMessages((prev) =>
      prev.map((m) => (m.isPending ? { ...m, isPending: false } : m))
    );
  };

  useEffect(() => {
    const handleScroll = () => {
      const scrollHeight = document.documentElement.scrollHeight || document.body.scrollHeight;
      const scrollTop = window.scrollY || document.documentElement.scrollTop;
      const clientHeight = window.innerHeight;
      const distanceFromBottom = scrollHeight - (scrollTop + clientHeight);
      setShowScrollBottom(distanceFromBottom > 140);
    };
    window.addEventListener("scroll", handleScroll, { passive: true });
    return () => window.removeEventListener("scroll", handleScroll);
  }, []);

  useEffect(() => {
    const onNewChat = () => resetConversation();
    window.addEventListener("radar:new-chat", onNewChat);
    return () => window.removeEventListener("radar:new-chat", onNewChat);
  }, [resetConversation]);

  useEffect(() => {
    const el = messagesEndRef.current;
    if (el && typeof el.scrollIntoView === "function") el.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  // Filter Mode State
  const [draft, setDraft] = useState<SearchFilters>({ order: "relevance" });
  const [appliedFilters, setAppliedFilters] = useState<SearchFilters>({ order: "relevance" });
  const [hasSearched, setHasSearched] = useState(false);
  const [filterViewMode, setFilterViewMode] = useState<"cards" | "table">("cards");
  const [page, setPage] = useState(0);

  const facets = useQuery({
    queryKey: ["talent-facets"],
    queryFn: api.talentFacets,
  });

  const ask = useMutation({
    mutationFn: ({ q, history, clientTurnId }: { q: string; history: HistoryTurn[]; clientTurnId: string }) =>
      api.rbProspects(q, history, threadId, clientTurnId),
  });

  const searchResults = useQuery({
    queryKey: ["rb-smart-filter-search", appliedFilters, page],
    queryFn: () => api.talentSearch(appliedFilters, 30, page * 30),
    enabled: mode === "loc" && hasSearched,
  });

  const createOpportunity = useMutation({
    mutationFn: ({ personId, product, need }: { personId: number; product: string; need: string }) =>
      api.rbOpportunityCreate({ person_id: personId, product, need }),
    onSuccess: () => {
      setCreatedMsg("✓ Đã tạo cơ hội mới vào Growth Radar thành công!");
      qc.invalidateQueries({ queryKey: ["rb-customer-tasks"] });
      qc.invalidateQueries({ queryKey: ["rb-opportunities"] });
      setTimeout(() => setCreatedMsg(null), 4000);
      setCreatingFor(null);
    },
  });

  const submitAI = (text: string) => {
    const cleaned = text.trim();
    if (!cleaned || isAsking || ask.isPending) return;
    setIsAsking(true);

    // Lịch sử cuộc trò chuyện để AI hỏi tiếp (refine) thay vì hỏi độc lập —
    // lấy tiêu chí mỗi lượt AI đã trả lời trước đó, KHÔNG tính lượt vừa gửi.
    const history: HistoryTurn[] = messages
      .filter((m) => m.sender === "ai" && m.data && !m.isPending)
      .slice(-8)
      .map((m) => ({ criteria: m.data!.criteria as unknown as Record<string, unknown>,
        question: m.data!.question, answer: m.text }));

    const clientTurnId = globalThis.crypto?.randomUUID?.() ?? `turn-${Date.now()}`;
    const userMsgId = `user-${Date.now()}`;
    const aiMsgId = `ai-${Date.now() + 1}`;
    const timeStr = new Date().toLocaleTimeString("vi-VN", { hour: "2-digit", minute: "2-digit" });

    setMessages((prev) => [
      ...prev,
      { id: userMsgId, sender: "user", text: cleaned, timestamp: timeStr },
      {
        id: aiMsgId,
        sender: "ai",
        text: "Radar đang suy nghĩ & phân tích khách hàng tiềm năng...",
        timestamp: timeStr,
        isPending: true,
      },
    ]);
    setInputText("");

    const patchMsg = (patch: Partial<ProspectChatMessage>) =>
      setMessages((prev) => prev.map((m) => (m.id === aiMsgId ? { ...m, ...patch } : m)));

    const TOOL_LABEL: Record<string, string> = {
      read_allowed_evidence: "Đọc bằng chứng hồ sơ",
      remember_proposal: "Đề xuất ghi nhớ",
      feedback: "Ghi nhận đánh giá",
      compare_candidates: "So sánh ứng viên",
      canonical_lookup: "Chuẩn hoá giá trị",
      fact_provenance: "Truy nguồn gốc dữ liệu",
  draft_outreach: "Soạn nháp tiếp cận",
  enrich_company_from_web: "Tra thông tin công ty (web)",
    };
    const conversationData = (answer: string, reasoning: string,
      provider = "", model = "", sources: WebSource[] = [],
      tools: ToolCallTrace[] = []): ProspectResponse => ({
      mode: "conversation", answer, question: cleaned, provider, model,
      reasoning_content: reasoning || undefined,
      sources: sources.length ? sources : undefined,
      tools: tools.length ? tools : undefined,
      trace: tools.map((t) => ({
        label: TOOL_LABEL[t.name] ?? `Tool: ${t.name}`,
        detail: t.ok ? "" : `lỗi: ${t.error ?? ""}`,
      })),
      criteria: {} as ProspectCriteria, criteria_from: "llm", error: "",
      count: 0, results: [],
    });

    const runAskStream = async () => {
      const controller = new AbortController();
      streamAbortRef.current = controller;
      let answer = "";
      let reasoning = "";
      let sources: WebSource[] = [];
      let tools: ToolCallTrace[] = [];
      try {
        for await (const ev of api.assistantStream(
          { q: cleaned, surface: "prospect", conversation_id: threadId,
            client_turn_id: clientTurnId, history },
          controller.signal,
        )) {
          if (ev.event === "route") { void runEvidenceAsk(); return; }
          if (ev.event === "thinking") {
            reasoning += String(ev.data.text ?? "");
            patchMsg({ data: conversationData(answer, reasoning, "", "", sources, tools) });
          } else if (ev.event === "sources") {
            sources = (ev.data.items as WebSource[] | undefined) ?? [];
            patchMsg({ data: conversationData(answer, reasoning, "", "", sources, tools) });
          } else if (ev.event === "tool") {
            tools = [...tools, ev.data as unknown as ToolCallTrace];
            patchMsg({ data: conversationData(answer, reasoning, "", "", sources, tools) });
          } else if (ev.event === "answer") {
            answer += String(ev.data.text ?? "");
            patchMsg({ text: answer || "Radar đang suy nghĩ...",
              data: conversationData(answer, reasoning, "", "", sources, tools) });
          } else if (ev.event === "error") {
            throw new ApiError(0, String(ev.data.text ?? "Lỗi khi stream câu trả lời."));
          } else if (ev.event === "done") {
            const finalAnswer = String(ev.data.answer ?? answer) || answer;
            const finalSources = (ev.data.sources as WebSource[] | undefined) ?? sources;
            const finalTools = (ev.data.tools as ToolCallTrace[] | undefined) ?? tools;
            patchMsg({ isPending: false, text: finalAnswer,
              data: conversationData(finalAnswer, reasoning,
                String(ev.data.provider ?? ""), String(ev.data.model ?? ""),
                finalSources, finalTools) });
            void refreshConversations();
          }
        }
      } catch (err: any) {
        if (err?.name === "AbortError" || streamAbortRef.current?.signal?.aborted) {
          patchMsg({ isPending: false, text: answer ? `${answer}\n\n*(Đã dừng trả lời)*` : `*(Đã dừng)*` });
        } else {
          if (!answer) { runAsk(); return; }
          const detail = err instanceof ApiError ? err.message : "Mất kết nối khi đang trả lời.";
          patchMsg({ isPending: false, text: `${answer}\n\n⚠️ ${detail}` });
        }
      } finally {
        streamAbortRef.current = null;
        setIsAsking(false);
      }
    };

    // Growth Answer Engine (`/rb/ask/`): câu trả lời có dẫn chứng + danh sách khách
    // xếp theo mức đáng ưu tiên + hành động do CODE chọn. Đường 8 khoá cũ
    // (`runAsk`) KHÔNG bị xoá: nó là dự phòng khi endpoint mới hỏng TRƯỚC khi có
    // chữ nào — thà trả một danh sách lọc thô còn hơn một ô chat trống.
    const runEvidenceAsk = async () => {
      const controller = new AbortController();
      streamAbortRef.current = controller;
      let answer = "";
      let steps: Array<{ label: string; detail: string }> = [];
      let plan: ProspectAnswerPlan | undefined;
      const answerData = (text: string, people: ProspectAnswerPerson[] = [],
        provider = "", model = ""): ProspectResponse => ({
        // Chưa có kế hoạch = chưa phải lượt tìm kiếm (hoặc là câu lệnh): hiện như
        // hội thoại, để không thoáng hiện thẻ tiêu chí rỗng và ô "chưa có khách nào".
        mode: plan ? "answer" : "conversation", answer: text, question: cleaned, provider, model,
        trace: steps, answer_plan: plan,
        criteria: {} as ProspectCriteria, criteria_from: "llm", error: "",
        count: people.length, results: people.map(prospectRowFromAnswer),
      });
      try {
        for await (const ev of api.rbAsk(
          { q: cleaned, conversation_id: threadId, client_turn_id: clientTurnId, history },
          controller.signal,
        )) {
          if (ev.event === "step") {
            const label = String(ev.data.label ?? "");
            const done = ev.data.state === "done";
            const at = steps.findIndex((row) => row.label === label);
            // Nhãn là khoá: cùng nhãn + done thì tick bước cũ, nhãn mới thì mở bước mới.
            if (at >= 0) steps = steps.map((row, i) => (i === at ? { label, detail: done ? "xong" : "" } : row));
            else steps = [...steps, { label, detail: done ? "xong" : "" }];
            patchMsg({ data: answerData(answer) });
          } else if (ev.event === "preamble") {
            // Kế hoạch tới NGAY sau ①, trước khi tìm và đọc — RM thấy hệ thống
            // hiểu câu hỏi thế nào trước khi danh sách xuất hiện.
            plan = (ev.data.plan as ProspectAnswerPlan | undefined) ?? plan;
            if (!answer) patchMsg({ text: String(ev.data.text ?? ""), data: answerData(answer) });
            else patchMsg({ data: answerData(answer) });
          } else if (ev.event === "answer") {
            answer += String(ev.data.text ?? "");
            patchMsg({ text: answer, data: answerData(answer) });
          } else if (ev.event === "revision") {
            // Bản đã sửa sau khi máy chủ kiểm trích dẫn — THAY, không nối thêm.
            answer = String(ev.data.text ?? answer);
            patchMsg({ text: answer, data: answerData(answer) });
          } else if (ev.event === "error") {
            throw new ApiError(0, String(ev.data.text ?? "Lỗi khi trả lời."));
          } else if (ev.event === "done") {
            const people = (ev.data.people as ProspectAnswerPerson[] | undefined) ?? [];
            const trace = (ev.data.trace as { plan?: ProspectAnswerPlan; keeps_last_result?: boolean }
              | undefined) ?? {};
            // Vòng nới có thể đổi kế hoạch sau preamble — bản ở `done` là bản cuối.
            plan = trace.plan ?? plan;
            const finalAnswer = String(ev.data.answer ?? answer) || answer;
            // Bước cuối được gửi ở `active` và không bao giờ có chunk đóng riêng —
            // tự đóng mọi bước còn treo, nếu không thẻ tiến trình quay mãi.
            steps = steps.map((row) => ({ ...row, detail: "xong" }));
            const provider = String(ev.data.provider ?? "");
            const model = String(ev.data.model ?? "");
            // Lượt CÂU LỆNH (soạn nháp, tạo cơ hội) không phải một kết quả tìm kiếm:
            // không có điểm, không có kế hoạch tìm. Hiện nó thành thẻ khách điểm 0
            // kèm "Hệ thống hiểu câu hỏi là…" rỗng là nói sai điều vừa xảy ra.
            patchMsg({ isPending: false, text: finalAnswer,
              data: trace.keeps_last_result
                ? { ...answerData(finalAnswer, [], provider, model), mode: "conversation" }
                : answerData(finalAnswer, people, provider, model) });
            void refreshConversations();
          }
        }
      } catch (err: any) {
        if (err?.name === "AbortError" || streamAbortRef.current?.signal?.aborted) {
          patchMsg({ isPending: false, text: answer ? `${answer}\n\n*(Đã dừng trả lời)*` : `*(Đã dừng)*` });
        } else if (!answer) {
          // Hỏng trước khi có chữ nào → dự phòng sang đường lọc cũ.
          runAsk();
          return;
        } else {
          const detail = err instanceof ApiError ? err.message : "Mất kết nối khi đang trả lời.";
          patchMsg({ isPending: false, text: `${answer}\n\n⚠️ ${detail}` });
        }
      } finally {
        streamAbortRef.current = null;
        setIsAsking(false);
      }
    };

    const runAsk = () => ask.mutate(
      { q: cleaned, history, clientTurnId },
      {
        onSuccess: (data) => {
          setIsAsking(false);
          setMessages((prev) =>
            prev.map((msg) =>
              msg.id === aiMsgId
                ? {
                    ...msg,
                    isPending: false,
                    text: data.mode === "conversation" && data.answer
                      ? data.answer
                      : data.count > 0
                        ? `Tôi đã tìm thấy ${data.count} khách hàng tiềm năng phù hợp với yêu cầu "${cleaned}":`
                        : `Không tìm thấy khách hàng nào phù hợp với yêu cầu "${cleaned}". Bạn có thể thử nới rộng tiêu chí tìm kiếm.`,
                    data,
                  }
                : msg,
            ),
          );
          void refreshConversations();
        },
        onError: (err: Error) => {
          setIsAsking(false);
          setMessages((prev) =>
            prev.map((msg) =>
              msg.id === aiMsgId ? { ...msg, isPending: false, text: `⚠️ Đã có lỗi xảy ra: ${err.message}` } : msg,
            ),
          );
        },
      },
    );

    if (looksConversational(cleaned)) {
      void runAskStream();
    } else {
      void runEvidenceAsk();
    }
  };

  const handleApplyFilters = (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    setAppliedFilters({ ...draft });
    setHasSearched(true);
    setPage(0);
  };

  const applyQuickFilter = (patch: Partial<SearchFilters>) => {
    const updated = { ...draft, ...patch };
    setDraft(updated);
    setAppliedFilters(updated);
    setHasSearched(true);
    setPage(0);
  };

  const resetFilters = () => {
    setDraft({ order: "relevance" });
    setAppliedFilters({ order: "relevance" });
    setHasSearched(false);
    setPage(0);
  };

  const activeFilterCount = Object.keys(appliedFilters).filter(
    (k) => k !== "order" && appliedFilters[k as keyof SearchFilters],
  ).length;

  return (
    <div className="talent-container full-page-ai-glow">
      {/* Dynamic Animated AI Glow Spheres */}
      <div className="ai-ambient-glow">
        <div className="glow-orb orb-1" />
        <div className="glow-orb orb-2" />
        <div className="glow-orb orb-3" />
      </div>

      <div className="talent-content-relative">
        {createdMsg && (
          <div className="talent-success-banner">
            <span>{createdMsg}</span>
          </div>
        )}

        {/* =========================================================
            CHẾ ĐỘ 1: HỎI BẰNG LỜI VỚI AI (COPILOT PROSPECT ENGINE)
            ========================================================= */}
        {mode === "ai" && (
          <div className="copilot-chat-container">
            <div className="radar-conversation-content full-width">
            {messages.length === 0 ? (
              <div className="copilot-welcome-hero">
                <div className="copilot-hero-heading-block">
                  <h1 className="copilot-hero-title">
                    Trợ lý Tìm Kiếm &amp; Bán Chéo <span className="hero-gradient-text">Growth Radar</span>
                  </h1>
                  <p className="copilot-hero-subtitle">
                    Hỗ trợ RM &amp; Sales tìm kiếm khách hàng tiềm năng, cơ hội tài chính và bán chéo sản phẩm qua mô tả tự nhiên.
                  </p>
                </div>

                {/* Hero Command Bar */}
                <div className="hero-command-card">
                  <form
                    onSubmit={(e) => {
                      e.preventDefault();
                      submitAI(inputText);
                    }}
                  >
                    <div className="hero-input-main-row">
                      <textarea
                        className="hero-command-textarea"
                        rows={2}
                        placeholder="Mô tả chân dung khách hàng hoặc nhu cầu tài chính…"
                        value={inputText}
                        onChange={(e) => setInputText(e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === "Enter" && !e.shiftKey) {
                            e.preventDefault();
                            submitAI(inputText);
                          }
                        }}
                      />
                    </div>

                    <div className="hero-command-actions-row">
                      <div className="hero-actions-left">
                        <span className="hero-shortcut-hint">
                          💡 Enter để gửi · Shift+Enter xuống dòng
                        </span>
                      </div>

                      <div className="hero-actions-right">
                        {isAsking || ask.isPending ? (
                          <button
                            type="button"
                            className="copilot-stop-btn"
                            onClick={handleStopGenerating}
                            title="Dừng câu trả lời của AI"
                            aria-label="Dừng câu trả lời"
                          >
                            <span className="stop-icon">⏹</span>
                            <span>Dừng trả lời</span>
                          </button>
                        ) : (
                          <button
                            type="submit"
                            className="hero-submit-btn"
                            disabled={!inputText.trim()}
                            aria-label="Tìm khách hàng"
                            title="Tìm khách hàng"
                          >
                            <span>✨</span>
                            <span>Tìm khách hàng</span>
                          </button>
                        )}
                      </div>
                    </div>
                  </form>
                </div>

                {/* Quick Starter Prompts */}
                <div className="hero-quick-prompts-section">
                  <div className="quick-prompts-label-bar">
                    <span>💡 GỢI Ý TÌM NHANH THEO MẪU:</span>
                  </div>
                  <div className="hero-quick-prompts-grid">
                    {GOI_Y_RB.map((item) => (
                      <button
                        key={item.text}
                        type="button"
                        className="hero-quick-prompt-card"
                        onClick={() => submitAI(item.text)}
                      >
                        <div className="prompt-card-icon-box" style={{ background: "rgba(5, 150, 105, 0.12)", color: "#059669" }}>
                          <span>{item.icon}</span>
                        </div>
                        <div className="prompt-card-text-col">
                          <strong className="prompt-card-heading">{item.title}</strong>
                          <span className="prompt-card-desc">{item.text}</span>
                        </div>
                      </button>
                    ))}
                  </div>
                </div>
              </div>
            ) : (
              <>
                <div className="copilot-chat-stream">
                  {messages.map((msg) => {
                    const ans = msg.data;
                    return (
                      <div key={msg.id} className={`chat-message-row ${msg.sender}`}>
                        <div className={`chat-avatar ${msg.sender === "ai" ? "radar-bot-avatar" : ""}`}>
                          {msg.sender === "user" ? (
                            "👤"
                          ) : radarAvatarUrl ? (
                            <img src={radarAvatarUrl} alt={appName} className="bot-avatar-img" />
                          ) : (
                            <span>{radarAvatarEmoji || "⚡"}</span>
                          )}
                        </div>

                        <div className="chat-bubble-wrapper">
                          <div className="chat-bubble-meta">
                            <span className="chat-author">{msg.sender === "user" ? "Bạn" : `${appName} AI`}</span>
                            {msg.sender === "ai" && ans?.model && (
                              <span
                                className="ai-model-tag"
                                style={{
                                  display: "inline-flex",
                                  alignItems: "center",
                                  gap: "4px",
                                  padding: "1px 8px",
                                  borderRadius: "12px",
                                  fontSize: "11px",
                                  fontWeight: 600,
                                  background: "var(--accent-soft, rgba(16, 185, 129, 0.1))",
                                  color: "var(--accent, #10b981)",
                                  border: "1px solid var(--border)",
                                }}
                              >
                                <span>🤖</span>
                                <span>Mô hình: <code>{ans.model}</code></span>
                              </span>
                            )}
                            <span className="chat-time">{msg.timestamp}</span>
                          </div>

                          <div className={`chat-bubble ${msg.sender}`}>
                            {/* Khi đang chờ xử lý và chưa có nội dung trả về */}
                            {msg.isPending && !ans?.reasoning_content && (!msg.text || msg.text.startsWith("Radar đang suy nghĩ")) ? (
                              <div className="radar-chat-pending-row">
                                <div className="copilot-typing-indicator">
                                  <span className="dot" />
                                  <span className="dot" />
                                  <span className="dot" />
                                </div>
                                <span className="radar-chat-pending-label">Radar đang suy nghĩ...</span>
                              </div>
                            ) : (
                              <>
                                {/* Khối suy nghĩ & lập luận thật của AI */}
                                {msg.sender === "ai" && (
                                  <ThinkingProcess
                                    isPending={msg.isPending}
                                    reasoning={ans?.reasoning_content || ans?.thinking_trace}
                                    trace={ans?.trace}
                                  />
                                )}

                                {/* Nội dung câu trả lời */}
                                {msg.text && !msg.text.startsWith("Radar đang suy nghĩ") && (
                                  <FormattedMarkdown content={msg.text} />
                                )}
                              </>
                            )}

                            {/* Nguồn web khi Radar tra Google */}
                            {msg.sender === "ai" && ans?.sources && ans.sources.length > 0 && (
                              <div className="radar-web-sources">
                                <span className="radar-web-sources-label">🌐 Nguồn tham khảo (Google)</span>
                                <ol>
                                  {ans.sources.map((s, i) => (
                                    <li key={`${s.url}-${i}`}>
                                      <a href={s.url} target="_blank" rel="noopener noreferrer">{s.title || s.url}</a>
                                    </li>
                                  ))}
                                </ol>
                              </div>
                            )}

                            {ans && ans.mode !== "conversation" && (
                              <div
                                className="copilot-ai-response-payload"
                                style={{ display: "flex", flexDirection: "column", gap: "16px" }}
                              >
                                {/* "Tiêu chí luôn hiện ra" áp cho CẢ engine mới: RM phải thấy hệ
                                    thống hiểu câu hỏi thế nào trước khi tin danh sách. Engine mới
                                    không có 8 khoá, nên thẻ hiện kế hoạch của ① bằng lời tự nhiên. */}
                                <section className="prospect-criteria-card">
                                  <div className="prospect-criteria-head" style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: "8px" }}>
                                    <h4 className="prospect-criteria-title">
                                      <span>🎯</span> Hệ thống hiểu câu hỏi của bạn là
                                    </h4>
                                    {ans.mode === "answer" ? (
                                      <span
                                        className={`badge ${ans.answer_plan?.fallback ? "warn" : "ok"}`}
                                        title={ans.answer_plan?.fallback
                                          ? "Mô hình không hiểu được câu hỏi lúc này; hệ thống đang đoán theo từ khoá."
                                          : "Đọc bằng chứng thật: bài đăng, tín hiệu, lịch sử tiếp cận."}
                                      >
                                        {ans.answer_plan?.fallback ? "Dự phòng (đoán theo từ khoá)" : "Đọc bằng chứng"}
                                      </span>
                                    ) : (
                                      <span
                                        className={`badge ${ans.criteria_from === "keyword" ? "warn" : "ok"}`}
                                        title={NGUON_TIEU_CHI[ans.criteria_from]?.giai_thich}
                                      >
                                        {NGUON_TIEU_CHI[ans.criteria_from]?.nhan ?? ans.criteria_from}
                                      </span>
                                    )}
                                    {ans.model && (
                                      <span className="badge ok" style={{ display: "inline-flex", alignItems: "center", gap: "4px" }}>
                                        🤖 Mô hình AI: <code>{ans.provider ? `${ans.provider}/${ans.model}` : ans.model}</code>
                                      </span>
                                    )}
                                  </div>
                                  {ans.mode === "answer"
                                    ? <PlanChips plan={ans.answer_plan} />
                                    : <CriteriaChips criteria={ans.criteria} />}
                                  {ans.mode !== "answer" && ans.criteria_from === "keyword" && (
                                    <p className="muted small" style={{ margin: "8px 0 0", color: "#f59e0b" }}>
                                      {NGUON_TIEU_CHI.keyword.giai_thich}
                                    </p>
                                  )}
                                </section>

                                {ans.results.length === 0 ? (
                                  <div className="empty-results-box" style={{ width: "100%" }}>
                                    <div className="empty-icon">🔍</div>
                                    <h3>
                                      {ans.mode === "answer"
                                        ? "Chưa có khách hàng nào có đủ bằng chứng phù hợp."
                                        : "Không có ai khớp tiêu chí trên. Thử nới bớt một điều kiện."}
                                    </h3>
                                    <p>Thử điều chỉnh câu hỏi mô tả hoặc dùng Bộ lọc Đa chiều để tra cứu rộng hơn.</p>
                                  </div>
                                ) : (
                                  <>
                                    <div className="results-header-toolbar" style={{ margin: "0" }}>
                                      <div className="results-count-badge">
                                        <span>
                                          Tìm thấy <strong>{ans.results.length}</strong> khách hàng tiềm năng{" "}
                                          {ans.mode === "answer" ? "xếp theo mức đáng ưu tiên liên hệ" : "xếp hạng theo AI Match"}
                                        </span>
                                      </div>
                                      <div className="results-actions-right">
                                        <div className="view-mode-toggle">
                                          <button
                                            type="button"
                                            className={`view-btn ${aiViewMode === "cards" ? "active" : ""}`}
                                            onClick={() => setAiViewMode("cards")}
                                            title="Xem dạng thẻ phân tích thông minh"
                                          >
                                            ⊞ Thẻ thông minh
                                          </button>
                                          <button
                                            type="button"
                                            className={`view-btn ${aiViewMode === "table" ? "active" : ""}`}
                                            onClick={() => setAiViewMode("table")}
                                            title="Xem dạng bảng cô đọng"
                                          >
                                            ≡ Bảng dữ liệu
                                          </button>
                                        </div>
                                      </div>
                                    </div>

                                    {aiViewMode === "cards" ? (
                                      <div className="prospect-ai-grid">
                                        {ans.results.map((row) => (
                                          <div key={row.person_id} className="prospect-ai-card">
                                            <div className="prospect-card-top">
                                              <div className="prospect-avatar-meta-group">
                                                <div className="prospect-avatar-circle">
                                                  {(row.display_name || "K")[0]?.toUpperCase()}
                                                </div>
                                                <div className="prospect-meta-info">
                                                  <Link
                                                    to={`/person/${row.person_id}?from=rb`}
                                                    className="prospect-name-link"
                                                    target="_blank"
                                                    rel="noopener noreferrer"
                                                  >
                                                    {row.display_name || `Person #${row.person_id}`}
                                                  </Link>
                                                  <div className="prospect-headline-text">
                                                    {row.occupation || "Khách hàng cá nhân"}
                                                  </div>
                                                  {row.location && (
                                                    <div className="prospect-location-tag">
                                                      <span>📍</span> {row.location}
                                                    </div>
                                                  )}
                                                  {row.action_label && (
                                                    <span
                                                      className="badge ok"
                                                      title="Hành động tiếp theo do hệ thống chọn từ trạng thái liên hệ và lịch sử tiếp cận"
                                                      style={{ alignSelf: "flex-start", marginTop: "4px", fontSize: "11px", fontWeight: 700 }}
                                                    >
                                                      → {row.action_label}
                                                      {typeof row.freshest_days === "number" && (
                                                        <span style={{ fontWeight: 500, marginLeft: 6, opacity: 0.8 }}>
                                                          · tín hiệu {row.freshest_days === 0 ? "hôm nay" : `${row.freshest_days} ngày trước`}
                                                        </span>
                                                      )}
                                                    </span>
                                                  )}
                                                  {row.has_open_opportunity && (
                                                    <span
                                                      className="badge"
                                                      style={{
                                                        alignSelf: "flex-start",
                                                        marginTop: "4px",
                                                        background: "rgba(245, 158, 11, 0.12)",
                                                        color: "#b45309",
                                                        border: "1px solid rgba(245, 158, 11, 0.3)",
                                                        fontSize: "11px",
                                                        fontWeight: 700,
                                                      }}
                                                    >
                                                      Đã có cơ hội mở
                                                    </span>
                                                  )}
                                                </div>
                                              </div>

                                              <div className="prospect-score-box" title="Điểm ưu tiên tổng hợp">
                                                <span className="score-number-big">{Math.round(row.priority_score)}</span>
                                                <span className="score-label-small">Điểm AI</span>
                                              </div>
                                            </div>

                                            {/* 5 Radar Dimension Pills */}
                                            <div className="radar-dimensions-bar">
                                              {(Object.keys(TEN_CHIEU) as Array<keyof ProspectRowScores>).map((key) => (
                                                <span key={key} className="radar-dimension-pill">
                                                  {TEN_CHIEU[key]}: <strong>{Math.round(row.scores[key])}</strong>
                                                </span>
                                              ))}
                                            </div>

                                            {/* Why AI Recommended Bullets */}
                                            <div className="prospect-why-box">
                                              {row.why.slice(0, 3).map((line, index) => (
                                                <div key={index} className="prospect-why-item">{line}</div>
                                              ))}
                                            </div>

                                            {/* Card Footer Actions */}
                                            <div className="prospect-card-bottom">
                                              <Link
                                                className="btn btn-secondary btn-sm"
                                                to={`/person/${row.person_id}?from=rb`}
                                                target="_blank"
                                                rel="noopener noreferrer"
                                              >
                                                Hồ sơ 360° →
                                              </Link>
                                              {creatingFor === row.person_id ? (
                                                <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
                                                  <select
                                                    className="config-select"
                                                    style={{ fontSize: "12px", padding: "4px 8px" }}
                                                    defaultValue={row.product || "credit_card"}
                                                    id={`prod-select-card-${row.person_id}`}
                                                  >
                                                    {PRODUCTS.filter(([p]) => Boolean(p)).map(([code, label]) => (
                                                      <option key={code} value={code}>{label}</option>
                                                    ))}
                                                  </select>
                                                  <button
                                                    type="button"
                                                    className="btn btn-primary btn-sm"
                                                    disabled={createOpportunity.isPending}
                                                    onClick={() => {
                                                      const sel = document.getElementById(
                                                        `prod-select-card-${row.person_id}`,
                                                      ) as HTMLSelectElement;
                                                      createOpportunity.mutate({
                                                        personId: row.person_id,
                                                        product: sel?.value || "credit_card",
                                                        need: `Đề xuất từ Growth Radar: ${ans.question}`,
                                                      });
                                                    }}
                                                  >
                                                    Xác nhận
                                                  </button>
                                                  <button
                                                    type="button"
                                                    className="btn btn-ghost btn-sm"
                                                    onClick={() => setCreatingFor(null)}
                                                  >
                                                    Huỷ
                                                  </button>
                                                </div>
                                              ) : (
                                                <button
                                                  type="button"
                                                  className="btn btn-primary btn-sm"
                                                  onClick={() => setCreatingFor(row.person_id)}
                                                >
                                                  ⚡ Tạo cơ hội
                                                </button>
                                              )}
                                            </div>
                                          </div>
                                        ))}
                                      </div>
                                    ) : (
                                      <div
                                        className="talent-table-wrapper"
                                        style={{ background: "var(--surface)", border: "1px solid var(--border)", borderRadius: "14px", overflow: "hidden" }}
                                      >
                                        <table className="table prospect-table" style={{ margin: 0 }}>
                                          <thead>
                                            <tr>
                                              <th style={{ minWidth: "220px" }}>Khách hàng</th>
                                              <th style={{ minWidth: "180px" }}>Nghề nghiệp / Chức danh</th>
                                              <th className="num" style={{ width: "140px", textAlign: "center" }}>Điểm ưu tiên</th>
                                              <th style={{ minWidth: "260px" }}>Vì sao đề xuất</th>
                                              <th style={{ width: "150px", textAlign: "right" }}>Thao tác</th>
                                            </tr>
                                          </thead>
                                          <tbody>
                                            {ans.results.map((row) => (
                                              <tr key={row.person_id}>
                                                <td>
                                                  <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
                                                    <div
                                                      className="task-avatar"
                                                      style={{
                                                        width: "34px",
                                                        height: "34px",
                                                        fontSize: "13px",
                                                        background: "var(--accent-gradient)",
                                                      }}
                                                    >
                                                      {(row.display_name || "K")[0]?.toUpperCase()}
                                                    </div>
                                                    <div>
                                                      <Link
                                                        to={`/person/${row.person_id}?from=rb`}
                                                        style={{ fontWeight: 700, color: "var(--text)", textDecoration: "none" }}
                                                        target="_blank"
                                                        rel="noopener noreferrer"
                                                      >
                                                        {row.display_name || `Person #${row.person_id}`}
                                                      </Link>
                                                      {row.location && (
                                                        <div className="muted small" style={{ fontSize: "12px" }}>
                                                          📍 {row.location}
                                                        </div>
                                                      )}
                                                      {row.has_open_opportunity && (
                                                        <span
                                                          className="badge"
                                                          style={{
                                                            marginTop: "4px",
                                                            display: "inline-block",
                                                            background: "rgba(245, 158, 11, 0.1)",
                                                            color: "#b45309",
                                                            border: "1px solid rgba(245, 158, 11, 0.3)",
                                                          }}
                                                        >
                                                          Đã có cơ hội mở
                                                        </span>
                                                      )}
                                                    </div>
                                                  </div>
                                                </td>
                                                <td>
                                                  <span style={{ fontWeight: 500, color: "var(--text-secondary)" }}>
                                                    {row.occupation || <span className="muted">Chưa rõ</span>}
                                                  </span>
                                                </td>
                                                <td className="num">
                                                  <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: "2px" }}>
                                                    <span
                                                      style={{
                                                        fontSize: "18px",
                                                        fontWeight: 800,
                                                        color: "#059669",
                                                        lineHeight: 1.2,
                                                      }}
                                                    >
                                                      {Math.round(row.priority_score)}
                                                    </span>
                                                    <div className="muted small" style={{ fontSize: "11px", textAlign: "center" }}>
                                                      {(Object.keys(TEN_CHIEU) as Array<keyof ProspectRowScores>)
                                                        .map((key) => `${TEN_CHIEU[key]} ${Math.round(row.scores[key])}`)
                                                        .join(" · ")}
                                                    </div>
                                                  </div>
                                                </td>
                                                <td className="prospect-why">
                                                  {row.why.slice(0, 3).map((line, index) => (
                                                    <div key={index}>{line}</div>
                                                  ))}
                                                </td>
                                                <td style={{ textAlign: "right" }}>
                                                  {creatingFor === row.person_id ? (
                                                    <div style={{ display: "flex", flexDirection: "column", gap: "4px" }}>
                                                      <select
                                                        className="config-select"
                                                        style={{ fontSize: "11.5px" }}
                                                        defaultValue={row.product || "credit_card"}
                                                        id={`prod-select-table-${row.person_id}`}
                                                      >
                                                        {PRODUCTS.filter(([p]) => Boolean(p)).map(([code, label]) => (
                                                          <option key={code} value={code}>{label}</option>
                                                        ))}
                                                      </select>
                                                      <button
                                                        type="button"
                                                        className="btn btn-primary btn-sm"
                                                        style={{ fontSize: "11px", padding: "3px 8px" }}
                                                        disabled={createOpportunity.isPending}
                                                        onClick={() => {
                                                          const sel = document.getElementById(
                                                            `prod-select-table-${row.person_id}`,
                                                          ) as HTMLSelectElement;
                                                          createOpportunity.mutate({
                                                            personId: row.person_id,
                                                            product: sel?.value || "credit_card",
                                                            need: `Đề xuất từ Growth Radar: ${ans.question}`,
                                                          });
                                                        }}
                                                      >
                                                        Xác nhận
                                                      </button>
                                                    </div>
                                                  ) : (
                                                    <button
                                                      type="button"
                                                      className="btn btn-secondary btn-sm"
                                                      style={{ fontSize: "11.5px", padding: "4px 10px", whiteSpace: "nowrap" }}
                                                      onClick={() => setCreatingFor(row.person_id)}
                                                    >
                                                      ⚡ Tạo cơ hội
                                                    </button>
                                                  )}
                                                </td>
                                              </tr>
                                            ))}
                                          </tbody>
                                        </table>
                                      </div>
                                    )}
                                  </>
                                )}
                              </div>
                            )}
                          </div>
                        </div>
                      </div>
                    );
                  })}
                  <div ref={messagesEndRef} />
                </div>

                {/* Khung Chat Input Bar cố định dưới luồng chat */}
                <div className="copilot-input-bar-wrapper">
                  <div className="copilot-input-box">
                    <textarea
                      rows={1}
                      className="copilot-textarea"
                      placeholder="Mô tả chân dung khách hàng hoặc nhu cầu tài chính…"
                      value={inputText}
                      onChange={(e) => {
                        setInputText(e.target.value);
                        e.target.style.height = "auto";
                        e.target.style.height = `${Math.min(e.target.scrollHeight, 120)}px`;
                      }}
                      onKeyDown={(e) => {
                        if (e.key === "Enter" && !e.shiftKey) {
                          e.preventDefault();
                          submitAI(inputText);
                        }
                      }}
                      disabled={isAsking || ask.isPending}
                    />
                    {isAsking || ask.isPending ? (
                      <button
                        type="button"
                        className="copilot-stop-btn"
                        onClick={handleStopGenerating}
                        title="Dừng câu trả lời của AI"
                        aria-label="Dừng câu trả lời"
                      >
                        <span className="stop-icon">⏹</span>
                        <span>Dừng</span>
                      </button>
                    ) : (
                      <button
                        type="button"
                        className="copilot-send-btn"
                        onClick={() => submitAI(inputText)}
                        disabled={!inputText.trim()}
                        title="Gửi câu hỏi"
                        aria-label="Gửi câu hỏi"
                      >
                        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                          <line x1="12" y1="19" x2="12" y2="5" />
                          <polyline points="5 12 12 5 19 12" />
                        </svg>
                      </button>
                    )}
                  </div>
                  {showScrollBottom && (
                    <button
                      type="button"
                      className="copilot-scroll-bottom-btn"
                      onClick={() => messagesEndRef.current?.scrollIntoView({ behavior: "smooth" })}
                      title="Cuộn xuống tin nhắn mới nhất"
                      aria-label="Cuộn xuống dưới cùng"
                    >
                      <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                        <path d="M12 5v14M5 12l7 7 7-7" />
                      </svg>
                      <span>Xuống dưới cùng</span>
                    </button>
                  )}
                  <div className="copilot-footer-hint">
                    <span>Radar AI có thể đưa ra thông tin chưa chính xác. Vui lòng kiểm tra lại các nội dung quan trọng.</span>
                    <button
                      type="button"
                      className="link small"
                      onClick={resetConversation}
                      style={{ marginLeft: "10px", whiteSpace: "nowrap" }}
                    >
                      🔄 Bắt đầu đoạn chat mới
                    </button>
                  </div>
                </div>
              </>
            )}
              </div>
            </div>
        )}

        {/* =========================================================
            CHẾ ĐỘ 2: BỘ LỌC ĐA CHIỀU & DANH BẠ KHÁCH HÀNG
            ========================================================= */}
        {mode === "loc" && (
          <div className="talent-filter-workspace">
            {/* Saved Views Bar */}
            <RBSavedViewsBar
              applied={appliedFilters}
              onApply={(f) => {
                setDraft(f);
                setAppliedFilters(f);
                setHasSearched(true);
                setPage(0);
              }}
            />

            {/* Main Search & Smart Filter Panel */}
            <div className="search-filter-card">
              <form onSubmit={handleApplyFilters}>
                {/* Main search bar */}
                <div className="search-main-row">
                  <div className="search-input-wrapper">
                    <span className="search-icon">🔍</span>
                    <input
                      type="search"
                      className="search-main-input"
                      placeholder="Tìm theo tên khách hàng, chức danh, công ty, nhu cầu tài chính…"
                      value={draft.q ?? ""}
                      onChange={(event) => setDraft((prev) => ({ ...prev, q: event.target.value }))}
                    />
                  </div>
                  <button type="submit" className="btn btn-primary">
                    Tìm kiếm
                  </button>
                  {(activeFilterCount > 0 || hasSearched) && (
                    <button
                      type="button"
                      className="btn btn-ghost"
                      onClick={resetFilters}
                    >
                      Xoá bộ lọc ({activeFilterCount})
                    </button>
                  )}
                </div>

                {/* Quick Filter Tag Buttons */}
                <div className="quick-tags-row">
                  <span className="quick-tags-title">Bộ lọc nhanh:</span>
                  <button
                    type="button"
                    className={`quick-tag-btn ${draft.location === "Hà Nội" ? "active" : ""}`}
                    onClick={() =>
                      applyQuickFilter({
                        location: draft.location === "Hà Nội" ? "" : "Hà Nội",
                      })
                    }
                  >
                    📍 Hà Nội
                  </button>
                  <button
                    type="button"
                    className={`quick-tag-btn ${draft.location === "Hồ Chí Minh" ? "active" : ""}`}
                    onClick={() =>
                      applyQuickFilter({
                        location: draft.location === "Hồ Chí Minh" ? "" : "Hồ Chí Minh",
                      })
                    }
                  >
                    📍 TP. Hồ Chí Minh
                  </button>
                  <button
                    type="button"
                    className={`quick-tag-btn ${draft.min_years === "5" ? "active" : ""}`}
                    onClick={() =>
                      applyQuickFilter({
                        min_years: draft.min_years === "5" ? undefined : "5",
                      })
                    }
                  >
                    💼 VIP / Priority
                  </button>
                  <button
                    type="button"
                    className={`quick-tag-btn ${draft.product === "credit_card" ? "active" : ""}`}
                    onClick={() =>
                      applyQuickFilter({
                        product: draft.product === "credit_card" ? "" : "credit_card",
                      })
                    }
                  >
                    💳 Nhu cầu Thẻ tín dụng
                  </button>
                  <button
                    type="button"
                    className={`quick-tag-btn ${draft.product === "mortgage" ? "active" : ""}`}
                    onClick={() =>
                      applyQuickFilter({
                        product: draft.product === "mortgage" ? "" : "mortgage",
                      })
                    }
                  >
                    🏡 Nhu cầu Vay mua nhà
                  </button>
                  <button
                    type="button"
                    className={`quick-tag-btn ${draft.has_phone ? "active" : ""}`}
                    onClick={() =>
                      applyQuickFilter({ has_phone: !draft.has_phone })
                    }
                  >
                    📞 Có SĐT
                  </button>
                  <button
                    type="button"
                    className={`quick-tag-btn ${draft.has_email ? "active" : ""}`}
                    onClick={() =>
                      applyQuickFilter({ has_email: !draft.has_email })
                    }
                  >
                    ✉️ Có Email
                  </button>
                  <span
                    className="boolean-badge-hint"
                    title="Hỗ trợ toán tử AND, OR, NOT, dấu ngoặc kép & ngoặc đơn"
                  >
                    ⚡ Boolean Search ON
                  </span>
                </div>

                {/* Detailed Criteria Grid */}
                <div className="filter-criteria-grid">
                  <Field
                    label="Kỹ năng / Nghề nghiệp"
                    icon="🛠️"
                    placeholder="VD: Kinh doanh OR Quản lý OR IT"
                    value={draft.skills ?? ""}
                    onChange={(event) => setDraft((prev) => ({ ...prev, skills: event.target.value }))}
                  />
                  <Field
                    label="Chức danh / Cấp bậc"
                    icon="💼"
                    placeholder='VD: (Giám đốc OR Trưởng phòng) NOT "Thực tập"'
                    value={draft.title ?? ""}
                    onChange={(event) => setDraft((prev) => ({ ...prev, title: event.target.value }))}
                  />
                  <Field
                    label="Khu vực / Tỉnh thành"
                    icon="📍"
                    placeholder="VD: Hà Nội OR Hồ Chí Minh"
                    value={draft.location ?? ""}
                    onChange={(event) => setDraft((prev) => ({ ...prev, location: event.target.value }))}
                  />
                  <Field
                    label="Doanh nghiệp / Nơi làm việc"
                    icon="🏢"
                    placeholder="VD: Viettel OR FPT OR Vingroup"
                    value={draft.company ?? ""}
                    onChange={(event) => setDraft((prev) => ({ ...prev, company: event.target.value }))}
                  />
                  <div className="filter-col-group">
                    <label className="filter-label">Sản phẩm quan tâm</label>
                    <select
                      className="select-dropdown"
                      value={draft.product ?? ""}
                      onChange={(event) => setDraft((prev) => ({ ...prev, product: event.target.value }))}
                    >
                      {PRODUCTS.map(([code, label]) => (
                        <option key={code} value={code}>{label}</option>
                      ))}
                    </select>
                  </div>
                  <div className="filter-col-group">
                    <label className="filter-label">Trạng thái khách hàng</label>
                    <select
                      className="select-dropdown"
                      value={draft.lead_status ?? ""}
                      onChange={(event) => setDraft((prev) => ({ ...prev, lead_status: event.target.value }))}
                    >
                      <option value="">Tất cả trạng thái</option>
                      {(facets.data?.lead_statuses ?? []).map((row) => (
                        <option key={row.value} value={row.value}>{row.label}</option>
                      ))}
                    </select>
                  </div>
                  <div className="filter-col-group">
                    <label className="filter-label">Nhóm khách hàng &amp; Pool</label>
                    <select
                      className="select-dropdown"
                      value={draft.pool ?? ""}
                      onChange={(event) => setDraft((prev) => ({ ...prev, pool: event.target.value }))}
                    >
                      <option value="">Tất cả nhóm khách hàng</option>
                      {(facets.data?.pools ?? []).map((row) => (
                        <option key={row.id} value={row.id}>
                          {row.name} ({row.member_count})
                        </option>
                      ))}
                    </select>
                  </div>
                  <div className="filter-col-group">
                    <label className="filter-label">RM Phụ trách</label>
                    <select
                      className="select-dropdown"
                      value={draft.owner ?? ""}
                      onChange={(event) => setDraft((prev) => ({ ...prev, owner: event.target.value }))}
                    >
                      <option value="">Tất cả RM</option>
                      {(facets.data?.owners ?? []).map((row) => (
                        <option key={row.id} value={row.id}>{row.name}</option>
                      ))}
                    </select>
                  </div>
                  <div className="filter-col-group">
                    <label className="filter-label">
                      <span className="field-icon">⏳</span> Kinh nghiệm / Độ tuổi
                    </label>
                    <div className="years-range-inputs">
                      <input
                        className="input-text filter-input"
                        type="number"
                        min={0}
                        placeholder="Từ"
                        value={draft.min_years ?? ""}
                        onChange={(event) => setDraft((prev) => ({ ...prev, min_years: event.target.value }))}
                      />
                      <input
                        className="input-text filter-input"
                        type="number"
                        min={0}
                        placeholder="Đến"
                        value={draft.max_years ?? ""}
                        onChange={(event) => setDraft((prev) => ({ ...prev, max_years: event.target.value }))}
                      />
                    </div>
                  </div>
                </div>

                {/* Toggles & Sắp xếp */}
                <div className="filter-bottom-bar">
                  <div className="filter-toggles-group">
                    <label className="checkbox-pill">
                      <input
                        type="checkbox"
                        checked={!!draft.has_email}
                        onChange={(event) => setDraft((prev) => ({ ...prev, has_email: event.target.checked }))}
                      />
                      <span>Có Email</span>
                    </label>
                    <label className="checkbox-pill">
                      <input
                        type="checkbox"
                        checked={!!draft.has_phone}
                        onChange={(event) => setDraft((prev) => ({ ...prev, has_phone: event.target.checked }))}
                      />
                      <span>Có Số điện thoại</span>
                    </label>
                  </div>

                  <div className="filter-sort-group">
                    <label className="sort-label">Sắp xếp theo:</label>
                    <select
                      className="select-dropdown"
                      value={draft.order ?? "relevance"}
                      onChange={(event) => setDraft((prev) => ({ ...prev, order: event.target.value }))}
                    >
                      <option value="relevance">🌟 Phù hợp nhất</option>
                      <option value="newest">📅 Mới cập nhật nhất</option>
                      <option value="oldest">⏳ Cũ nhất</option>
                      <option value="name">🔤 Theo bảng chữ cái tên</option>
                    </select>
                  </div>
                </div>
              </form>
            </div>

            {/* Trạng thái ban đầu: Chưa thực hiện tìm kiếm */}
            {!hasSearched && (
              <div className="talent-search-initial-card">
                <div className="initial-card-icon" style={{ background: "rgba(5, 150, 105, 0.12)", color: "#059669" }}>💼</div>
                <h3 className="initial-card-title">Kho Dữ Liệu Khách Hàng Tiềm Năng &amp; Bán Chéo</h3>
                <p className="initial-card-desc">
                  Nhập từ khoá tìm kiếm, chọn các bộ lọc nhanh ở trên hoặc thiết lập tiêu chí chuyên sâu rồi bấm <strong>Tìm kiếm</strong> để bắt đầu tra cứu.
                </p>
                <div className="initial-quick-actions">
                  <button
                    type="button"
                    className="btn btn-secondary btn-sm"
                    onClick={() => applyQuickFilter({ location: "Hà Nội" })}
                  >
                    📍 Khách hàng tại Hà Nội
                  </button>
                  <button
                    type="button"
                    className="btn btn-secondary btn-sm"
                    onClick={() => applyQuickFilter({ location: "Hồ Chí Minh" })}
                  >
                    📍 Khách hàng tại TP. HCM
                  </button>
                  <button
                    type="button"
                    className="btn btn-secondary btn-sm"
                    onClick={() => applyQuickFilter({ product: "credit_card" })}
                  >
                    💳 Nhu cầu Thẻ tín dụng
                  </button>
                  <button
                    type="button"
                    className="btn btn-primary btn-sm"
                    onClick={() => {
                      setAppliedFilters(draft);
                      setHasSearched(true);
                    }}
                  >
                    🚀 Khám phá toàn bộ danh bạ
                  </button>
                </div>
              </div>
            )}

            {/* Results Section: Chỉ hiển thị khi hasSearched === true */}
            {hasSearched && (
              <>
                {searchResults.error && (
                  <div className="error-box" role="alert">
                    Không tải được kết quả: {String(searchResults.error)}
                  </div>
                )}

                <div className="results-header-toolbar">
                  <div className="results-count-badge">
                    {searchResults.isFetching ? (
                      <span className="loading-text">
                        <span className="spinner-mini" /> Đang tra cứu danh bạ khách hàng…
                      </span>
                    ) : (
                      <span>
                        Tìm thấy <strong>{(searchResults.data?.count ?? 0).toLocaleString("vi-VN")}</strong> khách hàng tiềm năng
                      </span>
                    )}
                    {searchResults.data && searchResults.data.count > 30 && (
                      <nav className="pagination" aria-label="Phân trang kết quả">
                        <button
                          type="button"
                          className="btn btn-secondary btn-sm"
                          disabled={page === 0 || searchResults.isFetching}
                          onClick={() => setPage((value) => Math.max(0, value - 1))}
                        >
                          ← Trang trước
                        </button>
                        <span>
                          Trang {page + 1} / {Math.ceil(searchResults.data.count / 30)}
                        </span>
                        <button
                          type="button"
                          className="btn btn-secondary btn-sm"
                          disabled={(page + 1) * 30 >= searchResults.data.count || searchResults.isFetching}
                          onClick={() => setPage((value) => value + 1)}
                        >
                          Trang sau →
                        </button>
                      </nav>
                    )}
                  </div>

                  <div className="results-actions-right">
                    <div className="view-mode-toggle">
                      <button
                        type="button"
                        className={`view-btn ${filterViewMode === "cards" ? "active" : ""}`}
                        onClick={() => setFilterViewMode("cards")}
                        title="Xem dạng thẻ chi tiết"
                      >
                        ⊞ Thẻ
                      </button>
                      <button
                        type="button"
                        className={`view-btn ${filterViewMode === "table" ? "active" : ""}`}
                        onClick={() => setFilterViewMode("table")}
                        title="Xem dạng bảng cô đọng"
                      >
                        ≡ Bảng
                      </button>
                    </div>

                    {searchResults.data && searchResults.data.results.length > 0 && (
                      <a
                        className="btn btn-secondary btn-sm"
                        href={api.talentExportUrl(appliedFilters)}
                        download
                      >
                        ⬇ Xuất CSV
                      </a>
                    )}
                  </div>
                </div>

                {filterViewMode === "cards" ? (
                  <div className="talent-cards-grid">
                    {(searchResults.data?.results ?? []).map((card: TalentCard) => (
                      <div key={card.id} className="talent-card-modern" style={{ display: "flex", flexDirection: "column" }}>
                        <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: "10px", width: "100%" }}>
                          <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
                            <div
                              className="talent-avatar-modern"
                              style={{ background: "var(--accent-gradient)" }}
                            >
                              {(card.display_name || "K")[0]?.toUpperCase()}
                            </div>
                            <div>
                              <Link
                                to={`/person/${card.id}?from=rb`}
                                style={{ fontWeight: 700, fontSize: "15px", color: "var(--text)", textDecoration: "none" }}
                                target="_blank"
                                rel="noopener noreferrer"
                              >
                                {card.display_name || `Person #${card.id}`}
                              </Link>
                              <div className="talent-title" style={{ marginTop: "2px" }}>
                                <span className="title-text">{card.headline || "Khách hàng cá nhân"}</span>
                              </div>
                            </div>
                          </div>
                        </div>

                        <div className="talent-meta" style={{ marginTop: "8px" }}>
                          {card.location && <span className="meta-item">📍 {card.location}</span>}
                          {card.primary_phone && (
                            <span className="meta-item">📞 {maskSensitiveData ? `${card.primary_phone.slice(0, 4)}***` : card.primary_phone}</span>
                          )}
                          {card.primary_email && (
                            <span className="meta-item">✉️ {maskSensitiveData ? `${card.primary_email.slice(0, 2)}***` : card.primary_email}</span>
                          )}
                        </div>

                        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", borderTop: "1px solid var(--border)", paddingTop: "10px", marginTop: "12px", width: "100%" }}>
                          <Link
                            className="btn btn-secondary btn-sm"
                            to={`/person/${card.id}?from=rb`}
                            target="_blank"
                            rel="noopener noreferrer"
                          >
                            Hồ sơ 360° →
                          </Link>
                          <button
                            type="button"
                            className="btn btn-primary btn-sm"
                            onClick={() =>
                              createOpportunity.mutate({
                                personId: card.id,
                                product: draft.product || "credit_card",
                                need: `Tạo từ bộ lọc RB: ${card.headline || ""}`,
                              })
                            }
                          >
                            ⚡ Tạo cơ hội
                          </button>
                        </div>
                      </div>
                    ))}

                    {searchResults.data && searchResults.data.results.length === 0 && (
                      <div className="empty-results-box">
                        <div className="empty-icon">🔍</div>
                        <h3>Không tìm thấy khách hàng phù hợp</h3>
                        <p>Thử nới lỏng tiêu chí lọc để tìm kiếm rộng hơn.</p>
                      </div>
                    )}
                  </div>
                ) : (
                  <div className="talent-table-wrapper">
                    <table className="talent-modern-table">
                      <thead>
                        <tr>
                          <th>Khách hàng</th>
                          <th>Chức danh &amp; Nơi làm việc</th>
                          <th>Khu vực &amp; Liên hệ</th>
                          <th style={{ textAlign: "right" }}>Thao tác</th>
                        </tr>
                      </thead>
                      <tbody>
                        {(searchResults.data?.results ?? []).map((card: TalentCard) => (
                          <tr key={card.id} className="talent-table-row">
                            <td className="table-col-name">
                              <Link
                                to={`/person/${card.id}?from=rb`}
                                className="table-name-link"
                                target="_blank"
                                rel="noopener noreferrer"
                              >
                                <strong>{card.display_name || `Person #${card.id}`}</strong>
                              </Link>
                            </td>
                            <td className="table-col-title">
                              <div>{card.headline || "Khách hàng cá nhân"}</div>
                            </td>
                            <td className="table-col-meta">
                              <div>{card.location || "—"}</div>
                              <small className="muted">{card.primary_phone || card.primary_email || "—"}</small>
                            </td>
                            <td style={{ textAlign: "right" }}>
                              <button
                                type="button"
                                className="btn btn-primary btn-sm"
                                onClick={() =>
                                  createOpportunity.mutate({
                                    personId: card.id,
                                    product: draft.product || "credit_card",
                                    need: `Tạo từ bộ lọc RB: ${card.headline || ""}`,
                                  })
                                }
                              >
                                ⚡ Tạo cơ hội
                              </button>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                    {searchResults.data && searchResults.data.results.length === 0 && (
                      <div className="empty-results-box">
                        <p>Không có kết quả nào khớp với bộ lọc.</p>
                      </div>
                    )}
                  </div>
                )}
              </>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
