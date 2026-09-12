import { useQuery } from '@tanstack/react-query'
import { CaptureStats, Metric, OverviewResponse, api } from './api'

// Trang vận hành (Master Plan mục 15, PHASE 15).
//
// Trước phase này, "hệ thống có đang khoẻ không" nằm rải rác ở bốn nơi không
// ai gộp lại: đồng bộ Edge, chi phí AI, chỉ số Talent, chỉ số RB — cộng giờ có
// thêm quan sát Agent Runtime (Phase 14). Trang này KHÔNG tính lại logic của
// bốn nơi đó, chỉ gọi và gộp — xem `server/reports/overview.py`.
//
// Chỉ Admin/Manager vào được: trang này hiện cả số Talent lẫn số RB trên cùng
// một màn hình, và đó là thứ chỉ hai vai trò nhìn xuyên suốt mới nên thấy.

/** Cùng style với `.metric` ở Hiring.tsx — chưa có dữ liệu hiện "—", không
 * hiện 0, vì số 0 đọc như "làm rồi mà kém" còn dấu gạch đọc đúng là "chưa đủ
 * dữ liệu để nói". */
function MetricTile({ metric }: { metric: Metric }) {
  if (metric.value === null) {
    return (
      <div className="metric empty">
        <div className="metric-value">—</div>
        <div className="metric-detail">{metric.detail}</div>
      </div>
    )
  }
  const shown =
    metric.unit === 'ratio'
      ? `${Math.round(metric.value * 100)}%`
      : metric.unit === 'x'
        ? `${metric.value}×`
        : `${metric.value}${metric.unit ? ` ${metric.unit}` : ''}`
  return (
    <div className="metric">
      <div className="metric-value">{shown}</div>
      <div className="metric-label">{metric.label}</div>
      <div className="metric-detail">{metric.detail}</div>
    </div>
  )
}

function MetricGrid({ metrics }: { metrics: Record<string, Metric> }) {
  const rows = Object.values(metrics)
  return (
    <div className="metrics">
      {rows.map((metric, index) => (
        <MetricTile key={index} metric={metric} />
      ))}
    </div>
  )
}

function statLine(label: string, value: string | number) {
  return (
    <div className="stat">
      <div className="stat-value">{value}</div>
      <div className="stat-label">{label}</div>
    </div>
  )
}

function formatMs(ms: number | null) {
  if (ms === null) return '—'
  if (ms < 1000) return `${ms} ms`
  return `${(ms / 1000).toFixed(1)} s`
}

function AgentSection({ agents }: { agents: OverviewResponse['agents'] }) {
  const AGENT_LABELS: Record<string, string> = {
    talent: 'Talent Radar Agent',
    rb: 'Growth Radar Agent',
    social: 'Social Intent Agent',
  }
  return (
    <section className="panel">
      <h3>Radar Agent Runtime</h3>
      <p className="hint">
        Quan sát, không phải LLM tự chọn hành động — trình tự bước do code quyết
        định. Xem <code>docs/AGENT_RUNTIME.md</code>.
      </p>
      <div className="stats">
        {statLine('Lượt chạy', agents.total_runs)}
        {statLine(
          'Tỉ lệ lỗi',
          agents.error_rate === null ? '—' : `${Math.round(agents.error_rate * 100)}%`,
        )}
        {statLine('Thời gian trung vị', formatMs(agents.median_ms))}
      </div>
      {agents.by_agent.length > 0 && (
        <div className="chips">
          {agents.by_agent.map((row) => (
            <span key={row.agent} className="chip">
              {AGENT_LABELS[row.agent] ?? row.agent}: <strong>{row.runs}</strong>
            </span>
          ))}
        </div>
      )}
    </section>
  )
}

/**
 * Năng lực thu thập — chỗ moat kỹ thuật thành con số nhìn thấy được.
 *
 * Con số đắt nhất ở đây là `multi_source_people`: số người mà Hub đã chứng minh
 * được là **cùng một người** dù đến từ nhiều nền tảng khác nhau. Không có Hub
 * thì mỗi lượt đó là một hồ sơ rời, và tổ chức không biết mình đã từng biết ai.
 */
function CaptureSection({ capture }: { capture: CaptureStats }) {
  const { consolidation, parsing, providers } = capture
  return (
    <section className="panel">
      <h3>Thu thập &amp; hợp nhất dữ liệu</h3>
      <div className="stats">
        {statLine('Bản ghi nguồn đã nhận', consolidation.source_records)}
        {statLine('Hợp nhất thành người', consolidation.unique_people)}
        {statLine('Người đến từ nhiều nguồn', consolidation.multi_source_people)}
        {statLine('Lượt hồ sơ / người',
          consolidation.records_per_person ?? 'Chưa có dữ liệu')}
        {statLine('Bóc tách CV thành công',
          parsing.success_rate === null
            ? 'Chưa có tài liệu'
            : `${Math.round(parsing.success_rate * 100)}%`)}
      </div>

      {consolidation.max_sources_for_one_person > 1 && (
        <p className="muted">
          Hồ sơ nhiều nguồn nhất: <strong>
            {consolidation.max_sources_for_one_person} nền tảng
          </strong> gộp về cùng một người.
        </p>
      )}

      <table className="table">
        <thead>
          <tr>
            <th>Nguồn</th>
            <th className="num">Bản ghi</th>
            <th className="num">Người</th>
            <th className="num">Mới 24h</th>
            <th className="num">Chờ phân giải</th>
          </tr>
        </thead>
        <tbody>
          {providers.map((row) => (
            <tr key={row.source || row.label}>
              <td>
                {row.label}{' '}
                {/* Nguồn chưa kết nối vẫn hiện với số 0: "TopCV chưa chạy" là
                    thông tin vận hành, không phải thứ để giấu. */}
                <span className={`badge ${row.connected ? 'ok' : 'off'}`}>
                  {row.connected ? 'đang chảy' : 'chưa có dữ liệu'}
                </span>
              </td>
              <td className="num">{row.records}</td>
              <td className="num">{row.people}</td>
              <td className="num">{row.new_today}</td>
              <td className="num">{row.pending}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  )
}

export default function Dashboard() {
  const overview = useQuery({
    queryKey: ['reports-overview'],
    queryFn: api.reportsOverview,
    retry: false,
  })

  if (overview.isLoading) return <div className="hint">Đang tải…</div>
  if (!overview.data) {
    return <div className="empty-box">Không tải được dữ liệu vận hành.</div>
  }
  const data = overview.data

  return (
    <div>
      <CaptureSection capture={data.capture} />

      <section className="panel">
        <h3>Đồng bộ Edge</h3>
        <div className="stats">
          {statLine('Edge đã đăng ký', `${data.sync.edges_registered}/${data.sync.edges}`)}
          {statLine('Bản ghi nguồn', data.sync.source_records)}
          {statLine('Chờ phân giải', data.sync.pending_resolution)}
        </div>
      </section>

      <section className="panel">
        <h3>Sử dụng AI</h3>
        <div className="stats">
          {statLine('Tổng lượt gọi', data.ai_usage.total_calls)}
          {statLine('Lượt lỗi', data.ai_usage.failed_calls)}
        </div>
        {data.ai_usage.by_provider.length > 0 && (
          <div className="chips">
            {data.ai_usage.by_provider.map((row) => (
              <span key={row.provider} className="chip">
                {row.provider}: <strong>{row.calls}</strong>
              </span>
            ))}
          </div>
        )}
      </section>

      <AgentSection agents={data.agents} />

      <section className="panel">
        <h3>Talent Radar</h3>
        <MetricGrid metrics={data.talent} />
      </section>

      <section className="panel">
        <h3>Growth Radar</h3>
        <MetricGrid metrics={data.rb} />
      </section>
    </div>
  )
}
