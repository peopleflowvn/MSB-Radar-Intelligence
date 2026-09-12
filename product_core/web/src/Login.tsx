import { useMutation } from '@tanstack/react-query'
import { useMemo, useState } from 'react'
import { api, ApiError, Identity } from './api'
import { PRESET_PALETTES, useCustomTheme } from './CustomThemeContext'
import { ThreeRadarCanvas } from './ThreeRadarCanvas'

type Realm = 'tntalent' | 'msb'
type Screen = 'identify' | 'password' | 'otp' | 'reset'
const SUPPORT_EMAIL = 'tunglh2@tntalent.vn'

export default function Login({ onSuccess }: { onSuccess: (identity: Identity) => void }) {
  const { appName, appTagline, appIcon, appLogoUrl, colorPreset, customColor } = useCustomTheme()
  const [screen, setScreen] = useState<Screen>('identify')
  const [identifier, setIdentifier] = useState('')
  const [realm, setRealm] = useState<Realm | null>(null)
  const [password, setPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [code, setCode] = useState('')
  const [message, setMessage] = useState('')

  const login = useMutation({ mutationFn: () => api.login(identifier, password), onSuccess })
  const discovery = useMutation({
    mutationFn: () => api.loginDiscovery(identifier.trim()),
    onSuccess: (data) => {
      setMessage('')
      if (data.mode === 'local') {
        setRealm(null); setPassword(''); setScreen('password')
        return
      }
      const targetRealm = data.realm!
      setRealm(targetRealm); setCode(''); setScreen('otp')
      otpRequest.mutate({ realm: targetRealm, identifier: identifier.trim() })
    },
  })
  const otpRequest = useMutation({
    mutationFn: (input: { realm: Realm; identifier: string }) => api.emailOtpRequest(input.realm, input.identifier),
    onSuccess: (data) => setMessage(data.detail),
  })
  const otpVerify = useMutation({ mutationFn: () => api.emailOtpVerify(realm!, identifier, code), onSuccess })
  const resetRequest = useMutation({
    mutationFn: () => api.localPasswordResetRequest(identifier),
    onSuccess: (data) => setMessage(data.detail),
  })
  const resetConfirm = useMutation({
    mutationFn: () => api.localPasswordResetConfirm(identifier, code, password),
    onSuccess: (data) => {
      setMessage(data.detail)
      setPassword('')
      setCode('')
      setScreen('password')
    },
  })

  const error = discovery.error || login.error || otpRequest.error || otpVerify.error || resetRequest.error || resetConfirm.error

  // Dynamic theme hex for ThreeJS Radar
  const radarThemeColor = useMemo(() => {
    if (colorPreset === 'custom' && customColor) return customColor
    return PRESET_PALETTES[colorPreset]?.primary || '#FF8A33'
  }, [colorPreset, customColor])

  function continueFromIdentifier() {
    setMessage('')
    discovery.mutate()
  }

  function back() {
    setMessage('')
    setCode('')
    setPassword('')
    setScreen('identify')
  }

  return (
    <div
      className="radar-login-layout"
      style={{ '--radar-theme-color': radarThemeColor } as React.CSSProperties}
    >
      {/* 3D Visual Experience Panel - 100% Dedicated to 3D Radar */}
      <div className="radar-hero-panel">
        <ThreeRadarCanvas colorHex={radarThemeColor} />
        <div className="radar-hero-overlay" />

        {/* Minimal Floating 3D Status HUD on Bottom Left */}
        <div className="radar-canvas-hud">
          <div className="radar-hud-live-tag">
            <span className="radar-live-dot" />
            <span>RADAR 3D DÒ QUÉT THỜI GIAN THỰC</span>
          </div>
          <div className="radar-hud-legend">
            <span className="legend-item talent">
              <span className="legend-dot" /> Ứng viên Tiềm năng
            </span>
            <span className="legend-item customer">
              <span className="legend-dot" /> Khách hàng Tiềm năng
            </span>
          </div>
        </div>
      </div>

      {/* Right Column: Brand Cluster + Glassmorphic Login Form + Core Value Props */}
      <div className="radar-auth-panel">
        <div className="radar-auth-container">
          {/* Brand Header Cluster (Right Above Login Form) */}
          <div className="radar-brand-header-cluster">
            <div className="radar-brand-logo-box">
              {appLogoUrl ? (
                <img src={appLogoUrl} alt={appName} className="radar-brand-logo-img" />
              ) : (
                <span className="radar-brand-logo-icon">{appIcon || '⚡'}</span>
              )}
            </div>
            <div className="radar-brand-details">
              <div className="radar-brand-slogan-pill">
                <span>HỆ THỐNG TÌM KIẾM NHÂN TÀI &amp; TĂNG TRƯỞNG KHÁCH HÀNG</span>
              </div>
              <h1 className="radar-brand-main-title">
                Welcome to <span>{appName}</span>
              </h1>
              <p className="radar-brand-sub-tagline">{appTagline}</p>
            </div>
          </div>

          {/* Modern Glassmorphic Login Form Card */}
          <div className="radar-glass-card">
            <div className="radar-glass-glow" />

            {/* Card Header & Security Badge */}
            <div className="radar-form-header">
              <div className="radar-security-pill">
                <span className="radar-live-dot" />
                <span>CỔNG BẢO MẬT NỘI BỘ • MSB SECURE HUB</span>
              </div>

              <h2 className="radar-form-title">
                {screen === 'identify' && 'Đăng Nhập Hệ Thống'}
                {screen === 'password' && 'Xác Thực Mật Khẩu'}
                {screen === 'otp' && 'Xác Thực Mã OTP'}
                {screen === 'reset' && 'Đặt Lại Mật Khẩu'}
              </h2>
              <p className="radar-form-subtitle">
                {screen === 'identify' && 'Nhập địa chỉ Email hoặc Tên tài khoản để tiếp tục'}
                {screen === 'password' && `Tài khoản nội bộ: ${identifier}`}
                {screen === 'otp' && (
                  otpRequest.isError ? (
                    <span style={{ color: '#F87171', fontWeight: 600, display: 'inline-flex', alignItems: 'center', gap: 6 }}>
                      <span>⚠️</span> {otpRequest.error instanceof ApiError ? otpRequest.error.message : 'Chưa thể gửi mã. Vui lòng thử lại sau.'}
                    </span>
                  ) : otpRequest.isPending ? (
                    `Đang gửi mã xác thực tới ${identifier}…`
                  ) : (
                    `Mã xác thực 6 chữ số đã được gửi tới ${identifier}`
                  )
                )}
                {screen === 'reset' && `Khôi phục mật khẩu tài khoản ${identifier}`}
              </p>
            </div>

            {/* Auth Form Body */}
            <form
              className="radar-form-body"
              onSubmit={(e) => {
                e.preventDefault()
                if (screen === 'identify') continueFromIdentifier()
                else if (screen === 'password') login.mutate()
                else if (screen === 'otp') otpVerify.mutate()
                else resetConfirm.mutate()
              }}
            >
              {/* Message & Error Alerts at Top */}
              {message && (
                <div className="radar-alert radar-alert-success">
                  <span>✓</span>
                  <div>{message}</div>
                </div>
              )}

              {error && !(screen === 'otp' && otpRequest.isError) && (
                <div className="radar-alert radar-alert-error">
                  <span>⚠️</span>
                  <div>{error instanceof ApiError ? error.message : 'Không kết nối được máy chủ.'}</div>
                </div>
              )}
              {/* SCREEN 1: IDENTIFY */}
              {screen === 'identify' && (
                <>
                  <div className="radar-input-group">
                    <label htmlFor="login-identifier">
                      <span>Tài khoản / Email</span>
                    </label>
                    <div className="radar-input-wrap">
                      <span className="radar-input-icon">👤</span>
                      <input
                        id="login-identifier"
                        autoFocus
                        autoComplete="username"
                        autoCapitalize="none"
                        autoCorrect="off"
                        spellCheck={false}
                        inputMode="email"
                        className="radar-input"
                        placeholder="username hoặc email@msb.com.vn..."
                        value={identifier}
                        onChange={(e) => setIdentifier(e.target.value)}
                      />
                    </div>
                  </div>

                  <button
                    type="submit"
                    className="radar-submit-btn"
                    disabled={!identifier.trim() || discovery.isPending || otpRequest.isPending}
                  >
                    {(discovery.isPending || otpRequest.isPending) ? (
                      <span className="radar-btn-loading">
                        <span className="radar-spinner" /> Đang kiểm tra &amp; gửi mã…
                      </span>
                    ) : (
                      <span>Tiếp Tục ➔</span>
                    )}
                  </button>
                </>
              )}

              {/* SCREEN 2: PASSWORD */}
              {screen === 'password' && (
                <>
                  <div className="radar-input-group">
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                      <label htmlFor="login-password">Mật khẩu</label>
                      <button
                        type="button"
                        className="radar-text-btn"
                        onClick={() => {
                          setScreen('reset')
                          setMessage('')
                        }}
                      >
                        Quên mật khẩu?
                      </button>
                    </div>
                    <div className="radar-input-wrap">
                      <span className="radar-input-icon">🔒</span>
                      <input
                        id="login-password"
                        autoFocus
                        type={showPassword ? 'text' : 'password'}
                        autoComplete="current-password"
                        className="radar-input"
                        placeholder="••••••••••••"
                        value={password}
                        onChange={(e) => setPassword(e.target.value)}
                      />
                      <button
                        type="button"
                        className="radar-eye-btn"
                        onClick={() => setShowPassword(!showPassword)}
                        title={showPassword ? 'Ẩn mật khẩu' : 'Hiện mật khẩu'}
                      >
                        {showPassword ? '🙈' : '👁️'}
                      </button>
                    </div>
                  </div>

                  <button
                    type="submit"
                    className="radar-submit-btn"
                    disabled={!password || login.isPending}
                  >
                    {login.isPending ? (
                      <span className="radar-btn-loading">
                        <span className="radar-spinner" /> Đang đăng nhập…
                      </span>
                    ) : (
                      <span>Đăng Nhập Vào Hệ Thống</span>
                    )}
                  </button>

                  <button type="button" className="radar-back-btn" onClick={back}>
                    ← Đổi tài khoản khác
                  </button>
                </>
              )}

              {/* SCREEN 3: OTP */}
              {screen === 'otp' && (
                <>
                  <div className="radar-input-group">
                    <label htmlFor="login-otp">Mã xác thực OTP (6 chữ số)</label>
                    <div className="radar-input-wrap">
                      <span className="radar-input-icon">🔢</span>
                      <input
                        id="login-otp"
                        autoFocus
                        inputMode="numeric"
                        autoComplete="one-time-code"
                        maxLength={6}
                        className="radar-input radar-otp-input"
                        placeholder="••••••"
                        value={code}
                        onChange={(e) => setCode(e.target.value.replace(/\D/g, ''))}
                      />
                    </div>
                    <span className="radar-field-hint">
                      ⏱️ Mã có hiệu lực trong 10 phút. Kiểm tra hộp thư chính hoặc thư rác (Spam).
                    </span>
                  </div>

                  <button
                    type="submit"
                    className="radar-submit-btn"
                    disabled={code.length !== 6 || otpVerify.isPending}
                  >
                    {otpVerify.isPending ? (
                      <span className="radar-btn-loading">
                        <span className="radar-spinner" /> Đang xác thực OTP…
                      </span>
                    ) : (
                      <span>Xác Thực &amp; Đăng Nhập</span>
                    )}
                  </button>

                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: 12 }}>
                    <button type="button" className="radar-back-btn" onClick={back}>
                      ← Đổi Email
                    </button>
                    <button
                      type="button"
                      className="radar-text-btn"
                      onClick={() => otpRequest.mutate({ realm: realm!, identifier })}
                      disabled={otpRequest.isPending}
                    >
                      {otpRequest.isPending ? 'Đang gửi lại…' : '↻ Gửi lại mã OTP'}
                    </button>
                  </div>
                </>
              )}

              {/* SCREEN 4: RESET PASSWORD */}
              {screen === 'reset' && (
                <>
                  <div style={{ marginBottom: 16 }}>
                    <button
                      type="button"
                      className="radar-action-pill-btn"
                      onClick={() => resetRequest.mutate()}
                      disabled={resetRequest.isPending}
                    >
                      {resetRequest.isPending ? '⏳ Đang gửi mã…' : '✉️ Nhấn để gửi mã xác thực đặt lại'}
                    </button>
                  </div>

                  <div className="radar-input-group">
                    <label htmlFor="reset-code">Mã xác thực 6 số</label>
                    <div className="radar-input-wrap">
                      <span className="radar-input-icon">🔢</span>
                      <input
                        id="reset-code"
                        inputMode="numeric"
                        autoComplete="one-time-code"
                        maxLength={6}
                        className="radar-input radar-otp-input"
                        placeholder="••••••"
                        value={code}
                        onChange={(e) => setCode(e.target.value.replace(/\D/g, ''))}
                      />
                    </div>
                  </div>

                  <div className="radar-input-group">
                    <label htmlFor="reset-password">Mật khẩu mới</label>
                    <div className="radar-input-wrap">
                      <span className="radar-input-icon">🔑</span>
                      <input
                        id="reset-password"
                        type={showPassword ? 'text' : 'password'}
                        autoComplete="new-password"
                        className="radar-input"
                        placeholder="Nhập mật khẩu mới..."
                        value={password}
                        onChange={(e) => setPassword(e.target.value)}
                      />
                    </div>
                  </div>

                  <button
                    type="submit"
                    className="radar-submit-btn"
                    disabled={code.length !== 6 || !password || resetConfirm.isPending}
                  >
                    {resetConfirm.isPending ? (
                      <span className="radar-btn-loading">
                        <span className="radar-spinner" /> Đang cập nhật…
                      </span>
                    ) : (
                      <span>Lưu Mật Khẩu Mới &amp; Đăng Nhập</span>
                    )}
                  </button>

                  <button type="button" className="radar-back-btn" onClick={() => setScreen('password')}>
                    ← Quay lại đăng nhập
                  </button>
                </>
              )}

            </form>

            {/* Form Footer Support */}
            <div className="radar-form-footer">
              <span>Cần hỗ trợ kỹ thuật hoặc cấp quyền?</span>
              <a href={`mailto:${SUPPORT_EMAIL}`} className="radar-support-link">
                <span>📧</span> {SUPPORT_EMAIL}
              </a>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
