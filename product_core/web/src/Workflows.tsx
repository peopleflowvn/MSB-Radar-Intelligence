import React, { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, ApiError, WorkflowStage } from './api'

// Preset bảng màu chuẩn MSB Radar & Design System
const COLOR_PRESETS = [
  { label: 'Đỏ MSB', value: '#d81f2a' },
  { label: 'Cam Năng Động', value: '#ea580c' },
  { label: 'Vàng Cảnh Báo', value: '#d97706' },
  { label: 'Xanh Lục (Thành công)', value: '#10b981' },
  { label: 'Xanh Mòng Két (Teal)', value: '#0d9488' },
  { label: 'Xanh Dương MSB', value: '#2563eb' },
  { label: 'Tím Hoàng Gia', value: '#7c3aed' },
  { label: 'Hồng Fuchsia', value: '#db2777' },
  { label: 'Xám Slate', value: '#64748b' },
]

// Preset SLA thông dụng
const SLA_PRESETS = [
  { label: '12 giờ', value: 12 },
  { label: '24 giờ', value: 24 },
  { label: '48 giờ', value: 48 },
  { label: '72 giờ', value: 72 },
  { label: 'Không đặt SLA', value: null },
]

// --- SVG Icons ---
function IconFlow() {
  return (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <rect x="3" y="3" width="7" height="7" rx="1" />
      <rect x="14" y="3" width="7" height="7" rx="1" />
      <rect x="14" y="14" width="7" height="7" rx="1" />
      <rect x="3" y="14" width="7" height="7" rx="1" />
      <path d="M10 6.5h4M17.5 10v4M14 17.5H10M6.5 14V10" />
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

function IconCards() {
  return (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <rect x="3" y="3" width="7" height="7" rx="1" />
      <rect x="14" y="3" width="7" height="7" rx="1" />
      <rect x="3" y="14" width="7" height="7" rx="1" />
      <rect x="14" y="14" width="7" height="7" rx="1" />
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

function IconArrowRight() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <line x1="5" y1="12" x2="19" y2="12" />
      <polyline points="12 5 19 12 12 19" />
    </svg>
  )
}

function IconCheck() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
      <polyline points="20 6 9 17 4 12" />
    </svg>
  )
}

function IconClock() {
  return (
    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="10" />
      <polyline points="12 6 12 12 16 14" />
    </svg>
  )
}

function IconLock() {
  return (
    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <rect x="3" y="11" width="18" height="11" rx="2" ry="2" />
      <path d="M7 11V7a5 5 0 0 1 10 0v4" />
    </svg>
  )
}

function IconFlag() {
  return (
    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M4 15s1-1 4-1 5 2 8 2 4-1 4-1V3s-1 1-4 1-5-2-8-2-4 1-4 1z" />
      <line x1="4" y1="22" x2="4" y2="15" />
    </svg>
  )
}

function IconPipelineSetting() {
  return (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <line x1="4" y1="21" x2="4" y2="14" />
      <line x1="4" y1="10" x2="4" y2="3" />
      <line x1="12" y1="21" x2="12" y2="12" />
      <line x1="12" y1="8" x2="12" y2="3" />
      <line x1="20" y1="21" x2="20" y2="16" />
      <line x1="20" y1="12" x2="20" y2="3" />
      <line x1="1" y1="14" x2="7" y2="14" />
      <line x1="9" y1="8" x2="15" y2="8" />
      <line x1="17" y1="16" x2="23" y2="16" />
    </svg>
  )
}

function IconEdit() {
  return (
    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7" />
      <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z" />
    </svg>
  )
}

// --- Component Chọn màu thông minh ---
function ColorPickerPopover({
  color,
  onChange,
}: {
  color: string
  onChange: (val: string) => void
}) {
  const [isOpen, setIsOpen] = useState(false)
  return (
    <div style={{ position: 'relative', display: 'inline-block' }}>
      <div
        className="wf-color-picker-trigger"
        style={{ backgroundColor: color || '#64748b' }}
        title="Đổi màu sắc bước"
        onClick={() => setIsOpen(!isOpen)}
      />
      {isOpen && (
        <>
          <div
            style={{ position: 'fixed', inset: 0, zIndex: 100 }}
            onClick={() => setIsOpen(false)}
          />
          <div
            style={{
              position: 'absolute',
              top: '100%',
              left: 0,
              marginTop: '6px',
              background: 'var(--surface)',
              border: '1px solid var(--border)',
              borderRadius: '10px',
              padding: '10px',
              boxShadow: '0 8px 24px rgba(0,0,0,0.15)',
              zIndex: 101,
              width: '180px',
            }}
          >
            <div style={{ fontSize: '11px', fontWeight: 600, color: 'var(--muted)', marginBottom: '6px' }}>
              Màu tiêu chuẩn
            </div>
            <div className="wf-color-presets">
              {COLOR_PRESETS.map((preset) => (
                <button
                  key={preset.value}
                  type="button"
                  className={`wf-color-swatch-btn ${color === preset.value ? 'selected' : ''}`}
                  style={{ backgroundColor: preset.value }}
                  title={preset.label}
                  onClick={() => {
                    onChange(preset.value)
                    setIsOpen(false)
                  }}
                />
              ))}
            </div>
            <div style={{ marginTop: '10px', display: 'flex', alignItems: 'center', gap: '6px' }}>
              <input
                type="color"
                value={color || '#64748b'}
                onChange={(e) => onChange(e.target.value)}
                style={{ width: '28px', height: '28px', padding: 0, border: 'none', background: 'transparent', cursor: 'pointer' }}
              />
              <span style={{ fontSize: '11px', color: 'var(--muted)', fontFamily: 'monospace' }}>
                {color || '#64748b'}
              </span>
            </div>
          </div>
        </>
      )}
    </div>
  )
}

// --- Component Chọn Nhiều Bước Tiếp Theo (Allowed Next Stages) ---
function AllowedNextPicker({
  currentAllowed,
  allStages,
  currentCode,
  onChange,
}: {
  currentAllowed: string[]
  allStages: WorkflowStage[]
  currentCode: string
  onChange: (val: string[]) => void
}) {
  const [isOpen, setIsOpen] = useState(false)
  const availableStages = allStages.filter((s) => s.code !== currentCode)

  const isAllAllowed = currentAllowed.length === 0

  function toggleCode(code: string) {
    if (currentAllowed.includes(code)) {
      onChange(currentAllowed.filter((c) => c !== code))
    } else {
      onChange([...currentAllowed, code])
    }
  }

  return (
    <div style={{ position: 'relative', display: 'inline-block' }}>
      <div className="wf-tags-trigger" onClick={() => setIsOpen(!isOpen)}>
        {isAllAllowed ? (
          <span className="wf-tags-empty">Tất cả các bước (Chuyển tự do)</span>
        ) : (
          currentAllowed.map((code) => {
            const matched = allStages.find((s) => s.code === code)
            return (
              <span key={code} className="wf-next-pill">
                <span
                  className="wf-next-dot"
                  style={{ backgroundColor: matched?.color || '#64748b' }}
                />
                {matched?.label || code}
              </span>
            )
          })
        )}
      </div>

      {isOpen && (
        <>
          <div
            style={{ position: 'fixed', inset: 0, zIndex: 100 }}
            onClick={() => setIsOpen(false)}
          />
          <div
            style={{
              position: 'absolute',
              top: '100%',
              left: 0,
              marginTop: '6px',
              background: 'var(--surface)',
              border: '1px solid var(--border)',
              borderRadius: '12px',
              padding: '12px',
              boxShadow: '0 10px 30px rgba(0,0,0,0.18)',
              zIndex: 101,
              width: '260px',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '8px' }}>
              <span style={{ fontSize: '12px', fontWeight: 600, color: 'var(--text)' }}>
                Bước được phép chuyển tới
              </span>
              <button
                type="button"
                className="link small"
                onClick={() => onChange([])}
              >
                Chuyển tự do
              </button>
            </div>
            <div className="wf-multi-select-list">
              {availableStages.map((stage) => {
                const isChecked = currentAllowed.includes(stage.code)
                return (
                  <label key={stage.code} className="wf-multi-select-item">
                    <input
                      type="checkbox"
                      checked={isChecked}
                      onChange={() => toggleCode(stage.code)}
                    />
                    <span
                      className="wf-next-dot"
                      style={{ backgroundColor: stage.color || '#64748b' }}
                    />
                    <span style={{ flex: 1, color: 'var(--text)' }}>{stage.label}</span>
                    <span style={{ fontSize: '11px', color: 'var(--muted)', fontFamily: 'monospace' }}>
                      {stage.code}
                    </span>
                  </label>
                )
              })}
            </div>
            <div style={{ marginTop: '8px', fontSize: '11px', color: 'var(--muted)' }}>
              *Để trống để cho phép nhân viên chuyển sang bất kỳ bước nào.
            </div>
          </div>
        </>
      )}
    </div>
  )
}

// --- Component Hộp thoại Chỉnh sửa Chi tiết Stage (Modal) ---
function StageDetailModal({
  stage,
  allStages,
  onClose,
  onSave,
  isSaving,
}: {
  stage: WorkflowStage
  allStages: WorkflowStage[]
  onClose: () => void
  onSave: (patch: Partial<WorkflowStage>) => void
  isSaving: boolean
}) {
  const [draft, setDraft] = useState<WorkflowStage>({ ...stage })

  const setField = <K extends keyof WorkflowStage>(key: K, value: WorkflowStage[K]) =>
    setDraft((curr) => ({ ...curr, [key]: value }))

  return (
    <div className="wf-modal-overlay" onClick={onClose}>
      <div className="wf-modal-box" onClick={(e) => e.stopPropagation()}>
        <div className="wf-modal-header">
          <h3 className="wf-modal-title">
            <span
              style={{
                width: '12px',
                height: '12px',
                borderRadius: '50%',
                backgroundColor: draft.color || '#64748b',
              }}
            />
            Cấu hình Chi tiết Bước: {stage.label}
          </h3>
          <button className="wf-modal-close" onClick={onClose}>
            ×
          </button>
        </div>

        <div className="wf-modal-body">
          {/* Tên hiển thị & Mã định danh */}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '14px' }}>
            <div className="wf-form-group">
              <label className="wf-form-label">Tên hiển thị bước</label>
              <input
                className="wf-input-text"
                value={draft.label}
                onChange={(e) => setField('label', e.target.value)}
                placeholder="VD: Đang liên hệ"
              />
            </div>
            <div className="wf-form-group">
              <label className="wf-form-label">Mã hệ thống (Code)</label>
              <input
                className="wf-input-text"
                value={draft.code}
                disabled
                style={{ opacity: 0.7, cursor: 'not-allowed', fontFamily: 'monospace' }}
              />
              <span className="wf-form-hint">Mã định danh duy nhất theo domain</span>
            </div>
          </div>

          {/* Màu nhận diện */}
          <div className="wf-form-group">
            <label className="wf-form-label">Màu sắc nhận diện giai đoạn</label>
            <div className="wf-color-presets">
              {COLOR_PRESETS.map((preset) => (
                <button
                  key={preset.value}
                  type="button"
                  className={`wf-color-swatch-btn ${draft.color === preset.value ? 'selected' : ''}`}
                  style={{ backgroundColor: preset.value }}
                  title={preset.label}
                  onClick={() => setField('color', preset.value)}
                />
              ))}
              <input
                type="color"
                value={draft.color || '#64748b'}
                onChange={(e) => setField('color', e.target.value)}
                style={{ width: '26px', height: '26px', border: 'none', cursor: 'pointer', background: 'transparent' }}
              />
            </div>
          </div>

          {/* Thứ tự & Cam kết SLA */}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1.5fr', gap: '14px' }}>
            <div className="wf-form-group">
              <label className="wf-form-label">Thứ tự hiển thị (Position)</label>
              <input
                type="number"
                min={0}
                className="wf-input-text"
                value={draft.position}
                onChange={(e) => setField('position', Number(e.target.value))}
              />
            </div>

            <div className="wf-form-group">
              <label className="wf-form-label">Cam kết SLA xử lý (Giờ)</label>
              <div style={{ display: 'flex', gap: '6px', alignItems: 'center' }}>
                <input
                  type="number"
                  min={1}
                  placeholder="Không giới hạn"
                  className="wf-input-text"
                  value={draft.sla_hours ?? ''}
                  onChange={(e) => setField('sla_hours', e.target.value ? Number(e.target.value) : null)}
                />
              </div>
              <div style={{ display: 'flex', gap: '4px', marginTop: '6px', flexWrap: 'wrap' }}>
                {SLA_PRESETS.map((p) => (
                  <button
                    key={p.label}
                    type="button"
                    className="wf-filter-chip"
                    style={{ fontSize: '11px', padding: '3px 8px' }}
                    onClick={() => setField('sla_hours', p.value)}
                  >
                    {p.label}
                  </button>
                ))}
              </div>
            </div>
          </div>

          {/* Bước tiếp theo hợp lệ */}
          <div className="wf-form-group">
            <label className="wf-form-label">
              <span>Các bước tiếp theo hợp lệ (Allowed Transitions)</span>
              <button
                type="button"
                className="link small"
                onClick={() => setField('allowed_next', [])}
              >
                Cho phép chuyển tự do
              </button>
            </label>
            <div className="wf-multi-select-list" style={{ maxHeight: '140px' }}>
              {allStages
                .filter((s) => s.code !== draft.code)
                .map((s) => {
                  const isChecked = (draft.allowed_next ?? []).includes(s.code)
                  return (
                    <label key={s.code} className="wf-multi-select-item">
                      <input
                        type="checkbox"
                        checked={isChecked}
                        onChange={() => {
                          const current = draft.allowed_next ?? []
                          if (isChecked) {
                            setField('allowed_next', current.filter((c) => c !== s.code))
                          } else {
                            setField('allowed_next', [...current, s.code])
                          }
                        }}
                      />
                      <span className="wf-next-dot" style={{ backgroundColor: s.color || '#64748b' }} />
                      <span style={{ flex: 1, color: 'var(--text)' }}>{s.label}</span>
                      <span style={{ fontSize: '11px', color: 'var(--muted)', fontFamily: 'monospace' }}>
                        {s.code}
                      </span>
                    </label>
                  )
                })}
            </div>
            <span className="wf-form-hint">
              Để trống nếu cho phép người dùng chuyển tới bất kỳ bước nào trong quy trình.
            </span>
          </div>

          {/* Các thiết lập cờ quy tắc (Rules) */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: '10px', background: 'var(--surface-raised)', padding: '12px 14px', borderRadius: '10px' }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
              <div>
                <div style={{ fontSize: '13px', fontWeight: 600, color: 'var(--text)' }}>
                  Bắt buộc nhập lý do (Requires Reason)
                </div>
                <div style={{ fontSize: '11.5px', color: 'var(--muted)' }}>
                  Yêu cầu nhân viên chọn lý do khi chuyển vào bước này (VD: Thất bại, Hủy hồ sơ, Trả về).
                </div>
              </div>
              <label className="wf-switch">
                <input
                  type="checkbox"
                  checked={draft.requires_reason}
                  onChange={(e) => setField('requires_reason', e.target.checked)}
                />
                <span className="wf-slider" />
              </label>
            </div>

            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', borderTop: '1px solid var(--border)', paddingTop: '10px' }}>
              <div>
                <div style={{ fontSize: '13px', fontWeight: 600, color: 'var(--text)' }}>
                  Bước kết thúc quy trình (Terminal Stage)
                </div>
                <div style={{ fontSize: '11.5px', color: 'var(--muted)' }}>
                  Đánh dấu hồ sơ đã hoàn tất mục tiêu (Thành công hoặc Thất bại/Đóng hồ sơ).
                </div>
              </div>
              <label className="wf-switch">
                <input
                  type="checkbox"
                  checked={draft.is_terminal}
                  onChange={(e) => setField('is_terminal', e.target.checked)}
                />
                <span className="wf-slider" />
              </label>
            </div>

            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', borderTop: '1px solid var(--border)', paddingTop: '10px' }}>
              <div>
                <div style={{ fontSize: '13px', fontWeight: 600, color: 'var(--text)' }}>
                  Kích hoạt bước này (Active in Workflow)
                </div>
                <div style={{ fontSize: '11.5px', color: 'var(--muted)' }}>
                  Cho phép hiển thị và sử dụng bước này trên bảng Kanban và quy trình vận hành.
                </div>
              </div>
              <label className="wf-switch">
                <input
                  type="checkbox"
                  checked={draft.is_active}
                  onChange={(e) => setField('is_active', e.target.checked)}
                />
                <span className="wf-slider" />
              </label>
            </div>
          </div>
        </div>

        <div className="wf-modal-footer">
          <button type="button" className="btn-secondary" onClick={onClose}>
            Hủy bỏ
          </button>
          <button
            type="button"
            className="btn-primary"
            disabled={isSaving}
            onClick={() => onSave(draft)}
          >
            {isSaving ? 'Đang lưu…' : 'Lưu cấu hình'}
          </button>
        </div>
      </div>
    </div>
  )
}

// --- Component Hàng Bảng Cấu Hình Stage (StageRow) ---
function StageRow({
  stage,
  allStages,
  onSavePatch,
  onMoveOrder,
  onOpenModal,
  isSaving,
}: {
  stage: WorkflowStage
  allStages: WorkflowStage[]
  onSavePatch: (id: number, patch: Partial<WorkflowStage>) => Promise<void>
  onMoveOrder: (stage: WorkflowStage, direction: 'up' | 'down') => void
  onOpenModal: (stage: WorkflowStage) => void
  isSaving: boolean
}) {
  const [draft, setDraft] = useState<WorkflowStage>(stage)
  const [savedSuccess, setSavedSuccess] = useState(false)

  // Đồng bộ khi prop stage từ server thay đổi
  React.useEffect(() => {
    setDraft(stage)
  }, [stage])

  const isDirty =
    draft.label !== stage.label ||
    draft.color !== stage.color ||
    draft.position !== stage.position ||
    draft.sla_hours !== stage.sla_hours ||
    draft.requires_reason !== stage.requires_reason ||
    draft.is_terminal !== stage.is_terminal ||
    draft.is_active !== stage.is_active ||
    JSON.stringify(draft.allowed_next) !== JSON.stringify(stage.allowed_next)

  const setField = <K extends keyof WorkflowStage>(key: K, value: WorkflowStage[K]) =>
    setDraft((curr) => ({ ...curr, [key]: value }))

  async function handleSave() {
    await onSavePatch(stage.id, draft)
    setSavedSuccess(true)
    setTimeout(() => setSavedSuccess(false), 2000)
  }

  function handleRevert() {
    setDraft(stage)
  }

  return (
    <tr className={isDirty ? 'is-dirty' : ''}>
      {/* Position & Reorder */}
      <td>
        <div className="wf-pos-ctrl">
          <span className="wf-pos-num">{draft.position}</span>
          <div className="wf-pos-btn-group">
            <button
              type="button"
              className="wf-mini-btn"
              title="Đưa lên trên"
              onClick={() => onMoveOrder(stage, 'up')}
            >
              ▲
            </button>
            <button
              type="button"
              className="wf-mini-btn"
              title="Đưa xuống dưới"
              onClick={() => onMoveOrder(stage, 'down')}
            >
              ▼
            </button>
          </div>
        </div>
      </td>

      {/* Code */}
      <td>
        <span className="wf-node-code">{stage.code}</span>
      </td>

      {/* Color */}
      <td>
        <ColorPickerPopover
          color={draft.color}
          onChange={(c) => setField('color', c)}
        />
      </td>

      {/* Label */}
      <td>
        <input
          className="wf-input-text"
          value={draft.label}
          onChange={(e) => setField('label', e.target.value)}
          placeholder="Tên hiển thị"
        />
      </td>

      {/* SLA */}
      <td>
        <div className="wf-sla-input-wrapper">
          <input
            type="number"
            min={1}
            placeholder="-"
            className="wf-sla-input"
            value={draft.sla_hours ?? ''}
            onChange={(e) => setField('sla_hours', e.target.value ? Number(e.target.value) : null)}
          />
          <span style={{ fontSize: '11px', color: 'var(--muted)' }}>giờ</span>
        </div>
      </td>

      {/* Allowed Next */}
      <td>
        <AllowedNextPicker
          currentAllowed={draft.allowed_next ?? []}
          allStages={allStages}
          currentCode={stage.code}
          onChange={(val) => setField('allowed_next', val)}
        />
      </td>

      {/* Requires Reason */}
      <td style={{ textAlign: 'center' }}>
        <label className="wf-switch">
          <input
            type="checkbox"
            checked={draft.requires_reason}
            onChange={(e) => setField('requires_reason', e.target.checked)}
          />
          <span className="wf-slider" />
        </label>
      </td>

      {/* Is Terminal */}
      <td style={{ textAlign: 'center' }}>
        <label className="wf-switch">
          <input
            type="checkbox"
            checked={draft.is_terminal}
            onChange={(e) => setField('is_terminal', e.target.checked)}
          />
          <span className="wf-slider" />
        </label>
      </td>

      {/* Is Active */}
      <td style={{ textAlign: 'center' }}>
        <label className="wf-switch">
          <input
            type="checkbox"
            checked={draft.is_active}
            onChange={(e) => setField('is_active', e.target.checked)}
          />
          <span className="wf-slider" />
        </label>
      </td>

      {/* Actions */}
      <td>
        <div className="wf-row-actions">
          <button
            type="button"
            className="btn-ghost"
            style={{ padding: '6px', fontSize: '12px' }}
            title="Mở bảng cấu hình chi tiết"
            onClick={() => onOpenModal(stage)}
          >
            <IconEdit />
          </button>
          {isDirty && (
            <button
              type="button"
              className="wf-btn-revert"
              title="Hủy các sửa đổi chưa lưu"
              onClick={handleRevert}
            >
              Hoàn tác
            </button>
          )}
          <button
            type="button"
            className={`wf-btn-save ${savedSuccess ? 'saved' : ''}`}
            disabled={isSaving || !isDirty}
            onClick={handleSave}
          >
            {savedSuccess ? (
              <>
                <IconCheck /> Đã lưu
              </>
            ) : isSaving ? (
              'Đang lưu…'
            ) : (
              'Lưu'
            )}
          </button>
        </div>
      </td>
    </tr>
  )
}

// --- Main Workflows Component ---
export default function Workflows() {
  const queryClient = useQueryClient()
  const [domain, setDomain] = useState<'talent' | 'rb'>('talent')
  const [viewMode, setViewMode] = useState<'flow' | 'table' | 'cards'>('flow')
  const [searchQuery, setSearchQuery] = useState('')
  const [filterType, setFilterType] = useState<'all' | 'active' | 'sla' | 'reason' | 'terminal'>('all')
  const [editingStage, setEditingStage] = useState<WorkflowStage | null>(null)
  const [toast, setToast] = useState<{ type: 'success' | 'error'; text: string } | null>(null)

  // Fetch dữ liệu quy trình từ API
  const query = useQuery({
    queryKey: ['workflow-stages'],
    queryFn: api.workflowStages,
    retry: false,
  })

  // Mutation cập nhật cấu hình Stage
  const updateMutation = useMutation({
    mutationFn: ({ id, patch }: { id: number; patch: Partial<WorkflowStage> }) =>
      api.workflowStageUpdate(id, patch),
    onSuccess: (_data, variables) => {
      queryClient.invalidateQueries({ queryKey: ['workflow-stages'] })
      queryClient.invalidateQueries({ queryKey: ['workflow-catalog'] })
      const stageName =
        (query.data?.results ?? []).find((s) => s.id === variables.id)?.label || 'bước pipeline'
      showToast('success', `Đã lưu cấu hình "${stageName}" thành công.`)
      if (editingStage && editingStage.id === variables.id) {
        setEditingStage(null)
      }
    },
    onError: (err) => {
      const msg = err instanceof ApiError ? err.message : 'Không thể lưu thay đổi cấu hình.'
      showToast('error', msg)
    },
  })

  function showToast(type: 'success' | 'error', text: string) {
    setToast({ type, text })
    setTimeout(() => {
      setToast(null)
    }, 3500)
  }

  const allStages = useMemo(() => query.data?.results ?? [], [query.data])

  // Lọc theo Domain hiện tại và sắp xếp theo position
  const domainStages = useMemo(() => {
    return allStages
      .filter((row) => row.domain === domain)
      .sort((a, b) => a.position - b.position)
  }, [allStages, domain])

  // Lọc theo Search & Filter Bar
  const filteredStages = useMemo(() => {
    return domainStages.filter((stage) => {
      const matchQuery =
        searchQuery.trim() === '' ||
        stage.label.toLowerCase().includes(searchQuery.toLowerCase()) ||
        stage.code.toLowerCase().includes(searchQuery.toLowerCase())

      if (!matchQuery) return false

      if (filterType === 'active') return stage.is_active
      if (filterType === 'sla') return stage.sla_hours !== null && stage.sla_hours > 0
      if (filterType === 'reason') return stage.requires_reason
      if (filterType === 'terminal') return stage.is_terminal

      return true
    })
  }, [domainStages, searchQuery, filterType])

  // Thống kê KPI
  const stats = useMemo(() => {
    const total = domainStages.length
    const active = domainStages.filter((s) => s.is_active).length
    const withSla = domainStages.filter((s) => s.sla_hours && s.sla_hours > 0).length
    const requiresReason = domainStages.filter((s) => s.requires_reason).length
    const terminal = domainStages.filter((s) => s.is_terminal).length
    return { total, active, withSla, requiresReason, terminal }
  }, [domainStages])

  // Đổi thứ tự Stage (Move Up / Move Down)
  async function handleMoveOrder(stage: WorkflowStage, direction: 'up' | 'down') {
    const currentIndex = domainStages.findIndex((s) => s.id === stage.id)
    if (currentIndex === -1) return

    const targetIndex = direction === 'up' ? currentIndex - 1 : currentIndex + 1
    if (targetIndex < 0 || targetIndex >= domainStages.length) return

    const targetStage = domainStages[targetIndex]
    const stagePos = stage.position
    const targetPos = targetStage.position

    // Hoán đổi position giữa 2 stages
    await updateMutation.mutateAsync({
      id: stage.id,
      patch: { position: targetPos },
    })
    await updateMutation.mutateAsync({
      id: targetStage.id,
      patch: { position: stagePos },
    })
  }

  return (
    <div className="wf-page-container">
      {/* Toast Notification */}
      {toast && (
        <div
          className="wf-toast"
          style={{ borderLeftColor: toast.type === 'error' ? '#ef4444' : '#10b981' }}
        >
          {toast.type === 'success' ? <IconCheck /> : '⚠️'}
          <span>{toast.text}</span>
        </div>
      )}

      {/* Modal Chỉnh sửa Chi tiết */}
      {editingStage && (
        <StageDetailModal
          stage={editingStage}
          allStages={domainStages}
          onClose={() => setEditingStage(null)}
          onSave={(patch) =>
            updateMutation.mutate({
              id: editingStage.id,
              patch,
            })
          }
          isSaving={updateMutation.isPending}
        />
      )}

      {/* Header Banner & Navigation Card */}
      <div className="wf-header-card">
        <div className="wf-header-main">
          <div className="wf-header-title-group">
            <div className="wf-header-icon">
              <IconPipelineSetting />
            </div>
            <div>
              <h1 className="wf-header-title">
                Cấu hình Pipeline &amp; Quy trình Vận hành
              </h1>
              <p className="wf-header-desc">
                Thiết lập các giai đoạn (stages), cam kết thời gian xử lý (SLA), điều kiện chuyển đổi và quy tắc nghiệp vụ cho Talent Radar và Growth Radar.
              </p>
            </div>
          </div>
        </div>

        {/* Navigation & Controls Bar */}
        <div className="wf-nav-bar">
          {/* Domain Switcher */}
          <div className="wf-domain-tabs">
            <button
              type="button"
              className={`wf-domain-btn ${domain === 'talent' ? 'active' : ''}`}
              onClick={() => setDomain('talent')}
            >
              <span>Talent Radar (Tuyển dụng)</span>
              <span className="wf-domain-count">
                {allStages.filter((s) => s.domain === 'talent').length}
              </span>
            </button>
            <button
              type="button"
              className={`wf-domain-btn ${domain === 'rb' ? 'active' : ''}`}
              onClick={() => setDomain('rb')}
            >
              <span>Growth Radar (Khách hàng &amp; Bán lẻ)</span>
              <span className="wf-domain-count">
                {allStages.filter((s) => s.domain === 'rb').length}
              </span>
            </button>
          </div>

          {/* View Mode Switcher */}
          <div className="wf-view-modes">
            <button
              type="button"
              className={`wf-view-mode-btn ${viewMode === 'flow' ? 'active' : ''}`}
              onClick={() => setViewMode('flow')}
              title="Xem sơ đồ luồng quy trình trực quan"
            >
              <IconFlow />
              <span>Sơ đồ luồng</span>
            </button>
            <button
              type="button"
              className={`wf-view-mode-btn ${viewMode === 'table' ? 'active' : ''}`}
              onClick={() => setViewMode('table')}
              title="Xem bảng quản trị chi tiết"
            >
              <IconTable />
              <span>Bảng ma trận</span>
            </button>
            <button
              type="button"
              className={`wf-view-mode-btn ${viewMode === 'cards' ? 'active' : ''}`}
              onClick={() => setViewMode('cards')}
              title="Xem dạng thẻ"
            >
              <IconCards />
              <span>Thẻ cấu hình</span>
            </button>
          </div>
        </div>
      </div>

      {/* KPI Metrics Ribbon */}
      <div className="wf-metrics-grid">
        <div className="wf-metric-card">
          <div
            className="wf-metric-icon"
            style={{ background: 'rgba(37, 99, 235, 0.1)', color: '#2563eb' }}
          >
            📊
          </div>
          <div className="wf-metric-content">
            <span className="wf-metric-val">{stats.total}</span>
            <span className="wf-metric-lbl">Tổng số giai đoạn</span>
          </div>
        </div>

        <div className="wf-metric-card">
          <div
            className="wf-metric-icon"
            style={{ background: 'rgba(16, 185, 129, 0.1)', color: '#10b981' }}
          >
            ⚡
          </div>
          <div className="wf-metric-content">
            <span className="wf-metric-val">{stats.active}/{stats.total}</span>
            <span className="wf-metric-lbl">Đang hoạt động</span>
          </div>
        </div>

        <div className="wf-metric-card">
          <div
            className="wf-metric-icon"
            style={{ background: 'rgba(245, 158, 11, 0.1)', color: '#d97706' }}
          >
            ⏱️
          </div>
          <div className="wf-metric-content">
            <span className="wf-metric-val">{stats.withSla}</span>
            <span className="wf-metric-lbl">Có cam kết SLA</span>
          </div>
        </div>

        <div className="wf-metric-card">
          <div
            className="wf-metric-icon"
            style={{ background: 'rgba(139, 92, 246, 0.1)', color: '#7c3aed' }}
          >
            🔒
          </div>
          <div className="wf-metric-content">
            <span className="wf-metric-val">{stats.requiresReason}</span>
            <span className="wf-metric-lbl">Bắt buộc nhập lý do</span>
          </div>
        </div>

        <div className="wf-metric-card">
          <div
            className="wf-metric-icon"
            style={{ background: 'rgba(216, 31, 42, 0.1)', color: '#d81f2a' }}
          >
            🏁
          </div>
          <div className="wf-metric-content">
            <span className="wf-metric-val">{stats.terminal}</span>
            <span className="wf-metric-lbl">Giai đoạn kết thúc</span>
          </div>
        </div>
      </div>

      {query.isError && (
        <div className="err-box">
          Không tải được cấu hình pipeline từ máy chủ. Vui lòng kiểm tra quyền Admin/Manager hoặc kết nối mạng.
        </div>
      )}

      {/* 1. Chế độ SƠ ĐỒ LUỒNG (Visual Pipeline Flow) */}
      {viewMode === 'flow' && (
        <div className="wf-flow-wrapper">
          <div className="wf-flow-header">
            <div className="wf-flow-title">
              <IconFlow /> Sơ đồ dòng chảy quy trình (Pipeline Flow Stepper)
            </div>
            <div className="wf-flow-legend">
              <div className="wf-flow-legend-item">
                <span className="wf-flag-badge wf-flag-sla">
                  <IconClock /> SLA
                </span>
                <span>Thời hạn xử lý</span>
              </div>
              <div className="wf-flow-legend-item">
                <span className="wf-flag-badge wf-flag-reason">
                  <IconLock /> Lý do
                </span>
                <span>Cần nhập lý do</span>
              </div>
              <div className="wf-flow-legend-item">
                <span className="wf-flag-badge wf-flag-terminal">
                  <IconFlag /> Kết thúc
                </span>
                <span>Đóng hồ sơ</span>
              </div>
            </div>
          </div>

          <div className="wf-flow-track">
            {filteredStages.map((stage, index) => {
              const isLast = index === filteredStages.length - 1
              const allowedStages = (stage.allowed_next ?? []).map((code) =>
                domainStages.find((s) => s.code === code)
              ).filter(Boolean) as WorkflowStage[]

              return (
                <div key={stage.id} className="wf-node-step">
                  <div
                    className={`wf-node-card ${!stage.is_active ? 'inactive' : ''}`}
                    onClick={() => setEditingStage(stage)}
                    style={{ cursor: 'pointer' }}
                  >
                    <div
                      className="wf-node-bar"
                      style={{ backgroundColor: stage.color || '#64748b' }}
                    />
                    <div className="wf-node-body">
                      <div className="wf-node-top">
                        <span className="wf-node-pos">Bước #{stage.position + 1}</span>
                        <span className="wf-node-code">{stage.code}</span>
                      </div>

                      <h4 className="wf-node-title">{stage.label}</h4>

                      <div className="wf-node-flags">
                        {stage.sla_hours ? (
                          <span className="wf-flag-badge wf-flag-sla" title={`Cam kết SLA trong ${stage.sla_hours} giờ`}>
                            <IconClock /> {stage.sla_hours}h
                          </span>
                        ) : null}
                        {stage.requires_reason && (
                          <span className="wf-flag-badge wf-flag-reason" title="Bắt buộc chọn lý do chuyển">
                            <IconLock /> Cần lý do
                          </span>
                        )}
                        {stage.is_terminal && (
                          <span className="wf-flag-badge wf-flag-terminal" title="Bước kết thúc chu trình">
                            <IconFlag /> Kết thúc
                          </span>
                        )}
                        {!stage.is_active && (
                          <span className="wf-flag-badge" style={{ background: 'var(--surface-raised)', color: 'var(--muted)' }}>
                            Tạm ẩn
                          </span>
                        )}
                      </div>

                      <div className="wf-node-next-section">
                        <div className="wf-node-next-label">Chuyển tiếp đến:</div>
                        <div className="wf-node-next-tags">
                          {stage.allowed_next && stage.allowed_next.length > 0 ? (
                            allowedStages.map((s) => (
                              <span key={s.code} className="wf-next-pill">
                                <span
                                  className="wf-next-dot"
                                  style={{ backgroundColor: s.color || '#64748b' }}
                                />
                                {s.label}
                              </span>
                            ))
                          ) : (
                            <span style={{ fontSize: '11px', color: 'var(--muted)', fontStyle: 'italic' }}>
                              Tất cả các bước
                            </span>
                          )}
                        </div>
                      </div>
                    </div>
                  </div>

                  {!isLast && (
                    <div className="wf-node-arrow">
                      <IconArrowRight />
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        </div>
      )}

      {/* Controls Bar: Search & Filter (áp dụng cho cả Table & Cards View) */}
      <div className="wf-controls-bar">
        <div className="wf-search-box">
          <IconSearch />
          <input
            type="text"
            placeholder="Tìm kiếm bước theo tên hoặc mã..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
          />
        </div>

        <div className="wf-filters-group">
          <button
            type="button"
            className={`wf-filter-chip ${filterType === 'all' ? 'active' : ''}`}
            onClick={() => setFilterType('all')}
          >
            Tất cả ({domainStages.length})
          </button>
          <button
            type="button"
            className={`wf-filter-chip ${filterType === 'active' ? 'active' : ''}`}
            onClick={() => setFilterType('active')}
          >
            Đang hoạt động ({stats.active})
          </button>
          <button
            type="button"
            className={`wf-filter-chip ${filterType === 'sla' ? 'active' : ''}`}
            onClick={() => setFilterType('sla')}
          >
            Có SLA ({stats.withSla})
          </button>
          <button
            type="button"
            className={`wf-filter-chip ${filterType === 'reason' ? 'active' : ''}`}
            onClick={() => setFilterType('reason')}
          >
            Cần lý do ({stats.requiresReason})
          </button>
          <button
            type="button"
            className={`wf-filter-chip ${filterType === 'terminal' ? 'active' : ''}`}
            onClick={() => setFilterType('terminal')}
          >
            Kết thúc ({stats.terminal})
          </button>
        </div>
      </div>

      {/* 2. Chế độ BẢNG MA TRẬN (Interactive Matrix Table View) */}
      {viewMode === 'table' && (
        <div className="wf-table-container">
          <table className="wf-table">
            <thead>
              <tr>
                <th style={{ width: '65px' }}>Thứ tự</th>
                <th style={{ width: '120px' }}>Mã định danh</th>
                <th style={{ width: '60px' }}>Màu</th>
                <th style={{ minWidth: '180px' }}>Tên hiển thị</th>
                <th style={{ width: '100px' }}>SLA (giờ)</th>
                <th style={{ minWidth: '220px' }}>Bước tiếp theo cho phép</th>
                <th style={{ width: '90px', textAlign: 'center' }}>Cần lý do</th>
                <th style={{ width: '90px', textAlign: 'center' }}>Kết thúc</th>
                <th style={{ width: '90px', textAlign: 'center' }}>Hoạt động</th>
                <th style={{ width: '130px', textAlign: 'right' }}>Thao tác</th>
              </tr>
            </thead>
            <tbody>
              {filteredStages.map((stage) => (
                <StageRow
                  key={stage.id}
                  stage={stage}
                  allStages={domainStages}
                  onSavePatch={async (id, patch) => {
                    await updateMutation.mutateAsync({ id, patch })
                  }}
                  onMoveOrder={handleMoveOrder}
                  onOpenModal={(s) => setEditingStage(s)}
                  isSaving={updateMutation.isPending}
                />
              ))}
              {filteredStages.length === 0 && (
                <tr>
                  <td colSpan={10} style={{ textAlign: 'center', padding: '30px', color: 'var(--muted)' }}>
                    Không tìm thấy bước pipeline nào phù hợp với bộ lọc.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}

      {/* 3. Chế độ THẺ CẤU HÌNH (Card Grid View) */}
      {viewMode === 'cards' && (
        <div className="wf-cards-grid">
          {filteredStages.map((stage) => {
            const allowed = (stage.allowed_next ?? []).map((code) =>
              domainStages.find((s) => s.code === code)
            ).filter(Boolean) as WorkflowStage[]

            return (
              <div key={stage.id} className="wf-card-item">
                <div className="wf-card-header">
                  <div className="wf-card-title-group">
                    <span
                      style={{
                        width: '12px',
                        height: '12px',
                        borderRadius: '50%',
                        backgroundColor: stage.color || '#64748b',
                        flexShrink: 0,
                      }}
                    />
                    <strong style={{ fontSize: '15px', color: 'var(--text)' }}>
                      {stage.label}
                    </strong>
                  </div>
                  <span className="wf-node-pos">#{stage.position + 1}</span>
                </div>

                <div className="wf-card-body">
                  <div className="wf-card-prop-row">
                    <span className="wf-card-prop-label">Mã Code:</span>
                    <span className="wf-node-code">{stage.code}</span>
                  </div>

                  <div className="wf-card-prop-row">
                    <span className="wf-card-prop-label">Cam kết SLA:</span>
                    <span>
                      {stage.sla_hours ? (
                        <span className="wf-flag-badge wf-flag-sla">
                          <IconClock /> {stage.sla_hours} giờ
                        </span>
                      ) : (
                        <span style={{ color: 'var(--muted)', fontSize: '12px' }}>Không đặt</span>
                      )}
                    </span>
                  </div>

                  <div className="wf-card-prop-row">
                    <span className="wf-card-prop-label">Quy tắc nghiệp vụ:</span>
                    <div style={{ display: 'flex', gap: '4px', flexWrap: 'wrap' }}>
                      {stage.requires_reason && (
                        <span className="wf-flag-badge wf-flag-reason">Cần lý do</span>
                      )}
                      {stage.is_terminal && (
                        <span className="wf-flag-badge wf-flag-terminal">Kết thúc</span>
                      )}
                      {stage.is_active ? (
                        <span className="wf-flag-badge" style={{ background: 'rgba(16,185,129,0.1)', color: '#10b981' }}>
                          Kích hoạt
                        </span>
                      ) : (
                        <span className="wf-flag-badge" style={{ background: 'var(--surface-raised)', color: 'var(--muted)' }}>
                          Tạm ẩn
                        </span>
                      )}
                    </div>
                  </div>

                  <div>
                    <div className="wf-card-prop-label" style={{ marginBottom: '6px' }}>
                      Bước tiếp theo cho phép:
                    </div>
                    <div className="wf-node-next-tags">
                      {stage.allowed_next && stage.allowed_next.length > 0 ? (
                        allowed.map((s) => (
                          <span key={s.code} className="wf-next-pill">
                            <span
                              className="wf-next-dot"
                              style={{ backgroundColor: s.color || '#64748b' }}
                            />
                            {s.label}
                          </span>
                        ))
                      ) : (
                        <span style={{ fontSize: '12px', color: 'var(--muted)', fontStyle: 'italic' }}>
                          Tất cả các bước (Chuyển tự do)
                        </span>
                      )}
                    </div>
                  </div>
                </div>

                <div className="wf-card-footer">
                  <div style={{ display: 'flex', gap: '4px' }}>
                    <button
                      type="button"
                      className="wf-mini-btn"
                      onClick={() => handleMoveOrder(stage, 'up')}
                      title="Lên trước"
                    >
                      ▲
                    </button>
                    <button
                      type="button"
                      className="wf-mini-btn"
                      onClick={() => handleMoveOrder(stage, 'down')}
                      title="Xuống sau"
                    >
                      ▼
                    </button>
                  </div>
                  <button
                    type="button"
                    className="btn-secondary"
                    style={{ fontSize: '12px', padding: '5px 12px' }}
                    onClick={() => setEditingStage(stage)}
                  >
                    Chỉnh sửa chi tiết
                  </button>
                </div>
              </div>
            )
          })}
        </div>
      )}

      {/* Chú thích hướng dẫn nghiệp vụ */}
      <div style={{ background: 'var(--surface-raised)', border: '1px solid var(--border)', borderRadius: '10px', padding: '12px 18px', fontSize: '12.5px', color: 'var(--muted)', display: 'flex', alignItems: 'flex-start', gap: '10px' }}>
        <span style={{ fontSize: '16px', lineHeight: 1 }}>💡</span>
        <div>
          <strong>Lưu ý cấu hình Pipeline:</strong>
          <ul style={{ margin: '4px 0 0', paddingLeft: '18px', lineHeight: 1.6 }}>
            <li>
              <strong>Bước tiếp theo:</strong> Để trống danh sách để cho phép nhân viên tuyển dụng/RM chuyển tự do giữa các trạng thái.
            </li>
            <li>
              <strong>SLA (Service Level Agreement):</strong> Thời gian xử lý tiêu chuẩn tính bằng giờ để hệ thống kích hoạt cảnh báo trễ hạn trên Kanban và báo cáo điều hành.
            </li>
            <li>
              <strong>Cần lý do:</strong> Khi được bật, người dùng bắt buộc phải chọn nguyên nhân (như ứng viên từ chối, khách hàng không có nhu cầu) trước khi lưu.
            </li>
          </ul>
        </div>
      </div>
    </div>
  )
}
