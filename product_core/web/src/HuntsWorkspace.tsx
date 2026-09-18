import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Link, Navigate, useSearchParams } from "react-router-dom";
import { api, HuntTaskRow } from "./api";
import { Candidate, CandidateGroup, CreateShortlist, HuntCard } from "./Hunts";

const PAGE_SIZE = 30;

const RELATIONSHIP_LABELS: Record<string, string> = {
  new: "Mới trong kho",
  attempted: "Đã thử liên hệ",
  connected: "Đã kết nối",
  interested: "Có quan tâm",
  nurturing: "Đang chăm sóc",
  ready: "Sẵn sàng cho cơ hội",
  placed: "Đã tuyển",
  unavailable: "Chưa sẵn sàng",
  do_not_contact: "Không liên hệ",
};

function dateTime(value: string | null) {
  return value ? new Date(value).toLocaleString("vi-VN") : "—";
}

function RelationshipTask({
  row,
  hunts,
}: {
  row: HuntTaskRow;
  hunts: Array<{ id: number; title: string }>;
}) {
  const queryClient = useQueryClient();
  const [huntId, setHuntId] = useState("");
  const refresh = () =>
    queryClient.invalidateQueries({ queryKey: ["hunt-tasks"] });
  const update = useMutation({
    mutationFn: (patch: Record<string, unknown>) =>
      api.talentRelationshipUpdate(row.person_id, patch),
    onSuccess: refresh,
  });
  const add = useMutation({
    mutationFn: () =>
      api.huntUpdate(Number(huntId), { person_ids_add: [row.person_id] }),
    onSuccess: () => {
      setHuntId("");
      refresh();
      queryClient.invalidateQueries({ queryKey: ["hunts"] });
    },
  });
  const inSevenDays = () => {
    const value = new Date();
    value.setDate(value.getDate() + 7);
    update.mutate({
      next_action_at: value.toISOString(),
      next_action: row.relationship.next_action || "Liên hệ lại",
    });
  };
  const contacted = () => {
    const value = new Date();
    value.setDate(value.getDate() + 7);
    update.mutate({
      state: "connected",
      last_contact_at: new Date().toISOString(),
      next_action: "Đánh giá phản hồi sau lần liên hệ gần nhất",
      next_action_at: value.toISOString(),
    });
  };
  return (
    <div className="modern-task-card">
      <div className="task-card-header">
        <div className="task-avatar-wrap">
          <div className="task-avatar">{(row.display_name || "U")[0]?.toUpperCase()}</div>
          <div>
            <Link className="task-person-name" to={`/person/${row.person_id}?from=talent`}>
              {row.display_name}
            </Link>
            <div className="task-person-meta">
              <span>{row.headline || "Chưa có chức danh"}</span>
              <span className="dot-sep">•</span>
              <span>Chăm sóc dài hạn</span>
            </div>
          </div>
        </div>
        <div className="task-badges">
          {row.is_overdue && <span className="status-badge overdue">⚠️ Quá hạn</span>}
          <span className="status-badge neutral">
            {RELATIONSHIP_LABELS[row.relationship.state] || row.relationship.state}
          </span>
        </div>
      </div>

      <div className="task-action-box">
        <span className="action-tag">Hành động tiếp theo:</span>
        <p className="action-text">
          {row.relationship.next_action || "Chưa có ghi chú hành động tiếp theo"}
        </p>
      </div>

      <div className="task-meta-grid">
        <div className="meta-item">
          <span className="meta-lbl">Đến hạn:</span>
          <span className={`meta-val ${row.is_overdue ? "overdue-text" : ""}`}>
            {dateTime(row.relationship.next_action_at)}
          </span>
        </div>
        <div className="meta-item">
          <span className="meta-lbl">Độ quan tâm:</span>
          <span className="meta-val highlight">{row.relationship.interest_level}/5 ⭐</span>
        </div>
        <div className="meta-item">
          <span className="meta-lbl">Phụ trách:</span>
          <span className="meta-val">{row.relationship.owner || "Chưa phân công"}</span>
        </div>
      </div>

      {row.other_active_worklists.length > 0 && (
        <div className="task-active-chips">
          <span className="pipeline-alert-tag">
            Đồng thời trong {row.other_active_worklists.length} pipeline:
          </span>
          {row.other_active_worklists.map((item) => (
            <span className="chip pipeline-chip" key={item.hunt_id}>
              {item.title} · <strong>{item.state_label}</strong> ({item.assigned_to_name || "Chưa gán"})
            </span>
          ))}
        </div>
      )}

      <div className="task-card-footer">
        <div className="action-buttons-group">
          <button className="btn btn-primary btn-sm" onClick={contacted}>
            ✓ Đã liên hệ (Nhắc sau 7 ngày)
          </button>
          <button className="btn btn-secondary btn-sm" onClick={inSevenDays}>
            ⏳ Dời 7 ngày
          </button>
          <div className="quick-add-hunt">
            <select
              className="quick-hunt-select"
              value={huntId}
              onChange={(event) => setHuntId(event.target.value)}
            >
              <option value="">+ Đưa vào danh sách săn…</option>
              {hunts.map((hunt) => (
                <option key={hunt.id} value={hunt.id}>
                  {hunt.title}
                </option>
              ))}
            </select>
            <button
              className="btn btn-ghost btn-sm"
              disabled={!huntId || add.isPending}
              onClick={() => add.mutate()}
            >
              Thêm
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

type HuntsView = "tasks" | "pipeline" | "lists";

export default function HuntsWorkspace({ initialTab }: { initialTab?: HuntsView }) {
  const queryClient = useQueryClient();
  const [searchParams] = useSearchParams();
  const tabParam = searchParams.get("tab");

  // Tìm kiếm AI và bộ lọc đa chiều đã tách sang phân hệ Tìm kiếm (/search) —
  // link cũ của Talent Radar chuyển tiếp sang đó, giữ nguyên góc nhìn Tuyển dụng.
  const legacySearchTab = tabParam === "talent" ? "ai" : tabParam === "filter" ? "filter" : null;

  const [view, setView] = useState<HuntsView>(
    initialTab || (tabParam === "pipeline" || tabParam === "lists" ? tabParam : "tasks")
  );

  useEffect(() => {
    if (tabParam && ["tasks", "pipeline", "lists"].includes(tabParam)) {
      setView(tabParam as HuntsView);
    }
  }, [tabParam]);

  const [scope, setScope] = useState<
    "all" | "overdue" | "today" | "unassigned" | "completed"
  >("all");
  const [search, setSearch] = useState("");
  const [searchDraft, setSearchDraft] = useState("");
  const [huntFilter, setHuntFilter] = useState("");
  const [pool, setPool] = useState("");
  const [page, setPage] = useState(0);
  const [pipelinePage, setPipelinePage] = useState(0);
  const [listPage] = useState(0);
  const [selected, setSelected] = useState<string[]>([]);
  const [bulkStage, setBulkStage] = useState("");
  const [bulkOwner, setBulkOwner] = useState("");
  const [creating, setCreating] = useState(false);

  const workflow = useQuery({
    queryKey: ["workflow-catalog"],
    queryFn: api.workflowCatalog,
  });
  const stages = (workflow.data?.results ?? []).filter(
    (stage) => stage.domain === "talent",
  );

  const huntsQuery = useQuery({
    queryKey: ["hunts", { open: true, mine: false }],
    queryFn: () => api.hunts({ open: true, limit: 100 }),
  });

  const ownersQuery = useQuery({
    queryKey: ["rb-owners"],
    queryFn: api.rbOwners,
  });
  const owners = ownersQuery.data?.results ?? [];

  const pools = useQuery({
    queryKey: ["pools", "talent"],
    queryFn: () => api.pools("talent"),
  });

  const tasks = useQuery({
    queryKey: [
      "hunt-tasks",
      { scope, search, pool, page, pageSize: PAGE_SIZE },
    ],
    queryFn: () =>
      api.huntTasks({
        scope,
        q: search,
        pool: pool ? Number(pool) : undefined,
        limit: PAGE_SIZE,
        offset: page * PAGE_SIZE,
      }),
    enabled: view === "tasks",
  });

  const pipeline = useQuery({
    queryKey: ["hunts", "pipeline", pool, pipelinePage],
    queryFn: () =>
      api.hunts({
        pool: pool ? Number(pool) : undefined,
        limit: 10,
        offset: pipelinePage * 10,
      }),
    enabled: view === "pipeline",
  });

  const lists = useQuery({
    queryKey: ["hunts", "lists", listPage],
    queryFn: () =>
      api.hunts({
        limit: PAGE_SIZE,
        offset: listPage * PAGE_SIZE,
      }),
    enabled: view === "lists",
  });

  const bulk = useMutation({
    mutationFn: () => {
      const items = selected.map((item) => {
        const [huntId, personId] = item.split(":");
        return {
          hunt_id: Number(huntId),
          person_id: Number(personId),
        };
      });
      const patch: Record<string, unknown> = {};
      if (bulkOwner) patch.assigned_to_id = Number(bulkOwner);
      if (bulkStage) patch.state = bulkStage;
      return api.huntCandidatesBulk(items, patch);
    },
    onSuccess: () => {
      setSelected([]);
      setBulkOwner("");
      setBulkStage("");
      queryClient.invalidateQueries({ queryKey: ["hunt-tasks"] });
      queryClient.invalidateQueries({ queryKey: ["hunts"] });
    },
  });

  const taskRows = tasks.data?.results ?? [];
  const pipelineHunts = pipeline.data?.results ?? [];
  const allHunts = (lists.data?.results ?? []).map((h) => ({
    id: h.id,
    title: h.title,
  }));

  const allSelectable = taskRows
    .filter((row) => row.kind === "work" && row.hunt?.id)
    .map((row) => `${row.hunt!.id}:${row.person_id}`);
  const allSelected =
    allSelectable.length > 0 &&
    allSelectable.every((key) => selected.includes(key));

  const toggleAll = (checked: boolean) => {
    if (checked) {
      setSelected(Array.from(new Set([...selected, ...allSelectable])));
    } else {
      setSelected(selected.filter((key) => !allSelectable.includes(key)));
    }
  };

  const toggleItem = (key: string, checked: boolean) => {
    setSelected((prev) =>
      checked ? [...prev, key] : prev.filter((item) => item !== key),
    );
  };

  const totalTasks = tasks.data?.count ?? 0;
  const overdueCount = taskRows.filter((r) => r.is_overdue).length;
  const huntCount = huntsQuery.data?.results?.length ?? 0;

  if (legacySearchTab) {
    return <Navigate to={`/search?tab=${legacySearchTab}&perspective=recruiter`} replace />;
  }

  return (
    <div className="hunts-workspace-container">
      {/* Workspace Header & KPI Summary */}
        <div className="workspace-header-card">
          <div className="workspace-title-block">
            <div className="workspace-icon-wrap">🎯</div>
            <div>
              <h1 className="workspace-main-title">Talent Acquisition &amp; Xử lý Ứng viên</h1>
              <p className="workspace-subtitle">
                Trung tâm tìm kiếm nhân tài, điều phối ứng viên, quản lý pipeline tuyển dụng và chăm sóc mạng lưới hồ sơ.
              </p>
            </div>
          </div>
          <div className="workspace-quick-kpi">
            <div className="kpi-mini-card">
              <span className="kpi-num">{huntCount}</span>
              <span className="kpi-txt">Đợt tuyển mở</span>
            </div>
            <div className="kpi-mini-card">
              <span className="kpi-num">{totalTasks}</span>
              <span className="kpi-txt">Tổng công việc</span>
            </div>
            <div className={`kpi-mini-card ${overdueCount > 0 ? "overdue" : ""}`}>
              <span className="kpi-num">{overdueCount}</span>
              <span className="kpi-txt">Cần xử lý gấp</span>
            </div>
            <button
              type="button"
              className="btn btn-primary btn-sm"
              onClick={() => setCreating((value) => !value)}
            >
              {creating ? "✕ Đóng biểu mẫu" : "+ Tạo đợt săn mới"}
            </button>
          </div>
        </div>

      {/* Creation Modal / Form */}
      {creating && (
        <div className="workspace-create-panel">
          <CreateShortlist
            onDone={() => {
              setCreating(false);
              queryClient.invalidateQueries({ queryKey: ["hunts"] });
              queryClient.invalidateQueries({ queryKey: ["hunt-tasks"] });
            }}
          />
        </div>
      )}


      {/* 1. VIEW: TASKS WORKSPACE */}
      {view === "tasks" && (
        <>
          {/* Quick Filters Bar */}
          <div className="workspace-filter-toolbar">
            <div className="scope-pills-row">
              <button
                type="button"
                className={`scope-pill-btn ${scope === "all" ? "active" : ""}`}
                onClick={() => {
                  setScope("all");
                  setPage(0);
                }}
              >
                Tất cả việc
              </button>
              <button
                type="button"
                className={`scope-pill-btn ${scope === "overdue" ? "active" : ""}`}
                onClick={() => {
                  setScope("overdue");
                  setPage(0);
                }}
              >
                ⚠️ Quá hạn
              </button>
              <button
                type="button"
                className={`scope-pill-btn ${scope === "today" ? "active" : ""}`}
                onClick={() => {
                  setScope("today");
                  setPage(0);
                }}
              >
                📅 Hôm nay
              </button>
              <button
                type="button"
                className={`scope-pill-btn ${scope === "unassigned" ? "active" : ""}`}
                onClick={() => {
                  setScope("unassigned");
                  setPage(0);
                }}
              >
                👤 Chưa phân công
              </button>
              <button
                type="button"
                className={`scope-pill-btn ${scope === "completed" ? "active" : ""}`}
                onClick={() => {
                  setScope("completed");
                  setPage(0);
                }}
              >
                ✓ Đã hoàn tất
              </button>
            </div>

            <div className="search-filter-controls">
              <div className="search-input-wrapper" style={{ minWidth: "260px" }}>
                <span className="search-icon">🔍</span>
                <input
                  type="search"
                  className="search-main-input"
                  placeholder="Lọc tên, SĐT, email..."
                  value={searchDraft}
                  onChange={(e) => setSearchDraft(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") {
                      setSearch(searchDraft.trim());
                      setPage(0);
                    }
                  }}
                />
              </div>
              <select
                className="pool-select-input"
                value={pool}
                onChange={(e) => {
                  setPool(e.target.value);
                  setPage(0);
                  setPipelinePage(0);
                }}
              >
                <option value="">Toàn bộ Pool</option>
                {(pools.data?.results ?? []).map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.name} ({item.member_count})
                  </option>
                ))}
              </select>
              <select
                className="pool-select-input"
                value={huntFilter}
                onChange={(e) => {
                  setHuntFilter(e.target.value);
                  setPage(0);
                }}
              >
                <option value="">Tất cả đợt tuyển</option>
                {(huntsQuery.data?.results ?? []).map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.title}
                  </option>
                ))}
              </select>
            </div>
          </div>

          {/* Bulk Action Floating Bar */}
          {selected.length > 0 && (
            <div className="bulk-actions-floating-bar">
              <span className="bulk-count">Đã chọn <strong>{selected.length}</strong> ứng viên</span>
              <div className="bulk-controls">
                <select
                  className="bulk-select"
                  value={bulkOwner}
                  onChange={(e) => setBulkOwner(e.target.value)}
                >
                  <option value="">Chọn người phụ trách…</option>
                  {owners.map((owner: { id: number; name: string }) => (
                    <option key={owner.id} value={owner.id}>
                      {owner.name}
                    </option>
                  ))}
                </select>
                <select
                  className="bulk-select"
                  value={bulkStage}
                  onChange={(e) => setBulkStage(e.target.value)}
                >
                  <option value="">Chuyển trạng thái…</option>
                  {stages.map((stage) => (
                    <option key={stage.code} value={stage.code}>
                      {stage.label}
                    </option>
                  ))}
                </select>
                <button
                  type="button"
                  className="btn btn-primary btn-sm"
                  disabled={(!bulkOwner && !bulkStage) || bulk.isPending}
                  onClick={() => bulk.mutate()}
                >
                  {bulk.isPending ? "Đang áp dụng…" : "Áp dụng"}
                </button>
                <button
                  type="button"
                  className="btn btn-ghost btn-sm"
                  onClick={() => setSelected([])}
                >
                  Bỏ chọn
                </button>
              </div>
            </div>
          )}

          {/* Select all header */}
          {allSelectable.length > 0 && (
            <div className="select-all-header-row">
              <label className="checkbox-label" style={{ display: "flex", alignItems: "center", gap: "8px", fontSize: "13px", cursor: "pointer" }}>
                <input
                  type="checkbox"
                  checked={allSelected}
                  onChange={(e) => toggleAll(e.target.checked)}
                />
                <span>Chọn tất cả {allSelectable.length} công việc săn trên trang này</span>
              </label>
            </div>
          )}

          {/* Task Cards Grid */}
          <div className="workspace-tasks-grid">
            {taskRows.map((row) =>
              row.kind === "work" && row.hunt && row.candidate ? (
                <Candidate
                  key={`${row.hunt.id}-${row.person_id}`}
                  hunt={row.hunt}
                  row={row.candidate}
                  owners={owners}
                  stages={stages}
                  relationship={row.relationship}
                  otherWorklists={row.other_active_worklists}
                  relationshipDue={row.relationship_due}
                  selected={selected.includes(`${row.hunt!.id}:${row.person_id}`)}
                  onSelect={(checked) =>
                    toggleItem(`${row.hunt!.id}:${row.person_id}`, checked)
                  }
                />
              ) : (
                <RelationshipTask
                  key={`rel-${row.person_id}`}
                  row={row}
                  hunts={allHunts}
                />
              ),
            )}

            {!tasks.isLoading && !taskRows.length && (
              <div className="empty-results-box" style={{ gridColumn: "1 / -1", padding: "40px 20px" }}>
                <div className="empty-icon">✓</div>
                <h3>Không có nhiệm vụ nào trong mục này</h3>
                <p>Mọi ứng viên đã được xử lý hoặc chưa có công việc nào khớp với bộ lọc hiện tại.</p>
              </div>
            )}
          </div>

          {/* Pagination */}
          {totalTasks > PAGE_SIZE && (
            <nav className="pagination-bar">
              <button
                className="btn btn-secondary btn-sm"
                disabled={page === 0}
                onClick={() => setPage((v) => Math.max(0, v - 1))}
              >
                ← Trang trước
              </button>
              <span className="page-indicator">
                Trang {page + 1} / {Math.ceil(totalTasks / PAGE_SIZE)}
              </span>
              <button
                className="btn btn-secondary btn-sm"
                disabled={(page + 1) * PAGE_SIZE >= totalTasks}
                onClick={() => setPage((v) => v + 1)}
              >
                Trang sau →
              </button>
            </nav>
          )}
        </>
      )}

      {/* 2. VIEW: PIPELINE COLUMNS */}
      {view === "pipeline" && (
        <div className="pipeline-view-container">
          <div className="pipeline-columns-scroll">
            {stages.map((stage) => {
              const stageCandidates = pipelineHunts.flatMap((h) =>
                (h.people || []).map((p) => ({ hunt: h, candidate: p })),
              ).filter((item) => item.candidate.state === stage.code);

              return (
                <div className="pipeline-stage-column" key={stage.code}>
                  <div className="stage-column-header">
                    <div className="stage-title-wrap">
                      <span className="stage-dot" style={{ background: stage.color || "#0284c7" }} />
                      <h3 className="stage-name">{stage.label}</h3>
                    </div>
                    <span className="stage-count">{stageCandidates.length}</span>
                  </div>
                  <div className="stage-cards-stack">
                    {stageCandidates.map(({ hunt, candidate }) => (
                      <Candidate
                        key={`${hunt.id}-${candidate.person_id}`}
                        hunt={hunt}
                        row={candidate}
                        owners={owners}
                        stages={stages}
                      />
                    ))}
                    {stageCandidates.length === 0 && (
                      <div style={{ textAlign: "center", padding: "24px 8px", color: "var(--muted)", fontSize: "12.5px" }}>
                        Chưa có ứng viên
                      </div>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* 3. VIEW: LISTS & POOLS */}
      {view === "lists" && (
        <div className="lists-view-container">
          <div className="workspace-subhead" style={{ marginBottom: "16px" }}>
            <span className="subhead-title" style={{ fontSize: "15px", fontWeight: 700 }}>
              📁 <strong>{lists.data?.count ?? 0}</strong> đợt tuyển &amp; danh sách săn đang hoạt động
            </span>
          </div>

          <div className="workspace-tasks-grid">
            {(lists.data?.results ?? []).map((hunt) => (
              <HuntCard key={hunt.id} hunt={hunt} owners={owners} stages={stages} />
            ))}
            {!lists.isLoading && !lists.data?.results.length && (
              <div className="empty-results-box" style={{ gridColumn: "1 / -1" }}>
                <p>Chưa có danh sách xử lý nào được tạo.</p>
              </div>
            )}
          </div>

          <div className="pools-accordion-section" style={{ marginTop: "24px" }}>
            <h3 className="section-title" style={{ fontSize: "16px", fontWeight: 700, marginBottom: "12px" }}>
              👥 Nhóm ứng viên (Talent Pools)
            </h3>
            <div className="workspace-tasks-grid">
              {(pools.data?.results ?? []).map((item) => (
                <CandidateGroup key={item.id} pool={item} />
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
