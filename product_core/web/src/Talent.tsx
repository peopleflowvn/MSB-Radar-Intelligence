import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import React, { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import AiSearch from "./AiSearch";
import { ApiError, SavedView, SearchFilters, TalentCard, api } from "./api";
import { useCustomTheme } from "./CustomThemeContext";
import { useTalentFilterState } from "./searchPersistence";

// Màn hình tìm kiếm Talent (Master Plan mục 19.3).
const EMPTY: SearchFilters = { order: "relevance" };
const PAGE_SIZE = 50;

type TalentTabMode = "ai" | "loc";

/** Thanh bộ lọc đã lưu (Saved Views) */
function SavedViewsBar({
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
    queryKey: ["saved-views", "talent"],
    queryFn: () => api.savedViews("talent"),
    retry: false,
  });

  function refresh() {
    queryClient.invalidateQueries({ queryKey: ["saved-views", "talent"] });
  }

  const save = useMutation({
    mutationFn: () =>
      api.saveView(
        "talent",
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
    <div className="saved-views-modern">
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
              + Lưu bộ lọc hiện tại
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

function maskString(
  str?: string | null,
  type: "email" | "phone" = "phone",
): string {
  if (!str) return "";
  if (type === "email") {
    const parts = str.split("@");
    if (parts.length < 2) return str;
    const name = parts[0];
    return `${name.slice(0, 2)}***@${parts[1]}`;
  }
  if (str.length < 7) return str;
  return `${str.slice(0, 4)}***${str.slice(-3)}`;
}

function getSeniorityBadge(years?: number | null) {
  if (years == null) return null;
  if (years >= 5)
    return (
      <span className="seniority-badge lead">Lead / Senior ({years}y+)</span>
    );
  if (years >= 2)
    return <span className="seniority-badge mid">Mid-level ({years}y)</span>;
  return <span className="seniority-badge junior">Junior ({years}y)</span>;
}

function WorklistBadges({ person }: { person: TalentCard }) {
  if (!person.active_worklists?.length) return null;
  const owners = new Set(
    person.active_worklists.map((row) => row.assigned_to_name).filter(Boolean),
  );
  return (
    <div className="chips">
      {owners.size > 1 && (
        <span className="badge err">⚠ Nhiều người đang xử lý</span>
      )}
      {person.active_worklists.slice(0, 3).map((row) => (
        <span
          key={row.hunt_id}
          className={`chip rel rel-${row.state}`}
          title={row.note || undefined}
        >
          {row.title}: <strong>{row.state_label}</strong>
          {row.assigned_to_name && ` · ${row.assigned_to_name}`}
        </span>
      ))}
    </div>
  );
}

function Card({
  person,
  selected,
  onToggle,
  onOpen,
}: {
  person: TalentCard;
  selected: boolean;
  onToggle: () => void;
  onOpen: () => void;
}) {
  const { maskSensitiveData } = useCustomTheme();
  const t = person.talent;
  const name = person.display_name || "(Chưa rõ tên)";
  const initial = name.charAt(0).toUpperCase();

  const phoneDisplay =
    maskSensitiveData && person.primary_phone
      ? maskString(person.primary_phone, "phone")
      : person.primary_phone;

  const emailDisplay =
    maskSensitiveData && person.primary_email
      ? maskString(person.primary_email, "email")
      : person.primary_email;

  return (
    <Link to={`/person/${person.id}?from=talent-filter`} onClick={onOpen} className="talent-card-modern">
      <input
        className="talent-select-checkbox"
        aria-label={`Chọn ${name}`}
        type="checkbox"
        checked={selected}
        readOnly
        onClick={(event) => {
          event.preventDefault();
          event.stopPropagation();
          onToggle();
        }}
      />
      <div className="talent-card-left">
        <div className="talent-avatar-modern">{initial}</div>
        <div className="talent-main">
          <div className="talent-name">
            <span className="talent-name-text">{name}</span>
            {getSeniorityBadge(t?.years_experience)}
            {person.needs_review && (
              <span
                className="badge err"
                title="Có xung đột định danh cần giải quyết"
              >
                Cần xem lại
              </span>
            )}
            <span className="source-count-badge">
              📦 {person.source_count} nguồn
            </span>
          </div>

          <div className="talent-title">
            <span className="title-text">
              {t?.current_title || person.headline || "Chưa cập nhật chức danh"}
            </span>
            {t?.current_company && (
              <span className="company-text"> @ {t.current_company}</span>
            )}
          </div>

          <div className="talent-meta">
            {t?.location && <span className="meta-item">📍 {t.location}</span>}
            {t?.years_experience != null && (
              <span className="meta-item">⏳ {t.years_experience} năm KN</span>
            )}
            {t?.owner_name && (
              <span className="meta-item">👤 Phụ trách: {t.owner_name}</span>
            )}
            {t?.last_source_at && (
              <span className="meta-item">
                📅 Cập nhật{" "}
                {new Date(t.last_source_at).toLocaleDateString("vi-VN")}
              </span>
            )}
          </div>

          <WorklistBadges person={person} />

          {t?.skills && t.skills.length > 0 && (
            <div className="chips">
              {t.skills.slice(0, 8).map((skill) => (
                <span key={skill} className="chip skill-chip">
                  {skill}
                </span>
              ))}
              {t.skills.length > 8 && (
                <span className="chip more">
                  +{t.skills.length - 8} kỹ năng
                </span>
              )}
            </div>
          )}
        </div>
      </div>

      <div className="talent-card-right">
        <div className="talent-contact-box">
          <div className="contact-line">
            <span className="contact-icon">✉️</span>
            <span>
              {emailDisplay || <span className="muted">Chưa có email</span>}
            </span>
          </div>
          <div className="contact-line">
            <span className="contact-icon">📞</span>
            <span>
              {phoneDisplay || <span className="muted">Chưa có SĐT</span>}
            </span>
          </div>
        </div>
        <span className="btn btn-secondary btn-sm profile-action-btn">
          Hồ sơ 360° →
        </span>
      </div>
    </Link>
  );
}

function CompactTableRow({
  person,
  selected,
  onToggle,
  onOpen,
}: {
  person: TalentCard;
  selected: boolean;
  onToggle: () => void;
  onOpen: () => void;
}) {
  const { maskSensitiveData } = useCustomTheme();
  const t = person.talent;
  const name = person.display_name || "(Chưa rõ tên)";

  const phoneDisplay =
    maskSensitiveData && person.primary_phone
      ? maskString(person.primary_phone, "phone")
      : person.primary_phone;

  const emailDisplay =
    maskSensitiveData && person.primary_email
      ? maskString(person.primary_email, "email")
      : person.primary_email;

  return (
    <tr className="talent-table-row">
      <td>
        <input
          aria-label={`Chọn ${name}`}
          type="checkbox"
          checked={selected}
          onChange={onToggle}
        />
      </td>
      <td className="table-col-name">
        <Link to={`/person/${person.id}?from=talent-filter`} onClick={onOpen} className="table-name-link">
          <strong>{name}</strong>
        </Link>
      </td>
      <td className="table-col-title">
        <div>{t?.current_title || person.headline || "—"}</div>
        <small className="muted">{t?.current_company || "—"}</small>
      </td>
      <td className="table-col-meta">
        <div>{t?.location || "—"}</div>
        <small className="muted">
          {t?.years_experience != null ? `${t.years_experience} năm KN` : "—"}
        </small>
      </td>
      <td className="table-col-skills">
        <div className="chips-compact">
          {(t?.skills || []).slice(0, 3).map((s) => (
            <span key={s} className="chip-mini">
              {s}
            </span>
          ))}
          {(t?.skills || []).length > 3 && (
            <span className="chip-mini more">
              +{(t?.skills || []).length - 3}
            </span>
          )}
        </div>
      </td>
      <td className="table-col-contact">
        <div className="small">{emailDisplay || "—"}</div>
        <div className="small muted">{phoneDisplay || "—"}</div>
      </td>
      <td className="table-col-action" style={{ textAlign: "right" }}>
        <Link to={`/person/${person.id}?from=talent-filter`} onClick={onOpen} className="btn btn-secondary btn-sm">
          Xem 360°
        </Link>
      </td>
    </tr>
  );
}

export default function Talent({
  initialMode = "ai",
  onNavigateTab,
}: {
  initialMode?: TalentTabMode;
  onNavigateTab?: (tab: "tasks" | "pipeline" | "lists") => void;
} = {}) {
  const [searchParams] = useSearchParams();
  const tabParam = searchParams.get("tab");
  const [mode, setMode] = useState<TalentTabMode>(
    tabParam === "filter" ? "loc" : initialMode
  );

  useEffect(() => {
    if (tabParam === "filter") {
      setMode("loc");
    } else if (tabParam === "talent") {
      setMode("ai");
    }
  }, [tabParam]);
  const { draft, setDraft, applied, setApplied, hasSearched, setHasSearched,
    showAdvanced, setShowAdvanced, viewMode, setViewMode, page, setPage,
    scrollY, setScrollY, history: filterHistory, rememberFilter, clearHistory } = useTalentFilterState();
  const [filterError, setFilterError] = useState("");
  const [selectedIds, setSelectedIds] = useState<number[]>([]);
  const [worklistTitle, setWorklistTitle] = useState("");
  const [targetHunt, setTargetHunt] = useState("");
  const [successMsg, setSuccessMsg] = useState<string | null>(null);
  const queryClient = useQueryClient();
  const facets = useQuery({
    queryKey: ["talent-facets"],
    queryFn: api.talentFacets,
  });
  const filterHistoryQuery = useQuery({
    queryKey: ["filter-history", "talent"],
    queryFn: () => api.filterHistory("talent"),
    retry: false,
  });

  const results = useQuery({
    queryKey: ["talent-search", applied, page],
    queryFn: () => api.talentSearch(applied, PAGE_SIZE, page * PAGE_SIZE),
    enabled: hasSearched,
    retry: false,
  });
  useEffect(() => {
    if (mode !== "loc" || !hasSearched || !results.data || scrollY <= 0) return;
    const timer = window.setTimeout(() => window.scrollTo({ top: scrollY, behavior: "instant" }), 0);
    return () => window.clearTimeout(timer);
  }, [mode, hasSearched, results.data, scrollY]);
  const hunts = useQuery({
    queryKey: ["hunts", "open-from-talent"],
    queryFn: () => api.hunts({ open: true, mine: true }),
    enabled: selectedIds.length > 0,
  });
  const createWorklist = useMutation({
    mutationFn: () =>
      api.createShortlist({
        title: worklistTitle.trim(),
        person_ids: selectedIds,
      }),
    onSuccess: () => {
      const count = selectedIds.length;
      setSelectedIds([]);
      setWorklistTitle("");
      setSuccessMsg(`✓ Đã tạo đợt tuyển mới từ ${count} ứng viên đã chọn!`);
      queryClient.invalidateQueries({ queryKey: ["hunts"] });
      queryClient.invalidateQueries({ queryKey: ["hunt-tasks"] });
      setTimeout(() => setSuccessMsg(null), 6000);
    },
  });
  const addToWorklist = useMutation({
    mutationFn: () =>
      api.huntUpdate(Number(targetHunt), { person_ids_add: selectedIds }),
    onSuccess: () => {
      const count = selectedIds.length;
      setSelectedIds([]);
      setTargetHunt("");
      setSuccessMsg(`✓ Đã thêm ${count} ứng viên vào đợt tuyển thành công!`);
      queryClient.invalidateQueries({ queryKey: ["hunts"] });
      queryClient.invalidateQueries({ queryKey: ["hunt-tasks"] });
      queryClient.invalidateQueries({ queryKey: ["talent-search"] });
      setTimeout(() => setSuccessMsg(null), 6000);
    },
  });
  const togglePerson = (id: number) =>
    setSelectedIds((current) =>
      current.includes(id)
        ? current.filter((value) => value !== id)
        : [...current, id],
    );

  function set<K extends keyof SearchFilters>(key: K, value: SearchFilters[K]) {
    setDraft((current) => ({ ...current, [key]: value }));
  }

  function recordFilter(filters: SearchFilters) {
    rememberFilter(filters);
    const hasCriteria = Object.entries(filters).some(([key, value]) =>
      key !== "order" && value !== "" && value !== false && value !== undefined && value !== null);
    if (!hasCriteria) return;
    void api.recordFilterHistory("talent", filters)
      .then(() => queryClient.invalidateQueries({ queryKey: ["filter-history", "talent"] }))
      .catch(() => undefined);
  }

  function submit(event: React.FormEvent) {
    event.preventDefault();
    const min = draft.min_years === "" || draft.min_years == null ? null : Number(draft.min_years);
    const max = draft.max_years === "" || draft.max_years == null ? null : Number(draft.max_years);
    if (min != null && max != null && min > max) {
      setFilterError("Số năm kinh nghiệm tối thiểu không thể lớn hơn tối đa.");
      setShowAdvanced(true);
      return;
    }
    setFilterError("");
    setApplied(draft);
    setHasSearched(true);
    setPage(0);
    recordFilter(draft);
  }

  function reset() {
    setDraft(EMPTY);
    setApplied(EMPTY);
    setHasSearched(false);
    setFilterError("");
    setPage(0);
    setScrollY(0);
  }

  function applyQuickFilter(patch: Partial<SearchFilters>) {
    const updated = { ...draft, ...patch };
    setDraft(updated);
    setApplied(updated);
    setHasSearched(true);
    setPage(0);
    recordFilter(updated);
  }

  function reopenFilter(filters: SearchFilters) {
    setDraft(filters);
    setApplied(filters);
    setHasSearched(true);
    setPage(0);
    recordFilter(filters);
  }

  function filterSummary(filters: SearchFilters) {
    const labels: Partial<Record<keyof SearchFilters, string>> = {
      q: "Từ khoá", skills: "Kỹ năng", title: "Vai trò", location: "Khu vực",
      company: "Công ty", desired_location: "Nơi muốn làm", seniority: "Cấp bậc",
      education: "Học vấn", job_type: "Hình thức", foreign_language: "Ngoại ngữ",
      source: "Nguồn", relationship: "Quan hệ", pool: "Pool", owner: "Phụ trách",
      min_years: "KN từ", max_years: "KN đến", has_email: "Có email", has_phone: "Có SĐT",
    };
    const parts = Object.entries(filters).filter(([key, value]) => key !== "order" && value !== "" && value !== false && value != null)
      .map(([key, value]) => `${labels[key as keyof SearchFilters] ?? key}: ${value === true ? "Có" : value}`);
    return parts.slice(0, 3).join(" · ") + (parts.length > 3 ? ` · +${parts.length - 3}` : "");
  }

  const activeFilterCount = Object.keys(applied).filter(
    (k) => k !== "order" && applied[k as keyof SearchFilters],
  ).length;
  const filterLabels: Partial<Record<keyof SearchFilters, string>> = {
    q: "Từ khoá", skills: "Kỹ năng", title: "Vai trò", location: "Khu vực",
    company: "Công ty/ngành", desired_location: "Nơi muốn làm", seniority: "Cấp bậc",
    education: "Học vấn", job_type: "Hình thức", foreign_language: "Ngoại ngữ",
    source: "Nguồn", relationship: "Quan hệ", pool: "Pool", owner: "Phụ trách",
    min_years: "KN từ", max_years: "KN đến", has_email: "Có email", has_phone: "Có SĐT",
  };
  const activeFilters = Object.entries(applied).filter(
    ([key, value]) => key !== "order" && value !== "" && value !== false && value != null,
  ) as Array<[keyof SearchFilters, SearchFilters[keyof SearchFilters]]>;
  const serverHistory = (filterHistoryQuery.data?.results ?? []).map((row) => ({
    id: `server-${row.id}`, filters: row.filters, createdAt: new Date(row.used_at).getTime(),
  }));
  const serverSignatures = new Set(serverHistory.map((row) => JSON.stringify(row.filters)));
  const historyRows = [...serverHistory,
    ...filterHistory.filter((row) => !serverSignatures.has(JSON.stringify(row.filters)))].slice(0, 12);

  function clearFilterHistory() {
    clearHistory();
    void api.clearFilterHistory("talent")
      .then(() => queryClient.invalidateQueries({ queryKey: ["filter-history", "talent"] }))
      .catch(() => undefined);
  }

  function removeFilter(key: keyof SearchFilters) {
    const updated = { ...applied, [key]: undefined };
    setDraft(updated);
    setApplied(updated);
    setPage(0);
  }

  return (
    <div className="talent-container full-page-ai-glow">
      {/* Dynamic Animated AI Glow Spheres */}
      <div className="ai-ambient-glow">
        <div className="glow-orb orb-1" />
        <div className="glow-orb orb-2" />
        <div className="glow-orb orb-3" />
      </div>

      <div className="talent-content-relative">
        {successMsg && (
          <div className="talent-success-banner">
            <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
              <span>{successMsg}</span>
            </div>
            {onNavigateTab && (
              <button
                type="button"
                className="btn btn-primary btn-sm"
                onClick={() => onNavigateTab("tasks")}
              >
                👉 Chuyển sang Nhiệm vụ xử lý ngay →
              </button>
            )}
          </div>
        )}

        {mode === "ai" && <AiSearch />}

        {mode === "loc" && (
          <div className="talent-filter-workspace">
            {/* Saved Views Bar */}
            <SavedViewsBar
              applied={applied}
              onApply={(filters) => {
                reopenFilter(filters);
              }}
            />

            {historyRows.length > 0 && (
              <div className="saved-views-modern" aria-label="Lịch sử lọc">
                <div className="saved-views-label"><span>🕘 Lịch sử lọc:</span></div>
                <div className="saved-views-chips">
                  {historyRows.map((row) => (
                    <button key={row.id} type="button" className="filter-history-chip"
                      title={new Date(row.createdAt).toLocaleString("vi-VN")}
                      onClick={() => reopenFilter(row.filters)}>
                      <span>{filterSummary(row.filters)}</span>
                      <span className="filter-history-time">{new Date(row.createdAt).toLocaleString("vi-VN", {
                        day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit",
                      })}</span>
                    </button>
                  ))}
                  <button type="button" className="btn btn-ghost btn-sm" onClick={clearFilterHistory}>Xoá lịch sử</button>
                </div>
              </div>
            )}

            {selectedIds.length > 0 && (
              <div className="talent-bulk-selected-panel">
                <div className="result-head" style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                  <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                    <span className="badge ok" style={{ fontSize: "13px", padding: "4px 10px" }}>
                      Đã chọn <strong>{selectedIds.length}</strong> ứng viên tiềm năng
                    </span>
                  </div>
                  <button className="btn btn-ghost btn-sm" onClick={() => setSelectedIds([])}>
                    Bỏ chọn tất cả
                  </button>
                </div>
                <p className="hint" style={{ margin: "6px 0 12px", fontSize: "13px" }}>
                  Đưa ứng viên đã chọn vào đợt tuyển để phân công phụ trách và theo dõi tiến độ săn ngay trong studio:
                </p>
                <div className="search-row" style={{ display: "flex", gap: "10px", flexWrap: "wrap", alignItems: "center" }}>
                  <select
                    className="config-select"
                    style={{ minWidth: "220px" }}
                    value={targetHunt}
                    onChange={(event) => setTargetHunt(event.target.value)}
                  >
                    <option value="">Chọn đợt tuyển đang mở…</option>
                    {(hunts.data?.results ?? []).map((hunt) => (
                      <option key={hunt.id} value={hunt.id}>
                        {hunt.title || hunt.hiring_need_title}
                      </option>
                    ))}
                  </select>
                  <button
                    type="button"
                    className="btn btn-primary btn-sm"
                    disabled={!targetHunt || addToWorklist.isPending}
                    onClick={() => addToWorklist.mutate()}
                  >
                    {addToWorklist.isPending ? "Đang thêm…" : "Thêm vào đợt tuyển"}
                  </button>

                  <span className="muted" style={{ fontSize: "12px", margin: "0 4px" }}>hoặc</span>

                  <input
                    className="search-main"
                    style={{ minWidth: "200px" }}
                    value={worklistTitle}
                    onChange={(event) => setWorklistTitle(event.target.value)}
                    placeholder="Tên đợt tuyển mới…"
                  />
                  <button
                    type="button"
                    className="btn btn-secondary btn-sm"
                    disabled={!worklistTitle.trim() || createWorklist.isPending}
                    onClick={() => createWorklist.mutate()}
                  >
                    {createWorklist.isPending ? "Đang tạo…" : "+ Tạo đợt mới"}
                  </button>
                </div>
                {(createWorklist.error || addToWorklist.error) && (
                  <p className="err-box" style={{ marginTop: "10px" }}>
                    {String(createWorklist.error || addToWorklist.error)}
                  </p>
                )}
              </div>
            )}

            {/* Main Search & Smart Filter Panel */}
            <div className="search-filter-card">
              <form onSubmit={submit}>
                {/* Main search bar */}
                <div className="search-main-row">
                  <div className="search-input-wrapper">
                    <span className="search-icon">🔍</span>
                    <input
                      type="search"
                      className="search-main-input"
                      placeholder='Tìm theo tên ứng viên, kỹ năng, chức danh, công ty cũ…'
                      value={draft.q ?? ""}
                      onChange={(event) => set("q", event.target.value)}
                    />
                  </div>
                  <button type="submit" className="btn btn-primary">
                    Tìm kiếm
                  </button>
                  {(activeFilterCount > 0 || hasSearched) && (
                    <button
                      type="button"
                      className="btn btn-ghost"
                      onClick={reset}
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
                        location:
                          draft.location === "Hồ Chí Minh" ? "" : "Hồ Chí Minh",
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
                    🏆 Senior (từ 5 năm)
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
                    👔 Quản lý / Lead (từ 8 năm)
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
                    🎯 Mới trong kho
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
                  <button type="button" className="btn btn-ghost btn-sm"
                    aria-expanded={showAdvanced} onClick={() => setShowAdvanced((value) => !value)}>
                    {showAdvanced ? "Ẩn bộ lọc nâng cao" : `Bộ lọc nâng cao${activeFilterCount ? ` (${activeFilterCount})` : ""}`}
                  </button>
                </div>

                {activeFilters.length > 0 && (
                  <div className="chips" aria-label="Bộ lọc đang áp dụng">
                    {activeFilters.map(([key, value]) => (
                      <button type="button" className="chip" key={key}
                        title="Bỏ điều kiện này" onClick={() => removeFilter(key)}>
                        {filterLabels[key] ?? key}: <strong>{value === true ? "Có" : String(value)}</strong> ×
                      </button>
                    ))}
                  </div>
                )}

                {/* Detailed Criteria Grid */}
                {showAdvanced && <div className="filter-criteria-grid">
                  <Field
                    label="Kỹ năng / Chuyên môn"
                    icon="🛠️"
                    hint="Hỗ trợ OR, AND, NOT (VD: React OR Vue)"
                    placeholder="VD: (SQL OR Python) NOT PHP"
                    value={draft.skills ?? ""}
                    onChange={(event) => set("skills", event.target.value)}
                  />
                  <Field
                    label="Vai trò / Nghề nghiệp"
                    icon="💼"
                    placeholder='VD: (Lead OR Manager) NOT "Thực tập"'
                    value={draft.title ?? ""}
                    onChange={(event) => set("title", event.target.value)}
                  />
                  <Field
                    label="Khu vực / Tỉnh thành"
                    icon="📍"
                    placeholder="VD: Hà Nội OR Hồ Chí Minh"
                    value={draft.location ?? ""}
                    onChange={(event) => set("location", event.target.value)}
                  />
                  <Field
                    label="Đơn vị / Ngành từng làm"
                    icon="🏢"
                    placeholder="VD: FPT OR Techcombank OR MB"
                    value={draft.company ?? ""}
                    onChange={(event) => set("company", event.target.value)}
                  />
                  <Field
                    label="Nơi làm việc mong muốn"
                    icon="🧭"
                    placeholder="VD: Hà Nội OR Đà Nẵng"
                    value={draft.desired_location ?? ""}
                    onChange={(event) => set("desired_location", event.target.value)}
                  />
                  <Field
                    label="Cấp bậc"
                    icon="📈"
                    placeholder="VD: Senior OR Manager"
                    value={draft.seniority ?? ""}
                    onChange={(event) => set("seniority", event.target.value)}
                  />
                  <Field
                    label="Học vấn"
                    icon="🎓"
                    placeholder="VD: Đại học OR Thạc sĩ"
                    value={draft.education ?? ""}
                    onChange={(event) => set("education", event.target.value)}
                  />
                  <Field
                    label="Hình thức làm việc"
                    icon="🗓️"
                    placeholder="VD: Toàn thời gian OR Hybrid"
                    value={draft.job_type ?? ""}
                    onChange={(event) => set("job_type", event.target.value)}
                  />
                  <Field
                    label="Ngoại ngữ"
                    icon="🌐"
                    placeholder="VD: Tiếng Anh AND IELTS"
                    value={draft.foreign_language ?? ""}
                    onChange={(event) => set("foreign_language", event.target.value)}
                  />
                  <div className="filter-col-group">
                    <label className="filter-label">Nguồn dữ liệu</label>
                    <select
                      className="select-dropdown"
                      value={draft.source ?? ""}
                      onChange={(event) => set("source", event.target.value)}
                    >
                      <option value="">Tất cả nguồn</option>
                      {(facets.data?.by_source ?? []).map((row) => (
                        <option key={row.source} value={row.source}>
                          {row.source} ({row.count})
                        </option>
                      ))}
                    </select>
                  </div>
                  <div className="filter-col-group">
                    <label className="filter-label">Quan hệ ứng viên</label>
                    <select
                      className="select-dropdown"
                      value={draft.relationship ?? ""}
                      onChange={(event) =>
                        set("relationship", event.target.value)
                      }
                    >
                      <option value="">Tất cả trạng thái</option>
                      {(facets.data?.relationships ?? []).map((row) => (
                        <option key={row.value} value={row.value}>
                          {row.label}
                        </option>
                      ))}
                    </select>
                  </div>
                  <div className="filter-col-group">
                    <label className="filter-label">Đợt tuyển &amp; Pool</label>
                    <select
                      className="select-dropdown"
                      value={draft.pool ?? ""}
                      onChange={(event) => set("pool", event.target.value)}
                    >
                      <option value="">Tất cả đợt tuyển &amp; pool</option>
                      {(facets.data?.pools ?? []).map((row) => (
                        <option key={row.id} value={row.id}>
                          {row.name} ({row.member_count})
                        </option>
                      ))}
                    </select>
                  </div>
                  <div className="filter-col-group">
                    <label className="filter-label">
                      Recruiter phụ trách
                    </label>
                    <select
                      className="select-dropdown"
                      value={draft.owner ?? ""}
                      onChange={(event) => set("owner", event.target.value)}
                    >
                      <option value="">Tất cả chuyên viên</option>
                      {(facets.data?.owners ?? []).map((row) => (
                        <option key={row.id} value={row.id}>
                          {row.name}
                        </option>
                      ))}
                    </select>
                  </div>
                  <div className="filter-col-group">
                    <label className="filter-label">
                      <span className="field-icon">⏳</span> Kinh nghiệm (năm)
                    </label>
                    <div className="years-range-inputs">
                      <input
                        className="input-text filter-input"
                        type="number"
                        min={0}
                        placeholder="Từ (năm)"
                        value={draft.min_years ?? ""}
                        onChange={(event) =>
                          set("min_years", event.target.value)
                        }
                      />
                      <input
                        className="input-text filter-input"
                        type="number"
                        min={0}
                        placeholder="Đến (năm)"
                        value={draft.max_years ?? ""}
                        onChange={(event) =>
                          set("max_years", event.target.value)
                        }
                      />
                    </div>
                  </div>
                </div>}

                {filterError && <p className="err-box" role="alert">{filterError}</p>}

                {/* Toggles & Sắp xếp */}
                <div className="filter-bottom-bar">
                  <div className="filter-toggles-group">
                    <label className="checkbox-pill">
                      <input
                        type="checkbox"
                        checked={!!draft.has_email}
                        onChange={(event) =>
                          set("has_email", event.target.checked)
                        }
                      />
                      <span>Có Email</span>
                    </label>
                    <label className="checkbox-pill">
                      <input
                        type="checkbox"
                        checked={!!draft.has_phone}
                        onChange={(event) =>
                          set("has_phone", event.target.checked)
                        }
                      />
                      <span>Có Số điện thoại</span>
                    </label>
                  </div>

                  <div className="filter-sort-group">
                    <label className="sort-label">Sắp xếp theo:</label>
                    <select
                      className="select-dropdown"
                      value={draft.order ?? "relevance"}
                      onChange={(event) => set("order", event.target.value)}
                    >
                      <option value="relevance">🌟 Phù hợp nhất</option>
                      <option value="newest">📅 Mới cập nhật nhất</option>
                      <option value="oldest">⏳ Cũ nhất</option>
                      <option value="name">🔤 Theo bảng chữ cái tên</option>
                    </select>
                    <button type="submit" className="btn btn-primary" disabled={results.isFetching}>
                      {results.isFetching ? "Đang tìm…" : "Áp dụng bộ lọc"}
                    </button>
                  </div>
                </div>
              </form>
            </div>

            {/* Trạng thái ban đầu: Chưa thực hiện tìm kiếm */}
            {!hasSearched && (
              <div className="talent-search-initial-card">
                <div className="initial-card-icon">⚡</div>
                <h3 className="initial-card-title">Kho Dữ Liệu Nhân Tài Đa Nguồn</h3>
                <p className="initial-card-desc">
                  Nhập từ khoá tìm kiếm, chọn các bộ lọc nhanh ở trên hoặc thiết lập tiêu chí chuyên sâu rồi bấm <strong>Tìm kiếm</strong> để bắt đầu tra cứu.
                </p>
                <div className="initial-quick-actions">
                  <button
                    type="button"
                    className="btn btn-secondary btn-sm"
                    onClick={() => applyQuickFilter({ location: "Hà Nội" })}
                  >
                    📍 Ứng viên tại Hà Nội
                  </button>
                  <button
                    type="button"
                    className="btn btn-secondary btn-sm"
                    onClick={() => applyQuickFilter({ location: "Hồ Chí Minh" })}
                  >
                    📍 Ứng viên tại TP. HCM
                  </button>
                  <button
                    type="button"
                    className="btn btn-secondary btn-sm"
                    onClick={() => applyQuickFilter({ min_years: "5" })}
                  >
                    🏆 Nhân sự Senior (từ 5 năm)
                  </button>
                  <button
                    type="button"
                    className="btn btn-primary btn-sm"
                    onClick={() => {
                      setApplied(draft);
                      setHasSearched(true);
                    }}
                  >
                    🚀 Khám phá toàn bộ kho hồ sơ
                  </button>
                </div>
              </div>
            )}

            {/* Results Section: Chỉ hiển thị khi hasSearched === true */}
            {hasSearched && (
              <>
                {results.error && (
                  <div className="error-box" role="alert">
                    Không tải được kết quả:{" "}
                    {results.error instanceof ApiError
                      ? results.error.message
                      : "Lỗi không xác định"}
                    <button
                      type="button"
                      className="btn btn-secondary btn-sm"
                      onClick={() => results.refetch()}
                    >
                      Thử lại
                    </button>
                  </div>
                )}
                <div className="results-header-toolbar">
                  <div className="results-count-badge">
                    {results.isFetching ? (
                      <span className="loading-text">
                        <span className="spinner-mini" /> Đang truy vấn kho ứng
                        viên...
                      </span>
                    ) : (
                      <span>
                        Tìm thấy{" "}
                        <strong>
                          {(results.data?.count ?? 0).toLocaleString("vi-VN")}
                        </strong>{" "}
                        hồ sơ nhân tài
                      </span>
                    )}
                    {results.data && results.data.count > PAGE_SIZE && (
                      <nav className="pagination" aria-label="Phân trang kết quả">
                        <button
                          type="button"
                          className="btn btn-secondary btn-sm"
                          disabled={page === 0 || results.isFetching}
                          onClick={() => setPage((value) => Math.max(0, value - 1))}
                        >
                          ← Trang trước
                        </button>
                        <span>
                          Trang {page + 1} /{" "}
                          {Math.ceil(results.data.count / PAGE_SIZE)}
                        </span>
                        <button
                          type="button"
                          className="btn btn-secondary btn-sm"
                          disabled={
                            (page + 1) * PAGE_SIZE >= results.data.count ||
                            results.isFetching
                          }
                          onClick={() => setPage((value) => value + 1)}
                        >
                          Trang sau →
                        </button>
                      </nav>
                    )}
                  </div>

                  <div className="results-actions-right">
                    {/* Chuyển chế độ xem Cards vs Table */}
                    <div className="view-mode-toggle">
                      <button
                        type="button"
                        className={`view-btn ${viewMode === "cards" ? "active" : ""}`}
                        onClick={() => setViewMode("cards")}
                        title="Xem dạng thẻ chi tiết"
                      >
                        ⊞ Thẻ
                      </button>
                      <button
                        type="button"
                        className={`view-btn ${viewMode === "table" ? "active" : ""}`}
                        onClick={() => setViewMode("table")}
                        title="Xem dạng bảng cô đọng"
                      >
                        ≡ Bảng
                      </button>
                    </div>

                    {results.data && results.data.results.length > 0 && (
                      <a
                        className="btn btn-secondary btn-sm"
                        href={api.talentExportUrl(applied)}
                        download
                      >
                        ⬇ Xuất CSV
                      </a>
                    )}
                  </div>
                </div>

                {viewMode === "cards" ? (
                  <div className="talent-cards-grid">
                    {(results.data?.results ?? []).map((person) => (
                      <Card
                        key={person.id}
                        person={person}
                        selected={selectedIds.includes(person.id)}
                        onToggle={() => togglePerson(person.id)}
                        onOpen={() => setScrollY(window.scrollY)}
                      />
                    ))}
                    {results.data && results.data.results.length === 0 && (
                      <div className="empty-results-box">
                        <div className="empty-icon">🔍</div>
                        <h3>Không tìm thấy ứng viên phù hợp</h3>
                        <p>
                          Thử nới lỏng các tiêu chí kỹ năng, số năm kinh nghiệm hoặc
                          xoá bộ lọc để tìm kiếm rộng hơn.
                        </p>
                        <button
                          type="button"
                          className="btn btn-secondary"
                          onClick={reset}
                        >
                          Xoá toàn bộ bộ lọc
                        </button>
                      </div>
                    )}
                  </div>
                ) : (
                  <div className="talent-table-wrapper">
                    <table className="talent-modern-table">
                      <thead>
                        <tr>
                          <th>Chọn</th>
                          <th>Họ &amp; Tên</th>
                          <th>Chức danh &amp; Công ty</th>
                          <th>Địa điểm &amp; KN</th>
                          <th>Kỹ năng nổi bật</th>
                          <th>Thông tin liên hệ</th>
                          <th style={{ textAlign: "right" }}>Thao tác</th>
                        </tr>
                      </thead>
                      <tbody>
                        {(results.data?.results ?? []).map((person) => (
                          <CompactTableRow
                            key={person.id}
                            person={person}
                            selected={selectedIds.includes(person.id)}
                            onToggle={() => togglePerson(person.id)}
                            onOpen={() => setScrollY(window.scrollY)}
                          />
                        ))}
                      </tbody>
                    </table>
                    {results.data && results.data.results.length === 0 && (
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
