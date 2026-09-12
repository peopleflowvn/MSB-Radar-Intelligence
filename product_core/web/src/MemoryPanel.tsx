import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, MemoryRow, MemoryScope } from './api'

// Trình xem/sửa ghi nhớ dài hạn + tìm lịch sử hội thoại (Master Plan §11.2, §15 GĐ5).
// Hai store: profile (xưng hô, sở thích trình bày) và operational (quy ước nghiệp vụ).
// Đề xuất của AI ở trạng thái pending_review — người dùng tự duyệt.

const SCOPE_LABEL: Record<MemoryScope, string> = {
  profile: 'Hồ sơ của tôi',
  operational: 'Quy ước làm việc với Radar',
}

export default function MemoryPanel() {
  const qc = useQueryClient()
  const q = useQuery({ queryKey: ['ai-memory'], queryFn: () => api.memoryList(), retry: false })
  const del = useMutation({
    mutationFn: (id: number) => api.memoryDelete(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['ai-memory'] }),
  })
  const decide = useMutation({
    mutationFn: (v: { id: number; status: 'active' | 'rejected' }) => api.memoryUpdate(v.id, { status: v.status }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['ai-memory'] }),
  })

  if (q.isError) return <div className="settings-section-card"><div className="empty-box">Không tải được ghi nhớ.</div></div>
  const rows = q.data?.results ?? []
  const pending = rows.filter((r) => r.status === 'pending_review')
  const active = rows.filter((r) => r.status === 'active')

  return (
    <div className="settings-section-card">
      <div className="section-intro">
        <h2>Radar ghi nhớ về tôi</h2>
        <p className="hint">
          Radar chỉ nhớ những gì bạn cho phép. Nội dung ở đây được thêm vào ngữ cảnh mỗi lượt trò
          chuyện. Chi tiết hội thoại cũ không lưu vào đây — tìm lại bằng ô bên dưới.
        </p>
      </div>

      {pending.length > 0 && (
        <>
          <h3 style={{ fontSize: 14, margin: '4px 0 8px', color: 'var(--text)' }}>
            Radar đề xuất ghi nhớ ({pending.length}) — bạn duyệt
          </h3>
          {pending.map((m) => (
            <div key={m.id} style={{ border: '1px dashed var(--accent, #888)', borderRadius: 8, padding: 10, marginBottom: 8 }}>
              <div style={{ fontSize: 13 }}>{m.value}</div>
              <div style={{ display: 'flex', gap: 6, marginTop: 8 }}>
                <button className="btn-primary" disabled={decide.isPending}
                  onClick={() => decide.mutate({ id: m.id, status: 'active' })}>Đồng ý nhớ</button>
                <button className="ghost" disabled={decide.isPending}
                  onClick={() => decide.mutate({ id: m.id, status: 'rejected' })}>Bỏ qua</button>
              </div>
            </div>
          ))}
        </>
      )}

      <AddMemoryForm quota={q.data?.quota} activeCount={active.length} />

      {(['profile', 'operational'] as MemoryScope[]).map((scope) => {
        const list = active.filter((m) => m.scope === scope)
        return (
          <div key={scope} style={{ marginTop: 16 }}>
            <h3 style={{ fontSize: 14, margin: '0 0 8px', color: 'var(--text)' }}>
              {SCOPE_LABEL[scope]}
              {q.data?.quota && <span className="hint"> ({list.length}/{q.data.quota[scope]})</span>}
            </h3>
            {list.length === 0 && <div className="empty-box" style={{ margin: 0 }}>Chưa có.</div>}
            {list.map((m) => <MemoryItem key={m.id} row={m} onDelete={() => del.mutate(m.id)} />)}
          </div>
        )
      })}

      <hr style={{ margin: '24px 0', borderColor: 'var(--border)' }} />
      <HistorySearch />
    </div>
  )
}

function MemoryItem({ row, onDelete }: { row: MemoryRow; onDelete: () => void }) {
  const qc = useQueryClient()
  const [editing, setEditing] = useState(false)
  const [value, setValue] = useState(row.value)
  const save = useMutation({
    mutationFn: () => api.memoryUpdate(row.id, { value }),
    onSuccess: () => { setEditing(false); qc.invalidateQueries({ queryKey: ['ai-memory'] }) },
  })
  return (
    <div style={{ display: 'flex', gap: 8, alignItems: 'flex-start', padding: '6px 0', borderBottom: '1px solid var(--border)' }}>
      {editing ? (
        <>
          <textarea value={value} onChange={(e) => setValue(e.target.value)} rows={2} style={{ flex: 1 }} />
          <button className="btn-primary" disabled={save.isPending} onClick={() => save.mutate()}>Lưu</button>
          <button className="ghost" onClick={() => { setEditing(false); setValue(row.value) }}>Huỷ</button>
        </>
      ) : (
        <>
          <div style={{ flex: 1, fontSize: 13 }}>
            {row.value}
            {row.source === 'radar_ai' && <span className="hint"> · do Radar đề xuất</span>}
          </div>
          <button className="ghost" onClick={() => setEditing(true)}>Sửa</button>
          <button className="ghost" onClick={onDelete}>Xoá</button>
        </>
      )}
    </div>
  )
}

function AddMemoryForm({ quota, activeCount }: { quota?: Record<MemoryScope, number>; activeCount: number }) {
  const qc = useQueryClient()
  const [scope, setScope] = useState<MemoryScope>('operational')
  const [value, setValue] = useState('')
  const [err, setErr] = useState('')
  const add = useMutation({
    mutationFn: () => api.memoryCreate({ scope, value: value.trim() }),
    onSuccess: () => { setValue(''); setErr(''); qc.invalidateQueries({ queryKey: ['ai-memory'] }) },
    onError: (e: Error) => setErr(e.message || 'Không lưu được.'),
  })
  return (
    <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginTop: 8 }}>
      <select value={scope} onChange={(e) => setScope(e.target.value as MemoryScope)}>
        <option value="operational">{SCOPE_LABEL.operational}</option>
        <option value="profile">{SCOPE_LABEL.profile}</option>
      </select>
      <input
        placeholder="Điều bạn muốn Radar nhớ…"
        value={value}
        onChange={(e) => setValue(e.target.value)}
        style={{ flex: 1 }}
        onKeyDown={(e) => { if (e.key === 'Enter' && value.trim()) add.mutate() }}
      />
      <button className="btn-primary" disabled={add.isPending || !value.trim()} onClick={() => add.mutate()}>Thêm</button>
      {err && <span className="error-text">{err}</span>}
      {quota && activeCount >= (quota.profile + quota.operational) && <span className="hint">Đã gần hết hạn mức.</span>}
    </div>
  )
}

function HistorySearch() {
  const [q, setQ] = useState('')
  const search = useQuery({
    queryKey: ['ai-history-search', q],
    queryFn: () => api.searchHistory(q),
    enabled: q.trim().length >= 2,
    retry: false,
  })
  return (
    <div>
      <h3 style={{ fontSize: 14, margin: '0 0 8px', color: 'var(--text)' }}>Tìm trong hội thoại cũ của tôi</h3>
      <input
        placeholder="Từ khoá…"
        value={q}
        onChange={(e) => setQ(e.target.value)}
        style={{ width: '100%', maxWidth: 400 }}
      />
      {search.data && (
        <div style={{ marginTop: 8 }}>
          {search.data.results.length === 0 && <div className="empty-box" style={{ margin: 0 }}>Không thấy.</div>}
          {search.data.results.map((h) => (
            <div key={h.message_id} style={{ padding: '6px 0', borderBottom: '1px solid var(--border)', fontSize: 13 }}>
              <span className="hint">{new Date(h.created_at).toLocaleDateString('vi-VN')} · {h.title || h.surface} · {h.role}</span>
              <div>{h.snippet}</div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
