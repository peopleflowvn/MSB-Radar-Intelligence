import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import React, { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import {
  api,
  ProspectAnswerPerson,
  ProspectAnswerPlan,
  prospectRowFromAnswer,
  ProspectRow,
  SavedView,
  SearchFilters,
  TalentCard,
} from "./api";
import { useCustomTheme } from "./CustomThemeContext";
import { useProspectChatState, useRbFilterState } from "./searchPersistence";
import AnswerView, { AnswerTurn } from "./AnswerView";
import { inferFollowUpQuestions } from "./followUpInference";
import StepTimeline from "./StepTimeline";
import CopilotChat, { waitingHint } from "./CopilotChat";

/**
 * Tìm prospect bằng ngôn ngữ tự nhiên & Bộ lọc thông minh (RB Radar).
 *
 * Thiết kế tinh gọn, hiện đại và chuẩn mực:
 * 1. "✨ Hỏi & Tìm khách hàng với AI": Trợ lý Copilot thông minh với Hero Command Bar, Thẻ gợi ý nhanh & Thẻ kết quả đa chiều.
 * 2. "⚡ Bộ lọc Đa chiều & Danh bạ Khách hàng": Lọc đa chiều cho RM, hỗ trợ Saved Views, không tải sẵn 50 khách khi chưa tìm kiếm.
 */

const GOI_Y_RB = [
  {
    icon: "🏡",
    title: "Vay mua nhà & An cư",
    text: "Tìm quản lý hoặc chuyên gia từ 5 năm kinh nghiệm có thể tiếp cận vay mua nhà",
  },
  {
    icon: "💳",
    title: "Thẻ tín dụng VIP",
    text: "Tìm quản lý, giám đốc hoặc chuyên gia quan tâm thẻ tín dụng hạn mức cao",
  },
  {
    icon: "🏢",
    title: "Vay vốn SME & Payroll",
    text: "Tìm chủ doanh nghiệp, CEO, kế toán trưởng để chào gói vốn kinh doanh và chi lương",
  },
  {
    icon: "💎",
    title: "Khách Ưu tiên & Tiết kiệm",
    text: "Tìm giám đốc, bác sĩ, chuyên gia lâu năm có dòng tiền tốt để tư vấn Priority & Tiết kiệm",
  },
];

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

type ProspectRowScores = ProspectRow["scores"];

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

function ProspectCriteriaSection({ plan }: { plan?: ProspectAnswerPlan }) {
  const [open, setOpen] = useState(true);
  return (
    <section className="prospect-criteria-card" style={{ marginBottom: "12px" }}>
      <div
        className="prospect-criteria-head"
        style={{
          display: "flex",
          flexWrap: "wrap",
          alignItems: "center",
          justifyContent: "space-between",
          gap: "8px",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: "8px", flexWrap: "wrap" }}>
          <h4 className="prospect-criteria-title" style={{ margin: 0, fontSize: "12.5px" }}>
            <span>🎯</span> Hệ thống hiểu câu hỏi của bạn là
          </h4>
          <span
            className={`badge ${plan?.fallback ? "warn" : "ok"}`}
            title={
              plan?.fallback
                ? "Mô hình không hiểu được câu hỏi lúc này; hệ thống đang đoán theo từ khoá."
                : "Đọc bằng chứng thật: bài đăng, tín hiệu, lịch sử tiếp cận."
            }
          >
            {plan?.fallback ? "Dự phòng (đoán theo từ khoá)" : "AI suy luận bằng chứng"}
          </span>
        </div>
        <button
          type="button"
          className="btn btn-secondary btn-sm"
          style={{ fontSize: "11px", padding: "2px 8px", background: "none", border: "1px solid var(--border)" }}
          onClick={() => setOpen((prev) => !prev)}
        >
          {open ? "Thu gọn ▴" : "Chi tiết ▾"}
        </button>
      </div>
      {open ? (
        <div style={{ marginTop: "8px" }}>
          <PlanChips plan={plan} />
        </div>
      ) : null}
    </section>
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
  const { maskSensitiveData } = useCustomTheme();
  const [mode, setMode] = useState<"ai" | "loc">(
    tabParam === "filter" ? "loc" : initialMode
  );
  // Cỗ máy chat AI dùng CHUNG với Talent (`AiSearch`) — xem `CopilotChat.tsx`.
  const chatState = useProspectChatState();
  const [creatingFor, setCreatingFor] = useState<number | null>(null);
  const [createdMsg, setCreatedMsg] = useState<string | null>(null);
  const [aiViewMode, setAiViewMode] = useState<"cards" | "table">("cards");

  useEffect(() => {
    if (tabParam === "filter") {
      setMode("loc");
    } else if (tabParam === "prospects") {
      setMode("ai");
    }
  }, [tabParam]);

  // Filter Mode State (Đồng bộ với TalentFilterState)
  const {
    draft, setDraft, applied: appliedFilters, setApplied: setAppliedFilters,
    hasSearched, setHasSearched, showAdvanced, setShowAdvanced,
    viewMode: filterViewMode, setViewMode: setFilterViewMode,
    page, setPage, scrollY, setScrollY,
    history: filterHistory, rememberFilter, clearHistory,
  } = useRbFilterState();

  const [selectedIds, setSelectedIds] = useState<number[]>([]);
  const [selectedProduct, setSelectedProduct] = useState<string>("credit_card");
  const [selectedNeed, setSelectedNeed] = useState<string>("");
  const [targetPool, setTargetPool] = useState<string>("");
  const [newPoolTitle, setNewPoolTitle] = useState<string>("");
  const [successMsg, setSuccessMsg] = useState<string | null>(null);

  const facets = useQuery({
    queryKey: ["talent-facets"],
    queryFn: api.talentFacets,
  });

  const filterHistoryQuery = useQuery({
    queryKey: ["filter-history", "rb"],
    queryFn: () => api.filterHistory("rb"),
    retry: false,
  });

  const pools = useQuery({
    queryKey: ["pools", "rb"],
    queryFn: () => api.pools("rb"),
  });

  const searchResults = useQuery({
    queryKey: ["rb-smart-filter-search", appliedFilters, page],
    queryFn: () => api.talentSearch(appliedFilters, 30, page * 30),
    enabled: mode === "loc" && hasSearched,
    retry: false,
  });

  // Khôi phục vị trí cuộn khi quay lại từ 360°
  useEffect(() => {
    if (mode !== "loc" || !hasSearched || !searchResults.data || scrollY <= 0) return;
    const targetY = scrollY;
    const timer = window.setTimeout(() => {
      window.scrollTo({ top: targetY, behavior: "instant" });
      setScrollY(0);
    }, 0);
    return () => window.clearTimeout(timer);
  }, [mode, hasSearched, searchResults.data, scrollY, setScrollY]);

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

  const bulkCreateOpportunity = useMutation({
    mutationFn: async () => {
      const results = await Promise.allSettled(
        selectedIds.map((personId) =>
          api.rbOpportunityCreate({
            person_id: personId,
            product: selectedProduct || "credit_card",
            need: selectedNeed.trim() || "Tạo hàng loạt từ bộ lọc RB",
          })
        )
      );
      return results.filter((r) => r.status === "fulfilled").length;
    },
    onSuccess: (count) => {
      setSelectedIds([]);
      setSuccessMsg(`✓ Đã tạo thành công ${count} cơ hội tiếp cận cho khách hàng đã chọn!`);
      qc.invalidateQueries({ queryKey: ["rb-customer-tasks"] });
      qc.invalidateQueries({ queryKey: ["rb-opportunities"] });
      setTimeout(() => setSuccessMsg(null), 5000);
    },
  });

  const addToPool = useMutation({
    mutationFn: async () => {
      if (!targetPool) return;
      await Promise.allSettled(
        selectedIds.map((personId) =>
          api.setPoolMember(Number(targetPool), personId)
        )
      );
    },
    onSuccess: () => {
      const count = selectedIds.length;
      setSelectedIds([]);
      setTargetPool("");
      setSuccessMsg(`✓ Đã thêm ${count} khách hàng vào nhóm thành công!`);
      qc.invalidateQueries({ queryKey: ["customer-groups"] });
      qc.invalidateQueries({ queryKey: ["pools", "rb"] });
      setTimeout(() => setSuccessMsg(null), 5000);
    },
  });

  const createPoolWithMembers = useMutation({
    mutationFn: async () => {
      if (!newPoolTitle.trim()) return;
      const pool = await api.createPool(newPoolTitle.trim(), "Tạo từ bộ lọc khách hàng", "rb");
      await Promise.allSettled(
        selectedIds.map((personId) => api.setPoolMember(pool.id, personId))
      );
      return pool;
    },
    onSuccess: (pool) => {
      const count = selectedIds.length;
      setSelectedIds([]);
      setNewPoolTitle("");
      setSuccessMsg(`✓ Đã tạo nhóm "${pool?.name || newPoolTitle}" với ${count} khách hàng!`);
      qc.invalidateQueries({ queryKey: ["customer-groups"] });
      qc.invalidateQueries({ queryKey: ["pools", "rb"] });
      setTimeout(() => setSuccessMsg(null), 5000);
    },
  });

  const togglePerson = (id: number) =>
    setSelectedIds((current) =>
      current.includes(id)
        ? current.filter((val) => val !== id)
        : [...current, id]
    );

  /** Gợi ý câu hỏi tiếp theo — ngôn ngữ "khách hàng" thay cho "ứng viên" của
   *  Talent (`AnswerView`'s `getFollowUps` mặc định). */
  function getProspectFollowUps(turn: AnswerTurn<ProspectAnswerPerson>, question?: string): string[] {
    return inferFollowUpQuestions(turn, { domain: "rb", question });
  }

  function recordFilter(filters: SearchFilters) {
    rememberFilter(filters);
    const hasCriteria = Object.entries(filters).some(([key, value]) =>
      key !== "order" && value !== "" && value !== false && value !== undefined && value !== null);
    if (!hasCriteria) return;
    void api.recordFilterHistory("rb", filters)
      .then(() => qc.invalidateQueries({ queryKey: ["filter-history", "rb"] }))
      .catch(() => undefined);
  }

  function filterSummary(filters: SearchFilters) {
    const labels: Partial<Record<keyof SearchFilters, string>> = {
      q: "Từ khoá", skills: "Kỹ năng/Nghề", title: "Chức danh", location: "Khu vực",
      company: "Công ty", product: "Sản phẩm", lead_status: "Trạng thái",
      pool: "Nhóm khách", owner: "RM", min_years: "KN/Tuổi từ", max_years: "Đến",
      has_email: "Có email", has_phone: "Có SĐT",
    };
    const parts = Object.entries(filters).filter(([key, value]) => key !== "order" && value !== "" && value !== false && value != null)
      .map(([key, value]) => `${labels[key as keyof SearchFilters] ?? key}: ${value === true ? "Có" : value}`);
    return parts.slice(0, 3).join(" · ") + (parts.length > 3 ? ` · +${parts.length - 3}` : "");
  }

  function reopenFilter(filters: SearchFilters) {
    setDraft(filters);
    setAppliedFilters(filters);
    setHasSearched(true);
    setPage(0);
    recordFilter(filters);
  }

  function clearFilterHistory() {
    clearHistory();
    void api.clearFilterHistory("rb")
      .then(() => qc.invalidateQueries({ queryKey: ["filter-history", "rb"] }))
      .catch(() => undefined);
  }

  const handleApplyFilters = (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    setAppliedFilters({ ...draft });
    setHasSearched(true);
    setPage(0);
    recordFilter(draft);
  };

  const applyQuickFilter = (patch: Partial<SearchFilters>) => {
    const updated = { ...draft, ...patch };
    setDraft(updated);
    setAppliedFilters(updated);
    setHasSearched(true);
    setPage(0);
    recordFilter(updated);
  };

  const resetFilters = () => {
    setDraft({ order: "relevance" });
    setAppliedFilters({ order: "relevance" });
    setHasSearched(false);
    setPage(0);
    setScrollY(0);
  };

  const removeFilter = (key: keyof SearchFilters) => {
    const updated = { ...appliedFilters, [key]: undefined };
    setDraft(updated);
    setAppliedFilters(updated);
    setPage(0);
  };

  const activeFilterCount = Object.keys(appliedFilters).filter(
    (k) => k !== "order" && appliedFilters[k as keyof SearchFilters],
  ).length;

  const activeFilters = Object.entries(appliedFilters).filter(
    ([key, value]) => key !== "order" && value !== "" && value !== false && value != null,
  ) as Array<[keyof SearchFilters, SearchFilters[keyof SearchFilters]]>;

  const filterLabels: Partial<Record<keyof SearchFilters, string>> = {
    q: "Từ khoá", skills: "Kỹ năng/Nghề", title: "Chức danh", location: "Khu vực",
    company: "Công ty", product: "Sản phẩm", lead_status: "Trạng thái",
    pool: "Nhóm khách", owner: "RM", min_years: "Từ", max_years: "Đến",
    has_email: "Có email", has_phone: "Có SĐT",
  };

  const serverHistory = (filterHistoryQuery.data?.results ?? []).map((row) => ({
    id: `server-${row.id}`, filters: row.filters, createdAt: new Date(row.used_at).getTime(),
  }));
  const serverSignatures = new Set(serverHistory.map((row) => JSON.stringify(row.filters)));
  const historyRows = [...serverHistory,
    ...filterHistory.filter((row) => !serverSignatures.has(JSON.stringify(row.filters)))].slice(0, 12);

  const allPageIds = (searchResults.data?.results ?? []).map((c: TalentCard) => c.id);
  const isAllPageSelected = allPageIds.length > 0 && allPageIds.every((id: number) => selectedIds.includes(id));
  const toggleSelectAllPage = () => {
    if (isAllPageSelected) {
      setSelectedIds((prev) => prev.filter((id) => !allPageIds.includes(id)));
    } else {
      setSelectedIds((prev) => Array.from(new Set([...prev, ...allPageIds])));
    }
  };

  return (
    <div className="talent-container full-page-ai-glow">
      {/* Dynamic Animated AI Glow Spheres */}
      <div className="ai-ambient-glow">
        <div className="glow-orb orb-1" />
        <div className="glow-orb orb-2" />
        <div className="glow-orb orb-3" />
      </div>

      <div className="talent-content-relative">
        {(createdMsg || successMsg) && (
          <div className="talent-success-banner">
            <span>{createdMsg || successMsg}</span>
          </div>
        )}

        {/* =========================================================
            CHẾ ĐỘ 1: HỎI BẰNG LỜI VỚI AI (COPILOT PROSPECT ENGINE)
            ========================================================= */}
        {mode === "ai" && (
          <CopilotChat<ProspectAnswerPerson>
            chatState={chatState}
            ask={api.rbAsk}
            askTurn={api.rbAskTurn}
            supportsFiles={false}
            heroTitle={
              <>
                Trợ lý Tìm Kiếm &amp; Bán Chéo <span className="hero-gradient-text">Growth Radar</span>
              </>
            }
            heroSubtitle="Hỗ trợ RM &amp; Sales tìm kiếm khách hàng tiềm năng, cơ hội tài chính và bán chéo sản phẩm qua mô tả tự nhiên."
            heroPlaceholder="Mô tả chân dung khách hàng hoặc nhu cầu tài chính…"
            barPlaceholder="Mô tả chân dung khách hàng hoặc nhu cầu tài chính…"
            submitLabel="Tìm khách hàng"
            barSubmitAriaLabel="Gửi câu hỏi"
            quickPrompts={GOI_Y_RB}
            quickPromptIconStyle={{ background: "rgba(5, 150, 105, 0.12)", color: "#059669" }}
            renderAnswerBody={(msg, mi, messages, elapsedSeconds, sendFollowUp) => {
              const ans = msg.answer;
              const question = messages[mi - 1]?.sender === "user" ? messages[mi - 1].text : undefined;
              const plan = ans?.trace?.plan as ProspectAnswerPlan | undefined;
              const traceMeta = ans?.trace as { keeps_last_result?: boolean; count?: { exact?: boolean } } | undefined;
              // Lượt CÂU LỆNH (soạn nháp, tạo cơ hội) hay lượt ĐẾM CHÍNH XÁC không
              // phải một kết quả tìm kiếm: không có kế hoạch tìm hữu ích, không
              // danh sách. Hiện thẻ tiêu chí rỗng hay thẻ khách điểm 0 dưới đó là
              // nói sai điều vừa xảy ra — ẩn hẳn cả khối, chỉ còn văn bản trả lời.
              const textOnly = Boolean(traceMeta?.keeps_last_result) || Boolean(traceMeta?.count?.exact);
              // Kế hoạch tới NGAY từ preamble, trước khi có `done`/danh sách — RM
              // thấy hệ thống hiểu câu hỏi thế nào trước khi tin danh sách xuất hiện.
              const showPayload = Boolean(plan) && !textOnly;
              const rows = (ans?.people ?? []).map(prospectRowFromAnswer);
              return (
                <>
                  {(msg.isPending || (ans?.steps?.length ?? 0) > 0 || (ans?.durationMs ?? Number(ans?.trace?.ms_total ?? 0)) > 0) ? (
                    <StepTimeline
                      steps={ans?.steps}
                      stage={ans?.stage}
                      elapsedSeconds={elapsedSeconds}
                      hint={waitingHint(elapsedSeconds)}
                      isPending={msg.isPending}
                      compact={!!msg.text}
                      durationMs={ans?.durationMs ?? Number(ans?.trace?.ms_total ?? 0)}
                    />
                  ) : null}

                  {ans ? (
                    <AnswerView<ProspectAnswerPerson>
                      turn={ans}
                      isPending={msg.isPending}
                      question={question}
                      conversationId={chatState.threadId}
                      onFollowUp={sendFollowUp}
                      getFollowUps={getProspectFollowUps}
                      personLinkFrom="rb"
                      extraBeforePeople={
                        showPayload ? <ProspectCriteriaSection plan={plan} /> : null
                      }
                      renderPeople={() =>
                        !showPayload ? null : rows.length === 0 ? (
                          <div className="empty-results-box" style={{ width: "100%" }}>
                            <div className="empty-icon">🔍</div>
                            <h3>Chưa có khách hàng nào có đủ bằng chứng phù hợp.</h3>
                            <p>Thử điều chỉnh câu hỏi mô tả hoặc dùng Bộ lọc Đa chiều để tra cứu rộng hơn.</p>
                          </div>
                        ) : (
                          <>
                            <div className="results-header-toolbar" style={{ margin: "0" }}>
                              <div className="results-count-badge">
                                <span>
                                  Tìm thấy <strong>{rows.length}</strong> khách hàng tiềm năng xếp theo mức đáng ưu tiên liên hệ
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
                                {rows.map((row) => (
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
                                                need: `Đề xuất từ Growth Radar: ${question ?? ""}`,
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
                                className="talent-table-wrapper prospect-table-wrapper"
                                style={{
                                  background: "var(--surface)",
                                  border: "1px solid var(--border)",
                                  borderRadius: "14px",
                                  overflowX: "auto",
                                  overflowY: "hidden",
                                  WebkitOverflowScrolling: "touch",
                                  maxWidth: "100%",
                                }}
                              >
                                <table className="table prospect-table" style={{ margin: 0, minWidth: "980px", width: "100%" }}>
                                  <thead>
                                    <tr>
                                      <th style={{ minWidth: "220px", width: "240px" }}>Khách hàng</th>
                                      <th style={{ minWidth: "160px", width: "180px" }}>Nghề nghiệp / Chức danh</th>
                                      <th className="num" style={{ minWidth: "190px", width: "190px", textAlign: "center" }}>Điểm ưu tiên</th>
                                      <th style={{ minWidth: "260px" }}>Vì sao đề xuất</th>
                                      <th style={{ minWidth: "140px", width: "140px", textAlign: "right" }}>Thao tác</th>
                                    </tr>
                                  </thead>
                                  <tbody>
                                    {rows.map((row) => (
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
                                        <td className="num" style={{ minWidth: "190px", width: "190px", textAlign: "center" }}>
                                          <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: "3px" }}>
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
                                            <div className="muted small" style={{ fontSize: "11px", textAlign: "center", lineHeight: 1.45, maxWidth: "180px" }}>
                                              {(Object.keys(TEN_CHIEU) as Array<keyof ProspectRowScores>)
                                                .map((key) => `${TEN_CHIEU[key]} ${Math.round(row.scores[key])}`)
                                                .join(" · ")}
                                            </div>
                                          </div>
                                        </td>
                                        <td className="prospect-why" style={{ minWidth: "260px" }}>
                                          {row.why && row.why.length > 0 ? (
                                            row.why.slice(0, 3).map((line, index) => (
                                              <div key={index}>{line}</div>
                                            ))
                                          ) : (
                                            <span className="muted small" style={{ fontStyle: "italic", opacity: 0.7 }}>Chưa có ghi chú phân tích</span>
                                          )}
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
                                                    need: `Đề xuất từ Growth Radar: ${question ?? ""}`,
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
                        )
                      }
                    />
                  ) : (
                    msg.text && <p className="chat-paragraph">{msg.text}</p>
                  )}
                </>
              );
            }}
          />
        )}

        {/* =========================================================
            CHẾ ĐỘ 2: BỘ LỌC ĐA CHIỀU & DANH BẠ KHÁCH HÀNG
            ========================================================= */}
        {mode === "loc" && (
          <div className="talent-filter-workspace">
            {/* 1. Thanh tìm kiếm chính & Bộ lọc trực quan (Ưu tiên hiển thị trên cùng) */}
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
                    💳 Thẻ tín dụng
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
                    🏡 Vay mua nhà
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
                  <button
                    type="button"
                    className="btn btn-ghost btn-sm"
                    aria-expanded={showAdvanced}
                    onClick={() => setShowAdvanced((value) => !value)}
                  >
                    {showAdvanced
                      ? "Ẩn bộ lọc nâng cao"
                      : `Bộ lọc nâng cao${activeFilterCount ? ` (${activeFilterCount})` : ""}`}
                  </button>
                </div>

                {/* Active Filter Chips */}
                {activeFilters.length > 0 && (
                  <div className="chips" aria-label="Bộ lọc đang áp dụng">
                    {activeFilters.map(([key, value]) => (
                      <button
                        type="button"
                        className="chip"
                        key={key}
                        title="Bỏ điều kiện này"
                        onClick={() => removeFilter(key)}
                      >
                        {filterLabels[key] ?? key}: <strong>{value === true ? "Có" : String(value)}</strong> ×
                      </button>
                    ))}
                  </div>
                )}

                {/* Detailed Criteria Grid */}
                {showAdvanced && (
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
                )}

                {/* Sắp xếp & Áp dụng */}
                <div className="filter-bottom-bar">
                  <div className="filter-sort-group">
                    <label className="sort-label">Sắp xếp theo:</label>
                    <select
                      className="select-dropdown"
                      value={draft.order ?? "relevance"}
                      onChange={(event) => {
                        const nextOrder = event.target.value as SearchFilters["order"];
                        setDraft((prev) => ({ ...prev, order: nextOrder }));
                        if (hasSearched) {
                          setAppliedFilters((prev) => ({ ...prev, order: nextOrder }));
                        }
                      }}
                    >
                      <option value="relevance">🌟 Phù hợp nhất</option>
                      <option value="newest">📅 Mới cập nhật nhất</option>
                      <option value="oldest">⏳ Cũ nhất</option>
                      <option value="name">🔤 Theo bảng chữ cái tên</option>
                    </select>
                  </div>

                  <button
                    type="submit"
                    className="btn btn-primary"
                    disabled={searchResults.isFetching}
                  >
                    {searchResults.isFetching ? "Đang tìm…" : "Áp dụng bộ lọc"}
                  </button>
                </div>
              </form>
            </div>

            {/* 2. Tiện ích lưu trữ: Bộ lọc đã lưu & Lịch sử tìm kiếm gần đây */}
            <div className="talent-filter-subtools" style={{ width: "100%", display: "flex", flexDirection: "column", gap: "10px" }}>
              <RBSavedViewsBar
                applied={appliedFilters}
                onApply={(filters) => {
                  reopenFilter(filters);
                }}
              />

              {historyRows.length > 0 && (
                <div className="saved-views-modern" aria-label="Lịch sử lọc">
                  <div className="saved-views-label"><span>🕘 Lịch sử lọc gần đây:</span></div>
                  <div className="saved-views-chips">
                    {historyRows.map((row) => (
                      <button
                        key={row.id}
                        type="button"
                        className="filter-history-chip"
                        title={new Date(row.createdAt).toLocaleString("vi-VN")}
                        onClick={() => reopenFilter(row.filters)}
                      >
                        <span>{filterSummary(row.filters)}</span>
                        <span className="filter-history-time">
                          {new Date(row.createdAt).toLocaleString("vi-VN", {
                            day: "2-digit",
                            month: "2-digit",
                            hour: "2-digit",
                            minute: "2-digit",
                          })}
                        </span>
                      </button>
                    ))}
                    <button
                      type="button"
                      className="btn btn-ghost btn-sm"
                      onClick={clearFilterHistory}
                    >
                      Xoá lịch sử
                    </button>
                  </div>
                </div>
              )}
            </div>

            {/* 3. Panel thao tác hàng loạt khi chọn nhiều khách hàng */}
            {selectedIds.length > 0 && (
              <div className="talent-bulk-selected-panel">
                <div className="result-head" style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                  <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                    <span className="badge ok" style={{ fontSize: "13px", padding: "4px 10px" }}>
                      Đã chọn <strong>{selectedIds.length}</strong> khách hàng tiềm năng
                    </span>
                  </div>
                  <button className="btn btn-ghost btn-sm" onClick={() => setSelectedIds([])}>
                    Bỏ chọn tất cả
                  </button>
                </div>
                <p className="hint" style={{ margin: "6px 0 12px", fontSize: "13px" }}>
                  Tạo cơ hội tiếp cận đồng loạt hoặc đưa khách hàng vào nhóm chăm sóc:
                </p>
                <div className="search-row" style={{ display: "flex", gap: "10px", flexWrap: "wrap", alignItems: "center" }}>
                  <select
                    className="config-select"
                    style={{ minWidth: "180px" }}
                    value={selectedProduct}
                    onChange={(e) => setSelectedProduct(e.target.value)}
                  >
                    {PRODUCTS.map(([code, label]) => (
                      <option key={code} value={code}>{label}</option>
                    ))}
                  </select>
                  <input
                    className="search-main"
                    style={{ minWidth: "220px", flex: 1 }}
                    value={selectedNeed}
                    onChange={(e) => setSelectedNeed(e.target.value)}
                    placeholder="Nhu cầu tài chính / ghi chú tiếp cận…"
                  />
                  <button
                    type="button"
                    className="btn btn-primary btn-sm"
                    disabled={bulkCreateOpportunity.isPending}
                    onClick={() => bulkCreateOpportunity.mutate()}
                  >
                    {bulkCreateOpportunity.isPending ? "Đang tạo…" : "⚡ Tạo cơ hội hàng loạt"}
                  </button>

                  <span className="muted" style={{ fontSize: "12px", margin: "0 6px" }}>|</span>

                  <select
                    className="config-select"
                    style={{ minWidth: "180px" }}
                    value={targetPool}
                    onChange={(e) => setTargetPool(e.target.value)}
                  >
                    <option value="">Thêm vào nhóm / Pool…</option>
                    {(pools.data?.results ?? []).map((pool) => (
                      <option key={pool.id} value={pool.id}>
                        {pool.name} ({pool.member_count})
                      </option>
                    ))}
                  </select>
                  <button
                    type="button"
                    className="btn btn-secondary btn-sm"
                    disabled={!targetPool || addToPool.isPending}
                    onClick={() => addToPool.mutate()}
                  >
                    {addToPool.isPending ? "Đang thêm…" : "Thêm vào nhóm"}
                  </button>

                  <span className="muted" style={{ fontSize: "12px", margin: "0 4px" }}>hoặc</span>

                  <input
                    className="search-main"
                    style={{ minWidth: "180px" }}
                    value={newPoolTitle}
                    onChange={(e) => setNewPoolTitle(e.target.value)}
                    placeholder="Tên nhóm mới…"
                  />
                  <button
                    type="button"
                    className="btn btn-secondary btn-sm"
                    disabled={!newPoolTitle.trim() || createPoolWithMembers.isPending}
                    onClick={() => createPoolWithMembers.mutate()}
                  >
                    {createPoolWithMembers.isPending ? "Đang tạo…" : "+ Tạo nhóm mới"}
                  </button>
                </div>
                {(bulkCreateOpportunity.error || addToPool.error || createPoolWithMembers.error) && (
                  <p className="err-box" style={{ marginTop: "10px" }}>
                    {String(bulkCreateOpportunity.error || addToPool.error || createPoolWithMembers.error)}
                  </p>
                )}
              </div>
            )}

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
                      recordFilter(draft);
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
                            <input
                              type="checkbox"
                              checked={selectedIds.includes(card.id)}
                              onChange={() => togglePerson(card.id)}
                              title="Chọn khách hàng này"
                              style={{ cursor: "pointer", width: "16px", height: "16px", accentColor: "var(--accent)" }}
                            />
                            <div
                              className="talent-avatar-modern"
                              style={{ background: "var(--accent-gradient)" }}
                            >
                              {(card.display_name || "K")[0]?.toUpperCase()}
                            </div>
                            <div>
                              <Link
                                to={`/person/${card.id}?from=rb`}
                                onClick={() => setScrollY(window.scrollY)}
                                style={{ fontWeight: 700, fontSize: "15px", color: "var(--text)", textDecoration: "none" }}
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
                            onClick={() => setScrollY(window.scrollY)}
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
                          <th style={{ width: "40px" }}>
                            <input
                              type="checkbox"
                              checked={isAllPageSelected}
                              onChange={toggleSelectAllPage}
                              title="Chọn tất cả trên trang này"
                              style={{ cursor: "pointer", accentColor: "var(--accent)" }}
                            />
                          </th>
                          <th>Khách hàng</th>
                          <th>Chức danh &amp; Nơi làm việc</th>
                          <th>Khu vực &amp; Liên hệ</th>
                          <th style={{ textAlign: "right" }}>Thao tác</th>
                        </tr>
                      </thead>
                      <tbody>
                        {(searchResults.data?.results ?? []).map((card: TalentCard) => (
                          <tr key={card.id} className="talent-table-row">
                            <td style={{ width: "40px" }}>
                              <input
                                type="checkbox"
                                checked={selectedIds.includes(card.id)}
                                onChange={() => togglePerson(card.id)}
                                title="Chọn khách hàng này"
                                style={{ cursor: "pointer", accentColor: "var(--accent)" }}
                              />
                            </td>
                            <td className="table-col-name">
                              <Link
                                to={`/person/${card.id}?from=rb`}
                                onClick={() => setScrollY(window.scrollY)}
                                className="table-name-link"
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
