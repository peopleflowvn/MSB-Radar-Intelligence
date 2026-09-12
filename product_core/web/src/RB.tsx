import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, useEffect } from "react";
import { Link, useSearchParams } from "react-router-dom";
import {
  api,
  RBCustomerTaskRow,
  RBOpportunityRow,
  WorkflowStage,
} from "./api";
import ProspectSearch from "./ProspectSearch";
import TodaysOpportunities from "./TodaysOpportunities";

const PAGE_SIZE = 30;
const PRIORITIES = {
  low: "Thấp",
  normal: "Bình thường",
  high: "Cao",
  urgent: "Khẩn cấp",
} as const;

function localInput(value: string | null) {
  if (!value) return "";
  const date = new Date(value);
  const offset = date.getTimezoneOffset() * 60_000;
  return new Date(date.getTime() - offset).toISOString().slice(0, 16);
}

function dateTime(value: string | null) {
  return value ? new Date(value).toLocaleString("vi-VN") : "Chưa đặt hạn";
}

/**
 * Thẻ công việc khách hàng (Customer Task Card)
 */
export function CustomerTaskCard({
  row,
  owners,
  stages,
  canManage,
  selected,
  onSelect,
}: {
  row: RBCustomerTaskRow;
  owners: Array<{ id: number; name: string }>;
  stages: WorkflowStage[];
  canManage: boolean;
  selected: boolean;
  onSelect?: (checked: boolean) => void;
}) {
  const qc = useQueryClient();
  const opportunity = row.opportunity;
  const [details, setDetails] = useState(false);
  const [contact, setContact] = useState(false);
  const [draft, setDraft] = useState(opportunity?.outreach_draft ?? "");
  const [note, setNote] = useState(opportunity?.note ?? "");
  const [channel, setChannel] = useState<"message" | "call_script">("message");
  const [relationshipAction, setRelationshipAction] = useState(
    row.relationship.next_action,
  );
  const [relationshipDue, setRelationshipDue] = useState(
    localInput(row.relationship.next_action_at),
  );

  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["rb-customer-tasks"] });
    qc.invalidateQueries({ queryKey: ["rb-opportunities"] });
  };
  const update = useMutation({
    mutationFn: (patch: Record<string, unknown>) =>
      api.rbOpportunityUpdate(opportunity!.id, patch),
    onSuccess: refresh,
  });
  const updateRelationship = useMutation({
    mutationFn: () =>
      api.rbProfileUpdate(row.person_id, {
        next_action: relationshipAction,
        next_action_at: relationshipDue
          ? new Date(relationshipDue).toISOString()
          : null,
      }),
    onSuccess: refresh,
  });
  const compose = useMutation({
    mutationFn: () => api.rbOutreachDraft(opportunity!.id, channel),
    onSuccess: (result) => {
      setDraft(result.draft);
      setContact(true);
      refresh();
    },
  });
  const sent = useMutation({
    mutationFn: () => api.rbOutreachSent(opportunity!.id, channel, draft),
    onSuccess: () => {
      setContact(false);
      refresh();
    },
  });
  const currentStage = stages.find((stage) => stage.code === opportunity?.status);
  const nextStages = currentStage?.allowed_next?.length
    ? stages.filter((stage) => currentStage.allowed_next.includes(stage.code))
    : stages;
  const allProducts = [
    ...(opportunity ? [opportunity] : []),
    ...row.other_opportunities,
  ];
  const error = update.error || updateRelationship.error || compose.error || sent.error;

  return (
    <div className={`modern-task-card ${row.is_overdue ? "is-overdue" : ""} ${selected ? "selected" : ""}`}>
      {/* Header */}
      <div className="task-card-header">
        <div className="task-avatar-wrap">
          {onSelect && (
            <input
              type="checkbox"
              className="card-checkbox"
              aria-label={`Chọn ${row.display_name}`}
              checked={selected}
              onChange={(event) => onSelect(event.target.checked)}
            />
          )}
          <div className="task-avatar" style={{ background: "var(--accent-gradient)" }}>
            {(row.display_name || "K")[0]?.toUpperCase()}
          </div>
          <div>
            <Link className="task-person-name" to={`/person/${row.person_id}?from=rb`}>
              {row.display_name || "(chưa rõ tên khách)"}
            </Link>
            <div className="task-person-meta">
              <span>{row.headline || "Khách hàng cá nhân"}</span>
              {opportunity?.assigned_to_name && (
                <>
                  <span className="dot-sep">•</span>
                  <span>Phụ trách: <strong>{opportunity.assigned_to_name}</strong></span>
                </>
              )}
            </div>
          </div>
        </div>

        <div className="task-badges">
          {row.is_overdue && <span className="status-badge overdue">⚠️ Quá hạn xử lý</span>}
          {opportunity && (
            <span
              className="status-badge neutral"
              style={{
                borderColor: opportunity.stage_color || "var(--border)",
                color: opportunity.stage_color || "var(--text)",
                fontWeight: 700,
              }}
            >
              {opportunity.status_label}
            </span>
          )}
          {row.relationship.do_not_contact && (
            <span className="status-badge overdue">🚫 Không liên hệ</span>
          )}
        </div>
      </div>

      {/* Product chips & Active warnings */}
      <div className="task-active-chips">
        <div style={{ display: "flex", gap: "6px", flexWrap: "wrap" }}>
          {allProducts.map((item) => (
            <span className="pipeline-product-badge" key={item.id}>
              💼 {item.product_label}
            </span>
          ))}
          {!allProducts.length && (
            <span className="pipeline-chip">Chăm sóc quan hệ khách hàng</span>
          )}
        </div>
        {opportunity && opportunity.other_active_owners.length > 0 && (
          <span className="pipeline-alert-tag">
            ⚠️ RM khác cũng đang xử lý: {opportunity.other_active_owners.join(", ")}
          </span>
        )}
      </div>

      {/* Contact info bar */}
      <div className="task-contact-bar">
        {row.primary_phone && (
          <a className="contact-item" href={`tel:${row.primary_phone}`}>
            📞 {row.primary_phone}
          </a>
        )}
        {row.primary_email && (
          <a className="contact-item" href={`mailto:${row.primary_email}`}>
            ✉️ {row.primary_email}
          </a>
        )}
        {!row.primary_phone && !row.primary_email && (
          <span className="muted small">Chưa có SĐT / Email</span>
        )}
        {row.relationship.next_action_at && (
          <span className="relationship-tag">
            📅 Hạn: <strong>{dateTime(row.relationship.next_action_at)}</strong>
          </span>
        )}
      </div>

      {/* Action / Opportunity Need */}
      <div className="task-action-box">
        <span className="action-tag">Nhu cầu tài chính &amp; Hành động:</span>
        <p className="action-text">
          {opportunity?.need || row.relationship.next_action || "Khách hàng mới được chuyển từ kho dữ liệu. Hãy mở hồ sơ để cập nhật nhu cầu."}
        </p>

        <div className="quick-action-row" style={{ marginTop: "10px" }}>
          <div className="quick-stage-select-wrap">
            <select
              className="quick-stage-select"
              aria-label="Chuyển trạng thái khách hàng"
              value=""
              onChange={(event) => {
                const status = event.target.value;
                if (!status) return;
                if (status === "lost") {
                  const closeReason = window.prompt("Lý do không thành:");
                  if (closeReason?.trim()) {
                    update.mutate({ status, close_reason: closeReason.trim() });
                  }
                } else {
                  update.mutate({ status });
                }
              }}
            >
              <option value="">⚡ Chuyển trạng thái cơ hội…</option>
              {(nextStages.length ? nextStages : stages)
                .filter((stage) => !opportunity || stage.code !== opportunity.status)
                .map((stage) => (
                  <option key={stage.code} value={stage.code}>
                    {stage.label}
                  </option>
                ))}
            </select>
          </div>

          <div className="action-buttons-group">
            {opportunity?.assigned_to == null && (
              <button
                type="button"
                className="btn btn-primary btn-sm"
                onClick={() => update.mutate({ claim: true })}
              >
                Nhận xử lý
              </button>
            )}
            <button
              type="button"
              className="btn btn-secondary btn-sm"
              disabled={row.relationship.do_not_contact || compose.isPending}
              onClick={() => (contact ? setContact(false) : compose.mutate())}
            >
              {contact ? "✕ Đóng mẫu thư" : "✉️ Mẫu chào sản phẩm"}
            </button>
            <button
              type="button"
              className="btn btn-ghost btn-sm"
              onClick={() => setDetails((value) => !value)}
            >
              {details ? "Thu gọn ⌃" : "Cập nhật / Ghi chú ⌄"}
            </button>
          </div>
        </div>
      </div>

      {/* Collapsible Details & RM Config */}
      {details && (
        <div className="task-details-collapsible">
          {opportunity ? (
            <>
              <div className="task-config-grid">
                {canManage && (
                  <div className="config-item">
                    <label className="config-label">Người phụ trách:</label>
                    <select
                      className="config-select"
                      value={opportunity.assigned_to ?? ""}
                      onChange={(event) =>
                        update.mutate({
                          assigned_to_id: event.target.value
                            ? Number(event.target.value)
                            : null,
                        })
                      }
                    >
                      <option value="">Chưa phân công</option>
                      {owners.map((owner) => (
                        <option key={owner.id} value={owner.id}>{owner.name}</option>
                      ))}
                    </select>
                  </div>
                )}
                <div className="config-item">
                  <label className="config-label">Độ ưu tiên:</label>
                  <select
                    className="config-select"
                    value={opportunity.priority}
                    onChange={(event) => update.mutate({ priority: event.target.value })}
                  >
                    {Object.entries(PRIORITIES).map(([value, label]) => (
                      <option key={value} value={value}>{label}</option>
                    ))}
                  </select>
                </div>
                <div className="config-item">
                  <label className="config-label">Lịch follow-up:</label>
                  <input
                    type="datetime-local"
                    className="config-input"
                    value={localInput(opportunity.next_action_at)}
                    onChange={(event) =>
                      update.mutate({
                        next_action_at: event.target.value
                          ? new Date(event.target.value).toISOString()
                          : null,
                      })
                    }
                  />
                </div>
              </div>

              <div className="note-edit-box" style={{ marginTop: "10px" }}>
                <input
                  className="search-main-input"
                  value={note}
                  onChange={(event) => setNote(event.target.value)}
                  placeholder="Ghi chú tiến độ tiếp cận khách hàng..."
                />
                <button
                  type="button"
                  className="btn btn-secondary btn-sm"
                  disabled={note === opportunity.note || update.isPending}
                  onClick={() => update.mutate({ note })}
                >
                  Lưu ghi chú
                </button>
              </div>

              {row.other_opportunities.length > 0 && (
                <details className="small" style={{ marginTop: "8px", opacity: 0.85 }}>
                  <summary style={{ cursor: "pointer", fontWeight: 600 }}>
                    {row.other_opportunities.length} nhu cầu khác của khách
                  </summary>
                  <div style={{ marginTop: "6px", display: "flex", flexDirection: "column", gap: "4px" }}>
                    {row.other_opportunities.map((item) => (
                      <div
                        key={item.id}
                        style={{
                          background: "var(--surface)",
                          padding: "6px 10px",
                          borderRadius: "6px",
                          border: "1px solid var(--border)",
                          display: "flex",
                          alignItems: "center",
                          justifyContent: "space-between",
                          gap: "8px",
                        }}
                      >
                        <span style={{ fontWeight: 600 }}>{item.product_label}</span>
                        <span className="tag" style={{ fontSize: "11px" }}>{item.status_label}</span>
                        <span className="muted" style={{ fontSize: "12px", flex: 1, textAlign: "right" }}>
                          {item.need || "Chưa ghi nhu cầu"}
                        </span>
                      </div>
                    ))}
                  </div>
                </details>
              )}

              {opportunity.status_events.length > 0 && (
                <details className="small" style={{ marginTop: "8px", opacity: 0.85 }}>
                  <summary style={{ cursor: "pointer", fontWeight: 600 }}>
                    Lịch sử trạng thái ({opportunity.status_events.length})
                  </summary>
                  <ol style={{ paddingLeft: "16px", margin: "6px 0" }}>
                    {opportunity.status_events.map((event, index) => (
                      <li key={`${event.created_at}-${index}`} style={{ margin: "3px 0" }}>
                        {dateTime(event.created_at)} · <strong>{event.actor_name || "Hệ thống"}</strong>: {event.from_status || "mới"} → <span style={{ color: "var(--accent)" }}>{event.to_status}</span>
                      </li>
                    ))}
                  </ol>
                </details>
              )}
            </>
          ) : (
            <div className="note-edit-box">
              <input
                className="search-main-input"
                value={relationshipAction}
                onChange={(event) => setRelationshipAction(event.target.value)}
                placeholder="Hành động chăm sóc quan hệ tiếp theo..."
              />
              <input
                type="datetime-local"
                className="config-input"
                value={relationshipDue}
                onChange={(event) => setRelationshipDue(event.target.value)}
              />
              <button
                type="button"
                className="btn btn-secondary btn-sm"
                disabled={updateRelationship.isPending}
                onClick={() => updateRelationship.mutate()}
              >
                Lưu lịch chăm sóc
              </button>
            </div>
          )}
        </div>
      )}

      {/* Outreach composer */}
      {contact && (
        <div className="outreach" style={{ background: "var(--surface-raised)", border: "1px solid var(--border)", borderRadius: "10px", padding: "14px", marginTop: "8px" }}>
          <div className="outreach-head" style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: "10px", marginBottom: "8px" }}>
            <select
              className="config-select"
              value={channel}
              onChange={(e) => setChannel(e.target.value as "message" | "call_script")}
            >
              <option value="message">Tin nhắn SMS / Zalo</option>
              <option value="call_script">Kịch bản gọi điện</option>
            </select>
            <button className="btn btn-ghost btn-sm" onClick={() => compose.mutate()}>
              {compose.isPending ? "Đang soạn lại…" : "🔄 Soạn lại"}
            </button>
          </div>
          <textarea
            className="jd-box"
            rows={5}
            style={{ width: "100%", borderRadius: "8px", border: "1px solid var(--border)", padding: "10px", fontSize: "13px", fontFamily: "inherit" }}
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
          />
          <p className="hint" style={{ margin: "6px 0 0", fontSize: "12px", color: "var(--muted)" }}>
            ✨ Kịch bản tiếp cận đề xuất bởi AI dựa trên chân dung nghề nghiệp &amp; nhu cầu tài chính.
          </p>
          <div className="action-buttons-group" style={{ marginTop: "10px" }}>
            <button
              className="btn btn-primary btn-sm"
              disabled={sent.isPending || !draft.trim()}
              onClick={() => sent.mutate()}
            >
              ✓ Tôi đã liên hệ khách
            </button>
            <button
              className="btn btn-ghost btn-sm"
              onClick={() => update.mutate({ outreach_draft: draft })}
            >
              Lưu nháp
            </button>
            <button className="btn btn-secondary btn-sm" onClick={() => setContact(false)}>
              Đóng
            </button>
          </div>
        </div>
      )}

      {/* Footer */}
      <div className="task-card-footer">
        <span className="task-updated-txt">
          {opportunity ? `Cập nhật: ${dateTime(opportunity.created_at)}` : "Hồ sơ quan hệ"}
        </span>
        <Link className="btn btn-secondary btn-sm" to={`/person/${row.person_id}?from=rb`}>
          Hồ sơ 360° →
        </Link>
      </div>

      {error && <p className="err-box" style={{ marginTop: "8px" }}>{String(error)}</p>}
    </div>
  );
}

/**
 * Thẻ Danh sách Nhóm khách hàng (Customer Group / Pool)
 */
function CustomerGroup({ pool }: { pool: { id: number; name: string; description: string; member_count: number; owner_name: string } }) {
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [product, setProduct] = useState("credit_card");
  const members = useQuery({
    queryKey: ["pool-members", pool.id],
    queryFn: () => api.poolMembers(pool.id),
    enabled: open,
  });
  const create = useMutation({
    mutationFn: async () =>
      Promise.allSettled(
        (members.data?.results ?? []).map((person) =>
          api.rbOpportunityCreate({
            person_id: person.id,
            product,
            need: `Tạo từ danh sách: ${pool.name}`,
          }),
        ),
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["rb-customer-tasks"] });
      qc.invalidateQueries({ queryKey: ["rb-opportunities"] });
    },
  });
  return (
    <article className="hunt-card">
      <div className="hunt-head">
        <div>
          <strong>{pool.name}</strong>
          <div className="talent-meta">
            <span>{pool.member_count} khách hàng</span>
            <span>Chủ danh sách: {pool.owner_name || "Chưa xác định"}</span>
          </div>
        </div>
        <button className="btn btn-ghost btn-sm" onClick={() => setOpen((value) => !value)}>
          {open ? "Thu gọn" : "Xem danh sách"}
        </button>
      </div>
      {pool.description && <p className="muted" style={{ margin: "6px 0 0", fontSize: "13px" }}>{pool.description}</p>}
      {open && (
        <>
          <div className="hunt-people">
            {(members.data?.results ?? []).map((person) => (
              <div className="hunt-person" key={person.id}>
                <Link to={`/person/${person.id}?from=rb`}>{person.display_name}</Link>
              </div>
            ))}
          </div>
          <div className="search-row" style={{ marginTop: "10px" }}>
            <select className="config-select" value={product} onChange={(event) => setProduct(event.target.value)}>
              <option value="credit_card">Thẻ tín dụng</option>
              <option value="mortgage">Vay mua nhà</option>
              <option value="auto_loan">Vay mua xe</option>
              <option value="consumer_loan">Vay tiêu dùng</option>
              <option value="savings">Tiết kiệm</option>
              <option value="investment">Đầu tư</option>
              <option value="insurance">Bảo hiểm</option>
              <option value="fx">Ngoại tệ</option>
              <option value="payroll">Tài khoản lương</option>
            </select>
            <button className="btn btn-primary btn-sm" disabled={!members.data?.count || create.isPending} onClick={() => create.mutate()}>
              {create.isPending ? "Đang tạo…" : "Tạo việc cho danh sách"}
            </button>
          </div>
          {create.data && (
            <p className="hint">
              Đã tạo {create.data.filter((item) => item.status === "fulfilled").length}; bỏ qua {create.data.filter((item) => item.status === "rejected").length} mục trùng hoặc lỗi.
            </p>
          )}
        </>
      )}
    </article>
  );
}

/**
 * Màn hình Chính RB Radar (/rb)
 */
export default function RB() {
  const qc = useQueryClient();
  const [searchParams] = useSearchParams();
  const tabParam = searchParams.get("tab") as "today" | "prospects" | "filter" | "tasks" | "pipeline" | "lists" | null;
  const [view, setView] = useState<
    "today" | "prospects" | "filter" | "tasks" | "pipeline" | "lists">(tabParam || "today");

  useEffect(() => {
    if (tabParam && ["today", "prospects", "filter", "tasks", "pipeline", "lists"].includes(tabParam)) {
      setView(tabParam);
    }
  }, [tabParam]);

  const [scope, setScope] = useState<"all" | "overdue" | "today" | "unassigned" | "completed">("all");
  const [query, setQuery] = useState("");
  const [search, setSearch] = useState("");
  const [pool, setPool] = useState("");
  const [page, setPage] = useState(0);
  const [pipelinePage, setPipelinePage] = useState(0);
  const [selected, setSelected] = useState<number[]>([]);
  const [bulkStatus, setBulkStatus] = useState("");
  const [bulkOwner, setBulkOwner] = useState("");
  const [newList, setNewList] = useState("");

  const session = useQuery({ queryKey: ["me"], queryFn: api.me });
  const identity = session.data?.authenticated ? session.data : null;
  const canManage = Boolean(identity?.is_superuser || identity?.roles.some((role) => role === "manager" || role === "admin"));
  const owners = useQuery({ queryKey: ["rb-owners"], queryFn: api.rbOwners });
  const workflow = useQuery({ queryKey: ["workflow-catalog"], queryFn: api.workflowCatalog });
  const pools = useQuery({ queryKey: ["customer-groups"], queryFn: () => api.pools("rb") });
  const tasks = useQuery({
    queryKey: ["rb-customer-tasks", scope, pool, search, page],
    queryFn: () => api.rbCustomerTasks({
      scope,
      q: search,
      pool: pool ? Number(pool) : undefined,
      limit: PAGE_SIZE,
      offset: page * PAGE_SIZE,
    }),
    enabled: view === "tasks",
  });
  const todayCount = useQuery({
    queryKey: ["rb-today", ""],
    queryFn: () => api.rbToday(),
  });
  const pipeline = useQuery({
    queryKey: ["rb-opportunities", "pipeline-mine", pool, pipelinePage],
    queryFn: () => api.rbOpportunities({
      scope: "mine",
      pool: pool ? Number(pool) : undefined,
      limit: PAGE_SIZE,
      offset: pipelinePage * PAGE_SIZE,
    }),
    enabled: view === "pipeline",
  });
  const createList = useMutation({
    mutationFn: () => api.createPool(newList.trim(), "", "rb"),
    onSuccess: () => {
      setNewList("");
      qc.invalidateQueries({ queryKey: ["customer-groups"] });
    },
  });
  const bulk = useMutation({
    mutationFn: () => {
      const patch: Record<string, unknown> = {};
      if (bulkStatus) patch.status = bulkStatus;
      if (bulkOwner) patch.assigned_to_id = Number(bulkOwner);
      return api.rbOpportunitiesBulk(selected, patch);
    },
    onSuccess: () => {
      setSelected([]);
      setBulkStatus("");
      setBulkOwner("");
      qc.invalidateQueries({ queryKey: ["rb-customer-tasks"] });
      qc.invalidateQueries({ queryKey: ["rb-opportunities"] });
    },
  });
  const stages = (workflow.data?.results ?? []).filter((stage) => stage.domain === "rb");
  const taskRows = tasks.data?.results ?? [];
  const totalTasks = tasks.data?.count ?? 0;
  const overdueCount = tasks.data?.summary.overdue ?? 0;
  const todayOpportunitiesCount = todayCount.data?.summary.total ?? 0;
  const poolsCount = pools.data?.results?.length ?? 0;

  const chooseScope = (next: typeof scope) => {
    setScope(next);
    setPage(0);
    setSelected([]);
  };

  return (
    <div className="rb-workspace-container">
      {/* Workspace Header & KPI Summary - Chỉ hiển thị khi KHÔNG ở tab 'prospects' và 'filter' */}
      {view !== "prospects" && view !== "filter" && (
        <div className="workspace-header-card">
          <div className="workspace-title-block">
            <div className="workspace-icon-wrap" style={{ background: "var(--accent-gradient)" }}>
              💼
            </div>
            <div>
              <h1 className="workspace-main-title">Growth Radar · Xử lý Cơ hội &amp; Khách hàng</h1>
              <p className="workspace-subtitle">
                Quản lý tiến độ tiếp cận, cơ hội bán chéo sản phẩm tài chính và chăm sóc quan hệ khách hàng cá nhân.
              </p>
            </div>
          </div>
          <div className="workspace-quick-kpi">
            <div className="kpi-mini-card">
              <span className="kpi-num">{todayOpportunitiesCount}</span>
              <span className="kpi-txt">Hôm nay</span>
            </div>
            <div className="kpi-mini-card">
              <span className="kpi-num">{totalTasks}</span>
              <span className="kpi-txt">Tổng cơ hội</span>
            </div>
            <div className={`kpi-mini-card ${overdueCount > 0 ? "overdue" : ""}`}>
              <span className="kpi-num">{overdueCount}</span>
              <span className="kpi-txt">Quá hạn</span>
            </div>
            <div className="kpi-mini-card">
              <span className="kpi-num">{poolsCount}</span>
              <span className="kpi-txt">Nhóm khách</span>
            </div>
          </div>
        </div>
      )}

      {/* 0. VIEW: TODAY — Radar đề xuất, RM quyết định */}
      {view === "today" && <TodaysOpportunities />}

      {/* 0b. VIEW: PROSPECTS & FILTER — RM chủ động hỏi NLP & Lọc đa chiều */}
      {(view === "prospects" || view === "filter") && (
        <ProspectSearch initialMode={view === "filter" ? "loc" : "ai"} />
      )}

      {/* 1. VIEW: TASKS — Bảng công việc chi tiết */}
      {view === "tasks" && (
        <>
          {/* Quick Filters Toolbar */}
          <div className="workspace-filter-toolbar">
            <div className="scope-pills-row">
              <button
                type="button"
                className={`scope-pill-btn ${scope === "all" ? "active" : ""}`}
                onClick={() => chooseScope("all")}
              >
                Tất cả ({tasks.data?.summary.active ?? 0})
              </button>
              <button
                type="button"
                className={`scope-pill-btn ${scope === "overdue" ? "active" : ""}`}
                onClick={() => chooseScope("overdue")}
              >
                ⚠️ Quá hạn ({tasks.data?.summary.overdue ?? 0})
              </button>
              <button
                type="button"
                className={`scope-pill-btn ${scope === "today" ? "active" : ""}`}
                onClick={() => chooseScope("today")}
              >
                📅 Hôm nay ({tasks.data?.summary.today ?? 0})
              </button>
              <button
                type="button"
                className={`scope-pill-btn ${scope === "unassigned" ? "active" : ""}`}
                onClick={() => chooseScope("unassigned")}
              >
                👤 Chưa phân công ({tasks.data?.summary.unassigned ?? 0})
              </button>
              <button
                type="button"
                className={`scope-pill-btn ${scope === "completed" ? "active" : ""}`}
                onClick={() => chooseScope("completed")}
              >
                ✓ Đã kết thúc
              </button>
            </div>

            <div className="search-filter-controls">
              <div className="search-input-wrapper" style={{ minWidth: "260px" }}>
                <span className="search-icon">🔍</span>
                <input
                  type="search"
                  className="search-main-input"
                  placeholder="Tìm khách, nhu cầu..."
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") {
                      setSearch(query.trim());
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
                <option value="">Toàn bộ danh sách khách</option>
                {(pools.data?.results ?? []).map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.name} ({item.member_count})
                  </option>
                ))}
              </select>
            </div>
          </div>

          {/* Bulk Action Floating Bar */}
          {selected.length > 0 && (
            <div className="bulk-actions-floating-bar">
              <span className="bulk-count">Đã chọn <strong>{selected.length}</strong> khách hàng</span>
              <div className="bulk-controls">
                {canManage && (
                  <select
                    className="bulk-select"
                    value={bulkOwner}
                    onChange={(e) => setBulkOwner(e.target.value)}
                  >
                    <option value="">Chọn người phụ trách…</option>
                    {(owners.data?.results ?? []).map((owner) => (
                      <option key={owner.id} value={owner.id}>
                        {owner.name}
                      </option>
                    ))}
                  </select>
                )}
                <select
                  className="bulk-select"
                  value={bulkStatus}
                  onChange={(e) => setBulkStatus(e.target.value)}
                >
                  <option value="">Chọn trạng thái…</option>
                  {stages
                    .filter((stage) => !stage.requires_reason && stage.code !== "lost")
                    .map((stage) => (
                      <option key={stage.code} value={stage.code}>
                        {stage.label}
                      </option>
                    ))}
                </select>
                <button
                  type="button"
                  className="btn btn-primary btn-sm"
                  disabled={(!bulkOwner && !bulkStatus) || bulk.isPending}
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

          {/* Task Cards Grid */}
          <div className="workspace-tasks-grid">
            {taskRows.map((row) => (
              <CustomerTaskCard
                key={row.key}
                row={row}
                owners={owners.data?.results ?? []}
                stages={stages}
                canManage={canManage}
                selected={Boolean(row.opportunity && selected.includes(row.opportunity.id))}
                onSelect={
                  row.opportunity
                    ? (checked) =>
                        setSelected((old) =>
                          checked
                            ? [...new Set([...old, row.opportunity!.id])]
                            : old.filter((id) => id !== row.opportunity!.id),
                        )
                    : undefined
                }
              />
            ))}
            {!tasks.isLoading && !taskRows.length && (
              <div className="empty-results-box" style={{ gridColumn: "1 / -1", padding: "40px 20px" }}>
                <div className="empty-icon">✓</div>
                <h3 style={{ margin: "8px 0 4px", fontSize: "16px", color: "var(--text)" }}>
                  Không có cơ hội khách hàng nào trong mục này
                </h3>
                <p style={{ margin: 0, color: "var(--muted)", fontSize: "13.5px" }}>
                  Mọi khách hàng đã được chăm sóc hoặc không có kết quả phù hợp với bộ lọc.
                </p>
              </div>
            )}
          </div>

          {/* Pagination */}
          {totalTasks > PAGE_SIZE && (
            <nav className="pagination-bar">
              <button
                className="btn btn-secondary btn-sm"
                disabled={page === 0}
                onClick={() => setPage((old) => Math.max(0, old - 1))}
              >
                ← Trang trước
              </button>
              <span className="page-indicator">
                Trang {page + 1} / {Math.ceil(totalTasks / PAGE_SIZE)}
              </span>
              <button
                className="btn btn-secondary btn-sm"
                disabled={(page + 1) * PAGE_SIZE >= totalTasks}
                onClick={() => setPage((old) => old + 1)}
              >
                Trang sau →
              </button>
            </nav>
          )}
        </>
      )}

      {/* 2. VIEW: PIPELINE */}
      {view === "pipeline" && (
        <div className="pipeline-view-container">
          <div className="pipeline-columns-scroll">
            {stages.map((stage) => {
              const stageRows = (pipeline.data?.results ?? []).filter(
                (row: RBOpportunityRow) => row.status === stage.code,
              );
              return (
                <div className="pipeline-stage-column" key={stage.code}>
                  <div className="stage-column-header">
                    <div className="stage-title-wrap">
                      <span className="stage-dot" style={{ background: stage.color || "#10b981" }} />
                      <h3 className="stage-name">{stage.label}</h3>
                    </div>
                    <span className="stage-count">{stageRows.length}</span>
                  </div>
                  <div className="stage-cards-stack">
                    {stageRows.map((row: RBOpportunityRow) => (
                      <div className="modern-pipeline-card" key={row.id}>
                        <Link className="pipeline-candidate-name" to={`/person/${row.person}?from=rb`}>
                          {row.display_name}
                        </Link>
                        <div className="pipeline-product-badge">{row.product_label}</div>
                        <p className="pipeline-need-text">{row.need || "Chưa ghi nhu cầu cụ thể"}</p>
                        {row.next_action_at && (
                          <div className="pipeline-due-date">📅 {dateTime(row.next_action_at)}</div>
                        )}
                      </div>
                    ))}
                    {stageRows.length === 0 && (
                      <div style={{ textAlign: "center", padding: "24px 8px", color: "var(--muted)", fontSize: "12.5px" }}>
                        Chưa có cơ hội
                      </div>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* 3. VIEW: LISTS */}
      {view === "lists" && (
        <div className="lists-view-container">
          <div className="workspace-subhead" style={{ marginBottom: "16px", display: "flex", gap: "12px", alignItems: "center" }}>
            <div className="search-input-wrapper" style={{ flex: 1, maxWidth: "420px" }}>
              <input
                className="search-main-input"
                value={newList}
                onChange={(e) => setNewList(e.target.value)}
                placeholder="Nhập tên danh sách nhóm khách hàng mới..."
              />
            </div>
            <button
              type="button"
              className="btn btn-primary btn-sm"
              disabled={!newList.trim() || createList.isPending}
              onClick={() => createList.mutate()}
            >
              {createList.isPending ? "Đang tạo…" : "+ Tạo danh sách"}
            </button>
          </div>

          <div className="workspace-tasks-grid">
            {(pools.data?.results ?? []).map((item) => (
              <CustomerGroup key={item.id} pool={item} />
            ))}
            {!pools.isLoading && !pools.data?.results.length && (
              <div className="empty-results-box" style={{ gridColumn: "1 / -1" }}>
                <p>Chưa có danh sách nhóm khách hàng nào được tạo.</p>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
