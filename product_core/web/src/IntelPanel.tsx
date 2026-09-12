import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, IntelAlias, IntelReviewItem } from './api'

// People Intelligence — soi fact/provenance, xử lý hàng chờ review và alias.
// API: /api/v1/intel/ (Master Plan §5, §21). Chỉ Admin vào được (RBAC ở backend).

type SubView = 'dashboard' | 'review' | 'aliases'

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
        {(['dashboard', 'review', 'aliases'] as SubView[]).map((v) => (
          <button
            key={v}
            className={`otp-nav-tab-btn ${view === v ? 'active' : ''}`}
            onClick={() => setView(v)}
          >
            {v === 'dashboard' && '📊 Tổng quan trích xuất'}
            {v === 'review' && '🔍 Hàng chờ duyệt'}
            {v === 'aliases' && '🏷️ Alias chưa nhận diện'}
          </button>
        ))}
      </div>
      {view === 'dashboard' && <IntelDashboard />}
      {view === 'review' && <ReviewQueue />}
      {view === 'aliases' && <AliasQueue />}
    </div>
  )
}

function IntelDashboard() {
  const q = useQuery({ queryKey: ['intel-runs'], queryFn: api.intelRunsDashboard, retry: false })
  if (q.isError) return <div className="empty-box">Không tải được số liệu trích xuất.</div>
  if (!q.data) return <div className="empty-box">Đang tải…</div>
  const { totals, coverage_last_500: cov, recent } = q.data
  return (
    <div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(160px,1fr))', gap: 12 }}>
        <Stat label="Lượt trích xuất" value={totals.runs} />
        <Stat label="Fact đã chấp nhận" value={totals.accepted_facts} />
        <Stat label="Đang chờ duyệt" value={totals.open_reviews} warn={totals.open_reviews > 0} />
        <Stat label="Alias chưa nối" value={totals.proposed_aliases} warn={totals.proposed_aliases > 0} />
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

function ReviewQueue() {
  const qc = useQueryClient()
  const [reason, setReason] = useState('')
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

  if (q.isError) return <div className="empty-box">Không tải được hàng chờ duyệt.</div>
  const items = q.data?.results ?? []

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
      </div>
      {items.length === 0 && <div className="empty-box">Không có mục nào chờ duyệt.</div>}
      {items.map((it: IntelReviewItem) => (
        <div key={it.id} style={{ border: '1px solid var(--border)', borderRadius: 8, padding: 12, marginBottom: 10 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12 }}>
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
  const q = useQuery({ queryKey: ['intel-aliases'], queryFn: () => api.intelAliasQueue(), retry: false })
  const resolve = useMutation({
    mutationFn: (v: { id: number; decision: 'accept' | 'reject'; code?: string }) =>
      api.intelAliasResolve(v.id, v.decision, v.code),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['intel-aliases'] })
      qc.invalidateQueries({ queryKey: ['intel-runs'] })
    },
  })
  if (q.isError) return <div className="empty-box">Không tải được hàng chờ alias.</div>
  const aliases = q.data?.results ?? []
  return (
    <div>
      <p className="hint" style={{ marginTop: 0 }}>
        Nhập mã canonical để nối alias vào (vd <code>data-analyst</code>). AI không tự tạo mã mới —
        chỉ bạn nối alias lạ vào mã đã có, hoặc từ chối.
      </p>
      {aliases.length === 0 && <div className="empty-box">Không có alias nào chờ xử lý.</div>}
      {aliases.map((a: IntelAlias) => <AliasRow key={a.id} alias={a} onResolve={resolve.mutate} pending={resolve.isPending} />)}
    </div>
  )
}

function AliasRow({
  alias, onResolve, pending,
}: {
  alias: IntelAlias
  onResolve: (v: { id: number; decision: 'accept' | 'reject'; code?: string }) => void
  pending: boolean
}) {
  const [code, setCode] = useState('')
  return (
    <div style={{ display: 'flex', gap: 10, alignItems: 'center', padding: '8px 0', borderBottom: '1px solid var(--border)' }}>
      <div style={{ flex: 1, minWidth: 0 }}>
        <code>{alias.alias_norm}</code>
        <span className="hint"> · {alias.namespace} · nguồn {alias.source || '—'}</span>
      </div>
      <input placeholder="mã canonical" value={code} onChange={(e) => setCode(e.target.value.trim())} style={{ width: 160 }} />
      <button className="btn-primary" disabled={pending || !code}
        onClick={() => onResolve({ id: alias.id, decision: 'accept', code })}>Nối</button>
      <button className="ghost" disabled={pending}
        onClick={() => onResolve({ id: alias.id, decision: 'reject' })}>Bỏ</button>
    </div>
  )
}
