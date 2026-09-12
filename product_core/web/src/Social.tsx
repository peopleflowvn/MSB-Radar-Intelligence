import { useMutation, useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { api, ApiError, SocialPostRow } from './api'

// Social Radar (Master Plan mục 26–31).
//
// Màn hình này trả lời hai câu, theo đúng thứ tự đó:
//
//   1. Bài viết này có phải một cơ hội không?     — điểm ý định, đa nhãn
//   2. Ta đã biết người này chưa?                 — khớp vào People Database
//
// Câu thứ hai mới là chỗ sản phẩm có giá trị. Một bài "em đang tìm việc" trên
// Facebook thì ai đọc cũng thấy; biết rằng **người ấy từng nộp CV cho MSB 9
// tháng trước** thì chỉ hệ thống này biết.

const DOMAIN_LABELS: Record<string, string> = {
  talent: 'Tuyển dụng',
  rb: 'Khách hàng cá nhân',
}

// Hai ví dụ đầu cố ý mang CÙNG một số điện thoại: đó là cách duy nhất cho thấy
// được điều khó nói bằng lời — tuyển dụng thấy một ứng viên, bán lẻ thấy một
// khách hàng, nhưng chỉ có MỘT hồ sơ. Ví dụ thứ ba là cái bẫy: bài đăng tuyển
// của công ty khác, phải bị chấm thấp.
const VI_DU = [
  'Em đang tìm việc Data Analyst tại Hà Nội, 4 năm kinh nghiệm SQL và Python. Anh chị nào có cơ hội cho em xin với ạ. LH 0901234567',
  'Nhà em đang cần vay 500 triệu mua nhà, ngân hàng nào lãi suất tốt ạ? Em ở Hà Nội. LH 0901234567',
  'CÔNG TY ABC TUYỂN GẤP 5 Data Analyst tại Hà Nội. Ứng viên gửi CV qua hr@abc.vn',
]

/** Thanh điểm ý định. Hai điểm độc lập nhau nên vẽ hai thanh, không vẽ tròn 100%. */
function IntentBars({ scores }: { scores: Record<string, number> }) {
  const rows = Object.entries(scores).filter(([, v]) => typeof v === 'number')
  if (rows.length === 0) return null
  return (
    <div className="intent-bars">
      {rows.map(([domain, value]) => (
        <div key={domain} className={`intent-row ${value >= 0.5 ? 'on' : ''}`}>
          <span className="intent-name">{DOMAIN_LABELS[domain] ?? domain}</span>
          <span className="intent-bar">
            <span style={{ width: `${Math.round(value * 100)}%` }} />
          </span>
          <span className="intent-val">{Math.round(value * 100)}</span>
        </div>
      ))}
    </div>
  )
}

/** Kết quả khớp người — phần đáng giá nhất, nên nó phải nổi bật hơn điểm số. */
function Match({
  personId,
  name,
  note,
}: {
  personId: number | null
  name: string
  note: string
}) {
  if (!personId) {
    return (
      <p className="hint">
        Chưa khớp được với ai trong kho. Hệ thống <strong>không tự tạo hồ sơ mới</strong>{' '}
        từ một bài đăng — một cái tên hiển thị trên mạng chưa đủ để dựng một con người.
      </p>
    )
  }
  return (
    <div className="match-box">
      <Link to={`/person/${personId}`} className="talent-name">
        {name || '(chưa rõ tên)'}
      </Link>
      {note && <p className="match-note">{note}</p>}
    </div>
  )
}

function Analyze() {
  const [content, setContent] = useState('')

  const run = useMutation({
    mutationFn: (text: string) => api.socialAnalyze(text),
  })

  return (
    <div>
      <form
        className="search-panel"
        onSubmit={(event) => {
          event.preventDefault()
          if (content.trim()) run.mutate(content.trim())
        }}
      >
        <textarea
          className="jd-box"
          rows={5}
          placeholder="Dán một bài đăng Facebook vào đây…"
          value={content}
          onChange={(event) => setContent(event.target.value)}
        />
        <div className="search-row">
          <button type="submit" disabled={run.isPending || !content.trim()}>
            {run.isPending ? 'Đang đọc…' : 'Xem AI đọc ra gì'}
          </button>
          <span className="hint">
            Chỉ xem thử — không lưu gì vào cơ sở dữ liệu.
          </span>
        </div>

        {!run.data && !run.isPending && (
          <div className="suggestions">
            {VI_DU.map((text) => (
              <button
                key={text}
                type="button"
                className="chip"
                onClick={() => {
                  setContent(text)
                  run.mutate(text)
                }}
              >
                {text.slice(0, 70)}…
              </button>
            ))}
          </div>
        )}
      </form>

      {run.error && (
        <div className="login-error">
          {run.error instanceof ApiError ? run.error.message : 'Không gọi được máy chủ.'}
        </div>
      )}

      {run.data && (
        <div className="panel">
          <h3>AI đọc ra gì</h3>
          <IntentBars scores={run.data.intent.scores} />

          {run.data.intent.reason && (
            <p className="ai-summary">{run.data.intent.reason}</p>
          )}
          {run.data.intent.fallback && (
            <p className="err-box">
              AI đang bận nên điểm này do dò từ khoá — thô hơn nhiều, hãy tự đọc lại bài.
            </p>
          )}

          {Object.keys(run.data.intent.contacts).length > 0 && (
            <div className="chips">
              {Object.entries(run.data.intent.contacts).map(([kind, value]) => (
                <span key={kind} className="chip">
                  {kind}: <strong>{value}</strong>
                </span>
              ))}
            </div>
          )}

          <h3>Ta đã biết người này chưa?</h3>
          <Match
            personId={run.data.matched_person}
            name={run.data.matched_person_name}
            note={run.data.history_note}
          />
        </div>
      )}
    </div>
  )
}

function PostCard({ post }: { post: SocialPostRow }) {
  return (
    <div className={`social-card ${post.person ? 'linked' : ''}`}>
      <div className="social-head">
        <div>
          <strong>{post.author_name || 'ẩn danh'}</strong>
          {post.community_name && <span className="muted"> · {post.community_name}</span>}
        </div>
        {post.posted_at && (
          <span className="muted small">
            {new Date(post.posted_at).toLocaleDateString('vi-VN')}
          </span>
        )}
      </div>

      <p className="social-content">{post.content}</p>
      <IntentBars scores={post.intent} />
      {post.intent_reason && <p className="muted small">{post.intent_reason}</p>}

      <Match
        personId={post.person}
        name={post.person_name}
        note={post.history_note}
      />
    </div>
  )
}

export default function Social() {
  const [mode, setMode] = useState<'thu' | 'bai'>('thu')
  const posts = useQuery({
    queryKey: ['social-posts'],
    queryFn: () => api.socialPosts(),
    retry: false,
    enabled: mode === 'bai',
  })

  return (
    <div>
      <nav className="tabs sub-tabs">
        <button className={mode === 'thu' ? 'active' : ''} onClick={() => setMode('thu')}>
          Thử một bài
        </button>
        <button className={mode === 'bai' ? 'active' : ''} onClick={() => setMode('bai')}>
          Bài đã bắt được
        </button>
      </nav>

      {mode === 'thu' ? (
        <Analyze />
      ) : (
        <>
          <div className="result-head">
            <span>
              <strong>{posts.data?.count ?? 0}</strong> bài đáng chú ý
            </span>
          </div>
          <div className="hunt-list">
            {(posts.data?.results ?? []).map((post) => (
              <PostCard key={post.id} post={post} />
            ))}
            {posts.data && posts.data.count === 0 && (
              <div className="empty-box">
                Chưa có bài nào. Edge chưa có bộ thu Facebook — hiện tại dùng tab
                “Thử một bài” để dán bài vào xem AI đọc ra gì.
              </div>
            )}
          </div>
        </>
      )}
    </div>
  )
}
