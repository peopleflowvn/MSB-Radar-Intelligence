import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";
import { api, OpportunitySuggestionRow, WorkProfileRow } from "./api";

/**
 * CƠ HỘI HÔM NAY — màn hình chính của RB Radar.
 *
 * RM không nên phải tự hỏi "hôm nay tôi search gì". Mở lên là thấy việc, xếp
 * sẵn theo điểm ưu tiên, mỗi thẻ kèm VÌ SAO BÂY GIỜ.
 *
 * Thứ tự thông tin trên thẻ cố ý phản ánh thứ tự RM cần đọc — AI · NHU CẦU ·
 * VÌ SAO · GIÁ TRỊ · VIỆC NÊN LÀM. Chi tiết 5 chiều điểm nằm trong phần gấp:
 * RM cần chúng khi muốn phản bác, không phải khi đang lướt.
 */

const VALUE_LABELS: Record<string, string> = {
  low: "Thấp",
  medium: "Trung bình",
  high: "Cao",
  very_high: "Rất cao",
};

const SCORE_LABELS: Record<string, string> = {
  fit: "Khớp hồ sơ",
  need: "Rõ nhu cầu",
  timing: "Đúng thời điểm",
  reachability: "Tiếp cận được",
  value: "Giá trị",
};

const PRODUCTS: Array<[string, string]> = [
  ["mortgage", "Vay mua nhà"],
  ["credit_card", "Thẻ tín dụng"],
  ["auto_loan", "Vay mua xe"],
  ["consumer_loan", "Vay tiêu dùng"],
  ["savings", "Tiết kiệm"],
  ["investment", "Đầu tư"],
  ["insurance", "Bảo hiểm"],
  ["fx", "Ngoại tệ"],
  ["payroll", "Tài khoản lương"],
];

const SEGMENTS: Array<[string, string]> = [
  ["mass", "Phổ thông"],
  ["affluent", "Khá giả"],
  ["priority", "Ưu tiên"],
];

function ScoreBar({ label, value }: { label: string; value: number }) {
  return (
    <div className="score-dim-row">
      <span className="score-dim-label">{label}</span>
      <span className="score-dim-track">
        <span className="score-dim-fill" style={{ width: `${Math.round(value)}%` }} />
      </span>
      <span className="score-dim-num">{Math.round(value)}</span>
    </div>
  );
}

function SuggestionCard({ row }: { row: OpportunitySuggestionRow }) {
  const qc = useQueryClient();
  const [detail, setDetail] = useState(false);
  const [dismissing, setDismissing] = useState(false);
  const [reason, setReason] = useState("");
  const [error, setError] = useState("");

  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["rb-today"] });
    qc.invalidateQueries({ queryKey: ["rb-customer-tasks"] });
  };

  const act = useMutation({
    mutationFn: (payload: Parameters<typeof api.rbSuggestionAction>[1]) =>
      api.rbSuggestionAction(row.id, payload),
    onSuccess: () => {
      setError("");
      setDismissing(false);
      refresh();
    },
    onError: (err: Error) => setError(err.message),
  });

  const dismiss = () => {
    // Bỏ qua bắt buộc kèm lý do — cùng nguyên tắc với đóng cơ hội: một đề xuất
    // bị bỏ im lặng sẽ được sinh lại y hệt vào tháng sau.
    if (!reason.trim()) {
      setError("Cho biết lý do bỏ qua để Radar không đề xuất lại y hệt.");
      return;
    }
    act.mutate({ action: "dismiss", reason: reason.trim() });
  };

  return (
    <article
      className={`opportunity-card ${row.is_discovery ? "is-discovery" : ""}`}
    >
      <header className="opportunity-card-head">
        <div>
          <Link className="opportunity-person" to={`/person/${row.person}?from=rb`}>
            {row.person_name || `Person #${row.person}`}
          </Link>
          {row.occupation && (
            <span className="opportunity-occupation">{row.occupation}</span>
          )}
        </div>
        <div className="opportunity-score-block">
          <span className="opportunity-score">
            {Math.round(row.personalized_score)}
          </span>
          {row.personalized_score !== row.priority_score && (
            /* Hiện cả điểm gốc: điểm đã cá nhân hoá là của riêng người đang
               xem, còn điểm gốc mới là thứ so sánh được giữa các RM. */
            <span className="opportunity-score-base">
              gốc {Math.round(row.priority_score)}
            </span>
          )}
        </div>
      </header>

      <div className="opportunity-badges">
        <span className="badge">{row.product_label}</span>
        <span className="badge">
          Giá trị: {VALUE_LABELS[row.value_band] ?? row.value_band}
        </span>
        <span className="badge">
          Tin cậy {Math.round(row.confidence * 100)}%
        </span>
        {row.is_discovery && (
          <span className="badge warn" title="Ngoài khai báo của bạn nhưng điểm khách quan cao">
            🧭 Ngoài vùng bạn phụ trách — đáng xem
          </span>
        )}
        {row.territory === "out" && !row.is_discovery && (
          <span className="badge">📍 Ngoài địa bàn</span>
        )}
      </div>

      {row.need_summary && (
        <p className="opportunity-need">{row.need_summary}</p>
      )}

      <div className="opportunity-why">
        <span className="opportunity-why-title">VÌ SAO BÂY GIỜ</span>
        <ul>
          {row.why.slice(0, 4).map((line, index) => (
            <li key={index}>{line}</li>
          ))}
        </ul>
        {row.personalized_why.length > 0 && (
          <ul className="opportunity-why-personal">
            {row.personalized_why.map((line, index) => (
              <li key={index}>{line}</li>
            ))}
          </ul>
        )}
      </div>

      {row.handoff_to && (
        /* Ngoài địa bàn thì ĐỊNH TUYẾN, không đánh rơi: khách được giữ lại
           trong hệ thống, chỉ đổi người xử lý. Đây là gợi ý — chuyển việc cho
           người khác là quyết định của con người. */
        <div className="opportunity-handoff">
          Khách thuộc địa bàn <strong>{row.handoff_to.region}</strong> —
          cân nhắc chuyển cho <strong>{row.handoff_to.name}</strong>.
        </div>
      )}

      <div className="opportunity-action">
        <span className="opportunity-action-label">Việc nên làm</span>
        <strong>{row.action_label}</strong>
      </div>

      {error && <p className="opportunity-error">{error}</p>}

      <footer className="opportunity-card-foot">
        <button
          type="button"
          className="btn btn-primary"
          disabled={act.isPending}
          onClick={() => act.mutate({ action: "accept" })}
        >
          Nhận cơ hội
        </button>
        <button
          type="button"
          className="btn btn-secondary"
          disabled={act.isPending}
          onClick={() => act.mutate({ action: "snooze", days: 14 })}
        >
          Để sau
        </button>
        <button
          type="button"
          className="btn btn-ghost"
          disabled={act.isPending}
          onClick={() => setDismissing((open) => !open)}
        >
          Bỏ qua
        </button>
        <button
          type="button"
          className="btn btn-ghost"
          onClick={() => setDetail((open) => !open)}
        >
          {detail ? "Ẩn điểm" : "Xem điểm"}
        </button>
      </footer>

      {dismissing && (
        <div className="opportunity-dismiss">
          <input
            type="text"
            value={reason}
            placeholder="Vì sao bỏ qua? (bắt buộc)"
            onChange={(event) => setReason(event.target.value)}
          />
          <button type="button" className="btn btn-secondary" onClick={dismiss}>
            Xác nhận bỏ qua
          </button>
        </div>
      )}

      {detail && (
        <div className="opportunity-scores">
          {(Object.keys(SCORE_LABELS) as Array<keyof typeof row.scores>).map(
            (key) => (
              <ScoreBar
                key={key}
                label={SCORE_LABELS[key]}
                value={row.scores[key]}
              />
            ),
          )}
          <p className="opportunity-scores-note">
            Điểm do hệ thống tính theo công thức cố định, không phải do AI sinh ra.
          </p>
        </div>
      )}
    </article>
  );
}

function WorkProfilePanel({ profile }: { profile: WorkProfileRow }) {
  const qc = useQueryClient();
  const [regions, setRegions] = useState(profile.regions.join(", "));
  const [products, setProducts] = useState<string[]>(profile.focus_products);
  const [segments, setSegments] = useState<string[]>(profile.target_segments);
  const [capacity, setCapacity] = useState(String(profile.daily_capacity));
  const [notes, setNotes] = useState(profile.notes);
  const [saved, setSaved] = useState(false);

  const observed = profile.observed;
  const canPrefill =
    observed.confident &&
    (observed.regions.length > 0 || observed.focus_products.length > 0);

  const save = useMutation({
    mutationFn: () =>
      api.rbWorkProfileSave({
        regions: regions
          .split(",")
          .map((item) => item.trim())
          .filter(Boolean),
        focus_products: products,
        target_segments: segments,
        daily_capacity: Number(capacity) || 20,
        notes,
      }),
    onSuccess: () => {
      setSaved(true);
      qc.invalidateQueries({ queryKey: ["rb-today"] });
      qc.invalidateQueries({ queryKey: ["rb-work-profile"] });
    },
  });

  const toggle = (
    value: string,
    current: string[],
    setter: (next: string[]) => void,
  ) =>
    setter(
      current.includes(value)
        ? current.filter((item) => item !== value)
        : [...current, value],
    );

  return (
    <section className="work-profile-panel">
      <h3>Địa bàn &amp; trọng tâm của bạn</h3>
      <p className="work-profile-hint">
        Khai báo này chỉ đổi <strong>thứ tự</strong> danh sách của riêng bạn.
        Điểm gốc của mỗi cơ hội giữ nguyên, và Radar luôn giữ một phần danh sách
        cho cơ hội tốt nằm ngoài khai báo.
      </p>

      {canPrefill && (
        /* Rủi ro lớn nhất của form khai báo là không ai điền. Hệ thống đã có đủ
           dữ liệu để tự suy ra — hiện lên để người dùng chỉ việc xác nhận.
           Tách riêng khỏi ô nhập: phải phân biệt được đâu là mình khai, đâu là
           máy đoán. */
        <div className="work-profile-observed">
          <p>
            Từ {observed.sample_size} cơ hội bạn đã xử lý, hệ thống thấy bạn
            thường làm việc ở{" "}
            <strong>{observed.regions.join(", ") || "chưa rõ khu vực"}</strong>
            {observed.focus_products.length > 0 && (
              <>
                , chủ yếu sản phẩm{" "}
                <strong>
                  {observed.focus_products
                    .map(
                      (code) =>
                        PRODUCTS.find(([value]) => value === code)?.[1] ?? code,
                    )
                    .join(", ")}
                </strong>
              </>
            )}
            .
          </p>
          <button
            type="button"
            className="btn btn-secondary"
            onClick={() => {
              setRegions(observed.regions.join(", "));
              setProducts(observed.focus_products);
              setSaved(false);
            }}
          >
            Điền giúp tôi
          </button>
        </div>
      )}

      <label className="work-profile-field">
        <span>Địa bàn phụ trách</span>
        <input
          type="text"
          value={regions}
          placeholder="Hà Nội, Bắc Ninh"
          onChange={(event) => {
            setRegions(event.target.value);
            setSaved(false);
          }}
        />
      </label>

      <div className="work-profile-field">
        <span>Sản phẩm đang phụ trách</span>
        <div className="work-profile-chips">
          {PRODUCTS.map(([value, label]) => (
            <button
              key={value}
              type="button"
              className={`pill-btn ${products.includes(value) ? "active" : ""}`}
              onClick={() => {
                toggle(value, products, setProducts);
                setSaved(false);
              }}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      <div className="work-profile-field">
        <span>Phân khúc nhắm tới</span>
        <div className="work-profile-chips">
          {SEGMENTS.map(([value, label]) => (
            <button
              key={value}
              type="button"
              className={`pill-btn ${segments.includes(value) ? "active" : ""}`}
              onClick={() => {
                toggle(value, segments, setSegments);
                setSaved(false);
              }}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      <label className="work-profile-field">
        <span>Số việc xử lý nổi mỗi ngày</span>
        <input
          type="number"
          min={1}
          max={100}
          value={capacity}
          onChange={(event) => {
            setCapacity(event.target.value);
            setSaved(false);
          }}
        />
      </label>

      <label className="work-profile-field">
        <span>Ghi chú thêm cho AI</span>
        <textarea
          rows={3}
          value={notes}
          placeholder="Tôi phụ trách khu công nghiệp phía Bắc, khách chủ yếu là chủ xưởng."
          onChange={(event) => {
            setNotes(event.target.value);
            setSaved(false);
          }}
        />
        <small>
          Ghi chú chỉ dùng để AI diễn giải, không làm thay đổi điểm số hay
          thứ hạng.
        </small>
      </label>

      <button
        type="button"
        className="btn btn-primary"
        disabled={save.isPending}
        onClick={() => save.mutate()}
      >
        {save.isPending ? "Đang lưu…" : "Lưu khai báo"}
      </button>
      {saved && <span className="badge ok">Đã lưu</span>}
    </section>
  );
}

export default function TodaysOpportunities() {
  const [product, setProduct] = useState("");
  const [showProfile, setShowProfile] = useState(false);

  const today = useQuery({
    queryKey: ["rb-today", product],
    queryFn: () => api.rbToday({ product: product || undefined }),
  });
  const profile = useQuery({
    queryKey: ["rb-work-profile"],
    queryFn: api.rbWorkProfile,
  });

  const rows = today.data?.results ?? [];
  const summary = today.data?.summary;

  return (
    <div className="todays-opportunities">
      <div className="workspace-filter-toolbar">
        <div className="scope-pills-row">
          <button
            type="button"
            className={`scope-pill-btn ${product === "" ? "active" : ""}`}
            onClick={() => setProduct("")}
          >
            Tất cả ({summary?.total ?? 0})
          </button>
          {PRODUCTS.map(([value, label]) => (
            <button
              key={value}
              type="button"
              className={`scope-pill-btn ${product === value ? "active" : ""}`}
              onClick={() => setProduct(value)}
            >
              {label}
            </button>
          ))}
        </div>
        <button
          type="button"
          className="btn btn-secondary"
          onClick={() => setShowProfile((open) => !open)}
        >
          ⚙️ Địa bàn &amp; trọng tâm
        </button>
      </div>

      {showProfile && profile.data && <WorkProfilePanel profile={profile.data} />}

      {summary && summary.total > 0 && (
        <div className="workspace-quick-kpi opportunity-summary">
          <div className="kpi-mini-card">
            <span className="kpi-num">{summary.total}</span>
            <span className="kpi-txt">Cơ hội đáng xử lý</span>
          </div>
          <div className="kpi-mini-card">
            <span className="kpi-num">{summary.high_priority}</span>
            <span className="kpi-txt">Ưu tiên cao</span>
          </div>
          <div className="kpi-mini-card">
            <span className="kpi-num">{summary.call_now}</span>
            <span className="kpi-txt">Nên gọi ngay</span>
          </div>
          <div className="kpi-mini-card">
            <span className="kpi-num">{summary.fresh_signals}</span>
            <span className="kpi-txt">Tín hiệu mới</span>
          </div>
          <div className="kpi-mini-card">
            <span className="kpi-num">{summary.reactivation}</span>
            <span className="kpi-txt">Kích hoạt lại</span>
          </div>
        </div>
      )}

      {today.isLoading && <p className="empty">Đang tải cơ hội…</p>}
      {today.isError && (
        <p className="empty">Không tải được danh sách cơ hội.</p>
      )}
      {!today.isLoading && rows.length === 0 && (
        <p className="empty">
          Chưa có cơ hội nào được đề xuất. Radar sinh đề xuất từ tín hiệu thu
          được — thử phân tích một bài đăng ở Social Radar.
        </p>
      )}

      <div className="opportunity-grid">
        {rows.map((row) => (
          <SuggestionCard key={row.id} row={row} />
        ))}
      </div>
    </div>
  );
}
