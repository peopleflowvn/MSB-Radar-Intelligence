import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, IdentityConflict, IntelAlias, IntelReviewItem } from './api'

// People Intelligence — soi fact/provenance, xử lý hàng chờ review và alias.
// API: /api/v1/intel/ (Master Plan §5, §21). Chỉ Admin vào được (RBAC ở backend).

type SubView = 'dashboard' | 'review' | 'aliases' | 'conflicts'

const REASON_LABEL: Record<string, string> = {
  sensitive: 'Trường nhạy cảm',
  low_confidence: 'Độ tin cậy thấp',
  conflict: 'Mâu thuẫn với dữ liệu curated',
  unknown_alias: 'Alias chưa nhận diện',
}

function fmtDate(s?: string | null) {
  return s ? new Date(s).toLocaleString('vi-VN') : '—'
}

export default function IntelPanel() {
  const [view, setView] = useState<SubView>('dashboard')
  return (
    <div className="admin-panel-card">
      <div className="otp-nav-tabs" style={{ marginBottom: 16 }}>
        {(['dashboard', 'review', 'aliases', 'conflicts'] as SubView[]).map((v) => (
          <button
            key={v}
            className={`otp-nav-tab-btn ${view === v ? 'active' : ''}`}
            onClick={() => setView(v)}
          >
            {v === 'dashboard' && '📊 Tổng quan trích xuất'}
            {v === 'review' && '🔍 Hàng chờ duyệt'}
            {v === 'aliases' && '🏷️ Alias chưa nhận diện'}
            {v === 'conflicts' && '⚠️ Xung đột định danh'}
          </button>
        ))}
      </div>
      {view === 'dashboard' && <IntelDashboard onJump={setView} />}
      {view === 'review' && <ReviewQueue />}
      {view === 'aliases' && <AliasQueue />}
      {view === 'conflicts' && <IdentityConflictQueue />}
    </div>
  )
}

function IntelDashboard({ onJump }: { onJump: (v: SubView) => void }) {
  const q = useQuery({ queryKey: ['intel-runs'], queryFn: api.intelRunsDashboard, retry: false })
  if (q.isError) return <div className="empty-box">Không tải được số liệu trích xuất.</div>
  if (!q.data) return <div className="empty-box">Đang tải…</div>
  const { totals, alerts, coverage_last_500: cov, recent } = q.data
  const bannerItems: Array<{ label: string; view: SubView }> = [
    ...(alerts.reviews ? [{ label: `${totals.open_reviews} mục chờ duyệt`, view: 'review' as SubView }] : []),
    ...(alerts.aliases ? [{ label: `${totals.proposed_aliases} alias chưa nối`, view: 'aliases' as SubView }] : []),
    ...(alerts.conflicts
      ? [{ label: `${totals.open_identity_conflicts} xung đột định danh`, view: 'conflicts' as SubView }]
      : []),
  ]
  return (
    <div>
      {bannerItems.length > 0 && (
        <div style={{
          background: 'var(--danger-soft, #fdecea)', border: '1px solid var(--danger, #d33)',
          borderRadius: 8, padding: '10px 14px', marginBottom: 16, display: 'flex',
          alignItems: 'center', gap: 12, flexWrap: 'wrap',
        }}>
          <strong style={{ color: 'var(--danger, #d33)' }}>⚠️ Hàng chờ đang phình to:</strong>
          {bannerItems.map((b) => (
            <button key={b.view} className="ghost small" onClick={() => onJump(b.view)}>{b.label} →</button>
          ))}
        </div>
      )}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(160px,1fr))', gap: 12 }}>
        <Stat label="Lượt trích xuất" value={totals.runs} />
        <Stat label="Fact đã chấp nhận" value={totals.accepted_facts} />
        <Stat label="Đang chờ duyệt" value={totals.open_reviews} warn={totals.open_reviews > 0} />
        <Stat label="Alias chưa nối" value={totals.proposed_aliases} warn={totals.proposed_aliases > 0} />
        <Stat label="Xung đột định danh" value={totals.open_identity_conflicts}
          warn={totals.open_identity_conflicts > 0} />
      </div>
      <h4 style={{ margin: '20px 0 8px', color: 'var(--text)' }}>Coverage 500 lượt gần nhất</h4>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(150px,1fr))', gap: 10 }}>
        <Stat label="Field từ Edge" value={cov.edge ?? 0} />
        <Stat label="Field từ hồ sơ" value={cov.profile ?? 0} />
        <Stat label="Field từ CV text" value={cov.cv_text ?? 0} />
        <Stat label="Field cần AI" value={cov.ai ?? 0} />
        <Stat label="Lượt gọi AI" value={cov.ai_calls ?? 0} />
        <Stat
          label="Tỷ lệ tái dùng Edge"
          value={cov.edge_reuse_ratio != null ? `${Math.round((cov.edge_reuse_ratio as number) * 100)}%` : '—'}
          warn={cov.edge_reuse_ratio != null && (cov.edge_reuse_ratio as number) < 0.7}
        />
      </div>
      <h4 style={{ margin: '20px 0 8px', color: 'var(--text)' }}>Lượt gần đây</h4>
      <div style={{ overflowX: 'auto' }}>
        <table style={{ width: '100%' }}>
          <thead>
            <tr><th>#</th><th>Person</th><th>Trạng thái</th><th>Edge / AI</th><th>Bắt đầu</th></tr>
          </thead>
          <tbody>
            {recent.map((r) => (
              <tr key={r.id}>
                <td>{r.id}</td>
                <td>{r.person_id}</td>
                <td>
                  <span className={`badge ${r.status === 'done' ? 'good' : r.status === 'failed' ? 'warn' : ''}`}>
                    {r.status}
                  </span>
                </td>
                <td>{(r.coverage?.edge ?? 0) as number} / {(r.coverage?.ai ?? 0) as number}</td>
                <td>{fmtDate(r.started_at)}</td>
              </tr>
            ))}
            {recent.length === 0 && <tr><td colSpan={5} className="empty-box">Chưa có lượt trích xuất nào.</td></tr>}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function Stat({ label, value, warn }: { label: string; value: number | string; warn?: boolean }) {
  return (
    <div style={{ background: 'var(--surface-raised)', borderRadius: 8, padding: '12px 14px' }}>
      <div style={{ fontSize: 12, color: 'var(--muted)' }}>{label}</div>
      <div style={{ fontSize: 22, fontWeight: 700, color: warn ? 'var(--danger, #d33)' : 'var(--text)' }}>{value}</div>
    </div>
  )
}

/** Thanh hành động hàng loạt dùng chung cho Review/Alias — người vẫn tự chọn
 * dòng, đây chỉ gộp N lần bấm thành 1, không tự chọn thay ai cả. */
function BulkBar({ count, onClear, children }: { count: number; onClear: () => void; children: React.ReactNode }) {
  if (count === 0) return null
  return (
    <div style={{
      display: 'flex', alignItems: 'center', gap: 10, background: 'var(--surface-raised)',
      borderRadius: 8, padding: '8px 12px', marginBottom: 12, flexWrap: 'wrap',
    }}>
      <span className="hint">Đã chọn {count} dòng</span>
      {children}
      <button className="ghost small" onClick={onClear}>Bỏ chọn</button>
    </div>
  )
}

function ReviewQueue() {
  const qc = useQueryClient()
  const [reason, setReason] = useState('')
  const [selected, setSelected] = useState<Set<number>>(new Set())
  const q = useQuery({
    queryKey: ['intel-review', reason],
    queryFn: () => api.intelReviewQueue(reason || undefined),
    retry: false,
  })
  const resolve = useMutation({
    mutationFn: (v: { id: number; decision: 'accept' | 'reject' }) =>
      api.intelReviewResolve(v.id, v.decision),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['intel-review'] })
      qc.invalidateQueries({ queryKey: ['intel-runs'] })
    },
  })
  const bulkResolve = useMutation({
    mutationFn: (v: { decision: 'accept' | 'reject' }) =>
      api.intelReviewBulkResolve(Array.from(selected), v.decision),
    onSuccess: () => {
      setSelected(new Set())
      qc.invalidateQueries({ queryKey: ['intel-review'] })
      qc.invalidateQueries({ queryKey: ['intel-runs'] })
    },
  })

  if (q.isError) return <div className="empty-box">Không tải được hàng chờ duyệt.</div>
  const items = q.data?.results ?? []
  const toggle = (id: number) => setSelected((prev) => {
    const next = new Set(prev)
    next.has(id) ? next.delete(id) : next.add(id)
    return next
  })

  return (
    <div>
      <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 12 }}>
        <label className="hint">Lọc lý do:</label>
        <select value={reason} onChange={(e) => setReason(e.target.value)}>
          <option value="">Tất cả</option>
          {Object.entries(REASON_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </select>
        {q.data?.counts && (
          <span className="hint">
            {Object.entries(q.data.counts).map(([k, n]) => `${REASON_LABEL[k] ?? k}: ${n}`).join(' · ')}
          </span>
        )}
        {items.length > 0 && (
          <button className="ghost small" onClick={() => setSelected(new Set(items.map((it) => it.id)))}>
            Chọn tất cả
          </button>
        )}
      </div>
      <BulkBar count={selected.size} onClear={() => setSelected(new Set())}>
        <button className="btn-primary" disabled={bulkResolve.isPending}
          onClick={() => bulkResolve.mutate({ decision: 'accept' })}>Chấp nhận đã chọn</button>
        <button className="ghost" disabled={bulkResolve.isPending}
          onClick={() => bulkResolve.mutate({ decision: 'reject' })}>Từ chối đã chọn</button>
      </BulkBar>
      {items.length === 0 && <div className="empty-box">Không có mục nào chờ duyệt.</div>}
      {items.map((it: IntelReviewItem) => (
        <div key={it.id} style={{ border: '1px solid var(--border)', borderRadius: 8, padding: 12, marginBottom: 10 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12 }}>
            <div style={{ minWidth: 0, display: 'flex', gap: 10 }}>
              <input type="checkbox" checked={selected.has(it.id)} onChange={() => toggle(it.id)}
                style={{ marginTop: 4 }} aria-label={`Chọn mục ${it.id}`} />
              <div style={{ minWidth: 0 }}>
                <span className="badge warn">{REASON_LABEL[it.reason] ?? it.reason}</span>{' '}
                <strong>{it.field || it.fact?.field}</strong>
                {it.person_id != null && <span className="hint"> · Person {it.person_id}</span>}
                <div style={{ marginTop: 6, fontSize: 13 }}>
                  {it.fact && (
                    <>
                      <div>Giá trị thô: <code>{it.fact.raw_value || '—'}</code></div>
                      <div>Chuẩn hoá: <code>{it.fact.canonical_label || it.fact.normalized_value || '—'}</code>
                        {it.fact.canonical_code && <span className="hint"> ({it.fact.canonical_code})</span>}</div>
                      <div>Nguồn: <code>{it.fact.source_kind}</code> · tin cậy {(it.fact.confidence * 100).toFixed(0)}%</div>
                      {it.fact.evidence && <div style={{ color: 'var(--muted)' }}>Bằng chứng: “{it.fact.evidence}”</div>}
                    </>
                  )}
                  {it.alias && <div>Alias <code>{it.alias.alias_norm}</code> (namespace {it.alias.namespace}) — dùng tab “Alias chưa nhận diện” để nối.</div>}
                  {it.detail && <div className="hint">{it.detail}</div>}
                </div>
              </div>
            </div>
            {it.fact && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 6, flexShrink: 0 }}>
                <button className="btn-primary" disabled={resolve.isPending}
                  onClick={() => resolve.mutate({ id: it.id, decision: 'accept' })}>Chấp nhận</button>
                <button className="ghost" disabled={resolve.isPending}
                  onClick={() => resolve.mutate({ id: it.id, decision: 'reject' })}>Từ chối</button>
              </div>
            )}
          </div>
        </div>
      ))}
    </div>
  )
}

function AliasQueue() {
  const qc = useQueryClient()
  const [selected, setSelected] = useState<Set<number>>(new Set())
  const [bulkCode, setBulkCode] = useState('')
  const q = useQuery({ queryKey: ['intel-aliases'], queryFn: () => api.intelAliasQueue(), retry: false })
  const resolve = useMutation({
    mutationFn: (v: { id: number; decision: 'accept' | 'reject'; code?: string }) =>
      api.intelAliasResolve(v.id, v.decision, v.code),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['intel-aliases'] })
      qc.invalidateQueries({ queryKey: ['intel-runs'] })
    },
  })
  const newEntry = useMutation({
    mutationFn: (v: { id: number; code: string; label: string }) =>
      api.intelAliasNewEntry(v.id, v.code, v.label),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['intel-aliases'] })
      qc.invalidateQueries({ queryKey: ['intel-runs'] })
    },
  })
  const bulkResolve = useMutation({
    mutationFn: (v: { decision: 'accept' | 'reject'; code?: string }) =>
      api.intelAliasBulkResolve(Array.from(selected), v.decision, v.code),
    onSuccess: () => {
      setSelected(new Set())
      setBulkCode('')
      qc.invalidateQueries({ queryKey: ['intel-aliases'] })
      qc.invalidateQueries({ queryKey: ['intel-runs'] })
    },
  })
  if (q.isError) return <div className="empty-box">Không tải được hàng chờ alias.</div>
  const aliases = q.data?.results ?? []
  const toggle = (id: number) => setSelected((prev) => {
    const next = new Set(prev)
    next.has(id) ? next.delete(id) : next.add(id)
    return next
  })
  return (
    <div>
      <p className="hint" style={{ marginTop: 0 }}>
        Nhập mã canonical để nối alias vào (vd <code>data-analyst</code>). AI không tự tạo mã mới —
        chỉ bạn nối alias lạ vào mã đã có, tạo mã mới khi nó thật sự là giá trị mới, hoặc từ chối.
      </p>
      {aliases.length > 0 && (
        <button className="ghost small" style={{ marginBottom: 8 }}
          onClick={() => setSelected(new Set(aliases.map((a) => a.id)))}>
          Chọn tất cả
        </button>
      )}
      <BulkBar count={selected.size} onClear={() => setSelected(new Set())}>
        <input placeholder="mã canonical chung" value={bulkCode}
          onChange={(e) => setBulkCode(e.target.value.trim())} style={{ width: 160 }} />
        <button className="btn-primary" disabled={bulkResolve.isPending || !bulkCode}
          onClick={() => bulkResolve.mutate({ decision: 'accept', code: bulkCode })}>
          Nối đã chọn vào mã này
        </button>
        <button className="ghost" disabled={bulkResolve.isPending}
          onClick={() => bulkResolve.mutate({ decision: 'reject' })}>Từ chối đã chọn</button>
      </BulkBar>
      {aliases.length === 0 && <div className="empty-box">Không có alias nào chờ xử lý.</div>}
      {aliases.map((a: IntelAlias) => (
        <AliasRow key={a.id} alias={a} onResolve={resolve.mutate} pending={resolve.isPending}
          onNewEntry={newEntry.mutate} newEntryPending={newEntry.isPending}
          selected={selected.has(a.id)} onToggleSelected={() => toggle(a.id)} />
      ))}
    </div>
  )
}

function AliasRow({
  alias, onResolve, pending, onNewEntry, newEntryPending, selected, onToggleSelected,
}: {
  alias: IntelAlias
  onResolve: (v: { id: number; decision: 'accept' | 'reject'; code?: string }) => void
  pending: boolean
  onNewEntry: (v: { id: number; code: string; label: string }) => void
  newEntryPending: boolean
  selected: boolean
  onToggleSelected: () => void
}) {
  const [code, setCode] = useState('')
  const [creating, setCreating] = useState(false)
  const [newCode, setNewCode] = useState('')
  const [newLabel, setNewLabel] = useState('')
  return (
    <div style={{ borderBottom: '1px solid var(--border)', padding: '8px 0' }}>
      <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
        <input type="checkbox" checked={selected} onChange={onToggleSelected}
          aria-label={`Chọn alias ${alias.alias_norm}`} />
        <div style={{ flex: 1, minWidth: 0 }}>
          <code>{alias.alias_norm}</code>
          <span className="hint"> · {alias.namespace} · nguồn {alias.source || '—'}</span>
        </div>
        <input placeholder="mã canonical có sẵn" value={code}
          onChange={(e) => setCode(e.target.value.trim())} style={{ width: 160 }} />
        <button className="btn-primary" disabled={pending || !code}
          onClick={() => onResolve({ id: alias.id, decision: 'accept', code })}>Nối</button>
        <button className="ghost" disabled={pending}
          onClick={() => onResolve({ id: alias.id, decision: 'reject' })}>Bỏ</button>
        <button className="ghost small" onClick={() => setCreating((v) => !v)}>
          {creating ? 'Huỷ tạo mã mới' : '+ Tạo mã mới'}
        </button>
      </div>
      {creating && (
        <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginTop: 8, marginLeft: 30 }}>
          <span className="hint">Giá trị này chưa có mã nào đúng — tạo mã mới:</span>
          <input placeholder="mã (vd vietcombank)" value={newCode}
            onChange={(e) => setNewCode(e.target.value.trim())} style={{ width: 160 }} />
          <input placeholder="nhãn hiển thị (vd Vietcombank)" value={newLabel}
            onChange={(e) => setNewLabel(e.target.value)} style={{ width: 200 }} />
          <button className="btn-primary" disabled={newEntryPending || !newCode || !newLabel}
            onClick={() => {
              onNewEntry({ id: alias.id, code: newCode, label: newLabel })
              setCreating(false)
              setNewCode('')
              setNewLabel('')
            }}>
            Tạo &amp; nối
          </button>
        </div>
      )}
    </div>
  )
}

function IdentityConflictQueue() {
  const qc = useQueryClient()
  const q = useQuery({ queryKey: ['intel-identity-conflicts'], queryFn: api.intelIdentityConflicts, retry: false })
  const resolve = useMutation({
    mutationFn: (v: { id: number; decision: 'merge' | 'dismiss' }) =>
      api.intelIdentityConflictResolve(v.id, v.decision),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['intel-identity-conflicts'] })
      qc.invalidateQueries({ queryKey: ['intel-runs'] })
    },
  })
  if (q.isError) return <div className="empty-box">Không tải được hàng chờ xung đột định danh.</div>
  const conflicts = q.data?.results ?? []
  return (
    <div>
      <p className="hint" style={{ marginTop: 0 }}>
        Hai định danh mạnh (email/SĐT) trỏ tới hai Person khác nhau. Gộp nhầm hai người thành một gần
        như không gỡ lại được — xem kỹ bằng chứng trước khi quyết định. Không có duyệt hàng loạt ở đây.
      </p>
      {conflicts.length === 0 && <div className="empty-box">Không có xung đột nào chờ xử lý.</div>}
      {conflicts.map((c: IdentityConflict) => (
        <div key={c.id} style={{ border: '1px solid var(--border)', borderRadius: 8, padding: 12, marginBottom: 10 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12 }}>
            <div style={{ minWidth: 0 }}>
              <div className="hint">Xung đột #{c.id} · {fmtDate(c.created_at)}</div>
              {c.people.map((p) => (
                <div key={p.id} style={{ marginTop: 8 }}>
                  <strong>#{p.id} {p.display_name || '(chưa rõ tên)'}</strong>
                  <div className="hint">
                    {[p.primary_email, p.primary_phone, p.headline].filter(Boolean).join(' · ') || '—'}
                  </div>
                </div>
              ))}
              <div style={{ marginTop: 8, fontSize: 13 }}>
                Định danh gây xung đột: {c.evidence.identities.map((i) => `${i.kind}=${i.value}`).join(', ')}
              </div>
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 6, flexShrink: 0 }}>
              <button className="btn-primary" disabled={resolve.isPending}
                onClick={() => resolve.mutate({ id: c.id, decision: 'merge' })}>
                Gộp làm một người
              </button>
              <button className="ghost" disabled={resolve.isPending}
                onClick={() => resolve.mutate({ id: c.id, decision: 'dismiss' })}>
                Đây là hai người khác nhau
              </button>
            </div>
          </div>
        </div>
      ))}
    </div>
  )
}
