import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import React, { useEffect, useState } from 'react'
import { Link, useParams, useSearchParams } from 'react-router-dom'
import { api, ApiError, DocumentRow, DocumentStats, IndexHealth, PersonAskTurn, PersonDetail } from './api'
import ContactUnlock from './ContactUnlock'
import FormattedMarkdown from './FormattedMarkdown'
import { HuntAssignModal } from './HuntAssignModal'
import PersonFactsSection from './PersonFacts'
import { useCustomTheme } from './CustomThemeContext'

/**
 * Person 360 (Master Plan mục 24) — Trung tâm Hồ sơ 360° Hợp Nhất (/person/:id)
 * Gộp toàn diện Hồ sơ Ứng viên (Talent Radar) & Hồ sơ Khách hàng (Growth Radar).
 * Cột trái (65%): Thông tin năng lực, kỹ năng, cơ hội tài chính & bán chéo, đợt tuyển và định danh.
 * Cột phải (35%): Tự động hiển thị Quan hệ tương ứng theo ngữ cảnh (Talent/Growth) & phân quyền vai trò.
 * Quyền xem CV: Recruiter / TA / Admin được xem; RM / Sales không xem được CV.
 */

type RelationshipTab = 'talent' | 'rb'

function bytes(size: number) {
  if (!size) return '—'
  if (size < 1024) return `${size} B`
  if (size < 1024 * 1024) return `${Math.round(size / 1024)} KB`
  return `${(size / 1024 / 1024).toFixed(1)} MB`
}

function date(value: string | null | undefined) {
  return value ? new Date(value).toLocaleDateString('vi-VN') : '—'
}

function dateTime(value: string | null | undefined) {
  return value ? new Date(value).toLocaleString('vi-VN') : '—'
}

/** Trình nhúng xem trước tài liệu Blob URL chống lỗi Cross-Origin & Security Headers */
function DocumentPreviewFrame({ documentId, filename }: { documentId: number; filename?: string }) {
  const [blobUrl, setBlobUrl] = useState<string | null>(() => {
    return typeof URL.createObjectURL === 'function' ? null : api.documentPreviewUrl(documentId)
  })
  const [htmlContent, setHtmlContent] = useState<string | null>(null)
  const [isLoading, setIsLoading] = useState(() => typeof URL.createObjectURL === 'function')
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (typeof URL.createObjectURL !== 'function') {
      setBlobUrl(api.documentPreviewUrl(documentId))
      setIsLoading(false)
      return
    }

    let active = true
    let createdUrl: string | null = null
    setIsLoading(true)
    setError(null)

    fetch(api.documentPreviewUrl(documentId), { credentials: 'same-origin' })
      .then(async (res) => {
        if (!res.ok) {
          let msg = `Không thể tải bản xem trước (HTTP ${res.status})`
          try {
            const data = await res.json()
            if (data.detail) msg = data.detail
          } catch {
            // bỏ qua
          }
          throw new Error(msg)
        }
        const contentType = (res.headers.get('content-type') || '').toLowerCase()
        if (contentType.includes('text/html')) {
          const text = await res.text()
          if (active) {
            setHtmlContent(text)
            setIsLoading(false)
          }
        } else {
          const blob = await res.blob()
          if (active) {
            createdUrl = URL.createObjectURL(blob)
            setBlobUrl(createdUrl)
            setIsLoading(false)
          }
        }
      })
      .catch(() => {
        if (active) {
          // Nếu fetch bị chặn ở môi trường kiểm thử hoặc mạng riêng, fallback về URL trực tiếp
          setBlobUrl(api.documentPreviewUrl(documentId))
          setIsLoading(false)
        }
      })

    return () => {
      active = false
      if (createdUrl && typeof URL.revokeObjectURL === 'function') {
        URL.revokeObjectURL(createdUrl)
      }
    }
  }, [documentId])

  if (isLoading) {
    return (
      <div className="empty-results-box" style={{ padding: '60px 20px' }}>
        <div className="radar-loading-pulse-dot" style={{ margin: '0 auto 12px', width: '12px', height: '12px' }} />
        <p style={{ margin: 0, color: 'var(--text-muted)' }}>Đang chuẩn bị bản xem trước tài liệu…</p>
      </div>
    )
  }

  if (error) {
    return (
      <div className="empty-results-box" style={{ padding: '40px 20px' }}>
        <div style={{ fontSize: '32px', marginBottom: '8px' }}>📄</div>
        <p style={{ color: 'var(--text-primary)', fontWeight: 600 }}>{error}</p>
        <p style={{ color: 'var(--text-muted)', fontSize: '13px' }}>
          Bạn có thể xem trực tiếp bản văn bản bóc tách hoặc tải tệp gốc về máy.
        </p>
        <a className="btn btn-primary btn-sm" href={api.documentUrl(documentId)} download style={{ marginTop: '8px' }}>
          ⬇ Tải file gốc về
        </a>
      </div>
    )
  }

  if (htmlContent) {
    return (
      <iframe
        title={filename || `Document ${documentId}`}
        srcDoc={htmlContent}
        className="cv-pdf-iframe"
        sandbox="allow-same-origin allow-popups allow-downloads"
      />
    )
  }

  if (blobUrl) {
    return (
      <iframe
        title={filename || `Document ${documentId}`}
        src={blobUrl}
        className="cv-pdf-iframe"
      />
    )
  }

  return null
}

export function maskEmail(email: string): string {
  if (!email || !email.includes('@')) return email
  const [local, domain] = email.split('@')
  if (local.length <= 2) {
    return `${local[0] || ''}***@${domain}`
  }
  return `${local.slice(0, 2)}***${local.slice(-1)}@${domain}`
}

export function maskPhone(phone: string): string {
  if (!phone) return phone
  const clean = phone.replace(/\s+/g, '')
  if (clean.length <= 6) return clean.replace(/^(.)(.*)(.)$/, '$1***$3')
  return clean.replace(/^(\+?\d{3,4})\d+(\d{3})$/, '$1***$2')
}

export function maskTextContent(text: string): string {
  if (!text) return ''
  let masked = text.replace(/[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}/g, (match) => maskEmail(match))
  masked = masked.replace(/(?:\+?84|0)(?:[\s.-]?\d){8,10}/g, (match) => maskPhone(match))
  return masked
}

/** 1. TRÌNH XEM TRƯỚC NỘI DUNG CV & SO SÁNH PHIÊN BẢN (CV VAULT) */
function CvViewerSection({
  documents,
  stats,
  isUnlocked,
}: {
  documents: DocumentRow[]
  stats: DocumentStats
  isUnlocked?: boolean
}) {
  const { maskSensitiveData } = useCustomTheme()
  const shouldMask = maskSensitiveData || !isUnlocked

  const [selectedDocId, setSelectedDocId] = useState<number>(() => {
    return documents.length > 0 ? documents[documents.length - 1].id : 0
  })
  const [copySuccess, setCopySuccess] = useState(false)
  const [showText, setShowText] = useState(false)
  const [selectedTextId, setSelectedTextId] = useState<number | null>(null)
  const [isExpanded, setIsExpanded] = useState(false)

  const currentDoc = documents.find((d) => d.id === selectedDocId) || documents[documents.length - 1]
  const documentText = useQuery({
    queryKey: ['talent-document-text', currentDoc?.id],
    queryFn: () => api.documentText(currentDoc!.id),
    enabled: Boolean(showText && currentDoc && currentDoc.text_length > 0),
  })

  if (!currentDoc) {
    return (
      <div className="empty-results-box">
        <div className="empty-icon">📄</div>
        <h3>Chưa có file CV nào được đồng bộ</h3>
        <p>Hồ sơ này chưa có tệp đính kèm hoặc văn bản CV nào từ các nguồn ứng tuyển.</p>
      </div>
    )
  }

  const textVersions = documentText.data?.versions ?? []
  const selectedText = textVersions.find((version) => version.id === selectedTextId)
    ?? textVersions.find((version) => version.is_primary)
    ?? textVersions[0]
  const rawText = selectedText?.text ?? ''
  const parsedText = shouldMask ? maskTextContent(rawText) : rawText

  const handleCopyText = () => {
    if (!parsedText) return
    navigator.clipboard.writeText(parsedText)
    setCopySuccess(true)
    setTimeout(() => setCopySuccess(false), 3000)
  }

  return (
    <div className="cv-management-workspace">
      <div className={`cv-version-summary ${stats.unparsed_count ? 'warn' : ''}`}>
        <strong>Kho CV có {stats.submission_count} lượt nộp · {stats.file_version_count} file gốc</strong>
        <span>{stats.distinct_text_count} nội dung khác nhau</span>
        <span>{stats.duplicate_text_count} lượt trùng nội dung</span>
        <span>{stats.text_variant_count} kết quả parsing được giữ</span>
        {stats.unparsed_count > 0 && <span className="badge warn">⚠ {stats.unparsed_count} CV chưa parsing</span>}
        {stats.ai_retry_count > 0 && <span className="badge warn">⚠ {stats.ai_retry_count} CV cần AI chạy lại</span>}
        {stats.preview_pending_count > 0 && <span className="badge warn">◷ {stats.preview_pending_count} preview đang chờ</span>}
      </div>
      {/* Thanh chọn các phiên bản CV */}
      <div className="cv-version-selector-card">
        <div className="cv-version-header">
          <span className="version-list-title">📚 Các phiên bản CV đã ghi nhận ({documents.length}):</span>
          <span className="version-hint">Bấm chọn để xem file gốc và lịch sử parsing tương ứng</span>
        </div>
        <div className="cv-version-chips">
          {documents.map((doc, idx) => {
            const isLatest = idx === documents.length - 1
            const isSelected = doc.id === currentDoc.id
            return (
              <button
                key={doc.id}
                type="button"
                className={`cv-version-chip-btn ${isSelected ? 'active' : ''}`}
                onClick={() => { setSelectedDocId(doc.id); setShowText(false); setSelectedTextId(null) }}
              >
                <span className="v-tag">v{doc.version}</span>
                <span className="v-date">{date(doc.observed_at || doc.created_at)}</span>
                <span className="v-source">({doc.source || 'File'})</span>
                {isLatest && <span className="latest-pill">Mới nhất</span>}
                {doc.used_by > 1 && (
                  <span className="used-badge" title={`Dùng cho ${doc.used_by} lần nộp`}>
                    🔗 {doc.used_by}
                  </span>
                )}
                {doc.same_content_occurrences > 1 && (
                  <span className="duplicate-text-badge" title={`${doc.same_content_occurrences} lượt nộp có cùng nội dung parsing`}>
                    Trùng ×{doc.same_content_occurrences}
                  </span>
                )}
              </button>
            )
          })}
        </div>
      </div>

      {/* Khung chi tiết & Trình xem nội dung CV */}
      <div className="cv-viewer-container">
        <div className="cv-viewer-header">
          <div className="cv-file-meta">
            <div className="cv-file-icon">📄</div>
            <div>
              <h3 className="cv-filename">{currentDoc.filename || `Phiên bản CV v${currentDoc.version}`}</h3>
              <div className="cv-meta-row">
                <span>📅 Ngày ghi nhận: <strong>{date(currentDoc.observed_at || currentDoc.created_at)}</strong></span>
                <span>📦 Nguồn: <strong>{currentDoc.source || 'Trực tiếp'}</strong></span>
                <span>⚖️ Dung lượng: <strong>{bytes(currentDoc.file_size)}</strong></span>
                {currentDoc.text_length > 0 && (
                  <span>📝 Độ dài văn bản: <strong>{currentDoc.text_length.toLocaleString('vi-VN')} ký tự</strong></span>
                )}
              </div>
            </div>
          </div>
          <div className="cv-actions-toolbar">
            {currentDoc.text_length > 0 && (
              <button
                type="button"
                className="btn btn-secondary btn-sm"
                onClick={() => setShowText(true)}
              >
                📝 Xem văn bản trích xuất ({currentDoc.text_variant_count || 1})
              </button>
            )}
            {currentDoc.has_file && (
              <a
                className="btn btn-secondary btn-sm"
                href={api.documentPreviewUrl(currentDoc.id)}
                target="_blank"
                rel="noreferrer"
                title="Mở tài liệu trong tab mới của trình duyệt"
              >
                ↗ Mở tab mới
              </a>
            )}
            {currentDoc.has_file ? (
              <a
                className="btn btn-primary btn-sm"
                href={api.documentUrl(currentDoc.id)}
                download
              >
                ⬇ Tải file gốc về
              </a>
            ) : (
              <span className="badge warn">Chưa lưu trữ file gốc</span>
            )}
            <button
              type="button"
              className="btn btn-secondary btn-sm"
              onClick={() => setIsExpanded(!isExpanded)}
              title={isExpanded ? 'Thu nhỏ khung xem' : 'Mở rộng khung xem'}
            >
              {isExpanded ? '↕ Thu nhỏ' : '↕ Mở rộng'}
            </button>
          </div>
        </div>

        {/* Khung nội dung tài liệu */}
        <div className="cv-document-body">
          {currentDoc.has_file || currentDoc.text_length > 0 ? (
            <div className="cv-embed-frame-box" style={{ height: isExpanded ? '840px' : '580px', transition: 'height 0.25s ease' }}>
              <DocumentPreviewFrame
                documentId={currentDoc.id}
                filename={currentDoc.filename || `CV v${currentDoc.version}`}
              />
            </div>
          ) : (
            <div className="empty-results-box" style={{ padding: '30px' }}>
              <p>{currentDoc.preview_status === 'failed'
                ? `Chưa tạo được bản xem trước: ${currentDoc.preview_error || 'hãy thử lại.'}`
                : 'Chưa có nội dung tệp để xem trước.'}</p>
            </div>
          )}
        </div>
      </div>

      {showText && (
        <div className="cv-text-modal-overlay" role="presentation" onMouseDown={() => setShowText(false)}>
          <div className="cv-text-modal" role="dialog" aria-modal="true" aria-label="Văn bản trích xuất từ CV" onMouseDown={(event) => event.stopPropagation()}>
            <div className="cv-text-modal-header">
              <div>
                <strong>Văn bản trích xuất · {currentDoc.filename || `CV v${currentDoc.version}`}</strong>
                <div className="muted small">
                  {shouldMask ? '🔒 Email và SĐT trong văn bản đang được che bảo mật.' : 'Các kết quả khác nhau đều được giữ; bản chính dùng cho tìm kiếm được đánh dấu.'}
                </div>
              </div>
              <button type="button" className="ghost" aria-label="Đóng cửa sổ văn bản" onClick={() => setShowText(false)}>×</button>
            </div>
            <div className="cv-text-version-tabs">
              {textVersions.map((version, index) => (
                <button key={version.id} type="button" className={`cv-text-version-btn ${selectedText?.id === version.id ? 'active' : ''}`} onClick={() => setSelectedTextId(version.id)}>
                  Bản {index + 1}{version.is_primary ? ' · Đang dùng' : ''}
                  <small>{version.origins.join(', ')}{version.model ? ` · ${version.model}` : ''}</small>
                </button>
              ))}
            </div>
            <div className="cv-text-modal-toolbar">
              <span>{selectedText ? `${selectedText.text_length.toLocaleString('vi-VN')} ký tự` : 'Đang tải…'}</span>
              <button type="button" className="btn btn-secondary btn-sm" onClick={handleCopyText} disabled={!parsedText}>
                {copySuccess ? '✓ Đã sao chép!' : '📋 Sao chép văn bản'}
              </button>
            </div>
            {documentText.isLoading ? <div className="app-loading hint">Đang tải văn bản…</div> : (
              <pre className="cv-text-modal-content">{parsedText || documentText.data?.parse_error || 'Chưa có nội dung parsing.'}</pre>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

const CANDIDATE_STATES = [
  ['new', 'Chưa tiếp cận'], ['attempted', 'Đã thử liên hệ'],
  ['connected', 'Đã kết nối'], ['interested', 'Quan tâm cơ hội'],
  ['nurturing', 'Đang nuôi dưỡng'], ['ready', 'Sẵn sàng giới thiệu'],
  ['placed', 'Đã tuyển dụng'], ['unavailable', 'Chưa sẵn sàng'],
  ['do_not_contact', 'Không liên hệ'],
] as const

/** 2. QUẢN LÝ QUAN HỆ ỨNG VIÊN (TALENT RADAR - CANDIDATE RELATIONSHIP) */
function CandidateRelationship({ person }: { person: PersonDetail }) {
  const qc = useQueryClient()
  const relation = useQuery({ queryKey: ['talent-relationship', person.id], queryFn: () => api.talentRelationship(person.id) })
  const facets = useQuery({ queryKey: ['talent-facets'], queryFn: api.talentFacets })
  const update = useMutation({
    mutationFn: (patch: Record<string, unknown>) => api.talentRelationshipUpdate(person.id, patch),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['talent-relationship', person.id] })
      qc.invalidateQueries({ queryKey: ['person', person.id] })
    },
  })

  if (!relation.data) return <section className="person-section-card"><p className="muted">Đang tải quan hệ ứng viên…</p></section>
  const row = relation.data
  const preferences = row.preferences ?? {}
  const patchPreference = (key: string, value: string | boolean) => update.mutate({ preferences: { ...preferences, [key]: value } })
  const overdue = !!row.next_action_at && new Date(row.next_action_at) < new Date()

  return (
    <section className="person-section-card talent-rel-card">
      <div className="section-title-row">
        <h3 className="section-title">💼 Quan hệ Ứng viên (Talent Radar)</h3>
        <div style={{ display: 'flex', gap: '6px', alignItems: 'center', flexWrap: 'wrap' }}>
          {overdue && <span className="badge err">⚠️ Quá hạn</span>}
          {row.do_not_contact && <span className="badge err">🚫 Không liên hệ</span>}
        </div>
      </div>
      <p className="hint">Trạng thái chăm sóc &amp; nuôi dưỡng quan hệ lâu dài của Recruiter với ứng viên.</p>

      {/* 1. Trạng thái & Phụ trách */}
      <div className="talent-rel-section">
        <div className="talent-rel-grid-2">
          <label className="talent-rel-field">
            <span className="talent-rel-label">🎯 Trạng thái tuyển dụng</span>
            <select className="talent-rel-select" value={row.state} onChange={e => update.mutate({ state: e.target.value })}>
              {CANDIDATE_STATES.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
            </select>
          </label>
          <label className="talent-rel-field">
            <span className="talent-rel-label">👤 Recruiter phụ trách</span>
            <select className="talent-rel-select" value={row.owner_id ?? ''} onChange={e => update.mutate({ owner_id: e.target.value ? Number(e.target.value) : null })}>
              <option value="">Chưa phân công</option>
              {(facets.data?.owners ?? []).map(owner => <option key={owner.id} value={owner.id}>{owner.name}</option>)}
            </select>
          </label>
        </div>

        <div className="talent-rel-grid-2" style={{ marginTop: '12px' }}>
          <label className="talent-rel-field">
            <span className="talent-rel-label">⭐ Mức độ quan tâm</span>
            <select className="talent-rel-select" value={row.interest_level} onChange={e => update.mutate({ interest_level: Number((e.target as HTMLSelectElement).value) })}>
              <option value={0}>Chưa rõ mức độ</option>
              <option value={1}>⭐ 1 · Rất thấp</option>
              <option value={2}>⭐⭐ 2 · Thấp</option>
              <option value={3}>⭐⭐⭐ 3 · Có thể trao đổi</option>
              <option value={4}>⭐⭐⭐⭐ 4 · Quan tâm</option>
              <option value={5}>⭐⭐⭐⭐⭐ 5 · Sẵn sàng</option>
            </select>
          </label>
          <label className="talent-rel-field">
            <span className="talent-rel-label">📞 Kênh ưu tiên</span>
            <select className="talent-rel-select" value={row.preferred_channel} onChange={e => update.mutate({ preferred_channel: e.target.value })}>
              <option value="">Chưa xác định</option>
              <option value="phone">📞 Điện thoại</option>
              <option value="email">✉️ Email</option>
              <option value="message">💬 Tin nhắn</option>
            </select>
          </label>
        </div>
      </div>

      {/* 2. Kế hoạch hành động */}
      <div className="talent-rel-section">
        <div className="talent-rel-grid-2">
          <label className="talent-rel-field">
            <span className="talent-rel-label">🕒 Lần liên hệ gần nhất</span>
            <input className="talent-rel-input" type="datetime-local" value={row.last_contact_at?.slice(0, 16) || ''} onChange={e => update.mutate({ last_contact_at: e.target.value || null })} />
          </label>
          <label className="talent-rel-field">
            <span className="talent-rel-label">⏳ Hạn hành động tiếp theo</span>
            <input className="talent-rel-input" type="datetime-local" value={row.next_action_at?.slice(0, 16) || ''} onChange={e => update.mutate({ next_action_at: e.target.value || null })} />
          </label>
        </div>

        <label className="talent-rel-field" style={{ marginTop: '12px' }}>
          <span className="talent-rel-label">📌 Hành động tiếp theo</span>
          <input className="talent-rel-input" defaultValue={row.next_action} onBlur={e => update.mutate({ next_action: e.target.value })} placeholder="VD: Gửi thư mời phỏng vấn kỹ thuật..." />
        </label>
      </div>

      {/* 3. Nguyện vọng ứng viên */}
      <div className="talent-rel-section">
        <div className="talent-rel-grid-2">
          <label className="talent-rel-field">
            <span className="talent-rel-label">💼 Vị trí mong muốn</span>
            <input className="talent-rel-input" defaultValue={String(preferences.preferred_roles ?? '')} onBlur={e => patchPreference('preferred_roles', e.target.value)} placeholder="VD: Senior Data Engineer" />
          </label>
          <label className="talent-rel-field">
            <span className="talent-rel-label">📍 Khu vực làm việc</span>
            <input className="talent-rel-input" defaultValue={String(preferences.preferred_location ?? '')} onBlur={e => patchPreference('preferred_location', e.target.value)} placeholder="VD: Hà Nội, Remote" />
          </label>
        </div>
        <div className="talent-rel-grid-2" style={{ marginTop: '12px' }}>
          <label className="talent-rel-field">
            <span className="talent-rel-label">⏱️ Thời gian nhận việc</span>
            <input className="talent-rel-input" defaultValue={String(preferences.availability ?? '')} onBlur={e => patchPreference('availability', e.target.value)} placeholder="VD: Trong 1 tháng" />
          </label>
          <label className="talent-rel-field">
            <span className="talent-rel-label">🏢 Hình thức làm việc</span>
            <input className="talent-rel-input" defaultValue={String(preferences.work_mode ?? '')} onBlur={e => patchPreference('work_mode', e.target.value)} placeholder="VD: Hybrid / Fulltime" />
          </label>
        </div>
      </div>

      {/* 4. Ghi chú dài hạn & Đánh dấu */}
      <div className="talent-rel-section" style={{ borderBottom: 'none', paddingBottom: 0 }}>
        <label className="talent-rel-field">
          <span className="talent-rel-label">📝 Ghi chú quan hệ dài hạn</span>
          <textarea className="talent-rel-textarea" rows={2} defaultValue={row.notes} onBlur={e => update.mutate({ notes: e.target.value })} placeholder="Thông tin bổ sung về ứng viên..." />
        </label>

        <div style={{ marginTop: '12px', display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: '10px' }}>
          <label className="chip" style={{ cursor: 'pointer' }}>
            <input type="checkbox" checked={row.do_not_contact} onChange={e => update.mutate({ do_not_contact: e.target.checked })} />
            <span>🚫 Không tiếp tục liên hệ ứng viên</span>
          </label>
        </div>
      </div>

      {update.error && <p className="err-box" style={{ marginTop: '10px' }}>Không lưu được quan hệ ứng viên.</p>}
    </section>
  )
}

/** 3. QUẢN LÝ QUAN HỆ KHÁCH HÀNG (GROWTH RADAR - CUSTOMER RELATIONSHIP) */
function CustomerRelationship({ personId }: { personId: number }) {
  const qc = useQueryClient()
  const [newGroup, setNewGroup] = useState('')
  const groups = useQuery({ queryKey: ['customer-groups'], queryFn: () => api.pools('rb') })
  const owners = useQuery({ queryKey: ['rb-owners'], queryFn: api.rbOwners })
  const profile = useQuery({ queryKey: ['rb-profile', personId], queryFn: () => api.rbProfile(personId) })
  const update = useMutation({
    mutationFn: (patch: Record<string, unknown>) => api.rbProfileUpdate(personId, patch),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['rb-profile', personId] }),
  })
  const addGroup = useMutation({
    mutationFn: async () => {
      const group = await api.createPool(newGroup.trim(), '', 'rb')
      await api.setPoolMember(group.id, personId)
      return group
    },
    onSuccess: () => { setNewGroup(''); qc.invalidateQueries({ queryKey: ['customer-groups'] }) },
  })
  const membership = useMutation({
    mutationFn: ({ id, remove }: { id: number; remove: boolean }) => api.setPoolMember(id, personId, remove),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['person', personId] }),
  })

  if (!profile.data) return <section className="person-section-card"><p className="muted">Đang tải quan hệ khách hàng…</p></section>
  const row = profile.data

  return (
    <section className="person-section-card talent-rel-card">
      <div className="section-title-row">
        <h3 className="section-title">👔 Quan hệ Khách hàng (Growth Radar)</h3>
        {row.active_owners.length > 1 && <span className="badge err">⚠ Đa RM xử lý</span>}
      </div>
      <p className="hint">Trạng thái tiếp cận và phân công RM chăm sóc khách hàng cá nhân.</p>

      <div className="talent-rel-section">
        <div className="talent-rel-grid-2">
          <label className="talent-rel-field">
            <span className="talent-rel-label">🎯 Trạng thái khách hàng</span>
            <select className="talent-rel-select" value={row.lead_status} onChange={event => update.mutate({ lead_status: event.target.value })}>
              <option value="cold">Chưa tiếp cận</option>
              <option value="warm">Đã tiếp cận</option>
              <option value="interested">Có quan tâm</option>
              <option value="qualified">Đủ điều kiện</option>
              <option value="converted">Đã dùng sản phẩm</option>
              <option value="dormant">Nguội</option>
            </select>
          </label>
          <label className="talent-rel-field">
            <span className="talent-rel-label">💎 Phân khúc</span>
            <select className="talent-rel-select" value={row.segment} onChange={event => update.mutate({ segment: event.target.value })}>
              <option value="">Chưa xác định</option>
              <option value="mass">Phổ thông</option>
              <option value="affluent">Khá giả</option>
              <option value="priority">Ưu tiên (VIP)</option>
            </select>
          </label>
        </div>

        <div className="talent-rel-grid-2" style={{ marginTop: '12px' }}>
          <label className="talent-rel-field">
            <span className="talent-rel-label">👤 RM phụ trách</span>
            <select
              className="talent-rel-select"
              value={(owners.data?.results.find(owner => owner.name === row.sales_owner_name)?.id) ?? ''}
              onChange={event => update.mutate({ sales_owner_id: event.target.value ? Number(event.target.value) : null })}
            >
              <option value="">Chưa phân công</option>
              {(owners.data?.results ?? []).map(owner => <option key={owner.id} value={owner.id}>{owner.name}</option>)}
            </select>
          </label>
          <label className="talent-rel-field">
            <span className="talent-rel-label">📞 Kênh ưu tiên</span>
            <select className="talent-rel-select" value={row.preferred_channel} onChange={event => update.mutate({ preferred_channel: event.target.value })}>
              <option value="">Chưa xác định</option>
              <option value="phone">📞 Điện thoại</option>
              <option value="email">✉️ Email</option>
              <option value="message">💬 Tin nhắn</option>
            </select>
          </label>
        </div>
      </div>

      <div className="talent-rel-section">
        <label className="talent-rel-field">
          <span className="talent-rel-label">💼 Nghề nghiệp / Chức vụ</span>
          <input className="talent-rel-input" defaultValue={row.occupation} onBlur={event => update.mutate({ occupation: event.target.value })} placeholder="VD: Trưởng phòng KD" />
        </label>
        <label className="talent-rel-field" style={{ marginTop: '12px' }}>
          <span className="talent-rel-label">🏢 Doanh nghiệp / Nơi công tác</span>
          <input className="talent-rel-input" defaultValue={row.employer} onBlur={event => update.mutate({ employer: event.target.value })} placeholder="VD: Tập đoàn ABC" />
        </label>
      </div>

      <div className="talent-rel-section">
        <label className="talent-rel-field">
          <span className="talent-rel-label">📌 Hành động tiếp theo</span>
          <input className="talent-rel-input" defaultValue={row.next_action} onBlur={event => update.mutate({ next_action: event.target.value })} placeholder="VD: Hẹn gặp tư vấn gói vay..." />
        </label>
        <label className="talent-rel-field" style={{ marginTop: '12px' }}>
          <span className="talent-rel-label">⏳ Thời hạn hành động</span>
          <input className="talent-rel-input" type="datetime-local" value={row.next_action_at?.slice(0, 16) || ''} onChange={event => update.mutate({ next_action_at: event.target.value || null })} />
        </label>
      </div>

      <div className="talent-rel-section">
        <label className="talent-rel-field">
          <span className="talent-rel-label">💬 Tóm tắt tương tác</span>
          <textarea className="talent-rel-textarea" rows={2} defaultValue={row.interaction_summary} onBlur={event => update.mutate({ interaction_summary: event.target.value })} placeholder="Nội dung đã trao đổi gần nhất..." />
        </label>
      </div>

      {/* Nhóm khách hàng */}
      <div style={{ marginTop: '12px' }}>
        <span className="talent-rel-label" style={{ display: 'block', marginBottom: '8px' }}>📁 Nhóm khách hàng (Customer Groups)</span>
        <div className="chips" style={{ marginBottom: '10px' }}>
          {(groups.data?.results ?? []).map(group => (
            <button
              type="button"
              className="chip"
              key={group.id}
              onClick={() => membership.mutate({ id: group.id, remove: false })}
            >
              + {group.name}
            </button>
          ))}
        </div>
        <div style={{ display: 'flex', gap: '8px' }}>
          <input
            className="talent-rel-input"
            value={newGroup}
            onChange={event => setNewGroup(event.target.value)}
            placeholder="Tạo nhóm mới..."
          />
          <button
            type="button"
            className="btn btn-secondary btn-sm"
            disabled={!newGroup.trim() || addGroup.isPending}
            onClick={() => addGroup.mutate()}
          >
            Tạo
          </button>
        </div>
      </div>
    </section>
  )
}

/** 4. CƠ HỘI TÀI CHÍNH & BÁN CHÉO (GROWTH RADAR OPPORTUNITIES) */
function CustomerOpportunitiesSection({ personId }: { personId: number }) {
  const queryClient = useQueryClient()
  const [product, setProduct] = useState('credit_card')
  const [need, setNeed] = useState('')
  const profile = useQuery({ queryKey: ['rb-profile', personId], queryFn: () => api.rbProfile(personId) })
  const opportunities = useQuery({ queryKey: ['rb-opportunities', 'person', personId], queryFn: () => api.rbOpportunities({ person: personId }) })
  const createOpportunity = useMutation({
    mutationFn: () => api.rbOpportunityCreate({ person_id: personId, product, need }),
    onSuccess: () => { setNeed(''); queryClient.invalidateQueries({ queryKey: ['rb-opportunities'] }) },
  })

  const row = profile.data

  return (
    <section className="person-section-card">
      <div className="section-title-row">
        <h3 className="section-title">🎯 Cơ hội tài chính &amp; Bán chéo (Growth Radar)</h3>
        <Link className="btn btn-secondary btn-sm" to="/rb">Mở bàn làm việc Growth Radar →</Link>
      </div>

      {(opportunities.data?.results ?? []).length > 0 ? (
        <div className="hunt-people-modern">
          {(opportunities.data?.results ?? []).map(opp => (
            <div className="hunt-person-card" key={opp.id}>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', width: '100%' }}>
                <strong>{opp.product_label}</strong>
                <span className={`badge status-${opp.status}`}>{opp.status_label}</span>
              </div>
              <div className="muted small" style={{ marginTop: '4px' }}>
                Phụ trách: <strong>{opp.assigned_to_name || 'Chưa phân công'}</strong> · Follow-up: {dateTime(opp.next_action_at)}
              </div>
              {opp.need && <p style={{ margin: '6px 0 0', fontSize: '13px' }}>{opp.need}</p>}
            </div>
          ))}
        </div>
      ) : (
        <p className="muted" style={{ margin: '10px 0 16px' }}>Chưa có cơ hội tài chính nào đang mở cho khách hàng này.</p>
      )}

      {/* Form tạo nhanh cơ hội mới */}
      <div className="search-row" style={{ display: 'flex', gap: '10px', marginTop: '16px', flexWrap: 'wrap' }}>
        <select
          className="select-dropdown"
          style={{ minWidth: '180px' }}
          value={product}
          onChange={e => setProduct(e.target.value)}
        >
          <option value="credit_card">Thẻ tín dụng</option>
          <option value="mortgage">Vay mua nhà</option>
          <option value="auto_loan">Vay mua xe</option>
          <option value="consumer_loan">Vay tiêu dùng</option>
          <option value="savings">Tiết kiệm</option>
          <option value="investment">Đầu tư</option>
          <option value="insurance">Bảo hiểm</option>
          <option value="fx">Ngoại tệ / Chuyển tiền</option>
          <option value="payroll">Tài khoản lương</option>
        </select>
        <input
          className="input-text filter-input"
          style={{ flex: 1, minWidth: '220px' }}
          value={need}
          onChange={e => setNeed(e.target.value)}
          placeholder="Nhu cầu cụ thể hoặc ghi chú..."
        />
        <button
          type="button"
          className="btn btn-primary btn-sm"
          disabled={createOpportunity.isPending}
          onClick={() => createOpportunity.mutate()}
        >
          {createOpportunity.isPending ? 'Đang tạo…' : '⚡ Tạo cơ hội'}
        </button>
      </div>

      {/* Tín hiệu sản phẩm AI phát hiện */}
      {row && row.interests.length > 0 && (
        <div style={{ marginTop: '16px', borderTop: '1px solid var(--border)', paddingTop: '14px' }}>
          <h4 style={{ margin: '0 0 10px', fontSize: '13.5px', color: 'var(--text)' }}>💡 Tín hiệu nhu cầu sản phẩm AI phát hiện</h4>
          <div className="hunt-people-modern">
            {row.interests.map(interest => (
              <div className="hunt-person-card" key={interest.id}>
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', width: '100%' }}>
                  <strong>{interest.product_label}</strong>
                  <span className="score-pill">{Math.round(interest.confidence * 100)}%</span>
                </div>
                <div className="muted small">Nguồn: {interest.source || 'không rõ'} · {dateTime(interest.observed_at)}</div>
              </div>
            ))}
          </div>
        </div>
      )}
    </section>
  )
}

/** 5. ĐỢT TUYỂN DỤNG ĐANG XỬ LÝ (TALENT WORKLISTS) */
function ActiveWorklists({ person }: { person: PersonDetail }) {
  const queryClient = useQueryClient()
  const [huntId, setHuntId] = useState('')
  const hunts = useQuery({ queryKey: ['hunts', 'open-for-add'], queryFn: () => api.hunts({ open: true }) })
  const add = useMutation({
    mutationFn: () => api.huntUpdate(Number(huntId), { person_ids_add: [person.id] }),
    onSuccess: () => {
      setHuntId('')
      queryClient.invalidateQueries({ queryKey: ['person', person.id] })
      queryClient.invalidateQueries({ queryKey: ['hunts'] })
    },
  })
  const owners = new Set(person.active_worklists.map(row => row.assigned_to_name).filter(Boolean))

  return (
    <section className="person-section-card">
      <div className="section-title-row">
        <h3 className="section-title">📋 Đợt tuyển đang xử lý ({person.active_worklists.length})</h3>
        {owners.size > 1 && <span className="badge err">⚠ Có nhiều Recruiter cùng xử lý</span>}
      </div>

      {person.active_worklists.length ? (
        <div className="hunt-people-modern">
          {person.active_worklists.map(row => (
            <div className="hunt-person-card" key={row.hunt_id}>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', width: '100%', gap: '10px' }}>
                <Link to="/hunts" className="hunt-link-title"><strong>{row.title}</strong></Link>
                <span className={`badge cstate-${row.state}`}>{row.state_label}</span>
              </div>
              <div className="talent-meta" style={{ marginTop: '6px' }}>
                <span>👤 Phụ trách: <strong>{row.assigned_to_name || 'Chưa phân công'}</strong></span>
                <span>⭐ Ưu tiên: {row.priority}</span>
                {row.next_action_at && <span>⏳ Follow-up: {dateTime(row.next_action_at)}</span>}
              </div>
              {row.note && <p className="muted small" style={{ margin: '6px 0 0' }}>{row.note}</p>}
            </div>
          ))}
        </div>
      ) : (
        <p className="muted" style={{ margin: '10px 0 16px' }}>Ứng viên chưa nằm trong đợt tuyển dụng đang mở nào.</p>
      )}

      <div className="search-row" style={{ display: 'flex', gap: '10px', marginTop: '14px', flexWrap: 'wrap' }}>
        <select
          className="select-dropdown"
          style={{ flex: 1, minWidth: '220px' }}
          value={huntId}
          onChange={event => setHuntId(event.target.value)}
        >
          <option value="">Chọn đợt tuyển đang mở để thêm ứng viên…</option>
          {(hunts.data?.results ?? []).filter(hunt => !person.active_worklists.some(row => row.hunt_id === hunt.id)).map(hunt => (
            <option key={hunt.id} value={hunt.id}>{hunt.title || hunt.hiring_need_title}</option>
          ))}
        </select>
        <button
          type="button"
          className="btn btn-primary btn-sm"
          disabled={!huntId || add.isPending}
          onClick={() => add.mutate()}
        >
          {add.isPending ? 'Đang thêm…' : '+ Thêm vào đợt'}
        </button>
      </div>
    </section>
  )
}

/** 6. HỎI & ĐÁP AI VỀ NGƯỜI NÀY — có phạm vi: chỉ dựa trên dữ kiện đã có trong
 * hồ sơ (đúng nguyên tắc "AI hiểu, CODE quyết" — xem talent/person_qa.py),
 * không phải chatbot tự do đọc hồ sơ thô. */
const GOI_Y_HOI_NGUOI = [
  'Người này có phù hợp với vị trí đang tuyển không?',
  'Nên tiếp cận người này thế nào?',
  'Hồ sơ còn thiếu thông tin gì?',
]

interface AskMessage {
  id: string
  sender: 'user' | 'ai'
  text: string
  isPending?: boolean
}

function PersonAskSection({ personId }: { personId: number }) {
  const { appName, radarAvatarUrl, radarAvatarEmoji } = useCustomTheme()
  const [messages, setMessages] = useState<AskMessage[]>([])
  const [inputText, setInputText] = useState('')

  const ask = useMutation({
    mutationFn: ({ question, history }: { question: string; history: PersonAskTurn[] }) =>
      api.personAsk(personId, question, history),
  })

  const handleSend = (override?: string) => {
    const question = (override ?? inputText).trim()
    if (!question || ask.isPending) return

    // Lịch sử hỏi tiếp: ghép các cặp hỏi/đáp ĐÃ XONG (bỏ qua lượt đang chờ),
    // để AI hỏi tiếp có ngữ cảnh đúng người này thay vì hỏi độc lập từng câu.
    const history: PersonAskTurn[] = []
    for (let i = 0; i + 1 < messages.length; i += 2) {
      const q = messages[i]
      const a = messages[i + 1]
      if (q?.sender === 'user' && a?.sender === 'ai' && !a.isPending) {
        history.push({ question: q.text, answer: a.text })
      }
    }

    const userMsgId = `u-${Date.now()}`
    const aiMsgId = `a-${Date.now() + 1}`
    setMessages((prev) => [
      ...prev,
      { id: userMsgId, sender: 'user', text: question },
      { id: aiMsgId, sender: 'ai', text: '', isPending: true },
    ])
    setInputText('')

    ask.mutate(
      { question, history },
      {
        onSuccess: (data) => {
          setMessages((prev) =>
            prev.map((m) =>
              m.id === aiMsgId
                ? { ...m, isPending: false, text: data.error ? `⚠️ ${data.error}` : data.answer || 'Không có câu trả lời.' }
                : m,
            ),
          )
        },
        onError: (err) => {
          const detail = err instanceof ApiError ? err.message : 'Không kết nối được máy chủ AI.'
          setMessages((prev) =>
            prev.map((m) => (m.id === aiMsgId ? { ...m, isPending: false, text: `⚠️ ${detail}` } : m)),
          )
        },
      },
    )
  }

  return (
    <section className="person-section-card">
      <h3 className="section-title">💬 Hỏi &amp; đáp AI về người này</h3>
      <p className="hint" style={{ marginTop: 0, marginBottom: '14px' }}>
        Câu trả lời chỉ dựa trên dữ kiện đã có trong hồ sơ — không suy diễn thêm thu nhập, khả năng vay hay xác suất chốt.
      </p>

      {messages.length > 0 && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '16px', marginBottom: '14px' }}>
          {messages.map((msg) => (
            <div key={msg.id} className={`chat-message-row ${msg.sender}`}>
              <div className={`chat-avatar ${msg.sender === 'ai' ? 'radar-bot-avatar' : ''}`}>
                {msg.sender === 'user' ? (
                  '👤'
                ) : radarAvatarUrl ? (
                  <img src={radarAvatarUrl} alt={appName} className="bot-avatar-img" />
                ) : (
                  <span>{radarAvatarEmoji || '⚡'}</span>
                )}
              </div>
              <div className="chat-bubble-wrapper">
                <div className={`chat-bubble ${msg.sender}`}>
                  {msg.isPending ? (
                    <div className="copilot-typing-indicator">
                      <span className="dot" />
                      <span className="dot" />
                      <span className="dot" />
                    </div>
                  ) : (
                    <FormattedMarkdown content={msg.text} />
                  )}
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      {messages.length === 0 && (
        <div className="chips" style={{ marginBottom: '14px' }}>
          {GOI_Y_HOI_NGUOI.map((text) => (
            <button
              key={text}
              type="button"
              className="chip"
              style={{ cursor: 'pointer', background: 'none' }}
              onClick={() => handleSend(text)}
            >
              {text}
            </button>
          ))}
        </div>
      )}

      <div style={{ display: 'flex', gap: '8px' }}>
        <input
          className="input-text"
          style={{ flex: 1 }}
          placeholder="VD: Người này có phù hợp vị trí Data Analyst không?"
          value={inputText}
          onChange={(e) => setInputText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') {
              e.preventDefault()
              handleSend()
            }
          }}
          disabled={ask.isPending}
        />
        <button
          type="button"
          className="btn btn-primary btn-sm"
          disabled={!inputText.trim() || ask.isPending}
          onClick={() => handleSend()}
        >
          {ask.isPending ? <span className="spinner-small" /> : 'Hỏi'}
        </button>
      </div>
    </section>
  )
}

/** 7. TÍN HIỆU & GỢI Ý KHAI THÁC AI */
function CandidateInsights({ person }: { person: PersonDetail }) {
  const signals = person.signals.sort((a, b) => b.confidence - a.confidence)
  const suggestions: string[] = []
  if (!person.primary_email && !person.primary_phone) suggestions.push('⚠️ Cần bổ sung kênh liên hệ tin cậy')
  if (!person.talent?.last_source_at) suggestions.push('⚠️ Chưa xác định độ mới của hồ sơ')
  if (person.active_worklists.length === 0) suggestions.push('💡 Chưa có đợt tuyển dụng đang mở')

  return (
    <section className="person-section-card">
      <h3 className="section-title">⚡ Tín hiệu &amp; Gợi ý AI</h3>
      {suggestions.length > 0 && (
        <div className="chips" style={{ marginBottom: '14px' }}>
          {suggestions.map(text => <span className="chip" key={text} style={{ background: 'rgba(239, 68, 68, 0.08)', color: '#dc2626' }}>{text}</span>)}
        </div>
      )}
      {signals.length > 0 ? (
        <div className="hunt-people-modern">
          {signals.slice(0, 5).map(signal => (
            <div className="hunt-person-card" key={signal.id}>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', width: '100%' }}>
                <strong>{signal.signal_type}</strong>
                <span className="score-pill" title="Độ tin cậy AI">{Math.round(signal.confidence * 100)}%</span>
              </div>
              <div className="muted small">Lĩnh vực: {signal.domain} · Ghi nhận {dateTime(signal.observed_at)} · Trạng thái: {signal.status}</div>
            </div>
          ))}
        </div>
      ) : (
        <p className="muted">Chưa có tín hiệu tự động.</p>
      )}
    </section>
  )
}



/** 9. LỊCH SỬ NỘP HỒ SƠ & DÒNG THỜI GIAN HOẠT ĐỘNG */
function HistoryAndTimelineSection({ person }: { person: PersonDetail }) {
  return (
    <div className="history-timeline-stack" style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
      {/* 1. Lịch sử nộp hồ sơ qua các nguồn */}
      <section className="person-section-card">
        <div className="section-title-row">
          <h3 className="section-title">📍 Lịch sử nộp hồ sơ &amp; Nguồn ứng tuyển ({person.sources.length})</h3>
          <span className="badge" style={{ background: 'var(--accent-soft, rgba(99,102,241,0.12))', color: 'var(--accent, #6366f1)', fontWeight: 600 }}>
            🔗 Định danh hợp nhất
          </span>
        </div>
        <p className="hint">Mọi nguồn ứng tuyển và dữ liệu khách hàng được định danh về cùng 1 người nhờ đối soát Email/SĐT chuẩn hóa.</p>
        <div className="table-responsive-wrapper" style={{ marginTop: '12px', overflowX: 'auto' }}>
          <table className="sources-table" style={{ width: '100%' }}>
            <thead>
              <tr>
                <th style={{ width: '110px' }}>Kênh nguồn</th>
                <th>Vị trí / Thông tin ghi nhận</th>
                <th style={{ width: '120px' }}>Ngày ghi nhận</th>
                <th style={{ width: '220px' }}>Tài khoản</th>
              </tr>
            </thead>
            <tbody>
              {person.sources.map((source) => (
                <tr key={source.id}>
                  <td><span className="source-tag">{source.source}</span></td>
                  <td><strong>{source.position || '—'}</strong></td>
                  <td>{source.applied_ts?.slice(0, 10) || '—'}</td>
                  <td className="muted small">{source.account || '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {/* 2. Dòng thời gian hoạt động & Tương tác */}
      <section className="person-section-card">
        <div className="section-title-row">
          <h3 className="section-title">⏳ Dòng thời gian hoạt động &amp; Tương tác ({person.timeline.length})</h3>
        </div>
        {person.timeline.length === 0 ? (
          <div className="empty-box">Chưa có ghi nhận tương tác nào.</div>
        ) : (
          <ol className="timeline-modern">
            {person.timeline.map((event, index) => (
              <li key={index} className="timeline-item-modern">
                <div className="timeline-dot" />
                <div className="timeline-content">
                  <div className="timeline-time">{dateTime(event.at)}</div>
                  <div className="timeline-action">
                    <strong>{event.action}</strong>
                    {event.actor && <span className="timeline-actor"> · bởi {event.actor}</span>}
                  </div>
                </div>
              </li>
            ))}
          </ol>
        )}
      </section>
    </div>
  )
}

/** 10. QUẢN LÝ THÔNG TIN & NHÓM ỨNG VIÊN */
function ProfileManagement({ person }: { person: PersonDetail }) {
  const queryClient = useQueryClient()
  const facets = useQuery({ queryKey: ['talent-facets'], queryFn: api.talentFacets })
  const t = person.talent
  const [editing, setEditing] = useState(false)
  const [newPool, setNewPool] = useState('')
  const [form, setForm] = useState(() => ({
    current_title: t?.current_title ?? '',
    current_company: t?.current_company ?? '',
    years_experience: t?.years_experience == null ? '' : String(t.years_experience),
    seniority: t?.seniority ?? '',
    education: t?.education ?? '',
    expected_salary: t?.expected_salary ?? '',
    location: t?.location ?? '',
    summary: t?.summary ?? '',
    skills: (t?.skills ?? []).join(', '),
    industries: (t?.industries ?? []).join(', '),
    owner_id: t?.owner_id == null ? '' : String(t.owner_id),
  }))

  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: ['person', person.id] })
    queryClient.invalidateQueries({ queryKey: ['talent-facets'] })
  }

  const update = useMutation({
    mutationFn: () => api.personUpdate(person.id, {
      ...form,
      years_experience: form.years_experience === '' ? null : Number(form.years_experience),
      owner_id: form.owner_id === '' ? null : Number(form.owner_id),
      skills: form.skills.split(',').map((x) => x.trim()).filter(Boolean),
      industries: form.industries.split(',').map((x) => x.trim()).filter(Boolean),
    }),
    onSuccess: () => { refresh(); setEditing(false) },
  })

  const poolMutation = useMutation({
    mutationFn: ({ pool, remove }: { pool: number; remove: boolean }) => api.setPoolMember(pool, person.id, remove),
    onSuccess: refresh,
  })

  const createPool = useMutation({
    mutationFn: () => api.createPool(newPool.trim()),
    onSuccess: (pool) => { setNewPool(''); refresh(); poolMutation.mutate({ pool: pool.id, remove: false }) },
  })

  const setField = (key: keyof typeof form, value: string) => setForm((old) => ({ ...old, [key]: value }))
  const fields: Array<[keyof typeof form, string, string?]> = [
    ['current_title', 'Chức danh'], ['current_company', 'Công ty'],
    ['years_experience', 'Số năm kinh nghiệm', 'number'], ['seniority', 'Cấp bậc'],
    ['education', 'Học vấn'], ['expected_salary', 'Lương mong muốn'], ['location', 'Nơi ở'],
    ['skills', 'Kỹ năng (phân cách bằng dấu phẩy)'], ['industries', 'Ngành nghề (phân cách bằng dấu phẩy)'],
  ]
  const activePools = new Set(person.pools.map((pool) => pool.id))

  return (
    <section className="person-section-card">
      <div className="section-title-row">
        <h3 className="section-title">📁 Nhóm Ứng viên &amp; Chỉnh sửa</h3>
        <button
          type="button"
          className="btn btn-secondary btn-sm"
          onClick={() => setEditing((v) => !v)}
        >
          {editing ? '✕ Đóng' : '✏️ Chỉnh sửa'}
        </button>
      </div>

      {editing && (
        <form onSubmit={(event) => { event.preventDefault(); update.mutate() }} style={{ marginBottom: '20px' }}>
          <div className="filter-criteria-grid">
            {fields.map(([key, label, type]) => (
              <label key={key} className="filter-col-group">
                <span className="filter-label">{label}</span>
                <input
                  className="input-text filter-input"
                  type={type ?? 'text'}
                  min={type === 'number' ? 0 : undefined}
                  value={form[key]}
                  onChange={(event) => setField(key, event.target.value)}
                />
              </label>
            ))}
            <label className="filter-col-group">
              <span className="filter-label">Chuyên viên phụ trách</span>
              <select className="select-dropdown" value={form.owner_id} onChange={(event) => setField('owner_id', event.target.value)}>
                <option value="">Chưa phân công</option>
                {(facets.data?.owners ?? []).map((owner) => <option key={owner.id} value={owner.id}>{owner.name}</option>)}
              </select>
            </label>
          </div>
          <label className="filter-col-group" style={{ marginTop: '12px' }}>
            <span className="filter-label">Tóm tắt tiểu sử</span>
            <textarea className="input-text" rows={3} value={form.summary} onChange={(event) => setField('summary', event.target.value)} />
          </label>
          {update.error && <p className="error-text">{update.error instanceof ApiError ? update.error.message : 'Không lưu được hồ sơ.'}</p>}
          <div style={{ marginTop: '12px' }}>
            <button className="btn btn-primary btn-sm" disabled={update.isPending}>
              {update.isPending ? 'Đang lưu…' : '✓ Lưu thay đổi'}
            </button>
          </div>
        </form>
      )}

      <div className="chips" style={{ marginBottom: '14px' }}>
        {(facets.data?.pools ?? []).map((pool) => (
          <button
            key={pool.id}
            type="button"
            className={`chip ${activePools.has(pool.id) ? 'active' : ''}`}
            disabled={poolMutation.isPending}
            onClick={() => poolMutation.mutate({ pool: pool.id, remove: activePools.has(pool.id) })}
          >
            {activePools.has(pool.id) ? '✓ ' : '+ '}{pool.name}
          </button>
        ))}
      </div>

      <div className="search-row" style={{ display: 'flex', gap: '8px' }}>
        <input
          className="input-text filter-input"
          style={{ flex: 1 }}
          value={newPool}
          placeholder="Tên nhóm mới…"
          onChange={(event) => setNewPool(event.target.value)}
        />
        <button
          type="button"
          className="btn btn-secondary btn-sm"
          disabled={!newPool.trim() || createPool.isPending}
          onClick={() => createPool.mutate()}
        >
          + Tạo
        </button>
      </div>
    </section>
  )
}

const INDEX_HEALTH_STYLE: Record<IndexHealth['status'], { icon: string; label: string; cls: string }> = {
  ok: { icon: '✅', label: 'Đủ chỉ mục tìm kiếm', cls: 'badge muted' },
  stale: { icon: '🕓', label: 'Đang cập nhật chỉ mục', cls: 'badge warn' },
  missing: { icon: '⚠️', label: 'Thiếu chỉ mục tìm kiếm', cls: 'badge err' },
  no_documents: { icon: '', label: '', cls: '' },
}

/** Chỉ báo "Tìm trong kho" có đủ dữ liệu về người này chưa — chỉ Admin thấy
 * (xem `talent/views.py::_can_view_index_health`). `no_documents` (chưa có CV
 * nào để lập chỉ mục) không phải lỗi dữ liệu nên không hiện gì, tránh gây
 * hiểu nhầm "thiếu chỉ mục" cho hồ sơ vốn dĩ trống. */
function IndexHealthBadge({ health }: { health: IndexHealth }) {
  if (health.status === 'no_documents') return null
  const { icon, label, cls } = INDEX_HEALTH_STYLE[health.status]
  const tooltip = [
    `Đoạn CV đã embed: ${health.chunks_current}/${health.chunks_total}`,
    health.extraction_pending ? 'Đang chờ trích xuất fact AI' : '',
    health.indexed_at ? `Lập chỉ mục lần cuối: ${new Date(health.indexed_at).toLocaleString('vi-VN')}` : '',
  ].filter(Boolean).join(' · ')
  return (
    <span className={cls} title={tooltip}>
      {icon} {label}
    </span>
  )
}

/** 11. MÀN HÌNH CHÍNH PERSON 360 HỢP NHẤT — GIAO DIỆN ONE-PAGE HIỆN ĐẠI */
export default function Person360() {
  const { id } = useParams<{ id: string }>()
  const [searchParams] = useSearchParams()
  const fromParam = searchParams.get('from')
  const personId = Number(id)
  const [activeNav, setActiveNav] = useState<string>('tong-quan')
  const [avatarError, setAvatarError] = useState(false)
  const [unlockedContacts, setUnlockedContacts] = useState<{ email: string; phone: string } | null>(null)
  const isUnlocked = Boolean(unlockedContacts)

  // Đưa ứng viên vào đợt tuyển / nhiệm vụ săn
  const [huntModalOpen, setHuntModalOpen] = useState(false)
  const [isAddingHunt, setIsAddingHunt] = useState(false)
  const [addedHuntName, setAddedHuntName] = useState<string | null>(null)

  const { maskSensitiveData } = useCustomTheme()
  const queryClient = useQueryClient()
  const session = useQuery({ queryKey: ['me'], queryFn: api.me, retry: false })
  const roles = new Set(session.data?.authenticated ? session.data.roles : [])
  const canManageTalent = roles.has('recruiter') || roles.has('hiring_manager') || roles.has('manager') || roles.has('admin')
  const canManageRB = roles.has('rb_sales') || roles.has('manager') || roles.has('admin')
  const canViewCV = roles.has('recruiter') || roles.has('hiring_manager') || roles.has('manager') || roles.has('admin')
  const isRmOnly = roles.has('rb_sales') && !canManageTalent
  const isAdmin = roles.has('admin')

  // Đợt tuyển đang mở để đưa vào
  const huntsQuery = useQuery({
    queryKey: ['hunts', 'open-for-person'],
    queryFn: () => api.hunts({ open: true, limit: 100 }).catch(() => ({ count: 0, limit: 100, offset: 0, results: [] })),
    staleTime: 60_000,
  })
  const openHunts = huntsQuery.data?.results ?? []

  // Ngữ cảnh mở hồ sơ, gắn qua `?from=`. Phân hệ Tìm kiếm (/search) dùng dạng
  // `search-<tab>-<góc nhìn>`; các giá trị cũ (`talent-ai`, `talent-filter`) vẫn
  // được nhận và trỏ về đúng tab tương ứng của /search.
  const searchContext = fromParam === 'talent-ai'
    ? { tab: 'ai', perspective: 'recruiter' }
    : fromParam === 'talent-filter'
      ? { tab: 'filter', perspective: 'recruiter' }
      : /^search-(ai|filter)-(recruiter|prospect)$/.test(fromParam ?? '')
        ? { tab: fromParam!.split('-')[1], perspective: fromParam!.split('-')[2] }
        : null

  const returnPath = searchContext
    ? `/search?tab=${searchContext.tab}&perspective=${searchContext.perspective}`
    : isRmOnly || fromParam === 'rb'
      ? '/rb'
      : '/hunts'
  const returnLabel = searchContext
    ? (searchContext.tab === 'filter' ? 'bộ lọc đa chiều' : 'tìm kiếm AI')
    : isRmOnly || fromParam === 'rb'
      ? 'Growth Radar'
      : 'Talent Radar'

  // Tab quan hệ mặc định theo ngữ cảnh: góc nhìn khách hàng và luồng Growth Radar
  // mở thẳng bảng quan hệ RB, còn lại mở bảng quan hệ ứng viên.
  const initialRelTab: RelationshipTab =
    searchContext?.perspective === 'prospect' || (!searchContext && (isRmOnly || fromParam === 'rb'))
      ? 'rb'
      : 'talent'
  const [relTab, setRelTab] = useState<RelationshipTab>(initialRelTab)
  const hasBoth = canManageTalent && canManageRB
  const shouldMask = maskSensitiveData || !isUnlocked

  const handleAssignHunt = async (opts: { huntId?: number; newTitle?: string }) => {
    setIsAddingHunt(true)
    try {
      if (opts.huntId) {
        const hunt = openHunts.find((h) => h.id === opts.huntId)
        const huntTitle = hunt?.title || 'đợt tuyển'
        await api.huntUpdate(opts.huntId, { person_ids_add: [personId] })
        setAddedHuntName(huntTitle)
      } else if (opts.newTitle) {
        const title = opts.newTitle.trim()
        const created = await api.createShortlist({
          title,
          person_ids: [personId],
        })
        const finalTitle = created?.title || title
        setAddedHuntName(finalTitle)
      }
      queryClient.invalidateQueries({ queryKey: ['person', personId] })
      queryClient.invalidateQueries({ queryKey: ['hunts'] })
    } finally {
      setIsAddingHunt(false)
    }
  }

  useEffect(() => {
    if (typeof window !== 'undefined' && typeof window.scrollTo === 'function') {
      try {
        window.scrollTo({ top: 0, left: 0, behavior: 'instant' })
      } catch {
        // bỏ qua nếu môi trường test không hỗ trợ
      }
    }
  }, [personId])

  const person = useQuery({
    queryKey: ['person', personId],
    queryFn: () => api.person(personId),
    retry: false,
    enabled: Number.isFinite(personId),
  })

  const rederive = useMutation({
    mutationFn: () => api.personRederive(personId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['person', personId] }),
  })

  const scrollToAnchor = (elementId: string, navKey: string) => {
    setActiveNav(navKey)
    if (typeof document !== 'undefined') {
      try {
        const el = document.getElementById(elementId)
        if (el && typeof el.scrollIntoView === 'function') {
          el.scrollIntoView({ behavior: 'smooth', block: 'start' })
        }
      } catch {
        // an toàn cho môi trường test jsdom
      }
    }
  }

  if (person.error instanceof ApiError) {
    return (
      <div className="person-360-container" style={{ paddingTop: '40px' }}>
        <div className="empty-results-box">
          <h3>Không mở được hồ sơ: {person.error.message}</h3>
          <Link to={returnPath} className="btn btn-secondary">
            ← Về {returnLabel}
          </Link>
        </div>
      </div>
    )
  }
  if (!person.data) return <div className="app-loading hint">Đang tải hồ sơ 360°...</div>

  const data = person.data
  const t = data.talent
  const curated = new Set(t?.curated_fields ?? [])

  const rows: Array<[string, React.ReactNode, string?]> = [
    ['Chức danh hiện tại', t?.current_title || data.headline || '—', 'current_title'],
    ['Công ty / Tổ chức', t?.current_company || '—', 'current_company'],
    ['Số năm kinh nghiệm', t?.years_experience != null ? `${t.years_experience} năm` : '—', 'years_experience'],
    ['Cấp bậc chuyên môn', t?.seniority || '—', 'seniority'],
    ['Trình độ học vấn', t?.education || '—', 'education'],
    ['Khu vực / Nơi ở', t?.location || data.location || '—', 'location'],
    ['Mức lương mong muốn', t?.expected_salary || '—', 'expected_salary'],
    ['Chuyên viên tuyển dụng', t?.owner_name || '—'],
  ]

  return (
    <div className="person-360-container">
      {/* Executive Hero Card */}
      <div className="person-hero-card">
        {/* Thông tin Ứng viên & Thẻ liên hệ & Thao tác Đợt tuyển */}
        <div className="person-hero-main-row">
          <div className="person-hero-left">
            <div className="person-avatar-large">
              {!avatarError ? (
                <img
                  src={api.personAvatarUrl(data.id)}
                  alt={data.display_name || 'Avatar'}
                  className="person-avatar-img"
                  onError={() => setAvatarError(true)}
                />
              ) : (
                <span>{(data.display_name || 'U').charAt(0).toUpperCase()}</span>
              )}
            </div>
            <div className="person-identity-info">
              <div className="person-name-row">
                <h1 className="person-fullname">{data.display_name || '(Chưa rõ tên)'}</h1>
                {data.needs_review && (
                  <span className="badge err">⚠️ Cần xem lại định danh</span>
                )}
                {isAdmin && data.index_health && <IndexHealthBadge health={data.index_health} />}
                {t?.seniority && (
                  <span className="badge seniority-badge">
                    {t.seniority}
                  </span>
                )}
              </div>
              <p className="person-headline-text">
                <span className="headline-title">{t?.current_title || data.headline || 'Chưa cập nhật chức danh'}</span>
                {t?.current_company && <span className="company-text"> @ {t.current_company}</span>}
                {t?.location && <span className="meta-dot"> · 📍 {t.location}</span>}
                {t?.years_experience != null && <span className="meta-dot"> · ⏳ {t.years_experience} năm KN</span>}
              </p>
            </div>
          </div>

          <div className="person-hero-right">
            {/* Thông báo bảo mật liên hệ CV nếu đang bật che */}
            {shouldMask && (
              <div className="contact-mask-notice">
                <span className="notice-lock-icon">🔒</span>
                <div className="notice-text">
                  <strong>Bảo mật liên hệ CV:</strong> Email và SĐT trong CV đang được che tự động. Mở khoá để xem chi tiết.
                </div>
              </div>
            )}

            {/* Thao tác Mở khoá liên hệ & Đợt tuyển / Săn */}
            <div className="person-hero-actions-col">
              <ContactUnlock
                personId={data.id}
                maskedEmail={data.primary_email}
                maskedPhone={data.primary_phone}
                onUnlocked={(res) => setUnlockedContacts(res)}
              />

              {canManageTalent && (
                <button
                  type="button"
                  className={`person-hunt-btn${addedHuntName ? ' is-added' : ''}`}
                  disabled={isAddingHunt}
                  onClick={() => setHuntModalOpen(true)}
                  title={
                    addedHuntName
                      ? `Đã vào đợt tuyển: ${addedHuntName} (bấm để đổi đợt tuyển)`
                      : 'Đưa ứng viên này vào đợt tuyển dụng hoặc nhiệm vụ săn'
                  }
                >
                  {isAddingHunt ? (
                    <>⏳ Đang thêm…</>
                  ) : addedHuntName ? (
                    <>✓ {addedHuntName}</>
                  ) : (
                    <>🎯 + Đợt tuyển / Săn</>
                  )}
                </button>
              )}
            </div>
          </div>
        </div>
      </div>

      {/* Sticky Quick-Nav Dock (Ghim nút quay lại + các Tabs ngay sát dưới Hero Card khi cuộn xuống) */}
      <nav className="person-sticky-nav" aria-label="Thanh điều hướng hồ sơ">
        <div className="person-sticky-nav-inner">
          <Link to={returnPath} className="person-sticky-back" title={`Quay lại ${returnLabel}`}>
            ← Quay lại {returnLabel}
          </Link>

          <div className="person-nav-pills">
            <button
              type="button"
              className={`person-nav-pill-btn ${activeNav === 'tong-quan' ? 'active' : ''}`}
              onClick={() => scrollToAnchor('sec-overview', 'tong-quan')}
            >
              <span>👤 Tổng quan</span>
            </button>
            {canViewCV ? (
              <button
                type="button"
                className={`person-nav-pill-btn ${activeNav === 'cv' ? 'active' : ''}`}
                onClick={() => scrollToAnchor('sec-cv', 'cv')}
              >
                <span>📄 Kho CV ({data.documents.length} file · {data.document_stats.submission_count} lượt)</span>
              </button>
            ) : (
              <button
                type="button"
                className="person-nav-pill-btn"
                disabled
                title="RM/Sales không có quyền xem tệp CV ứng viên"
              >
                <span>🔒 Kho CV (Chỉ dành cho TA)</span>
              </button>
            )}
            <button
              type="button"
              className={`person-nav-pill-btn ${activeNav === 'dot-tuyen' ? 'active' : ''}`}
              onClick={() => scrollToAnchor('sec-opportunities', 'dot-tuyen')}
            >
              <span>🎯 Đợt tuyển &amp; Cơ hội</span>
            </button>
            <button
              type="button"
              className={`person-nav-pill-btn ${activeNav === 'lich-su' ? 'active' : ''}`}
              onClick={() => scrollToAnchor('sec-history', 'lich-su')}
            >
              <span>⏳ Lịch sử &amp; Nguồn ({data.sources.length})</span>
            </button>
            <button
              type="button"
              className={`person-nav-pill-btn ${activeNav === 'ai' ? 'active' : ''}`}
              onClick={() => scrollToAnchor('sec-ai', 'ai')}
            >
              <span>💬 Hỏi &amp; đáp AI</span>
            </button>
          </div>
        </div>
      </nav>

      {/* 2-Column One-Page Cockpit Grid */}
      <div className="person-cockpit-grid">
        {/* CỘT TRÁI (~64%): HỒ SƠ NĂNG LỰC, KHO CV, ĐỢT TUYỂN & CƠ HỘI, LỊCH SỬ NGUỒN VÀ AI */}
        <div className="person-main-col">
          {/* KHỐI 1: TỔNG QUAN NĂNG LỰC & CHUYÊN MÔN */}
          <div id="sec-overview" className="person-section-card" style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
            {/* Tóm tắt năng lực & tiểu sử */}
            {t?.summary && (
              <div style={{ paddingBottom: '14px', borderBottom: '1px solid var(--border, rgba(255,255,255,0.08))' }}>
                <h3 className="section-title">📝 Tóm tắt năng lực &amp; Tiểu sử</h3>
                <p style={{ lineHeight: 1.6, color: 'var(--text)', margin: 0 }}>{t.summary}</p>
              </div>
            )}

            {/* Chi tiết chuyên môn & năng lực */}
            <div>
              <div className="section-title-row">
                <h3 className="section-title">🎓 Hồ sơ năng lực &amp; Chuyên môn</h3>
                <span className="person-section-tag">Năng lực cốt lõi</span>
              </div>
              <dl className="detail-grid-modern">
                {rows.map(([label, value, field]) => (
                  <div key={label} className="detail-item-modern">
                    <dt className="detail-dt">
                      {label}
                      {field && curated.has(field) && (
                        <span className="badge ok" title="Do người dùng chỉnh sửa — không bị ghi đè khi suy lại">
                          ✓ Xác nhận
                        </span>
                      )}
                    </dt>
                    <dd className="detail-dd">{value}</dd>
                  </div>
                ))}
              </dl>
            </div>

            {/* Bộ kỹ năng chuyên môn */}
            {t?.skills && t.skills.length > 0 && (
              <div style={{ paddingTop: '14px', borderTop: '1px solid var(--border, rgba(255,255,255,0.08))' }}>
                <div className="section-title-row">
                  <h3 className="section-title">
                    ⚡ Bộ kỹ năng chuyên môn <span className="skills-badge">{t.skills.length}</span>
                  </h3>
                </div>
                <div className="chips">
                  {t.skills.map((skill) => (
                    <span key={skill} className="chip skill-chip">
                      {skill}
                    </span>
                  ))}
                </div>
                <p className="hint" style={{ marginTop: '10px' }}>Kỹ năng được tự động tổng hợp từ dữ liệu ứng tuyển và hồ sơ nghề nghiệp.</p>
              </div>
            )}
          </div>

          {/* KHỐI 2: KHO CV & BẢN XEM TRƯỚC TÀI LIỆU */}
          <div id="sec-cv">
            {canViewCV ? (
              <CvViewerSection
                documents={data.documents}
                stats={data.document_stats}
                isUnlocked={isUnlocked}
              />
            ) : (
              <section className="person-section-card empty-results-box" style={{ padding: '30px 20px' }}>
                <div style={{ fontSize: '28px', marginBottom: '8px' }}>🔒</div>
                <h3 style={{ margin: '0 0 6px' }}>Kho CV bảo mật</h3>
                <p style={{ margin: 0, color: 'var(--text-muted)' }}>
                  Tệp CV và văn bản trích xuất được giới hạn cho bộ phận Tuyển dụng (TA) theo chính sách bảo mật thông tin.
                </p>
              </section>
            )}
          </div>

          {/* KHỐI 3: ĐỢT TUYỂN DỤNG & CƠ HỘI TÀI CHÍNH */}
          <div id="sec-opportunities" style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
            {/* Cơ hội tài chính & Bán chéo (Growth Radar) */}
            {canManageRB && <CustomerOpportunitiesSection personId={data.id} />}

            {/* Đợt tuyển đang xử lý (Talent Radar) */}
            {canManageTalent && <ActiveWorklists person={data} />}

            {/* Tín hiệu & Gợi ý AI */}
            <CandidateInsights person={data} />
          </div>

          {/* KHỐI 4: LỊCH SỬ NGUỒN, ĐỊNH DANH & BẰNG CHỨNG TRÍCH XUẤT */}
          <div id="sec-history" style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
            {/* Lịch sử nộp & Timeline (Stack dọc thoáng đãng) */}
            <HistoryAndTimelineSection person={data} />

            {/* Bằng chứng & nguồn gốc facts đã bóc tách (Chỉ dành cho Admin) */}
            <PersonFactsSection personId={personId} isAdmin={isAdmin} />

            {/* Định danh số & Kênh liên kết */}
            <section className="person-section-card">
              <div className="section-title-row">
                <h3 className="section-title">🔑 Kênh định danh số &amp; Liên kết ({data.identities.length})</h3>
                {shouldMask && (
                  <span className="badge muted" style={{ fontSize: '11px', padding: '3px 8px' }}>
                    🔒 Email &amp; SĐT đang được che bảo mật
                  </span>
                )}
              </div>
              <table className="identities-table" style={{ width: '100%', margin: '10px 0 0' }}>
                <thead>
                  <tr>
                    <th style={{ width: '140px' }}>Loại định danh</th>
                    <th>Giá trị ghi nhận</th>
                    <th style={{ width: '160px' }}>Ghi nhận đầu tiên</th>
                  </tr>
                </thead>
                <tbody>
                  {data.identities.map((identity) => {
                    const isEmail = identity.kind === 'email' || identity.value.includes('@')
                    const isPhone = identity.kind === 'phone' || identity.kind === 'mobile' || identity.kind === 'phone_number' || /^\+?\d{8,15}$/.test(identity.value.replace(/\s/g, ''))
                    const isSensitive = isEmail || isPhone
                    const displayVal = shouldMask && isEmail
                      ? maskEmail(identity.value)
                      : shouldMask && isPhone
                      ? maskPhone(identity.value)
                      : identity.value

                    return (
                      <tr key={`${identity.kind}-${identity.value}`}>
                        <td className="identity-kind-cell">
                          <span className="kind-badge">{identity.kind}</span>
                        </td>
                        <td>
                          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                            <strong>{displayVal}</strong>
                            {shouldMask && isSensitive && (
                              <span className="badge muted" style={{ fontSize: '10px', padding: '1px 5px' }}>🔒 Đã che</span>
                            )}
                          </div>
                        </td>
                        <td className="muted small">{date(identity.first_seen_at)}</td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </section>
          </div>

          {/* KHỐI 5: HỎI & ĐÁP AI VỀ NGƯỜI NÀY */}
          <div id="sec-ai">
            <PersonAskSection personId={data.id} />
          </div>
        </div>

        {/* CỘT PHẢI (~36%): STICKY CRM ACTION COCKPIT */}
        <div className="person-sticky-sidebar">
          {/* Bộ chuyển đổi quan hệ dành cho Admin hoặc người có cả 2 quyền */}
          {hasBoth && (
            <div className="person-crm-segmented-dock">
              <button
                type="button"
                aria-label="💼 Quan hệ Ứng viên (Talent)"
                className={`person-crm-segmented-btn ${relTab === 'talent' ? 'active' : ''}`}
                onClick={() => setRelTab('talent')}
              >
                <span className="crm-btn-icon">💼</span>
                <span className="crm-btn-text">Talent (Ứng viên)</span>
              </button>
              <button
                type="button"
                aria-label="👔 Quan hệ Khách hàng (Growth)"
                className={`person-crm-segmented-btn ${relTab === 'rb' ? 'active' : ''}`}
                onClick={() => setRelTab('rb')}
              >
                <span className="crm-btn-icon">👔</span>
                <span className="crm-btn-text">Growth (Khách hàng)</span>
              </button>
            </div>
          )}

          {/* Hiển thị bảng Quan hệ tương ứng */}
          {((hasBoth && relTab === 'talent') || (!hasBoth && canManageTalent)) && (
            <>
              <CandidateRelationship person={data} />
              <ProfileManagement person={data} />
            </>
          )}

          {((hasBoth && relTab === 'rb') || (!hasBoth && canManageRB)) && (
            <CustomerRelationship personId={data.id} />
          )}
        </div>
      </div>

      {/* Footer Bar */}
      <div className="person-footer-bar" style={{ marginTop: '24px' }}>
        {canManageTalent && (
          <button
            type="button"
            className="btn btn-secondary btn-sm"
            onClick={() => rederive.mutate()}
            disabled={rederive.isPending}
          >
            {rederive.isPending ? 'Đang suy lại…' : '🔄 Suy lại hồ sơ từ dữ liệu nguồn'}
          </button>
        )}
        <span className="hint">
          Tự động hợp nhất dữ liệu từ tất cả các nguồn và phiên bản CV (giữ nguyên các trường đã xác nhận thủ công).
        </span>
      </div>

      {/* Modal Đưa ứng viên vào Đợt tuyển / Nhiệm vụ săn */}
      {huntModalOpen && (
        <HuntAssignModal
          isOpen={huntModalOpen}
          title={`Đưa ${data.display_name || 'ứng viên'} vào Đợt tuyển / Săn`}
          people={[{ person_id: data.id, name: data.display_name || `Ứng viên #${data.id}` }]}
          openHunts={openHunts}
          onClose={() => setHuntModalOpen(false)}
          onAssign={handleAssignHunt}
        />
      )}
    </div>
  )
}

