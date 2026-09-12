import React from 'react'
import { PRESET_PALETTES, useCustomTheme } from './CustomThemeContext'

export default function RadarLoadingScreen() {
  const { appName, appTagline, appIcon, appLogoUrl, colorPreset, customColor } = useCustomTheme()

  const primaryColor = colorPreset === 'custom' && customColor
    ? customColor
    : PRESET_PALETTES[colorPreset]?.primary || '#FF8A33'

  return (
    <div
      className="radar-loading-backdrop"
      style={{ '--radar-accent': primaryColor } as React.CSSProperties}
    >
      {/* Center Radar Scanner Sphere with Ambient Pulse */}
      <div className="radar-loading-scanner-box">
        <div className="radar-pulse-aura radar-pulse-1" />
        <div className="radar-pulse-aura radar-pulse-2" />
        <div className="radar-ring radar-ring-1" />
        <div className="radar-ring radar-ring-2" />
        <div className="radar-ring radar-ring-3" />

        {/* 360° Conic Sweep Scan Beam */}
        <div className="radar-sweep-beam" />

        {/* Center Holographic Brand Core (matching sidebar) */}
        <div className="radar-center-core">
          {appLogoUrl ? (
            <img src={appLogoUrl} alt="Logo" className="radar-center-logo" />
          ) : (
            <span className="radar-center-icon">{appIcon || '⚡'}</span>
          )}
        </div>
      </div>

      {/* Brand & Loading Info Cluster */}
      <div className="radar-loading-info">
        <div className="radar-loading-tag-pill">
          <span className="radar-loading-pulse-dot" />
          HỆ THỐNG RADAR ĐANG KHỞI TẠO
        </div>
        <h1 className="radar-loading-title">
          Welcome to <span className="radar-gradient-name">{appName || 'MSB Radar'}</span>
        </h1>
        <p className="radar-loading-tagline">
          {appTagline || 'Hệ Thống Tìm Kiếm Nhân Tài & Tăng Trưởng Khách Hàng'}
        </p>

        {/* Progress Bar & Status */}
        <div className="radar-loading-bar-wrapper">
          <div className="radar-loading-bar-fill" />
        </div>
        <span className="radar-loading-status-text">
          Đang kết nối &amp; đồng bộ dữ liệu thời gian thực…
        </span>
      </div>
    </div>
  )
}
