import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api, IntelFact } from './api'

// Fact có nguồn của một Person — raw → canonical → evidence → nguồn (Master Plan §5).
// Chỉ hiện khi pipeline trích xuất đã chạy; im lặng nếu chưa có fact nào.

const FIELD_LABEL: Record<string, string> = {
  full_name: 'Họ tên', email: 'Email', phone: 'Điện thoại', gender: 'Giới tính',
  date_of_birth: 'Ngày sinh', city: 'Tỉnh/Thành', current_address: 'Địa chỉ',
  current_title: 'Chức danh', current_company: 'Công ty', seniority: 'Cấp bậc',
  years_experience: 'Số năm KN', education_level: 'Trình độ', university: 'Trường',
  major: 'Chuyên ngành', graduation_year: 'Năm tốt nghiệp', skills: 'Kỹ năng',
  industries: 'Ngành', languages: 'Ngôn ngữ', certifications: 'Chứng chỉ',
  expected_salary: 'Lương mong muốn', notice_period: 'Thời gian báo trước',
  applied_position: 'Vị trí ứng tuyển', applied_date: 'Ngày ứng tuyển', source: 'Nguồn',
}

const SOURCE_LABEL: Record<string, string> = {
  edge: 'Dữ liệu nguồn', cv_text: 'Trích từ CV', profile: 'Hồ sơ hiện có',
  ai: 'AI suy luận', manual: 'Người nhập tay',
}

export default function PersonFactsSection({ personId, isAdmin = false }: { personId: number; isAdmin?: boolean }) {
  const [isOpen, setIsOpen] = useState(false)
  const [showAll, setShowAll] = useState(false)
  const q = useQuery({
    queryKey: ['intel-person-facts', personId],
    queryFn: () => api.intelPersonFacts(personId),
    retry: false,
    enabled: isAdmin,
  })

  // Chỉ hiển thị cho Admin; không làm rối mắt người dùng thông thường
  if (!isAdmin) return null
  if (q.isError || !q.data) return null
  const current = Object.values(q.data.current)
  if (current.length === 0 && Object.keys(q.data.fields).length === 0) return null

  const historical = Object.entries(q.data.fields).flatMap(([, facts]) =>
    facts.filter((f) => !(f.is_current && f.status === 'accepted')))

  return (
    <section className="person-section-card" style={{ marginTop: 16 }}>
      <div
        className="section-title-row"
        style={{ cursor: 'pointer', userSelect: 'none', margin: 0 }}
        onClick={() => setIsOpen(!isOpen)}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <h3 className="section-title" style={{ margin: 0 }}>
            🛡️ Dữ liệu đã trích xuất &amp; Nguồn gốc (Facts Audit)
          </h3>
          <span className="badge muted" style={{ fontSize: '11px', padding: '2px 7px' }}>
            Chỉ Quản trị viên
          </span>
        </div>
        <button type="button" className="btn btn-secondary btn-sm">
          {isOpen ? '▲ Thu gọn' : '▼ Xem chi tiết đối soát'}
        </button>
      </div>

      {isOpen && (
        <div style={{ marginTop: '16px' }}>
          <p className="hint" style={{ marginTop: 0 }}>
            Mỗi giá trị truy ngược được về nguồn, bằng chứng và độ tin cậy. Giá trị người dùng sửa tay
            luôn thắng giá trị AI suy ra.
          </p>
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', fontSize: 13 }}>
              <thead>
                <tr><th>Trường</th><th>Giá trị</th><th>Nguồn</th><th>Tin cậy</th><th>Bằng chứng</th></tr>
              </thead>
              <tbody>
                {current.map((f) => <FactRow key={f.id} f={f} />)}
                {current.length === 0 && <tr><td colSpan={5} className="hint">Chưa có giá trị nào được chấp nhận.</td></tr>}
              </tbody>
            </table>
          </div>

          {historical.length > 0 && (
            <>
              <button className="ghost small" style={{ marginTop: 8 }} onClick={() => setShowAll(!showAll)}>
                {showAll ? 'Ẩn' : `Xem ${historical.length} giá trị cũ / chờ duyệt`}
              </button>
              {showAll && (
                <div style={{ overflowX: 'auto', marginTop: 8 }}>
                  <table style={{ width: '100%', fontSize: 12.5, opacity: 0.85 }}>
                    <thead>
                      <tr><th>Trường</th><th>Giá trị</th><th>Nguồn</th><th>Trạng thái</th><th>Ghi nhận</th></tr>
                    </thead>
                    <tbody>
                      {historical.map((f) => (
                        <tr key={f.id}>
                          <td>{FIELD_LABEL[f.field] ?? f.field}</td>
                          <td><code>{f.canonical_label || f.normalized_value || f.raw_value || '—'}</code></td>
                          <td>{SOURCE_LABEL[f.source_kind] ?? f.source_kind}</td>
                          <td><span className={`badge ${f.status === 'conflict' ? 'warn' : ''}`}>{f.status}</span></td>
                          <td className="hint">{f.observed_at ? new Date(f.observed_at).toLocaleDateString('vi-VN') : '—'}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </>
          )}
        </div>
      )}
    </section>
  )
}

function FactRow({ f }: { f: IntelFact }) {
  return (
    <tr>
      <td>{FIELD_LABEL[f.field] ?? f.field}</td>
      <td>
        <strong>{f.canonical_label || f.normalized_value || f.raw_value || '—'}</strong>
        {f.canonical_code && <span className="hint"> ({f.canonical_code})</span>}
        {f.raw_value && f.raw_value !== (f.canonical_label || f.normalized_value) && (
          <div className="hint">gốc: {f.raw_value}</div>
        )}
      </td>
      <td>{SOURCE_LABEL[f.source_kind] ?? f.source_kind}</td>
      <td>{f.source_kind === 'ai' ? `${(f.confidence * 100).toFixed(0)}%` : '—'}</td>
      <td className="hint" style={{ maxWidth: 260 }}>{f.evidence ? `“${f.evidence}”` : '—'}</td>
    </tr>
  )
}
