import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";
import {
  api,
  HuntCandidateRow,
  HuntCandidateState,
  HuntRequestRow,
  HuntTaskRow,
  WorkflowStage,
} from "./api";

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
  return value ? new Date(value).toLocaleString("vi-VN") : "—";
}

export function Candidate({
  hunt,
  row,
  owners,
  stages,
  relationship,
  otherWorklists = [],
  relationshipDue = false,
  selected = false,
  onSelect,
}: {
  hunt: Pick<HuntRequestRow, "id" | "title" | "message" | "status">;
  row: HuntCandidateRow;
  owners: Array<{ id: number; name: string }>;
  stages: WorkflowStage[];
  relationship?: HuntTaskRow["relationship"];
  otherWorklists?: HuntTaskRow["other_active_worklists"];
  relationshipDue?: boolean;
  selected?: boolean;
  onSelect?: (checked: boolean) => void;
}) {
  const queryClient = useQueryClient();
  const [draft, setDraft] = useState(row.outreach_draft);
  const [note, setNote] = useState(row.note);
  const [open, setOpen] = useState(false);
  const [archiving, setArchiving] = useState(false);
  const [targetState, setTargetState] =
    useState<HuntCandidateState>("returned");
  const [reason, setReason] = useState("");
  const [showConfig, setShowConfig] = useState(false);
  const [channel, setChannel] = useState<"email" | "message">("message");
  const closed = row.state === "submitted" || row.state === "returned";
  const overdue =
    !!row.next_action_at &&
    new Date(row.next_action_at) < new Date() &&
    !closed;
  const currentStage = stages.find((stage) => stage.code === row.state);
  const visibleStages = currentStage?.allowed_next?.length
    ? stages.filter((stage) => currentStage.allowed_next.includes(stage.code))
    : stages;

  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: ["hunts"] });
    queryClient.invalidateQueries({ queryKey: ["hunt-tasks"] });
  };
  const update = useMutation({
    mutationFn: (patch: Parameters<typeof api.huntCandidateUpdate>[2]) =>
      api.huntCandidateUpdate(hunt.id, row.person_id, patch),
    onSuccess: () => {
      setArchiving(false);
      refresh();
    },
  });
  const compose = useMutation({
    mutationFn: () => api.outreachDraft(hunt.id, row.person_id, channel),
    onSuccess: (result) => {
      setDraft(result.draft);
      setOpen(true);
    },
  });
  const sent = useMutation({
    mutationFn: () => api.outreachSent(hunt.id, row.person_id, channel, draft),
    onSuccess: () => {
      setOpen(false);
      refresh();
    },
  });
  const transition = (state: HuntCandidateState) => {
    const targetStageObj = stages.find((item) => item.code === state);
    if (targetStageObj?.requires_reason || ["submitted", "returned"].includes(state)) {
      setTargetState(state);
      setReason("");
      setArchiving(true);
    } else {
      update.mutate({ state });
    }
  };

  return (
    <div className={`modern-task-card state-${row.state} ${selected ? "selected" : ""}`}>
      {/* Header */}
      <div className="task-card-header">
        <div className="task-avatar-wrap">
          {onSelect && (
            <input
              type="checkbox"
              className="card-checkbox"
              checked={selected}
              onChange={(e) => onSelect(e.target.checked)}
              aria-label={`Chọn ${row.display_name}`}
            />
          )}
          <div className="task-avatar" style={{ background: "var(--accent-gradient)" }}>
            {(row.display_name || "U")[0]?.toUpperCase()}
          </div>
          <div>
            <Link className="task-person-name" to={`/person/${row.person_id}?from=talent`}>
              {row.display_name || "(chưa rõ tên)"}
            </Link>
            <div className="task-person-meta">
              <span>{row.headline || "Chưa có chức danh"}</span>
              <span className="dot-sep">•</span>
              <span className="hunt-origin-title" title={hunt.title}>🎯 {hunt.title}</span>
            </div>
          </div>
        </div>

        <div className="task-badges">
          {overdue && <span className="status-badge overdue">⚠️ Quá hạn follow-up</span>}
          {row.is_overdue && <span className="status-badge overdue">Quá SLA pipeline</span>}
          <span
            className="status-badge neutral"
            style={{
              borderColor: row.stage_color || "var(--border)",
              color: row.stage_color || "var(--text)",
            }}
          >
            {row.state_label}
          </span>
          {relationshipDue && (
            <span className="status-badge neutral">📅 Trùng lịch chăm sóc</span>
          )}
          {relationship?.do_not_contact && (
            <span className="status-badge overdue">🚫 Không liên hệ</span>
          )}
        </div>
      </div>

      {/* Relationship & Pipeline conflict tags */}
      {otherWorklists.length > 0 && (
        <div className="task-active-chips">
          <span className="pipeline-alert-tag">
            ⚠️ Đồng thời trong {otherWorklists.length} luồng khác:
          </span>
          {otherWorklists.map((item) => (
            <span className="chip pipeline-chip" key={item.hunt_id}>
              {item.title} · <strong>{item.state_label}</strong> ({item.assigned_to_name || "Chưa phân công"})
            </span>
          ))}
        </div>
      )}

      {/* Contact info */}
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
        {relationship && !relationship.do_not_contact && (
          <span className="relationship-tag">
            Quan hệ: <strong>{relationship.state}</strong> (Quan tâm {relationship.interest_level}/5 ⭐)
          </span>
        )}
      </div>

      {/* Primary Action / Quick Controls */}
      <div className="task-action-box">
        <div className="quick-action-row">
          <div className="quick-stage-select-wrap">
            <select
              className="quick-stage-select"
              aria-label="Chuyển trạng thái ứng viên"
              value=""
              onChange={(e) => {
                if (e.target.value) {
                  transition(e.target.value as HuntCandidateState);
                }
              }}
            >
              <option value="">⚡ Chuyển trạng thái tuyển dụng…</option>
              {(visibleStages.length
                ? visibleStages
                : [
                    { code: "contacting", label: "Đang tiếp cận" },
                    { code: "responded", label: "Đã phản hồi" },
                    { code: "interested", label: "Có quan tâm" },
                    { code: "not_interested", label: "Chưa quan tâm" },
                    { code: "unreachable", label: "Không liên hệ được" },
                    { code: "submitted", label: "Hoàn tất mục tiêu" },
                    { code: "returned", label: "Đưa về chăm sóc dài hạn" },
                  ]
              )
                .filter((stage) => stage.code !== row.state)
                .map((stage) => (
                  <option key={stage.code} value={stage.code}>
                    {stage.label}
                  </option>
                ))}
            </select>
          </div>

          <div className="action-buttons-group">
            {row.assigned_to == null && (
              <button
                type="button"
                className="btn btn-primary btn-sm"
                onClick={() => update.mutate({ claim: true })}
              >
                Nhận xử lý
              </button>
            )}
            {!closed && (
              <button
                type="button"
                className="btn btn-secondary btn-sm"
                disabled={compose.isPending || relationship?.do_not_contact}
                onClick={() => (open ? setOpen(false) : compose.mutate())}
              >
                {open ? "✕ Đóng mẫu thư" : "✉️ Soạn thư"}
              </button>
            )}
            <button
              type="button"
              className="btn btn-ghost btn-sm"
              onClick={() => setShowConfig(!showConfig)}
            >
              {showConfig ? "Thu gọn ⌃" : "Cập nhật / Ghi chú ⌄"}
            </button>
          </div>
        </div>
      </div>

      {/* Archiving / Return Prompt */}
      {archiving && (
        <div className="reason-prompt-card">
          <input
            className="search-main-input"
            autoFocus
            placeholder={`Nhập lý do chuyển sang ${stages.find((item) => item.code === targetState)?.label || targetState}...`}
            value={reason}
            onChange={(e) => setReason(e.target.value)}
          />
          <div className="prompt-actions">
            <button
              type="button"
              className="btn btn-primary btn-sm"
              disabled={!reason.trim()}
              onClick={() =>
                update.mutate({
                  state: targetState,
                  return_reason: targetState === "returned" ? reason : undefined,
                  note: targetState === "returned" ? note : reason,
                })
              }
            >
              Lưu trạng thái
            </button>
            <button
              type="button"
              className="btn btn-ghost btn-sm"
              onClick={() => setArchiving(false)}
            >
              Huỷ
            </button>
          </div>
        </div>
      )}

      {/* Expandable Config & Note Box */}
      {showConfig && (
        <div className="task-details-collapsible">
          <div className="task-config-grid">
            <div className="config-item">
              <label className="config-label">Phụ trách:</label>
              <select
                className="config-select"
                value={row.assigned_to ?? ""}
                onChange={(e) =>
                  update.mutate({
                    assigned_to_id: e.target.value ? Number(e.target.value) : null,
                  })
                }
              >
                <option value="">Chưa phân công</option>
                {owners.map((owner) => (
                  <option key={owner.id} value={owner.id}>
                    {owner.name}
                  </option>
                ))}
              </select>
            </div>

            <div className="config-item">
              <label className="config-label">Ưu tiên:</label>
              <select
                className="config-select"
                value={row.priority}
                onChange={(e) =>
                  update.mutate({
                    priority: e.target.value as HuntCandidateRow["priority"],
                  })
                }
              >
                {Object.entries(PRIORITIES).map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </select>
            </div>

            <div className="config-item">
              <label className="config-label">Hạn follow-up:</label>
              <input
                type="datetime-local"
                className="config-input"
                value={localInput(row.next_action_at)}
                onChange={(e) =>
                  update.mutate({
                    next_action_at: e.target.value
                      ? new Date(e.target.value).toISOString()
                      : null,
                  })
                }
              />
            </div>
          </div>

          <div className="note-edit-box">
            <input
              className="search-main-input"
              placeholder="Nhập ghi chú xử lý ứng viên..."
              value={note}
              onChange={(e) => setNote(e.target.value)}
            />
            <button
              type="button"
              className="btn btn-secondary btn-sm"
              disabled={note === row.note || update.isPending}
              onClick={() => update.mutate({ note })}
            >
              Lưu ghi chú
            </button>
          </div>
        </div>
      )}

      {/* Outreach Drawer */}
      {open && (
        <div className="outreach">
          <div className="outreach-head">
            <select
              value={channel}
              onChange={(e) =>
                setChannel(e.target.value as "email" | "message")
              }
            >
              <option value="message">Tin nhắn</option>
              <option value="email">Email</option>
            </select>
            <button className="btn btn-ghost btn-sm" onClick={() => compose.mutate()}>
              {compose.isPending ? "Đang soạn lại…" : "Soạn lại"}
            </button>
          </div>
          <textarea
            className="jd-box"
            rows={6}
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
          />
          <p className="hint">
            AI chỉ dùng dữ kiện có trong hồ sơ. Hãy kiểm tra nội dung trước khi gửi.
          </p>
          <div className="action-buttons-group" style={{ marginTop: "8px" }}>
            <button className="btn btn-primary btn-sm" onClick={() => sent.mutate()}>
              Tôi đã gửi
            </button>
            <button
              className="btn btn-ghost btn-sm"
              onClick={() => update.mutate({ outreach_draft: draft })}
            >
              Lưu nháp
            </button>
            <button className="btn btn-secondary btn-sm" onClick={() => setOpen(false)}>
              Đóng
            </button>
          </div>
        </div>
      )}

      {row.status_events.length > 0 && (
        <details className="small" style={{ marginTop: "8px", opacity: 0.8 }}>
          <summary>Lịch sử trạng thái ({row.status_events.length})</summary>
          <ol style={{ paddingLeft: "16px", margin: "6px 0" }}>
            {row.status_events.map((event, index) => (
              <li key={`${event.created_at}-${index}`}>
                {new Date(event.created_at).toLocaleString("vi-VN")} ·{" "}
                {event.actor_name || "Hệ thống"} · {event.from_state || "mới"} →{" "}
                {event.to_state}
                {event.note && ` · ${event.note}`}
              </li>
            ))}
          </ol>
        </details>
      )}

      {/* Footer */}
      <div className="task-card-footer">
        <span className="task-updated-txt">Cập nhật: {dateTime(row.updated_at)}</span>
        <Link className="btn btn-secondary btn-sm" to={`/person/${row.person_id}?from=talent`}>
          Hồ sơ 360° →
        </Link>
      </div>

      {update.error && <p className="err-box">{String(update.error)}</p>}
      {(compose.error || sent.error) && (
        <p className="err-box">{String(compose.error || sent.error)}</p>
      )}
    </div>
  );
}

export function HuntCard({
  hunt,
  owners,
  stages,
}: {
  hunt: HuntRequestRow;
  owners: Array<{ id: number; name: string }>;
  stages: WorkflowStage[];
}) {
  const queryClient = useQueryClient();
  const [editing, setEditing] = useState(false);
  const [title, setTitle] = useState(hunt.title || hunt.hiring_need_title);
  const [message, setMessage] = useState(hunt.message);
  const [priority, setPriority] = useState(hunt.priority);
  const update = useMutation({
    mutationFn: (patch: Record<string, unknown>) =>
      api.huntUpdate(hunt.id, patch),
    onSuccess: () => {
      setEditing(false);
      queryClient.invalidateQueries({ queryKey: ["hunts"] });
      queryClient.invalidateQueries({ queryKey: ["hunt-tasks"] });
    },
  });
  return (
    <div className={`hunt-card status-${hunt.status}`}>
      <div className="hunt-head">
        <div>
          <div className="talent-name">
            {hunt.title || hunt.hiring_need_title}
          </div>
          <div className="talent-meta">
            <span>
              Chủ danh sách: {hunt.assigned_to_name || hunt.requested_by_name}
            </span>
            <span>{new Date(hunt.created_at).toLocaleDateString("vi-VN")}</span>
            <span>Ưu tiên {PRIORITIES[hunt.priority]}</span>
            <span>
              Đã xử lý {hunt.progress.closed}/{hunt.progress.total}
            </span>
            {hunt.visible_count !== hunt.progress.total && (
              <span>
                Đang hiển thị {hunt.visible_count} ứng viên theo bộ lọc
              </span>
            )}
          </div>
        </div>
        <span className={`badge status-${hunt.status}`}>
          {hunt.status === "done" ? "Đã đóng" : "Đang xử lý"}
        </span>
      </div>
      {hunt.message && <p className="hunt-message">{hunt.message}</p>}
      {editing && (
        <div className="hunt-card">
          <div className="search-row">
            <input className="search-main" value={title}
              onChange={(event) => setTitle(event.target.value)}
              placeholder="Tên danh sách" />
            <select value={priority}
              onChange={(event) => setPriority(event.target.value as HuntRequestRow["priority"])}>
              {Object.entries(PRIORITIES).map(([value, label]) =>
                <option key={value} value={value}>{label}</option>)}
            </select>
          </div>
          <textarea className="jd-box" rows={2} value={message}
            onChange={(event) => setMessage(event.target.value)}
            placeholder="Mục tiêu hoặc lưu ý xử lý" />
          <div className="mark-row">
            <button disabled={!title.trim() || update.isPending}
              onClick={() => update.mutate({ title, message, priority })}>Lưu</button>
            <button className="ghost" onClick={() => setEditing(false)}>Thôi</button>
          </div>
        </div>
      )}
      <ul className="hunt-people">
        {hunt.people.map((row) => (
          <Candidate
            key={row.person_id}
            hunt={hunt}
            row={row}
            owners={owners}
            stages={stages}
          />
        ))}
      </ul>
      <div className="mark-row">
        <button className="ghost" onClick={() => setEditing((value) => !value)}>
          Sửa danh sách
        </button>
        {hunt.status === "done" ? (
          <button onClick={() => update.mutate({ status: "in_progress" })}>
            Mở lại danh sách
          </button>
        ) : (
          <button
            className="ghost"
            disabled={hunt.progress.closed < hunt.progress.total}
            title={
              hunt.progress.closed < hunt.progress.total
                ? "Cần xử lý xong tất cả ứng viên trước khi đóng"
                : undefined
            }
            onClick={() => update.mutate({ status: "done" })}
          >
            Đóng danh sách
          </button>
        )}
      </div>
      {update.error && <p className="err-box">{String(update.error)}</p>}
    </div>
  );
}

export function CreateShortlist({ onDone }: { onDone: () => void }) {
  const [title, setTitle] = useState("");
  const [message, setMessage] = useState("");
  const [priority, setPriority] = useState<keyof typeof PRIORITIES>("normal");
  const create = useMutation({
    mutationFn: () =>
      api.createShortlist({
        title,
        message,
        priority,
        person_ids: [],
      }),
    onSuccess: onDone,
  });
  return (
    <div className="hunt-card">
      <h2>Tạo danh sách xử lý trống</h2>
      <p className="hint">
        Sau khi tạo, hãy chọn ứng viên từ Tra cứu hồ sơ hoặc thêm từ một nhóm
        ứng viên.
      </p>
      <div className="search-row">
        <input
          className="search-main"
          placeholder="Tên danh sách, ví dụ: Data Engineer tháng 8"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
        />
        <select
          value={priority}
          onChange={(e) =>
            setPriority(e.target.value as keyof typeof PRIORITIES)
          }
        >
          {Object.entries(PRIORITIES).map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </select>
      </div>
      <textarea
        className="jd-box"
        rows={2}
        placeholder="Mục tiêu hoặc lưu ý xử lý (không bắt buộc)"
        value={message}
        onChange={(e) => setMessage(e.target.value)}
      />
      {create.error && <p className="err-box">{String(create.error)}</p>}
      <div className="mark-row">
        <button
          disabled={!title.trim() || create.isPending}
          onClick={() => create.mutate()}
        >
          Tạo danh sách
        </button>
      </div>
    </div>
  );
}

export function CandidateGroup({
  pool,
}: {
  pool: {
    id: number;
    name: string;
    description: string;
    owner_name: string;
    member_count: number;
  };
}) {
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const members = useQuery({
    queryKey: ["pool-members", pool.id],
    queryFn: () => api.poolMembers(pool.id),
    enabled: open,
  });
  const create = useMutation({
    mutationFn: () =>
      api.createShortlist({
        title: pool.name,
        person_ids: (members.data?.results ?? []).map((row) => row.id),
        message: `Tạo từ nhóm ứng viên: ${pool.name}`,
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["hunts"] }),
  });
  return (
    <div className="hunt-card">
      <div className="hunt-head">
        <div>
          <div className="talent-name">{pool.name}</div>
          <div className="talent-meta">
            <span>{pool.member_count} ứng viên</span>
            <span>Chủ nhóm: {pool.owner_name || "Chưa xác định"}</span>
          </div>
        </div>
        <button className="ghost" onClick={() => setOpen((value) => !value)}>
          {open ? "Thu gọn" : "Xem thành viên"}
        </button>
      </div>
      {pool.description && <p className="muted">{pool.description}</p>}
      {open && (
        <>
          <div className="hunt-people">
            {(members.data?.results ?? []).map((person) => (
              <div className="hunt-person" key={person.id}>
                <Link to={`/person/${person.id}?from=talent`}>
                  <strong>{person.display_name}</strong>
                </Link>
                <span className="muted">
                  {" "}
                  ·{" "}
                  {person.headline ||
                    person.talent?.current_title ||
                    "Chưa có chức danh"}
                </span>
                {person.active_worklists.length > 0 && (
                  <div className="chips">
                    {person.active_worklists.map((row) => (
                      <span className="chip" key={row.hunt_id}>
                        {row.title} · {row.state_label} ·{" "}
                        {row.assigned_to_name || "Chưa phân công"}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            ))}
          </div>
          <button
            disabled={!members.data?.count || create.isPending}
            onClick={() => create.mutate()}
          >
            Tạo danh sách xử lý từ nhóm
          </button>
        </>
      )}
    </div>
  );
}

export function HuntsLegacy() {
  const queryClient = useQueryClient();
  const [view, setView] = useState<"work" | "pipeline">("work");
  const [pipelinePool, setPipelinePool] = useState("");
  const [filter, setFilter] = useState<
    | "mine"
    | "followup"
    | "relationship_due"
    | "unassigned"
    | "groups"
    | "recent"
    | "completed"
  >("mine");
  const [creating, setCreating] = useState(false);
  const facets = useQuery({
    queryKey: ["talent-facets"],
    queryFn: api.talentFacets,
  });
  const workflow = useQuery({
    queryKey: ["workflow-catalog"],
    queryFn: api.workflowCatalog,
  });
  const hunts = useQuery({
    queryKey: ["hunts", filter],
    queryFn: () =>
      api.hunts({
        scope: filter as "mine" | "followup" | "unassigned" | "completed",
      }),
    retry: false,
    enabled:
      filter !== "recent" &&
      filter !== "groups" &&
      filter !== "relationship_due",
  });
  const recent = useQuery({
    queryKey: ["recently-viewed"],
    queryFn: () => api.recentlyViewed(100),
    enabled: filter === "recent",
  });
  const relationshipDue = useQuery({
    queryKey: ["talent-relationship-followups"],
    queryFn: api.talentRelationshipFollowups,
    enabled: filter === "relationship_due",
  });
  const pools = useQuery({
    queryKey: ["candidate-groups"],
    queryFn: () => api.pools("talent"),
    enabled: filter === "groups" || view === "pipeline",
  });
  const rows = hunts.data?.results ?? [];
  const pipeline = useQuery({
    queryKey: ["hunts", "pipeline-mine", pipelinePool],
    queryFn: () =>
      api.hunts({
        scope: "mine",
        pool: pipelinePool ? Number(pipelinePool) : undefined,
      }),
    enabled: view === "pipeline",
  });
  const pipelineRows = pipeline.data?.results ?? [];
  const talentStages = (workflow.data?.results ?? []).filter(
    (stage) => stage.domain === "talent",
  );
  return (
    <div>
      <div className="result-head">
        <div>
          <h1>Xử lý ứng viên</h1>
          <p className="muted">
            Công việc và pipeline ứng viên của tài khoản đang đăng nhập.
          </p>
        </div>
        <button onClick={() => setCreating((value) => !value)}>
          {creating ? "Đóng" : "+ Tạo danh sách"}
        </button>
      </div>
      <nav className="tabs sub-tabs">
        <button
          className={view === "work" ? "active" : ""}
          onClick={() => setView("work")}
        >
          Danh sách xử lý
        </button>
        <button
          className={view === "pipeline" ? "active" : ""}
          onClick={() => setView("pipeline")}
        >
          Pipeline ứng viên
        </button>
      </nav>
      {creating && (
        <CreateShortlist
          onDone={() => {
            setCreating(false);
            queryClient.invalidateQueries({ queryKey: ["hunts"] });
          }}
        />
      )}
      {view === "pipeline" && (
        <div className="result-head">
          <label className="filter-col-group">
            <span className="filter-label">Phạm vi nhóm ứng viên</span>
            <select
              value={pipelinePool}
              onChange={(e) => setPipelinePool(e.target.value)}
            >
              <option value="">Tất cả công việc của tôi</option>
              {(pools.data?.results ?? []).map((pool) => (
                <option key={pool.id} value={pool.id}>
                  {pool.name}
                </option>
              ))}
            </select>
          </label>
        </div>
      )}
      {view === "work" && filter === "relationship_due" && (
        <div className="hunt-list">
          {(relationshipDue.data?.results ?? []).map((person) => (
            <div className="hunt-card" key={person.id}>
              <Link className="talent-name" to={`/person/${person.id}?from=talent`}>
                {person.display_name}
              </Link>
              <div className="talent-meta">
                <span>
                  {person.relationship_followup.next_action ||
                    "Chưa ghi hành động"}
                </span>
                <span>
                  Đến hạn:{" "}
                  {dateTime(person.relationship_followup.next_action_at)}
                </span>
                <span>
                  Quan tâm: {person.relationship_followup.interest_level}/5
                </span>
              </div>
            </div>
          ))}
          {!relationshipDue.isLoading && !relationshipDue.data?.count && (
            <div className="empty-box">
              Không có quan hệ ứng viên đến hạn chăm sóc.
            </div>
          )}
        </div>
      )}
      {view === "pipeline" ? (
        <div className="pipeline-board">
          {talentStages.map((stage) => (
            <section className="pipeline-column" key={stage.code}>
              <h3 style={{ borderColor: stage.color }}>
                {stage.label}{" "}
                <span className="badge">
                  {pipelineRows.reduce(
                    (count, hunt) =>
                      count +
                      hunt.people.filter((row) => row.state === stage.code)
                        .length,
                    0,
                  )}
                </span>
              </h3>
              {pipelineRows.flatMap((hunt) =>
                hunt.people
                  .filter((row) => row.state === stage.code)
                  .map((row) => (
                    <Candidate
                      key={`${hunt.id}-${row.person_id}`}
                      hunt={hunt}
                      row={row}
                      owners={facets.data?.owners ?? []}
                      stages={talentStages}
                    />
                  )),
              )}
            </section>
          ))}
        </div>
      ) : (
        <>
          <nav className="tabs sub-tabs">
            <button
              className={filter === "mine" ? "active" : ""}
              onClick={() => setFilter("mine")}
            >
              Việc của tôi
            </button>
            <button
              className={filter === "followup" ? "active" : ""}
              onClick={() => setFilter("followup")}
            >
              Cần follow-up
            </button>
            <button
              className={filter === "relationship_due" ? "active" : ""}
              onClick={() => setFilter("relationship_due")}
            >
              Quan hệ cần chăm sóc
            </button>
            <button
              className={filter === "unassigned" ? "active" : ""}
              onClick={() => setFilter("unassigned")}
            >
              Chưa phân công
            </button>
            <button
              className={filter === "groups" ? "active" : ""}
              onClick={() => setFilter("groups")}
            >
              Nhóm ứng viên
            </button>
            <button
              className={filter === "recent" ? "active" : ""}
              onClick={() => setFilter("recent")}
            >
              Đã xem gần đây
            </button>
            <button
              className={filter === "completed" ? "active" : ""}
              onClick={() => setFilter("completed")}
            >
              Đã hoàn tất
            </button>
          </nav>
          {filter === "relationship_due" ? null : filter === "groups" ? (
            <div className="hunt-list">
              {(pools.data?.results ?? []).map((pool) => (
                <CandidateGroup key={pool.id} pool={pool} />
              ))}
              {!pools.isLoading && !pools.data?.results.length && (
                <div className="empty-box">
                  Chưa có nhóm ứng viên. Có thể tạo nhóm từ Person 360.
                </div>
              )}
            </div>
          ) : filter === "recent" ? (
            <div className="hunt-list">
              {(recent.data?.results ?? []).map((person) => (
                <div className="hunt-card" key={person.id}>
                  <Link className="talent-name" to={`/person/${person.id}?from=talent`}>
                    {person.display_name}
                  </Link>
                  <div className="talent-meta">
                    <span>
                      {person.headline ||
                        person.talent?.current_title ||
                        "Chưa có chức danh"}
                    </span>
                    <span>
                      {person.active_worklists.length
                        ? `${person.active_worklists.length} danh sách đang xử lý`
                        : "Chưa được xử lý"}
                    </span>
                  </div>
                  {person.active_worklists.map((row) => (
                    <div className="chip" key={row.hunt_id}>
                      {row.title} · {row.state_label} ·{" "}
                      {row.assigned_to_name || "Chưa phân công"}
                    </div>
                  ))}
                </div>
              ))}
              {!recent.isLoading && !recent.data?.results.length && (
                <div className="empty-box">Tài khoản chưa xem hồ sơ nào.</div>
              )}
            </div>
          ) : (
            <>
              <div className="result-head">
                <span>
                  <strong>{rows.length}</strong> danh sách công việc
                </span>
              </div>
              <div className="hunt-list">
                {rows.map((hunt) => (
                  <HuntCard
                    key={hunt.id}
                    hunt={hunt}
                    owners={facets.data?.owners ?? []}
                    stages={talentStages}
                  />
                ))}
                {!rows.length && !hunts.isLoading && (
                  <div className="empty-box">Chưa có danh sách ở mục này.</div>
                )}
              </div>
            </>
          )}
        </>
      )}
    </div>
  );
}
