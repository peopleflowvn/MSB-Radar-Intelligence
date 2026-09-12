import React, { createContext, useContext, useEffect, useState } from 'react'
import { api, PublicSettings } from './api'

export type ColorPreset = 'crimson_red' | 'ocean_blue' | 'emerald_green' | 'royal_purple' | 'amber_gold' | 'cyber_cyan' | 'custom'
export type ThemeMode = 'auto' | 'light' | 'dark'
export type TableDensity = 'compact' | 'normal' | 'comfortable'

export interface ColorPalette {
  primary: string
  primaryDark: string
  primarySoftLight: string
  primarySoftDark: string
  gradientFrom: string
  gradientVia?: string
  gradientTo: string
}

export const PRESET_PALETTES: Record<ColorPreset, ColorPalette> = {
  ocean_blue: {
    primary: '#0284c7',
    primaryDark: '#38bdf8',
    primarySoftLight: '#e0f2fe',
    primarySoftDark: 'rgba(56, 189, 248, 0.18)',
    gradientFrom: '#0284c7',
    gradientVia: '#0ea5e9',
    gradientTo: '#0369a1',
  },
  crimson_red: {
    primary: '#dc2626',
    primaryDark: '#ef4444',
    primarySoftLight: '#fee2e2',
    primarySoftDark: 'rgba(239, 68, 68, 0.18)',
    gradientFrom: '#ef4444',
    gradientVia: '#dc2626',
    gradientTo: '#b91c1c',
  },
  emerald_green: {
    primary: '#059669',
    primaryDark: '#34d399',
    primarySoftLight: '#d1fae5',
    primarySoftDark: 'rgba(52, 211, 153, 0.18)',
    gradientFrom: '#10b981',
    gradientVia: '#059669',
    gradientTo: '#047857',
  },
  royal_purple: {
    primary: '#7c3aed',
    primaryDark: '#a78bfa',
    primarySoftLight: '#ede9fe',
    primarySoftDark: 'rgba(167, 139, 250, 0.18)',
    gradientFrom: '#8b5cf6',
    gradientVia: '#7c3aed',
    gradientTo: '#6d28d9',
  },
  amber_gold: {
    primary: '#d97706',
    primaryDark: '#fbbf24',
    primarySoftLight: '#fef3c7',
    primarySoftDark: 'rgba(251, 191, 36, 0.18)',
    gradientFrom: '#FF8A33',
    gradientVia: '#F59E0B',
    gradientTo: '#EA580C',
  },
  cyber_cyan: {
    primary: '#0891b2',
    primaryDark: '#22d3ee',
    primarySoftLight: '#cffafe',
    primarySoftDark: 'rgba(34, 211, 238, 0.18)',
    gradientFrom: '#06b6d4',
    gradientVia: '#0891b2',
    gradientTo: '#0e7490',
  },
  custom: {
    primary: '#FF8A33',
    primaryDark: '#fbbf24',
    primarySoftLight: '#fef3c7',
    primarySoftDark: 'rgba(255, 138, 51, 0.18)',
    gradientFrom: '#FF8A33',
    gradientVia: '#F59E0B',
    gradientTo: '#EA580C',
  },
}

export const PRESET_ICONS = ['⚡', '🎯', '🚀', '🔮', '🌐', '🛡️', '💎', '🔥', '💡', '🌟', '📊', '👥']

interface CustomThemeContextType {
  appName: string
  appTagline: string
  appIcon: string
  appLogoUrl: string
  radarAvatarUrl: string
  radarAvatarEmoji: string
  themeMode: ThemeMode
  colorPreset: ColorPreset
  customColor: string
  gradientFrom: string
  gradientVia: string
  gradientTo: string
  gradientAngle: string
  tableDensity: TableDensity
  maskSensitiveData: boolean
  minMatchScore: number
  itemsPerPage: number
  soundAlerts: boolean
  setAppName: (name: string) => void
  setAppTagline: (tagline: string) => void
  setAppIcon: (icon: string) => void
  setAppLogoUrl: (url: string) => void
  setRadarAvatarUrl: (url: string) => void
  setRadarAvatarEmoji: (emoji: string) => void
  setThemeMode: (mode: ThemeMode) => void
  setColorPreset: (preset: ColorPreset) => void
  setCustomColor: (hex: string) => void
  setGradientFrom: (color: string) => void
  setGradientVia: (color: string) => void
  setGradientTo: (color: string) => void
  setGradientAngle: (angle: string) => void
  setTableDensity: (density: TableDensity) => void
  setMaskSensitiveData: (mask: boolean) => void
  setMinMatchScore: (score: number) => void
  setItemsPerPage: (num: number) => void
  setSoundAlerts: (sound: boolean) => void
  saveSystemSettings: (patch: Partial<PublicSettings>) => Promise<PublicSettings>
  resetToDefaults: () => Promise<void>
}

const CustomThemeContext = createContext<CustomThemeContextType | null>(null)

export function CustomThemeProvider({ children }: { children: React.ReactNode }) {
  const [appName, setAppNameState] = useState(() => {
    return localStorage.getItem('radar_custom_app_name') || 'MSB Radar'
  })

  const [appTagline, setAppTaglineState] = useState(() => {
    return localStorage.getItem('radar_custom_app_tagline') || 'Hệ Thống Tìm Kiếm Nhân Tài & Tăng Trưởng Khách Hàng'
  })

  const [appIcon, setAppIconState] = useState(() => {
    return localStorage.getItem('radar_custom_app_icon') || '⚡'
  })

  const [appLogoUrl, setAppLogoUrlState] = useState(() => {
    return localStorage.getItem('radar_custom_app_logo_url') || ''
  })

  const [radarAvatarUrl, setRadarAvatarUrlState] = useState(() => {
    return localStorage.getItem('radar_avatar_url') || ''
  })

  const [radarAvatarEmoji, setRadarAvatarEmojiState] = useState(() => {
    return localStorage.getItem('radar_avatar_emoji') || '⚡'
  })

  const [themeMode, setThemeModeState] = useState<ThemeMode>(() => {
    return (localStorage.getItem('radar_theme_mode') as ThemeMode) || 'dark'
  })

  const [colorPreset, setColorPresetState] = useState<ColorPreset>(() => {
    return (localStorage.getItem('radar_color_preset') as ColorPreset) || 'amber_gold'
  })

  const [customColor, setCustomColorState] = useState(() => {
    return localStorage.getItem('radar_custom_color') || '#FF8A33'
  })

  const [gradientFrom, setGradientFromState] = useState(() => {
    return localStorage.getItem('radar_gradient_from') || '#FF8A33'
  })

  const [gradientVia, setGradientViaState] = useState(() => {
    return localStorage.getItem('radar_gradient_via') || '#F59E0B'
  })

  const [gradientTo, setGradientToState] = useState(() => {
    return localStorage.getItem('radar_gradient_to') || '#EA580C'
  })

  const [gradientAngle, setGradientAngleState] = useState(() => {
    return localStorage.getItem('radar_gradient_angle') || '135deg'
  })

  const [tableDensity, setTableDensityState] = useState<TableDensity>(() => {
    return (localStorage.getItem('radar_table_density') as TableDensity) || 'normal'
  })

  const [maskSensitiveData, setMaskSensitiveDataState] = useState<boolean>(() => {
    return localStorage.getItem('radar_mask_sensitive') === 'true'
  })

  const [minMatchScore, setMinMatchScoreState] = useState<number>(() => {
    const val = localStorage.getItem('radar_min_match_score')
    return val ? Number(val) : 50
  })

  const [itemsPerPage, setItemsPerPageState] = useState<number>(() => {
    const val = localStorage.getItem('radar_items_per_page')
    return val ? Number(val) : 25
  })

  const [soundAlerts, setSoundAlertsState] = useState<boolean>(() => {
    return localStorage.getItem('radar_sound_alerts') !== 'false'
  })

  // 1. Tải cấu hình chung từ máy chủ CSDL khi khởi tạo ứng dụng
  useEffect(() => {
    if (typeof api?.publicSettings !== 'function') return
    api.publicSettings()
      .then((settings: PublicSettings) => {
        if (settings.app_name) {
          setAppNameState(settings.app_name)
          localStorage.setItem('radar_custom_app_name', settings.app_name)
        }
        if (settings.app_tagline) {
          setAppTaglineState(settings.app_tagline)
          localStorage.setItem('radar_custom_app_tagline', settings.app_tagline)
        }
        if (settings.app_icon) {
          setAppIconState(settings.app_icon)
          localStorage.setItem('radar_custom_app_icon', settings.app_icon)
        }
        if (settings.app_logo_url !== undefined) {
          setAppLogoUrlState(settings.app_logo_url)
          localStorage.setItem('radar_custom_app_logo_url', settings.app_logo_url)
        }
        if (settings.theme_mode) {
          setThemeModeState(settings.theme_mode as ThemeMode)
          localStorage.setItem('radar_theme_mode', settings.theme_mode)
        }
        if (settings.color_preset) {
          setColorPresetState(settings.color_preset as ColorPreset)
          localStorage.setItem('radar_color_preset', settings.color_preset)
        }
        if (settings.custom_color) {
          setCustomColorState(settings.custom_color)
          localStorage.setItem('radar_custom_color', settings.custom_color)
        }
        if (settings.gradient_from) {
          setGradientFromState(settings.gradient_from)
          localStorage.setItem('radar_gradient_from', settings.gradient_from)
        }
        if (settings.gradient_via !== undefined) {
          setGradientViaState(settings.gradient_via)
          localStorage.setItem('radar_gradient_via', settings.gradient_via)
        }
        if (settings.gradient_to) {
          setGradientToState(settings.gradient_to)
          localStorage.setItem('radar_gradient_to', settings.gradient_to)
        }
        if (settings.gradient_angle) {
          setGradientAngleState(settings.gradient_angle)
          localStorage.setItem('radar_gradient_angle', settings.gradient_angle)
        }
        if (settings.radar_avatar_url !== undefined) {
          setRadarAvatarUrlState(settings.radar_avatar_url)
          localStorage.setItem('radar_avatar_url', settings.radar_avatar_url)
        }
        if (settings.radar_avatar_emoji !== undefined) {
          setRadarAvatarEmojiState(settings.radar_avatar_emoji)
          localStorage.setItem('radar_avatar_emoji', settings.radar_avatar_emoji)
        }
        if (settings.table_density) {
          setTableDensityState(settings.table_density as TableDensity)
          localStorage.setItem('radar_table_density', settings.table_density)
        }
        if (settings.mask_sensitive_data !== undefined) {
          setMaskSensitiveDataState(settings.mask_sensitive_data)
          localStorage.setItem('radar_mask_sensitive', String(settings.mask_sensitive_data))
        }
        if (settings.min_match_score !== undefined) {
          setMinMatchScoreState(settings.min_match_score)
          localStorage.setItem('radar_min_match_score', String(settings.min_match_score))
        }
        if (settings.items_per_page !== undefined) {
          setItemsPerPageState(settings.items_per_page)
          localStorage.setItem('radar_items_per_page', String(settings.items_per_page))
        }
        if (settings.sound_alerts !== undefined) {
          setSoundAlertsState(settings.sound_alerts)
          localStorage.setItem('radar_sound_alerts', String(settings.sound_alerts))
        }
      })
      .catch(() => {
        // Dự phòng khi mạng lỗi: tiếp tục dùng cache từ localStorage
      })
  }, [])

  // 2. Hàm lưu cài đặt đồng bộ CSDL máy chủ toàn hệ thống
  const saveSystemSettings = async (patch: Partial<PublicSettings>): Promise<PublicSettings> => {
    if (patch.app_name !== undefined) {
      setAppNameState(patch.app_name)
      localStorage.setItem('radar_custom_app_name', patch.app_name)
    }
    if (patch.app_tagline !== undefined) {
      setAppTaglineState(patch.app_tagline)
      localStorage.setItem('radar_custom_app_tagline', patch.app_tagline)
    }
    if (patch.app_icon !== undefined) {
      setAppIconState(patch.app_icon)
      localStorage.setItem('radar_custom_app_icon', patch.app_icon)
    }
    if (patch.app_logo_url !== undefined) {
      setAppLogoUrlState(patch.app_logo_url)
      localStorage.setItem('radar_custom_app_logo_url', patch.app_logo_url)
    }
    if (patch.theme_mode !== undefined) {
      setThemeModeState(patch.theme_mode as ThemeMode)
      localStorage.setItem('radar_theme_mode', patch.theme_mode)
    }
    if (patch.color_preset !== undefined) {
      setColorPresetState(patch.color_preset as ColorPreset)
      localStorage.setItem('radar_color_preset', patch.color_preset)
    }
    if (patch.custom_color !== undefined) {
      setCustomColorState(patch.custom_color)
      localStorage.setItem('radar_custom_color', patch.custom_color)
    }
    if (patch.gradient_from !== undefined) {
      setGradientFromState(patch.gradient_from)
      localStorage.setItem('radar_gradient_from', patch.gradient_from)
    }
    if (patch.gradient_via !== undefined) {
      setGradientViaState(patch.gradient_via)
      localStorage.setItem('radar_gradient_via', patch.gradient_via)
    }
    if (patch.gradient_to !== undefined) {
      setGradientToState(patch.gradient_to)
      localStorage.setItem('radar_gradient_to', patch.gradient_to)
    }
    if (patch.gradient_angle !== undefined) {
      setGradientAngleState(patch.gradient_angle)
      localStorage.setItem('radar_gradient_angle', patch.gradient_angle)
    }
    if (patch.radar_avatar_url !== undefined) {
      setRadarAvatarUrlState(patch.radar_avatar_url)
      localStorage.setItem('radar_avatar_url', patch.radar_avatar_url)
    }
    if (patch.radar_avatar_emoji !== undefined) {
      setRadarAvatarEmojiState(patch.radar_avatar_emoji)
      localStorage.setItem('radar_avatar_emoji', patch.radar_avatar_emoji)
    }
    if (patch.table_density !== undefined) {
      setTableDensityState(patch.table_density as TableDensity)
      localStorage.setItem('radar_table_density', patch.table_density)
    }
    if (patch.mask_sensitive_data !== undefined) {
      setMaskSensitiveDataState(patch.mask_sensitive_data)
      localStorage.setItem('radar_mask_sensitive', String(patch.mask_sensitive_data))
    }
    if (patch.min_match_score !== undefined) {
      setMinMatchScoreState(patch.min_match_score)
      localStorage.setItem('radar_min_match_score', String(patch.min_match_score))
    }
    if (patch.items_per_page !== undefined) {
      setItemsPerPageState(patch.items_per_page)
      localStorage.setItem('radar_items_per_page', String(patch.items_per_page))
    }
    if (patch.sound_alerts !== undefined) {
      setSoundAlertsState(patch.sound_alerts)
      localStorage.setItem('radar_sound_alerts', String(patch.sound_alerts))
    }

    try {
      return await api.publicSettingsSave(patch)
    } catch (err) {
      console.warn('Lỗi khi lưu cài đặt máy chủ:', err)
      throw err
    }
  }

  const setAppName = (name: string) => {
    setAppNameState(name)
    localStorage.setItem('radar_custom_app_name', name)
    saveSystemSettings({ app_name: name }).catch(() => {})
  }

  const setAppTagline = (tagline: string) => {
    setAppTaglineState(tagline)
    localStorage.setItem('radar_custom_app_tagline', tagline)
    saveSystemSettings({ app_tagline: tagline }).catch(() => {})
  }

  const setAppIcon = (icon: string) => {
    setAppIconState(icon)
    localStorage.setItem('radar_custom_app_icon', icon)
    saveSystemSettings({ app_icon: icon }).catch(() => {})
  }

  const setAppLogoUrl = (url: string) => {
    setAppLogoUrlState(url)
    localStorage.setItem('radar_custom_app_logo_url', url)
    saveSystemSettings({ app_logo_url: url }).catch(() => {})
  }

  const setRadarAvatarUrl = (url: string) => {
    setRadarAvatarUrlState(url)
    localStorage.setItem('radar_avatar_url', url)
    saveSystemSettings({ radar_avatar_url: url }).catch(() => {})
  }

  const setRadarAvatarEmoji = (emoji: string) => {
    setRadarAvatarEmojiState(emoji)
    localStorage.setItem('radar_avatar_emoji', emoji)
    saveSystemSettings({ radar_avatar_emoji: emoji }).catch(() => {})
  }

  const setThemeMode = (mode: ThemeMode) => {
    setThemeModeState(mode)
    localStorage.setItem('radar_theme_mode', mode)
    saveSystemSettings({ theme_mode: mode }).catch(() => {})
  }

  const setColorPreset = (preset: ColorPreset) => {
    setColorPresetState(preset)
    localStorage.setItem('radar_color_preset', preset)
    if (preset !== 'custom') {
      const p = PRESET_PALETTES[preset]
      if (p) {
        setGradientFromState(p.gradientFrom)
        setGradientViaState(p.gradientVia || p.primary)
        setGradientToState(p.gradientTo)
        localStorage.setItem('radar_gradient_from', p.gradientFrom)
        localStorage.setItem('radar_gradient_via', p.gradientVia || p.primary)
        localStorage.setItem('radar_gradient_to', p.gradientTo)
        saveSystemSettings({
          color_preset: preset,
          gradient_from: p.gradientFrom,
          gradient_via: p.gradientVia || p.primary,
          gradient_to: p.gradientTo,
        }).catch(() => {})
        return
      }
    }
    saveSystemSettings({ color_preset: preset }).catch(() => {})
  }

  const setCustomColor = (hex: string) => {
    setCustomColorState(hex)
    localStorage.setItem('radar_custom_color', hex)
    saveSystemSettings({ custom_color: hex }).catch(() => {})
  }

  const setGradientFrom = (color: string) => {
    setGradientFromState(color)
    localStorage.setItem('radar_gradient_from', color)
    saveSystemSettings({ gradient_from: color }).catch(() => {})
  }

  const setGradientVia = (color: string) => {
    setGradientViaState(color)
    localStorage.setItem('radar_gradient_via', color)
    saveSystemSettings({ gradient_via: color }).catch(() => {})
  }

  const setGradientTo = (color: string) => {
    setGradientToState(color)
    localStorage.setItem('radar_gradient_to', color)
    saveSystemSettings({ gradient_to: color }).catch(() => {})
  }

  const setGradientAngle = (angle: string) => {
    setGradientAngleState(angle)
    localStorage.setItem('radar_gradient_angle', angle)
    saveSystemSettings({ gradient_angle: angle }).catch(() => {})
  }

  const setTableDensity = (density: TableDensity) => {
    setTableDensityState(density)
    localStorage.setItem('radar_table_density', density)
    saveSystemSettings({ table_density: density }).catch(() => {})
  }

  const setMaskSensitiveData = (mask: boolean) => {
    setMaskSensitiveDataState(mask)
    localStorage.setItem('radar_mask_sensitive', String(mask))
    saveSystemSettings({ mask_sensitive_data: mask }).catch(() => {})
  }

  const setMinMatchScore = (score: number) => {
    setMinMatchScoreState(score)
    localStorage.setItem('radar_min_match_score', String(score))
    saveSystemSettings({ min_match_score: score }).catch(() => {})
  }

  const setItemsPerPage = (num: number) => {
    setItemsPerPageState(num)
    localStorage.setItem('radar_items_per_page', String(num))
    saveSystemSettings({ items_per_page: num }).catch(() => {})
  }

  const setSoundAlerts = (sound: boolean) => {
    setSoundAlertsState(sound)
    localStorage.setItem('radar_sound_alerts', String(sound))
    saveSystemSettings({ sound_alerts: sound }).catch(() => {})
  }

  const resetToDefaults = async () => {
    const defaults: Partial<PublicSettings> = {
      app_name: 'MSB Radar',
      app_tagline: 'Hệ Thống Tìm Kiếm Nhân Tài & Tăng Trưởng Khách Hàng',
      app_icon: '⚡',
      app_logo_url: '',
      theme_mode: 'dark',
      color_preset: 'amber_gold',
      custom_color: '#FF8A33',
      gradient_from: '#FF8A33',
      gradient_via: '#F59E0B',
      gradient_to: '#EA580C',
      gradient_angle: '135deg',
      table_density: 'normal',
      mask_sensitive_data: false,
      min_match_score: 50,
      items_per_page: 25,
      sound_alerts: true,
    }
    await saveSystemSettings(defaults).catch(() => {})
  }

  // Effect: cập nhật title, favicon SVG động từ icon, theme và CSS variables
  useEffect(() => {
    const root = document.documentElement
    const fullTitle = `${appName} Hub | ${appTagline}`
    document.title = fullTitle

    // Đổi toàn bộ favicon & apple-touch-icon trình duyệt động theo icon / logo cấu hình
    try {
      const iconUrl = appLogoUrl || `data:image/svg+xml,${encodeURIComponent(
        `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><text y=".88em" x="50%" text-anchor="middle" font-size="82">${appIcon || '⚡'}</text></svg>`
      )}`

      const iconSelectors = ["link[rel*='icon']", "link[rel='apple-touch-icon']", "link[rel='shortcut icon']"]
      let updatedAny = false
      iconSelectors.forEach((sel) => {
        document.querySelectorAll(sel).forEach((el) => {
          (el as HTMLLinkElement).href = iconUrl
          updatedAny = true
        })
      })

      if (!updatedAny) {
        const link = document.createElement('link')
        link.rel = 'icon'
        link.href = iconUrl
        document.head.appendChild(link)
      }

      // Cập nhật các thẻ meta og & twitter tương ứng
      const metaMap: Record<string, string> = {
        'og:title': fullTitle,
        'og:site_name': `${appName} Hub`,
        'og:description': appTagline,
        'twitter:title': fullTitle,
        'twitter:description': appTagline,
      }
      Object.entries(metaMap).forEach(([prop, content]) => {
        const meta = document.querySelector(`meta[property='${prop}'], meta[name='${prop}']`)
        if (meta) meta.setAttribute('content', content)
      })
    } catch {
      // ignore
    }

    // Xác định chế độ dark hiện tại
    const isSystemDark = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches
    const isDark = themeMode === 'dark' || (themeMode === 'auto' && isSystemDark)

    if (themeMode === 'dark') {
      root.setAttribute('data-theme', 'dark')
    } else if (themeMode === 'light') {
      root.setAttribute('data-theme', 'light')
    } else {
      root.removeAttribute('data-theme')
    }

    // Áp dụng Table Density
    root.setAttribute('data-density', tableDensity)

    // Xác định màu chủ đạo và gradient
    let primary = '#FF8A33'
    let primarySoft = 'rgba(255, 138, 51, 0.18)'
    let gFrom = gradientFrom || '#FF8A33'
    let gVia = gradientVia || '#F59E0B'
    let gTo = gradientTo || '#EA580C'
    const gAngle = gradientAngle || '135deg'

    if (colorPreset === 'custom') {
      primary = customColor || '#FF8A33'
      primarySoft = isDark ? `${primary}33` : `${primary}1a`
    } else {
      const palette = PRESET_PALETTES[colorPreset] || PRESET_PALETTES.amber_gold
      primary = isDark ? palette.primaryDark : palette.primary
      primarySoft = isDark ? palette.primarySoftDark : palette.primarySoftLight
      if (!gradientFrom) {
        gFrom = palette.gradientFrom
        gVia = palette.gradientVia || palette.primary
        gTo = palette.gradientTo
      }
    }

    root.style.setProperty('--accent', primary)
    root.style.setProperty('--accent-soft', primarySoft)

    // Các biến CSS Gradient chuẩn toàn hệ thống
    root.style.setProperty('--gradient-from', gFrom)
    root.style.setProperty('--gradient-via', gVia)
    root.style.setProperty('--gradient-to', gTo)
    root.style.setProperty('--gradient-angle', gAngle)

    const viaStr = gVia ? `${gVia} 50%, ` : ''
    root.style.setProperty('--accent-gradient', `linear-gradient(${gAngle}, ${gFrom} 0%, ${viaStr}${gTo} 100%)`)
    root.style.setProperty('--accent-gradient-hover', `linear-gradient(${gAngle}, ${gVia || gFrom} 0%, ${gTo} 100%)`)
    root.style.setProperty('--accent-gradient-text', `linear-gradient(${gAngle}, ${gFrom} 0%, ${gTo} 100%)`)
    root.style.setProperty('--accent-gradient-soft', `linear-gradient(${gAngle}, ${gFrom}26 0%, ${gTo}0d 100%)`)
  }, [appName, appTagline, appIcon, appLogoUrl, themeMode, colorPreset, customColor, gradientFrom, gradientVia, gradientTo, gradientAngle, tableDensity])

  return (
    <CustomThemeContext.Provider
      value={{
        appName,
        appTagline,
        appIcon,
        appLogoUrl,
        radarAvatarUrl,
        radarAvatarEmoji,
        themeMode,
        colorPreset,
        customColor,
        gradientFrom,
        gradientVia,
        gradientTo,
        gradientAngle,
        tableDensity,
        maskSensitiveData,
        minMatchScore,
        itemsPerPage,
        soundAlerts,
        setAppName,
        setAppTagline,
        setAppIcon,
        setAppLogoUrl,
        setRadarAvatarUrl,
        setRadarAvatarEmoji,
        setThemeMode,
        setColorPreset,
        setCustomColor,
        setGradientFrom,
        setGradientVia,
        setGradientTo,
        setGradientAngle,
        setTableDensity,
        setMaskSensitiveData,
        setMinMatchScore,
        setItemsPerPage,
        setSoundAlerts,
        saveSystemSettings,
        resetToDefaults,
      }}
    >
      {children}
    </CustomThemeContext.Provider>
  )
}

const DEFAULT_THEME_CONTEXT: CustomThemeContextType = {
  appName: 'MSB Radar',
  appTagline: 'Hệ Thống Tìm Kiếm Nhân Tài & Tăng Trưởng Khách Hàng',
  appIcon: '⚡',
  appLogoUrl: '',
  radarAvatarUrl: '',
  radarAvatarEmoji: '⚡',
  themeMode: 'dark',
  colorPreset: 'amber_gold',
  customColor: '#FF8A33',
  gradientFrom: '#FF8A33',
  gradientVia: '#F59E0B',
  gradientTo: '#EA580C',
  gradientAngle: '135deg',
  tableDensity: 'normal',
  maskSensitiveData: false,
  minMatchScore: 50,
  itemsPerPage: 25,
  soundAlerts: true,
  setAppName: () => {},
  setAppTagline: () => {},
  setAppIcon: () => {},
  setAppLogoUrl: () => {},
  setRadarAvatarUrl: () => {},
  setRadarAvatarEmoji: () => {},
  setThemeMode: () => {},
  setColorPreset: () => {},
  setCustomColor: () => {},
  setGradientFrom: () => {},
  setGradientVia: () => {},
  setGradientTo: () => {},
  setGradientAngle: () => {},
  setTableDensity: () => {},
  setMaskSensitiveData: () => {},
  setMinMatchScore: () => {},
  setItemsPerPage: () => {},
  setSoundAlerts: () => {},
  saveSystemSettings: async () => ({} as any),
  resetToDefaults: async () => {},
}

export function useCustomTheme() {
  const context = useContext(CustomThemeContext)
  return context || DEFAULT_THEME_CONTEXT
}
