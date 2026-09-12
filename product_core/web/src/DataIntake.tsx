import { useMemo, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, IntakeBatch, IntakeRow, IntakeRowStatus } from './api'

// --- SVG Icons ---
function IconFileSpreadsheet() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
      <polyline points="14 2 14 8 20 8" />
      <path d="M8 13h2" />
      <path d="M14 13h2" />
      <path d="M8 17h2" />
      <path d="M14 17h2" />
    </svg>
  )
}

function IconFileText() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
      <polyline points="14 2 14 8 20 8" />
      <line x1="16" y1="13" x2="8" y2="13" />
      <line x1="16" y1="17" x2="8" y2="17" />
      <polyline points="10 9 9 9 8 9" />
    </svg>
  )
}

function IconUploadCloud() {
  return (
    <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M16 16l-4-4-4 4" />
      <path d="M12 12v9" />
      <path d="M20.39 18.39A5 5 0 0 0 18 9h-1.26A8 8 0 1 0 3 16.3" />
    </svg>
  )
}

function IconDownload() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
      <polyline points="7 10 12 15 17 10" />
      <line x1="12" y1="15" x2="12" y2="3" />
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

function IconSparkles() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="m12 3-1.912 5.813a2 2 0 0 1-1.275 1.275L3 12l5.813 1.912a2 2 0 0 1 1.275 1.275L12 21l1.912-5.813a2 2 0 0 1 1.275-1.275L21 12l-5.813-1.912a2 2 0 0 1-1.275-1.275L12 3Z" />
    </svg>
  )
}

function IconCheckCircle() {
  return (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
      <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14" />
      <polyline points="22 4 12 14.01 9 11.01" />
    </svg>
  )
}

function IconAlertCircle() {
  return (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="10" />
      <line x1="12" y1="8" x2="12" y2="12" />
      <line x1="12" y1="16" x2="12.01" y2="16" />
    </svg>
  )
}

function IconTrash() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <polyline points="3 6 5 6 21 6" />
      <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
    </svg>
  )
}

function IconEye() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z" />
      <circle cx="12" cy="12" r="3" />
    </svg>
  )
}

function IconExternalLink() {
  return (
    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6" />
      <polyline points="15 3 21 3 21 9" />
      <line x1="10" y1="14" x2="21" y2="3" />
    </svg>
  )
}

function IconX() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <line x1="18" y1="6" x2="6" y2="18" />
      <line x1="6" y1="6" x2="18" y2="18" />
    </svg>
  )
}

// Các cột cho phép sửa nhanh trên lưới
const EDITABLE: Array<{ key: string; label: string; placeholder: string }> = [
  { key: 'fullname', label: 'Họ tên', placeholder: 'Nguyễn Văn A' },
  { key: 'email', label: 'Email', placeholder: 'a.nguyen@email.com' },
  { key: 'phone', label: 'Số điện thoại', placeholder: '0901234567' },
  { key: 'position', label: 'Vị trí / Chức danh', placeholder: 'Chuyên viên...' },
  { key: 'skills', label: 'Kỹ năng chính', placeholder: 'Python, SQL, React...' },
]

const STATUS_META: Record<IntakeRowStatus, { label: string; color: string; bg: string; icon: string }> = {
  valid: { label: 'Hợp lệ', color: '#059669', bg: 'rgba(16,185,129,0.12)', icon: '🟢' },
  duplicate: { label: 'Trùng lặp', color: '#d97706', bg: 'rgba(245,158,11,0.14)', icon: '🟠' },
  invalid: { label: 'Lỗi định danh', color: '#dc2626', bg: 'rgba(239,68,68,0.12)', icon: '🔴' },
  skipped: { label: 'Bỏ qua', color: '#6b7280', bg: 'rgba(107,114,128,0.12)', icon: '⚪' },
  committed: { label: 'Đã ghi hệ thống', color: '#2563eb', bg: 'rgba(37,99,235,0.12)', icon: '🔵' },
  error: { label: 'Ghi thất bại', color: '#dc2626', bg: 'rgba(239,68,68,0.18)', icon: '⚠️' },
}

function StatusChip({ status }: { status: IntakeRowStatus }) {
  const m = STATUS_META[status] ?? STATUS_META.valid
  return (
    <span
      className="tag"
      style={{
        background: m.bg,
        color: m.color,
        border: 'none',
        fontWeight: 600,
        whiteSpace: 'nowrap',
        display: 'inline-flex',
        alignItems: 'center',
        gap: '4px',
        fontSize: '11.5px',
        padding: '3px 8px',
      }}
    >
      <span>{m.icon}</span>
      <span>{m.label}</span>
    </span>
  )
}

export default function DataIntake() {
  const queryClient = useQueryClient()
  const [mode, setMode] = useState<'excel' | 'cv'>('excel')
  const [sourceLabel, setSourceLabel] = useState('')
  const [batchId, setBatchId] = useState<number | null>(null)
  const [dedupStrategy, setDedupStrategy] = useState<'skip' | 'update'>('skip')
  const [notice, setNotice] = useState<{ text: string; type?: 'info' | 'error' | 'success' } | null>(null)
  const [searchQuery, setSearchQuery] = useState('')
  const [statusFilter, setStatusFilter] = useState<'all' | IntakeRowStatus>('all')
  const [inspectRow, setInspectRow] = useState<IntakeRow | null>(null)
  const [dragOver, setDragOver] = useState(false)
  const [isUploadingStep1, setIsUploadingStep1] = useState(false)

  const fileRef = useRef<HTMLInputElement>(null)
  const cvInputRef = useRef<HTMLInputElement>(null)
  const cvRef = useRef<HTMLInputElement>(null)

  const history = useQuery({ queryKey: ['intake-batches'], queryFn: api.intakeBatches, retry: false })
  const batchQuery = useQuery({
    queryKey: ['intake-batch', batchId],
    queryFn: () => api.intakeBatch(batchId as number),
    enabled: batchId != null,
    retry: false,
  })
  const batch = batchQuery.data ?? null

  function refreshAll() {
    queryClient.invalidateQueries({ queryKey: ['intake-batch', batchId] })
    queryClient.invalidateQueries({ queryKey: ['intake-batches'] })
    queryClient.invalidateQueries({ queryKey: ['summary'] })
    queryClient.invalidateQueries({ queryKey: ['records'] })
  }

  const createExcel = useMutation({
    mutationFn: (file: File) => api.intakeCreateExcelBatch(file, sourceLabel.trim()),
    onSuccess: (created) => {
      setBatchId(created.id)
      queryClient.setQueryData(['intake-batch', created.id], created)
      setNotice({
        text: `Đã nạp file "${fileRef.current?.files?.[0]?.name || 'Excel'}" với ${created.row_count} ứng viên vào bàn dựng.`,
        type: 'success',
      })
      queryClient.invalidateQueries({ queryKey: ['intake-batches'] })
    },
    onError: (e: Error) => setNotice({ text: e.message, type: 'error' }),
  })

  // Hàm tải trực tiếp danh sách CV: tạo lô + upload + bóc tách AI trong 1 bước duy nhất
  const handleBulkCvUpload = async (files: File[]) => {
    if (!files.length) return
    setIsUploadingStep1(true)
    setNotice({ text: `Đang khởi tạo lô và tải lên ${files.length} file CV để AI bóc tách...`, type: 'info' })
    try {
      const created = await api.intakeCreateCvBatch(sourceLabel.trim())
      const updated = await api.intakeUploadCvs(created.id, files)
      setBatchId(updated.id)
      queryClient.setQueryData(['intake-batch', updated.id], updated)
      queryClient.invalidateQueries({ queryKey: ['intake-batches'] })
      const r = updated.cv_result
      if (r) {
        setNotice({
          text: `Đã xử lý xong ${r.attached + r.parsed} CV (Gắn hồ sơ: ${r.attached}, AI bóc tách: ${r.parsed}, Cảnh báo: ${r.errors.length}).`,
          type: r.errors.length > 0 ? 'info' : 'success',
        })
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Lỗi khi tải lên và bóc tách CV.'
      setNotice({ text: msg, type: 'error' })
    } finally {
      setIsUploadingStep1(false)
    }
  }

  const uploadCvs = useMutation({
    mutationFn: (files: File[]) => api.intakeUploadCvs(batchId as number, files),
    onSuccess: (updated) => {
      queryClient.setQueryData(['intake-batch', updated.id], updated)
      const r = updated.cv_result
      if (r) {
        setNotice({
          text: `Đã tải ${r.attached + r.parsed} CV (Gắn hồ sơ: ${r.attached}, AI bóc tách: ${r.parsed}, Lỗi: ${r.errors.length}).`,
          type: r.errors.length > 0 ? 'info' : 'success',
        })
      }
    },
    onError: (e: Error) => setNotice({ text: e.message, type: 'error' }),
  })

  const patchRow = useMutation({
    mutationFn: (v: { rowId: number; patch: { fields?: Record<string, string>; skip?: boolean } }) =>
      api.intakePatchRow(batchId as number, v.rowId, v.patch),
    onSuccess: (updatedRow) => {
      queryClient.invalidateQueries({ queryKey: ['intake-batch', batchId] })
      if (inspectRow && inspectRow.id === updatedRow.id) {
        setInspectRow(updatedRow)
      }
    },
    onError: (e: Error) => setNotice({ text: e.message, type: 'error' }),
  })

  const commit = useMutation({
    mutationFn: () => api.intakeCommit(batchId as number, dedupStrategy),
    onSuccess: (done) => {
      queryClient.setQueryData(['intake-batch', done.id], done)
      setNotice({
        text: `Đã commit thành công ${done.commit_result?.committed ?? 0} ứng viên vào bộ não Radar Core!`,
        type: 'success',
      })
      refreshAll()
    },
    onError: (e: Error) => setNotice({ text: e.message, type: 'error' }),
  })

  const discard = useMutation({
    mutationFn: () => api.intakeDeleteBatch(batchId as number),
    onSuccess: () => {
      setBatchId(null)
      setInspectRow(null)
      setNotice({ text: 'Đã huỷ lô nháp và giải phóng file CV tạm.', type: 'info' })
      refreshAll()
    },
    onError: (e: Error) => setNotice({ text: e.message, type: 'error' }),
  })

  const rows = useMemo<IntakeRow[]>(() => batch?.rows ?? [], [batch])

  const filteredRows = useMemo(() => {
    return rows.filter((r) => {
      if (statusFilter !== 'all' && r.validation_status !== statusFilter) {
        return false
      }
      if (!searchQuery.trim()) return true
      const q = searchQuery.toLowerCase()
      const f = r.fields || {}
      return (
        (f.fullname && f.fullname.toLowerCase().includes(q)) ||
        (f.email && f.email.toLowerCase().includes(q)) ||
        (f.phone && f.phone.toLowerCase().includes(q)) ||
        (f.position && f.position.toLowerCase().includes(q)) ||
        (f.skills && f.skills.toLowerCase().includes(q)) ||
        (r.cv_filename && r.cv_filename.toLowerCase().includes(q))
      )
    })
  }, [rows, statusFilter, searchQuery])

  const committable = useMemo(
    () => rows.filter((r) => r.validation_status === 'valid' || r.validation_status === 'duplicate').length,
    [rows],
  )

  const isDone = batch?.status === 'done'

  // Kéo thả file ở Bước 1
  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault()
    setDragOver(false)
    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      if (mode === 'excel') {
        createExcel.mutate(e.dataTransfer.files[0])
      } else {
        handleBulkCvUpload(Array.from(e.dataTransfer.files))
      }
    }
  }

  // ---- GIAI ĐOẠN 1: MÀN HÌNH KHỞI TẠO NGUỒN & TẢI TỆP ----
  if (batch == null) {
    return (
      <div className="intake-studio-container">
        {/* Hero Card */}
        <div className="intake-hero-card">
          <div className="intake-hero-top">
            <div className="intake-hero-title-group">
              <div className="intake-hero-icon">📥</div>
              <div>
                <h2 style={{ margin: 0, fontSize: '18px', fontWeight: 700, color: 'var(--text)' }}>
                  Nhập liệu Ứng viên & Bàn dựng dữ liệu (Data Intake Studio)
                </h2>
                <p className="muted" style={{ margin: '4px 0 0', fontSize: '13px', maxWidth: '680px' }}>
                  Nạp ứng viên từ bên ngoài thông qua nút trung gian ảo <code>hub-manual</code>. Dữ liệu đi qua bàn nhận <code>SourceRecord</code>, được chuẩn hóa định danh và bảo toàn nguyên vẹn mọi thông tin đã xác thực.
                </p>
              </div>
            </div>

            <div className="intake-pipeline-stepper">
              <div className="intake-step-item active">
                <span className="intake-step-num">1</span>
                <span>Khởi tạo & Tải tệp</span>
              </div>
              <div className="intake-step-divider" />
              <div className="intake-step-item">
                <span className="intake-step-num">2</span>
                <span>Bàn dựng & Kiểm duyệt</span>
              </div>
              <div className="intake-step-divider" />
              <div className="intake-step-item">
                <span className="intake-step-num">3</span>
                <span>Đồng bộ Radar Core</span>
              </div>
            </div>
          </div>
        </div>

        {/* Action Panel: Config + Dropzone */}
        <div className="intake-card">
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: '12px' }}>
            <div className="intake-mode-pills">
              <button
                type="button"
                className={`intake-mode-btn ${mode === 'excel' ? 'active' : ''}`}
                onClick={() => setMode('excel')}
              >
                <IconFileSpreadsheet />
                <span>Từ bảng tính Excel / CSV</span>
              </button>
              <button
                type="button"
                className={`intake-mode-btn ${mode === 'cv' ? 'active' : ''}`}
                onClick={() => setMode('cv')}
              >
                <IconSparkles />
                <span>Hàng loạt CV (AI Bóc tách)</span>
              </button>
            </div>

            {mode === 'excel' && (
              <a
                href={api.intakeTemplateUrl}
                download="radar_nhap_ung_vien.xlsx"
                className="btn btn-sm btn-secondary"
                style={{ display: 'inline-flex', alignItems: 'center', gap: '6px', textDecoration: 'none' }}
              >
                <IconDownload />
                <span>Tải file Excel mẫu (.xlsx)</span>
              </a>
            )}
            <a
              href={api.intakeExportUrl}
              download="radar_xuat_ung_vien.csv"
              className="btn btn-sm btn-secondary"
              style={{ display: 'inline-flex', alignItems: 'center', gap: '6px', textDecoration: 'none' }}
              title="Xuất toàn bộ ứng viên hiện có theo đúng cột template này — liên hệ được che như mọi bản xuất khác"
            >
              <IconDownload />
              <span>Xuất dữ liệu (.csv)</span>
            </a>
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: '6px', maxWidth: '520px' }}>
            <label style={{ fontSize: '13px', fontWeight: 600, color: 'var(--text)', display: 'flex', alignItems: 'center', gap: '6px' }}>
              <span>Nguồn thu nhận (Source Label)</span>
              <span className="muted" style={{ fontWeight: 400, fontSize: '12px' }}>(gán cho toàn bộ lô)</span>
            </label>
            <input
              type="text"
              className="edge-create-input"
              placeholder="VD: Hội thảo ĐH Bách Khoa, Sự kiện Tech Expo 2026, TopCV Q3…"
              value={sourceLabel}
              onChange={(e) => setSourceLabel(e.target.value)}
            />
          </div>

          {/* Drag & Drop Zone - Click mở thẳng file picker */}
          <div
            className={`intake-dropzone ${dragOver ? 'drag-active' : ''}`}
            onDragOver={(e) => {
              e.preventDefault()
              setDragOver(true)
            }}
            onDragLeave={() => setDragOver(false)}
            onDrop={handleDrop}
            onClick={() => {
              if (mode === 'excel') {
                fileRef.current?.click()
              } else {
                cvInputRef.current?.click()
              }
            }}
          >
            <div className="intake-dropzone-icon">
              {mode === 'excel' ? <IconUploadCloud /> : <IconSparkles />}
            </div>

            <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
              <span style={{ fontSize: '15px', fontWeight: 600, color: 'var(--text)' }}>
                {mode === 'excel'
                  ? (createExcel.isPending ? 'Đang đọc và phân tích bảng tính...' : 'Kéo thả file Excel / CSV vào đây hoặc bấm để chọn tệp')
                  : (isUploadingStep1 ? 'Đang tạo lô và AI bóc tách thông tin...' : 'Kéo thả các file CV vào đây hoặc bấm để chọn nhiều file')}
              </span>
              <span className="muted" style={{ fontSize: '12.5px' }}>
                {mode === 'excel'
                  ? 'Hỗ trợ định dạng .xlsx, .csv (Tối đa 5.000 dòng / 10MB)'
                  : 'AI tự động trích xuất Họ tên, Email, SĐT, Kỹ năng, Kinh nghiệm (Tối đa 200 file .pdf, .docx, .doc, .txt)'}
              </span>
            </div>

            <div className="intake-format-tags">
              {mode === 'excel' ? (
                <>
                  <span className="intake-format-pill">XLSX</span>
                  <span className="intake-format-pill">CSV</span>
                  <span className="intake-format-pill">Định danh qua Email / SĐT / LinkedIn</span>
                </>
              ) : (
                <>
                  <span className="intake-format-pill">PDF</span>
                  <span className="intake-format-pill">DOCX</span>
                  <span className="intake-format-pill">DOC</span>
                  <span className="intake-format-pill">TXT</span>
                  <span className="intake-format-pill">Trích xuất tự động + Regex Fallback</span>
                </>
              )}
            </div>

            {/* Input file cho Excel */}
            <input
              ref={fileRef}
              type="file"
              accept=".xlsx,.csv"
              style={{ display: 'none' }}
              onChange={(e) => {
                const f = e.target.files?.[0]
                if (f) createExcel.mutate(f)
                if (fileRef.current) fileRef.current.value = ''
              }}
            />

            {/* Input file cho Multi-CV ở Step 1 */}
            <input
              ref={cvInputRef}
              type="file"
              multiple
              accept=".pdf,.doc,.docx,.txt"
              style={{ display: 'none' }}
              onChange={(e) => {
                const files = Array.from(e.target.files ?? [])
                if (files.length) handleBulkCvUpload(files)
                if (cvInputRef.current) cvInputRef.current.value = ''
              }}
            />
          </div>

          {notice && <IntakeNotice notice={notice} onClose={() => setNotice(null)} />}
        </div>

        {/* Lịch sử và Lô nháp gần đây */}
        <IntakeHistorySection
          history={history.data?.results ?? []}
          onOpen={(id) => {
            setBatchId(id)
            setNotice(null)
          }}
        />
      </div>
    )
  }


  // ---- GIAI ĐOẠN 2 & 3: BÀN DỰNG DỮ LIỆU & COMMIT VÀO RADAR CORE ----
  return (
    <div className="intake-studio-container">
      {/* Active Batch Hero Header */}
      <div className="intake-hero-card">
        <div className="intake-hero-top">
          <div className="intake-hero-title-group">
            <div
              className="intake-hero-icon"
              style={{
                background: isDone
                  ? 'rgba(16, 185, 129, 0.15)'
                  : 'linear-gradient(135deg, rgba(37, 99, 235, 0.15), rgba(124, 58, 237, 0.15))',
                color: isDone ? '#059669' : '#2563eb',
              }}
            >
              {isDone ? '✓' : '⚙️'}
            </div>
            <div>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap' }}>
                <h2 style={{ margin: 0, fontSize: '18px', fontWeight: 700, color: 'var(--text)' }}>
                  Lô #{batch.id} · {batch.kind === 'excel' ? 'Bảng tính Excel/CSV' : 'Hàng loạt CV'}
                </h2>
                {batch.source_label && (
                  <span className="source-badge file_import">
                    {batch.source_label}
                  </span>
                )}
                <span
                  className="tag"
                  style={{
                    background: isDone ? 'rgba(16,185,129,0.12)' : 'rgba(37,99,235,0.12)',
                    color: isDone ? '#059669' : '#2563eb',
                    fontWeight: 600,
                  }}
                >
                  {isDone ? 'Đã hoàn tất ghi' : 'Bàn dựng đang mở'}
                </span>
              </div>
              <p className="muted" style={{ margin: '4px 0 0', fontSize: '12.5px' }}>
                {batch.original_filename ? `Tệp gốc: ${batch.original_filename} · ` : ''}
                {batch.row_count} ứng viên · Tạo bởi <strong>{batch.created_by_name || 'Hệ thống'}</strong> lúc {new Date(batch.created_at).toLocaleString('vi-VN')}
              </p>
            </div>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
            <button
              type="button"
              className="btn btn-sm btn-secondary"
              onClick={() => {
                setBatchId(null)
                setInspectRow(null)
              }}
            >
              ← Danh sách Lô
            </button>
          </div>
        </div>

        {/* Pipeline Stepper State */}
        <div className="intake-pipeline-stepper">
          <div className="intake-step-item completed">
            <span className="intake-step-num">✓</span>
            <span>Khởi tạo & Tải tệp</span>
          </div>
          <div className="intake-step-divider" />
          <div className={`intake-step-item ${!isDone ? 'active' : 'completed'}`}>
            <span className="intake-step-num">{isDone ? '✓' : '2'}</span>
            <span>Bàn dựng & Kiểm duyệt</span>
          </div>
          <div className="intake-step-divider" />
          <div className={`intake-step-item ${isDone ? 'completed' : ''}`}>
            <span className="intake-step-num">{isDone ? '✓' : '3'}</span>
            <span>Đồng bộ Radar Core</span>
          </div>
        </div>
      </div>

      {/* KPI Ribbon */}
      <div className="intake-metrics-ribbon">
        <div className="intake-metric-card">
          <div className="intake-metric-icon" style={{ background: 'rgba(37, 99, 235, 0.1)', color: '#2563eb' }}>
            📋
          </div>
          <div className="intake-metric-info">
            <span className="intake-metric-val">{batch.row_count}</span>
            <span className="intake-metric-lbl">Tổng ứng viên</span>
          </div>
        </div>

        <div className="intake-metric-card">
          <div className="intake-metric-icon" style={{ background: 'rgba(16, 185, 129, 0.1)', color: '#059669' }}>
            🟢
          </div>
          <div className="intake-metric-info">
            <span className="intake-metric-val" style={{ color: '#059669' }}>{batch.valid_count}</span>
            <span className="intake-metric-lbl">Hợp lệ (Mới)</span>
          </div>
        </div>

        <div className="intake-metric-card">
          <div className="intake-metric-icon" style={{ background: 'rgba(245, 158, 11, 0.1)', color: '#d97706' }}>
            🟠
          </div>
          <div className="intake-metric-info">
            <span className="intake-metric-val" style={{ color: '#d97706' }}>{batch.duplicate_count}</span>
            <span className="intake-metric-lbl">Trùng lặp</span>
          </div>
        </div>

        <div className="intake-metric-card">
          <div className="intake-metric-icon" style={{ background: 'rgba(239, 68, 68, 0.1)', color: '#dc2626' }}>
            🔴
          </div>
          <div className="intake-metric-info">
            <span className="intake-metric-val" style={{ color: '#dc2626' }}>{batch.invalid_count}</span>
            <span className="intake-metric-lbl">Lỗi định danh</span>
          </div>
        </div>

        <div className="intake-metric-card">
          <div className="intake-metric-icon" style={{ background: 'rgba(107, 114, 128, 0.1)', color: '#6b7280' }}>
            ⚪
          </div>
          <div className="intake-metric-info">
            <span className="intake-metric-val">{rows.filter((r) => r.validation_status === 'skipped').length}</span>
            <span className="intake-metric-lbl">Đã bỏ qua</span>
          </div>
        </div>

        <div className="intake-metric-card">
          <div className="intake-metric-icon" style={{ background: 'rgba(37, 99, 235, 0.1)', color: '#2563eb' }}>
            🔵
          </div>
          <div className="intake-metric-info">
            <span className="intake-metric-val" style={{ color: '#2563eb' }}>{batch.committed_count}</span>
            <span className="intake-metric-lbl">Đã ghi thành công</span>
          </div>
        </div>
      </div>

      {notice && <IntakeNotice notice={notice} onClose={() => setNotice(null)} />}

      {/* CV Attachment Drop bar for draft */}
      {!isDone && (
        <div className="intake-card" style={{ padding: '14px 20px', gap: '12px' }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: '12px' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
              <div style={{ width: '32px', height: '32px', borderRadius: '8px', background: 'rgba(124, 58, 237, 0.1)', color: '#7c3aed', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                <IconSparkles />
              </div>
              <div>
                <span style={{ fontSize: '13.5px', fontWeight: 600, color: 'var(--text)' }}>
                  {batch.kind === 'excel' ? 'Đính kèm tệp CV cho các ứng viên trong lô' : 'Thêm tệp CV mới vào lô'}
                </span>
                <p className="muted" style={{ margin: 0, fontSize: '12px' }}>
                  {batch.kind === 'excel'
                    ? 'Tự động ghép file CV ↔ ứng viên theo tên tệp hoặc email'
                    : 'AI bóc tách văn bản và tạo thành các dòng ứng viên mới'}
                </p>
              </div>
            </div>

            <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
              <input
                ref={cvRef}
                type="file"
                multiple
                accept=".pdf,.doc,.docx,.txt"
                style={{ display: 'none' }}
                onChange={(e) => {
                  const files = Array.from(e.target.files ?? [])
                  if (files.length) uploadCvs.mutate(files)
                  if (cvRef.current) cvRef.current.value = ''
                }}
              />
              <button
                type="button"
                className="btn btn-sm btn-secondary"
                disabled={uploadCvs.isPending}
                onClick={() => cvRef.current?.click()}
                style={{ display: 'inline-flex', alignItems: 'center', gap: '6px' }}
              >
                <IconUploadCloud />
                <span>{uploadCvs.isPending ? 'Đang phân tích CV...' : 'Tải lên nhiều CV (.pdf, .doc, .docx)'}</span>
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Staging Data Grid Section */}
      <div className="intake-card" style={{ gap: '16px' }}>
        <div className="intake-staging-header">
          <div className="intake-filter-chips">
            <button
              type="button"
              className={`intake-chip ${statusFilter === 'all' ? 'active' : ''}`}
              onClick={() => setStatusFilter('all')}
            >
              <span>Tất cả</span>
              <span className="intake-chip-count">{rows.length}</span>
            </button>
            <button
              type="button"
              className={`intake-chip ${statusFilter === 'valid' ? 'active' : ''}`}
              onClick={() => setStatusFilter('valid')}
            >
              <span>🟢 Hợp lệ</span>
              <span className="intake-chip-count">{batch.valid_count}</span>
            </button>
            <button
              type="button"
              className={`intake-chip ${statusFilter === 'duplicate' ? 'active' : ''}`}
              onClick={() => setStatusFilter('duplicate')}
            >
              <span>🟠 Trùng lặp</span>
              <span className="intake-chip-count">{batch.duplicate_count}</span>
            </button>
            <button
              type="button"
              className={`intake-chip ${statusFilter === 'invalid' ? 'active' : ''}`}
              onClick={() => setStatusFilter('invalid')}
            >
              <span>🔴 Lỗi định danh</span>
              <span className="intake-chip-count">{batch.invalid_count}</span>
            </button>
            <button
              type="button"
              className={`intake-chip ${statusFilter === 'skipped' ? 'active' : ''}`}
              onClick={() => setStatusFilter('skipped')}
            >
              <span>⚪ Bỏ qua</span>
              <span className="intake-chip-count">{rows.filter((r) => r.validation_status === 'skipped').length}</span>
            </button>
            {batch.committed_count > 0 && (
              <button
                type="button"
                className={`intake-chip ${statusFilter === 'committed' ? 'active' : ''}`}
                onClick={() => setStatusFilter('committed')}
              >
                <span>🔵 Đã ghi</span>
                <span className="intake-chip-count">{batch.committed_count}</span>
              </button>
            )}
          </div>

          <div className="wf-search-box" style={{ minWidth: '240px' }}>
            <IconSearch />
            <input
              type="text"
              placeholder="Tìm theo tên, email, sđt, vị trí..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
            />
          </div>
        </div>

        {/* Data Grid Table */}
        <div className="wf-table-container">
          <table className="wf-table">
            <thead>
              <tr>
                <th style={{ width: '48px', textAlign: 'center' }}>#</th>
                <th style={{ width: '130px' }}>Trạng thái</th>
                {EDITABLE.map((c) => (
                  <th key={c.key}>{c.label}</th>
                ))}
                <th style={{ width: '150px' }}>File CV</th>
                <th style={{ minWidth: '160px' }}>Ghi chú / Cảnh báo</th>
                <th style={{ width: '90px', textAlign: 'right' }}>Thao tác</th>
              </tr>
            </thead>
            <tbody>
              {filteredRows.map((row) => (
                <RowItem
                  key={row.id}
                  row={row}
                  readOnly={isDone}
                  onInspect={() => setInspectRow(row)}
                  onEdit={(key, value) => patchRow.mutate({ rowId: row.id, patch: { fields: { [key]: value } } })}
                  onToggleSkip={() =>
                    patchRow.mutate({
                      rowId: row.id,
                      patch: { skip: row.validation_status !== 'skipped' },
                    })
                  }
                />
              ))}

              {filteredRows.length === 0 && (
                <tr>
                  <td colSpan={10} style={{ textAlign: 'center', padding: '36px 16px', color: 'var(--muted)' }}>
                    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '8px' }}>
                      <span style={{ fontSize: '24px' }}>🔍</span>
                      <span style={{ fontSize: '13.5px', fontWeight: 500 }}>
                        {rows.length === 0
                          ? 'Chưa có dữ liệu nào trong bàn dựng. Thả CV ở trên để bắt đầu.'
                          : 'Không tìm thấy ứng viên nào phù hợp với bộ lọc.'}
                      </span>
                    </div>
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* Commit Action Bar */}
      <div className="intake-commit-bar">
        {!isDone ? (
          <>
            <div className="intake-strategy-selector">
              <label style={{ fontWeight: 600, color: 'var(--text)' }}>
                Chiến lược xử lý trùng:
              </label>
              <select
                value={dedupStrategy}
                onChange={(e) => setDedupStrategy(e.target.value as 'skip' | 'update')}
                className="oh-select"
                style={{ fontSize: '13px', padding: '6px 12px' }}
              >
                <option value="skip">Bỏ qua hồ sơ trùng (Chỉ nạp ứng viên mới)</option>
                <option value="update">Cập nhật hồ sơ đã có (Smart Merge)</option>
              </select>
              <span className="muted" style={{ fontSize: '12px' }}>
                (Dữ liệu đi qua Edge <code>hub-manual</code>, bảo toàn dữ liệu do Recruiter xác thực)
              </span>
            </div>

            <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
              <button
                type="button"
                className="btn btn-ghost"
                style={{ color: '#dc2626' }}
                disabled={discard.isPending}
                onClick={() => {
                  if (window.confirm('Bạn có chắc chắn muốn xoá lô nháp này và các CV tạm?')) {
                    discard.mutate()
                  }
                }}
              >
                <IconTrash />
                <span>Huỷ lô</span>
              </button>

              <button
                type="button"
                className="btn btn-brand btn-primary"
                disabled={commit.isPending || committable === 0}
                onClick={() => commit.mutate()}
                style={{ display: 'inline-flex', alignItems: 'center', gap: '8px', padding: '8px 20px' }}
              >
                <IconCheckCircle />
                <span>
                  {commit.isPending
                    ? 'Đang đồng bộ vào Radar Core...'
                    : `Ghi ${committable} ứng viên vào hệ thống`}
                </span>
              </button>
            </div>
          </>
        ) : (
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', width: '100%' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '10px', color: '#059669' }}>
              <IconCheckCircle />
              <span style={{ fontWeight: 600, fontSize: '14px' }}>
                Lô đã được ghi nhận hoàn tất vào kho Talent Radar.
              </span>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
              <a href="/talent" className="btn btn-secondary btn-sm" style={{ textDecoration: 'none' }}>
                Mở Talent Hub
              </a>
              <button
                type="button"
                className="btn btn-brand btn-primary btn-sm"
                onClick={() => {
                  setBatchId(null)
                  setInspectRow(null)
                }}
              >
                + Nhập lô mới
              </button>
            </div>
          </div>
        )}
      </div>

      {/* Row Detail Side Drawer */}
      {inspectRow && (
        <RowDetailDrawer
          row={inspectRow}
          readOnly={isDone}
          onClose={() => setInspectRow(null)}
          onEdit={(key, value) => patchRow.mutate({ rowId: inspectRow.id, patch: { fields: { [key]: value } } })}
        />
      )}
    </div>
  )
}

// --- SUB-COMPONENTS ---

function RowItem({
  row,
  readOnly,
  onInspect,
  onEdit,
  onToggleSkip,
}: {
  row: IntakeRow
  readOnly: boolean
  onInspect: () => void
  onEdit: (key: string, value: string) => void
  onToggleSkip: () => void
}) {
  const errorEntries = Object.entries(row.errors ?? {})
  const hasError = errorEntries.length > 0
  const isSkipped = row.validation_status === 'skipped'

  return (
    <tr style={{ opacity: isSkipped ? 0.6 : 1 }}>
      <td style={{ textAlign: 'center', color: 'var(--muted)', fontSize: '12px' }}>
        {row.row_number}
      </td>
      <td>
        <StatusChip status={row.validation_status} />
        {row.person_id && (
          <div style={{ marginTop: '2px' }}>
            <a
              href={`/person/${row.person_id}`}
              target="_blank"
              rel="noreferrer"
              style={{ fontSize: '11.5px', color: '#2563eb', display: 'inline-flex', alignItems: 'center', gap: '3px' }}
            >
              <span>Xem hồ sơ</span>
              <IconExternalLink />
            </a>
          </div>
        )}
      </td>

      {EDITABLE.map((c) => (
        <td key={c.key} style={{ padding: '4px 6px' }}>
          {readOnly ? (
            <span style={{ fontSize: '13px', color: 'var(--text)' }}>
              {row.fields?.[c.key] || '—'}
            </span>
          ) : (
            <input
              defaultValue={row.fields?.[c.key] ?? ''}
              className="intake-cell-input"
              placeholder={c.placeholder}
              onBlur={(e) => {
                const v = e.target.value.trim()
                if (v !== (row.fields?.[c.key] ?? '')) {
                  onEdit(c.key, v)
                }
              }}
            />
          )}
        </td>
      ))}

      <td>
        {row.cv_filename ? (
          <span
            style={{
              fontSize: '12px',
              display: 'inline-flex',
              alignItems: 'center',
              gap: '4px',
              color: 'var(--text)',
              background: 'var(--surface-raised)',
              padding: '2px 6px',
              borderRadius: '6px',
              border: '1px solid var(--border)',
              maxWidth: '140px',
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              whiteSpace: 'nowrap',
            }}
            title={row.cv_filename}
          >
            {row.ai_extracted && <IconSparkles />}
            <span style={{ overflow: 'hidden', textOverflow: 'ellipsis' }}>{row.cv_filename}</span>
          </span>
        ) : (
          <span className="muted" style={{ fontSize: '12px' }}>—</span>
        )}
      </td>

      <td>
        {hasError ? (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '2px' }}>
            {errorEntries.map(([k, msg]) => (
              <span
                key={k}
                style={{
                  fontSize: '11.5px',
                  color: k === 'duplicate' ? '#d97706' : '#dc2626',
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: '4px',
                }}
              >
                <span>•</span>
                <span>{msg}</span>
              </span>
            ))}
          </div>
        ) : (
          <span className="muted" style={{ fontSize: '12px' }}>Ổn định</span>
        )}
      </td>

      <td style={{ textAlign: 'right' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'flex-end', gap: '6px' }}>
          <button
            type="button"
            className="btn btn-sm btn-ghost"
            style={{ padding: '4px 8px', fontSize: '12px' }}
            onClick={onInspect}
            title="Xem chi tiết dòng"
          >
            <IconEye />
          </button>
          {!readOnly && (
            <button
              type="button"
              className="btn btn-sm btn-ghost"
              style={{
                padding: '4px 8px',
                fontSize: '11.5px',
                color: isSkipped ? '#059669' : 'var(--muted)',
              }}
              onClick={onToggleSkip}
              title={isSkipped ? 'Khôi phục dòng' : 'Bỏ qua dòng này khi commit'}
            >
              {isSkipped ? 'Khôi phục' : 'Bỏ qua'}
            </button>
          )}
        </div>
      </td>
    </tr>
  )
}

function RowDetailDrawer({
  row,
  readOnly,
  onClose,
  onEdit,
}: {
  row: IntakeRow
  readOnly: boolean
  onClose: () => void
  onEdit: (key: string, value: string) => void
}) {
  const [localFields, setLocalFields] = useState<Record<string, string>>(row.fields || {})

  return (
    <div className="intake-drawer-overlay" onClick={onClose}>
      <div className="intake-drawer" onClick={(e) => e.stopPropagation()}>
        <div className="intake-drawer-head">
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <h3 style={{ margin: 0, fontSize: '16px', fontWeight: 700, color: 'var(--text)' }}>
                Chi tiết dòng #{row.row_number}
              </h3>
              <StatusChip status={row.validation_status} />
            </div>
            <p className="muted" style={{ margin: '2px 0 0', fontSize: '12px' }}>
              Mã định danh: <code>{row.entity_key || 'Chưa định danh'}</code>
            </p>
          </div>
          <button type="button" className="btn btn-sm btn-ghost" onClick={onClose}>
            <IconX />
          </button>
        </div>

        <div className="intake-drawer-body">
          {/* Duplicate Match Warning */}
          {row.matched_person_id && (
            <div
              style={{
                padding: '12px 16px',
                borderRadius: '10px',
                background: 'rgba(245, 158, 11, 0.08)',
                border: '1px solid rgba(245, 158, 11, 0.25)',
                display: 'flex',
                alignItems: 'flex-start',
                gap: '10px',
              }}
            >
              <div style={{ color: '#d97706', marginTop: '2px' }}>
                <IconAlertCircle />
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                <span style={{ fontSize: '13px', fontWeight: 600, color: '#d97706' }}>
                  Khớp với hồ sơ đã có trong Radar Core
                </span>
                <span style={{ fontSize: '12.5px', color: 'var(--text)' }}>
                  Họ tên hệ thống: <strong>{row.matched_person_name || 'Ứng viên'}</strong> (ID: #{row.matched_person_id})
                </span>
                <a
                  href={`/person/${row.matched_person_id}`}
                  target="_blank"
                  rel="noreferrer"
                  style={{ fontSize: '12px', color: '#2563eb', display: 'inline-flex', alignItems: 'center', gap: '4px', marginTop: '2px' }}
                >
                  <span>Mở hồ sơ Person360 trong tab mới</span>
                  <IconExternalLink />
                </a>
              </div>
            </div>
          )}

          {/* Form Fields */}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr', gap: '14px' }}>
            {EDITABLE.map((c) => (
              <div key={c.key} className="intake-detail-field">
                <label className="intake-detail-label">{c.label}</label>
                {readOnly ? (
                  <div className="intake-detail-value">{localFields[c.key] || '—'}</div>
                ) : (
                  <input
                    type="text"
                    className="edge-create-input"
                    value={localFields[c.key] || ''}
                    onChange={(e) => setLocalFields({ ...localFields, [c.key]: e.target.value })}
                    onBlur={() => {
                      if (localFields[c.key] !== (row.fields?.[c.key] ?? '')) {
                        onEdit(c.key, localFields[c.key])
                      }
                    }}
                  />
                )}
              </div>
            ))}

            {/* Other Fields if available */}
            {Object.entries(row.fields || {})
              .filter(([k]) => !EDITABLE.some((c) => c.key === k))
              .map(([k, v]) => (
                <div key={k} className="intake-detail-field">
                  <label className="intake-detail-label">{k}</label>
                  <div className="intake-detail-value">{v || '—'}</div>
                </div>
              ))}
          </div>

          {/* CV Attachment Audit */}
          {row.cv_filename && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
              <span className="intake-detail-label">File CV đính kèm</span>
              <div
                style={{
                  padding: '10px 14px',
                  borderRadius: '8px',
                  background: 'var(--surface-raised)',
                  border: '1px solid var(--border)',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  fontSize: '13px',
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                  <IconFileText />
                  <span>{row.cv_filename}</span>
                </div>
                {row.ai_extracted && (
                  <span className="tag" style={{ background: 'rgba(124, 58, 237, 0.12)', color: '#7c3aed', fontWeight: 600 }}>
                    AI Parsed
                  </span>
                )}
              </div>
            </div>
          )}

          {/* Errors section */}
          {row.errors && Object.keys(row.errors).length > 0 && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
              <span className="intake-detail-label" style={{ color: '#dc2626' }}>
                Chi tiết cảnh báo / Lỗi
              </span>
              <div
                style={{
                  padding: '10px 14px',
                  borderRadius: '8px',
                  background: 'rgba(239, 68, 68, 0.06)',
                  border: '1px solid rgba(239, 68, 68, 0.2)',
                  fontSize: '12.5px',
                  color: '#dc2626',
                  display: 'flex',
                  flexDirection: 'column',
                  gap: '4px',
                }}
              >
                {Object.entries(row.errors).map(([k, msg]) => (
                  <div key={k}>
                    <strong>{k}:</strong> {msg}
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>

        <div className="intake-drawer-footer">
          <button type="button" className="btn btn-secondary btn-sm" onClick={onClose}>
            Đóng
          </button>
        </div>
      </div>
    </div>
  )
}

function IntakeNotice({
  notice,
  onClose,
}: {
  notice: { text: string; type?: 'info' | 'error' | 'success' }
  onClose: () => void
}) {
  const isError = notice.type === 'error'
  const isSuccess = notice.type === 'success'

  return (
    <div
      style={{
        padding: '10px 16px',
        borderRadius: '10px',
        background: isError
          ? 'rgba(239, 68, 68, 0.1)'
          : isSuccess
          ? 'rgba(16, 185, 129, 0.1)'
          : 'var(--surface-raised)',
        border: `1px solid ${
          isError ? 'rgba(239, 68, 68, 0.3)' : isSuccess ? 'rgba(16, 185, 129, 0.3)' : 'var(--border)'
        }`,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        fontSize: '13px',
        color: isError ? '#dc2626' : isSuccess ? '#059669' : 'var(--text)',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
        <span>{isError ? '⚠️' : isSuccess ? '✓' : 'ℹ️'}</span>
        <span>{notice.text}</span>
      </div>
      <button
        type="button"
        className="btn btn-sm btn-ghost"
        style={{ padding: '2px 6px', color: 'inherit' }}
        onClick={onClose}
      >
        <IconX />
      </button>
    </div>
  )
}

function IntakeHistorySection({
  history,
  onOpen,
}: {
  history: IntakeBatch[]
  onOpen: (id: number) => void
}) {
  if (history.length === 0) return null

  return (
    <div className="intake-card" style={{ gap: '14px' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <h3 style={{ margin: 0, fontSize: '15px', fontWeight: 700, color: 'var(--text)' }}>
          Các lô nhập liệu gần đây ({history.length})
        </h3>
      </div>

      <div className="wf-table-container">
        <table className="wf-table">
          <thead>
            <tr>
              <th style={{ width: '60px' }}>Lô #</th>
              <th>Loại hình</th>
              <th>Nguồn thu nhận</th>
              <th style={{ textAlign: 'center' }}>Tổng số</th>
              <th style={{ textAlign: 'center' }}>Đã ghi</th>
              <th>Trạng thái</th>
              <th>Người tạo</th>
              <th>Thời gian</th>
              <th style={{ textAlign: 'right' }} />
            </tr>
          </thead>
          <tbody>
            {history.slice(0, 15).map((b) => {
              const isDraft = b.status === 'draft'
              return (
                <tr key={b.id}>
                  <td>
                    <strong>#{b.id}</strong>
                  </td>
                  <td>
                    <span style={{ display: 'inline-flex', alignItems: 'center', gap: '6px', fontSize: '13px' }}>
                      {b.kind === 'excel' ? <IconFileSpreadsheet /> : <IconSparkles />}
                      <span>{b.kind === 'excel' ? 'Excel / CSV' : 'Nhiều CV'}</span>
                    </span>
                  </td>
                  <td>
                    {b.source_label ? (
                      <span className="source-badge file_import">{b.source_label}</span>
                    ) : (
                      <span className="muted">—</span>
                    )}
                  </td>
                  <td style={{ textAlign: 'center', fontWeight: 600 }}>{b.row_count}</td>
                  <td style={{ textAlign: 'center', color: '#059669', fontWeight: 600 }}>{b.committed_count}</td>
                  <td>
                    <span
                      className="tag"
                      style={{
                        background: isDraft ? 'rgba(37,99,235,0.12)' : 'rgba(16,185,129,0.12)',
                        color: isDraft ? '#2563eb' : '#059669',
                        fontWeight: 600,
                        fontSize: '11.5px',
                      }}
                    >
                      {isDraft ? 'Nháp (Đang xử lý)' : 'Hoàn tất'}
                    </span>
                  </td>
                  <td style={{ fontSize: '12.5px', color: 'var(--muted)' }}>{b.created_by_name || 'Hệ thống'}</td>
                  <td style={{ fontSize: '12px', color: 'var(--muted)' }}>
                    {new Date(b.created_at).toLocaleString('vi-VN')}
                  </td>
                  <td style={{ textAlign: 'right' }}>
                    <button
                      type="button"
                      className={`btn btn-sm ${isDraft ? 'btn-primary btn-brand' : 'btn-secondary'}`}
                      style={{ fontSize: '12px', padding: '4px 12px' }}
                      onClick={() => onOpen(b.id)}
                    >
                      {isDraft ? 'Tiếp tục xử lý' : 'Xem chi tiết'}
                    </button>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}
