import { useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, EdgeAdminRow, SourceRecordRow } from './api'
import DataIntake from './DataIntake'

// --- SVG Icons ---
function IconDatabase() {
  return (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <ellipse cx="12" cy="5" rx="9" ry="3" />
      <path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3" />
      <path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5" />
    </svg>
  )
}

function IconServer() {
  return (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <rect x="2" y="2" width="20" height="8" rx="2" ry="2" />
      <rect x="2" y="14" width="20" height="8" rx="2" ry="2" />
      <line x1="6" y1="6" x2="6.01" y2="6" />
      <line x1="6" y1="18" x2="6.01" y2="18" />
    </svg>
  )
}

function IconTable() {
  return (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M3 3h18v18H3zM3 9h18M3 15h18M9 3v18" />
    </svg>
  )
}

function IconPieChart() {
  return (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M21.21 15.89A10 10 0 1 1 8 2.83" />
      <path d="M22 12A10 10 0 0 0 12 2v10z" />
    </svg>
  )
}

function IconSearch() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="11" cy="11" r="8" />
      <line x1="21" y1="21" x2="16.65" y2="16.65" />
    </svg>
  )
}

function IconKey() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M21 2l-2 2m-1.5 1.5L14 9l-1.5-1.5L11 9l-1.5-1.5L8 9 3 14v7h7l5-5 1.5-1.5L18 13l1.5-1.5L21 10z" />
      <circle cx="7.5" cy="16.5" r="1.5" />
    </svg>
  )
}

function IconCopy() {
  return (
    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <rect x="9" y="9" width="13" height="13" rx="2" ry="2" />
      <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
    </svg>
  )
}

function IconCheck() {
  return (
    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
      <polyline points="20 6 9 17 4 12" />
    </svg>
  )
}

function dateTime(value: string | null) {
  return value ? new Date(value).toLocaleString('vi-VN') : 'chưa bao giờ'
}

function getSourceBadgeClass(source: string) {
  const s = source.toLowerCase()
  if (s.includes('linkedin')) return 'source-badge linkedin'
  if (s.includes('topcv')) return 'source-badge topcv'
  if (s.includes('vietnamworks') || s.includes('vnw')) return 'source-badge vietnamworks'
  if (s.includes('facebook') || s.includes('fb')) return 'source-badge facebook'
  if (s.includes('file') || s.includes('excel') || s.includes('import')) return 'source-badge file_import'
  if (s.includes('crm') || s.includes('internal')) return 'source-badge crm'
  return 'source-badge default'
}

/**
 * Quản lý Kết nối Edge & Cấp phát / Thu hồi khóa API
 */
export function EdgeConnections({ canManage }: { canManage: boolean }) {
  const qc = useQueryClient()
  const [newLabel, setNewLabel] = useState('')
  const [issuingFor, setIssuingFor] = useState<number | null>(null)
  const [keyName, setKeyName] = useState('')
  const [justIssued, setJustIssued] = useState<{ edgeId: number; apiKey: string } | null>(null)
  const [copiedKey, setCopiedKey] = useState(false)
  const [edgeSearch, setEdgeSearch] = useState('')
  const [renamingFor, setRenamingFor] = useState<number | null>(null)
  const [renameLabel, setRenameLabel] = useState('')
  const [edgeError, setEdgeError] = useState<string | null>(null)

  const edges = useQuery({ queryKey: ['edge-admin-list'], queryFn: api.edgeAdminList })

  const refresh = () => qc.invalidateQueries({ queryKey: ['edge-admin-list'] })

  const create = useMutation({
    mutationFn: () => api.edgeAdminCreate(newLabel.trim()),
    onSuccess: () => {
      setNewLabel('')
      refresh()
    },
  })

  const toggleActive = useMutation({
    mutationFn: (edge: EdgeAdminRow) => api.edgeAdminUpdate(edge.id, { is_active: !edge.is_active }),
    onSuccess: refresh,
  })

  const issue = useMutation({
    mutationFn: (edgeId: number) => api.edgeAdminIssueKey(edgeId, keyName.trim()),
    onSuccess: (result, edgeId) => {
      setJustIssued({ edgeId, apiKey: result.api_key })
      setIssuingFor(null)
      setKeyName('')
      refresh()
    },
  })

  const revoke = useMutation({
    mutationFn: (keyId: number) => api.edgeAdminRevokeKey(keyId),
    onSuccess: refresh,
  })

  const rename = useMutation({
    mutationFn: (edge: EdgeAdminRow) => api.edgeAdminUpdate(edge.id, { label: renameLabel.trim() }),
    onSuccess: () => {
      setRenamingFor(null)
      setRenameLabel('')
      setEdgeError(null)
      refresh()
    },
    onError: (err: unknown) => {
      setEdgeError(err instanceof Error ? err.message : 'Không thể đổi tên Edge.')
    },
  })

  const remove = useMutation({
    mutationFn: (edge: EdgeAdminRow) => api.edgeAdminDelete(edge.id),
    onSuccess: () => {
      setEdgeError(null)
      refresh()
    },
    onError: (err: unknown) => {
      setEdgeError(err instanceof Error ? err.message : 'Không thể xoá Edge. Hãy thử lại.')
    },
  })

  function handleCopyApiKey(text: string) {
    if (navigator.clipboard) {
      navigator.clipboard.writeText(text)
      setCopiedKey(true)
      setTimeout(() => setCopiedKey(false), 2000)
    }
  }

  function handleRemoveEdge(edge: EdgeAdminRow) {
    const detail = edge.record_count > 0
      ? `Edge đã nạp ${edge.record_count.toLocaleString('vi-VN')} bản ghi. Kết nối và toàn bộ khoá sẽ bị thu hồi; dữ liệu đã nạp vẫn được giữ nguyên.`
      : 'Edge chưa nạp dữ liệu và sẽ được xoá hẳn.'
    if (!window.confirm(`Xoá kết nối Edge "${edge.label}"?\n\n${detail}`)) return
    setEdgeError(null)
    remove.mutate(edge)
  }

  const edgeList = edges.data?.results ?? []
  const filteredEdges = edgeList.filter((edge) => {
    if (!edgeSearch.trim()) return true
    const q = edgeSearch.toLowerCase()
    return (
      edge.label.toLowerCase().includes(q) ||
      (edge.hostname && edge.hostname.toLowerCase().includes(q)) ||
      (edge.edge_id && edge.edge_id.toLowerCase().includes(q))
    )
  })

  return (
    <div className="edge-list-container">
      {/* Header Info & Quick Create */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: '12px' }}>
          <div>
            <h2 style={{ margin: 0, fontSize: '17px', fontWeight: 700, color: 'var(--text)' }}>
              Kết nối Máy trạm Edge (Data Ingestion Nodes)
            </h2>
            <p className="muted" style={{ margin: '4px 0 0', fontSize: '13px' }}>
              Mỗi Edge là một bản cài đặt trên máy tính nhân viên hoặc máy chủ crawler. Cấp khoá API rồi dán vào ứng dụng Edge để đồng bộ dữ liệu về Hub.
            </p>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
            <div className="wf-search-box" style={{ minWidth: '220px' }}>
              <IconSearch />
              <input
                type="text"
                placeholder="Tìm kiếm máy Edge..."
                value={edgeSearch}
                onChange={(e) => setEdgeSearch(e.target.value)}
              />
            </div>
          </div>
        </div>
      </div>

      {edgeError && (
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: '10px',
            background: 'rgba(220, 38, 38, 0.08)',
            border: '1px solid rgba(220, 38, 38, 0.35)',
            color: '#dc2626',
            borderRadius: '10px',
            padding: '10px 14px',
            fontSize: '13px',
          }}
        >
          <span style={{ fontSize: '16px' }}>⚠️</span>
          <span style={{ flex: 1 }}>{edgeError}</span>
          <button
            type="button"
            className="btn btn-ghost"
            style={{ padding: '3px 8px', fontSize: '12px' }}
            onClick={() => setEdgeError(null)}
          >
            Đóng
          </button>
        </div>
      )}

      {canManage && (
        <form
          className="edge-create-bar"
          onSubmit={(event) => {
            event.preventDefault()
            if (newLabel.trim()) create.mutate()
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', color: 'var(--accent)' }}>
            <IconServer />
          </div>
          <input
            type="text"
            className="edge-create-input"
            placeholder="Tên gọi Edge mới — ví dụ: Máy phòng Tuyển dụng, tầng 12"
            value={newLabel}
            onChange={(event) => setNewLabel(event.target.value)}
          />
          <button type="submit" className="btn btn-brand btn-primary" disabled={create.isPending || !newLabel.trim()}>
            {create.isPending ? 'Đang tạo…' : 'Tạo Edge'}
          </button>
        </form>
      )}

      {/* Danh sách các Edge Cards */}
      {filteredEdges.map((edge) => (
        <div className={`edge-card ${!edge.is_active ? 'inactive' : ''}`} key={edge.id}>
          <div className="edge-card-head">
            <div className="edge-card-title">
              <span
                className={`live-pulse ${edge.is_active && edge.last_seen_at ? '' : 'offline'}`}
                title={edge.is_active ? 'Đang kích hoạt' : 'Đã tạm tắt'}
              />
              <span>{edge.label}</span>
              {!edge.is_active && (
                <span className="tag" style={{ background: 'var(--surface-raised)', color: 'var(--muted)' }}>
                  đã tắt
                </span>
              )}
            </div>

            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              {canManage && issuingFor !== edge.id && (
                <button
                  type="button"
                  className="btn btn-sm btn-secondary"
                  style={{ fontSize: '12px', padding: '5px 12px' }}
                  onClick={() => setIssuingFor(edge.id)}
                >
                  <IconKey /> + Cấp khoá mới
                </button>
              )}

              {canManage && (
                <button
                  type="button"
                  className={`btn btn-sm ${edge.is_active ? 'btn-secondary' : 'btn-primary'}`}
                  style={{ fontSize: '12px', padding: '5px 12px' }}
                  disabled={toggleActive.isPending}
                  onClick={() => toggleActive.mutate(edge)}
                >
                  {edge.is_active ? 'Tắt' : 'Bật lại'}
                </button>
              )}

              {canManage && renamingFor !== edge.id && (
                <button
                  type="button"
                  className="btn btn-sm btn-secondary"
                  style={{ fontSize: '12px', padding: '5px 12px' }}
                  onClick={() => {
                    setRenamingFor(edge.id)
                    setRenameLabel(edge.label)
                    setEdgeError(null)
                  }}
                >
                  ✏️ Sửa tên
                </button>
              )}

              {canManage && (
                <button
                  type="button"
                  className="btn btn-sm"
                  style={{
                    fontSize: '12px',
                    padding: '5px 12px',
                    background: 'rgba(220, 38, 38, 0.08)',
                    color: '#dc2626',
                    border: '1px solid rgba(220, 38, 38, 0.35)',
                    cursor: 'pointer',
                  }}
                  disabled={remove.isPending}
                  title="Gỡ kết nối Edge; dữ liệu đã nạp vẫn được giữ nguyên"
                  onClick={() => handleRemoveEdge(edge)}
                >
                  🗑️ Xóa Edge
                </button>
              )}
            </div>
          </div>

          {canManage && renamingFor === edge.id && (
            <form
              className="btn-row"
              style={{ background: 'var(--surface-raised)', padding: '12px 16px', borderRadius: '10px', marginTop: '4px' }}
              onSubmit={(event) => {
                event.preventDefault()
                const val = renameLabel.trim()
                if (!val || val === edge.label) {
                  setRenamingFor(null)
                  return
                }
                rename.mutate(edge)
              }}
            >
              <input
                type="text"
                className="wf-input-text"
                style={{ flex: 1 }}
                placeholder="Tên gọi mới của Edge"
                value={renameLabel}
                onChange={(event) => setRenameLabel(event.target.value)}
                autoFocus
              />
              <button type="submit" className="btn btn-brand btn-primary" disabled={rename.isPending}>
                {rename.isPending ? 'Đang lưu…' : 'Lưu tên mới'}
              </button>
              <button
                type="button"
                className="btn btn-ghost"
                onClick={() => setRenamingFor(null)}
              >
                Huỷ
              </button>
            </form>
          )}

          <div className="edge-meta-chips">
            <div className="edge-meta-item">
              <strong>Mã Edge ID:</strong>{' '}
              {edge.edge_id ? (
                <span style={{ display: 'inline-flex', alignItems: 'center', gap: '6px' }}>
                  <code style={{ background: 'var(--surface-raised)', padding: '2px 8px', borderRadius: '4px', color: 'var(--accent)', fontWeight: 600 }}>
                    {edge.edge_id}
                  </code>
                  <button
                    type="button"
                    className="btn btn-ghost"
                    style={{ padding: '2px 6px', fontSize: '11px', height: 'auto', lineHeight: 1 }}
                    title="Sao chép Edge ID"
                    onClick={() => handleCopyApiKey(edge.edge_id)}
                  >
                    <IconCopy />
                  </button>
                </span>
              ) : (
                <span className="tag" style={{ background: 'rgba(245, 158, 11, 0.15)', color: '#F59E0B', border: '1px solid rgba(245, 158, 11, 0.3)', fontSize: '11px' }}>
                  Chờ kết nối lần đầu (Tự động nhận diện)
                </span>
              )}
            </div>
            <div className="edge-meta-item">
              <strong>Máy:</strong> <code>{edge.hostname || '—'}</code>
            </div>
            <div className="edge-meta-item">
              <strong>Phiên bản:</strong> <span>{edge.app_version || '—'}</span>
            </div>
            <div className="edge-meta-item">
              <strong>Liên lạc gần nhất:</strong> <span>{dateTime(edge.last_seen_at)}</span>
            </div>
            <div className="edge-meta-item">
              <strong>Dữ liệu nạp:</strong>{' '}
              <span style={{ fontWeight: 700, color: 'var(--accent)' }}>
                {edge.record_count.toLocaleString('vi-VN')} bản ghi
              </span>
            </div>
          </div>

          {/* Banner Hiển thị Khóa API vừa cấp */}
          {canManage && justIssued?.edgeId === edge.id && (
            <div className="edge-key-banner">
              <div style={{ fontSize: '24px', lineHeight: 1 }}>🔑</div>
              <div style={{ flex: 1 }}>
                <h3 style={{ margin: 0, fontSize: '14px', fontWeight: 700, color: '#b45309' }}>
                  Chép khoá ngay — sẽ không hiện lại
                </h3>
                <p className="muted small" style={{ margin: '4px 0' }}>
                  Dán vào ô &quot;API key của máy này&quot; trong tab Đồng bộ Hub của ứng dụng Edge. Vì lý do an ninh, hệ thống không lưu khóa thô sau phiên này.
                </p>
                <div className="edge-key-box">
                  <code>{justIssued.apiKey}</code>
                  <button
                    type="button"
                    className="btn btn-sm btn-secondary"
                    style={{ padding: '4px 10px', fontSize: '12px' }}
                    onClick={() => handleCopyApiKey(justIssued.apiKey)}
                  >
                    {copiedKey ? (
                      <>
                        <IconCheck /> Đã chép!
                      </>
                    ) : (
                      <>
                        <IconCopy /> Chép khoá
                      </>
                    )}
                  </button>
                </div>
                <button
                  type="button"
                  className="btn btn-sm btn-secondary"
                  style={{ marginTop: '4px' }}
                  onClick={() => setJustIssued(null)}
                >
                  Đã chép, đóng lại
                </button>
              </div>
            </div>
          )}

          {/* Form Cấp Khóa Mới */}
          {canManage && issuingFor === edge.id && (
            <form
              className="btn-row"
              style={{ background: 'var(--surface-raised)', padding: '12px 16px', borderRadius: '10px', marginTop: '4px' }}
              onSubmit={(event) => {
                event.preventDefault()
                issue.mutate(edge.id)
              }}
            >
              <input
                type="text"
                className="wf-input-text"
                style={{ flex: 1 }}
                placeholder="Ghi chú (tuỳ chọn) — ví dụ: đợt cấp tháng 9"
                value={keyName}
                onChange={(event) => setKeyName(event.target.value)}
              />
              <button type="submit" className="btn btn-brand btn-primary" disabled={issue.isPending}>
                {issue.isPending ? 'Đang cấp…' : 'Xác nhận cấp khoá'}
              </button>
              <button
                type="button"
                className="btn btn-ghost"
                onClick={() => setIssuingFor(null)}
              >
                Huỷ
              </button>
            </form>
          )}

          {/* Bảng Danh sách API Keys của Edge */}
          <div style={{ overflowX: 'auto' }}>
            <table className="edge-key-table">
              <thead>
                <tr>
                  <th style={{ width: '140px' }}>Khoá (Prefix)</th>
                  <th>Ghi chú</th>
                  <th style={{ width: '180px' }}>Cấp lúc</th>
                  <th style={{ width: '180px' }}>Dùng gần nhất</th>
                  <th style={{ width: '130px' }}>Trạng thái</th>
                  {canManage && <th style={{ width: '100px', textAlign: 'right' }}>Thao tác</th>}
                </tr>
              </thead>
              <tbody>
                {edge.api_keys.map((key) => (
                  <tr key={key.id}>
                    <td>
                      <code style={{ background: 'var(--surface-raised)', padding: '2px 6px', borderRadius: '4px' }}>
                        {key.prefix}…
                      </code>
                    </td>
                    <td>{key.name || '—'}</td>
                    <td style={{ fontSize: '12px', color: 'var(--muted)' }}>{dateTime(key.created_at)}</td>
                    <td style={{ fontSize: '12px', color: 'var(--muted)' }}>{dateTime(key.last_used_at)}</td>
                    <td>
                      <span className={`source-badge ${key.is_active ? 'topcv' : 'default'}`}>
                        {key.is_active ? 'còn hiệu lực' : 'đã thu hồi'}
                      </span>
                    </td>
                    {canManage && (
                      <td style={{ textAlign: 'right' }}>
                        {key.is_active && (
                          <button
                            type="button"
                            className="btn btn-sm btn-secondary"
                            style={{ fontSize: '11.5px', padding: '4px 10px' }}
                            disabled={revoke.isPending}
                            onClick={() => revoke.mutate(key.id)}
                          >
                            Thu hồi
                          </button>
                        )}
                      </td>
                    )}
                  </tr>
                ))}
                {edge.api_keys.length === 0 && (
                  <tr>
                    <td colSpan={canManage ? 6 : 5} className="empty" style={{ textAlign: 'center', padding: '16px', color: 'var(--muted)' }}>
                      Chưa có khoá nào.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      ))}

      {filteredEdges.length === 0 && (
        <div style={{ textAlign: 'center', padding: '40px 20px', background: 'var(--surface)', borderRadius: '12px', border: '1px solid var(--border)' }}>
          <p className="empty" style={{ margin: 0, color: 'var(--muted)' }}>
            Chưa có Edge nào.{' '}
            {canManage
              ? 'Tạo Edge ở ô phía trên rồi cấp khoá.'
              : 'Nhờ quản trị viên tạo Edge và cấp khoá.'}
          </p>
        </div>
      )}
    </div>
  )
}

/**
 * Trình Duyệt Kho Bản ghi Nguồn Thô (Source Records Explorer)
 */
function SourceRecordsExplorer({
  records,
  search,
  onSearchChange,
}: {
  records: ReturnType<typeof useQuery<{ count: number; results: SourceRecordRow[] }>>
  search: string
  onSearchChange: (val: string) => void
}) {
  const [selectedSource, setSelectedSource] = useState<string>('all')

  const results = records.data?.results ?? []

  const sourcesList = useMemo(() => {
    const s = new Set<string>()
    results.forEach((r) => {
      if (r.source) s.add(r.source)
    })
    return Array.from(s)
  }, [results])

  const filtered = useMemo(() => {
    if (selectedSource === 'all') return results
    return results.filter((r) => r.source === selectedSource)
  }, [results, selectedSource])

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
      {/* Controls Bar */}
      <div className="wf-controls-bar">
        <div className="wf-search-box" style={{ flex: 1, maxWidth: '400px' }}>
          <IconSearch />
          <input
            type="search"
            placeholder="Tìm theo tên, email, số điện thoại, vị trí…"
            value={search}
            onChange={(e) => onSearchChange(e.target.value)}
          />
        </div>

        <div className="wf-filters-group">
          <button
            type="button"
            className={`wf-filter-chip ${selectedSource === 'all' ? 'active' : ''}`}
            onClick={() => setSelectedSource('all')}
          >
            Tất cả nguồn ({results.length})
          </button>
          {sourcesList.map((src) => (
            <button
              key={src}
              type="button"
              className={`wf-filter-chip ${selectedSource === src ? 'active' : ''}`}
              onClick={() => setSelectedSource(src)}
            >
              <span className={getSourceBadgeClass(src)} style={{ padding: '0 4px', fontSize: '10px' }}>
                {src}
              </span>
            </button>
          ))}
        </div>
      </div>

      {/* Bảng Bản ghi Nguồn */}
      <div className="wf-table-container">
        <table className="wf-table">
          <thead>
            <tr>
              <th style={{ minWidth: '180px' }}>Họ tên</th>
              <th style={{ minWidth: '160px' }}>Vị trí / Chức danh</th>
              <th style={{ minWidth: '180px' }}>Email</th>
              <th style={{ minWidth: '130px' }}>Điện thoại</th>
              <th style={{ width: '130px' }}>Nguồn dữ liệu</th>
              <th style={{ minWidth: '160px' }}>Edge thu thập</th>
              <th style={{ minWidth: '150px' }}>Đồng bộ lúc</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((row) => (
              <tr key={row.id}>
                <td>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                    <span style={{ fontWeight: 600, color: 'var(--text)' }}>
                      {row.fullname || '—'}
                    </span>
                    {row.revision > 1 && (
                      <span className="tag" style={{ fontSize: '10.5px', padding: '1px 5px' }}>
                        v{row.revision}
                      </span>
                    )}
                  </div>
                </td>
                <td style={{ color: 'var(--text-secondary)' }}>{row.position || '—'}</td>
                <td>
                  {row.email ? (
                    <a href={`mailto:${row.email}`} className="link" style={{ fontSize: '13px' }}>
                      {row.email}
                    </a>
                  ) : (
                    '—'
                  )}
                </td>
                <td>{row.phone || '—'}</td>
                <td>
                  <span className={getSourceBadgeClass(row.source)}>
                    {row.source}
                  </span>
                </td>
                <td style={{ fontSize: '12.5px' }}>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '3px' }}>
                    <span style={{ fontWeight: 600, color: 'var(--text)' }}>
                      {row.edge_label || '—'}
                    </span>
                    {row.edge_id ? (
                      <span style={{ display: 'inline-flex', alignItems: 'center' }}>
                        <code
                          style={{
                            fontSize: '11px',
                            color: 'var(--muted)',
                            background: 'var(--surface-raised)',
                            padding: '1px 5px',
                            borderRadius: '3px',
                            maxWidth: '150px',
                            overflow: 'hidden',
                            textOverflow: 'ellipsis',
                            whiteSpace: 'nowrap',
                          }}
                          title={`Mã Edge ID: ${row.edge_id}`}
                        >
                          {row.edge_id}
                        </code>
                      </span>
                    ) : null}
                  </div>
                </td>
                <td style={{ fontSize: '12.5px', whiteSpace: 'nowrap' }}>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '3px' }}>
                    <span style={{ fontWeight: 600, color: 'var(--text)' }}>
                      {row.last_seen_at ? new Date(row.last_seen_at).toLocaleString('vi-VN') : '—'}
                    </span>
                    {row.first_seen_at && row.revision > 1 ? (
                      <span style={{ color: 'var(--muted)', fontSize: '11px' }}>
                        Lần đầu: {new Date(row.first_seen_at).toLocaleString('vi-VN')}
                      </span>
                    ) : null}
                  </div>
                </td>
              </tr>
            ))}
            {filtered.length === 0 && (
              <tr>
                <td colSpan={7} style={{ textAlign: 'center', padding: '36px', color: 'var(--muted)' }}>
                  Không có bản ghi nào khớp.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}

/**
 * Thống kê Phân bổ Nguồn Dữ liệu (Source Breakdown)
 */
function SourceBreakdownView({
  bySource,
  totalRecords,
}: {
  bySource: Array<{ source: string; count: number }>
  totalRecords: number
}) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
      <div className="source-breakdown-grid">
        {bySource.map((item) => {
          const percent = totalRecords > 0 ? Math.round((item.count / totalRecords) * 100) : 0
          return (
            <div key={item.source} className="source-breakdown-card">
              <div className="source-breakdown-top">
                <span className={getSourceBadgeClass(item.source)} style={{ fontSize: '12px' }}>
                  {item.source}
                </span>
                <span style={{ fontWeight: 700, fontSize: '16px', color: 'var(--text)' }}>
                  {item.count.toLocaleString('vi-VN')}
                </span>
              </div>

              <div className="source-progress-bar-bg">
                <div
                  className="source-progress-bar-fill"
                  style={{ width: `${percent}%` }}
                />
              </div>

              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '12px', color: 'var(--muted)' }}>
                <span>Tỷ trọng kho dữ liệu</span>
                <strong>{percent}%</strong>
              </div>
            </div>
          )
        })}

        {bySource.length === 0 && (
          <div style={{ gridColumn: '1 / -1', textAlign: 'center', padding: '40px', background: 'var(--surface)', borderRadius: '12px', border: '1px solid var(--border)' }}>
            <p className="empty" style={{ margin: 0, color: 'var(--muted)' }}>
              Chưa có dữ liệu phân bổ nguồn.
            </p>
          </div>
        )}
      </div>
    </div>
  )
}

/**
 * Component Trang Data Chính (/data)
 */
export default function Data() {
  const [activeTab, setActiveTab] = useState<'edges' | 'records' | 'sources' | 'intake'>('edges')
  const [search, setSearch] = useState('')

  const session = useQuery({ queryKey: ['me'], queryFn: api.me })
  const canManage = Boolean(
    session.data?.authenticated &&
      (session.data.is_superuser || session.data.roles.includes('admin')),
  )
  // Người chỉ có quyền Nhập liệu (không có Vận hành Edge) chỉ thấy tab Nhập liệu.
  const canEdgeOps = Boolean(
    session.data?.authenticated && (session.data.modules ?? []).includes('edge_ops'),
  )

  useEffect(() => {
    if (session.data?.authenticated && !canEdgeOps) setActiveTab('intake')
  }, [session.data, canEdgeOps])

  const summary = useQuery({
    queryKey: ['summary'],
    queryFn: api.summary,
    retry: false,
    enabled: canEdgeOps,
  })
  const records = useQuery({
    queryKey: ['records', search],
    queryFn: () => api.sourceRecords(search),
    retry: false,
    enabled: canEdgeOps,
  })

  const edgeCount = summary.data?.edges ?? 0
  const recordCount = summary.data?.source_records ?? 0
  const bySource = summary.data?.by_source ?? []

  return (
    <div className="data-page-container">
      {/* Header Banner & Context */}
      <div className="data-header-card">
        <div className="data-header-main">
          <div className="data-header-title-group">
            <div className="data-header-icon">
              <IconDatabase />
            </div>
            <div>
              <h1 className="data-header-title">
                Hạ tầng Dữ liệu &amp; Quản lý Edge (Data Ingestion Hub)
              </h1>
              <p className="data-header-desc">
                Giám sát các máy trạm Edge thu thập dữ liệu phân tán, cấp phát khoá API an toàn và tra cứu kho bản ghi nguồn thô của hệ thống.
              </p>
            </div>
          </div>
        </div>

        {/* Sub-tabs Navigation */}
        <div className="data-tabs-bar">
          <div className="data-subtabs">
            {canEdgeOps && (
              <>
                <button
                  type="button"
                  className={`data-tab-btn ${activeTab === 'edges' ? 'active' : ''}`}
                  onClick={() => setActiveTab('edges')}
                >
                  <IconServer />
                  <span>Kết nối Edge</span>
                  <span className="data-tab-count">{edgeCount}</span>
                </button>

                <button
                  type="button"
                  className={`data-tab-btn ${activeTab === 'records' ? 'active' : ''}`}
                  onClick={() => setActiveTab('records')}
                >
                  <IconTable />
                  <span>Bản ghi Nguồn</span>
                  <span className="data-tab-count">
                    {records.data ? records.data.count.toLocaleString('vi-VN') : recordCount.toLocaleString('vi-VN')}
                  </span>
                </button>

                <button
                  type="button"
                  className={`data-tab-btn ${activeTab === 'sources' ? 'active' : ''}`}
                  onClick={() => setActiveTab('sources')}
                >
                  <IconPieChart />
                  <span>Phân bổ Nguồn</span>
                  <span className="data-tab-count">{bySource.length}</span>
                </button>
              </>
            )}

            <button
              type="button"
              className={`data-tab-btn ${activeTab === 'intake' ? 'active' : ''}`}
              onClick={() => setActiveTab('intake')}
            >
              <IconTable />
              <span>Nhập liệu</span>
            </button>
          </div>
        </div>
      </div>

      {/* KPI Metrics Ribbon */}
      {canEdgeOps && (
      <div className="data-metrics-grid">
        <div className="data-metric-card">
          <div
            className="data-metric-icon"
            style={{ background: 'rgba(37, 99, 235, 0.1)', color: '#2563eb' }}
          >
            🖥️
          </div>
          <div className="data-metric-content">
            <span className="data-metric-val">{summary.data?.edges ?? '—'}</span>
            <span className="data-metric-lbl">Edge đã kết nối</span>
          </div>
        </div>

        <div className="data-metric-card">
          <div
            className="data-metric-icon"
            style={{ background: 'rgba(16, 185, 129, 0.1)', color: '#10b981' }}
          >
            📋
          </div>
          <div className="data-metric-content">
            <span className="data-metric-val">{summary.data?.edges_registered ?? '—'}</span>
            <span className="data-metric-lbl">Đã đăng ký</span>
          </div>
        </div>

        <div className="data-metric-card">
          <div
            className="data-metric-icon"
            style={{ background: 'rgba(245, 158, 11, 0.1)', color: '#d97706' }}
          >
            📥
          </div>
          <div className="data-metric-content">
            <span className="data-metric-val">
              {summary.data?.source_records != null ? summary.data.source_records.toLocaleString('vi-VN') : '—'}
            </span>
            <span className="data-metric-lbl">Bản ghi nguồn</span>
          </div>
        </div>

        <div className="data-metric-card">
          <div
            className="data-metric-icon"
            style={{ background: 'rgba(139, 92, 246, 0.1)', color: '#7c3aed' }}
          >
            🔄
          </div>
          <div className="data-metric-content">
            <span className="data-metric-val">
              {summary.data?.pending_resolution != null ? summary.data.pending_resolution.toLocaleString('vi-VN') : '—'}
            </span>
            <span className="data-metric-lbl">Chờ phân giải</span>
          </div>
        </div>
      </div>
      )}

      {/* Nội dung Tab Tương ứng */}
      {activeTab === 'edges' && canEdgeOps && <EdgeConnections canManage={canManage} />}

      {activeTab === 'records' && (
        <SourceRecordsExplorer
          records={records}
          search={search}
          onSearchChange={setSearch}
        />
      )}

      {activeTab === 'sources' && (
        <SourceBreakdownView
          bySource={bySource}
          totalRecords={recordCount}
        />
      )}

      {activeTab === 'intake' && <DataIntake />}
    </div>
  )
}
