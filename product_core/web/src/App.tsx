import React, { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { NavLink, Navigate, Route, Routes, useLocation, useNavigate, Link } from 'react-router-dom'
import Admin from './Admin'
import { api } from './api'
import { useCustomTheme } from './CustomThemeContext'
import Dashboard from './Dashboard'
import Data from './Data'
import Hunts from './HuntsWorkspace'
import Knowledge from './Knowledge'
import Login from './Login'
import Person360 from './Person360'
import RadarLoadingScreen from './RadarLoadingScreen'
import RB from './RB'
import Settings from './Settings'
import Social from './Social'
import Workflows from './Workflows'
import SidebarChatHistory from './SidebarChatHistory'

// --- SVG Icons ---

function IconMenu() {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <line x1="3" y1="12" x2="21" y2="12" />
      <line x1="3" y1="6" x2="21" y2="6" />
      <line x1="3" y1="18" x2="21" y2="18" />
    </svg>
  )
}

function IconChevronLeft() {
  return (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
      <polyline points="15 18 9 12 15 6" />
    </svg>
  )
}

function IconChevronRight() {
  return (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
      <polyline points="9 18 15 12 9 6" />
    </svg>
  )
}

function IconChevronDown() {
  return (
    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
      <polyline points="6 9 12 15 18 9" />
    </svg>
  )
}

function IconHunts() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="10" />
      <line x1="22" y1="12" x2="18" y2="12" />
      <line x1="6" y1="12" x2="2" y2="12" />
      <line x1="12" y1="6" x2="12" y2="2" />
      <line x1="12" y1="22" x2="12" y2="18" />
      <circle cx="12" cy="12" r="3" />
    </svg>
  )
}

function IconSocial() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="18" cy="5" r="3" />
      <circle cx="6" cy="12" r="3" />
      <circle cx="18" cy="19" r="3" />
      <line x1="8.59" y1="13.51" x2="15.42" y2="17.49" />
      <line x1="15.41" y1="6.51" x2="8.59" y2="10.49" />
    </svg>
  )
}

function IconRB() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <polyline points="23 6 13.5 15.5 8.5 10.5 1 18" />
      <polyline points="17 6 23 6 23 12" />
    </svg>
  )
}

function IconDashboard() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <rect x="3" y="3" width="7" height="9" rx="1.5" />
      <rect x="14" y="3" width="7" height="5" rx="1.5" />
      <rect x="14" y="12" width="7" height="9" rx="1.5" />
      <rect x="3" y="16" width="7" height="5" rx="1.5" />
    </svg>
  )
}

function IconData() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <ellipse cx="12" cy="5" rx="9" ry="3" />
      <path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3" />
      <path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5" />
    </svg>
  )
}

function IconSettings() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="3" />
      <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z" />
    </svg>
  )
}

function IconKnowledge() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20" />
      <path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z" />
    </svg>
  )
}

function IconAdmin() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
    </svg>
  )
}

function IconWorkflows() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <rect x="3" y="3" width="6" height="6" rx="1.5" />
      <rect x="15" y="3" width="6" height="6" rx="1.5" />
      <rect x="9" y="15" width="6" height="6" rx="1.5" />
      <path d="M6 9v3a1 1 0 0 0 1 1h5m0 0h5a1 1 0 0 0 1-1V9m-6 4v2" />
    </svg>
  )
}

function IconLogout() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" />
      <polyline points="16 17 21 12 16 7" />
      <line x1="21" y1="12" x2="9" y2="12" />
    </svg>
  )
}

// Submenu micro SVG icons
function IconSubSearch() {
  return (
    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="11" cy="11" r="8" />
      <line x1="21" y1="21" x2="16.65" y2="16.65" />
    </svg>
  )
}

function IconSubFilter() {
  return (
    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
      <polygon points="22 3 2 3 10 12.46 10 19 14 21 14 12.46 22 3" />
    </svg>
  )
}

function IconSubTasks() {
  return (
    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M9 11l3 3L22 4" />
      <path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11" />
    </svg>
  )
}

function IconSubPipeline() {
  return (
    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
      <rect x="3" y="3" width="5" height="18" rx="1" />
      <rect x="11" y="3" width="5" height="12" rx="1" />
      <rect x="19" y="3" width="5" height="8" rx="1" />
    </svg>
  )
}

function IconSubFolder() {
  return (
    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z" />
    </svg>
  )
}

function IconSubTarget() {
  return (
    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="10" />
      <circle cx="12" cy="12" r="6" />
      <circle cx="12" cy="12" r="2" />
    </svg>
  )
}

interface NavItem {
  to: string
  label: string
  module: string
  /** Module khác cũng đủ để thấy mục này (VD: người chỉ có people_intake vẫn vào /data). */
  altModules?: string[]
  icon: React.ReactNode
  category: string
  roles?: string[]
}

interface NavSection {
  title: string
  items: NavItem[]
}

const NAV_SECTIONS: NavSection[] = [
  {
    title: 'Phân hệ Radar',
    items: [
      { to: '/talent', label: 'Talent Radar', module: 'talent', icon: <IconHunts />, category: 'Phân hệ Radar', roles: ['recruiter', 'rb_sales', 'manager', 'admin'] },
      { to: '/rb', label: 'Growth Radar', module: 'rb', icon: <IconRB />, category: 'Phân hệ Radar', roles: ['rb_sales', 'manager', 'admin'] },
      { to: '/social', label: 'Social Radar', module: 'social', icon: <IconSocial />, category: 'Phân hệ Radar' },
    ],
  },
  {
    title: 'Báo cáo & Vận hành',
    items: [
      { to: '/dashboard', label: 'Tổng quan & Giám sát', module: 'reports', icon: <IconDashboard />, category: 'Báo cáo & Vận hành' },
      { to: '/workflows', label: 'Quy trình & Pipeline', module: 'reports', icon: <IconWorkflows />, category: 'Báo cáo & Vận hành', roles: ['manager', 'admin'] },
    ],
  },
  {
    title: 'Quản trị & Hệ thống',
    items: [
      { to: '/data', label: 'Đồng bộ Dữ liệu & Edge', module: 'edge_ops', altModules: ['people_intake'], icon: <IconData />, category: 'Quản trị & Hệ thống' },
      { to: '/knowledge', label: 'Tri thức nội bộ', module: 'knowledge', icon: <IconKnowledge />, category: 'Quản trị & Hệ thống' },
      { to: '/settings', label: 'Cấu hình AI & Trí tuệ', module: 'ai_settings', icon: <IconSettings />, category: 'Quản trị & Hệ thống' },
      { to: '/admin', label: 'Quản trị & Phân quyền', module: 'admin_console', icon: <IconAdmin />, category: 'Quản trị & Hệ thống' },
    ],
  },
]

const ALL_ITEMS = NAV_SECTIONS.flatMap((s) => s.items)

export default function App() {
  const { appName, appIcon, appLogoUrl } = useCustomTheme()
  const [collapsed, setCollapsed] = useState(() => {
    try {
      const saved = localStorage.getItem('radar_sidebar_collapsed')
      if (saved !== null) {
        return saved === 'true'
      }
    } catch {
      // ignore
    }
    return false
  })
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false)
  const [expandedMenus, setExpandedMenus] = useState<Record<string, boolean>>({
    '/talent': true,
    '/rb': true,
  })

  const location = useLocation()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const session = useQuery({ queryKey: ['me'], queryFn: api.me, retry: false })

  // Auto close mobile drawer on route change
  useEffect(() => {
    setMobileMenuOpen(false)
  }, [location.pathname])

  const toggleCollapsed = () => {
    setCollapsed((prev) => {
      const next = !prev
      try {
        localStorage.setItem('radar_sidebar_collapsed', String(next))
      } catch {
        // ignore
      }
      return next
    })
  }

  const logout = useMutation({
    mutationFn: api.logout,
    onSuccess: () => {
      queryClient.setQueryData(['me'], { authenticated: false })
      queryClient.removeQueries({
        predicate: (query) => query.queryKey[0] !== 'me',
      })
    },
  })

  // Tự động cuộn lên đầu trang khi đổi route
  // (PHẢI đặt trước mọi early return để tuân thủ React Rules of Hooks)
  useEffect(() => {
    if (typeof window !== 'undefined') {
      try {
        window.scrollTo({ top: 0, left: 0, behavior: 'instant' })
      } catch {
        // bỏ qua trong test
      }
    }
  }, [location.pathname])

  if (session.isLoading) return <RadarLoadingScreen />

  const identity = session.data?.authenticated ? session.data : null
  const modules = new Set(identity?.modules ?? [])
  const userRoles = new Set(identity?.roles ?? [])
  const rmOnly = userRoles.has('rb_sales') && !userRoles.has('recruiter') &&
    !userRoles.has('manager') && !userRoles.has('admin')
  const isRecruiterOrAbove = userRoles.has('recruiter') || userRoles.has('manager') || userRoles.has('admin')
  const edgeOpsOnly = modules.has('edge_ops') && !modules.has('talent') && !modules.has('rb')

  const visibleSections = NAV_SECTIONS.map((section) => ({
    ...section,
    items: section.items.filter((item) =>
      (modules.has(item.module) || (item.altModules ?? []).some((m) => modules.has(m))) &&
      (!item.roles || item.roles.some((role) => userRoles.has(role)))),
  })).filter((section) => section.items.length > 0)

  const visibleItems = visibleSections.flatMap((s) => s.items)
  // Landing mặc định theo role: recruiter/manager/admin → AI Search (/talent),
  // rb_sales thuần → Growth Radar (/rb), edge_ops thuần → Data Hub (/data),
  // còn lại → mục đầu tiên trong menu.
  const landing = isRecruiterOrAbove && modules.has('talent')
    ? '/talent'
    : rmOnly
      ? '/rb'
      : edgeOpsOnly
        ? '/data'
        : (visibleItems[0]?.to ?? '/talent')



  // Tìm thông tin trang hiện tại cho Breadcrumb trên Topbar
  const currentPath = location.pathname
  let currentNav = ALL_ITEMS.find((item) => item.to === currentPath)
  if (!currentNav) {
    if (currentPath.startsWith('/person/') || currentPath.startsWith('/talent/')) {
      currentNav = { to: currentPath, label: 'Hồ sơ 360°', module: 'talent', icon: <IconHunts />, category: 'Phân hệ Radar' }
    } else if (currentPath.startsWith('/talent') || currentPath.startsWith('/hunts')) {
      currentNav = { to: '/talent', label: 'Talent Radar', module: 'talent', icon: <IconHunts />, category: 'Phân hệ Radar' }
    } else if (currentPath.startsWith('/rb')) {
      currentNav = { to: '/rb', label: 'Growth Radar', module: 'rb', icon: <IconRB />, category: 'Phân hệ Radar' }
    } else if (currentPath.startsWith('/social')) {
      currentNav = { to: '/social', label: 'Social Radar', module: 'social', icon: <IconSocial />, category: 'Phân hệ Radar' }
    } else if (currentPath.startsWith('/dashboard')) {
      currentNav = { to: '/dashboard', label: 'Tổng quan & Giám sát', module: 'reports', icon: <IconDashboard />, category: 'Báo cáo & Vận hành' }
    } else if (currentPath.startsWith('/workflows')) {
      currentNav = { to: '/workflows', label: 'Quy trình & Pipeline', module: 'reports', icon: <IconWorkflows />, category: 'Báo cáo & Vận hành' }
    } else if (currentPath.startsWith('/data')) {
      currentNav = { to: '/data', label: 'Đồng bộ Dữ liệu & Edge', module: 'edge_ops', icon: <IconData />, category: 'Quản trị & Hệ thống' }
    } else if (currentPath.startsWith('/knowledge')) {
      currentNav = { to: '/knowledge', label: 'Tri thức nội bộ', module: 'knowledge', icon: <IconKnowledge />, category: 'Quản trị & Hệ thống' }
    } else if (currentPath.startsWith('/settings')) {
      currentNav = { to: '/settings', label: 'Cấu hình AI & Trí tuệ', module: 'ai_settings', icon: <IconSettings />, category: 'Quản trị & Hệ thống' }
    } else if (currentPath.startsWith('/admin')) {
      currentNav = { to: '/admin', label: 'Quản trị & Phân quyền', module: 'admin_console', icon: <IconAdmin />, category: 'Quản trị & Hệ thống' }
    }
  }

  function guard(module: string, element: React.ReactElement) {
    if (modules.has(module)) return element
    const label = ALL_ITEMS.find((tab) => tab.module === module)?.label ?? module
    return (
      <div className="empty-box" style={{ margin: '32px' }}>
        Vai trò của bạn không được vào <strong>{label}</strong>.
      </div>
    )
  }

  function guardAny(moduleList: string[], element: React.ReactElement) {
    if (moduleList.some((m) => modules.has(m))) return element
    return (
      <div className="empty-box" style={{ margin: '32px' }}>
        Vai trò của bạn không có quyền truy cập hồ sơ này.
      </div>
    )
  }

  if (!identity) {
    return <Login onSuccess={() => queryClient.invalidateQueries({ queryKey: ['me'] })} />
  }

  if (visibleItems.length === 0) {
    return (
      <div className="empty-box" style={{ margin: '60px auto', maxWidth: '600px' }}>
        Tài khoản của bạn chưa được gán vai trò nào nên chưa vào được module nào.
        <br />
        Liên hệ quản trị viên để được cấp quyền.
        <div style={{ marginTop: '16px' }}>
          <button className="btn" onClick={() => logout.mutate()}>Đăng xuất</button>
        </div>
      </div>
    )
  }

  return (
    <div className={`hub-layout ${collapsed ? 'sidebar-collapsed' : ''} ${mobileMenuOpen ? 'mobile-menu-open' : ''}`}>
      {/* Mobile Drawer Backdrop */}
      <div
        className={`sidebar-backdrop ${mobileMenuOpen ? 'open' : ''}`}
        onClick={() => setMobileMenuOpen(false)}
        aria-hidden="true"
      />

      {/* Sidebar Navigation */}
      <aside className={`hub-sidebar ${mobileMenuOpen ? 'mobile-open' : ''}`}>
        <div className="sidebar-brand">
          <div className="brand-logo">
            <span className="brand-icon">
              {appLogoUrl ? (
                <img src={appLogoUrl} alt={appName} className="brand-custom-img" />
              ) : (
                <span className="brand-emoji-icon">{appIcon || '⚡'}</span>
              )}
            </span>
            {(!collapsed || mobileMenuOpen) && (
              <div className="brand-text">
                <span className="brand-title">{appName}</span>
                <span className="brand-tag">RADAR INTELLIGENCE</span>
              </div>
            )}
          </div>
          <button
            className="sidebar-toggle-btn desktop-only"
            onClick={toggleCollapsed}
            title={collapsed ? 'Mở rộng menu (Ctrl+\\)' : 'Thu gọn menu (Ctrl+\\)'}
            type="button"
            aria-label="Toggle Sidebar"
          >
            {collapsed ? <IconChevronRight /> : <IconChevronLeft />}
          </button>
          <button
            className="sidebar-close-btn mobile-only"
            onClick={() => setMobileMenuOpen(false)}
            title="Đóng menu"
            type="button"
            aria-label="Close Menu"
          >
            ✕
          </button>
        </div>

        <nav className="sidebar-nav">
          {visibleSections.map((section) => (
            <div key={section.title} className="nav-group">
              {(!collapsed || mobileMenuOpen) && <div className="nav-group-title">{section.title}</div>}
              {section.items.map((item) => {
                const isTalent = item.to === '/talent'
                const isRb = item.to === '/rb'
                const hasSub = isTalent || isRb
                const isExpanded = hasSub && (expandedMenus[item.to] ?? true)
                const isItemActive = location.pathname.startsWith(item.to) || (isTalent && location.pathname.startsWith('/hunts'))

                return (
                  <React.Fragment key={item.to}>
                    <div className="sidebar-nav-item-wrap">
                      <NavLink
                        to={isTalent ? '/talent?tab=talent' : isRb ? '/rb?tab=today' : item.to}
                        className={({ isActive }) => `sidebar-nav-item ${isActive || isItemActive ? 'active' : ''}`}
                        data-tooltip={collapsed && !mobileMenuOpen ? item.label : undefined}
                        onClick={() => {
                          if (hasSub) {
                            setExpandedMenus((prev) => ({ ...prev, [item.to]: true }))
                          }
                          setMobileMenuOpen(false)
                        }}
                      >
                        <span className="nav-item-icon">{item.icon}</span>
                        {(!collapsed || mobileMenuOpen) && <span className="nav-item-label">{item.label}</span>}
                        {hasSub && (!collapsed || mobileMenuOpen) && (
                          <span
                            className={`sidebar-submenu-chevron ${isExpanded ? 'expanded' : ''}`}
                            onClick={(e) => {
                              e.preventDefault()
                              e.stopPropagation()
                              setExpandedMenus((prev) => ({ ...prev, [item.to]: !isExpanded }))
                            }}
                            title={isExpanded ? 'Thu gọn menu con' : 'Mở rộng menu con'}
                          >
                            <IconChevronDown />
                          </span>
                        )}
                      </NavLink>
                    </div>

                    {/* Menu con trực tiếp cho Talent Radar */}
                    {(!collapsed || mobileMenuOpen) && isTalent && isExpanded && (
                      <div className="sidebar-submenu">
                        <Link
                          to="/talent?tab=talent"
                          className={`sidebar-subitem ${(isItemActive && (!location.search || location.search.includes('tab=talent'))) ? 'active' : ''}`}
                          onClick={() => setMobileMenuOpen(false)}
                        >
                          <span className="subitem-icon"><IconSubSearch /></span>
                          <span>Tìm kiếm AI</span>
                        </Link>
                        <Link
                          to="/talent?tab=filter"
                          className={`sidebar-subitem ${(isItemActive && location.search.includes('tab=filter')) ? 'active' : ''}`}
                          onClick={() => setMobileMenuOpen(false)}
                        >
                          <span className="subitem-icon"><IconSubFilter /></span>
                          <span>Bộ lọc đa chiều</span>
                        </Link>
                        <Link
                          to="/talent?tab=tasks"
                          className={`sidebar-subitem ${(isItemActive && location.search.includes('tab=tasks')) ? 'active' : ''}`}
                          onClick={() => setMobileMenuOpen(false)}
                        >
                          <span className="subitem-icon"><IconSubTasks /></span>
                          <span>Nhiệm vụ săn</span>
                        </Link>
                        <Link
                          to="/talent?tab=pipeline"
                          className={`sidebar-subitem ${(isItemActive && location.search.includes('tab=pipeline')) ? 'active' : ''}`}
                          onClick={() => setMobileMenuOpen(false)}
                        >
                          <span className="subitem-icon"><IconSubPipeline /></span>
                          <span>Pipeline tuyển dụng</span>
                        </Link>
                        <Link
                          to="/talent?tab=lists"
                          className={`sidebar-subitem ${(isItemActive && location.search.includes('tab=lists')) ? 'active' : ''}`}
                          onClick={() => setMobileMenuOpen(false)}
                        >
                          <span className="subitem-icon"><IconSubFolder /></span>
                          <span>Đợt tuyển &amp; Pool</span>
                        </Link>
                      </div>
                    )}

                    {/* Menu con trực tiếp cho Growth Radar */}
                    {(!collapsed || mobileMenuOpen) && isRb && isExpanded && (
                      <div className="sidebar-submenu">
                        <Link
                          to="/rb?tab=today"
                          className={`sidebar-subitem ${(isItemActive && (!location.search || location.search.includes('tab=today'))) ? 'active' : ''}`}
                          onClick={() => setMobileMenuOpen(false)}
                        >
                          <span className="subitem-icon"><IconSubTarget /></span>
                          <span>Cơ hội hôm nay</span>
                        </Link>
                        <Link
                          to="/rb?tab=prospects"
                          className={`sidebar-subitem ${(isItemActive && location.search.includes('tab=prospects')) ? 'active' : ''}`}
                          onClick={() => setMobileMenuOpen(false)}
                        >
                          <span className="subitem-icon"><IconSubSearch /></span>
                          <span>Tìm khách AI</span>
                        </Link>
                        <Link
                          to="/rb?tab=filter"
                          className={`sidebar-subitem ${(isItemActive && location.search.includes('tab=filter')) ? 'active' : ''}`}
                          onClick={() => setMobileMenuOpen(false)}
                        >
                          <span className="subitem-icon"><IconSubFilter /></span>
                          <span>Bộ lọc khách hàng</span>
                        </Link>
                        <Link
                          to="/rb?tab=tasks"
                          className={`sidebar-subitem ${(isItemActive && location.search.includes('tab=tasks')) ? 'active' : ''}`}
                          onClick={() => setMobileMenuOpen(false)}
                        >
                          <span className="subitem-icon"><IconSubTasks /></span>
                          <span>Việc cần xử lý</span>
                        </Link>
                        <Link
                          to="/rb?tab=pipeline"
                          className={`sidebar-subitem ${(isItemActive && location.search.includes('tab=pipeline')) ? 'active' : ''}`}
                          onClick={() => setMobileMenuOpen(false)}
                        >
                          <span className="subitem-icon"><IconSubPipeline /></span>
                          <span>Pipeline</span>
                        </Link>
                        <Link
                          to="/rb?tab=lists"
                          className={`sidebar-subitem ${(isItemActive && location.search.includes('tab=lists')) ? 'active' : ''}`}
                          onClick={() => setMobileMenuOpen(false)}
                        >
                          <span className="subitem-icon"><IconSubFolder /></span>
                          <span>Nhóm khách hàng</span>
                        </Link>
                      </div>
                    )}
                  </React.Fragment>
                )
              })}
            </div>
          ))}

          {/* Lịch sử trò chuyện đặt ngay dưới các chức năng */}
          <SidebarChatHistory
            collapsed={collapsed && !mobileMenuOpen}
            onExpand={() => setCollapsed(false)}
            onNavigate={() => setMobileMenuOpen(false)}
            allowedModules={modules}
          />
        </nav>

        <div className="sidebar-footer">
          <div className="user-profile-badge" title={`${identity.full_name} (${identity.username})`}>
            <div className="user-avatar-wrap">
              <div className="user-avatar">{identity.full_name?.[0]?.toUpperCase() || 'U'}</div>
              <span className="live-user-dot" title="Đang trực tuyến" />
            </div>
            {(!collapsed || mobileMenuOpen) && (
              <div className="user-info">
                <div className="user-name">{identity.full_name}</div>
                <div className="user-role">
                  {identity.role_labels.join(', ') || 'Thành viên'}
                </div>
              </div>
            )}
          </div>
          <button
            className="logout-action-btn"
            onClick={() => logout.mutate()}
            title="Đăng xuất khỏi hệ thống"
            type="button"
            data-tooltip={collapsed && !mobileMenuOpen ? 'Đăng xuất' : undefined}
          >
            <IconLogout />
            {(!collapsed || mobileMenuOpen) && <span>Đăng xuất</span>}
          </button>
        </div>
      </aside>

      {/* Main Content Workspace */}
      <main className="hub-main-content">
        <header className="hub-topbar">
          <div className="topbar-left-wrap">
            <button
              className="sidebar-mobile-toggle"
              onClick={() => setMobileMenuOpen((prev) => !prev)}
              title="Mở bảng điều hướng"
              type="button"
              aria-label="Toggle Menu"
            >
              <IconMenu />
            </button>
            <div className="topbar-title">
              <div className="topbar-breadcrumb">
                <span className="crumb-icon">{currentNav?.icon}</span>
                <h2 className="crumb-active">{currentNav?.label || 'Tổng quan'}</h2>
              </div>
            </div>
          </div>
          <div className="topbar-right-actions">
            <button
              type="button"
              className="topbar-new-chat-btn"
              onClick={() => {
                window.dispatchEvent(new CustomEvent('radar:new-chat'));
                if (!location.pathname.startsWith('/talent') && !location.pathname.startsWith('/rb')) {
                  navigate('/talent?tab=talent');
                }
              }}
              title="Tạo cuộc trò chuyện mới"
              aria-label="Tạo cuộc trò chuyện mới"
            >
              <span className="btn-icon">✨</span>
              <span className="btn-text">+ Cuộc trò chuyện mới</span>
            </button>
          </div>
        </header>

        <div className="hub-page-body">
          <Routes>
            <Route path="/" element={<Navigate to={landing} replace />} />
            <Route path="/talent" element={guard('talent', <Hunts initialTab="talent" />)} />
            <Route path="/talent/:id" element={guardAny(['talent', 'rb'], <Person360 />)} />
            <Route path="/person/:id" element={guardAny(['talent', 'rb'], <Person360 />)} />
            <Route path="/hunts" element={guard('talent', <Hunts />)} />
            <Route path="/social" element={guard('social', <Social />)} />
            <Route path="/rb" element={guard('rb', <RB />)} />
            <Route path="/dashboard" element={guard('reports', <Dashboard />)} />
            <Route path="/workflows" element={guard('reports', <Workflows />)} />
            <Route path="/data" element={guardAny(['edge_ops', 'people_intake'], <Data />)} />
            <Route path="/knowledge" element={guard('knowledge', <Knowledge />)} />
            <Route path="/settings" element={guard('ai_settings', <Settings />)} />
            <Route
              path="/admin"
              element={guard('admin_console', <Admin currentUsername={identity.username} />)}
            />
            <Route path="*" element={<Navigate to={landing} replace />} />
          </Routes>
        </div>
      </main>
    </div>
  )
}
