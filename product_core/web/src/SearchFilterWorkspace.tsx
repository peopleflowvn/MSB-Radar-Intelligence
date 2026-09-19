import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import React, { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import {
  api,
  SavedView,
  SearchFilters,
  TalentCard,
} from "./api";
import { useCustomTheme } from "./CustomThemeContext";
import { useSearchFilterState } from "./searchPersistence";
import { SearchPerspective, perspectiveDomain, personLinkFrom } from "./searchPerspective";

/** Thanh bộ lọc đã lưu, theo phân hệ đích (talent = đợt tuyển, rb = khách hàng) */
function SavedViewsBar({
  domain,
  applied,
  onApply,
}: {
  domain: "talent" | "rb";
  applied: SearchFilters;
  onApply: (filters: SearchFilters) => void;
}) {
  const queryClient = useQueryClient();
  const [naming, setNaming] = useState(false);
  const [name, setName] = useState("");

  const views = useQuery({
    queryKey: ["saved-views", domain],
    queryFn: () => api.savedViews(domain),
    retry: false,
  });

  function refresh() {
    queryClient.invalidateQueries({ queryKey: ["saved-views", domain] });
  }

  const save = useMutation({
    mutationFn: () =>
      api.saveView(
        domain,
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
        <span>🔖 Bộ lọc đã lưu:</span>
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

function maskString(str?: string | null, type: "email" | "phone" = "phone"): string {
  if (!str) return "";
  if (type === "email") {
    const parts = str.split("@");
    if (parts.length < 2) return str;
    return `${parts[0].slice(0, 2)}***@${parts[1]}`;
  }
  if (str.length < 7) return str;
  return `${str.slice(0, 4)}***${str.slice(-3)}`;
}

function getSeniorityBadge(years?: number | null) {
  if (years == null) return null;
  if (years >= 5) return <span className="seniority-badge lead">Lead / Senior ({years}y+)</span>;
  if (years >= 2) return <span className="seniority-badge mid">Mid-level ({years}y)</span>;
  return <span className="seniority-badge junior">Junior ({years}y)</span>;
}

/** Ứng viên đang nằm trong đợt tuyển nào, ai xử lý — và cảnh báo khi trùng người. */
function WorklistBadges({ person }: { person: TalentCard }) {
  if (!person.active_worklists?.length) return null;
  const owners = new Set(
    person.active_worklists.map((row) => row.assigned_to_name).filter(Boolean),
  );
  return (
    <div className="chips">
      {owners.size > 1 && <span className="badge err">⚠ Nhiều người đang xử lý</span>}
      {person.active_worklists.slice(0, 3).map((row) => (
        <span key={row.hunt_id} className={`chip rel rel-${row.state}`} title={row.note || undefined}>
          {row.title}: <strong>{row.state_label}</strong>
          {row.assigned_to_name && ` · ${row.assigned_to_name}`}
        </span>
      ))}
    </div>
  );
}

/**
 * Kết quả của một thao tác hàng loạt chạy bằng `Promise.allSettled`: báo đúng số
 * thành công, và nói rõ số hỏng — trước đây thông báo luôn lấy số đã CHỌN, nên
 * 3/50 người thêm vào nhóm thất bại vẫn hiện "Đã thêm 50".
 */
function settledCount(results: PromiseSettledResult<unknown>[]) {
  const ok = results.filter((r) => r.status === "fulfilled").length;
  return { ok, failed: results.length - ok };
}

function failedSuffix(failed: number) {
  return failed > 0 ? ` (${failed} hồ sơ không xử lý được — thử lại sau)` : "";
}

/**
 * Mọi chữ và con số khác nhau giữa hai góc nhìn, gom một chỗ. Trước đây là hơn
 * ba chục phép `isProspect ? … : …` rải khắp phần hiển thị — thêm một nhãn là
 * phải lần hết file, sót một chỗ là màn hình Khách hàng hiện chữ "ứng viên".
 */
const COPY = {
  recruiter: {
    //: Giữ đúng nhịp duyệt cũ của từng bên: bộ lọc ứng viên 50 hồ sơ một trang.
    pageSize: 50,
    noun: "ứng viên",
    nounTitle: "Ứng viên",
    found: "ứng viên phù hợp",
    tasksLink: "/talent?tab=tasks",
    tasksLabel: "Sang Nhiệm vụ săn",
    searchPlaceholder: "Tìm theo tên ứng viên, kỹ năng, chức danh, công ty…",
    poolLabel: "Đợt tuyển & Pool",
    ownerLabel: "Recruiter phụ trách",
    emptyIcon: "🎯",
    emptyTitle: "Kho Hồ Sơ Ứng Viên & Nhân Tài",
    titleFallback: "Chưa cập nhật chức danh",
    metaColumn: "Khu vực & Kinh nghiệm",
  },
  prospect: {
    //: Bộ lọc khách hàng vốn duyệt 30 — gộp về một số là đổi nhịp của cả hai.
    pageSize: 30,
    noun: "khách hàng",
    nounTitle: "Khách hàng",
    found: "khách hàng tiềm năng",
    tasksLink: "/rb?tab=tasks",
    tasksLabel: "Sang Cơ hội & Việc cần xử lý",
    searchPlaceholder: "Tìm theo tên khách hàng, chức danh, công ty, nhu cầu tài chính…",
    poolLabel: "Nhóm khách hàng",
    ownerLabel: "RM phụ trách",
    emptyIcon: "💼",
    emptyTitle: "Kho Dữ Liệu Khách Hàng Tiềm Năng & Bán Chéo",
    titleFallback: "Khách hàng cá nhân",
    metaColumn: "Khu vực & Liên hệ",
  },
} as const;

const PRODUCT_OPTIONS: Array<[string, string]> = [
  ["credit_card", "Thẻ tín dụng"],
  ["mortgage", "Vay mua nhà"],
  ["savings", "Tiết kiệm"],
  ["investment", "Đầu tư"],
  ["insurance", "Bảo hiểm"],
  ["fx", "Ngoại tệ"],
  ["auto_loan", "Vay mua xe"],
  ["consumer_loan", "Vay tiêu dùng"],
  ["payroll", "Tài khoản lương"],
];

interface BulkActionProps {
  selectedIds: number[];
  /** Xong một thao tác: bỏ chọn và báo kết quả lên banner chung. */
  onDone: (message: string) => void;
}

/** Thao tác hàng loạt của góc nhìn Khách hàng: tạo cơ hội sang Growth Radar. */
function ProspectBulkActions({ selectedIds, onDone }: BulkActionProps) {
  const qc = useQueryClient();
  const [product, setProduct] = useState("credit_card");
  const [need, setNeed] = useState("");

  const create = useMutation({
    mutationFn: async () => settledCount(await Promise.allSettled(
      selectedIds.map((personId) =>
        api.rbOpportunityCreate({
          person_id: personId,
          product: product || "credit_card",
          need: need.trim() || "Tạo hàng loạt từ bộ lọc đa chiều",
        })
      )
    )),
    onSuccess: ({ ok, failed }) => {
      onDone(`✓ Đã tạo ${ok} cơ hội tiếp cận cho khách hàng đã chọn${failedSuffix(failed)}`);
      qc.invalidateQueries({ queryKey: ["rb-customer-tasks"] });
      qc.invalidateQueries({ queryKey: ["rb-opportunities"] });
      qc.invalidateQueries({ queryKey: ["search-filter-results"] });
    },
  });

  return (
    <>
      <select
        className="config-select"
        style={{ minWidth: "160px" }}
        value={product}
        onChange={(e) => setProduct(e.target.value)}
      >
        {PRODUCT_OPTIONS.map(([value, label]) => (
          <option key={value} value={value}>{label}</option>
        ))}
      </select>
      <input
        className="search-main"
        style={{ minWidth: "200px" }}
        value={need}
        onChange={(e) => setNeed(e.target.value)}
        placeholder="Ghi chú nhu cầu tiếp cận…"
      />
      <button
        type="button"
        className="btn btn-primary btn-sm"
        disabled={create.isPending}
        onClick={() => create.mutate()}
      >
        {create.isPending ? "Đang tạo…" : "⚡ Tạo cơ hội hàng loạt"}
      </button>
      {create.error && <span className="err-box">{String(create.error)}</span>}
    </>
  );
}

/** Thao tác hàng loạt của góc nhìn Tuyển dụng: đưa ứng viên vào đợt tuyển. */
function RecruiterBulkActions({ selectedIds, onDone }: BulkActionProps) {
  const qc = useQueryClient();
  const [targetHunt, setTargetHunt] = useState("");
  const [title, setTitle] = useState("");

  const hunts = useQuery({
    queryKey: ["hunts", "open-from-search"],
    queryFn: () => api.hunts({ open: true, mine: true }),
  });

  function refresh() {
    qc.invalidateQueries({ queryKey: ["hunts"] });
    qc.invalidateQueries({ queryKey: ["hunt-tasks"] });
    qc.invalidateQueries({ queryKey: ["search-filter-results"] });
  }

  const createWorklist = useMutation({
    mutationFn: () => api.createShortlist({ title: title.trim(), person_ids: selectedIds }),
    onSuccess: () => {
      onDone(`✓ Đã tạo đợt tuyển mới từ ${selectedIds.length} ứng viên đã chọn!`);
      setTitle("");
      refresh();
    },
  });

  const addToWorklist = useMutation({
    mutationFn: () => api.huntUpdate(Number(targetHunt), { person_ids_add: selectedIds }),
    onSuccess: () => {
      onDone(`✓ Đã thêm ${selectedIds.length} ứng viên vào đợt tuyển thành công!`);
      setTargetHunt("");
      refresh();
    },
  });

  const error = addToWorklist.error || createWorklist.error;
  return (
    <>
      <select
        className="config-select"
        style={{ minWidth: "180px" }}
        value={targetHunt}
        onChange={(e) => setTargetHunt(e.target.value)}
      >
        <option value="">Thêm vào đợt tuyển…</option>
        {(hunts.data?.results ?? []).map((hunt) => (
          <option key={hunt.id} value={hunt.id}>
            {hunt.title}
          </option>
        ))}
      </select>
      <button
        type="button"
        className="btn btn-primary btn-sm"
        disabled={!targetHunt || addToWorklist.isPending}
        onClick={() => addToWorklist.mutate()}
      >
        {addToWorklist.isPending ? "Đang thêm…" : "🎯 Thêm vào đợt tuyển"}
      </button>
      <span className="muted" style={{ fontSize: "12px", margin: "0 4px" }}>hoặc</span>
      <input
        className="search-main"
        style={{ minWidth: "180px" }}
        value={title}
        onChange={(e) => setTitle(e.target.value)}
        placeholder="Tên đợt tuyển mới…"
      />
      <button
        type="button"
        className="btn btn-secondary btn-sm"
        disabled={!title.trim() || createWorklist.isPending}
        onClick={() => createWorklist.mutate()}
      >
        {createWorklist.isPending ? "Đang tạo…" : "+ Tạo đợt tuyển mới"}
      </button>
      {error && <span className="err-box">{String(error)}</span>}
    </>
  );
}

/**
 * Tạo một cơ hội cho một khách, dùng chung cho thẻ và bảng.
 *
 * Sản phẩm lấy từ bộ lọc ĐÃ ÁP (trước đây lấy từ bản nháp — gõ dở bộ lọc sản
 * phẩm rồi bấm là tạo cơ hội cho sản phẩm chưa hề lọc), và khoá nút trong lúc
 * chờ để bấm đúp không sinh hai cơ hội trùng.
 */
function CreateOpportunityButton({
  card, product, onCreated,
}: {
  card: TalentCard;
  product?: string;
  onCreated: (message: string) => void;
}) {
  const qc = useQueryClient();
  const create = useMutation({
    mutationFn: () => api.rbOpportunityCreate({
      person_id: card.id,
      product: product || "credit_card",
      need: `Tạo từ bộ lọc đa chiều: ${card.headline || ""}`,
    }),
    onSuccess: () => {
      onCreated("✓ Đã tạo cơ hội mới vào Growth Radar thành công!");
      qc.invalidateQueries({ queryKey: ["rb-customer-tasks"] });
      qc.invalidateQueries({ queryKey: ["rb-opportunities"] });
    },
  });
  return (
    <button
      type="button"
      className="btn btn-primary btn-sm"
      disabled={create.isPending}
      title={create.error ? String(create.error) : undefined}
      onClick={() => create.mutate()}
    >
      {create.isPending ? "Đang tạo…" : create.error ? "⚠ Thử lại" : "⚡ Tạo cơ hội"}
    </button>
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

export default function SearchFilterWorkspace({
  perspective,
}: {
  perspective: SearchPerspective;
}) {
  const qc = useQueryClient();
  const { maskSensitiveData } = useCustomTheme();
  const isProspect = perspective === "prospect";
  const copy = COPY[perspective];
  const domain = perspectiveDomain(perspective);

  const {
    draft, setDraft, applied: appliedFilters, setApplied: setAppliedFilters,
    hasSearched, setHasSearched, showAdvanced, setShowAdvanced,
    viewMode: filterViewMode, setViewMode: setFilterViewMode,
    page, setPage, scrollY, setScrollY,
    history: filterHistory, rememberFilter, clearHistory,
  } = useSearchFilterState();

  const [selectedIds, setSelectedIds] = useState<number[]>([]);
  const [targetPool, setTargetPool] = useState<string>("");
  const [newPoolTitle, setNewPoolTitle] = useState<string>("");
  const [successMsg, setSuccessMsg] = useState<string | null>(null);

  const personFrom = personLinkFrom(perspective, "filter");
  const pageSize = copy.pageSize;

  const facets = useQuery({
    queryKey: ["talent-facets"],
    queryFn: api.talentFacets,
  });

  const filterHistoryQuery = useQuery({
    queryKey: ["filter-history", domain],
    queryFn: () => api.filterHistory(domain),
    retry: false,
  });

  const pools = useQuery({
    queryKey: ["pools", domain],
    queryFn: () => api.pools(domain),
  });

  const searchResults = useQuery({
    // `pageSize` nằm trong khoá: hai góc nhìn duyệt 50 và 30 hồ sơ một trang, cùng
    // bộ lọc + cùng số trang mà dùng chung cache thì đổi góc nhìn sẽ hiện trang
    // của bên kia (offset 100 thay vì 60) với số trang tính theo bên này.
    queryKey: ["search-filter-results", appliedFilters, page, pageSize],
    queryFn: () => api.talentSearch(appliedFilters, pageSize, page * pageSize),
    enabled: hasSearched,
    retry: false,
  });

  // Pool/đợt tuyển dùng CHUNG một bảng `talent.Pool`, phân biệt nhau bằng cột
  // `domain` — nên cùng một id lại là hai nhóm khác nhau ở hai góc nhìn. Đổi góc
  // nhìn mà giữ nguyên id đang chọn sẽ lọc nhầm nhóm (backend không kiểm tra
  // domain khi lọc, xem `talent/search.py`) và tệ hơn là ghi nhầm người vào nhóm
  // của nghiệp vụ kia. Vì vậy phải xoá mọi lựa chọn mang id theo nghiệp vụ.
  // Danh sách đã tick thì giữ — chuyển ứng viên vừa tìm sang xem như khách hàng
  // tiềm năng chính là việc người dùng cần làm.
  const prevPerspective = useRef(perspective);
  useEffect(() => {
    if (prevPerspective.current === perspective) return;  // lần mount đầu: giữ bộ lọc đã lưu
    prevPerspective.current = perspective;
    setTargetPool("");
    setDraft((prev) => (prev.pool ? { ...prev, pool: "" } : prev));
    setAppliedFilters((prev) => (prev.pool ? { ...prev, pool: "" } : prev));
  }, [perspective, setDraft, setAppliedFilters]);

  useEffect(() => {
    if (!hasSearched || !searchResults.data || scrollY <= 0) return;
    const targetY = scrollY;
    const timer = window.setTimeout(() => {
      window.scrollTo({ top: targetY, behavior: "instant" });
      setScrollY(0);
    }, 0);
    return () => window.clearTimeout(timer);
  }, [hasSearched, searchResults.data, scrollY, setScrollY]);

  // Một bộ hẹn giờ cho banner, huỷ khi có thông báo mới hoặc khi rời màn hình —
  // trước đây mỗi thao tác tự `setTimeout` riêng, thông báo sau bị thông báo
  // trước xoá sớm, và hẹn giờ còn chạy sau khi component đã gỡ.
  const successTimer = useRef<number | undefined>(undefined);
  useEffect(() => () => window.clearTimeout(successTimer.current), []);
  const showSuccess = useCallback((message: string) => {
    window.clearTimeout(successTimer.current);
    setSuccessMsg(message);
    successTimer.current = window.setTimeout(() => setSuccessMsg(null), 5000);
  }, []);
  const finishBulk = useCallback((message: string) => {
    setSelectedIds([]);
    showSuccess(message);
  }, [showSuccess]);

  const addToPool = useMutation({
    mutationFn: async () => {
      if (!targetPool) return { ok: 0, failed: 0 };
      return settledCount(await Promise.allSettled(
        selectedIds.map((personId) =>
          api.setPoolMember(Number(targetPool), personId)
        )
      ));
    },
    onSuccess: ({ ok, failed }) => {
      setTargetPool("");
      finishBulk(`✓ Đã thêm ${ok} hồ sơ vào nhóm${failedSuffix(failed)}`);
      qc.invalidateQueries({ queryKey: ["customer-groups"] });
      qc.invalidateQueries({ queryKey: ["pools", domain] });
      qc.invalidateQueries({ queryKey: ["search-filter-results"] });
    },
  });

  const createPoolWithMembers = useMutation({
    mutationFn: async () => {
      if (!newPoolTitle.trim()) return;
      const pool = await api.createPool(newPoolTitle.trim(), "Tạo từ bộ lọc đa chiều", domain);
      const { ok, failed } = settledCount(await Promise.allSettled(
        selectedIds.map((personId) => api.setPoolMember(pool.id, personId))
      ));
      return { pool, ok, failed };
    },
    onSuccess: (result) => {
      setNewPoolTitle("");
      if (result) {
        finishBulk(`✓ Đã tạo nhóm "${result.pool.name || newPoolTitle}" với ${result.ok} hồ sơ${failedSuffix(result.failed)}`);
      }
      qc.invalidateQueries({ queryKey: ["customer-groups"] });
      qc.invalidateQueries({ queryKey: ["pools", domain] });
      qc.invalidateQueries({ queryKey: ["search-filter-results"] });
    },
  });

  const togglePerson = (id: number) =>
    setSelectedIds((current) =>
      current.includes(id)
        ? current.filter((val) => val !== id)
        : [...current, id]
    );

  function recordFilter(filters: SearchFilters) {
    rememberFilter(filters);
    const hasCriteria = Object.entries(filters).some(([key, value]) =>
      key !== "order" && value !== "" && value !== false && value !== undefined && value !== null);
    if (!hasCriteria) return;
    void api.recordFilterHistory(domain, filters)
      .then(() => qc.invalidateQueries({ queryKey: ["filter-history", domain] }))
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
    void api.clearFilterHistory(domain)
      .then(() => qc.invalidateQueries({ queryKey: ["filter-history", domain] }))
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
    <div className="talent-filter-workspace">
      {successMsg && (
        <div className="talent-success-banner" style={{ marginBottom: "16px" }}>
          <span>{successMsg}</span>
          {/* Phân hệ Tìm kiếm không có bảng công việc — đưa thẳng sang nơi xử lý
              tiếp ở Radar tương ứng, thay vì bắt người dùng tự mò trong menu. */}
          <Link
            className="btn btn-primary btn-sm"
            to={copy.tasksLink}
          >
            👉 {copy.tasksLabel} →
          </Link>
        </div>
      )}

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
                placeholder={copy.searchPlaceholder}
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
            {isProspect ? (
              <>
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
              </>
            ) : (
              <>
                <button
                  type="button"
                  className={`quick-tag-btn ${draft.min_years === "5" ? "active" : ""}`}
                  onClick={() =>
                    applyQuickFilter({
                      min_years: draft.min_years === "5" ? undefined : "5",
                    })
                  }
                >
                  ⏳ Từ 5 năm KN
                </button>
                <button
                  type="button"
                  className={`quick-tag-btn ${draft.min_years === "8" ? "active" : ""}`}
                  onClick={() =>
                    applyQuickFilter({
                      min_years: draft.min_years === "8" ? undefined : "8",
                    })
                  }
                >
                  ⏳ Từ 8 năm KN
                </button>
                <button
                  type="button"
                  className={`quick-tag-btn ${draft.relationship === "new" ? "active" : ""}`}
                  onClick={() =>
                    applyQuickFilter({
                      relationship: draft.relationship === "new" ? "" : "new",
                    })
                  }
                >
                  🤝 Mới trong kho
                </button>
              </>
            )}
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
                hint="Hỗ trợ OR, AND, NOT (VD: React OR Vue)"
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
                label="Công ty / Doanh nghiệp"
                icon="🏢"
                placeholder="VD: FPT OR Vingroup OR Viettel"
                value={draft.company ?? ""}
                onChange={(event) => setDraft((prev) => ({ ...prev, company: event.target.value }))}
              />
              <Field
                label="Nơi làm việc mong muốn"
                icon="🧭"
                placeholder="VD: Hà Nội OR Đà Nẵng"
                value={draft.desired_location ?? ""}
                onChange={(event) => setDraft((prev) => ({ ...prev, desired_location: event.target.value }))}
              />
              <Field
                label="Cấp bậc"
                icon="📈"
                placeholder="VD: Senior OR Manager"
                value={draft.seniority ?? ""}
                onChange={(event) => setDraft((prev) => ({ ...prev, seniority: event.target.value }))}
              />
              <Field
                label="Học vấn"
                icon="🎓"
                placeholder="VD: Đại học OR Thạc sĩ"
                value={draft.education ?? ""}
                onChange={(event) => setDraft((prev) => ({ ...prev, education: event.target.value }))}
              />
              <Field
                label="Hình thức làm việc"
                icon="🗓️"
                placeholder="VD: Toàn thời gian OR Hybrid"
                value={draft.job_type ?? ""}
                onChange={(event) => setDraft((prev) => ({ ...prev, job_type: event.target.value }))}
              />
              <Field
                label="Ngoại ngữ"
                icon="🌐"
                placeholder="VD: Tiếng Anh AND IELTS"
                value={draft.foreign_language ?? ""}
                onChange={(event) => setDraft((prev) => ({ ...prev, foreign_language: event.target.value }))}
              />

              <div className="filter-col">
                <label className="filter-label">
                  <span>⏳ Kinh nghiệm / Thâm niên (năm)</span>
                </label>
                <div className="years-range-inputs">
                  <input
                    className="input-text filter-input"
                    type="number"
                    min={0}
                    placeholder="Từ (năm)"
                    value={draft.min_years ?? ""}
                    onChange={(event) => setDraft((prev) => ({ ...prev, min_years: event.target.value }))}
                  />
                  <input
                    className="input-text filter-input"
                    type="number"
                    min={0}
                    placeholder="Đến (năm)"
                    value={draft.max_years ?? ""}
                    onChange={(event) => setDraft((prev) => ({ ...prev, max_years: event.target.value }))}
                  />
                </div>
              </div>

              <div className="filter-col">
                <label className="filter-label">
                  <span>🗂️ Nguồn dữ liệu</span>
                </label>
                <select
                  className="config-select"
                  value={draft.source ?? ""}
                  onChange={(event) => setDraft((prev) => ({ ...prev, source: event.target.value }))}
                >
                  <option value="">Tất cả nguồn</option>
                  {(facets.data?.by_source ?? []).map((row) => (
                    <option key={row.source} value={row.source}>
                      {row.source} ({row.count})
                    </option>
                  ))}
                </select>
              </div>

              <div className="filter-col">
                <label className="filter-label">
                  <span>🤝 Quan hệ ứng viên</span>
                </label>
                <select
                  className="config-select"
                  value={draft.relationship ?? ""}
                  onChange={(event) => setDraft((prev) => ({ ...prev, relationship: event.target.value }))}
                >
                  <option value="">Tất cả trạng thái</option>
                  {(facets.data?.relationships ?? []).map((row) => (
                    <option key={row.value} value={row.value}>
                      {row.label}
                    </option>
                  ))}
                </select>
              </div>

              <div className="filter-col">
                <label className="filter-label">
                  <span>💼 Sản phẩm quan tâm</span>
                </label>
                <select
                  className="config-select"
                  value={draft.product ?? ""}
                  onChange={(event) => setDraft((prev) => ({ ...prev, product: event.target.value }))}
                >
                  <option value="">Tất cả sản phẩm</option>
                  <option value="mortgage">Vay mua nhà</option>
                  <option value="credit_card">Thẻ tín dụng</option>
                  <option value="savings">Tiết kiệm</option>
                  <option value="investment">Đầu tư</option>
                  <option value="insurance">Bảo hiểm</option>
                  <option value="fx">Ngoại tệ</option>
                  <option value="auto_loan">Vay mua xe</option>
                  <option value="consumer_loan">Vay tiêu dùng</option>
                  <option value="payroll">Tài khoản lương</option>
                </select>
              </div>

              <div className="filter-col">
                <label className="filter-label">
                  <span>📊 Trạng thái cơ hội</span>
                </label>
                <select
                  className="config-select"
                  value={draft.lead_status ?? ""}
                  onChange={(event) => setDraft((prev) => ({ ...prev, lead_status: event.target.value }))}
                >
                  <option value="">Tất cả trạng thái</option>
                  <option value="new">Mới phát hiện</option>
                  <option value="contacted">Đã tiếp cận</option>
                  <option value="qualified">Đủ điều kiện</option>
                  <option value="won">Thành công</option>
                  <option value="lost">Chưa chốt được</option>
                </select>
              </div>

              <div className="filter-col">
                <label className="filter-label">
                  <span>👥 {copy.poolLabel}</span>
                </label>
                <select
                  className="config-select"
                  value={draft.pool ?? ""}
                  onChange={(event) => setDraft((prev) => ({ ...prev, pool: event.target.value }))}
                >
                  <option value="">Tất cả nhóm</option>
                  {(pools.data?.results ?? []).map((pool) => (
                    <option key={pool.id} value={pool.id}>
                      {pool.name} ({pool.member_count})
                    </option>
                  ))}
                </select>
              </div>

              <div className="filter-col">
                <label className="filter-label">
                  <span>👔 {copy.ownerLabel}</span>
                </label>
                <select
                  className="config-select"
                  value={draft.owner ?? ""}
                  onChange={(event) => setDraft((prev) => ({ ...prev, owner: event.target.value }))}
                >
                  <option value="">Tất cả RM</option>
                  {(facets.data?.owners ?? []).map((owner) => (
                    <option key={owner.id} value={owner.id}>
                      {owner.name}
                    </option>
                  ))}
                </select>
              </div>

              <div className="filter-col">
                <label className="filter-label">
                  <span>📞 Thông tin liên hệ</span>
                </label>
                <div style={{ display: "flex", gap: "12px", marginTop: "6px" }}>
                  <label className="filter-checkbox-label">
                    <input
                      type="checkbox"
                      checked={Boolean(draft.has_email)}
                      onChange={(e) => setDraft((prev) => ({ ...prev, has_email: e.target.checked }))}
                    />
                    <span>Có Email</span>
                  </label>
                  <label className="filter-checkbox-label">
                    <input
                      type="checkbox"
                      checked={Boolean(draft.has_phone)}
                      onChange={(e) => setDraft((prev) => ({ ...prev, has_phone: e.target.checked }))}
                    />
                    <span>Có SĐT</span>
                  </label>
                </div>
              </div>

              <div className="filter-col">
                <label className="filter-label">
                  <span>↕️ Sắp xếp theo</span>
                </label>
                <select
                  className="config-select"
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
            </div>
          )}
        </form>
      </div>

      {/* 2. Thanh bộ lọc đã lưu (Saved Views Bar) */}
      <SavedViewsBar
        domain={domain}
        applied={appliedFilters}
        onApply={(f) => {
          setDraft(f);
          setAppliedFilters(f);
          setHasSearched(true);
          setPage(0);
        }}
      />

      {/* 3. Lịch sử tìm kiếm gần đây */}
      {historyRows.length > 0 && (
        <div className="filter-history-accordion" style={{ marginBottom: "16px" }}>
          <div className="history-head">
            <span className="history-title">⏱️ Tra cứu gần đây:</span>
            <div className="history-chips">
              {historyRows.map((entry) => (
                <button
                  key={entry.id}
                  type="button"
                  className="history-chip"
                  title="Nhấn để áp dụng lại bộ lọc này"
                  onClick={() => reopenFilter(entry.filters)}
                >
                  {filterSummary(entry.filters)}
                </button>
              ))}
              <button
                type="button"
                className="btn-clear-history"
                title="Xoá lịch sử tra cứu"
                onClick={clearFilterHistory}
              >
                Xoá
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Bulk action toolbar khi có tick chọn */}
      {selectedIds.length > 0 && (
        <div className="bulk-actions-toolbar" style={{ marginBottom: "16px" }}>
          <div style={{ display: "flex", alignItems: "center", gap: "10px", flexWrap: "wrap" }}>
            <span className="bulk-count-badge">
              Đã chọn: <strong>{selectedIds.length}</strong> {copy.noun}
            </span>
            <button
              type="button"
              className="btn btn-secondary btn-sm"
              onClick={toggleSelectAllPage}
            >
              {isAllPageSelected ? "Bỏ chọn trang này" : "Chọn toàn bộ trang"}
            </button>
            <button
              type="button"
              className="btn btn-ghost btn-sm"
              onClick={() => setSelectedIds([])}
            >
              Bỏ chọn tất cả
            </button>

            <span className="muted" style={{ fontSize: "12px", margin: "0 6px" }}>|</span>

            {/* `key` theo góc nhìn: đổi góc nhìn là dựng lại, không mang lựa chọn
                đợt tuyển / sản phẩm của nghiệp vụ này sang nghiệp vụ kia. */}
            {isProspect
              ? <ProspectBulkActions key="prospect" selectedIds={selectedIds} onDone={finishBulk} />
              : <RecruiterBulkActions key="recruiter" selectedIds={selectedIds} onDone={finishBulk} />}

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
          {(addToPool.error || createPoolWithMembers.error) && (
            <p className="err-box" style={{ marginTop: "10px" }}>
              {String(addToPool.error || createPoolWithMembers.error)}
            </p>
          )}
        </div>
      )}

      {/* Trạng thái ban đầu: Chưa thực hiện tìm kiếm */}
      {!hasSearched && (
        <div className="talent-search-initial-card">
          <div className="initial-card-icon" style={{ background: "rgba(5, 150, 105, 0.12)", color: "#059669" }}>
            {copy.emptyIcon}
          </div>
          <h3 className="initial-card-title">
            {copy.emptyTitle}
          </h3>
          <p className="initial-card-desc">
            Nhập từ khoá tìm kiếm, chọn các bộ lọc nhanh ở trên hoặc thiết lập tiêu chí chuyên sâu rồi bấm <strong>Tìm kiếm</strong> để bắt đầu tra cứu.
          </p>
          <div className="initial-quick-actions">
            <button
              type="button"
              className="btn btn-secondary btn-sm"
              onClick={() => applyQuickFilter({ location: "Hà Nội" })}
            >
              📍 Tại Hà Nội
            </button>
            <button
              type="button"
              className="btn btn-secondary btn-sm"
              onClick={() => applyQuickFilter({ location: "Hồ Chí Minh" })}
            >
              📍 Tại TP. HCM
            </button>
            {isProspect ? (
              <button
                type="button"
                className="btn btn-secondary btn-sm"
                onClick={() => applyQuickFilter({ product: "credit_card" })}
              >
                💳 Nhu cầu Thẻ tín dụng
              </button>
            ) : (
              <button
                type="button"
                className="btn btn-secondary btn-sm"
                onClick={() => applyQuickFilter({ min_years: "5" })}
              >
                📈 Từ 5 năm kinh nghiệm
              </button>
            )}
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
                  <span className="spinner-mini" /> Đang tra cứu kho hồ sơ…
                </span>
              ) : (
                <span>
                  Tìm thấy <strong>{(searchResults.data?.count ?? 0).toLocaleString("vi-VN")}</strong>{" "}
                  {copy.found}
                </span>
              )}
              {searchResults.data && searchResults.data.count > pageSize && (
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
                    Trang {page + 1} / {Math.ceil(searchResults.data.count / pageSize)}
                  </span>
                  <button
                    type="button"
                    className="btn btn-secondary btn-sm"
                    disabled={(page + 1) * pageSize >= searchResults.data.count || searchResults.isFetching}
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
                        title={`Chọn ${copy.noun} này`}
                        style={{ cursor: "pointer", width: "16px", height: "16px", accentColor: "var(--accent)" }}
                      />
                      <div
                        className="talent-avatar-modern"
                        style={{ background: "var(--accent-gradient)" }}
                      >
                        {(card.display_name || "K")[0]?.toUpperCase()}
                      </div>
                      <div>
                        <div className="talent-name">
                          <Link
                            to={`/person/${card.id}?from=${personFrom}`}
                            onClick={() => setScrollY(window.scrollY)}
                            style={{ fontWeight: 700, fontSize: "15px", color: "var(--text)", textDecoration: "none" }}
                          >
                            {card.display_name || `Person #${card.id}`}
                          </Link>
                          {!isProspect && getSeniorityBadge(card.talent?.years_experience)}
                          {!isProspect && card.needs_review && (
                            <span className="badge err" title="Có xung đột định danh cần giải quyết">
                              Cần xem lại
                            </span>
                          )}
                          {!isProspect && (
                            <span className="source-count-badge">📦 {card.source_count} nguồn</span>
                          )}
                        </div>
                        <div className="talent-title" style={{ marginTop: "2px" }}>
                          <span className="title-text">
                            {card.talent?.current_title || card.headline
                              || copy.titleFallback}
                          </span>
                          {!isProspect && card.talent?.current_company && (
                            <span className="company-text"> @ {card.talent.current_company}</span>
                          )}
                        </div>
                      </div>
                    </div>
                  </div>

                  <div className="talent-meta" style={{ marginTop: "8px" }}>
                    {(card.talent?.location || card.location) && (
                      <span className="meta-item">📍 {card.talent?.location || card.location}</span>
                    )}
                    {!isProspect && card.talent?.years_experience != null && (
                      <span className="meta-item">⏳ {card.talent.years_experience} năm KN</span>
                    )}
                    {!isProspect && card.talent?.owner_name && (
                      <span className="meta-item">👤 Phụ trách: {card.talent.owner_name}</span>
                    )}
                    {!isProspect && card.talent?.last_source_at && (
                      <span className="meta-item">
                        📅 Cập nhật {new Date(card.talent.last_source_at).toLocaleDateString("vi-VN")}
                      </span>
                    )}
                    {card.primary_phone && (
                      <span className="meta-item">
                        📞 {maskSensitiveData ? maskString(card.primary_phone, "phone") : card.primary_phone}
                      </span>
                    )}
                    {card.primary_email && (
                      <span className="meta-item">
                        ✉️ {maskSensitiveData ? maskString(card.primary_email, "email") : card.primary_email}
                      </span>
                    )}
                  </div>

                  {!isProspect && <WorklistBadges person={card} />}

                  {!isProspect && (card.talent?.skills?.length ?? 0) > 0 && (
                    <div className="chips" style={{ marginTop: "8px" }}>
                      {card.talent!.skills.slice(0, 8).map((skill: string) => (
                        <span key={skill} className="chip skill-chip">{skill}</span>
                      ))}
                      {card.talent!.skills.length > 8 && (
                        <span className="chip more">+{card.talent!.skills.length - 8} kỹ năng</span>
                      )}
                    </div>
                  )}

                  <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", borderTop: "1px solid var(--border)", paddingTop: "10px", marginTop: "12px", width: "100%" }}>
                    <Link
                      className="btn btn-secondary btn-sm"
                      to={`/person/${card.id}?from=${personFrom}`}
                      onClick={() => setScrollY(window.scrollY)}
                    >
                      Hồ sơ 360° →
                    </Link>
                    {isProspect && (
                      <CreateOpportunityButton
                        card={card}
                        product={appliedFilters.product}
                        onCreated={showSuccess}
                      />
                    )}
                  </div>
                </div>
              ))}

              {searchResults.data && searchResults.data.results.length === 0 && (
                <div className="empty-results-box">
                  <p>Không có {copy.noun} nào khớp với bộ lọc.</p>
                </div>
              )}
            </div>
          ) : (
            <div
              className="talent-table-wrapper"
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
              <table className="table prospect-table" style={{ margin: 0, minWidth: "850px", width: "100%" }}>
                <thead>
                  <tr>
                    <th style={{ width: "40px" }}>
                      <input
                        type="checkbox"
                        checked={isAllPageSelected}
                        onChange={toggleSelectAllPage}
                        title="Chọn tất cả trên trang"
                        style={{ cursor: "pointer", width: "16px", height: "16px" }}
                      />
                    </th>
                    <th>{copy.nounTitle}</th>
                    <th>Chức danh / Nghề nghiệp</th>
                    <th>{copy.metaColumn}</th>
                    {!isProspect && <th>Kỹ năng</th>}
                    {!isProspect && <th>Liên hệ</th>}
                    <th style={{ textAlign: "right", width: "140px" }}>Thao tác</th>
                  </tr>
                </thead>
                <tbody>
                  {(searchResults.data?.results ?? []).map((card: TalentCard) => (
                    <tr key={card.id}>
                      <td>
                        <input
                          type="checkbox"
                          checked={selectedIds.includes(card.id)}
                          onChange={() => togglePerson(card.id)}
                          style={{ cursor: "pointer", width: "16px", height: "16px" }}
                        />
                      </td>
                      <td>
                        <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
                          <div
                            className="task-avatar"
                            style={{
                              width: "32px",
                              height: "32px",
                              fontSize: "12px",
                              background: "var(--accent-gradient)",
                            }}
                          >
                            {(card.display_name || "K")[0]?.toUpperCase()}
                          </div>
                          <div>
                            <Link
                              to={`/person/${card.id}?from=${personFrom}`}
                              onClick={() => setScrollY(window.scrollY)}
                              style={{ fontWeight: 700, color: "var(--text)", textDecoration: "none" }}
                            >
                              {card.display_name || `Person #${card.id}`}
                            </Link>
                          </div>
                        </div>
                      </td>
                      <td className="table-col-title">
                        <div>{card.talent?.current_title || card.headline || "—"}</div>
                        {!isProspect && (
                          <small className="muted">{card.talent?.current_company || "—"}</small>
                        )}
                      </td>
                      <td className="table-col-meta">
                        <div>{card.talent?.location || card.location || "—"}</div>
                        <small className="muted">
                          {isProspect
                            ? (card.primary_phone || card.primary_email || "—")
                            : (card.talent?.years_experience != null
                                ? `${card.talent.years_experience} năm KN` : "—")}
                        </small>
                      </td>
                      {!isProspect && (
                        <td className="table-col-skills">
                          <div className="chips-compact">
                            {(card.talent?.skills ?? []).slice(0, 3).map((skill: string) => (
                              <span key={skill} className="chip-mini">{skill}</span>
                            ))}
                            {(card.talent?.skills?.length ?? 0) > 3 && (
                              <span className="chip-mini more">+{card.talent!.skills.length - 3}</span>
                            )}
                          </div>
                        </td>
                      )}
                      {!isProspect && (
                        <td className="table-col-contact">
                          <div className="small">
                            {card.primary_email
                              ? (maskSensitiveData ? maskString(card.primary_email, "email") : card.primary_email)
                              : "—"}
                          </div>
                          <div className="small muted">
                            {card.primary_phone
                              ? (maskSensitiveData ? maskString(card.primary_phone, "phone") : card.primary_phone)
                              : "—"}
                          </div>
                        </td>
                      )}
                      <td style={{ textAlign: "right" }}>
                        {isProspect ? (
                          <CreateOpportunityButton
                            card={card}
                            product={appliedFilters.product}
                            onCreated={showSuccess}
                          />
                        ) : (
                          <Link
                            className="btn btn-secondary btn-sm"
                            to={`/person/${card.id}?from=${personFrom}`}
                            onClick={() => setScrollY(window.scrollY)}
                          >
                            Hồ sơ 360° →
                          </Link>
                        )}
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
  );
}
