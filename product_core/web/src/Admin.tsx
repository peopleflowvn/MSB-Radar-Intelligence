import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useRef, useState } from 'react'
import { api, AccessLogRow, ApiError, DatabaseBackupRow, EmailOtpTestSendResult, LoginTypeChoice, UserBulkResult, UserRow } from './api'
import { useCustomTheme } from './CustomThemeContext'
import IntelPanel from './IntelPanel'

// Trang Quản trị Hệ thống (Admin Console)
// Dành riêng cho Quản trị viên (vai trò admin / module admin_console).
// Cung cấp giao diện quản lý người dùng, phân quyền RBAC chi tiết từng tính năng,
// định mức mở khoá liên hệ hàng ngày (Contact Quotas), và nhật ký an ninh hệ thống.

export interface RoleInfo {
  key: string
  label: string
  desc: string
  color: string
  badgeText: string
}

export const ROLES: RoleInfo[] = [
  { key: 'admin', label: 'Quản trị hệ thống', desc: 'Toàn quyền cấu hình, quản lý người dùng và an ninh', color: 'admin', badgeText: 'Admin' },
  { key: 'recruiter', label: 'Chuyên viên Tuyển dụng', desc: 'Săn nhân tài, quản lý đợt tuyển và xem hồ sơ CV', color: 'recruiter', badgeText: 'Recruiter' },
  { key: 'hiring_manager', label: 'Trưởng bộ phận tuyển dụng', desc: 'Đánh giá ứng viên, phê duyệt đợt tuyển', color: 'recruiter', badgeText: 'Hiring Mgr' },
  { key: 'rb_sales', label: 'Sales/RM Khách hàng cá nhân', desc: 'Khai thác cơ hội bán chéo, tiếp cận khách hàng tiềm năng', color: 'rb_sales', badgeText: 'RM Sales' },
  { key: 'manager', label: 'Quản lý & Lãnh đạo', desc: 'Xem báo cáo KPI, giám sát quy trình & phân bổ công việc', color: 'manager', badgeText: 'Manager' },
  { key: 'edge_operator', label: 'Vận hành Edge & Dữ liệu', desc: 'Quản trị node thu thập và đồng bộ dữ liệu nguồn', color: 'manager', badgeText: 'Edge Ops' },
]

export interface FeaturePermission {
  key: string
  name: string
  desc: string
  module: string
  moduleName: string
  moduleIcon: string
  securityLevel: 'normal' | 'sensitive' | 'critical'
}

export const SYSTEM_FEATURES: FeaturePermission[] = [
  // 1. Talent Radar
  { key: 'talent:view_candidates', name: 'Xem hồ sơ Ứng viên & Pipeline', desc: 'Truy cập danh sách ứng viên, thông tin nghề nghiệp, kỹ năng', module: 'talent', moduleName: 'Talent Radar', moduleIcon: '🎯', securityLevel: 'normal' },
  { key: 'talent:search_ai', name: 'Tìm kiếm Nhân tài bằng AI & Bóc tách JD', desc: 'Sử dụng AI Agent để bóc tách tiêu chí tuyển dụng và matching ứng viên', module: 'talent', moduleName: 'Talent Radar', moduleIcon: '🎯', securityLevel: 'normal' },
  { key: 'talent:view_cv', name: 'Kho CV & Xem tài liệu CV gốc', desc: 'Mở tab Kho CV, đọc file CV PDF/Docx và nội dung trích xuất chi tiết', module: 'talent', moduleName: 'Talent Radar', moduleIcon: '🎯', securityLevel: 'sensitive' },
  { key: 'talent:manage_worklists', name: 'Tạo & Quản lý Đợt Tuyển (Hunts)', desc: 'Tạo mới, phân công và thay đổi trạng thái tuyển dụng ứng viên trong Pipeline', module: 'talent', moduleName: 'Talent Radar', moduleIcon: '🎯', securityLevel: 'normal' },
  { key: 'talent:outreach', name: 'Soạn thư tiếp cận AI & Gửi liên hệ', desc: 'Sử dụng AI sinh email tiếp cận và tương tác trực tiếp với ứng viên', module: 'talent', moduleName: 'Talent Radar', moduleIcon: '🎯', securityLevel: 'normal' },
  { key: 'talent:export_candidates', name: 'Xuất dữ liệu Ứng viên (Excel/CSV)', desc: 'Tải về danh sách dữ liệu ứng viên ra khỏi hệ thống', module: 'talent', moduleName: 'Talent Radar', moduleIcon: '🎯', securityLevel: 'critical' },

  // 2. Growth Radar
  { key: 'rb:view_prospects', name: 'Xem danh sách Khách hàng tiềm năng', desc: 'Tra cứu danh sách khách hàng bán lẻ, phân khúc và thông tin định danh', module: 'rb', moduleName: 'Growth Radar', moduleIcon: '💳', securityLevel: 'normal' },
  { key: 'rb:search_ai', name: 'Tìm kiếm Khách hàng thông minh AI', desc: 'Sử dụng mô hình AI nhận diện nhu cầu tài chính và gợi ý sản phẩm phù hợp', module: 'rb', moduleName: 'Growth Radar', moduleIcon: '💳', securityLevel: 'normal' },
  { key: 'rb:manage_opportunities', name: 'Khai thác Cơ hội Bán chéo & Xử lý SLA', desc: 'Tạo mới, tiếp nhận và giải quyết các cơ hội sản phẩm bán chéo cho RM', module: 'rb', moduleName: 'Growth Radar', moduleIcon: '💳', securityLevel: 'normal' },
  { key: 'rb:update_crm', name: 'Cập nhật trạng thái CRM & Khai báo liên hệ', desc: 'Ghi nhận kết quả cuộc gọi, nhu cầu thực tế và bước chăm sóc tiếp theo', module: 'rb', moduleName: 'Growth Radar', moduleIcon: '💳', securityLevel: 'normal' },
  { key: 'rb:export_opportunities', name: 'Xuất dữ liệu Cơ hội Khách hàng', desc: 'Tải về bảng phân tích cơ hội và danh sách liên hệ khách hàng', module: 'rb', moduleName: 'Growth Radar', moduleIcon: '💳', securityLevel: 'critical' },

  // 3. Social Radar
  { key: 'social:view_signals', name: 'Dò tìm & Bắt sóng Tín hiệu MXH', desc: 'Theo dõi bài đăng, xu hướng thảo luận tuyển dụng/khách hàng trên mạng xã hội', module: 'social', moduleName: 'Social Radar', moduleIcon: '🌐', securityLevel: 'normal' },
  { key: 'social:analyze_ai', name: 'Phân tích Ý định & Bóc tách Tín hiệu AI', desc: 'Chạy phân tích NLP nhận diện tín hiệu tuyển dụng hoặc nhu cầu tài chính', module: 'social', moduleName: 'Social Radar', moduleIcon: '🌐', securityLevel: 'normal' },
  { key: 'social:link_profile', name: 'Liên kết Tín hiệu vào Hồ sơ 360°', desc: 'Gắn bài đăng và danh tính mạng xã hội vào người tương ứng', module: 'social', moduleName: 'Social Radar', moduleIcon: '🌐', securityLevel: 'normal' },

  // 4. Báo cáo & Quy trình
  { key: 'reports:view_dashboard', name: 'Xem Dashboard & Báo cáo Giám sát KPI', desc: 'Truy cập các biểu đồ chỉ số hiệu suất, SLA và phân bổ khối lượng công việc', module: 'reports', moduleName: 'Báo cáo & Vận hành', moduleIcon: '📊', securityLevel: 'normal' },
  { key: 'reports:manage_workflows', name: 'Cấu hình Quy trình & Pipeline SLA', desc: 'Chỉnh sửa sơ đồ luồng, ma trận bước xử lý và thời hạn SLA các giai đoạn', module: 'reports', moduleName: 'Báo cáo & Vận hành', moduleIcon: '📊', securityLevel: 'sensitive' },

  // 5. Quản trị & Hạ tầng
  { key: 'edge:manage_nodes', name: 'Quản trị Node Edge & Cấp Khóa Thu Thập', desc: 'Tạo mới, tạm dừng node Edge và cấp phát API token bảo mật', module: 'edge_ops', moduleName: 'Đồng bộ Dữ liệu & Edge', moduleIcon: '⚙️', securityLevel: 'sensitive' },
  { key: 'intake:import_excel', name: 'Nhập ứng viên hàng loạt (Excel/CSV)', desc: 'Tải template, upload bảng ứng viên, xem trước trùng lặp và ghi vào hệ thống', module: 'people_intake', moduleName: 'Nhập liệu Ứng viên', moduleIcon: '📥', securityLevel: 'sensitive' },
  { key: 'intake:import_cv', name: 'Nhập ứng viên từ CV (AI bóc tách)', desc: 'Kéo-thả nhiều CV, AI trích xuất hồ sơ, xem lại rồi ghi vào hệ thống', module: 'people_intake', moduleName: 'Nhập liệu Ứng viên', moduleIcon: '📥', securityLevel: 'sensitive' },
  { key: 'ai:manage_providers', name: 'Cấu hình Mô hình AI & GreenNode AgentBase', desc: 'Thay đổi API key, endpoint, model weights và prompt templates', module: 'ai_settings', moduleName: 'Cấu hình AI & Trí tuệ', moduleIcon: '🧠', securityLevel: 'critical' },
  { key: 'admin:manage_users', name: 'Quản lý Tài khoản & Phân quyền Người dùng', desc: 'Tạo tài khoản, gán vai trò RBAC, khoá/mở tài khoản và đổi mật khẩu', module: 'admin_console', moduleName: 'Quản trị hệ thống', moduleIcon: '👑', securityLevel: 'critical' },
  { key: 'admin:view_audit_logs', name: 'Xem & Xuất Nhật ký An ninh Hệ thống', desc: 'Theo dõi toàn bộ vết truy cập dữ liệu, cảnh báo liên nghiệp vụ và nguy cơ rò rỉ', module: 'admin_console', moduleName: 'Quản trị hệ thống', moduleIcon: '👑', securityLevel: 'critical' },
]

export const DEFAULT_ROLE_PERMISSIONS: Record<string, string[]> = {
  admin: SYSTEM_FEATURES.map((f) => f.key),
  manager: [
    'talent:view_candidates', 'talent:search_ai', 'talent:view_cv', 'talent:manage_worklists', 'talent:outreach', 'talent:export_candidates',
    'rb:view_prospects', 'rb:search_ai', 'rb:manage_opportunities', 'rb:update_crm', 'rb:export_opportunities',
    'social:view_signals', 'social:analyze_ai', 'social:link_profile',
    'reports:view_dashboard', 'reports:manage_workflows',
  ],
  recruiter: [
    'talent:view_candidates', 'talent:search_ai', 'talent:view_cv', 'talent:manage_worklists', 'talent:outreach', 'talent:export_candidates',
    'social:view_signals', 'social:analyze_ai', 'social:link_profile',
  ],
  hiring_manager: [
    'talent:view_candidates', 'talent:search_ai', 'talent:view_cv', 'talent:manage_worklists',
  ],
  rb_sales: [
    'rb:view_prospects', 'rb:search_ai', 'rb:manage_opportunities', 'rb:update_crm',
    'social:view_signals', 'social:analyze_ai',
  ],
  edge_operator: [
    'edge:manage_nodes', 'intake:import_excel', 'intake:import_cv',
  ],
}

// Default daily contact unlock quota per role (null = unlimited)
export const DEFAULT_DAILY_ROLE_QUOTAS: Record<string, number | null> = {
  admin: null,
  manager: 50,
  recruiter: 30,
  rb_sales: 15,
  hiring_manager: 10,
  edge_operator: 5,
}

export interface UserCustomUnlockPolicy {
  username: string
  is_unlimited: boolean
  custom_daily_quota?: number
  reason: string
  granted_by: string
}

const ACTION_LABELS: Record<string, string> = {
  view: 'Xem hồ sơ',
  search: 'Tìm kiếm',
  list: 'Xem danh sách',
  download: 'Tải tài liệu',
  export: 'Xuất dữ liệu',
}

const MODULE_LABELS: Record<string, string> = {
  talent: 'Talent Radar',
  rb: 'Growth Radar',
  social: 'Social Radar',
  edge_ops: 'Đồng bộ Edge',
  people_intake: 'Nhập liệu Ứng viên',
  ai_settings: 'Cấu hình AI',
  reports: 'Báo cáo & Vận hành',
  admin_console: 'Quản trị hệ thống',
}

function RoleChecks({
  selected,
  onToggle,
}: {
  selected: string[]
  onToggle: (key: string) => void
}) {
  return (
    <div className="admin-role-grid-selector">
      {ROLES.map((role) => {
        const isChecked = selected.includes(role.key)
        return (
          <div
            key={role.key}
            className={`admin-role-card-item ${isChecked ? 'selected' : ''}`}
            onClick={() => onToggle(role.key)}
          >
            <input
              type="checkbox"
              checked={isChecked}
              onChange={() => onToggle(role.key)}
              onClick={(e) => e.stopPropagation()}
            />
            <div className="admin-role-card-text">
              <span className="admin-role-name">{role.label}</span>
              <span className="admin-role-desc">{role.desc}</span>
            </div>
          </div>
        )
      })}
    </div>
  )
}

function CreateUserForm({ onDone }: { onDone: () => void }) {
  const queryClient = useQueryClient()
  const [loginType, setLoginType] = useState<LoginTypeChoice>('local')
  const [username, setUsername] = useState('')
  const [fullName, setFullName] = useState('')
  const [password, setPassword] = useState('')
  const [roles, setRoles] = useState<string[]>([])
  const [message, setMessage] = useState('')

  const isOtp = loginType === 'otp'

  const create = useMutation({
    mutationFn: () => api.userCreate({ username: username.trim(), password: isOtp ? '' : password, full_name: fullName.trim(), roles, login_type: loginType }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['users'] })
      onDone()
    },
    onError: (error) => setMessage(error instanceof ApiError ? error.message : 'Tạo tài khoản thất bại.'),
  })

  function toggleRole(key: string) {
    setRoles((prev) => (prev.includes(key) ? prev.filter((r) => r !== key) : [...prev, key]))
  }

  return (
    <div className="admin-form-modal">
      <div className="brand-preview-title-row" style={{ marginBottom: 12 }}>
        <h3 style={{ margin: 0, fontSize: 16, fontWeight: 700, color: 'var(--text)' }}>
          ➕ Thêm tài khoản người dùng mới
        </h3>
        <button className="btn btn-secondary btn-sm" onClick={onDone}>✕ Đóng</button>
      </div>

      {/* Bước 1: chọn hình thức đăng nhập — quyết định các trường phải điền */}
      <div>
        <label>Hình thức đăng nhập *</label>
        <select
          className="input-text"
          value={loginType}
          onChange={(event) => { setLoginType(event.target.value as LoginTypeChoice); setMessage('') }}
        >
          <option value="local">Tài khoản thường — đăng nhập bằng mật khẩu</option>
          <option value="otp">Tài khoản Email OTP — nhận mã qua email</option>
        </select>
        <small className="hint">
          {isOtp
            ? 'Loại OTP (TNTalent / MSB) tự xác định theo domain email đã khai ở tab Email OTP.'
            : 'Người dùng đăng nhập bằng username và mật khẩu khởi tạo bên dưới.'}
        </small>
      </div>

      <div className="form-row-2" style={{ marginTop: 12 }}>
        <div>
          <label>{isOtp ? 'Email nhận mã OTP *' : 'Tên đăng nhập (Username) *'}</label>
          <input
            className="input-text"
            type={isOtp ? 'email' : 'text'}
            placeholder={isOtp ? 'vd: nguyen.van.a@msb.com.vn' : 'VD: nguyenvana, huongtt...'}
            value={username}
            onChange={(event) => setUsername(event.target.value)}
          />
        </div>
        <div>
          <label>Họ và tên *</label>
          <input
            className="input-text"
            placeholder="VD: Nguyễn Văn A"
            value={fullName}
            onChange={(event) => setFullName(event.target.value)}
          />
        </div>
      </div>

      {!isOtp && (
        <div style={{ marginTop: 12 }}>
          <label>Mật khẩu khởi tạo *</label>
          <input
            type="password"
            className="input-text"
            autoComplete="new-password"
            placeholder="Nhập mật khẩu an toàn..."
            value={password}
            onChange={(event) => setPassword(event.target.value)}
          />
          <small className="hint">Mật khẩu cần tối thiểu 8 ký tự theo tiêu chuẩn an ninh.</small>
        </div>
      )}

      <div style={{ marginTop: 16 }}>
        <label style={{ fontWeight: 600 }}>Gán vai trò &amp; Phân quyền hệ thống</label>
        <RoleChecks selected={roles} onToggle={toggleRole} />
      </div>

      <div className="form-actions" style={{ marginTop: 16 }}>
        <button
          className="btn btn-primary"
          onClick={() => create.mutate()}
          disabled={!username.trim() || (!isOtp && !password) || create.isPending}
        >
          {create.isPending ? 'Đang khởi tạo…' : 'Xác nhận tạo tài khoản'}
        </button>
        <button className="btn btn-secondary" type="button" onClick={onDone}>
          Huỷ
        </button>
        {message && <span className="save-hint-ok" style={{ color: '#ef4444' }}>{message}</span>}
      </div>
    </div>
  )
}

// Xuất kết quả (tài khoản + mật khẩu vừa cấp) ra file để mail-merge gửi hàng
// loạt bằng Outlook/Gmail — thay vì gõ tay mật khẩu vào một file rồi mới tạo
// tài khoản (rủi ro: mật khẩu thật nằm trong file có thể lưu/gửi lung tung
// TRƯỚC khi có tài khoản để đối chiếu). File này chỉ chứa mật khẩu SAU khi đã
// tạo xong, tải một lần rồi thôi — cùng nguyên tắc "chỉ hiện một lần".
function downloadBulkResultsCsv(result: UserBulkResult) {
  const rows = result.results.filter((row) => row.status === 'created' && (row.login_type ?? 'local') === 'local')
  if (rows.length === 0) return

  const escape = (value: string) => `"${value.replace(/"/g, '""')}"`
  const header = ['username', 'ho_ten', 'mat_khau'].map(escape).join(',')
  const lines = rows.map((row) =>
    [row.username, row.full_name ?? '', row.password ?? ''].map(escape).join(','),
  )
  // BOM để Excel mở đúng dấu tiếng Việt thay vì ra chữ lạ.
  const blob = new Blob(['﻿' + [header, ...lines].join('\r\n')], {
    type: 'text/csv;charset=utf-8',
  })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = `mat_khau_tai_khoan_moi_${new Date().toISOString().slice(0, 10)}.csv`
  link.click()
  URL.revokeObjectURL(url)
}

export function BulkCreatePanel({ onDone }: { onDone: () => void }) {
  const queryClient = useQueryClient()
  const fileInput = useRef<HTMLInputElement>(null)
  const [file, setFile] = useState<File | null>(null)
  const [result, setResult] = useState<UserBulkResult | null>(null)
  const [error, setError] = useState('')

  const upload = useMutation({
    mutationFn: (f: File) => api.userBulkCreate(f),
    onSuccess: (data) => {
      setResult(data)
      setError('')
      if (data.created > 0) queryClient.invalidateQueries({ queryKey: ['users'] })
    },
    onError: (err) => setError(err instanceof ApiError ? err.message : 'Tải lên thất bại.'),
  })

  return (
    <div className="admin-form-modal">
      <div className="brand-preview-title-row" style={{ marginBottom: 12 }}>
        <h3 style={{ margin: 0, fontSize: 16, fontWeight: 700, color: 'var(--text)' }}>
          📁 Nhập danh sách tài khoản hàng loạt qua file Excel
        </h3>
        <button className="btn btn-secondary btn-sm" onClick={onDone}>✕ Đóng</button>
      </div>

      <p className="hint" style={{ margin: '0 0 14px', lineHeight: 1.5 }}>
        Tải file mẫu, điền một người mỗi dòng và chọn "loai_dang_nhap":
        <strong> local</strong> (sinh mật khẩu) hoặc <strong>otp</strong> (username
        phải là email thuộc domain đã khai ở tab Email OTP — loại TNTalent/MSB tự
        xác định). Mỗi dòng xử lý độc lập — dòng lỗi không làm hỏng các dòng hợp lệ.
      </p>

      <div style={{ display: 'flex', gap: 12, alignItems: 'center', marginBottom: 16, flexWrap: 'wrap' }}>
        <a
          className="link"
          href={api.userBulkTemplateUrl()}
          download
          style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontWeight: 600 }}
        >
          ⬇ Tải file mẫu (.xlsx)
        </a>
      </div>

      <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
        <input
          ref={fileInput}
          type="file"
          accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
          className="input-text"
          style={{ maxWidth: 360 }}
          onChange={(event) => {
            setFile(event.target.files?.[0] ?? null)
            setResult(null)
            setError('')
          }}
        />
        <button
          className="btn btn-primary"
          onClick={() => file && upload.mutate(file)}
          disabled={!file || upload.isPending}
        >
          {upload.isPending ? 'Đang tạo…' : 'Tải lên & tạo hàng loạt'}
        </button>
        <button className="btn btn-secondary" type="button" onClick={onDone}>
          Đóng
        </button>
        {error && <span className="save-hint-ok" style={{ color: '#ef4444' }}>{error}</span>}
      </div>

      {result && (
        <div style={{ marginTop: 20 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 10 }}>
            <span style={{ fontSize: 14, fontWeight: 700, color: 'var(--text)' }}>
              Kết quả xử lý: Đã tạo <strong>{result.created}</strong>/{result.total} tài khoản.
            </span>
            {result.results.some((row) => row.status === 'created' && (row.login_type ?? 'local') === 'local') && (
              <>
                <span className="tag" style={{ background: '#fef3c7', color: '#b45309', fontWeight: 600 }}>
                  chép mật khẩu ngay — sẽ không hiện lại
                </span>
                <button
                  type="button"
                  className="link small"
                  onClick={() => downloadBulkResultsCsv(result)}
                >
                  ⬇ Tải kết quả (mật khẩu)
                </button>
              </>
            )}
          </div>

          <table style={{ width: '100%' }}>
            <thead>
              <tr>
                <th>Dòng</th>
                <th>Tên đăng nhập</th>
                <th>Kết quả</th>
                <th>Mật khẩu / lý do</th>
              </tr>
            </thead>
            <tbody>
              {result.results.map((row) => (
                <tr key={row.row}>
                  <td className="num">{row.row}</td>
                  <td><strong>{row.username || <span className="muted">—</span>}</strong></td>
                  <td>
                    {row.status === 'created' ? (
                      <span className="badge ok">đã tạo</span>
                    ) : (
                      <span className="badge err">bị từ chối</span>
                    )}
                  </td>
                  <td>
                    {row.status === 'created' ? (
                      <code className="key-code" style={{ padding: '3px 8px', borderRadius: 4, background: 'rgba(16,185,129,0.1)', color: '#059669', fontWeight: 700 }}>
                        {(row.login_type ?? 'local') === 'local' ? row.password : `Email OTP — ${row.login_type === 'tntalent' ? 'TNTalent' : 'MSB'}`}
                      </code>
                    ) : (
                      <span className="muted small">{row.detail}</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

function UserRowItem({ row, isSelf }: { row: UserRow; isSelf: boolean }) {
  const queryClient = useQueryClient()
  const [editing, setEditing] = useState(false)
  const [fullName, setFullName] = useState(row.full_name)
  const [roles, setRoles] = useState<string[]>(row.roles)
  const [password, setPassword] = useState('')
  const [loginType, setLoginType] = useState<LoginTypeChoice>(row.login_type === 'local' ? 'local' : 'otp')
  const [message, setMessage] = useState('')

  const update = useMutation({
    mutationFn: (patch: Parameters<typeof api.userUpdate>[1]) => api.userUpdate(row.id, patch),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['users'] })
      setMessage('')
      setPassword('')
      setEditing(false)
    },
    onError: (error) => setMessage(error instanceof ApiError ? error.message : 'Lưu thất bại.'),
  })

  function toggleRole(key: string) {
    setRoles((prev) => (prev.includes(key) ? prev.filter((r) => r !== key) : [...prev, key]))
  }

  function saveDetails() {
    const patch: Parameters<typeof api.userUpdate>[1] = { full_name: fullName, roles, login_type: loginType }
    if (password) patch.password = password
    update.mutate(patch)
  }

  const initials = (row.full_name || row.username)
    .split(' ')
    .map((w) => w[0])
    .filter(Boolean)
    .slice(0, 2)
    .join('')
    .toUpperCase() || 'U'

  return (
    <>
      <tr>
        <td>
          <div className="admin-user-cell">
            <div className="admin-user-avatar">{initials}</div>
            <div className="admin-user-meta">
              <div className="admin-user-fullname">
                {row.full_name || row.username}
                {row.is_superuser && <span className="tag" style={{ background: '#f3e8ff', color: '#9333ea', fontSize: 10 }}>superuser</span>}
                {isSelf && <span className="tag" style={{ background: '#e0f2fe', color: '#0284c7', fontSize: 10 }}>bạn</span>}
                <span className="tag" style={{ background: '#eef2ff', color: '#4338ca', fontSize: 10 }}>
                  {row.login_type === 'local' ? 'tài khoản thường' : row.login_type === 'tntalent' ? 'Email OTP TNTalent' : 'Email OTP MSB'}
                </span>
              </div>
              <span className="admin-user-username">@{row.username}</span>
            </div>
          </div>
        </td>
        <td>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
            {row.roles.length > 0 ? (
              row.roles.map((r) => {
                const found = ROLES.find((item) => item.key === r)
                return (
                  <span key={r} className={`role-pill ${found?.color || ''}`}>
                    {found?.label || r}
                  </span>
                )
              })
            ) : (
              <span className="muted" style={{ fontSize: 12 }}>Chưa gán vai trò</span>
            )}
          </div>
        </td>
        <td>
          {row.is_active ? (
            <span className="status-dot-badge active">Đang dùng</span>
          ) : (
            <span className="status-dot-badge locked">Đã khoá</span>
          )}
        </td>
        <td>
          <span style={{ fontSize: 12.5, color: row.last_login ? 'var(--text)' : 'var(--muted)' }}>
            {row.last_login ? new Date(row.last_login).toLocaleString('vi-VN') : 'Chưa đăng nhập'}
          </span>
        </td>
        <td>
          <div style={{ display: 'flex', gap: 6, justifyContent: 'flex-end' }}>
            <button className="btn btn-secondary btn-sm" onClick={() => setEditing((v) => !v)}>
              {editing ? '✕ Đóng' : '✏️ Sửa'}
            </button>
            {!isSelf && (
              <button
                className={`btn btn-sm ${row.is_active ? 'btn-secondary' : 'btn-primary'}`}
                onClick={() => update.mutate({ is_active: !row.is_active })}
                disabled={update.isPending}
                title={row.is_active ? 'Tạm khoá tài khoản này' : 'Mở khoá tài khoản này'}
              >
                {row.is_active ? '🔒 Khoá' : '🔓 Mở lại'}
              </button>
            )}
          </div>
        </td>
      </tr>

      {editing && (
        <tr>
          <td colSpan={5}>
            <div className="admin-form-modal" style={{ margin: '8px 0', border: '1.5px solid var(--accent)' }}>
              <h4 style={{ margin: '0 0 12px', fontSize: 14, fontWeight: 700, color: 'var(--text)' }}>
                Chỉnh sửa tài khoản: @{row.username} ({row.full_name})
              </h4>
              <div className="form-row-2">
                <div>
                  <label>Họ và tên</label>
                  <input className="input-text" value={fullName} onChange={(event) => setFullName(event.target.value)} />
                </div>
                <div>
                  <label>Đặt lại mật khẩu mới (Tuỳ chọn)</label>
                  <input
                    type="password"
                    className="input-text"
                    autoComplete="new-password"
                    placeholder="Để trống = giữ nguyên mật khẩu cũ"
                    value={password}
                    onChange={(event) => setPassword(event.target.value)}
                  />
                </div>
              </div>

              <div style={{ marginTop: 12 }}>
                <label>Hình thức đăng nhập</label>
                <select className="input-text" value={loginType} onChange={(event) => setLoginType(event.target.value as LoginTypeChoice)}>
                  <option value="local">Tài khoản thường — mật khẩu</option>
                  <option value="otp">Tài khoản Email OTP — mã qua email</option>
                </select>
                {loginType === 'otp' && (
                  <small className="hint">Loại OTP (TNTalent / MSB) suy theo domain email của tài khoản; domain phải đã khai ở tab Email OTP.</small>
                )}
                {row.login_type !== 'local' && loginType === 'local' && !password && (
                  <small className="hint" style={{ color: '#b45309' }}>Phải nhập mật khẩu mới khi chuyển từ Email OTP sang tài khoản thường.</small>
                )}
              </div>

              <div style={{ marginTop: 14 }}>
                <label style={{ fontWeight: 600 }}>Cập nhật vai trò &amp; quyền hạn:</label>
                <RoleChecks selected={roles} onToggle={toggleRole} />
              </div>

              <div className="form-actions" style={{ marginTop: 14 }}>
                <button className="btn btn-primary" onClick={saveDetails} disabled={update.isPending}>
                  {update.isPending ? 'Đang lưu…' : 'Lưu thay đổi'}
                </button>
                <button className="btn btn-secondary" onClick={() => setEditing(false)}>Huỷ</button>
                {message && <span className="save-hint-ok" style={{ color: '#ef4444' }}>{message}</span>}
              </div>
            </div>
          </td>
        </tr>
      )}
    </>
  )
}

function UsersPanel({ currentUsername }: { currentUsername: string }) {
  const [panel, setPanel] = useState<'none' | 'create' | 'bulk'>('none')
  const [searchQuery, setSearchQuery] = useState('')
  const [roleFilter, setRoleFilter] = useState('')
  const [statusFilter, setStatusFilter] = useState('')
  const users = useQuery({ queryKey: ['users'], queryFn: api.users, retry: false })

  const userList = users.data?.results ?? []

  // Stats calculation
  const totalUsers = userList.length
  const activeUsers = userList.filter((u) => u.is_active).length
  const lockedUsers = userList.filter((u) => !u.is_active).length
  const superUsers = userList.filter((u) => u.is_superuser).length

  // Filtered list
  const filteredUsers = userList.filter((u) => {
    if (searchQuery.trim()) {
      const q = searchQuery.toLowerCase().trim()
      const matchName = u.full_name?.toLowerCase().includes(q)
      const matchUsername = u.username?.toLowerCase().includes(q)
      if (!matchName && !matchUsername) return false
    }
    if (roleFilter && !u.roles.includes(roleFilter)) return false
    if (statusFilter === 'active' && !u.is_active) return false
    if (statusFilter === 'locked' && u.is_active) return false
    return true
  })

  return (
    <div className="admin-panel-card">
      {/* 4-Stat Metrics Strip */}
      <div className="admin-stats-strip">
        <div className="admin-stat-card">
          <div className="admin-stat-icon-circle admin-stat-icon-blue">👥</div>
          <div className="admin-stat-info">
            <span className="admin-stat-val">{totalUsers}</span>
            <span className="admin-stat-lbl">Tổng tài khoản</span>
          </div>
        </div>
        <div className="admin-stat-card">
          <div className="admin-stat-icon-circle admin-stat-icon-green">✓</div>
          <div className="admin-stat-info">
            <span className="admin-stat-val">{activeUsers}</span>
            <span className="admin-stat-lbl">Đang hoạt động</span>
          </div>
        </div>
        <div className="admin-stat-card">
          <div className="admin-stat-icon-circle admin-stat-icon-rose">🔒</div>
          <div className="admin-stat-info">
            <span className="admin-stat-val">{lockedUsers}</span>
            <span className="admin-stat-lbl">Đã tạm khoá</span>
          </div>
        </div>
        <div className="admin-stat-card">
          <div className="admin-stat-icon-circle admin-stat-icon-purple">👑</div>
          <div className="admin-stat-info">
            <span className="admin-stat-val">{superUsers}</span>
            <span className="admin-stat-lbl">Quản trị viên cấp cao</span>
          </div>
        </div>
      </div>

      {/* Toolbar & Filters */}
      <div className="admin-toolbar-row">
        <div className="admin-search-filters">
          <input
            type="text"
            placeholder="🔍 Tìm theo họ tên, username..."
            className="input-text admin-search-input"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
          />
          <select
            className="admin-select-filter"
            value={roleFilter}
            onChange={(e) => setRoleFilter(e.target.value)}
          >
            <option value="">Tất cả vai trò</option>
            {ROLES.map((r) => (
              <option key={r.key} value={r.key}>{r.label}</option>
            ))}
          </select>
          <select
            className="admin-select-filter"
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
          >
            <option value="">Tất cả trạng thái</option>
            <option value="active">Đang hoạt động</option>
            <option value="locked">Đã khoá</option>
          </select>
        </div>

        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          <button
            className="btn btn-primary btn-sm"
            onClick={() => setPanel((v) => (v === 'create' ? 'none' : 'create'))}
          >
            {panel === 'create' ? '✕ Đóng form' : '➕ Thêm tài khoản'}
          </button>
          <button
            className="btn btn-secondary btn-sm"
            onClick={() => setPanel((v) => (v === 'bulk' ? 'none' : 'bulk'))}
          >
            {panel === 'bulk' ? '✕ Đóng' : '📁 Tạo hàng loạt (.xlsx)'}
          </button>
        </div>
      </div>

      {panel === 'create' && <CreateUserForm onDone={() => setPanel('none')} />}
      {panel === 'bulk' && <BulkCreatePanel onDone={() => setPanel('none')} />}

      {/* Users Table */}
      <div style={{ overflowX: 'auto' }}>
        <table style={{ width: '100%' }}>
          <thead>
            <tr>
              <th>Nhân sự / Tài khoản</th>
              <th>Vai trò phân quyền</th>
              <th>Trạng thái</th>
              <th>Đăng nhập gần nhất</th>
              <th style={{ textAlign: 'right' }}>Thao tác</th>
            </tr>
          </thead>
          <tbody>
            {filteredUsers.map((row) => (
              <UserRowItem key={row.id} row={row} isSelf={row.username === currentUsername} />
            ))}
            {filteredUsers.length === 0 && (
              <tr>
                <td colSpan={5} className="empty" style={{ textAlign: 'center', padding: '36px 16px' }}>
                  Không tìm thấy tài khoản nào khớp với bộ lọc.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function RoleFeaturesPolicyPanel() {
  const users = useQuery({ queryKey: ['users'], queryFn: api.users, retry: false })
  const userList = users.data?.results ?? []

  const [selectedRole, setSelectedRole] = useState<string>('recruiter')
  const [viewMode, setViewMode] = useState<'per-role' | 'matrix'>('per-role')
  const [savedMsg, setSavedMsg] = useState('')

  // Permissions state per role (persisted in localStorage)
  const [rolePermissions, setRolePermissions] = useState<Record<string, string[]>>(() => {
    try {
      const saved = localStorage.getItem('radar_role_feature_permissions')
      if (saved) {
        return JSON.parse(saved)
      }
    } catch {
      // ignore
    }
    return DEFAULT_ROLE_PERMISSIONS
  })

  const currentRoleInfo = ROLES.find((r) => r.key === selectedRole) || ROLES[0]
  const currentPermissions = rolePermissions[selectedRole] || []

  // Count active users with this role
  const userCountForRole = userList.filter((u) => u.roles.includes(selectedRole)).length

  // Toggle single permission for selected role
  const togglePermission = (roleKey: string, featKey: string) => {
    setRolePermissions((prev) => {
      const current = prev[roleKey] || []
      const updated = current.includes(featKey)
        ? current.filter((k) => k !== featKey)
        : [...current, featKey]
      const next = { ...prev, [roleKey]: updated }
      try {
        localStorage.setItem('radar_role_feature_permissions', JSON.stringify(next))
      } catch {
        // ignore
      }
      return next
    })
  }

  // Grant all permissions for active role
  const handleGrantAll = () => {
    setRolePermissions((prev) => {
      const next = { ...prev, [selectedRole]: SYSTEM_FEATURES.map((f) => f.key) }
      localStorage.setItem('radar_role_feature_permissions', JSON.stringify(next))
      return next
    })
    showSaveNotice('✓ Đã cấp toàn bộ tính năng cho vai trò này.')
  }

  // Revoke all permissions for active role
  const handleRevokeAll = () => {
    setRolePermissions((prev) => {
      const next = { ...prev, [selectedRole]: [] }
      localStorage.setItem('radar_role_feature_permissions', JSON.stringify(next))
      return next
    })
    showSaveNotice('✓ Đã thu hồi toàn bộ quyền hạn của vai trò này.')
  }

  // Reset active role to defaults
  const handleResetRoleDefaults = () => {
    setRolePermissions((prev) => {
      const next = { ...prev, [selectedRole]: DEFAULT_ROLE_PERMISSIONS[selectedRole] || [] }
      localStorage.setItem('radar_role_feature_permissions', JSON.stringify(next))
      return next
    })
    showSaveNotice('✓ Đã khôi phục quyền mặc định thành công.')
  }

  const showSaveNotice = (msg: string) => {
    setSavedMsg(msg)
    setTimeout(() => setSavedMsg(''), 3500)
  }

  // Group features by module
  const modulesList = [
    { key: 'talent', name: 'Talent Radar (Tuyển dụng & Săn nhân tài)', icon: '🎯' },
    { key: 'rb', name: 'Growth Radar (Khách hàng bán lẻ & Bán chéo)', icon: '💳' },
    { key: 'social', name: 'Social Radar (Tín hiệu Mạng xã hội)', icon: '🌐' },
    { key: 'reports', name: 'Báo cáo & Vận hành Quy trình', icon: '📊' },
    { key: 'edge_ops', name: 'Đồng bộ Dữ liệu & Edge Ops', icon: '⚙️' },
    { key: 'people_intake', name: 'Nhập liệu Ứng viên (Excel & CV)', icon: '📥' },
    { key: 'ai_settings', name: 'Cấu hình AI & Trí tuệ', icon: '🧠' },
    { key: 'admin_console', name: 'Quản trị Hệ thống & An ninh', icon: '👑' },
  ]

  return (
    <div className="admin-panel-card">
      {/* Title & View Switcher */}
      <div className="brand-preview-title-row" style={{ margin: 0 }}>
        <div>
          <h3 style={{ fontSize: 16, fontWeight: 700, margin: '0 0 4px', color: 'var(--text)' }}>
            🔐 Quản trị Chi tiết Tính năng &amp; Phân quyền Vai trò (Feature RBAC Policy)
          </h3>
          <span className="hint">
            Kiểm soát quyền truy cập chi tiết đến từng hành động, xem CV, xuất dữ liệu và mô hình AI cho từng vai trò trong tổ chức.
          </span>
        </div>

        <div style={{ display: 'flex', gap: 6 }}>
          <button
            className={`btn btn-sm ${viewMode === 'per-role' ? 'btn-primary' : 'btn-secondary'}`}
            onClick={() => setViewMode('per-role')}
          >
            📋 Theo từng vai trò
          </button>
          <button
            className={`btn btn-sm ${viewMode === 'matrix' ? 'btn-primary' : 'btn-secondary'}`}
            onClick={() => setViewMode('matrix')}
          >
            📊 Bảng ma trận toàn diện
          </button>
        </div>
      </div>

      {savedMsg && (
        <div className="talent-success-banner" style={{ margin: '4px 0 10px', maxWidth: '100%' }}>
          {savedMsg}
        </div>
      )}

      {viewMode === 'per-role' ? (
        <div className="role-policy-container">
          {/* Horizontal Role Selector Bar */}
          <div className="role-selector-horizontal">
            {ROLES.map((r) => {
              const count = userList.filter((u) => u.roles.includes(r.key)).length
              const isSelected = selectedRole === r.key
              return (
                <div
                  key={r.key}
                  className={`role-nav-pill-card ${isSelected ? 'active' : ''}`}
                  onClick={() => setSelectedRole(r.key)}
                >
                  <div className={`role-nav-avatar ${r.color}`}>{r.badgeText[0]}</div>
                  <div className="role-nav-text">
                    <span className="role-nav-title">{r.label}</span>
                    <span className="role-nav-count">{count} nhân sự đang gán</span>
                  </div>
                </div>
              )
            })}
          </div>

          {/* Selected Role Meta & Action Bar */}
          <div className="role-detail-header-card">
            <div className="role-detail-meta">
              <div className="role-detail-title-row">
                <span className={`role-pill ${currentRoleInfo.color}`} style={{ fontSize: 13, padding: '4px 10px' }}>
                  {currentRoleInfo.badgeText}
                </span>
                <h4 className="role-detail-title">{currentRoleInfo.label}</h4>
                <span className="hint" style={{ fontSize: 12 }}>
                  ({currentPermissions.length}/{SYSTEM_FEATURES.length} tính năng được cấp)
                </span>
              </div>
              <p className="role-detail-desc">{currentRoleInfo.desc} • Áp dụng cho <strong>{userCountForRole}</strong> tài khoản.</p>
            </div>

            <div className="role-detail-actions">
              <button className="btn btn-secondary btn-sm" onClick={handleGrantAll}>
                ✓ Cho phép tất cả
              </button>
              <button className="btn btn-secondary btn-sm" onClick={handleRevokeAll}>
                ✕ Bỏ chọn tất cả
              </button>
              <button className="btn btn-secondary btn-sm" onClick={handleResetRoleDefaults}>
                🔄 Khôi phục mặc định
              </button>
              <button
                className="btn btn-primary btn-sm"
                onClick={() => showSaveNotice(`✓ Đã lưu chính sách phân quyền cho vai trò ${currentRoleInfo.label} thành công.`)}
              >
                💾 Lưu chính sách
              </button>
            </div>
          </div>

          {/* Feature Groups Accordions */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
            {modulesList.map((mod) => {
              const modFeatures = SYSTEM_FEATURES.filter((f) => f.module === mod.key)
              if (modFeatures.length === 0) return null

              const grantedCount = modFeatures.filter((f) => currentPermissions.includes(f.key)).length

              return (
                <div key={mod.key} className="feature-group-card">
                  <div className="feature-group-header">
                    <h5 className="feature-group-title">
                      <span>{mod.icon}</span>
                      <span>{mod.name}</span>
                    </h5>
                    <span className="hint" style={{ fontSize: 12, fontWeight: 600 }}>
                      Được cấp: {grantedCount}/{modFeatures.length}
                    </span>
                  </div>

                  <div className="feature-group-list">
                    {modFeatures.map((feat) => {
                      const isGranted = currentPermissions.includes(feat.key)

                      return (
                        <div key={feat.key} className="feature-item-row">
                          <div className="feature-item-left">
                            <input
                              type="checkbox"
                              className="feature-item-checkbox"
                              checked={isGranted}
                              onChange={() => togglePermission(selectedRole, feat.key)}
                              id={`feat-${selectedRole}-${feat.key}`}
                            />
                            <label
                              htmlFor={`feat-${selectedRole}-${feat.key}`}
                              className="feature-item-text"
                              style={{ cursor: 'pointer', margin: 0 }}
                            >
                              <div className="feature-item-title-row">
                                <span className="feature-item-name" style={{ color: isGranted ? 'var(--text)' : 'var(--muted)' }}>
                                  {feat.name}
                                </span>
                                <code className="feature-key-code">{feat.key}</code>
                              </div>
                              <p className="feature-item-desc">{feat.desc}</p>
                            </label>
                          </div>

                          <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexShrink: 0 }}>
                            {feat.securityLevel === 'normal' && (
                              <span className="security-level-pill normal">● Tiêu chuẩn</span>
                            )}
                            {feat.securityLevel === 'sensitive' && (
                              <span className="security-level-pill sensitive">⚠️ Nhạy cảm / CV</span>
                            )}
                            {feat.securityLevel === 'critical' && (
                              <span className="security-level-pill critical">🚨 Tối mật / Xuất dữ liệu</span>
                            )}
                          </div>
                        </div>
                      )
                    })}
                  </div>
                </div>
              )
            })}
          </div>
        </div>
      ) : (
        /* Full Matrix Comprehensive Grid View */
        <div style={{ overflowX: 'auto' }}>
          <table className="admin-matrix-grid" style={{ width: '100%', minWidth: 900 }}>
            <thead>
              <tr>
                <th style={{ width: '32%' }}>Tính năng &amp; Thẩm quyền</th>
                <th style={{ width: '14%' }}>Mức an ninh</th>
                {ROLES.map((r) => (
                  <th key={r.key} style={{ textAlign: 'center' }}>
                    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 2 }}>
                      <span>{r.badgeText}</span>
                      <small style={{ fontSize: 10, color: 'var(--muted)', fontWeight: 'normal' }}>
                        ({rolePermissions[r.key]?.length || 0})
                      </small>
                    </div>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {SYSTEM_FEATURES.map((feat) => (
                <tr key={feat.key}>
                  <td>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                      <span style={{ fontWeight: 700, fontSize: 13 }}>{feat.name}</span>
                      <span style={{ fontSize: 11, color: 'var(--muted)' }}>{feat.moduleName} • <code>{feat.key}</code></span>
                    </div>
                  </td>
                  <td>
                    {feat.securityLevel === 'normal' && (
                      <span className="security-level-pill normal" style={{ fontSize: 10 }}>Tiêu chuẩn</span>
                    )}
                    {feat.securityLevel === 'sensitive' && (
                      <span className="security-level-pill sensitive" style={{ fontSize: 10 }}>Nhạy cảm</span>
                    )}
                    {feat.securityLevel === 'critical' && (
                      <span className="security-level-pill critical" style={{ fontSize: 10 }}>Tối mật</span>
                    )}
                  </td>
                  {ROLES.map((r) => {
                    const isGranted = (rolePermissions[r.key] || []).includes(feat.key)
                    return (
                      <td key={r.key} style={{ textAlign: 'center', cursor: 'pointer' }} onClick={() => togglePermission(r.key, feat.key)}>
                        <input
                          type="checkbox"
                          checked={isGranted}
                          onChange={() => togglePermission(r.key, feat.key)}
                          onClick={(e) => e.stopPropagation()}
                          style={{ cursor: 'pointer', width: 16, height: 16 }}
                        />
                      </td>
                    )
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

// --------------------------------------------------------------------------
// 3. Phân hệ Quản lý Định mức Mở Liên hệ (Contact Unlock Quota & Policy)
// --------------------------------------------------------------------------
function ContactUnlockQuotaPanel({ currentUsername }: { currentUsername: string }) {
  const users = useQuery({ queryKey: ['users'], queryFn: api.users, retry: false })
  const userList = users.data?.results ?? []

  // Role-based quotas state
  const [roleQuotas, setRoleQuotas] = useState<Record<string, number | null>>(() => {
    try {
      const saved = localStorage.getItem('radar_daily_role_quotas')
      if (saved) return JSON.parse(saved)
    } catch {
      // ignore
    }
    return DEFAULT_DAILY_ROLE_QUOTAS
  })

  // User custom policies state (ContactUnlockPolicy)
  const [userPolicies, setUserPolicies] = useState<UserCustomUnlockPolicy[]>(() => {
    try {
      const saved = localStorage.getItem('radar_user_custom_unlock_policies')
      if (saved) return JSON.parse(saved)
    } catch {
      // ignore
    }
    return [
      { username: 'truong_phong_ta', is_unlimited: false, custom_daily_quota: 100, reason: 'Chỉ đạo chiến dịch tuyển dụng quy mô lớn Q3/2026', granted_by: 'admin' },
      { username: 'lead_rm_vip', is_unlimited: false, custom_daily_quota: 40, reason: 'Chăm sóc danh mục khách hàng VIP phân khúc Private Banking', granted_by: 'admin' },
    ]
  })

  const [isAddingPolicy, setIsAddingPolicy] = useState(false)
  const [newPolicyUser, setNewPolicyUser] = useState('')
  const [newPolicyUnlimited, setNewPolicyUnlimited] = useState(false)
  const [newPolicyQuota, setNewPolicyQuota] = useState<number>(50)
  const [newPolicyReason, setNewPolicyReason] = useState('')
  const [policyError, setPolicyError] = useState('')
  const [savedNotice, setSavedNotice] = useState('')

  // Update role quota
  const handleUpdateRoleQuota = (roleKey: string, value: number | null) => {
    setRoleQuotas((prev) => {
      const next = { ...prev, [roleKey]: value }
      localStorage.setItem('radar_daily_role_quotas', JSON.stringify(next))
      return next
    })
  }

  // Save custom policy for user
  const handleSaveCustomPolicy = (e: React.FormEvent) => {
    e.preventDefault()
    if (!newPolicyUser) {
      setPolicyError('Vui lòng chọn tài khoản nhân sự.')
      return
    }
    if (!newPolicyReason.trim()) {
      setPolicyError('Bắt buộc nhập lý do phê duyệt hạn mức riêng để phục vụ kiểm toán.')
      return
    }

    const newPolicy: UserCustomUnlockPolicy = {
      username: newPolicyUser,
      is_unlimited: newPolicyUnlimited,
      custom_daily_quota: newPolicyUnlimited ? undefined : Number(newPolicyQuota) || 30,
      reason: newPolicyReason.trim(),
      granted_by: currentUsername || 'admin',
    }

    setUserPolicies((prev) => {
      const filtered = prev.filter((p) => p.username !== newPolicyUser)
      const next = [newPolicy, ...filtered]
      localStorage.setItem('radar_user_custom_unlock_policies', JSON.stringify(next))
      return next
    })

    setIsAddingPolicy(false)
    setNewPolicyUser('')
    setNewPolicyReason('')
    setPolicyError('')
    showNotice(`✓ Đã thiết lập hạn mức mở liên hệ riêng cho @${newPolicyUser} thành công.`)
  }

  // Remove custom policy
  const handleRemovePolicy = (username: string) => {
    setUserPolicies((prev) => {
      const next = prev.filter((p) => p.username !== username)
      localStorage.setItem('radar_user_custom_unlock_policies', JSON.stringify(next))
      return next
    })
    showNotice(`✓ Đã thu hồi hạn mức riêng của @${username}, đưa về hạn mức mặc định theo vai trò.`)
  }

  const handleResetRoleQuotas = () => {
    setRoleQuotas(DEFAULT_DAILY_ROLE_QUOTAS)
    localStorage.setItem('radar_daily_role_quotas', JSON.stringify(DEFAULT_DAILY_ROLE_QUOTAS))
    showNotice('✓ Đã khôi phục định mức mặc định theo vai trò.')
  }

  const showNotice = (msg: string) => {
    setSavedNotice(msg)
    setTimeout(() => setSavedNotice(''), 3500)
  }

  // Calculate effective quota for each user
  const getUserEffectiveQuota = (u: UserRow): { limit: number | null; isCustom: boolean; reason?: string } => {
    if (u.is_superuser) return { limit: null, isCustom: false }
    const custom = userPolicies.find((p) => p.username === u.username)
    if (custom) {
      return {
        limit: custom.is_unlimited ? null : (custom.custom_daily_quota ?? 30),
        isCustom: true,
        reason: custom.reason,
      }
    }
    const userRoleKeys = u.roles || []
    if (userRoleKeys.includes('admin')) return { limit: roleQuotas.admin ?? null, isCustom: false }

    const limits = userRoleKeys.map((r) => roleQuotas[r] ?? 15)
    if (limits.length === 0) return { limit: 5, isCustom: false }
    if (limits.some((l) => l === null)) return { limit: null, isCustom: false }
    return { limit: Math.max(...(limits as number[])), isCustom: false }
  }

  return (
    <div className="admin-panel-card">
      <div className="brand-preview-title-row" style={{ margin: 0 }}>
        <div>
          <h3 style={{ fontSize: 16, fontWeight: 700, margin: '0 0 4px', color: 'var(--text)' }}>
            📞 Quản trị Định mức Mở Liên hệ Hàng Ngày (Contact Unlock Quota Policy)
          </h3>
          <span className="hint">
            Kiểm soát số lượng số điện thoại &amp; email tối đa 1 người / 1 vai trò được mở khóa mỗi ngày để ngăn ngừa rò rỉ dữ liệu khách hàng &amp; ứng viên.
          </span>
        </div>

        <button className="btn btn-secondary btn-sm" onClick={handleResetRoleQuotas}>
          🔄 Khôi phục mặc định
        </button>
      </div>

      {savedNotice && (
        <div className="talent-success-banner" style={{ margin: '4px 0 10px', maxWidth: '100%' }}>
          {savedNotice}
        </div>
      )}

      <div className="quota-section-wrapper">
        {/* Phần 1: Định mức theo từng vai trò */}
        <div>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
            <h4 style={{ margin: 0, fontSize: 14.5, fontWeight: 700, color: 'var(--text)' }}>
              1. Hạn mức mặc định theo từng vai trò (Role Quota)
            </h4>
            <span className="hint" style={{ fontSize: 12 }}>Áp dụng tự động cho nhân sự có vai trò tương ứng</span>
          </div>

          <div className="quota-role-cards-grid">
            {ROLES.map((r) => {
              const currentQuota = roleQuotas[r.key]
              const isUnlimited = currentQuota === null
              const usersInRole = userList.filter((u) => u.roles.includes(r.key)).length

              return (
                <div key={r.key} className="quota-role-card">
                  <div className="quota-role-head">
                    <div className="quota-role-title-group">
                      <span className={`role-pill ${r.color}`}>{r.badgeText}</span>
                      <span className="quota-role-name">{r.label}</span>
                    </div>
                    <span className="hint" style={{ fontSize: 11.5 }}>{usersInRole} người</span>
                  </div>

                  <p className="hint" style={{ margin: 0, fontSize: 12, lineHeight: 1.4 }}>
                    {r.desc}
                  </p>

                  <div className="quota-input-row">
                    {isUnlimited ? (
                      <span className="quota-badge-pill unlimited">👑 Không giới hạn</span>
                    ) : (
                      <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                        <input
                          type="number"
                          min={1}
                          max={1000}
                          className="input-text quota-number-input"
                          value={currentQuota ?? 30}
                          onChange={(e) => handleUpdateRoleQuota(r.key, Math.max(1, parseInt(e.target.value) || 1))}
                        />
                        <span style={{ fontSize: 13, fontWeight: 600, color: 'var(--text)' }}>lượt / ngày</span>
                      </div>
                    )}

                    <label className="quota-unlimited-label" style={{ marginLeft: 'auto' }}>
                      <input
                        type="checkbox"
                        checked={isUnlimited}
                        onChange={(e) => handleUpdateRoleQuota(r.key, e.target.checked ? null : 30)}
                      />
                      Vô hạn
                    </label>
                  </div>
                </div>
              )
            })}
          </div>
        </div>

        {/* Phần 2: Cấp hạn mức riêng cho từng cá nhân (ContactUnlockPolicy) */}
        <div style={{ borderTop: '1px solid var(--border)', paddingTop: 18 }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12, flexWrap: 'wrap', gap: 10 }}>
            <div>
              <h4 style={{ margin: 0, fontSize: 14.5, fontWeight: 700, color: 'var(--text)' }}>
                2. Hạn mức mở rộng riêng cho cá nhân (Special User Policy)
              </h4>
              <span className="hint" style={{ fontSize: 12 }}>
                Dành cho trưởng nhóm, dự án đặc biệt cần định mức cao hơn mức chuẩn của vai trò.
              </span>
            </div>

            <button
              className="btn btn-primary btn-sm"
              onClick={() => setIsAddingPolicy((v) => !v)}
            >
              {isAddingPolicy ? '✕ Đóng form' : '➕ Cấp hạn mức riêng cho nhân sự'}
            </button>
          </div>

          {isAddingPolicy && (
            <form onSubmit={handleSaveCustomPolicy} className="admin-form-modal" style={{ marginBottom: 16 }}>
              <h4 style={{ margin: '0 0 12px', fontSize: 14, fontWeight: 700 }}>
                Cấp hạn mức mở khoá liên hệ cá nhân
              </h4>

              <div className="form-row-2">
                <div>
                  <label>Chọn tài khoản nhân sự *</label>
                  <select
                    className="input-text"
                    value={newPolicyUser}
                    onChange={(e) => setNewPolicyUser(e.target.value)}
                  >
                    <option value="">-- Chọn nhân sự từ danh sách --</option>
                    {userList.map((u) => (
                      <option key={u.username} value={u.username}>
                        @{u.username} — {u.full_name} ({u.role_labels.join(', ') || 'Chưa gán vai trò'})
                      </option>
                    ))}
                  </select>
                </div>

                <div>
                  <label>Định mức cấp phát (Lượt mở / ngày)</label>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginTop: 4 }}>
                    {!newPolicyUnlimited ? (
                      <input
                        type="number"
                        min={1}
                        max={2000}
                        className="input-text"
                        style={{ maxWidth: 140 }}
                        value={newPolicyQuota}
                        onChange={(e) => setNewPolicyQuota(parseInt(e.target.value) || 30)}
                      />
                    ) : (
                      <span className="quota-badge-pill unlimited">👑 Không giới hạn lượt mở</span>
                    )}

                    <label className="quota-unlimited-label">
                      <input
                        type="checkbox"
                        checked={newPolicyUnlimited}
                        onChange={(e) => setNewPolicyUnlimited(e.target.checked)}
                      />
                      Không giới hạn
                    </label>
                  </div>
                </div>
              </div>

              <div style={{ marginTop: 12 }}>
                <label>Lý do phê duyệt định mức riêng (Bắt buộc cho Kiểm toán &amp; Compliance) *</label>
                <input
                  type="text"
                  className="input-text"
                  placeholder="VD: Phụ trách chiến dịch săn nhân tài khối Công nghệ thông tin..."
                  value={newPolicyReason}
                  onChange={(e) => setNewPolicyReason(e.target.value)}
                />
              </div>

              {policyError && <p className="error-text" style={{ marginTop: 8 }}>{policyError}</p>}

              <div className="form-actions" style={{ marginTop: 14 }}>
                <button type="submit" className="btn btn-primary">Xác nhận cấp hạn mức</button>
                <button type="button" className="btn btn-secondary" onClick={() => setIsAddingPolicy(false)}>Huỷ</button>
              </div>
            </form>
          )}

          {/* Bảng danh sách chính sách riêng */}
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%' }}>
              <thead>
                <tr>
                  <th>Tài khoản nhân sự</th>
                  <th>Hạn mức áp dụng</th>
                  <th>Lý do cấp phát (Compliance)</th>
                  <th>Người phê duyệt</th>
                  <th style={{ textAlign: 'right' }}>Thao tác</th>
                </tr>
              </thead>
              <tbody>
                {userPolicies.map((p) => {
                  const targetUser = userList.find((u) => u.username === p.username)
                  return (
                    <tr key={p.username}>
                      <td>
                        <div style={{ display: 'flex', flexDirection: 'column' }}>
                          <strong style={{ fontSize: 13.5 }}>@{p.username}</strong>
                          <span className="muted" style={{ fontSize: 12 }}>{targetUser?.full_name || 'Nhân sự MSB'}</span>
                        </div>
                      </td>
                      <td>
                        {p.is_unlimited ? (
                          <span className="quota-badge-pill unlimited">👑 Không giới hạn</span>
                        ) : (
                          <span className="quota-badge-pill custom">⭐ {p.custom_daily_quota} lượt / ngày</span>
                        )}
                      </td>
                      <td>
                        <span style={{ fontSize: 13 }}>{p.reason}</span>
                      </td>
                      <td>
                        <span className="muted" style={{ fontSize: 12 }}>@{p.granted_by}</span>
                      </td>
                      <td style={{ textAlign: 'right' }}>
                        <button
                          className="btn btn-secondary btn-sm"
                          onClick={() => handleRemovePolicy(p.username)}
                          title="Huỷ hạn mức riêng và đưa về mức theo vai trò"
                        >
                          🗑️ Thu hồi
                        </button>
                      </td>
                    </tr>
                  )
                })}
                {userPolicies.length === 0 && (
                  <tr>
                    <td colSpan={5} className="empty" style={{ textAlign: 'center', padding: '24px 16px' }}>
                      Chưa có nhân sự nào được cấp hạn mức riêng. Tất cả nhân sự đang áp dụng định mức mặc định theo vai trò.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>

        {/* Phần 3: Giám sát Định mức Thực Tế Của Toàn Bộ Nhân Viên */}
        <div style={{ borderTop: '1px solid var(--border)', paddingTop: 18 }}>
          <h4 style={{ margin: '0 0 4px', fontSize: 14.5, fontWeight: 700, color: 'var(--text)' }}>
            3. Bảng tổng hợp hạn mức mở liên hệ của toàn bộ nhân sự
          </h4>
          <span className="hint" style={{ display: 'block', marginBottom: 12 }}>
            Tổng hợp định mức thực tế của từng tài khoản dựa trên vai trò hoặc chính sách riêng biệt.
          </span>

          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%' }}>
              <thead>
                <tr>
                  <th>Tài khoản</th>
                  <th>Vai trò chính</th>
                  <th>Loại hạn mức</th>
                  <th>Hạn mức tối đa/ngày</th>
                  <th>Trạng thái sử dụng</th>
                </tr>
              </thead>
              <tbody>
                {userList.map((u) => {
                  const effective = getUserEffectiveQuota(u)
                  return (
                    <tr key={u.id}>
                      <td>
                        <strong>@{u.username}</strong>
                        <div style={{ fontSize: 12, color: 'var(--muted)' }}>{u.full_name}</div>
                      </td>
                      <td>
                        {u.roles.map((r) => (
                          <span key={r} className="role-pill" style={{ fontSize: 11 }}>{r}</span>
                        ))}
                        {u.roles.length === 0 && <span className="muted">—</span>}
                      </td>
                      <td>
                        {u.is_superuser ? (
                          <span className="quota-badge-pill unlimited">Superuser</span>
                        ) : effective.isCustom ? (
                          <span className="quota-badge-pill custom">Hạn mức riêng</span>
                        ) : (
                          <span className="quota-badge-pill standard">Theo vai trò</span>
                        )}
                      </td>
                      <td>
                        {effective.limit === null ? (
                          <span style={{ fontWeight: 700, color: '#9333ea' }}>Không giới hạn</span>
                        ) : (
                          <strong style={{ fontSize: 14, color: 'var(--text)' }}>
                            {effective.limit} lượt / ngày
                          </strong>
                        )}
                      </td>
                      <td>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 10, minWidth: 160 }}>
                          <div className="quota-progress-track">
                            <div
                              className="quota-progress-fill green"
                              style={{ width: '15%' }}
                            />
                          </div>
                          <span className="muted small" style={{ whiteSpace: 'nowrap' }}>
                            Sẵn sàng
                          </span>
                        </div>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  )
}

function AccessLogPanel() {
  const [user, setUser] = useState('')
  const [action, setAction] = useState('')
  const [crossDomain, setCrossDomain] = useState(false)
  const [exfiltration, setExfiltration] = useState(false)
  const [denied, setDenied] = useState(false)

  const summary = useQuery({ queryKey: ['access-log-summary'], queryFn: api.accessLogSummary, retry: false })

  const params: Record<string, string> = {}
  if (user.trim()) params.user = user.trim()
  if (action) params.action = action
  if (crossDomain) params.cross_domain = '1'
  if (exfiltration) params.exfiltration = '1'
  if (denied) params.denied = '1'

  const log = useQuery({
    queryKey: ['access-log', params],
    queryFn: () => api.accessLog(params),
    retry: false,
  })

  return (
    <div className="admin-panel-card">
      {/* 4-Stat Security Strip */}
      <div className="admin-stats-strip">
        <div className="admin-stat-card">
          <div className="admin-stat-icon-circle admin-stat-icon-blue">🛡️</div>
          <div className="admin-stat-info">
            <span className="admin-stat-val">{summary.data?.total?.toLocaleString('vi-VN') ?? '—'}</span>
            <span className="admin-stat-lbl">Tổng lượt ghi nhận</span>
          </div>
        </div>
        <div className="admin-stat-card">
          <div className="admin-stat-icon-circle admin-stat-icon-amber">⚡</div>
          <div className="admin-stat-info">
            <span className="admin-stat-val">{summary.data?.cross_domain?.toLocaleString('vi-VN') ?? '—'}</span>
            <span className="admin-stat-lbl">Truy cập liên nghiệp vụ</span>
          </div>
        </div>
        <div className="admin-stat-card">
          <div className="admin-stat-icon-circle admin-stat-icon-rose">🚫</div>
          <div className="admin-stat-info">
            <span className="admin-stat-val">{summary.data?.denied?.toLocaleString('vi-VN') ?? '—'}</span>
            <span className="admin-stat-lbl">Truy cập bị chặn</span>
          </div>
        </div>
        <div className="admin-stat-card">
          <div className="admin-stat-icon-circle admin-stat-icon-purple">📤</div>
          <div className="admin-stat-info">
            <span className="admin-stat-val">{summary.data?.exfiltration?.toLocaleString('vi-VN') ?? '—'}</span>
            <span className="admin-stat-lbl">Tải / Xuất dữ liệu</span>
          </div>
        </div>
      </div>

      {/* Filter Toolbar */}
      <div className="admin-toolbar-row">
        <div className="admin-search-filters">
          <input
            type="text"
            placeholder="🔍 Tìm theo username..."
            className="input-text admin-search-input"
            value={user}
            onChange={(event) => setUser(event.target.value)}
          />
          <select
            className="admin-select-filter"
            value={action}
            onChange={(event) => setAction(event.target.value)}
          >
            <option value="">Tất cả hành động</option>
            {Object.entries(ACTION_LABELS).map(([key, label]) => (
              <option key={key} value={key}>{label}</option>
            ))}
          </select>
          <label className="toggle" style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 13, cursor: 'pointer' }}>
            <input
              type="checkbox"
              checked={crossDomain}
              onChange={(event) => setCrossDomain(event.target.checked)}
            />
            ⚠️ Liên nghiệp vụ
          </label>
          <label className="toggle" style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 13, cursor: 'pointer' }}>
            <input
              type="checkbox"
              checked={exfiltration}
              onChange={(event) => setExfiltration(event.target.checked)}
            />
            📤 Xuất dữ liệu
          </label>
          <label className="toggle" style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 13, cursor: 'pointer' }}>
            <input
              type="checkbox"
              checked={denied}
              onChange={(event) => setDenied(event.target.checked)}
            />
            🚫 Bị chặn
          </label>
        </div>
      </div>

      {/* Log Header Count */}
      <div className="result-head" style={{ margin: 0 }}>
        <h3 style={{ fontSize: 15, fontWeight: 700, margin: 0 }}>
          Danh sách nhật ký an ninh{' '}
          {log.data && <span className="count">({log.data.count.toLocaleString('vi-VN')} sự kiện)</span>}
        </h3>
      </div>

      {/* Log Table */}
      <div style={{ overflowX: 'auto' }}>
        <table style={{ width: '100%' }}>
          <thead>
            <tr>
              <th>Thời gian</th>
              <th>Người dùng</th>
              <th>Hành động</th>
              <th>Phân hệ (Module)</th>
              <th>Đối tượng hồ sơ</th>
              <th>Địa chỉ IP</th>
              <th>Cảnh báo an ninh</th>
            </tr>
          </thead>
          <tbody>
            {(log.data?.results ?? []).map((row: AccessLogRow) => (
              <tr key={row.id}>
                <td style={{ fontSize: 12.5, whiteSpace: 'nowrap' }}>
                  {new Date(row.at).toLocaleString('vi-VN')}
                </td>
                <td>
                  <strong>@{row.user}</strong>
                </td>
                <td>
                  <span className="role-pill" style={{ background: 'rgba(2,132,199,0.08)', color: '#0284c7', fontWeight: 600 }}>
                    {ACTION_LABELS[row.action] ?? row.action}
                  </span>
                </td>
                <td>
                  <span style={{ fontSize: 13, fontWeight: 600 }}>
                    {MODULE_LABELS[row.module] ?? row.module}
                  </span>
                </td>
                <td>
                  {row.person_name ? (
                    <span style={{ color: 'var(--text)', fontWeight: 600 }}>{row.person_name}</span>
                  ) : (
                    <span className="muted">—</span>
                  )}
                </td>
                <td className="muted small">{row.ip || '—'}</td>
                <td>
                  <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
                    {row.cross_domain && <span className="badge warn">liên nghiệp vụ</span>}
                    {row.exfiltration && <span className="badge warn">ra khỏi hệ thống</span>}
                    {!row.allowed && <span className="badge err">bị chặn</span>}
                    {row.allowed && !row.cross_domain && !row.exfiltration && (
                      <span className="badge ok" style={{ fontSize: 11 }}>hợp lệ</span>
                    )}
                  </div>
                </td>
              </tr>
            ))}
            {log.data?.results.length === 0 && (
              <tr>
                <td colSpan={7} className="empty" style={{ textAlign: 'center', padding: '36px 16px' }}>
                  Không có bản ghi nhật ký nào khớp bộ lọc.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {log.data && log.data.count > (log.data.results?.length ?? 0) && (
        <p className="hint" style={{ margin: 0 }}>
          Đang hiển thị {log.data.results.length} trên tổng {log.data.count.toLocaleString('vi-VN')} bản ghi. Hãy sử dụng bộ lọc để thu hẹp khoảng thời gian.
        </p>
      )}
    </div>
  )
}

const DEFAULT_MSB_EMAIL_TEMPLATE = `<!DOCTYPE html><html lang="vi" xmlns:v="urn:schemas-microsoft-com:vml" xmlns:o="urn:schemas-microsoft-com:office:office"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><meta name="color-scheme" content="light dark"><meta name="supported-color-schemes" content="light dark"><title>Mã xác thực đăng nhập - {{app_name}}</title><!--[if mso]><noscript><xml><o:OfficeDocumentSettings><o:PixelsPerInch>96</o:PixelsPerInch></o:OfficeDocumentSettings></xml></noscript><![endif]--></head>
<body bgcolor="#F1F5F9" style="margin:0;padding:0;background-color:#F1F5F9;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;color:#1E293B;line-height:1.6;-webkit-text-size-adjust:100%;-ms-text-size-adjust:100%;">
<table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" bgcolor="#F1F5F9" style="background-color:#F1F5F9;padding:40px 16px;"><tr><td align="center">
<!--[if (gte mso 9)|(IE)]><table width="580" align="center" cellpadding="0" cellspacing="0" border="0" bgcolor="#FFFFFF"><tr><td><![endif]-->
<table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" bgcolor="#FFFFFF" style="max-width:580px;margin:0 auto;background-color:#FFFFFF;border-radius:16px;overflow:hidden;box-shadow:0 4px 20px rgba(0,0,0,0.06);border:1px solid #E2E8F0;">
<tr><td bgcolor="#EA580C" style="background-color:#EA580C;background-image:linear-gradient(135deg, #F59E0B 0%, #FF8A33 50%, #E65C00 100%);background-repeat:no-repeat;padding:28px 36px;text-align:left;">
<table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0"><tr>
<td valign="middle" style="width:52px;padding-right:14px;">
<img src="{{app_icon_url}}" width="48" height="48" alt="{{app_name}}" border="0" style="display:block;border-radius:12px;border:1.5px solid #FED7AA;background-color:#FFFFFF;object-fit:contain;box-shadow:0 2px 8px rgba(0,0,0,0.15);" />
</td>
<td valign="middle">
<div style="display:inline-block;background-color:#C2410C;background:rgba(255,255,255,0.22);padding:3px 10px;border-radius:20px;border:1px solid rgba(255,255,255,0.35);font-size:11px;font-weight:700;color:#FFFFFF;letter-spacing:0.5px;margin-bottom:4px;mso-line-height-rule:exactly;">XÁC THỰC BẢO MẬT HỆ THỐNG</div>
<h1 style="margin:0;color:#FFFFFF;font-size:22px;font-weight:800;letter-spacing:-0.5px;line-height:1.2;">{{app_name}}</h1>
<p style="margin:2px 0 0;color:#FFF7ED;font-size:12.5px;">Hệ Thống Tìm Kiếm Nhân Tài &amp; Tăng Trưởng Khách Hàng</p></td>
</tr></table></td></tr>
<tr><td bgcolor="#FFFFFF" style="padding:32px 36px 28px;background-color:#FFFFFF;"><h2 style="margin:0 0 12px;font-size:19px;font-weight:700;color:#0F172A;">Mã xác thực đăng nhập (OTP)</h2>
<p style="margin:0 0 24px;font-size:14.5px;color:#475569;line-height:1.6;">Bạn vừa thực hiện yêu cầu đăng nhập an toàn vào hệ thống <strong>{{app_name}}</strong>. Vui lòng sử dụng mã xác thực gồm 6 chữ số dưới đây để tiếp tục:</p>
<table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="margin:0 0 24px;"><tr><td bgcolor="#FFF7ED" style="background-color:#FFF7ED;border:1.5px dashed #FB923C;border-radius:12px;padding:24px 20px;text-align:center;">
<div style="font-size:12px;font-weight:700;color:#9A3412;text-transform:uppercase;letter-spacing:1px;margin-bottom:6px;">MÃ XÁC THỰC CỦA BẠN</div>
<div style="font-family:'SF Mono',Consolas,'Liberation Mono',Menlo,Courier,monospace;font-size:38px;font-weight:800;color:#EA580C;letter-spacing:10px;line-height:48px;mso-line-height-rule:exactly;padding:4px 0;">{{code}}</div>
<div style="font-size:13px;color:#C2410C;font-weight:600;margin-top:8px;">⏱️ Có hiệu lực trong vòng {{expires_minutes}} phút</div></td></tr></table>
<table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" bgcolor="#F8FAFC" style="background-color:#F8FAFC;border:1px solid #E2E8F0;border-radius:10px;margin-bottom:20px;"><tr><td bgcolor="#F8FAFC" style="padding:16px 18px;background-color:#F8FAFC;">
<div style="font-size:13px;font-weight:700;color:#334155;margin-bottom:6px;">🛡️ Lưu ý an ninh quan trọng:</div>
<ul style="margin:0;padding-left:18px;font-size:13px;color:#64748B;line-height:1.5;">
<li style="margin-bottom:4px;">Mã OTP này chỉ có hiệu lực <strong>một lần duy nhất</strong>.</li>
<li style="margin-bottom:4px;"><strong>Tuyệt đối không chia sẻ</strong> mã này với bất kỳ ai, bao gồm cả quản trị viên hay nhân viên hỗ trợ.</li>
<li>Nếu bạn không thực hiện yêu cầu này, vui lòng bỏ qua email hoặc liên hệ ngay với Quản trị viên An ninh.</li></ul></td></tr></table>
</td></tr><tr><td bgcolor="#F8FAFC" style="background-color:#F8FAFC;border-top:1px solid #E2E8F0;padding:20px 36px;text-align:center;">
<p style="margin:0 0 4px;font-size:12.5px;font-weight:600;color:#64748B;">Email bảo mật tự động từ {{app_name}}</p>
<p style="margin:0;font-size:11.5px;color:#94A3B8;">Ngân hàng TMCP Hàng Hải Việt Nam (MSB) • Đây là email tự động, vui lòng không phản hồi thư này.</p>
</td></tr></table>
<!--[if (gte mso 9)|(IE)]></td></tr></table><![endif]-->
</td></tr></table></body></html>`

function EmailOtpSettingsPanel() {
  const { appName: themeAppName } = useCustomTheme()
  const queryClient = useQueryClient()
  const settings = useQuery({ queryKey: ['email-otp-settings'], queryFn: api.emailOtpSettings, retry: false })
  const inbox = useQuery({ queryKey: ['resend-inbox'], queryFn: api.resendInbox, retry: false })
  const events = useQuery({ queryKey: ['resend-events'], queryFn: api.resendEvents, retry: false })
  const logoFileRef = useRef<HTMLInputElement>(null)
  const [logoUploadError, setLogoUploadError] = useState('')

  const [activeSubTab, setActiveSubTab] = useState<'config' | 'template' | 'inbox'>('config')
  const [apiKey, setApiKey] = useState('')
  const [showApiKey, setShowApiKey] = useState(false)
  const [webhookSecret, setWebhookSecret] = useState('')
  const [showWebhookSecret, setShowWebhookSecret] = useState(false)
  const [copiedWebhook, setCopiedWebhook] = useState(false)
  const [previewDevice, setPreviewDevice] = useState<'desktop' | 'mobile'>('desktop')
  const [savedSuccess, setSavedSuccess] = useState(false)
  const [testEmail, setTestEmail] = useState('')
  const [testResult, setTestResult] = useState<EmailOtpTestSendResult | null>(null)

  const testSend = useMutation({
    mutationFn: (recipient?: string) =>
      api.emailOtpTestSend(
        recipient || testEmail || undefined,
        activeSubTab === 'template' ? currentTemplate : undefined
      ),
    onSuccess: (data) => {
      setTestResult(data)
      queryClient.invalidateQueries({ queryKey: ['resend-events'] })
    },
  })
  const [form, setForm] = useState<Record<string, string | boolean>>({})

  const data = settings.data
  const value = (key: string) => String(form[key] ?? (data as Record<string, unknown> | undefined)?.[key] ?? '')
  const checked = (key: string) => Boolean(form[key] ?? (data as Record<string, unknown> | undefined)?.[key] ?? false)

  const currentDomainsValue = value('domains') || value('allowed_domains') || [value('tntalent_domains'), value('msb_domains')].filter(Boolean).join(', ')

  const handleLogoUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    setLogoUploadError('')
    if (file.size > 2 * 1024 * 1024) { setLogoUploadError('Tệp vượt quá 2MB.'); return }
    const reader = new FileReader()
    reader.onload = (ev) => setForm({ ...form, app_logo_url: ev.target?.result as string })
    reader.readAsDataURL(file)
  }

  const save = useMutation({
    mutationFn: () => api.emailOtpSettingsSave({
      enabled: checked('enabled'),
      from_email: value('from_email'),
      from_name: value('from_name'),
      reply_to: value('reply_to'),
      subject: value('subject'),
      code_ttl_seconds: 600,
      resend_cooldown_seconds: Number(value('resend_cooldown_seconds') || 60),
      max_attempts: Number(value('max_attempts') || 5),
      ...(apiKey ? { api_key: apiKey } : {}),
      ...(webhookSecret ? { webhook_secret: webhookSecret } : {}),
      webhook_inbound_enabled: checked('webhook_inbound_enabled'),
      otp_html_template: value('otp_html_template'),
      app_logo_url: value('app_logo_url'),
      app_icon: value('app_icon'),
      app_tagline: value('app_tagline'),
      domains: currentDomainsValue,
    }),
    onSuccess: () => {
      setApiKey('')
      setWebhookSecret('')
      setForm({})
      setSavedSuccess(true)
      setTimeout(() => setSavedSuccess(false), 4000)
      queryClient.invalidateQueries({ queryKey: ['email-otp-settings'] })
      queryClient.invalidateQueries({ queryKey: ['resend-inbox'] })
      queryClient.invalidateQueries({ queryKey: ['resend-events'] })
    },
  })

  const copyWebhookUrl = () => {
    if (data?.webhook_url) {
      navigator.clipboard.writeText(data.webhook_url)
      setCopiedWebhook(true)
      setTimeout(() => setCopiedWebhook(false), 2000)
    }
  }

  const insertVariable = (variable: string) => {
    const currentTpl = value('otp_html_template') || DEFAULT_MSB_EMAIL_TEMPLATE
    setForm({ ...form, otp_html_template: currentTpl + variable })
  }

  const resetToDefaultTemplate = () => {
    if (window.confirm('Khôi phục mẫu HTML email về giao diện chuẩn MSB Radar? Thay đổi chưa lưu trên mẫu hiện tại sẽ bị ghi đè.')) {
      setForm({ ...form, otp_html_template: DEFAULT_MSB_EMAIL_TEMPLATE })
    }
  }

  if (settings.isLoading) {
    return (
      <div className="otp-admin-container">
        <div className="otp-card" style={{ textAlign: 'center', padding: '40px 20px' }}>
          <div className="loading-spinner" style={{ margin: '0 auto 16px' }} />
          <p style={{ color: 'var(--muted)', margin: 0 }}>Đang tải thông số cấu hình Email OTP &amp; Resend…</p>
        </div>
      </div>
    )
  }

  const isReady = data?.is_ready
  const currentTemplate = value('otp_html_template') || DEFAULT_MSB_EMAIL_TEMPLATE
  // Ưu tiên: 1) form chưa lưu, 2) DB config.app_logo_url, 3) apple-touch-icon của domain hiện tại
  const iconSource = value('app_logo_url') || data?.app_logo_url || (typeof window !== 'undefined' && window.location.origin ? `${window.location.origin}/apple-touch-icon.png` : 'https://dev-radar.tunghr.io.vn/apple-touch-icon.png')
  const iconEmoji = value('app_icon') || data?.app_icon || '⚡'
  const renderedPreviewDoc = currentTemplate
    .replaceAll('{{code}}', '839204')
    .replaceAll('{{expires_minutes}}', '10')
    .replaceAll('{{app_name}}', value('from_name') || themeAppName || 'MSB Radar')
    .replaceAll('{{app_icon_url}}', iconSource)
    .replaceAll('{{app_icon}}', iconEmoji)

  return (
    <div className="otp-admin-container">
      {/* Hero Command Status Banner */}
      <div className="otp-hero-banner">
        <div className="otp-hero-header">
          <div className="otp-hero-title">
            <h2>
              <span>📧</span> Trung Tâm Cấu Hình Email OTP &amp; Resend
            </h2>
            <p>
              Xác thực an toàn hai lớp (2FA/OTP) cho nhân sự qua hạ tầng Resend API. Toàn bộ khóa bảo mật được mã hóa AES-256 trong Hub.
            </p>
          </div>
          <div className="otp-status-pills">
            <div className={`otp-badge-pill ${isReady ? 'ready' : 'warning'}`}>
              <span className="otp-pulse-dot" />
              <span>{isReady ? 'Dịch vụ Sẵn sàng' : 'Chưa kích hoạt / Cần hoàn thiện'}</span>
            </div>
            <div className={`otp-badge-pill ${data?.api_key_configured ? 'ready' : 'disabled'}`}>
              <span>🔑 API Key: {data?.api_key_configured ? 'Đã thiết lập' : 'Chưa có'}</span>
            </div>
            {checked('enabled') && (
              <div className="otp-badge-pill ready">
                <span>🛡️ Cổng OTP Bật</span>
              </div>
            )}
          </div>
        </div>

        <div className="otp-hero-metrics">
          <div className="otp-metric-item">
            <div className="otp-metric-label">Người gửi (From)</div>
            <div className="otp-metric-val">{value('from_email') || 'Chưa cấu hình'}</div>
          </div>
          <div className="otp-metric-item">
            <div className="otp-metric-label">Hiệu lực mã (TTL)</div>
            <div className="otp-metric-val">10 phút (Chuẩn an toàn)</div>
          </div>
          <div className="otp-metric-item">
            <div className="otp-metric-label">Thời gian chờ gửi lại</div>
            <div className="otp-metric-val">{value('resend_cooldown_seconds') || '60'} giây</div>
          </div>
          <div className="otp-metric-item">
            <div className="otp-metric-label">Hộp thư Inbound Hub</div>
            <div className="otp-metric-val">{checked('webhook_inbound_enabled') ? '🟢 Đang lưu' : '⚪ Đang tắt'}</div>
          </div>
        </div>
      </div>

      {/* Sub-tabs Navigation */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 12 }}>
        <div className="otp-nav-tabs">
          <button
            type="button"
            className={`otp-nav-tab-btn ${activeSubTab === 'config' ? 'active' : ''}`}
            onClick={() => setActiveSubTab('config')}
          >
            <span>⚙️</span> Cấu hình Dịch vụ &amp; Kết nối
          </button>
          <button
            type="button"
            className={`otp-nav-tab-btn ${activeSubTab === 'template' ? 'active' : ''}`}
            onClick={() => setActiveSubTab('template')}
          >
            <span>✉️</span> Thiết kế Mẫu thư HTML &amp; Preview
          </button>
          <button
            type="button"
            className={`otp-nav-tab-btn ${activeSubTab === 'inbox' ? 'active' : ''}`}
            onClick={() => setActiveSubTab('inbox')}
          >
            <span>📥</span> Hộp thư Inbound &amp; Webhooks ({inbox.data?.results?.length ?? 0})
          </button>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          {savedSuccess && (
            <span style={{ color: '#059669', fontSize: 13, fontWeight: 700, display: 'inline-flex', alignItems: 'center', gap: 4 }}>
              ✓ Đã lưu cấu hình thành công!
            </span>
          )}
          {save.error && (
            <span style={{ color: '#dc2626', fontSize: 13, fontWeight: 600 }}>
              {save.error instanceof ApiError ? save.error.message : 'Không thể lưu cấu hình.'}
            </span>
          )}
          <button
            type="button"
            className="btn btn-primary"
            onClick={() => save.mutate()}
            disabled={save.isPending}
            style={{ padding: '8px 20px' }}
          >
            {save.isPending ? 'Đang lưu…' : '💾 Lưu tất cả thay đổi'}
          </button>
        </div>
      </div>

      {/* SUBTAB 1: Cấu hình Dịch vụ & Kết nối */}
      {activeSubTab === 'config' && (
        <div className="otp-grid-2col">
          {/* Card: Thiết lập Kết nối Resend */}
          <div className="otp-card">
            <div className="otp-card-header">
              <h3 className="otp-card-title">
                <span>⚡</span> Kết Nối Hạ Tầng Resend API
              </h3>
              <a
                href="https://resend.com/api-keys"
                target="_blank"
                rel="noreferrer"
                style={{ fontSize: 12, color: 'var(--accent)', textDecoration: 'none', fontWeight: 600 }}
              >
                Quản lý API Key Resend ↗
              </a>
            </div>

            <div style={{ marginBottom: 20 }}>
              <label style={{ display: 'flex', alignItems: 'center', gap: 10, cursor: 'pointer', fontWeight: 700 }}>
                <input
                  type="checkbox"
                  style={{ width: 18, height: 18, accentColor: 'var(--accent)' }}
                  checked={checked('enabled')}
                  onChange={(e) => setForm({ ...form, enabled: e.target.checked })}
                />
                <span>Kích hoạt cổng Đăng nhập qua Email OTP</span>
              </label>
              <p className="hint" style={{ margin: '4px 0 0 28px', fontSize: 12.5 }}>
                Khi bật, người dùng thuộc các domain được chỉ định có thể nhận mã xác thực OTP qua email để đăng nhập.
              </p>
            </div>

            <div className="otp-field">
              <label>
                <span>Resend API Key</span>
                {data?.api_key_configured && (
                  <span className="field-hint" style={{ color: '#059669', fontWeight: 700 }}>
                    🔒 Đã lưu khóa an toàn
                  </span>
                )}
              </label>
              <div className="otp-input-wrap">
                <input
                  type={showApiKey ? 'text' : 'password'}
                  className="input-text"
                  placeholder={data?.api_key_configured ? '•••••••••••••••••••••••• (Nhập để thay mới)' : 're_123456789...'}
                  value={apiKey}
                  onChange={(e) => setApiKey(e.target.value)}
                  autoComplete="new-password"
                />
                <button
                  type="button"
                  className="otp-input-action-btn"
                  onClick={() => setShowApiKey(!showApiKey)}
                  title={showApiKey ? 'Ẩn' : 'Hiện'}
                >
                  {showApiKey ? 'Ẩn' : 'Hiện'}
                </button>
              </div>
              <span className="field-hint">
                Khóa bắt đầu bằng <code>re_</code>, được mã hóa sha256/fernet và không bao giờ lộ ra frontend.
              </span>
            </div>

            <div className="otp-field">
              <label>
                <span>Email người gửi (From Email)</span>
                <span className="field-hint">Bắt buộc</span>
              </label>
              <input
                className="input-text"
                value={value('from_email')}
                onChange={(e) => setForm({ ...form, from_email: e.target.value })}
                placeholder="radar-auth@domain-da-xac-thuc.vn"
              />
              <span className="field-hint">Domain phải được Verify DNS (SPF/DKIM) trong Resend Dashboard.</span>
            </div>

            <div className="otp-field">
              <label>Tên người gửi (From Name)</label>
              <input
                className="input-text"
                value={value('from_name')}
                onChange={(e) => setForm({ ...form, from_name: e.target.value })}
                placeholder={themeAppName || "MSB Radar"}
              />
            </div>

            {/* Branding icon cho email */}
            <div className="otp-field">
              <label style={{ fontWeight: 700 }}>🖼️ Logo / Icon trong Email OTP</label>
              <input ref={logoFileRef} type="file" accept="image/*,.ico" style={{ display: 'none' }} onChange={handleLogoUpload} />
              {value('app_logo_url') || data?.app_logo_url ? (
                <div style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '10px', background: 'var(--panel)', borderRadius: 10, border: '1.5px solid var(--border)' }}>
                  <img
                    src={value('app_logo_url') || data?.app_logo_url}
                    alt="Email logo"
                    style={{ width: 48, height: 48, borderRadius: 10, objectFit: 'contain', background: '#fff', border: '1px solid var(--border)' }}
                  />
                  <div style={{ flex: 1 }}>
                    <div style={{ fontWeight: 700, fontSize: 13 }}>✓ Đã có logo email</div>
                    <div style={{ fontSize: 12, color: 'var(--muted)' }}>Đây là icon sẽ hiển thị trong phần header email OTP.</div>
                  </div>
                  <div style={{ display: 'flex', gap: 8 }}>
                    <button type="button" className="btn btn-secondary btn-sm" onClick={() => logoFileRef.current?.click()}>📁 Đổi</button>
                    <button type="button" className="btn btn-secondary btn-sm" onClick={() => setForm({ ...form, app_logo_url: '' })}>🗑️ Gỡ</button>
                  </div>
                </div>
              ) : (
                <div
                  style={{ border: '2px dashed var(--border)', borderRadius: 10, padding: '18px 20px', textAlign: 'center', cursor: 'pointer', background: 'var(--panel)' }}
                  onClick={() => logoFileRef.current?.click()}
                >
                  <div style={{ fontSize: 28, marginBottom: 6 }}>📁</div>
                  <div style={{ fontWeight: 600, fontSize: 13 }}>Bấm để tải logo email lên</div>
                  <div style={{ fontSize: 12, color: 'var(--muted)' }}>PNG, JPG, SVG, ICO — tối đa 2MB. Nếu không có, sẽ dùng favicon của website.</div>
                </div>
              )}
              {logoUploadError && <p className="error-text" style={{ marginTop: 6 }}>{logoUploadError}</p>}
              <span className="field-hint">Nếu để trống, hệ thống sẽ dùng favicon từ domain đang chạy (<code>/apple-touch-icon.png</code>).</span>
            </div>

            <div className="otp-field">
              <label>Emoji biểu tượng (dự phòng khi không có logo)</label>
              <input
                className="input-text"
                style={{ width: 80 }}
                value={value('app_icon') || data?.app_icon || '⚡'}
                onChange={(e) => setForm({ ...form, app_icon: e.target.value })}
                maxLength={4}
                placeholder="⚡"
              />
            </div>

            <div className="otp-field">
              <label>Email phản hồi (Reply-To)</label>
              <input
                className="input-text"
                value={value('reply_to')}
                onChange={(e) => setForm({ ...form, reply_to: e.target.value })}
                placeholder="support@msb.com.vn, it-sec@tntalent.vn"
              />
              <span className="field-hint">Có thể nhập nhiều email cách nhau bằng dấu phẩy <code>,</code> hoặc chấm phẩy <code>;</code>.</span>
            </div>

            <div className="otp-field" style={{ marginBottom: 0 }}>
              <label>Tiêu đề thư (Subject)</label>
              <input
                className="input-text"
                value={value('subject')}
                onChange={(e) => setForm({ ...form, subject: e.target.value })}
                placeholder="Mã xác thực đăng nhập MSB Radar"
              />
            </div>
          </div>

          {/* Card: Quy định Domain & An ninh */}
          <div className="otp-card">
            <div className="otp-card-header">
              <h3 className="otp-card-title">
                <span>🛡️</span> Danh Sách Domain &amp; Chính Sách An Toàn
              </h3>
            </div>

            <div className="otp-field">
              <label>
                <span>Danh sách Domain Email OTP được phép đăng nhập</span>
                <span className="field-hint">Phân tách bằng dấu <code>,</code> hoặc <code>;</code></span>
              </label>
              <textarea
                className="input-text"
                rows={3}
                value={currentDomainsValue}
                onChange={(e) => {
                  const val = e.target.value
                  setForm({ ...form, domains: val, allowed_domains: val, tntalent_domains: val, msb_domains: val })
                }}
                placeholder="msb.com.vn, tntalent.vn, talent.msb.com.vn"
                style={{ resize: 'vertical' }}
              />
              <span className="field-hint">
                Người dùng có địa chỉ email kết thúc bằng bất kỳ tên miền nào trong danh sách trên sẽ được phép nhận mã OTP đăng nhập hệ thống.
              </span>
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
              <div className="otp-field">
                <label>Thời gian chờ gửi lại (Cooldown)</label>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <input
                    type="number"
                    min="30"
                    max="600"
                    className="input-text"
                    value={value('resend_cooldown_seconds')}
                    onChange={(e) => setForm({ ...form, resend_cooldown_seconds: e.target.value })}
                  />
                  <span style={{ fontSize: 13, color: 'var(--muted)', fontWeight: 600 }}>giây</span>
                </div>
                <span className="field-hint">Tránh spam gửi OTP liên tục.</span>
              </div>

              <div className="otp-field">
                <label>Số lần nhập sai tối đa</label>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <input
                    type="number"
                    min="3"
                    max="10"
                    className="input-text"
                    value={value('max_attempts')}
                    onChange={(e) => setForm({ ...form, max_attempts: e.target.value })}
                  />
                  <span style={{ fontSize: 13, color: 'var(--muted)', fontWeight: 600 }}>lần</span>
                </div>
                <span className="field-hint">Khóa mã sau số lần thử này.</span>
              </div>
            </div>

            <div className="otp-field" style={{ marginBottom: 0 }}>
              <label>Thời hạn hiệu lực mã xác thực (TTL)</label>
              <input className="input-text" value="10 phút (Cố định chuẩn an ninh ngân hàng)" disabled />
              <span className="field-hint">Mã OTP sẽ tự hủy sau 10 phút hoặc sau 1 lần xác thực thành công.</span>
            </div>
          </div>

          {/* Card: Kiểm Tra Luồng Gửi Email OTP Thử Nghiệm */}
          <div className="otp-card" style={{ gridColumn: '1 / -1', border: '1px solid rgba(255, 138, 51, 0.35)', background: 'linear-gradient(180deg, rgba(255, 138, 51, 0.03) 0%, rgba(15, 23, 42, 0.5) 100%)' }}>
            <div className="otp-card-header">
              <h3 className="otp-card-title">
                <span>🧪</span> Kiểm Tra &amp; Gửi Thử Nghiệm OTP (Test Email Pipeline)
              </h3>
              <span className="field-hint" style={{ color: 'var(--accent)', fontWeight: 600 }}>
                Kiểm tra trực tiếp kết nối Resend &amp; khả năng nhận thư thực tế
              </span>
            </div>

            <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
              <p style={{ margin: 0, fontSize: 13, color: 'var(--text-secondary)' }}>
                Nhập địa chỉ email bất kỳ để hệ thống phát mã xác thực thử nghiệm 6 chữ số và gửi qua cổng Resend. Bạn có thể kiểm tra xem thư có vào Inbox hay bị rơi vào Spam/Junk mail không.
              </p>

              <div style={{ display: 'flex', gap: 10, alignItems: 'flex-start', flexWrap: 'wrap' }}>
                <div style={{ flex: '1 1 320px', minWidth: 260 }}>
                  <input
                    type="email"
                    className="input-text"
                    placeholder="Nhập email nhận mã test (ví dụ: your-email@msb.com.vn)..."
                    value={testEmail}
                    onChange={(e) => setTestEmail(e.target.value)}
                  />
                  <span className="field-hint">
                    Mặc định sẽ gửi tới email tài khoản hiện tại của bạn nếu để trống.
                  </span>
                </div>
                <button
                  type="button"
                  className="btn btn-primary"
                  onClick={() => testSend.mutate(testEmail)}
                  disabled={testSend.isPending || !data?.api_key_configured || !value('from_email')}
                  style={{ padding: '9px 22px', display: 'inline-flex', alignItems: 'center', gap: 8 }}
                >
                  {testSend.isPending ? (
                    <>
                      <span className="loading-spinner" style={{ width: 14, height: 14, margin: 0 }} />
                      <span>Đang gửi qua Resend…</span>
                    </>
                  ) : (
                    <>
                      <span>🚀</span>
                      <span>Gửi Test OTP Ngay</span>
                    </>
                  )}
                </button>
              </div>

              {/* Success Result Box */}
              {testResult && (
                <div
                  style={{
                    background: 'rgba(16, 185, 129, 0.1)',
                    border: '1px solid rgba(16, 185, 129, 0.35)',
                    borderRadius: 10,
                    padding: '14px 16px',
                    display: 'flex',
                    flexDirection: 'column',
                    gap: 6,
                    fontSize: 13,
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, color: '#34D399', fontWeight: 700 }}>
                    <span style={{ fontSize: 16 }}>✓</span>
                    <span>{testResult.message}</span>
                  </div>
                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: 8, marginTop: 4, color: 'var(--text-secondary)', fontSize: 12 }}>
                    <div>• <strong>Mã test:</strong> <code style={{ color: 'var(--accent)', fontWeight: 700 }}>{testResult.test_code}</code></div>
                    <div>• <strong>Thời gian phản hồi:</strong> {testResult.duration_ms}ms</div>
                    <div>• <strong>Resend ID:</strong> <code>{testResult.resend_id || 'N/A'}</code></div>
                    <div>• <strong>Người gửi:</strong> {testResult.sender}</div>
                  </div>
                  <span style={{ fontSize: 12, color: 'var(--muted)', marginTop: 2 }}>
                    💡 Hãy kiểm tra hộp thư đến (Inbox) hoặc thư rác (Spam) của <strong>{testResult.recipient}</strong> để xác nhận giao diện thư.
                  </span>
                </div>
              )}

              {/* Error Box */}
              {testSend.error && (
                <div
                  style={{
                    background: 'rgba(239, 68, 68, 0.1)',
                    border: '1px solid rgba(239, 68, 68, 0.35)',
                    borderRadius: 10,
                    padding: '12px 16px',
                    color: '#F87171',
                    fontSize: 13,
                    display: 'flex',
                    alignItems: 'flex-start',
                    gap: 8,
                  }}
                >
                  <span style={{ fontSize: 16 }}>⚠️</span>
                  <div>
                    <div style={{ fontWeight: 700 }}>Gửi thử nghiệm thất bại:</div>
                    <div>{testSend.error instanceof ApiError ? testSend.error.message : 'Lỗi kết nối Resend API.'}</div>
                    <div style={{ fontSize: 12, color: 'var(--muted)', marginTop: 4 }}>
                      Gợi ý: Kiểm tra lại Resend API Key, quyền hạn khóa, và đảm bảo Domain trong From Email đã được Verify DNS trong Resend.
                    </div>
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* SUBTAB 2: Thiết kế Mẫu thư HTML & Xem trước */}
      {activeSubTab === 'template' && (
        <div style={{ display: 'grid', gridTemplateColumns: '1.1fr 0.9fr', gap: 20 }}>
          {/* Editor Column */}
          <div className="otp-card" style={{ display: 'flex', flexDirection: 'column' }}>
            <div className="otp-card-header">
              <h3 className="otp-card-title">
                <span>📝</span> Trình Soạn Thảo Mẫu Thư HTML
              </h3>
              <button
                type="button"
                className="btn btn-secondary"
                onClick={resetToDefaultTemplate}
                style={{ fontSize: 12, padding: '5px 12px' }}
              >
                ✨ Khôi phục Mẫu MSB Chuẩn
              </button>
            </div>

            <div style={{ marginBottom: 12 }}>
              <div style={{ fontSize: 12.5, fontWeight: 700, color: 'var(--text-secondary)', marginBottom: 6 }}>
                Chèn biến động hệ thống (Click để chèn vào cuối):
              </div>
              <div className="otp-var-chips">
                <button type="button" className="otp-var-chip" onClick={() => insertVariable('{{code}}')}>
                  + {'{{code}}'} (Mã 6 số)
                </button>
                <button type="button" className="otp-var-chip" onClick={() => insertVariable('{{expires_minutes}}')}>
                  + {'{{expires_minutes}}'} (Số phút)
                </button>
                <button type="button" className="otp-var-chip" onClick={() => insertVariable('{{app_name}}')}>
                  + {'{{app_name}}'} (Tên hệ thống)
                </button>
                <button type="button" className="otp-var-chip" onClick={() => insertVariable('{{app_icon_url}}')}>
                  + {'{{app_icon_url}}'} (URL Ảnh Icon)
                </button>
                <button type="button" className="otp-var-chip" onClick={() => insertVariable('{{app_icon}}')}>
                  + {'{{app_icon}}'} (Icon ký tự)
                </button>
              </div>
            </div>

            <textarea
              className="input-text"
              rows={18}
              value={currentTemplate}
              onChange={(e) => setForm({ ...form, otp_html_template: e.target.value })}
              style={{
                fontFamily: "'SF Mono', Consolas, 'Liberation Mono', Menlo, monospace",
                fontSize: 12.5,
                lineHeight: 1.5,
                flex: 1,
                resize: 'vertical',
                minHeight: 380,
              }}
              placeholder="Nhập mã nguồn HTML email..."
            />
            <p className="hint" style={{ margin: '8px 0 0', fontSize: 12 }}>
              Mẫu thư sử dụng inline CSS và table layout để tương thích tốt nhất với Gmail, Microsoft Outlook, Apple Mail và thiết bị di động.
            </p>
          </div>

          {/* Live Preview Column */}
          <div className="otp-preview-container">
            <div className="otp-preview-topbar">
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 13, fontWeight: 700 }}>
                <span>👁️</span> Xem Trước Thực Tế (Live Preview)
              </div>
              <div className="otp-preview-modes">
                <button
                  type="button"
                  className={`otp-preview-mode-btn ${previewDevice === 'desktop' ? 'active' : ''}`}
                  onClick={() => setPreviewDevice('desktop')}
                >
                  💻 Desktop
                </button>
                <button
                  type="button"
                  className={`otp-preview-mode-btn ${previewDevice === 'mobile' ? 'active' : ''}`}
                  onClick={() => setPreviewDevice('mobile')}
                >
                  📱 Mobile (375px)
                </button>
              </div>
            </div>

            <div className="otp-preview-viewport">
              <div
                className="otp-device-frame"
                style={{
                  width: previewDevice === 'mobile' ? '375px' : '100%',
                  maxWidth: previewDevice === 'mobile' ? '375px' : '620px',
                }}
              >
                <iframe
                  title="Live OTP Email Preview"
                  sandbox=""
                  srcDoc={renderedPreviewDoc}
                  style={{
                    width: '100%',
                    height: '520px',
                    border: 'none',
                    display: 'block',
                    background: '#F1F5F9',
                  }}
                />
              </div>
            </div>
          </div>
        </div>
      )}

      {/* SUBTAB 3: Hộp thư Inbound & Webhooks */}
      {activeSubTab === 'inbox' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
          {/* Card Cấu hình Webhook */}
          <div className="otp-card">
            <div className="otp-card-header">
              <h3 className="otp-card-title">
                <span>🔗</span> Cấu Hình Resend Webhook &amp; Tiếp Nhận Inbound
              </h3>
            </div>

            <p className="hint" style={{ margin: '0 0 16px' }}>
              Sao chép URL bên dưới và dán vào <strong>Resend Dashboard ➔ Webhooks</strong>. Chọn các sự kiện:{' '}
              <code>email.received</code>, <code>email.sent</code>, <code>email.delivered</code>, <code>email.bounced</code>,{' '}
              <code>email.failed</code>.
            </p>

            <div className="otp-field">
              <label>Webhook Endpoint URL</label>
              <div className="otp-input-wrap">
                <input
                  className="input-text"
                  readOnly
                  value={data?.webhook_url ?? ''}
                  onFocus={(e) => e.currentTarget.select()}
                  style={{ fontFamily: 'monospace', fontWeight: 600 }}
                />
                <button
                  type="button"
                  className="otp-input-action-btn"
                  onClick={copyWebhookUrl}
                  style={{ fontWeight: 700 }}
                >
                  {copiedWebhook ? '✓ Đã sao chép' : '📋 Sao chép URL'}
                </button>
              </div>
            </div>

            <div style={{ margin: '14px 0' }}>
              <label style={{ display: 'flex', alignItems: 'center', gap: 10, cursor: 'pointer', fontWeight: 600 }}>
                <input
                  type="checkbox"
                  style={{ width: 16, height: 16, accentColor: 'var(--accent)' }}
                  checked={checked('webhook_inbound_enabled')}
                  onChange={(e) => setForm({ ...form, webhook_inbound_enabled: e.target.checked })}
                />
                <span>Tự động lưu nội dung email phản hồi (Inbound) vào Hộp thư Hub</span>
              </label>
            </div>

            <div className="otp-field" style={{ marginBottom: 0 }}>
              <label>
                <span>Webhook Signing Secret</span>
                {data?.webhook_secret_configured && (
                  <span className="field-hint" style={{ color: '#059669', fontWeight: 700 }}>
                    🔒 Đã cấu hình Signing Secret
                  </span>
                )}
              </label>
              <div className="otp-input-wrap">
                <input
                  type={showWebhookSecret ? 'text' : 'password'}
                  className="input-text"
                  placeholder={data?.webhook_secret_configured ? 'whsec_•••••••••••••••• (Nhập để thay mới)' : 'whsec_...'}
                  value={webhookSecret}
                  onChange={(e) => setWebhookSecret(e.target.value)}
                  autoComplete="new-password"
                />
                <button
                  type="button"
                  className="otp-input-action-btn"
                  onClick={() => setShowWebhookSecret(!showWebhookSecret)}
                >
                  {showWebhookSecret ? 'Ẩn' : 'Hiện'}
                </button>
              </div>
              <span className="field-hint">Dùng để xác thực chữ ký Svix tiêu chuẩn từ máy chủ Resend.</span>
            </div>
          </div>

          {/* Card Hộp thư Inbound */}
          <div className="otp-card">
            <div className="otp-card-header">
              <h3 className="otp-card-title">
                <span>📥</span> Hộp Thư Inbound Tiếp Nhận ({inbox.data?.results?.length ?? 0})
              </h3>
            </div>

            {(inbox.data?.results ?? []).length === 0 ? (
              <div style={{ textAlign: 'center', padding: '32px 16px', color: 'var(--muted)' }}>
                <div style={{ fontSize: 32, marginBottom: 8 }}>📭</div>
                <p style={{ margin: '0 0 4px', fontWeight: 600 }}>Chưa có thư phản hồi nào được ghi nhận</p>
                <p style={{ margin: 0, fontSize: 12.5 }}>
                  Hãy đảm bảo đã cấu hình Resend Receiving và webhook đang truyền event <code>email.received</code>.
                </p>
              </div>
            ) : (
              <div className="otp-inbox-list">
                {inbox.data?.results.map((mail) => (
                  <details key={mail.id} className="otp-inbox-card">
                    <summary className="otp-inbox-summary">
                      <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                        <span style={{ fontSize: 16 }}>✉️</span>
                        <div>
                          <strong style={{ fontSize: 14, color: 'var(--text)' }}>
                            {mail.subject || '(Không có tiêu đề)'}
                          </strong>
                          <div style={{ fontSize: 12, color: 'var(--muted)' }}>
                            Từ: <strong>{mail.sender}</strong> ➔ Tới: {mail.recipients.join(', ')}
                          </div>
                        </div>
                      </div>
                      <span className="otp-badge-pill" style={{ fontSize: 11.5 }}>
                        {mail.received_at ? new Date(mail.received_at).toLocaleString('vi-VN') : ''}
                      </span>
                    </summary>
                    <div style={{ marginTop: 12, paddingTop: 12, borderTop: '1px solid var(--border)' }}>
                      <pre
                        style={{
                          whiteSpace: 'pre-wrap',
                          fontFamily: 'inherit',
                          fontSize: 13,
                          background: 'var(--surface)',
                          padding: 12,
                          borderRadius: 8,
                          margin: '0 0 8px',
                        }}
                      >
                        {mail.text_body || '(Thư không có văn bản thuần / Chỉ có HTML)'}
                      </pre>
                      {mail.attachments.length > 0 && (
                        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center' }}>
                          <span style={{ fontSize: 12, color: 'var(--muted)' }}>📎 Đính kèm:</span>
                          {mail.attachments.map((att, idx) => (
                            <span key={idx} className="otp-badge-pill" style={{ fontSize: 11 }}>
                              {att.filename || 'tệp'}
                            </span>
                          ))}
                        </div>
                      )}
                    </div>
                  </details>
                ))}
              </div>
            )}
          </div>

          {/* Card Sự kiện Gửi/Nhận gần đây */}
          <div className="otp-card">
            <div className="otp-card-header">
              <h3 className="otp-card-title">
                <span>📊</span> Nhật Ký Sự Kiện Resend Gần Đây (Activity Stream)
              </h3>
            </div>

            {(events.data?.results ?? []).length === 0 ? (
              <p className="hint" style={{ margin: 0 }}>Chưa có sự kiện gửi/nhận nào được ghi nhận.</p>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 8, maxHeight: 320, overflowY: 'auto' }}>
                {(events.data?.results ?? []).slice(0, 20).map((ev) => {
                  const evType = ev.event_type || 'unknown'
                  const badgeClass = evType.includes('sent')
                    ? 'sent'
                    : evType.includes('delivered')
                    ? 'delivered'
                    : evType.includes('received')
                    ? 'received'
                    : evType.includes('bounced') || evType.includes('failed')
                    ? 'failed'
                    : 'sent'

                  return (
                    <div
                      key={ev.id}
                      style={{
                        display: 'flex',
                        justifyContent: 'space-between',
                        alignItems: 'center',
                        padding: '8px 12px',
                        background: 'var(--surface-raised)',
                        borderRadius: 8,
                        fontSize: 12.5,
                      }}
                    >
                      <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                        <span className={`otp-event-badge ${badgeClass}`}>{evType}</span>
                        <span style={{ fontFamily: 'monospace', color: 'var(--text)' }}>
                          ID: {ev.email_id || (ev.svix_id ? ev.svix_id.slice(0, 16) : `#${ev.id}`)}
                        </span>
                      </div>
                      <span style={{ color: 'var(--muted)', fontSize: 12 }}>
                        {new Date(ev.received_at).toLocaleString('vi-VN')}
                      </span>
                    </div>
                  )
                })}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

function RoleMatrixSummaryPanel() {
  const queryClient = useQueryClient()
  const summary = useQuery({ queryKey: ['access-log-summary'], queryFn: api.accessLogSummary, retry: false })
  const matrix = useQuery({ queryKey: ['role-module-matrix'], queryFn: api.roleModuleMatrix, retry: false })

  const setCell = useMutation({
    mutationFn: (v: { role: string; module: string; enabled: boolean }) =>
      api.roleModuleSet(v.role, v.module, v.enabled),
    onSuccess: (data) => queryClient.setQueryData(['role-module-matrix'], data),
  })

  const data = matrix.data
  const cellMap = new Map(
    (data?.cells ?? []).map((c) => [`${c.role}:${c.module}`, c] as const),
  )

  return (
    <div className="admin-panel-card">
      <div className="brand-preview-title-row" style={{ margin: 0 }}>
        <h3 style={{ fontSize: 16, fontWeight: 700, margin: 0, color: 'var(--text)' }}>
          📋 Ma trận Phân quyền Vai trò theo Phân hệ (RBAC Matrix)
        </h3>
        <span className="hint">
          Tick để cấp module cho vai trò, bỏ tick để thu hồi. Mặc định trong code là sàn an toàn;
          ô có dấu ● là đã chỉnh so với mặc định. Áp dụng ngay cho lần đăng nhập kế tiếp.
        </span>
      </div>

      {matrix.isError && (
        <div className="empty-box" style={{ margin: '8px 0' }}>Không tải được ma trận phân quyền.</div>
      )}

      {data && (
        <div style={{ overflowX: 'auto' }}>
          <table className="admin-matrix-grid">
            <thead>
              <tr>
                <th style={{ width: '24%' }}>Phân hệ / Module</th>
                {data.roles.map((r) => (
                  <th key={r.key} style={{ textAlign: 'center' }}>{r.label}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {data.modules.map((m) => (
                <tr key={m.key}>
                  <td><strong>{m.label}</strong></td>
                  {data.roles.map((r) => {
                    const cell = cellMap.get(`${r.key}:${m.key}`)
                    if (!cell) return <td key={r.key} className="admin-matrix-dash">—</td>
                    return (
                      <td key={r.key} style={{ textAlign: 'center' }}>
                        <label style={{ display: 'inline-flex', alignItems: 'center', gap: 4, cursor: cell.editable ? 'pointer' : 'not-allowed' }}>
                          <input
                            type="checkbox"
                            checked={cell.enabled}
                            disabled={!cell.editable || setCell.isPending}
                            onChange={() => setCell.mutate({ role: r.key, module: m.key, enabled: !cell.enabled })}
                          />
                          {cell.changed && <span title="Đã chỉnh so với mặc định" style={{ color: 'var(--accent)' }}>●</span>}
                        </label>
                      </td>
                    )
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Top Active Users by Security Logs */}
      {summary.data?.by_user && summary.data.by_user.length > 0 && (
        <div style={{ marginTop: 24 }}>
          <h4 style={{ fontSize: 15, fontWeight: 700, margin: '0 0 12px', color: 'var(--text)' }}>
            📊 Top người dùng có tần suất tương tác cao nhất
          </h4>
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%' }}>
              <thead>
                <tr>
                  <th>Tài khoản người dùng</th>
                  <th>Tổng lượt truy cập</th>
                  <th>Lượt truy cập liên nghiệp vụ</th>
                </tr>
              </thead>
              <tbody>
                {summary.data.by_user.map((u) => (
                  <tr key={u.user_name}>
                    <td><strong>@{u.user_name}</strong></td>
                    <td>{u.n.toLocaleString('vi-VN')}</td>
                    <td>
                      {u.cross > 0 ? (
                        <span className="badge warn">{u.cross} lượt</span>
                      ) : (
                        <span className="muted">0</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  )
}


function DatabaseBackupPanel() {
  const queryClient = useQueryClient()
  const backupsQuery = useQuery({
    queryKey: ['db-backups'],
    queryFn: api.backupList,
    refetchInterval: 10000,
  })

  const [triggerSuccessMsg, setTriggerSuccessMsg] = useState('')

  const triggerMutation = useMutation({
    mutationFn: api.backupTrigger,
    onSuccess: (data) => {
      setTriggerSuccessMsg(`✓ Đã tạo bản sao lưu thành công: ${data.filename} (${(data.size_bytes / 1024 / 1024).toFixed(2)} MB, ${data.duration_ms}ms)`)
      setTimeout(() => setTriggerSuccessMsg(''), 6000)
      queryClient.invalidateQueries({ queryKey: ['db-backups'] })
    },
  })

  const deleteMutation = useMutation({
    mutationFn: (id: number) => api.backupDelete(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['db-backups'] })
    },
  })

  const handleDelete = (backup: DatabaseBackupRow) => {
    if (window.confirm(`Bạn có chắc chắn muốn xoá vĩnh viễn bản sao lưu "${backup.filename}" khỏi Cloudflare R2 / máy chủ?`)) {
      deleteMutation.mutate(backup.id)
    }
  }

  const summary = backupsQuery.data?.summary
  const results = backupsQuery.data?.results || []

  const formatBytes = (bytes: number) => {
    if (!bytes) return '0 B'
    if (bytes < 1024) return `${bytes} B`
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
    return `${(bytes / (1024 * 1024)).toFixed(2)} MB`
  }

  const isR2 = summary?.storage_backend === 'r2'

  return (
    <div className="otp-admin-container">
      {/* Hero Command Banner */}
      <div className="otp-hero-banner">
        <div className="otp-hero-header">
          <div className="otp-hero-title">
            <h2>
              <span>💾</span> Trung Tâm Sao Lưu CSDL &amp; Cloudflare R2
            </h2>
            <p>
              Cơ chế sao lưu dự phòng CSDL tự động 2 lần/ngày (02:00 &amp; 14:00) từ VPS lên Cloudflare R2 Storage. Dữ liệu nén gzip mã hóa toàn vẹn.
            </p>
          </div>
          <div className="otp-status-pills">
            <div className={`otp-badge-pill ${isR2 ? 'ready' : 'warning'}`}>
              <span className="otp-pulse-dot" />
              <span>{isR2 ? `☁️ Cloudflare R2 (${summary?.r2_bucket || 'Default'})` : '🖥️ Ổ đĩa Cục bộ VPS'}</span>
            </div>
            <div className="otp-badge-pill ready">
              <span>⏰ Lịch: 2 lần/ngày (02h &amp; 14h)</span>
            </div>
            <div className="otp-badge-pill ready">
              <span>🗄️ Lưu giữ 30 ngày gần nhất</span>
            </div>
          </div>
        </div>

        <div className="otp-hero-metrics">
          <div className="otp-metric-item">
            <div className="otp-metric-label">Tổng số bản sao lưu</div>
            <div className="otp-metric-val">{summary?.total_backups || 0} bản ghi</div>
          </div>
          <div className="otp-metric-item">
            <div className="otp-metric-label">Tổng dung lượng lưu trữ</div>
            <div className="otp-metric-val">{formatBytes(summary?.total_size_bytes || 0)}</div>
          </div>
          <div className="otp-metric-item">
            <div className="otp-metric-label">Lần sao lưu gần nhất</div>
            <div className="otp-metric-val" style={{ fontSize: 14 }}>
              {summary?.latest_backup?.created_at
                ? new Date(summary.latest_backup.created_at).toLocaleString('vi-VN')
                : 'Chưa có'}
            </div>
          </div>
          <div className="otp-metric-item">
            <div className="otp-metric-label">Tốc độ xuất trung bình</div>
            <div className="otp-metric-val">
              {summary?.latest_backup?.duration_ms ? `${summary.latest_backup.duration_ms}ms` : '—'}
            </div>
          </div>
        </div>
      </div>

      {/* Action Controls & Notifications */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 12, marginBottom: 16 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
          <button
            type="button"
            className="btn btn-primary"
            onClick={() => triggerMutation.mutate()}
            disabled={triggerMutation.isPending}
            style={{ padding: '9px 22px', display: 'inline-flex', alignItems: 'center', gap: 8 }}
          >
            {triggerMutation.isPending ? (
              <>
                <span className="loading-spinner" style={{ width: 14, height: 14, margin: 0 }} />
                <span>Đang kết xuất &amp; tải lên R2…</span>
              </>
            ) : (
              <>
                <span>🚀</span>
                <span>Sao Lưu Cơ Sở Dữ Liệu Ngay</span>
              </>
            )}
          </button>
          <button
            type="button"
            className="btn btn-secondary"
            onClick={() => backupsQuery.refetch()}
            disabled={backupsQuery.isFetching}
            style={{ padding: '9px 16px', display: 'inline-flex', alignItems: 'center', gap: 6 }}
          >
            <span>🔄</span>
            <span>Làm mới</span>
          </button>
        </div>

        {triggerSuccessMsg && (
          <div style={{ color: '#059669', fontSize: 13, fontWeight: 700, display: 'inline-flex', alignItems: 'center', gap: 6 }}>
            <span>✓</span>
            <span>{triggerSuccessMsg}</span>
          </div>
        )}
        {triggerMutation.error && (
          <div style={{ color: '#dc2626', fontSize: 13, fontWeight: 600 }}>
            {triggerMutation.error instanceof ApiError ? triggerMutation.error.message : 'Lỗi khi kích hoạt sao lưu.'}
          </div>
        )}
      </div>

      {/* Backup History Table */}
      <div className="admin-panel-card" style={{ padding: 0, overflow: 'hidden' }}>
        <div style={{ padding: '16px 20px', borderBottom: '1px solid var(--border)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <h3 style={{ fontSize: 15, fontWeight: 700, margin: 0, color: 'var(--text)', display: 'flex', alignItems: 'center', gap: 8 }}>
            <span>📁</span> Danh Sách Bản Sao Lưu Cơ Sở Dữ Liệu ({results.length})
          </h3>
          <span style={{ fontSize: 12.5, color: 'var(--muted)' }}>
            Định dạng nén chuẩn: <code>.sql.gz</code> / <code>.json.gz</code>
          </span>
        </div>

        {backupsQuery.isLoading ? (
          <div style={{ padding: '40px 20px', textAlign: 'center', color: 'var(--muted)' }}>
            <div className="loading-spinner" style={{ margin: '0 auto 12px' }} />
            <p>Đang tải danh sách bản sao lưu CSDL…</p>
          </div>
        ) : results.length === 0 ? (
          <div style={{ padding: '40px 20px', textAlign: 'center', color: 'var(--muted)' }}>
            <p style={{ fontSize: 14, margin: '0 0 8px' }}>Chưa có bản sao lưu nào được ghi nhận.</p>
            <p style={{ fontSize: 12.5, margin: 0 }}>Bấm nút "Sao Lưu Cơ Sở Dữ Liệu Ngay" ở trên để tạo bản lưu trữ đầu tiên.</p>
          </div>
        ) : (
          <div style={{ overflowX: 'auto' }}>
            <table className="data-table" style={{ width: '100%', borderCollapse: 'collapse' }}>
              <thead>
                <tr>
                  <th style={{ textAlign: 'left', padding: '12px 16px' }}>Tệp sao lưu</th>
                  <th style={{ textAlign: 'left', padding: '12px 16px' }}>Thời điểm tạo</th>
                  <th style={{ textAlign: 'center', padding: '12px 16px' }}>Dung lượng</th>
                  <th style={{ textAlign: 'center', padding: '12px 16px' }}>Nơi lưu</th>
                  <th style={{ textAlign: 'center', padding: '12px 16px' }}>Loại kích hoạt</th>
                  <th style={{ textAlign: 'center', padding: '12px 16px' }}>Thời gian</th>
                  <th style={{ textAlign: 'center', padding: '12px 16px' }}>Trạng thái</th>
                  <th style={{ textAlign: 'right', padding: '12px 16px' }}>Thao tác</th>
                </tr>
              </thead>
              <tbody>
                {results.map((b) => {
                  const isCompleted = b.status === 'completed'
                  return (
                    <tr key={b.id} style={{ borderBottom: '1px solid var(--border)' }}>
                      <td style={{ padding: '12px 16px' }}>
                        <div style={{ fontWeight: 700, color: 'var(--text)', fontSize: 13, fontFamily: 'monospace' }}>
                          {b.filename}
                        </div>
                        {b.sha256 && (
                          <div style={{ fontSize: 11, color: 'var(--muted)', fontFamily: 'monospace', marginTop: 2 }}>
                            SHA256: {b.sha256.slice(0, 16)}…
                          </div>
                        )}
                        {b.error_message && (
                          <div style={{ fontSize: 11.5, color: '#F87171', marginTop: 4 }}>
                            Lỗi: {b.error_message}
                          </div>
                        )}
                      </td>
                      <td style={{ padding: '12px 16px', fontSize: 12.5, whiteSpace: 'nowrap' }}>
                        {b.created_at ? new Date(b.created_at).toLocaleString('vi-VN') : '—'}
                      </td>
                      <td style={{ padding: '12px 16px', textAlign: 'center', fontSize: 12.5, fontWeight: 700 }}>
                        {formatBytes(b.size_bytes)}
                      </td>
                      <td style={{ padding: '12px 16px', textAlign: 'center' }}>
                        <span
                          className={`badge ${b.storage_backend === 'r2' ? 'success' : 'warn'}`}
                          style={{ fontSize: 11, padding: '2px 8px' }}
                        >
                          {b.storage_backend === 'r2' ? 'Cloudflare R2' : 'Local Disk'}
                        </span>
                      </td>
                      <td style={{ padding: '12px 16px', textAlign: 'center' }}>
                        <span
                          className={`badge ${b.trigger_type === 'scheduled' ? 'info' : 'neutral'}`}
                          style={{ fontSize: 11, padding: '2px 8px' }}
                        >
                          {b.trigger_type === 'scheduled' ? '⏰ Tự động' : `👤 ${b.created_by || 'Admin'}`}
                        </span>
                      </td>
                      <td style={{ padding: '12px 16px', textAlign: 'center', fontSize: 12, color: 'var(--muted)' }}>
                        {b.duration_ms ? `${b.duration_ms}ms` : '—'}
                      </td>
                      <td style={{ padding: '12px 16px', textAlign: 'center' }}>
                        <span
                          className={`badge ${isCompleted ? 'success' : b.status === 'in_progress' ? 'warn' : 'danger'}`}
                          style={{ fontSize: 11, padding: '2px 8px' }}
                        >
                          {isCompleted ? '✓ Hoàn thành' : b.status === 'in_progress' ? '⏳ Đang chạy' : '✗ Thất bại'}
                        </span>
                      </td>
                      <td style={{ padding: '12px 16px', textAlign: 'right', whiteSpace: 'nowrap' }}>
                        <div style={{ display: 'inline-flex', gap: 6 }}>
                          {isCompleted && (
                            <a
                              href={api.backupDownloadUrl(b.id)}
                              className="btn btn-secondary"
                              style={{ fontSize: 11.5, padding: '4px 10px', textDecoration: 'none', display: 'inline-flex', alignItems: 'center', gap: 4 }}
                              title="Tải tệp nén về máy tính"
                            >
                              <span>📥</span> Tải về
                            </a>
                          )}
                          <button
                            type="button"
                            className="btn btn-secondary"
                            onClick={() => handleDelete(b)}
                            disabled={deleteMutation.isPending}
                            style={{ fontSize: 11.5, padding: '4px 8px', color: '#EF4444' }}
                            title="Xoá bản sao lưu này"
                          >
                            🗑️
                          </button>
                        </div>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}

export default function Admin({ currentUsername }: { currentUsername: string }) {
  const [mode, setMode] = useState<'users' | 'email' | 'backup' | 'features' | 'quotas' | 'log' | 'matrix' | 'intel'>('users')

  return (
    <div className="admin-container">
      {/* Executive Hero Header */}
      <div className="admin-hero-header">
        <div className="admin-hero-title-group">
          <div className="admin-hero-title-row">
            <span className="admin-hero-badge">Admin Console</span>
            <h1 className="admin-hero-heading">Quản Trị &amp; Phân Quyền Hệ Thống</h1>
          </div>
          <p className="admin-hero-subtitle">
            Kiểm soát tài khoản người dùng, thiết lập chính sách phân quyền RBAC chi tiết, định mức mở liên hệ và theo dõi nhật ký an ninh dữ liệu.
          </p>
        </div>
      </div>

      {/* Segmented Navigation Tabs */}
      <div className="admin-nav-tabs">
        <button
          className={`admin-tab-btn ${mode === 'email' ? 'active' : ''}`}
          onClick={() => setMode('email')}
        >
          ✉️ Email OTP
        </button>
        <button
          className={`admin-tab-btn ${mode === 'backup' ? 'active' : ''}`}
          onClick={() => setMode('backup')}
        >
          💾 Sao lưu &amp; R2
        </button>
        <button
          className={`admin-tab-btn ${mode === 'users' ? 'active' : ''}`}
          onClick={() => setMode('users')}
        >
          👥 Người dùng &amp; tài khoản
        </button>
        <button
          className={`admin-tab-btn ${mode === 'features' ? 'active' : ''}`}
          onClick={() => setMode('features')}
        >
          🔐 Tính năng theo vai trò (RBAC)
        </button>
        <button
          className={`admin-tab-btn ${mode === 'quotas' ? 'active' : ''}`}
          onClick={() => setMode('quotas')}
        >
          📞 Định mức mở liên hệ (Quota)
        </button>
        <button
          className={`admin-tab-btn ${mode === 'log' ? 'active' : ''}`}
          onClick={() => setMode('log')}
        >
          🛡️ Nhật ký hệ thống
        </button>
        <button
          className={`admin-tab-btn ${mode === 'matrix' ? 'active' : ''}`}
          onClick={() => setMode('matrix')}
        >
          📊 Ma trận &amp; Hoạt động
        </button>
        <button
          className={`admin-tab-btn ${mode === 'intel' ? 'active' : ''}`}
          onClick={() => setMode('intel')}
        >
          🧠 People Intelligence
        </button>
      </div>

      {/* Sub-Views */}
      {mode === 'users' && <UsersPanel currentUsername={currentUsername} />}
      {mode === 'email' && <EmailOtpSettingsPanel />}
      {mode === 'backup' && <DatabaseBackupPanel />}
      {mode === 'features' && <RoleFeaturesPolicyPanel />}
      {mode === 'quotas' && <ContactUnlockQuotaPanel currentUsername={currentUsername} />}
      {mode === 'log' && <AccessLogPanel />}
      {mode === 'matrix' && <RoleMatrixSummaryPanel />}
      {mode === 'intel' && <IntelPanel />}
    </div>
  )
}
