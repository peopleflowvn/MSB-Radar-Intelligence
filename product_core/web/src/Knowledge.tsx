import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import React, { useState } from 'react'
import {
  api,
  ApiError,
  KnowledgeCategory,
  KnowledgeDocumentDetail,
  KnowledgeDocumentRow,
} from './api'

const CATEGORY_FALLBACK: Array<{ value: KnowledgeCategory; label: string }> = [
  { value: 'hr_policy', label: 'Chính sách nhân sự' },
  { value: 'recruitment_process', label: 'Quy trình tuyển dụng' },
  { value: 'leadership_decision', label: 'Quyết định lãnh đạo' },
  { value: 'guideline', label: 'Hướng dẫn nội bộ' },
  { value: 'other', label: 'Khác' },
]

function formatBytes(bytes: number) {
  if (!bytes) return '—'
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(2)} MB`
}

function StatusBadge({ status, label }: { status: string; label: string }) {
  const cls = status === 'done' ? 'ok' : status === 'failed' ? 'err' : 'warn'
  return <span className={`badge ${cls}`}>{label}</span>
}

// --- Panel tạo tài liệu: tải file (Radar tự trích) hoặc nhập tay ---
function CreatePanel({ categories, onDone }: {
  categories: Array<{ value: KnowledgeCategory; label: string }>
  onDone: () => void
}) {
  const [mode, setMode] = useState<'upload' | 'manual'>('upload')
  const [title, setTitle] = useState('')
  const [category, setCategory] = useState<KnowledgeCategory>('other')
  const [text, setText] = useState('')
  const [file, setFile] = useState<File | null>(null)
  const [isDragOver, setIsDragOver] = useState(false)
  const [warning, setWarning] = useState('')
  const fileInputRef = React.useRef<HTMLInputElement | null>(null)

  const uploadMutation = useMutation({
    mutationFn: () => api.knowledgeUpload(file as File, { title, category }),
    onSuccess: (result) => {
      setWarning(result.warning || '')
      if (!result.warning) onDone()
    },
  })
  const createMutation = useMutation({
    mutationFn: () => api.knowledgeCreate({ title, category, parsed_text: text }),
    onSuccess: () => onDone(),
  })

  const pending = uploadMutation.isPending || createMutation.isPending
  const error = uploadMutation.error || createMutation.error

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (!title.trim()) return
    if (mode === 'upload') {
      if (!file) return
      uploadMutation.mutate()
    } else {
      if (!text.trim()) return
      createMutation.mutate()
    }
  }

  const pickFile = (picked: File | null | undefined) => {
    if (!picked) return
    setFile(picked)
    if (!title.trim()) setTitle(picked.name.replace(/\.[^.]+$/, ''))
  }

  return (
    <div className="admin-panel-card" style={{ padding: 20, marginBottom: 20 }}>
      <form onSubmit={handleSubmit}>
        <div className="form-row-2">
          <div>
            <label>Tiêu đề</label>
            <input
              type="text" className="input-text" value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="VD: Quy trình nghỉ phép 2026"
            />
          </div>
          <div>
            <label>Danh mục</label>
            <select
              className="input-text" value={category}
              onChange={(e) => setCategory(e.target.value as KnowledgeCategory)}
            >
              {categories.map((c) => (
                <option key={c.value} value={c.value}>{c.label}</option>
              ))}
            </select>
          </div>
        </div>

        <div style={{ display: 'flex', gap: 8, margin: '16px 0 12px' }}>
          <button type="button"
            className={`pill-btn ${mode === 'upload' ? 'active' : ''}`}
            onClick={() => setMode('upload')}>
            📁 Tải file lên
          </button>
          <button type="button"
            className={`pill-btn ${mode === 'manual' ? 'active' : ''}`}
            onClick={() => setMode('manual')}>
            ✏️ Nhập nội dung
          </button>
        </div>

        {mode === 'upload' ? (
          <div>
            <input
              ref={fileInputRef} type="file" style={{ display: 'none' }}
              accept=".pdf,.docx,.xlsx,.pptx,.txt,.md,.csv,.json,.png,.jpg,.jpeg,.webp"
              onChange={(e) => pickFile(e.target.files?.[0])}
            />
            <div
              className={`icon-upload-dropzone ${isDragOver ? 'dragover' : ''}`}
              onClick={() => fileInputRef.current?.click()}
              onDragOver={(e) => { e.preventDefault(); setIsDragOver(true) }}
              onDragLeave={() => setIsDragOver(false)}
              onDrop={(e) => {
                e.preventDefault(); setIsDragOver(false)
                pickFile(e.dataTransfer.files?.[0])
              }}
            >
              <div className="icon-upload-icon-svg">📄</div>
              {file ? (
                <span className="icon-upload-main-text">{file.name} ({formatBytes(file.size)})</span>
              ) : (
                <span className="icon-upload-main-text">Bấm để chọn tệp hoặc kéo &amp; thả vào đây</span>
              )}
              <span className="icon-upload-sub-text">
                PDF, DOCX, XLSX, PPTX, TXT/MD/CSV/JSON hoặc ảnh — Radar tự trích nội dung.
              </span>
            </div>
          </div>
        ) : (
          <div>
            <label>Nội dung</label>
            <textarea
              className="input-text" rows={8} value={text}
              onChange={(e) => setText(e.target.value)}
              placeholder="Dán hoặc gõ nội dung tài liệu…"
            />
          </div>
        )}

        {warning && <p className="hint" style={{ color: 'var(--warn, #b45309)', marginTop: 10 }}>⚠️ {warning}</p>}
        {error && (
          <p className="error-text" style={{ marginTop: 10 }}>
            {error instanceof ApiError ? error.message : 'Có lỗi xảy ra.'}
          </p>
        )}

        <div className="form-actions" style={{ marginTop: 16 }}>
          <button type="submit" className="btn btn-primary" disabled={pending}>
            {pending ? 'Đang lưu…' : 'Lưu tài liệu'}
          </button>
          <button type="button" className="btn btn-secondary" onClick={onDone}>Huỷ</button>
        </div>
      </form>
    </div>
  )
}

// --- Panel sửa một tài liệu đã có ---
function EditPanel({ id, onDone }: { id: number; onDone: () => void }) {
  const queryClient = useQueryClient()
  const detailQuery = useQuery({
    queryKey: ['knowledge-detail', id],
    queryFn: () => api.knowledgeGet(id),
  })
  const [draft, setDraft] = useState<KnowledgeDocumentDetail | null>(null)
  React.useEffect(() => {
    if (detailQuery.data) setDraft(detailQuery.data)
  }, [detailQuery.data])

  const saveMutation = useMutation({
    mutationFn: () => api.knowledgeUpdate(id, {
      title: draft!.title, category: draft!.category,
      parsed_text: draft!.parsed_text, is_active: draft!.is_active,
    }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['knowledge-documents'] })
      onDone()
    },
  })

  if (detailQuery.isLoading || !draft) {
    return (
      <div className="admin-panel-card" style={{ padding: 20, marginBottom: 20, textAlign: 'center' }}>
        <div className="loading-spinner" style={{ margin: '0 auto' }} />
      </div>
    )
  }

  return (
    <div className="admin-panel-card" style={{ padding: 20, marginBottom: 20 }}>
      <div className="form-row-2">
        <div>
          <label>Tiêu đề</label>
          <input
            type="text" className="input-text" value={draft.title}
            onChange={(e) => setDraft({ ...draft, title: e.target.value })}
          />
        </div>
        <div>
          <label>Danh mục</label>
          <select
            className="input-text" value={draft.category}
            onChange={(e) => setDraft({ ...draft, category: e.target.value as KnowledgeCategory })}
          >
            {CATEGORY_FALLBACK.map((c) => (
              <option key={c.value} value={c.value}>{c.label}</option>
            ))}
          </select>
        </div>
      </div>

      <div style={{ marginTop: 16 }}>
        <label>Nội dung</label>
        <textarea
          className="input-text" rows={10} value={draft.parsed_text}
          onChange={(e) => setDraft({ ...draft, parsed_text: e.target.value })}
        />
      </div>

      <label style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 16, cursor: 'pointer' }}>
        <input
          type="checkbox" checked={draft.is_active}
          onChange={(e) => setDraft({ ...draft, is_active: e.target.checked })}
        />
        <span>Đang hiệu lực (tắt để rút khỏi Radar ngay mà không phải xoá)</span>
      </label>

      {saveMutation.error && (
        <p className="error-text" style={{ marginTop: 10 }}>
          {saveMutation.error instanceof ApiError ? saveMutation.error.message : 'Có lỗi xảy ra.'}
        </p>
      )}

      <div className="form-actions" style={{ marginTop: 16 }}>
        <button
          type="button" className="btn btn-primary"
          disabled={saveMutation.isPending || !draft.title.trim()}
          onClick={() => saveMutation.mutate()}
        >
          {saveMutation.isPending ? 'Đang lưu…' : 'Lưu thay đổi'}
        </button>
        <button type="button" className="btn btn-secondary" onClick={onDone}>Huỷ</button>
      </div>
    </div>
  )
}

export default function Knowledge() {
  const queryClient = useQueryClient()
  const [categoryFilter, setCategoryFilter] = useState('')
  const [showCreate, setShowCreate] = useState(false)
  const [editingId, setEditingId] = useState<number | null>(null)

  const listQuery = useQuery({
    queryKey: ['knowledge-documents', categoryFilter],
    queryFn: () => api.knowledgeList(categoryFilter || undefined),
  })

  const toggleMutation = useMutation({
    mutationFn: (row: KnowledgeDocumentRow) =>
      api.knowledgeUpdate(row.id, { is_active: !row.is_active }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['knowledge-documents'] }),
  })

  const deleteMutation = useMutation({
    mutationFn: (id: number) => api.knowledgeDelete(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['knowledge-documents'] }),
  })

  const handleDelete = (row: KnowledgeDocumentRow) => {
    if (window.confirm(`Xoá hẳn tài liệu "${row.title}"? Không thể hoàn tác.`)) {
      deleteMutation.mutate(row.id)
    }
  }

  const results = listQuery.data?.results ?? []
  const categories = listQuery.data?.categories ?? CATEGORY_FALLBACK

  const closeForms = () => { setShowCreate(false); setEditingId(null) }

  return (
    <div className="otp-admin-container">
      <div className="otp-hero-banner">
        <div className="otp-hero-header">
          <div className="otp-hero-title">
            <h2><span>📚</span> Tri thức nội bộ</h2>
            <p>
              Tài liệu quy trình, chính sách và quyết định để Radar trả lời theo đúng
              tài liệu của công ty thay vì kiến thức chung. Chỉ người có quyền phù hợp
              mới thấy trang này.
            </p>
          </div>
        </div>
      </div>

      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 12, marginBottom: 16 }}>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          <button
            type="button" className={`pill-btn ${categoryFilter === '' ? 'active' : ''}`}
            onClick={() => setCategoryFilter('')}
          >
            Tất cả ({results.length})
          </button>
          {categories.map((c) => (
            <button
              key={c.value} type="button"
              className={`pill-btn ${categoryFilter === c.value ? 'active' : ''}`}
              onClick={() => setCategoryFilter(c.value)}
            >
              {c.label}
            </button>
          ))}
        </div>
        <button
          type="button" className="btn btn-primary"
          onClick={() => { setEditingId(null); setShowCreate((v) => !v) }}
        >
          {showCreate ? '✕ Đóng' : '+ Thêm tài liệu'}
        </button>
      </div>

      {showCreate && <CreatePanel categories={categories} onDone={closeForms} />}
      {editingId !== null && <EditPanel id={editingId} onDone={closeForms} />}

      <div className="admin-panel-card" style={{ padding: 0, overflow: 'hidden' }}>
        <div style={{ padding: '16px 20px', borderBottom: '1px solid var(--border)' }}>
          <h3 style={{ fontSize: 15, fontWeight: 700, margin: 0 }}>
            📁 Danh sách tài liệu ({results.length})
          </h3>
        </div>

        {listQuery.isLoading ? (
          <div style={{ padding: '40px 20px', textAlign: 'center', color: 'var(--muted)' }}>
            <div className="loading-spinner" style={{ margin: '0 auto 12px' }} />
            <p>Đang tải danh sách…</p>
          </div>
        ) : results.length === 0 ? (
          <div style={{ padding: '40px 20px', textAlign: 'center', color: 'var(--muted)' }}>
            <p style={{ fontSize: 14, margin: '0 0 8px' }}>Chưa có tài liệu nào.</p>
            <p style={{ fontSize: 12.5, margin: 0 }}>Bấm "+ Thêm tài liệu" để bắt đầu.</p>
          </div>
        ) : (
          <div style={{ overflowX: 'auto' }}>
            <table className="data-table" style={{ width: '100%', borderCollapse: 'collapse' }}>
              <thead>
                <tr>
                  <th style={{ textAlign: 'left', padding: '12px 16px' }}>Tiêu đề</th>
                  <th style={{ textAlign: 'left', padding: '12px 16px' }}>Danh mục</th>
                  <th style={{ textAlign: 'center', padding: '12px 16px' }}>Trạng thái</th>
                  <th style={{ textAlign: 'center', padding: '12px 16px' }}>Hiệu lực</th>
                  <th style={{ textAlign: 'left', padding: '12px 16px' }}>Người tải lên</th>
                  <th style={{ textAlign: 'center', padding: '12px 16px' }}>Cập nhật</th>
                  <th style={{ textAlign: 'right', padding: '12px 16px' }}>Thao tác</th>
                </tr>
              </thead>
              <tbody>
                {results.map((row) => (
                  <tr key={row.id}>
                    <td style={{ padding: '10px 16px' }}>
                      <strong>{row.title}</strong>
                      {row.filename && (
                        <div style={{ fontSize: 12, color: 'var(--muted)' }}>
                          {row.filename} · {formatBytes(row.file_size)} · {row.text_length.toLocaleString('vi-VN')} ký tự
                        </div>
                      )}
                    </td>
                    <td style={{ padding: '10px 16px' }}>{row.category_label}</td>
                    <td style={{ padding: '10px 16px', textAlign: 'center' }}>
                      <StatusBadge status={row.parse_status} label={row.parse_status_label} />
                    </td>
                    <td style={{ padding: '10px 16px', textAlign: 'center' }}>
                      <button
                        type="button"
                        className={`badge ${row.is_active ? 'ok' : 'off'}`}
                        style={{ cursor: 'pointer', border: 'none' }}
                        disabled={toggleMutation.isPending}
                        onClick={() => toggleMutation.mutate(row)}
                        title="Bấm để bật/tắt"
                      >
                        {row.is_active ? 'Đang bật' : 'Đã tắt'}
                      </button>
                    </td>
                    <td style={{ padding: '10px 16px' }}>{row.uploaded_by_name || '—'}</td>
                    <td style={{ padding: '10px 16px', textAlign: 'center', fontSize: 12.5 }}>
                      {new Date(row.updated_at).toLocaleString('vi-VN')}
                    </td>
                    <td style={{ padding: '10px 16px', textAlign: 'right' }}>
                      <button
                        type="button" className="btn btn-secondary btn-sm"
                        style={{ marginRight: 6 }}
                        onClick={() => { setShowCreate(false); setEditingId(row.id) }}
                      >
                        Sửa
                      </button>
                      <button
                        type="button" className="btn btn-secondary btn-sm"
                        onClick={() => handleDelete(row)}
                      >
                        Xoá
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}
