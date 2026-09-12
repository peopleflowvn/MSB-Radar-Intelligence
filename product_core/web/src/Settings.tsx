import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import React, { useState } from 'react'
import { api, AiModelInfo, AiTaskInfo, ApiError, EffectiveTaskConfig, EmbeddingConfig, ProviderPatch, ProviderRow, PublicSettings, TaskModelRoute, UsageModelRow, UsageProviderRow, UsageSummary, UsageTaskRow } from './api'
import MemoryPanel from './MemoryPanel'
import ThumbnailSettings from './ThumbnailSettings'
import RadarAvatarSettings from './RadarAvatarSettings'
import {
  ColorPreset,
  PRESET_PALETTES,
  PRESET_ICONS,
  TableDensity,
  useCustomTheme,
} from './CustomThemeContext'

// ==========================================
// 1. Phân hệ Tuỳ biến Giao diện & Thương hiệu
// ==========================================
function AppearanceSettings() {
  const {
    appName,
    appTagline,
    appIcon,
    appLogoUrl,
    themeMode,
    colorPreset,
    customColor,
    gradientFrom,
    gradientVia,
    gradientTo,
    gradientAngle,
    tableDensity,
    setThemeMode,
    setColorPreset,
    setCustomColor,
    setGradientFrom,
    setGradientVia,
    setGradientTo,
    setGradientAngle,
    setTableDensity,
    saveSystemSettings,
    resetToDefaults,
  } = useCustomTheme()

  const [localName, setLocalName] = useState(appName)
  const [localTagline, setLocalTagline] = useState(appTagline)
  const [localIcon, setLocalIcon] = useState(appIcon)
  const [localLogoUrl, setLocalLogoUrl] = useState(appLogoUrl)
  const [savedMsg, setSavedMsg] = useState('')
  const [uploadError, setUploadError] = useState('')
  // Cấu hình toàn hệ thống, đọc thẳng từ máy chủ. Khối thumbnail cần cả giá trị
  // THÔ (ô nào đang trống) lẫn bản ĐÃ SUY RA (để xem trước khớp thực tế), mà
  // CustomThemeContext chỉ giữ vài trường nên lấy riêng ở đây.
  const [publicSettings, setPublicSettings] = useState<PublicSettings | null>(null)
  React.useEffect(() => {
    api.publicSettings().then(setPublicSettings).catch(() => undefined)
  }, [])
  const [isDragOver, setIsDragOver] = useState(false)
  const fileInputRef = React.useRef<HTMLInputElement | null>(null)

  React.useEffect(() => {
    setLocalName(appName)
  }, [appName])
  React.useEffect(() => {
    setLocalTagline(appTagline)
  }, [appTagline])
  React.useEffect(() => {
    setLocalIcon(appIcon)
  }, [appIcon])
  React.useEffect(() => {
    setLocalLogoUrl(appLogoUrl)
  }, [appLogoUrl])

  const handleProcessFile = (file: File) => {
    if (!file) return
    // Kiểm tra định dạng
    const validTypes = ['image/png', 'image/jpeg', 'image/svg+xml', 'image/x-icon', 'image/vnd.microsoft.icon', 'image/webp']
    const isIco = file.name.endsWith('.ico')
    if (!validTypes.includes(file.type) && !isIco) {
      setUploadError('Định dạng tệp không được hỗ trợ. Vui lòng chọn tệp ảnh PNG, SVG, ICO, JPG, hoặc WebP.')
      return
    }
    // Giới hạn 2MB
    if (file.size > 2 * 1024 * 1024) {
      setUploadError('Dung lượng tệp vượt quá 2MB. Vui lòng chọn tệp nhỏ hơn để đảm bảo tốc độ tải.')
      return
    }
    setUploadError('')

    const reader = new FileReader()
    reader.onload = (event) => {
      const dataUrl = event.target?.result as string
      setLocalLogoUrl(dataUrl)
    }
    reader.onerror = () => {
      setUploadError('Không thể đọc tệp ảnh. Vui lòng thử lại.')
    }
    reader.readAsDataURL(file)
  }

  const handleFileUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (file) {
      handleProcessFile(file)
    }
  }

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault()
    setIsDragOver(false)
    const file = e.dataTransfer.files?.[0]
    if (file) {
      handleProcessFile(file)
    }
  }

  const handleSaveBrand = async (e: React.FormEvent) => {
    e.preventDefault()
    try {
      await saveSystemSettings({
        app_name: localName.trim() || 'MSB Radar',
        app_tagline: localTagline.trim() || 'Hệ Thống Tìm Kiếm Nhân Tài & Tăng Trưởng Khách Hàng',
        app_icon: localIcon || '⚡',
        app_logo_url: localLogoUrl.trim(),
      })
      setSavedMsg('✓ Đã lưu cài đặt toàn hệ thống thành công (tất cả máy tính và trình duyệt sẽ áp dụng).')
    } catch {
      setSavedMsg('⚠️ Lỗi khi lưu lên máy chủ. Vui lòng kiểm tra quyền quản trị.')
    }
    setTimeout(() => setSavedMsg(''), 4000)
  }

  const handleRemoveUploadedLogo = () => {
    setLocalLogoUrl('')
    setUploadError('')
    if (fileInputRef.current) {
      fileInputRef.current.value = ''
    }
  }

  const presets: Array<{ id: ColorPreset; label: string; color: string }> = [
    { id: 'ocean_blue', label: 'Ocean Blue (Mặc định)', color: PRESET_PALETTES.ocean_blue.primary },
    { id: 'crimson_red', label: 'Crimson Red', color: PRESET_PALETTES.crimson_red.primary },
    { id: 'emerald_green', label: 'Emerald Green', color: PRESET_PALETTES.emerald_green.primary },
    { id: 'royal_purple', label: 'Royal Purple', color: PRESET_PALETTES.royal_purple.primary },
    { id: 'amber_gold', label: 'Amber Gold', color: PRESET_PALETTES.amber_gold.primary },
    { id: 'cyber_cyan', label: 'Cyber Cyan', color: PRESET_PALETTES.cyber_cyan.primary },
    { id: 'custom', label: 'Màu tuỳ chọn (Hex)', color: customColor },
  ]

  const densities: Array<{ id: TableDensity; label: string; desc: string }> = [
    { id: 'compact', label: 'Thu gọn (Compact)', desc: 'Tiết kiệm diện tích, hiển thị được nhiều dòng nhất' },
    { id: 'normal', label: 'Vừa vặn (Mặc định)', desc: 'Cân đối giữa khoảng cách và khả năng đọc' },
    { id: 'comfortable', label: 'Rộng rãi (Comfortable)', desc: 'Khoảng cách rộng, thoáng mắt cho màn hình lớn' },
  ]

  return (
    <div className="settings-section-card">
      <div className="section-intro">
        <h2>Nhận diện Thương hiệu &amp; Giao diện</h2>
        <p className="hint">
          Cá nhân hoá 100% thương hiệu: tên phần mềm, tải trực tiếp tệp biểu tượng (Icon/Favicon), Logo tuỳ biến và bảng màu chủ đạo.
        </p>
      </div>

      {/* Tên sản phẩm & Logo */}
      <div className="settings-block">
        <h3>Tên hệ thống, Biểu tượng &amp; Logo</h3>
        <form onSubmit={handleSaveBrand} className="brand-form">
          <div className="form-row-2">
            <div>
              <label>Tên phần mềm / Nền tảng</label>
              <input
                type="text"
                value={localName}
                onChange={(e) => setLocalName(e.target.value)}
                placeholder="VD: Talent Radar, HR Nexus, PeopleFlow..."
                className="input-text"
              />
            </div>
            <div>
              <label>Khẩu hiệu (Tagline)</label>
              <input
                type="text"
                value={localTagline}
                onChange={(e) => setLocalTagline(e.target.value)}
                placeholder="VD: People Intelligence & Opportunity Discovery"
                className="input-text"
              />
            </div>
          </div>

          {/* Tải tệp Biểu tượng & Favicon lên trực tiếp */}
          <div style={{ marginTop: '16px' }}>
            <label style={{ display: 'block', marginBottom: '6px', fontWeight: 600 }}>
              Biểu tượng hệ thống &amp; Favicon (Icon)
            </label>
            <p className="hint" style={{ margin: '0 0 10px' }}>
              Tải trực tiếp tệp ảnh/icon từ máy tính (PNG, SVG, ICO, JPG, WebP) để làm Favicon trên thanh tab trình duyệt và logo thương hiệu.
            </p>

            <input
              ref={fileInputRef}
              type="file"
              accept="image/png, image/jpeg, image/svg+xml, image/x-icon, image/vnd.microsoft.icon, image/webp, .ico"
              style={{ display: 'none' }}
              onChange={handleFileUpload}
            />

            {localLogoUrl ? (
              <div className="icon-preview-active-card">
                <div className="icon-preview-left">
                  <div className="icon-preview-thumb-box">
                    <img src={localLogoUrl} alt="Logo Preview" className="icon-preview-thumb-img" />
                  </div>
                  <div className="icon-preview-meta">
                    <h4 className="icon-preview-title">✓ Đã áp dụng tệp biểu tượng tùy chỉnh</h4>
                    <p className="icon-preview-desc">Tệp này đang được dùng làm Favicon trình duyệt và Logo hệ thống.</p>
                  </div>
                </div>
                <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
                  <button
                    type="button"
                    className="btn btn-secondary btn-sm"
                    onClick={() => fileInputRef.current?.click()}
                  >
                    📁 Chọn tệp khác
                  </button>
                  <button
                    type="button"
                    className="btn btn-secondary btn-sm"
                    onClick={handleRemoveUploadedLogo}
                  >
                    🗑️ Gỡ bỏ tệp
                  </button>
                </div>
              </div>
            ) : (
              <div
                className={`icon-upload-dropzone ${isDragOver ? 'dragover' : ''}`}
                onClick={() => fileInputRef.current?.click()}
                onDragOver={(e) => { e.preventDefault(); setIsDragOver(true) }}
                onDragLeave={() => setIsDragOver(false)}
                onDrop={handleDrop}
              >
                <div className="icon-upload-icon-svg">📁</div>
                <span className="icon-upload-main-text">Bấm để tải tệp biểu tượng lên hoặc kéo &amp; thả vào đây</span>
                <span className="icon-upload-sub-text">Hỗ trợ các định dạng .ico, .png, .svg, .jpg, .webp (Dung lượng tối đa 2MB)</span>
              </div>
            )}

            {uploadError && <p className="error-text" style={{ marginTop: '8px' }}>{uploadError}</p>}
          </div>

          {/* Tuỳ chọn phụ: Emoji Preset hoặc nhập URL ngoài */}
          <div className="form-row-2" style={{ marginTop: '16px' }}>
            <div>
              <label>Hoặc chọn Biểu tượng Emoji thay thế (khi không dùng tệp ảnh)</label>
              <div className="icon-selector-wrapper">
                <input
                  type="text"
                  value={localIcon}
                  onChange={(e) => setLocalIcon(e.target.value)}
                  placeholder="⚡"
                  className="input-text icon-input-text"
                  maxLength={4}
                />
                <div className="icon-preset-list">
                  {PRESET_ICONS.map((ic) => (
                    <button
                      key={ic}
                      type="button"
                      className={`icon-preset-btn ${localIcon === ic && !localLogoUrl ? 'selected' : ''}`}
                      onClick={() => {
                        setLocalIcon(ic)
                        setLocalLogoUrl('')
                      }}
                      title={`Chọn ${ic}`}
                    >
                      {ic}
                    </button>
                  ))}
                </div>
              </div>
            </div>
            <div>
              <label>Hoặc dán URL ảnh ngoài (Tuỳ chọn)</label>
              <input
                type="text"
                value={localLogoUrl.startsWith('data:') ? '' : localLogoUrl}
                onChange={(e) => setLocalLogoUrl(e.target.value)}
                placeholder="https://example.com/logo.png"
                className="input-text"
              />
            </div>
          </div>

          {/* Khung Xem Trước Nhận Diện Trực Tiếp (Live Preview) */}
          <div className="brand-live-preview-box">
            <div className="brand-preview-title-row">
              <h4 className="brand-preview-heading">👁️ Xem trước nhận diện thương hiệu thời gian thực</h4>
              <span className="hint">Mô phỏng vị trí hiển thị Favicon &amp; Logo</span>
            </div>
            <div className="brand-preview-cards-grid">
              {/* 1. Mô phỏng Tab Trình duyệt */}
              <div className="mockup-item-card">
                <span className="mockup-item-label">1. Thanh Tab Trình duyệt (Favicon)</span>
                <div className="browser-tab-simulation">
                  {localLogoUrl ? (
                    <img src={localLogoUrl} alt="Favicon" className="tab-sim-icon-img" />
                  ) : (
                    <span>{localIcon || '⚡'}</span>
                  )}
                  <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {localName || 'Radar'} Hub
                  </span>
                </div>
              </div>

              {/* 2. Mô phỏng Logo Sidebar */}
              <div className="mockup-item-card">
                <span className="mockup-item-label">2. Đầu thanh điều hướng (Sidebar)</span>
                <div className="sidebar-sim-brand">
                  {localLogoUrl ? (
                    <img src={localLogoUrl} alt="Sidebar Logo" className="sidebar-sim-logo-img" />
                  ) : (
                    <span style={{ fontSize: '20px' }}>{localIcon || '⚡'}</span>
                  )}
                  <div style={{ display: 'flex', flexDirection: 'column' }}>
                    <strong style={{ fontSize: '14px', color: 'var(--text)' }}>{localName || 'Radar'}</strong>
                    <small style={{ fontSize: '11px', color: 'var(--muted)' }}>{localTagline || 'People Intelligence'}</small>
                  </div>
                </div>
              </div>
            </div>
          </div>

          <div className="form-actions" style={{ marginTop: '16px' }}>
            <button type="submit" className="btn btn-primary">Lưu nhận diện &amp; Logo</button>
            {savedMsg && <span className="save-hint-ok">{savedMsg}</span>}
          </div>
        </form>
      </div>

      {/* Thumbnail khi chia sẻ liên kết — lưu ở CSDL, máy chủ chèn vào HTML */}
      <div className="settings-block">
        <ThumbnailSettings settings={publicSettings} onSaved={setPublicSettings} />
      </div>

      {/* Avatar & Trợ diện Radar AI */}
      <div className="settings-block">
        <RadarAvatarSettings settings={publicSettings} onSaved={setPublicSettings} />
      </div>

      {/* Chế độ Sáng / Tối */}
      <div className="settings-block">
        <h3>Chế độ giao diện (Theme Mode)</h3>
        <div className="theme-mode-options">
          <label className={`theme-mode-pill ${themeMode === 'auto' ? 'active' : ''}`}>
            <input
              type="radio"
              name="themeMode"
              value="auto"
              checked={themeMode === 'auto'}
              onChange={() => setThemeMode('auto')}
            />
            <span>🌓 Tự động (Theo máy)</span>
          </label>
          <label className={`theme-mode-pill ${themeMode === 'light' ? 'active' : ''}`}>
            <input
              type="radio"
              name="themeMode"
              value="light"
              checked={themeMode === 'light'}
              onChange={() => setThemeMode('light')}
            />
            <span>☀️ Chế độ Sáng (Light)</span>
          </label>
          <label className={`theme-mode-pill ${themeMode === 'dark' ? 'active' : ''}`}>
            <input
              type="radio"
              name="themeMode"
              value="dark"
              checked={themeMode === 'dark'}
              onChange={() => setThemeMode('dark')}
            />
            <span>🌙 Chế độ Tối (Dark)</span>
          </label>
        </div>
      </div>

      {/* Mật độ hiển thị bảng */}
      <div className="settings-block">
        <h3>Mật độ hiển thị bảng biểu (Table Density)</h3>
        <div className="density-grid">
          {densities.map((d) => (
            <div
              key={d.id}
              className={`density-card ${tableDensity === d.id ? 'active' : ''}`}
              onClick={() => setTableDensity(d.id)}
            >
              <div className="density-title">{d.label}</div>
              <div className="density-desc">{d.desc}</div>
            </div>
          ))}
        </div>
      </div>

      {/* Bảng màu chủ đạo */}
      <div className="settings-block">
        <h3>Bảng màu chủ đạo (Accent Color)</h3>
        <div className="palette-grid">
          {presets.map((p) => (
            <div
              key={p.id}
              className={`palette-card ${colorPreset === p.id ? 'selected' : ''}`}
              onClick={() => setColorPreset(p.id)}
            >
              <div className="palette-color-preview" style={{ background: p.color }} />
              <div className="palette-info">
                <span className="palette-name">{p.label}</span>
                <span className="palette-hex">{p.color}</span>
              </div>
              {colorPreset === p.id && <span className="palette-check">✓</span>}
            </div>
          ))}
        </div>

        {/* Trình nhập mã màu Hex */}
        <div className="custom-color-picker-row">
          <label>Nhập mã màu Hex tuỳ ý:</label>
          <div className="color-input-wrapper">
            <input
              type="color"
              value={customColor}
              onChange={(e) => {
                setCustomColor(e.target.value)
                setColorPreset('custom')
              }}
              className="color-picker-input"
            />
            <input
              type="text"
              value={customColor}
              onChange={(e) => {
                setCustomColor(e.target.value)
                setColorPreset('custom')
              }}
              placeholder="#d81f2a"
              className="color-hex-text"
            />
          </div>
          <button
            type="button"
            className="btn btn-secondary"
            onClick={resetToDefaults}
            style={{ marginLeft: 'auto' }}
          >
            Khôi phục mặc định
          </button>
        </div>
      </div>

      {/* Cấu hình dải màu Gradient (Đa sắc) */}
      <div className="settings-block">
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: '8px', marginBottom: '6px' }}>
          <h3 style={{ margin: 0 }}>Cấu hình dải màu Gradient (Đa sắc)</h3>
          <span className="hint" style={{ fontSize: '12px' }}>
            Áp dụng cho mọi nút bấm chính, chữ nghệ thuật gradient, thanh tiến trình &amp; điểm nhấn
          </span>
        </div>
        <p className="hint" style={{ marginTop: 0 }}>
          Chọn mẫu gradient phối sẵn hoặc tự do chọn 2–3 màu để tạo dải chuyển sắc riêng cho thương hiệu của bạn.
        </p>

        {/* 1. Các mẫu Gradient phối sẵn */}
        <label style={{ display: 'block', fontWeight: 600, marginBottom: '8px' }}>
          Mẫu Gradient phối sẵn:
        </label>
        <div className="gradient-presets-grid" style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(180px, 1fr))', gap: '10px', marginBottom: '16px' }}>
          {[
            { id: 'msb_sunset', name: 'MSB Sunset', from: '#FF8A33', via: '#F59E0B', to: '#EA580C', angle: '135deg' },
            { id: 'ocean_breeze', name: 'Ocean Breeze', from: '#0284c7', via: '#0ea5e9', to: '#0369a1', angle: '135deg' },
            { id: 'emerald_peak', name: 'Emerald Peak', from: '#10b981', via: '#059669', to: '#047857', angle: '135deg' },
            { id: 'cosmic_purple', name: 'Cosmic Purple', from: '#8b5cf6', via: '#7c3aed', to: '#6d28d9', angle: '135deg' },
            { id: 'crimson_flame', name: 'Crimson Flame', from: '#ef4444', via: '#dc2626', to: '#b91c1c', angle: '135deg' },
            { id: 'cyber_neon', name: 'Cyber Neon', from: '#06b6d4', via: '#3b82f6', to: '#8b5cf6', angle: '135deg' },
            { id: 'aurora_glow', name: 'Aurora Glow', from: '#ec4899', via: '#8b5cf6', to: '#3b82f6', angle: '135deg' },
          ].map((gp) => {
            const isSelected = gradientFrom === gp.from && gradientTo === gp.to && (gradientVia === gp.via || (!gradientVia && !gp.via))
            const bgGrad = `linear-gradient(${gp.angle}, ${gp.from} 0%, ${gp.via ? `${gp.via} 50%, ` : ''}${gp.to} 100%)`
            return (
              <button
                key={gp.id}
                type="button"
                className={`gradient-preset-card ${isSelected ? 'active' : ''}`}
                style={{
                  display: 'flex',
                  flexDirection: 'column',
                  padding: '10px',
                  borderRadius: '10px',
                  border: isSelected ? '2px solid var(--accent, #FF8A33)' : '1px solid var(--border)',
                  background: 'var(--card)',
                  cursor: 'pointer',
                  textAlign: 'left',
                  transition: 'all 0.2s ease',
                  position: 'relative',
                }}
                onClick={() => {
                  setGradientFrom(gp.from)
                  setGradientVia(gp.via)
                  setGradientTo(gp.to)
                  setGradientAngle(gp.angle)
                }}
              >
                <div style={{ height: '36px', borderRadius: '6px', background: bgGrad, marginBottom: '8px' }} />
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                  <span style={{ fontSize: '13px', fontWeight: 600, color: 'var(--text)' }}>{gp.name}</span>
                  {isSelected && <span style={{ color: 'var(--accent, #FF8A33)', fontWeight: 800 }}>✓</span>}
                </div>
              </button>
            )
          })}
        </div>

        {/* 2. Bộ chọn màu Gradient tùy biến (Custom Multi-Color) */}
        <div style={{ background: 'var(--surface-raised, rgba(255,255,255,0.03))', border: '1px solid var(--border)', borderRadius: '12px', padding: '16px', marginBottom: '16px' }}>
          <label style={{ display: 'block', fontWeight: 600, marginBottom: '12px' }}>
            Tùy biến các điểm dừng màu (Gradient Stops):
          </label>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: '16px' }}>
            {/* Màu bắt đầu */}
            <div>
              <span className="hint" style={{ display: 'block', marginBottom: '6px', fontSize: '12px', fontWeight: 600 }}>
                1. Màu bắt đầu (Start Color)
              </span>
              <div className="color-input-wrapper" style={{ width: '100%' }}>
                <input
                  type="color"
                  value={gradientFrom}
                  onChange={(e) => setGradientFrom(e.target.value)}
                  className="color-picker-input"
                />
                <input
                  type="text"
                  value={gradientFrom}
                  onChange={(e) => setGradientFrom(e.target.value)}
                  placeholder="#FF8A33"
                  className="color-hex-text"
                />
              </div>
            </div>

            {/* Màu trung gian */}
            <div>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '6px' }}>
                <span className="hint" style={{ fontSize: '12px', fontWeight: 600 }}>
                  2. Màu ở giữa (Middle Color - Tùy chọn)
                </span>
                {gradientVia ? (
                  <button
                    type="button"
                    className="btn btn-link btn-sm"
                    style={{ padding: 0, fontSize: '11px', color: 'var(--muted)' }}
                    onClick={() => setGradientVia('')}
                  >
                    Bỏ màu giữa
                  </button>
                ) : (
                  <button
                    type="button"
                    className="btn btn-link btn-sm"
                    style={{ padding: 0, fontSize: '11px', color: 'var(--accent)' }}
                    onClick={() => setGradientVia('#F59E0B')}
                  >
                    + Thêm màu giữa
                  </button>
                )}
              </div>
              <div className="color-input-wrapper" style={{ width: '100%', opacity: gradientVia ? 1 : 0.6 }}>
                <input
                  type="color"
                  value={gradientVia || gradientFrom}
                  disabled={!gradientVia}
                  onChange={(e) => setGradientVia(e.target.value)}
                  className="color-picker-input"
                />
                <input
                  type="text"
                  value={gradientVia}
                  placeholder="(Bỏ trống nếu chỉ dùng 2 màu)"
                  onChange={(e) => setGradientVia(e.target.value)}
                  className="color-hex-text"
                />
              </div>
            </div>

            {/* Màu kết thúc */}
            <div>
              <span className="hint" style={{ display: 'block', marginBottom: '6px', fontSize: '12px', fontWeight: 600 }}>
                3. Màu kết thúc (End Color)
              </span>
              <div className="color-input-wrapper" style={{ width: '100%' }}>
                <input
                  type="color"
                  value={gradientTo}
                  onChange={(e) => setGradientTo(e.target.value)}
                  className="color-picker-input"
                />
                <input
                  type="text"
                  value={gradientTo}
                  onChange={(e) => setGradientTo(e.target.value)}
                  placeholder="#EA580C"
                  className="color-hex-text"
                />
              </div>
            </div>
          </div>

          {/* Góc xoay dải màu */}
          <div style={{ marginTop: '16px' }}>
            <label style={{ display: 'block', fontWeight: 600, marginBottom: '8px', fontSize: '13px' }}>
              Hướng xoay dải màu (Gradient Angle):
            </label>
            <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
              {[
                { angle: '135deg', label: '↘ 135° (Chéo chuẩn)' },
                { angle: '90deg', label: '➔ 90° (Ngang)' },
                { angle: '180deg', label: '↓ 180° (Dọc)' },
                { angle: '45deg', label: '↗ 45° (Chéo ngược)' },
              ].map((ang) => (
                <button
                  key={ang.angle}
                  type="button"
                  className={`btn btn-sm ${gradientAngle === ang.angle ? 'btn-primary' : 'btn-secondary'}`}
                  style={{ borderRadius: '20px', padding: '4px 14px', fontSize: '12px' }}
                  onClick={() => setGradientAngle(ang.angle)}
                >
                  {ang.label}
                </button>
              ))}
            </div>
          </div>
        </div>

        {/* 3. Live Interactive Gradient Preview Card */}
        <div style={{
          border: '1px solid var(--border)',
          borderRadius: '12px',
          padding: '16px',
          background: 'var(--card)',
          boxShadow: '0 4px 20px rgba(0,0,0,0.06)',
        }}>
          <h4 style={{ margin: '0 0 12px', fontSize: '14px', display: 'flex', alignItems: 'center', gap: '8px' }}>
            <span>🎨</span> Xem trước hiệu ứng Gradient thời gian thực
          </h4>
          <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: '16px' }}>
            {/* Nút bấm mẫu */}
            <button
              type="button"
              className="btn btn-primary"
              style={{
                background: 'var(--accent-gradient)',
                border: 'none',
                color: '#fff',
                padding: '9px 20px',
                borderRadius: '8px',
                fontWeight: 600,
                boxShadow: '0 4px 14px var(--accent-soft)',
              }}
            >
              🚀 Nút hành động mẫu
            </button>

            {/* Chữ Gradient nghệ thuật */}
            <span
              className="radar-gradient-text"
              style={{
                fontSize: '18px',
                fontWeight: 800,
                background: 'var(--accent-gradient-text)',
                WebkitBackgroundClip: 'text',
                WebkitTextFillColor: 'transparent',
              }}
            >
              {localName || 'Radar'} Intelligence Gradient Text
            </span>

            {/* Badge mẫu */}
            <span
              style={{
                background: 'var(--accent-gradient)',
                color: '#fff',
                padding: '4px 12px',
                borderRadius: '20px',
                fontSize: '12px',
                fontWeight: 700,
                boxShadow: '0 2px 8px var(--accent-soft)',
              }}
            >
              ⚡ PRO BADGE
            </span>
          </div>

          <div style={{ marginTop: '12px', paddingTop: '10px', borderTop: '1px solid var(--border)' }}>
            <span className="hint" style={{ fontSize: '12px', fontFamily: 'monospace' }}>
              Mã CSS: <code>linear-gradient({gradientAngle}, {gradientFrom} 0%, {gradientVia ? `${gradientVia} 50%, ` : ''}{gradientTo} 100%)</code>
            </span>
          </div>
        </div>
      </div>
    </div>
  )
}

// ==========================================
// 2. Phân hệ Tuỳ chọn Tìm kiếm & Bảo mật
// ==========================================
function SearchAndPrivacySettings() {
  const {
    maskSensitiveData,
    minMatchScore,
    itemsPerPage,
    soundAlerts,
    setMaskSensitiveData,
    setMinMatchScore,
    setItemsPerPage,
    setSoundAlerts,
  } = useCustomTheme()

  const [clearCacheMsg, setClearCacheMsg] = useState('')

  const handleClearCache = () => {
    try {
      sessionStorage.clear()
      setClearCacheMsg('Đã làm sạch bộ nhớ đệm thành công!')
      setTimeout(() => setClearCacheMsg(''), 3000)
    } catch {
      setClearCacheMsg('Không thể xoá bộ nhớ đệm.')
    }
  }

  return (
    <div className="settings-section-card">
      <div className="section-intro">
        <h2>Trải nghiệm Tìm kiếm, Hiệu năng &amp; Bảo mật</h2>
        <p className="hint">
          Cấu hình tham số lọc ứng viên, mật độ trang và che giấu thông tin nhạy cảm.
        </p>
      </div>

      {/* Ngưỡng điểm phù hợp */}
      <div className="settings-block">
        <h3>Ngưỡng điểm phù hợp tối thiểu (Minimum Match Score)</h3>
        <p className="hint">Chỉ hiển thị các ứng viên / leads có điểm số phù hợp lớn hơn hoặc bằng ngưỡng này.</p>
        <div className="range-slider-box">
          <input
            type="range"
            min="20"
            max="90"
            step="5"
            value={minMatchScore}
            onChange={(e) => setMinMatchScore(Number(e.target.value))}
            className="slider"
          />
          <span className="slider-val-badge">{minMatchScore}%</span>
        </div>
      </div>

      {/* Số lượng mục trên mỗi trang */}
      <div className="settings-block">
        <h3>Số lượng kết quả hiển thị trên mỗi trang</h3>
        <div className="items-per-page-options">
          {[10, 25, 50, 100].map((num) => (
            <button
              key={num}
              type="button"
              className={`pill-btn ${itemsPerPage === num ? 'active' : ''}`}
              onClick={() => setItemsPerPage(num)}
            >
              {num} mục / trang
            </button>
          ))}
        </div>
      </div>

      {/* Bảo mật & Che dữ liệu */}
      <div className="settings-block">
        <h3>Bảo mật thông tin cá nhân (Data Masking)</h3>
        <label className="checkbox-setting-row">
          <input
            type="checkbox"
            checked={maskSensitiveData}
            onChange={(e) => setMaskSensitiveData(e.target.checked)}
          />
          <div>
            <strong>Tự động che số điện thoại và email trên danh sách xem trước</strong>
            <p className="hint">Ví dụ: 098***1234, t***@gmail.com — chỉ mở đầy đủ khi bấm vào chi tiết hồ sơ.</p>
          </div>
        </label>
      </div>

      {/* Thông báo & Âm thanh */}
      <div className="settings-block">
        <h3>Âm thanh &amp; Thông báo</h3>
        <label className="checkbox-setting-row">
          <input
            type="checkbox"
            checked={soundAlerts}
            onChange={(e) => setSoundAlerts(e.target.checked)}
          />
          <div>
            <strong>Bật âm thanh báo hiệu khi hoàn tất quét / đồng bộ dữ liệu</strong>
            <p className="hint">Phát chuông nhẹ khi hoàn thành tìm kiếm AI hoặc phát hiện tín hiệu ứng viên mới.</p>
          </div>
        </label>
      </div>

      {/* Dọn dẹp cache */}
      <div className="settings-block">
        <h3>Bộ nhớ tạm (Cache Management)</h3>
        <div className="cache-action-row">
          <button type="button" className="btn btn-secondary" onClick={handleClearCache}>
            Xoá bộ nhớ đệm tìm kiếm
          </button>
          {clearCacheMsg && <span className="save-hint-ok">{clearCacheMsg}</span>}
        </div>
      </div>

      {/* Cấu hình Xưng hô & Nhân cách Trợ lý Radar */}
      <AssistantPersonaSettings />
    </div>
  )
}

function AssistantPersonaSettings() {
  const qc = useQueryClient()
  const prefQuery = useQuery({
    queryKey: ['assistant-preference'],
    queryFn: api.assistantPreference,
  })

  const [gender, setGender] = useState<string>('')
  const [salutation, setSalutation] = useState<string>('')
  const [preferredName, setPreferredName] = useState<string>('')
  const [personalization, setPersonalization] = useState<boolean>(true)
  const [saveMsg, setSaveMsg] = useState<string>('')
  const [errorMsg, setErrorMsg] = useState<string>('')

  React.useEffect(() => {
    if (prefQuery.data) {
      setGender(prefQuery.data.gender || '')
      setSalutation(prefQuery.data.preferred_salutation || '')
      setPreferredName(prefQuery.data.preferred_name || '')
      setPersonalization(prefQuery.data.personalization_enabled ?? true)
    }
  }, [prefQuery.data])

  const saveMutation = useMutation({
    mutationFn: api.assistantPreferenceSave,
    onSuccess: (data) => {
      qc.setQueryData(['assistant-preference'], data)
      setSaveMsg('✓ Đã lưu cài đặt xưng hô Radar thành công!')
      setErrorMsg('')
      setTimeout(() => setSaveMsg(''), 3500)
    },
    onError: (err: Error) => {
      setErrorMsg(`Lỗi khi lưu: ${err.message}`)
      setSaveMsg('')
    },
  })

  const handleSave = (e: React.FormEvent) => {
    e.preventDefault()
    saveMutation.mutate({
      gender: gender as any,
      preferred_salutation: salutation as any,
      preferred_name: preferredName.trim(),
      personalization_enabled: personalization,
    })
  }

  const sampleAddress = salutation === 'anh' ? 'anh' : salutation === 'chi' ? 'chị' : salutation === 'ban' ? 'bạn' : gender === 'male' ? 'anh' : gender === 'female' ? 'chị' : 'anh/chị'
  const displayName = preferredName.trim() ? ` ${preferredName.trim()}` : ''

  return (
    <div className="settings-block" style={{ borderTop: '1px solid var(--border)', paddingTop: '20px', marginTop: '20px' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '8px' }}>
        <span style={{ fontSize: '20px' }}>🤖</span>
        <h3 style={{ margin: 0 }}>Xưng hô &amp; Nhân cách Trợ lý Radar</h3>
      </div>
      <p className="hint">
        Radar luôn tự xưng là &quot;Radar&quot; và tôn trọng cách xưng hô bạn mong muốn trong mọi câu trả lời, phân tích ứng viên và khách hàng.
      </p>

      <form onSubmit={handleSave} style={{ display: 'flex', flexDirection: 'column', gap: '14px', marginTop: '12px' }}>
        <div className="form-row-2">
          <div>
            <label style={{ display: 'block', fontSize: '13px', fontWeight: 600, marginBottom: '6px' }}>
              Cách Radar xưng hô với bạn
            </label>
            <select
              value={salutation}
              onChange={(e) => setSalutation(e.target.value)}
              className="input-text"
              style={{ width: '100%' }}
            >
              <option value="">Tự động theo giới tính (Mặc định: anh/chị)</option>
              <option value="anh">Gọi tôi là &quot;Anh&quot;</option>
              <option value="chi">Gọi tôi là &quot;Chị&quot;</option>
              <option value="ban">Gọi tôi là &quot;Bạn&quot;</option>
            </select>
          </div>

          <div>
            <label style={{ display: 'block', fontSize: '13px', fontWeight: 600, marginBottom: '6px' }}>
              Tên gọi ưu tiên (Tuỳ chọn)
            </label>
            <input
              type="text"
              value={preferredName}
              onChange={(e) => setPreferredName(e.target.value)}
              placeholder="VD: Tùng, Lan, Nam..."
              className="input-text"
              style={{ width: '100%' }}
            />
          </div>
        </div>

        <div className="form-row-2">
          <div>
            <label style={{ display: 'block', fontSize: '13px', fontWeight: 600, marginBottom: '6px' }}>
              Giới tính tài khoản
            </label>
            <select
              value={gender}
              onChange={(e) => setGender(e.target.value)}
              className="input-text"
              style={{ width: '100%' }}
            >
              <option value="">Không chỉ định</option>
              <option value="male">Nam</option>
              <option value="female">Nữ</option>
              <option value="other">Khác</option>
              <option value="undisclosed">Bảo mật / Không nêu</option>
            </select>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', paddingTop: '20px' }}>
            <label className="checkbox-setting-row" style={{ width: '100%' }}>
              <input
                type="checkbox"
                checked={personalization}
                onChange={(e) => setPersonalization(e.target.checked)}
              />
              <div>
                <strong>Bật cá nhân hoá hội thoại Radar</strong>
                <p className="hint">Radar ghi nhớ ngữ cảnh và xưng hô thân thiện, chính xác theo hồ sơ.</p>
              </div>
            </label>
          </div>
        </div>

        {/* Live Preview Box */}
        <div style={{
          background: 'var(--surface-raised, rgba(255, 255, 255, 0.04))',
          border: '1px solid var(--border)',
          borderRadius: '8px',
          padding: '12px 16px',
          fontSize: '13px',
        }}>
          <span style={{ color: 'var(--muted)', fontSize: '11px', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.06em' }}>
            👁️ Ví dụ câu chào thực tế từ Radar:
          </span>
          <p style={{ margin: '6px 0 0', color: 'var(--text)', fontStyle: 'italic' }}>
            &ldquo;Chào {sampleAddress}{displayName}, Radar đã phân tích xong yêu cầu của {sampleAddress}. Dưới đây là các ứng viên phù hợp nhất...&rdquo;
          </p>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          <button
            type="submit"
            className="btn btn-primary"
            disabled={saveMutation.isPending}
          >
            {saveMutation.isPending ? 'Đang lưu...' : '💾 Lưu cài đặt xưng hô'}
          </button>
          {saveMsg && <span className="save-hint-ok">{saveMsg}</span>}
          {errorMsg && <span className="error-text">{errorMsg}</span>}
        </div>
      </form>
    </div>
  )
}

// ==========================================
// 3. Phân hệ Cài đặt Nhà cung cấp AI
// ==========================================
function TrangThai({ row, dangDung }: { row: ProviderRow; dangDung: boolean }) {
  if (!row.enabled && dangDung)
    return <span className="badge ok">⚡ Đang dùng (từ .env)</span>
  if (!row.enabled) return <span className="badge off">Tạm tắt</span>
  if (row.has_api_key && !row.key_readable)
    return <span className="badge err">⚠️ Khoá hỏng</span>
  if (!row.has_api_key) return <span className="badge warn">Chưa có khoá</span>
  if (!row.model && !row.model_default)
    return <span className="badge warn">Chưa chọn model</span>
  if (row.last_check_ok === true) return <span className="badge ok">✓ Đã kiểm tra (Online)</span>
  if (row.last_check_ok === false) return <span className="badge err">✕ Lỗi kết nối</span>
  return <span className="badge">Sẵn sàng</span>
}

function ProviderLogo({ provider }: { provider: string }) {
  const p = provider.toLowerCase()
  switch (p) {
    case 'greennode':
      return (
        <svg viewBox="0 0 24 24" width="22" height="22" fill="none">
          <rect width="24" height="24" rx="6" fill="#10b981" />
          <path
            d="M7 12.5L10.5 16L17 8.5"
            stroke="#ffffff"
            strokeWidth="2.5"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
      )
    case 'gemini':
      return (
        <svg viewBox="0 0 24 24" width="22" height="22" fill="none">
          <path
            d="M12 2C12 7.52285 7.52285 12 2 12C7.52285 12 12 16.4771 12 22C12 16.4771 16.4771 12 22 12C16.4771 12 12 7.52285 12 2Z"
            fill="url(#gemini-grad)"
          />
          <defs>
            <linearGradient id="gemini-grad" x1="2" y1="2" x2="22" y2="22" gradientUnits="userSpaceOnUse">
              <stop stopColor="#1ba1e2" />
              <stop offset="0.5" stopColor="#9b51e0" />
              <stop offset="1" stopColor="#ff4081" />
            </linearGradient>
          </defs>
        </svg>
      )
    case 'openai':
      return (
        <svg viewBox="0 0 24 24" width="22" height="22" fill="currentColor">
          <path d="M21.5 10.45c-.2-.93-.68-1.78-1.37-2.43a5.55 5.55 0 0 0-3.83-1.42c-.28 0-.57.02-.85.07A5.5 5.5 0 0 0 11 3.5c-1.33 0-2.58.48-3.56 1.34A5.53 5.53 0 0 0 5 8.7c0 .3.02.6.07.9A5.5 5.5 0 0 0 2.5 14c0 1.33.48 2.58 1.34 3.56A5.53 5.53 0 0 0 7.7 20.4c.3 0 .6-.02.9-.07A5.5 5.5 0 0 0 13 23.5c1.33 0 2.58-.48 3.56-1.34a5.53 5.53 0 0 0 2.44-3.86c.28 0 .57-.02.85-.07A5.5 5.5 0 0 0 22.5 13c0-.9-.23-1.76-.66-2.5a5.4 5.4 0 0 0-.34-.05zM12 15.5a3.5 3.5 0 1 1 0-7 3.5 3.5 0 0 1 0 7z"/>
        </svg>
      )
    case 'anthropic':
      return (
        <svg viewBox="0 0 24 24" width="22" height="22" fill="#d97706">
          <path d="M13.8 3.2L7.6 18.8h2.8l1.3-3.4h5.6l1.3 3.4h2.8L15.2 3.2h-1.4zm-.2 3.8l2.1 5.6h-4.2l2.1-5.6zM4.5 18.8h2.6l4.2-10.6H8.7L4.5 18.8z"/>
        </svg>
      )
    case 'groq':
      return (
        <svg viewBox="0 0 24 24" width="22" height="22" fill="#f97316">
          <path d="M13 2L3 14h8l-2 8 10-12h-8l2-8z" stroke="#f97316" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
        </svg>
      )
    case 'deepseek':
      return (
        <svg viewBox="0 0 24 24" width="22" height="22" fill="#0284c7">
          <path d="M12 3c-4.97 0-9 4.03-9 9 0 2.12.74 4.07 1.97 5.61L4 21l3.5-.96C9.01 20.61 10.45 21 12 21c4.97 0 9-4.03 9-9s-4.03-9-9-9zm-2 11c-.55 0-1-.45-1-1s.45-1 1-1 1 .45 1 1-.45 1-1 1zm4 0c-.55 0-1-.45-1-1s.45-1 1-1 1 .45 1 1-.45 1-1 1z"/>
        </svg>
      )
    case 'ollama':
      return (
        <svg viewBox="0 0 24 24" width="22" height="22" fill="currentColor">
          <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm1 16.93c-3.95-.49-7-3.85-7-7.93 0-.62.08-1.21.21-1.79L9 15v1c0 1.1.9 2 2 2v.93zm5.9-4.04c-.33-.6-.82-1.09-1.42-1.42l-1.04-.58A2.99 2.99 0 0 0 15 12V9c0-1.66-1.34-3-3-3S9 7.34 9 9v1.26c-.32.17-.61.4-.84.68L6.4 12.8A7.95 7.95 0 0 1 12 4c4.08 0 7.44 3.05 7.9 7-.01 1.05-.33 2.03-.9 2.89z"/>
        </svg>
      )
    default:
      return (
        <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" strokeWidth="2">
          <path d="M12 2v4M12 18v4M4.93 4.93l2.83 2.83M16.24 16.24l2.83 2.83M2 12h4M18 12h4M4.93 19.07l2.83-2.83M16.24 7.76l2.83-2.83"/>
        </svg>
      )
  }
}

function ProviderCard({ row, dangDung }: { row: ProviderRow; dangDung: boolean }) {
  const queryClient = useQueryClient()
  const [apiKey, setApiKey] = useState('')
  const [model, setModel] = useState(row.model)
  const [baseUrl, setBaseUrl] = useState(row.base_url)
  const [priority, setPriority] = useState(String(row.priority))
  const [message, setMessage] = useState('')
  const [models, setModels] = useState<string[] | null>(null)
  const [showAdvanced, setShowAdvanced] = useState(false)
  const [keyResults, setKeyResults] = useState<
    Array<{ index: number; label: string; ok: boolean; detail: string }>
  >([])

  const refresh = () => queryClient.invalidateQueries({ queryKey: ['ai-providers'] })

  const save = useMutation({
    mutationFn: (patch: ProviderPatch) => api.aiProviderUpdate(row.provider, patch),
    onSuccess: () => {
      setApiKey('')
      setMessage('Đã lưu cấu hình thành công.')
      refresh()
      setTimeout(() => setMessage(''), 4000)
    },
    onError: (error) => setMessage(error instanceof ApiError ? error.message : 'Lưu thất bại.'),
  })

  const check = useMutation({
    mutationFn: () => api.aiProviderTest(row.provider),
    onSuccess: (result) => {
      setMessage(result.detail)
      setKeyResults(result.keys ?? [])
      refresh()
    },
    onError: (error) => {
      setMessage(error instanceof ApiError ? error.message : 'Kiểm tra thất bại.')
      setKeyResults([])
    },
  })

  const loadModels = useMutation({
    mutationFn: () => api.aiProviderModels(row.provider),
    onSuccess: (result) => {
      setModels(result.models)
      setMessage(`Tìm thấy ${result.models.length} model khả dụng.`)
      setTimeout(() => setMessage(''), 4000)
    },
    onError: (error) =>
      setMessage(error instanceof ApiError ? error.message : 'Không lấy được danh sách model.'),
  })

  function handleSave() {
    const patch: ProviderPatch = {
      model,
      base_url: baseUrl,
      priority: Number(priority) || 0,
    }
    if (apiKey.trim()) patch.api_key = apiKey.trim()
    save.mutate(patch)
  }

  return (
    <div className={`ai-provider-card ${row.enabled ? 'active' : 'disabled'}`}>
      {/* Header card */}
      <div className="ai-provider-header">
        <div className="provider-brand-info">
          <div className="provider-icon-badge">
            <ProviderLogo provider={row.provider} />
          </div>
          <div>
            <div className="provider-title-row">
              <h3 className="provider-name">{row.label}</h3>
              {dangDung && <span className="active-pill">Đang phục vụ</span>}
            </div>
            <div className="provider-subinfo">
              <span>Model hiện tại: <strong>{model || row.model_default || 'Chưa thiết lập'}</strong></span>
              {row.key_count > 0 && <span> · {row.key_count} API Key</span>}
            </div>
          </div>
        </div>

        <div className="provider-header-actions">
          <TrangThai row={row} dangDung={dangDung} />
          <label className="toggle-switch-ui" title={row.enabled ? 'Bấm để tạm tắt' : 'Bấm để kích hoạt'}>
            <input
              type="checkbox"
              checked={row.enabled}
              onChange={(event) => save.mutate({ enabled: event.target.checked })}
            />
            <span className="toggle-slider" />
          </label>
        </div>
      </div>

      {/* Body Inputs */}
      <div className="ai-provider-body">
        <div className="provider-input-grid">
          {/* API Key */}
          <div className="input-group-col">
            <label>
              <span>Khoá API Key {row.key_count > 1 && <span className="tag-count">({row.key_count} keys)</span>}</span>
            </label>
            <textarea
              rows={2}
              className="input-text key-textarea"
              autoComplete="new-password"
              placeholder={
                row.has_api_key
                  ? `Đang dùng: ${row.api_key_hint} (gõ vào đây nếu muốn đổi khoá mới)`
                  : 'Dán API Key vào đây (hỗ trợ nhiều khoá cách nhau bằng dấu phẩy)...'
              }
              value={apiKey}
              onChange={(event) => setApiKey(event.target.value)}
            />
            <small className="field-hint">
              Nhập nhiều key để hệ thống tự động luân phiên (load-balance &amp; failover) khi hết hạn mức.
            </small>
          </div>

          {/* Model Name */}
          <div className="input-group-col">
            <div className="label-with-action">
              <label><span>Mã Model chỉ định</span></label>
              {row.has_api_key && (
                <button
                  type="button"
                  className="link-action-btn"
                  onClick={() => loadModels.mutate()}
                  disabled={loadModels.isPending}
                >
                  {loadModels.isPending ? 'Đang tải...' : '⚡ Lấy danh sách model'}
                </button>
              )}
            </div>
            <input
              list={`models-${row.provider}`}
              className="input-text"
              placeholder={row.model_default || 'VD: gemini-2.5-flash, gpt-4o...'}
              value={model}
              onChange={(event) => setModel(event.target.value)}
            />
            {models && (
              <datalist id={`models-${row.provider}`}>
                {models.map((name) => (
                  <option key={name} value={name} />
                ))}
              </datalist>
            )}
            <small className="field-hint">
              {row.model_default ? `Mặc định hệ thống: ${row.model_default}` : 'Bắt buộc điền tên model.'}
            </small>
          </div>
        </div>

        {/* Nút mở rộng cấu hình nâng cao */}
        <div className="advanced-toggle-row">
          <button
            type="button"
            className="btn-toggle-advanced"
            onClick={() => setShowAdvanced(!showAdvanced)}
          >
            {showAdvanced ? '▴ Thu gọn tuỳ chọn nâng cao' : '▾ Cấu hình nâng cao (Base URL & Độ ưu tiên)'}
          </button>
        </div>

        {showAdvanced && (
          <div className="provider-advanced-box">
            <div className="form-row-2">
              <div>
                <label><span>Base URL / Endpoint Proxy</span></label>
                <input
                  className="input-text"
                  placeholder={row.base_url_default || 'Để trống nếu dùng API chính thức'}
                  value={baseUrl}
                  onChange={(event) => setBaseUrl(event.target.value)}
                />
                <small className="field-hint">Tuỳ chỉnh khi chạy qua Proxy hoặc mô hình nội bộ Local AI.</small>
              </div>
              <div style={{ maxWidth: '180px' }}>
                <label><span>Độ ưu tiên (Priority)</span></label>
                <input
                  type="number"
                  min={0}
                  className="input-text"
                  value={priority}
                  onChange={(event) => setPriority(event.target.value)}
                />
                <small className="field-hint">Số nhỏ được gọi trước (0 là cao nhất).</small>
              </div>
            </div>
          </div>
        )}

        {/* Danh sách Multi-key trạng thái chi tiết */}
        {row.keys.length > 1 && (
          <div className="multi-keys-status-box">
            <div className="multi-keys-title">Trạng thái luân phiên từng khoá:</div>
            <div className="multi-keys-grid">
              {row.keys.map((key, index) => (
                <div key={key.label + index} className="multi-key-chip">
                  <code className="key-code">{key.label}</code>
                  {key.disabled ? (
                    <span className="badge err">Khoá sai</span>
                  ) : key.available ? (
                    <span className="badge ok">✓ Sẵn sàng</span>
                  ) : (
                    <span className="badge warn">Nghỉ {key.cooling_seconds}s</span>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Footer Actions & Test Status */}
        <div className="ai-provider-footer">
          <div className="footer-left-buttons">
            <button
              type="button"
              className="btn btn-primary"
              onClick={handleSave}
              disabled={save.isPending}
            >
              {save.isPending ? 'Đang lưu...' : 'Lưu cấu hình'}
            </button>
            <button
              type="button"
              className="btn btn-secondary"
              onClick={() => check.mutate()}
              disabled={check.isPending}
            >
              {check.isPending ? 'Đang test...' : '⚡ Kiểm tra kết nối'}
            </button>
          </div>

          <div className="footer-feedback-msg">
            {message && <span className="feedback-badge">{message}</span>}
            {!message && row.last_check_detail && (
              <span className="feedback-dimmed">{row.last_check_detail}</span>
            )}
          </div>
        </div>

        {/* Chi tiết kết quả kiểm tra nhiều key */}
        {keyResults.length > 0 && (
          <div className="key-test-results-panel">
            <div className="test-results-heading">Kết quả kiểm tra chi tiết:</div>
            <div className="test-results-list">
              {keyResults.map((item) => (
                <div key={item.index} className={`test-result-row ${item.ok ? 'success' : 'failed'}`}>
                  <span className="test-dot" />
                  <code>{item.label}</code>
                  <span className={item.ok ? 'badge ok' : 'badge err'}>
                    {item.ok ? 'Hoạt động tốt' : 'Lỗi kết nối'}
                  </span>
                  <span className="test-detail-text">{item.detail}</span>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

function EffectiveTaskRoutes({ routes, providers, catalog, groups, models, kindRequires }: {
  routes: TaskModelRoute[]; providers: ProviderRow[];
  catalog: AiTaskInfo[]; groups: string[];
  models: Record<string, AiModelInfo[]>; kindRequires: Record<string, string>;
}) {
  const queryClient = useQueryClient()
  const [task, setTask] = useState('talent_search')
  const [provider, setProvider] = useState('greennode')
  const [model, setModel] = useState('')
  const selected = catalog.find(item => item.name === task)

  // Đổi tác vụ thì điền sẵn mặc định đã đo được — người vận hành không phải
  // nhớ model nào hợp việc nào, mà vẫn sửa được ngay bên dưới.
  const applyTask = (name: string) => {
    setTask(name)
    const info = catalog.find(item => item.name === name)
    if (info?.default_provider) setProvider(info.default_provider)
    setModel(info?.default_model ?? '')
  }

  /** Model của ĐÚNG nhà cung cấp đang chọn. GreenNode là hub nhiều model nên
   *  danh sách này khác hẳn Gemini — trộn chung là gán nhầm. */
  const choices = models[provider] ?? []
  const chosen = choices.find(m => m.id === model)

  /** Chặn, không chỉ cảnh báo: `cv_ocr` gán nhầm model không có thị giác thì
   *  không có gì báo lỗi, CV scan chỉ lặng lẽ vào kho thành rỗng. */
  const canNangLuc = selected ? kindRequires[selected.kind] : undefined
  const chan = (() => {
    if (!canNangLuc || !model.trim()) return ''
    if (!chosen) return `Không rõ “${model}” có ${canNangLuc} hay không. Tác vụ này chọn sai sẽ không báo lỗi, chỉ trả rác.`
    if (chosen.discovered) return `“${chosen.label}” dò được từ nhà cung cấp nhưng chưa ai xác nhận nó có ${canNangLuc}.`
    if (!chosen.capabilities.includes(canNangLuc)) return `“${chosen.label}” không có năng lực ${canNangLuc}, mà tác vụ này bắt buộc phải có.`
    return ''
  })()
  const save = useMutation({ mutationFn: () => api.aiTaskRouteSave(task.trim(), { provider, model }), onSuccess: () => queryClient.invalidateQueries({ queryKey: ['ai-providers'] }) })
  const remove = useMutation({ mutationFn: (name: string) => api.aiTaskRouteDelete(name), onSuccess: () => queryClient.invalidateQueries({ queryKey: ['ai-providers'] }) })
  const labelOf = (name: string) => catalog.find(item => item.name === name)?.label ?? ''
  return <div className="settings-block" style={{ marginTop: 20 }}>
    <h3>Model thực sự đang có hiệu lực theo tác vụ</h3>
    <p className="hint">Nguồn DB task route là ưu tiên vận hành. Nếu có emergency override từ VPS, Radar hiển thị rõ nguồn thay vì âm thầm ghi đè cài đặt.</p>
    {!routes.length && <p className="hint">Chưa có route theo tác vụ. Thêm route đầu tiên bên dưới.</p>}
    <div className="table-scroll"><table><thead><tr><th>Tác vụ</th><th>Provider / model hiệu lực</th><th>Nguồn</th></tr></thead>
      <tbody>{routes.map(route => <tr key={route.task}><td><code>{route.task}</code>{labelOf(route.task) && <><br /><span className="muted small">{labelOf(route.task)}</span></>}</td><td><code>{route.effective.provider}/{route.effective.model || 'default'}</code></td><td>{route.effective.config_source}{route.effective.emergency_key ? ` (${route.effective.emergency_key})` : ''} <button type="button" className="btn btn-secondary" onClick={() => remove.mutate(route.task)}>Bỏ</button></td></tr>)}</tbody>
    </table></div>
    <div style={{ display: 'flex', gap: 8, marginTop: 12, flexWrap: 'wrap' }}>
      {/* Danh sách CHỌN, không phải ô gõ tay: gõ tay nghĩa là chỉ đổi được
          thứ mình đã biết tên, mà không ai đoán ra `rb_prospect_search` là gì. */}
      <select value={task} onChange={e => applyTask(e.target.value)} aria-label="Tác vụ AI">
        {groups.map(group => {
          const rows = catalog.filter(item => item.group === group)
          if (!rows.length) return null
          return <optgroup key={group} label={group}>
            {rows.map(item => <option key={item.name} value={item.name}>{item.label}</option>)}
          </optgroup>
        })}
      </select>
      <select value={provider} onChange={e => setProvider(e.target.value)}>{providers.map(item => <option key={item.provider} value={item.provider}>{item.label}</option>)}</select>
      {/* Combobox, không phải select: chọn trong danh mục HOẶC gõ tay. Tên model
          đổi liên tục nên danh mục sẽ luôn thiếu — khoá vào nó là tự trói. */}
      <input value={model} onChange={e => setModel(e.target.value)} list={`ds-model-${provider}`}
             placeholder="Model (trống = default)" aria-label="Model tác vụ" style={{ minWidth: 260 }} />
      <datalist id={`ds-model-${provider}`}>
        {choices.map(m => <option key={m.id} value={m.id}>{m.label}{m.discovered ? ' · mới dò được' : ''}</option>)}
      </datalist>
      <button type="button" className="btn btn-primary"
              disabled={!task.trim() || save.isPending || !!chan}
              onClick={() => save.mutate()}>Lưu route tác vụ</button>
    </div>
    {selected && <p className="hint" style={{ marginTop: 8 }}>
      <strong>{selected.label}</strong> — {selected.description}
      {' '}<em>{KIND_HINT[selected.kind] ?? ''}</em>
      {selected.default_model && <>
        {' '}Mặc định đề xuất: <code>{selected.default_provider}/{selected.default_model}</code>.
      </>}
    </p>}
    {chosen?.note && !chan && <p className="hint" style={{ marginTop: 4 }}>
      <strong>{chosen.label}</strong> — {chosen.note}
    </p>}
    {model.trim() && !chosen && !chan && <p className="hint" style={{ marginTop: 4 }}>
      <code>{model}</code> không có trong danh mục <strong>{provider}</strong>. Vẫn lưu được — nhưng
      nếu gõ sai mã thì không ai báo: router cứ gửi đi, nhà cung cấp trả 404, và tác vụ lặng lẽ
      rơi sang provider sau. Bấm “Lấy danh sách model” ở phần nhà cung cấp để đối chiếu.
    </p>}
    {chan && <p className="hint" style={{ marginTop: 4, color: 'var(--danger, #c0392b)' }}>
      <strong>Không lưu được.</strong> {chan}
    </p>}
  </div>
}

/** Loại model hợp với từng tác vụ. Không có gợi ý này thì người vận hành phải
 *  tự đoán vì sao ⑤ nên dùng model khác ①. */
const KIND_HINT: Record<string, string> = {
  json: 'Nên chọn model NHANH, trả JSON chuẩn.',
  viet: 'Nên chọn model hành văn tốt nhất — đây là chữ người dùng đọc thấy.',
  doc: 'Nên chọn model RẺ mà đọc được nhiều chữ.',
  embedding: 'BẮT BUỘC model embedding (sinh vector), không phải model sinh văn.',
  vision: 'BẮT BUỘC model đọc được ảnh — chọn sai thì CV scan vào kho thành rỗng mà không báo lỗi.',
}

const CONFIG_SOURCE_LABEL: Record<string, string> = {
  db_task_route: 'DB · route theo tác vụ',
  registry_default: 'Mặc định sổ đăng ký (chưa lưu vào DB)',
  db_provider_default: 'DB · thứ tự provider',
  env_bootstrap: 'ENV · bootstrap/mặc định',
  env_emergency: 'ENV · emergency override',
}

function EffectiveTasksPanel({ tasks }: { tasks: EffectiveTaskConfig[] }) {
  if (!tasks.length) return null
  return (
    <div className="settings-block" style={{ marginTop: 20 }}>
      <h3>Provider / model đang THỰC SỰ chạy theo từng tác vụ</h3>
      <p className="hint">
        Gồm cả tác vụ chưa có route (đang chạy bằng biến môi trường). Nếu cột &ldquo;Nguồn&rdquo; là
        ENV mà bạn đã cấu hình ở trên, nghĩa là biến môi trường trên VPS đang ghi đè — gỡ biến đó
        hoặc tạo route DB để <code>/settings</code> thắng.
      </p>
      <div className="table-scroll">
        <table>
          <thead>
            <tr><th>Tác vụ</th><th>Provider / model hiệu lực</th><th>Nguồn</th><th>Biến ENV đang ghi đè</th></tr>
          </thead>
          <tbody>
            {tasks.map((t) => {
              const envVar = t.model_env_override || t.emergency_key || t.emergency_model_key || ''
              const fromEnv = t.config_source?.startsWith('env')
              return (
                <tr key={t.task}>
                  <td><code>{t.task}</code></td>
                  <td><code>{t.provider || '—'}/{t.model || 'default'}</code></td>
                  <td>
                    <span className={`badge ${fromEnv ? 'warn' : 'ok'}`}>
                      {CONFIG_SOURCE_LABEL[t.config_source] || t.config_source}
                    </span>
                  </td>
                  <td>{envVar ? <code>{envVar}</code> : <span className="hint">—</span>}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function EmbeddingModePanel() {
  const qc = useQueryClient()
  const q = useQuery({ queryKey: ['embedding-config'], queryFn: () => api.embeddingConfig(true), retry: false })
  const [draft, setDraft] = useState<Partial<EmbeddingConfig>>({})
  const [msg, setMsg] = useState('')
  const cfg = q.data
  const v = <K extends keyof EmbeddingConfig>(k: K): EmbeddingConfig[K] | undefined =>
    (draft[k] as EmbeddingConfig[K] | undefined) ?? cfg?.[k]

  const save = useMutation({
    mutationFn: () => api.embeddingConfigSave({
      mode: v('mode') as EmbeddingConfig['mode'],
      selfhost_base_url: v('selfhost_base_url') as string,
      selfhost_model: v('selfhost_model') as string,
      gemini_model: v('gemini_model') as string,
      greennode_model: v('greennode_model') as string,
      dimensions: v('dimensions') as number,
    }),
    onSuccess: (data) => {
      qc.setQueryData(['embedding-config'], data)
      setDraft({})
      setMsg(data.needs_rebackfill
        ? '✓ Đã lưu. Đổi nguồn ⇒ toàn bộ vector được đánh dấu tính lại; worker nền sẽ backfill dần.'
        : '✓ Đã lưu.')
      setTimeout(() => setMsg(''), 6000)
    },
    onError: (e: Error) => setMsg(`⚠️ ${e.message}`),
  })

  if (q.isLoading || !cfg) return <div className="settings-block" style={{ marginTop: 20 }}><h3>Nguồn embedding (hỏi đáp kho CV)</h3><p className="hint">Đang tải…</p></div>

  const cov = cfg.coverage
  const pct = (a: number, b: number) => (b ? Math.round((100 * a) / b) : 0)
  const mode = v('mode')

  return (
    <div className="settings-block" style={{ marginTop: 20 }}>
      <h3>Nguồn embedding — hỏi đáp kho CV kiểu NotebookLM</h3>
      <p className="hint">
        Chọn nơi tính vector ngữ nghĩa cho CV: <b>GreenNode MaaS</b> (ưu tiên), <b>Gemini API</b> hay
        <b> tự host</b> (Ollama trong VPS — không quota, CV không rời máy chủ, chậm hơn trên VPS nhỏ).
        Đổi nguồn sẽ tự đánh dấu backfill lại.
      </p>

      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', margin: '10px 0' }}>
        {cfg.mode_choices.map((c) => (
          <button key={c.value} type="button"
            className={`pill-btn ${mode === c.value ? 'active' : ''}`}
            onClick={() => setDraft((d) => ({ ...d, mode: c.value as EmbeddingConfig['mode'] }))}>
            {c.label}
          </button>
        ))}
      </div>

      {mode === 'greennode' && (
        <div className="form-row-2">
          <div>
            <label><span>Mã model embedding GreenNode</span></label>
            <input className="input-text" value={v('greennode_model') as string}
              onChange={(e) => setDraft((d) => ({ ...d, greennode_model: e.target.value }))}
              placeholder="BAAI/bge-m3" />
            <small className="field-hint">
              {cfg.greennode_key_present
                ? 'GreenNode đã bật và có khoá ✓'
                : '⚠️ GreenNode chưa bật hoặc chưa có khoá ở phần Nhà cung cấp AI.'}
            </small>
          </div>
          <div style={{ maxWidth: 160 }}>
            <label><span>Số chiều</span></label>
            <input type="number" className="input-text" value={v('dimensions') as number}
              onChange={(e) => setDraft((d) => ({ ...d, dimensions: Number(e.target.value) }))} />
            <small className="field-hint">BGE-M3 thường trả 1024 chiều; probe sẽ hiển thị số chiều thực tế.</small>
          </div>
        </div>
      )}

      {mode === 'gemini' && (
        <div className="form-row-2">
          <div>
            <label><span>Mã model embedding Gemini</span></label>
            <input className="input-text" value={v('gemini_model') as string}
              onChange={(e) => setDraft((d) => ({ ...d, gemini_model: e.target.value }))}
              placeholder="gemini-embedding-001" />
            <small className="field-hint">
              {cfg.gemini_key_present
                ? 'Khoá Gemini đã cấu hình ở phần Nhà cung cấp AI ✓'
                : '⚠️ Chưa có khoá Gemini — thêm ở thẻ Gemini phía trên.'}
            </small>
          </div>
          <div style={{ maxWidth: 160 }}>
            <label><span>Số chiều</span></label>
            <input type="number" className="input-text" value={v('dimensions') as number}
              onChange={(e) => setDraft((d) => ({ ...d, dimensions: Number(e.target.value) }))} />
            <small className="field-hint">Giữ 768 để hoán đổi với tự host không phải re-pin cột.</small>
          </div>
        </div>
      )}

      {mode === 'selfhost' && (
        <div className="form-row-2">
          <div>
            <label><span>Endpoint (OpenAI-compatible /embeddings)</span></label>
            <input className="input-text" value={v('selfhost_base_url') as string}
              onChange={(e) => setDraft((d) => ({ ...d, selfhost_base_url: e.target.value }))}
              placeholder="http://ollama:11434/v1" />
          </div>
          <div>
            <label><span>Model</span></label>
            <input className="input-text" value={v('selfhost_model') as string}
              onChange={(e) => setDraft((d) => ({ ...d, selfhost_model: e.target.value }))}
              placeholder="nomic-embed-text" />
            <small className="field-hint">
              Kéo model: <code>docker exec msbradar-ollama ollama pull &lt;model&gt;</code>.
              Box mạnh: <code>bge-m3</code> (1024d, đa ngữ tốt hơn).
            </small>
          </div>
        </div>
      )}

      {mode === 'off' && (
        <p className="hint">Dense tắt — hỏi đáp kho CV chỉ dùng full-text (khớp từ khoá, vẫn có trích dẫn).</p>
      )}

      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginTop: 12, flexWrap: 'wrap' }}>
        <button type="button" className="btn btn-primary" disabled={save.isPending || !Object.keys(draft).length}
          onClick={() => save.mutate()}>
          {save.isPending ? 'Đang lưu…' : 'Lưu & áp dụng'}
        </button>
        <span className={`badge ${cfg.active ? 'ok' : 'warn'}`}>
          {cfg.active
            ? `Đang chạy: ${cfg.effective?.provider}/${cfg.effective?.model}`
            : 'Chưa hoạt động'}
        </span>
        {cfg.probe && (
          <span className={`badge ${cfg.probe.ok ? 'ok' : 'err'}`}>
            {cfg.probe.ok ? `Test OK · ${cfg.probe.dims} chiều` : `Test lỗi (${cfg.probe.model || 'chưa cấu hình'})`}
          </span>
        )}
        {msg && <span className="feedback-badge">{msg}</span>}
      </div>

      <div className="hint" style={{ marginTop: 10 }}>
        Phủ vector: hồ sơ <b>{cov.projections_embedded}/{cov.projections}</b> ({pct(cov.projections_embedded, cov.projections)}%)
        · đoạn CV <b>{cov.chunks_embedded}/{cov.chunks}</b> ({pct(cov.chunks_embedded, cov.chunks)}%)
      </div>
    </div>
  )
}

// ==========================================
// Component Chính: Settings Router Tabs
// ==========================================
// ==========================================
// 4. Phân hệ Thống kê Token & Mô hình AI
// ==========================================
function getProviderInfo(provider: string) {
  const p = provider.toLowerCase()
  switch (p) {
    case 'greennode':
      return { label: 'GreenNode', color: '#10b981', bg: 'rgba(16, 185, 129, 0.12)' }
    case 'gemini':
      return { label: 'Google Gemini', color: '#3b82f6', bg: 'rgba(59, 130, 246, 0.12)' }
    case 'openai':
      return { label: 'OpenAI', color: '#6366f1', bg: 'rgba(99, 102, 241, 0.12)' }
    case 'deepseek':
      return { label: 'DeepSeek', color: '#0284c7', bg: 'rgba(2, 132, 199, 0.12)' }
    case 'anthropic':
      return { label: 'Anthropic', color: '#d97706', bg: 'rgba(217, 119, 6, 0.12)' }
    case 'groq':
      return { label: 'Groq', color: '#ea580c', bg: 'rgba(234, 88, 12, 0.12)' }
    case 'ollama':
      return { label: 'Ollama', color: '#8b5cf6', bg: 'rgba(139, 92, 246, 0.12)' }
    default:
      return { label: provider, color: '#64748b', bg: 'rgba(100, 116, 139, 0.12)' }
  }
}

function TokenUsageSection({ usage }: { usage: { data?: UsageSummary; isLoading: boolean } }) {
  const [viewMode, setViewMode] = useState<'grouped' | 'flat'>('grouped')
  const [searchFilter, setSearchFilter] = useState('')

  const data = usage.data
  const totalCalls = data?.total_calls ?? 0
  const failedCalls = data?.failed_calls ?? 0
  const totalTokens = data?.total_tokens ?? (data?.by_provider ?? []).reduce((s: number, r: UsageProviderRow) => s + r.total_tokens, 0)
  const promptTokens = data?.total_prompt_tokens ?? (data?.by_provider ?? []).reduce((s: number, r: UsageProviderRow) => s + r.prompt_tokens, 0)
  const completionTokens = data?.total_completion_tokens ?? (data?.by_provider ?? []).reduce((s: number, r: UsageProviderRow) => s + r.completion_tokens, 0)
  const allModels: UsageModelRow[] = data?.by_model ?? []
  const uniqueModelsCount = allModels.length

  const filteredModels = allModels.filter(
    (m: UsageModelRow) =>
      m.model.toLowerCase().includes(searchFilter.toLowerCase()) ||
      m.provider.toLowerCase().includes(searchFilter.toLowerCase())
  )

  const filteredProviders = (data?.by_provider ?? []).map((prov: UsageProviderRow) => {
    const models = (prov.models ?? []).filter(
      (m: UsageModelRow) =>
        m.model.toLowerCase().includes(searchFilter.toLowerCase()) ||
        prov.provider.toLowerCase().includes(searchFilter.toLowerCase())
    )
    return { ...prov, models }
  }).filter((prov) => (prov.models?.length ?? 0) > 0 || !searchFilter)

  return (
    <div className="settings-section-card">
      <div className="section-intro">
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: '12px' }}>
          <div>
            <h2>Thống kê Lượt gọi &amp; Mức sử dụng Token theo Mô hình</h2>
            <p className="hint">
              Báo cáo kiểm toán chi tiết số lượng token đầu vào (prompt) và đầu ra (completion) của từng mô hình tương ứng trên mỗi nhà cung cấp AI.
            </p>
          </div>
          {totalCalls > 0 && (
            <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
              <div className="items-per-page-options" style={{ margin: 0 }}>
                <button
                  type="button"
                  className={`pill-btn ${viewMode === 'grouped' ? 'active' : ''}`}
                  onClick={() => setViewMode('grouped')}
                >
                  🏢 Gom theo Nhà cung cấp
                </button>
                <button
                  type="button"
                  className={`pill-btn ${viewMode === 'flat' ? 'active' : ''}`}
                  onClick={() => setViewMode('flat')}
                >
                  📊 Tất cả mô hình ({uniqueModelsCount})
                </button>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* KPI Overview Cards */}
      {totalCalls > 0 && (
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))',
            gap: '12px',
            marginBottom: '20px',
          }}
        >
          <div style={{ background: 'var(--bg)', padding: '14px 16px', borderRadius: '10px', border: '1px solid var(--border)' }}>
            <div style={{ fontSize: '12px', color: 'var(--muted)', marginBottom: '4px' }}>Tổng lượt gọi AI</div>
            <div style={{ fontSize: '20px', fontWeight: 700, color: 'var(--text)' }}>
              {totalCalls.toLocaleString('vi-VN')}
            </div>
            {failedCalls > 0 ? (
              <div style={{ fontSize: '11px', color: '#ef4444', marginTop: '2px' }}>
                ⚠️ {failedCalls.toLocaleString('vi-VN')} lượt lỗi ({((failedCalls / totalCalls) * 100).toFixed(1)}%)
              </div>
            ) : (
              <div style={{ fontSize: '11px', color: '#10b981', marginTop: '2px' }}>
                ✓ 100% thành công
              </div>
            )}
          </div>

          <div style={{ background: 'var(--bg)', padding: '14px 16px', borderRadius: '10px', border: '1px solid var(--border)' }}>
            <div style={{ fontSize: '12px', color: 'var(--muted)', marginBottom: '4px' }}>Tổng Token tiêu thụ</div>
            <div style={{ fontSize: '20px', fontWeight: 700, color: 'var(--accent, #3b82f6)' }}>
              {totalTokens.toLocaleString('vi-VN')}
            </div>
            <div style={{ fontSize: '11px', color: 'var(--muted)', marginTop: '2px' }}>
              Vào: {promptTokens.toLocaleString('vi-VN')} • Ra: {completionTokens.toLocaleString('vi-VN')}
            </div>
          </div>

          <div style={{ background: 'var(--bg)', padding: '14px 16px', borderRadius: '10px', border: '1px solid var(--border)' }}>
            <div style={{ fontSize: '12px', color: 'var(--muted)', marginBottom: '4px' }}>Số mô hình đã dùng</div>
            <div style={{ fontSize: '20px', fontWeight: 700, color: 'var(--text)' }}>
              {uniqueModelsCount} <span style={{ fontSize: '13px', fontWeight: 'normal', color: 'var(--muted)' }}>mô hình</span>
            </div>
            <div style={{ fontSize: '11px', color: 'var(--muted)', marginTop: '2px' }}>
              Trên {(data?.by_provider ?? []).length} nhà cung cấp
            </div>
          </div>

          <div style={{ background: 'var(--bg)', padding: '14px 16px', borderRadius: '10px', border: '1px solid var(--border)' }}>
            <div style={{ fontSize: '12px', color: 'var(--muted)', marginBottom: '4px' }}>Nhà cung cấp chính</div>
            <div style={{ fontSize: '16px', fontWeight: 700, color: '#10b981', textTransform: 'capitalize' }}>
              {data?.primary_provider ?? 'greennode'}
            </div>
            <div style={{ fontSize: '11px', color: 'var(--muted)', marginTop: '2px' }}>
              {data?.fallback_calls ? `Dự phòng: ${data.fallback_calls.toLocaleString('vi-VN')} lượt` : 'Chưa cần dùng dự phòng'}
            </div>
          </div>
        </div>
      )}

      {/* Filter input */}
      {totalCalls > 0 && uniqueModelsCount > 3 && (
        <div style={{ marginBottom: '12px' }}>
          <input
            type="text"
            placeholder="🔍 Tìm kiếm theo tên mô hình hoặc nhà cung cấp..."
            value={searchFilter}
            onChange={(e) => setSearchFilter(e.target.value)}
            style={{
              width: '100%',
              maxWidth: '360px',
              padding: '8px 12px',
              fontSize: '13px',
              borderRadius: '8px',
              border: '1px solid var(--border)',
              background: 'var(--bg)',
              color: 'var(--text)',
            }}
          />
        </div>
      )}

      {/* Main Table Content */}
      {totalCalls === 0 ? (
        <div style={{ padding: '32px 16px', textAlign: 'center', color: 'var(--muted)' }}>
          <p style={{ margin: 0, fontSize: '14px' }}>Chưa có lượt gọi nào được ghi nhận vào hệ thống.</p>
        </div>
      ) : viewMode === 'grouped' ? (
        <div style={{ overflowX: 'auto', marginTop: '8px' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead>
              <tr style={{ borderBottom: '1px solid var(--border)' }}>
                <th style={{ textAlign: 'left', padding: '10px 12px' }}>Nhà cung cấp / Mô hình AI</th>
                <th className="num" style={{ padding: '10px 12px' }}>Lượt gọi</th>
                <th className="num" style={{ padding: '10px 12px' }}>Token vào (Prompt)</th>
                <th className="num" style={{ padding: '10px 12px' }}>Token ra (Completion)</th>
                <th className="num" style={{ padding: '10px 12px' }}>Tổng Token</th>
                <th className="num" style={{ padding: '10px 12px' }}>Độ trễ TB</th>
              </tr>
            </thead>
            <tbody>
              {filteredProviders.map((prov: UsageProviderRow) => {
                const info = getProviderInfo(prov.provider)
                return (
                  <React.Fragment key={prov.provider}>
                    {/* Provider summary row */}
                    <tr
                      style={{
                        background: 'var(--bg-muted, rgba(0,0,0,0.02))',
                        borderTop: '2px solid var(--border)',
                        borderBottom: '1px solid var(--border)',
                        fontWeight: 600,
                      }}
                    >
                      <td style={{ padding: '12px 12px' }}>
                        <div style={{ display: 'inline-flex', alignItems: 'center', gap: '8px' }}>
                          <ProviderLogo provider={prov.provider} />
                          <span
                            style={{
                              padding: '2px 8px',
                              borderRadius: '6px',
                              fontSize: '12px',
                              fontWeight: 700,
                              color: info.color,
                              background: info.bg,
                            }}
                          >
                            {info.label}
                          </span>
                          <span style={{ fontSize: '12px', color: 'var(--muted)', fontWeight: 'normal' }}>
                            ({(prov.models ?? []).length} mô hình)
                          </span>
                        </div>
                      </td>
                      <td className="num" style={{ padding: '12px 12px' }}>
                        {prov.calls.toLocaleString('vi-VN')}
                        {prov.failed > 0 && (
                          <span style={{ marginLeft: '6px', fontSize: '11px', color: '#ef4444' }}>
                            ({prov.failed} lỗi)
                          </span>
                        )}
                      </td>
                      <td className="num" style={{ padding: '12px 12px' }}>{prov.prompt_tokens.toLocaleString('vi-VN')}</td>
                      <td className="num" style={{ padding: '12px 12px' }}>{prov.completion_tokens.toLocaleString('vi-VN')}</td>
                      <td className="num" style={{ padding: '12px 12px', color: info.color }}>
                        <strong>{prov.total_tokens.toLocaleString('vi-VN')}</strong>
                      </td>
                      <td className="num" style={{ padding: '12px 12px', color: 'var(--muted)' }}>
                        {prov.avg_latency_ms ? `${prov.avg_latency_ms} ms` : '—'}
                      </td>
                    </tr>

                    {/* Specific Model Rows */}
                    {(prov.models ?? []).map((m: UsageModelRow) => (
                      <tr
                        key={`${prov.provider}-${m.model}`}
                        style={{
                          borderBottom: '1px solid var(--border)',
                          fontSize: '13px',
                        }}
                      >
                        <td style={{ padding: '10px 12px 10px 36px' }}>
                          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                            <span style={{ color: 'var(--muted)', fontSize: '12px' }}>↳</span>
                            <code
                              style={{
                                background: 'var(--code-bg, rgba(0,0,0,0.05))',
                                padding: '2px 8px',
                                borderRadius: '4px',
                                fontSize: '12px',
                                color: 'var(--text)',
                                border: '1px solid var(--border)',
                                fontFamily: 'monospace',
                              }}
                            >
                              {m.model}
                            </code>
                          </div>
                        </td>
                        <td className="num" style={{ padding: '10px 12px' }}>
                          {m.calls.toLocaleString('vi-VN')}
                          {m.failed > 0 && (
                            <span style={{ marginLeft: '4px', fontSize: '11px', color: '#ef4444' }}>
                              ({m.failed} lỗi)
                            </span>
                          )}
                        </td>
                        <td className="num" style={{ padding: '10px 12px', color: 'var(--muted)' }}>
                          {m.prompt_tokens.toLocaleString('vi-VN')}
                        </td>
                        <td className="num" style={{ padding: '10px 12px', color: 'var(--muted)' }}>
                          {m.completion_tokens.toLocaleString('vi-VN')}
                        </td>
                        <td className="num" style={{ padding: '10px 12px' }}>
                          <strong>{m.total_tokens.toLocaleString('vi-VN')}</strong>
                        </td>
                        <td className="num" style={{ padding: '10px 12px', color: 'var(--muted)' }}>
                          {m.avg_latency_ms ? `${m.avg_latency_ms} ms` : '—'}
                        </td>
                      </tr>
                    ))}
                  </React.Fragment>
                )
              })}
            </tbody>
          </table>
        </div>
      ) : (
        /* Flat View of All Models */
        <div style={{ overflowX: 'auto', marginTop: '8px' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead>
              <tr style={{ borderBottom: '1px solid var(--border)' }}>
                <th style={{ textAlign: 'left', padding: '10px 12px' }}>Nhà cung cấp</th>
                <th style={{ textAlign: 'left', padding: '10px 12px' }}>Mô hình AI (Model)</th>
                <th className="num" style={{ padding: '10px 12px' }}>Lượt gọi</th>
                <th className="num" style={{ padding: '10px 12px' }}>Token vào</th>
                <th className="num" style={{ padding: '10px 12px' }}>Token ra</th>
                <th className="num" style={{ padding: '10px 12px' }}>Tổng Token</th>
                <th className="num" style={{ padding: '10px 12px' }}>Độ trễ TB</th>
              </tr>
            </thead>
            <tbody>
              {filteredModels.map((m: UsageModelRow) => {
                const info = getProviderInfo(m.provider)
                return (
                  <tr key={`${m.provider}-${m.model}`} style={{ borderBottom: '1px solid var(--border)', fontSize: '13px' }}>
                    <td style={{ padding: '10px 12px' }}>
                      <div style={{ display: 'inline-flex', alignItems: 'center', gap: '6px' }}>
                        <ProviderLogo provider={m.provider} />
                        <span
                          style={{
                            padding: '2px 6px',
                            borderRadius: '4px',
                            fontSize: '11px',
                            fontWeight: 700,
                            color: info.color,
                            background: info.bg,
                          }}
                        >
                          {info.label}
                        </span>
                      </div>
                    </td>
                    <td style={{ padding: '10px 12px' }}>
                      <code
                        style={{
                          background: 'var(--code-bg, rgba(0,0,0,0.05))',
                          padding: '3px 8px',
                          borderRadius: '4px',
                          fontSize: '12px',
                          color: 'var(--text)',
                          border: '1px solid var(--border)',
                          fontFamily: 'monospace',
                        }}
                      >
                        {m.model}
                      </code>
                    </td>
                    <td className="num" style={{ padding: '10px 12px' }}>
                      {m.calls.toLocaleString('vi-VN')}
                      {m.failed > 0 && (
                        <span style={{ marginLeft: '4px', fontSize: '11px', color: '#ef4444' }}>
                          ({m.failed} lỗi)
                        </span>
                      )}
                    </td>
                    <td className="num" style={{ padding: '10px 12px', color: 'var(--muted)' }}>
                      {m.prompt_tokens.toLocaleString('vi-VN')}
                    </td>
                    <td className="num" style={{ padding: '10px 12px', color: 'var(--muted)' }}>
                      {m.completion_tokens.toLocaleString('vi-VN')}
                    </td>
                    <td className="num" style={{ padding: '10px 12px' }}>
                      <strong style={{ color: info.color }}>{m.total_tokens.toLocaleString('vi-VN')}</strong>
                    </td>
                    <td className="num" style={{ padding: '10px 12px', color: 'var(--muted)' }}>
                      {m.avg_latency_ms ? `${m.avg_latency_ms} ms` : '—'}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}

      <ChiPhiTheoChang rows={data?.by_task ?? []} />
      <p className="hint">
        Khoảng đo: {data?.window_hours ?? 24} giờ gần nhất. Độ trễ lượt thành công:
        {' '}P50 {data?.p50_latency_ms == null ? 'chưa có dữ liệu' : `${data.p50_latency_ms} ms`},
        {' '}P95 {data?.p95_latency_ms == null ? 'chưa có dữ liệu' : `${data.p95_latency_ms} ms`}.
      </p>
      {data?.failure_causes && <p className="hint">
        Lỗi chờ quá hạn: {data.failure_causes.timeout ?? 0} ·
        {' '}Giới hạn lượt gọi: {data.failure_causes.rate_limit ?? 0} ·
        {' '}Xác thực: {data.failure_causes.authentication ?? 0} ·
        {' '}Khác: {data.failure_causes.other ?? 0}
      </p>}

      {failedCalls > 0 && (
        <p className="hint" style={{ marginTop: '16px', color: '#ef4444' }}>
          ⚠️ Hệ thống ghi nhận {failedCalls.toLocaleString('vi-VN')} lượt gọi thất bại (do quá hạn mức hoặc sự cố mạng) trên tổng số{' '}
          {totalCalls.toLocaleString('vi-VN')} lượt gọi.
        </p>
      )}
    </div>
  )
}

/** Chi phí theo CHẶNG, không phải theo nhà cung cấp.
 *
 *  Bảng `by_model` trả lời "nhà cung cấp nào tốn". Bảng này trả lời "chặng nào
 *  tốn" — và chỉ câu thứ hai mới dẫn tới hành động: biết ③ nuốt phần lớn token
 *  thì mới biết nên đi tối ưu ③ chứ không phải ⑤. */
function ChiPhiTheoChang({ rows }: { rows: UsageTaskRow[] }) {
  if (!rows.length) return null
  const dinh = Math.max(...rows.map(r => r.token_share), 0.0001)
  return (
    <div style={{ marginTop: 24 }}>
      <h4 style={{ margin: '0 0 4px' }}>Token &amp; độ trễ theo chặng</h4>
      <p className="hint" style={{ marginTop: 0 }}>
        Chặng chiếm phần token lớn nhất là chặng đáng đi tối ưu — không nhất thiết
        là chặng chạy nhiều lượt nhất.
      </p>
      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              <th>Chặng</th><th className="num">Lượt</th><th className="num">Token</th>
              <th>Phần token</th><th className="num">Độ trễ TB</th><th className="num">Lỗi</th>
            </tr>
          </thead>
          <tbody>
            {rows.map(r => (
              <tr key={r.task}>
                <td>
                  {r.label}
                  <br /><code className="muted small">{r.task}</code>
                </td>
                <td className="num">{r.calls.toLocaleString('vi-VN')}</td>
                <td className="num">{r.tokens.toLocaleString('vi-VN')}</td>
                <td>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <div style={{ flex: 1, minWidth: 60, height: 6, borderRadius: 3,
                                  background: 'var(--border)' }}>
                      <div style={{ width: `${(r.token_share / dinh) * 100}%`, height: '100%',
                                    borderRadius: 3, background: 'var(--accent, #3b82f6)' }} />
                    </div>
                    <span className="muted small">{(r.token_share * 100).toFixed(1)}%</span>
                  </div>
                </td>
                <td className="num">{r.avg_latency_ms ? `${r.avg_latency_ms} ms` : '—'}</td>
                <td className="num">{r.failed || '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

type SettingsTab = 'appearance' | 'search' | 'ai' | 'usage' | 'memory'

export default function Settings() {
  const [activeTab, setActiveTab] = useState<SettingsTab>('appearance')
  const providers = useQuery({ queryKey: ['ai-providers'], queryFn: api.aiProviders, retry: false })
  const usage = useQuery({ queryKey: ['ai-usage'], queryFn: api.aiUsage, retry: false })

  const order = providers.data?.active_order ?? []
  const dungDuoc = new Set(providers.data?.available ?? [])

  return (
    <div className="settings-page-wrapper">
      {/* Sub-tab Navigation Bar */}
      <div className="settings-subtabs">
        <button
          type="button"
          className={`settings-tab-btn ${activeTab === 'appearance' ? 'active' : ''}`}
          onClick={() => setActiveTab('appearance')}
        >
          🎨 Giao diện &amp; Thương hiệu
        </button>
        <button
          type="button"
          className={`settings-tab-btn ${activeTab === 'search' ? 'active' : ''}`}
          onClick={() => setActiveTab('search')}
        >
          🎯 Trải nghiệm &amp; Tìm kiếm
        </button>
        <button
          type="button"
          className={`settings-tab-btn ${activeTab === 'ai' ? 'active' : ''}`}
          onClick={() => setActiveTab('ai')}
        >
          🤖 Nhà cung cấp AI
        </button>
        <button
          type="button"
          className={`settings-tab-btn ${activeTab === 'usage' ? 'active' : ''}`}
          onClick={() => setActiveTab('usage')}
        >
          📊 Mức sử dụng Token
        </button>
        <button
          type="button"
          className={`settings-tab-btn ${activeTab === 'memory' ? 'active' : ''}`}
          onClick={() => setActiveTab('memory')}
        >
          🧠 Radar ghi nhớ
        </button>
      </div>

      {/* Tab Content */}
      <div className="settings-tab-content">
        {activeTab === 'appearance' && <AppearanceSettings />}

        {activeTab === 'search' && <SearchAndPrivacySettings />}

        {activeTab === 'ai' && (
          <div className="settings-section-card">
            <div className="section-intro">
              <h2>Cấu hình Mô hình &amp; Nhà cung cấp AI</h2>
              <p className="hint">
                Thứ tự ưu tiên gọi:{' '}
                {order.length ? <code>{order.join(' → ')}</code> : <em>chưa có</em>}. Nhà cung cấp
                chưa có khoá sẽ tự bị bỏ qua an toàn và fallback về các nhà cung cấp sẵn sàng.
              </p>
            </div>

            <div className="providers-list">
              {(providers.data?.results ?? []).map((row) => (
                <ProviderCard
                  key={row.provider}
                  row={row}
                  dangDung={dungDuoc.has(row.provider)}
                />
              ))}
            </div>
            <EffectiveTaskRoutes routes={providers.data?.task_routes ?? []} providers={providers.data?.results ?? []}
                                 catalog={providers.data?.task_catalog ?? []} groups={providers.data?.task_groups ?? []}
                                 models={providers.data?.models ?? {}} kindRequires={providers.data?.kind_requires ?? {}} />
            <EffectiveTasksPanel tasks={providers.data?.effective_tasks ?? []} />
            <EmbeddingModePanel />
          </div>
        )}

        {activeTab === 'usage' && <TokenUsageSection usage={usage} />}

        {activeTab === 'memory' && <MemoryPanel />}
      </div>
    </div>
  )
}
