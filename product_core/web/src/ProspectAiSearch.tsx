import { useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  api,
  ProspectAnswerPerson,
  ProspectAnswerPlan,
  prospectRowFromAnswer,
  ProspectRow,
} from "./api";
import { useProspectChatState } from "./searchPersistence";
import AnswerView, { AnswerTurn } from "./AnswerView";
import { inferFollowUpQuestions } from "./followUpInference";
import StepTimeline from "./StepTimeline";
import CopilotChat, { waitingHint } from "./CopilotChat";
import { personLinkFrom } from "./searchPerspective";

/** Ngữ cảnh quay lại cho Hồ sơ 360°: luồng này luôn là góc nhìn Khách hàng của /search. */
const PERSON_FROM = personLinkFrom("prospect", "ai");

export const GOI_Y_RB = [
  {
    icon: "🏡",
    title: "Vay mua nhà & An cư",
    text: "Tìm quản lý hoặc chuyên gia từ 5 năm kinh nghiệm có thể tiếp cận vay mua nhà",
  },
  {
    icon: "💳",
    title: "Thẻ tín dụng VIP",
    text: "Tìm quản lý, giám đốc hoặc chuyên gia quan tâm thẻ tín dụng hạn mức cao",
  },
  {
    icon: "🏢",
    title: "Vay vốn SME & Payroll",
    text: "Tìm chủ doanh nghiệp, CEO, kế toán trưởng để chào gói vốn kinh doanh và chi lương",
  },
  {
    icon: "💎",
    title: "Khách Ưu tiên & Tiết kiệm",
    text: "Tìm giám đốc, bác sĩ, chuyên gia lâu năm có dòng tiền tốt để tư vấn Priority & Tiết kiệm",
  },
];

export type ProspectRowScores = ProspectRow["scores"];

export const TEN_CHIEU: Record<keyof ProspectRowScores, string> = {
  fit: "Khớp hồ sơ",
  need: "Rõ nhu cầu",
  timing: "Đúng thời điểm",
  reachability: "Tiếp cận được",
  value: "Giá trị",
};

export const PRODUCTS: Array<[string, string]> = [
  ["", "Tất cả sản phẩm"],
  ["mortgage", "Vay mua nhà"],
  ["credit_card", "Thẻ tín dụng"],
  ["savings", "Tiết kiệm"],
  ["investment", "Đầu tư"],
  ["insurance", "Bảo hiểm"],
  ["fx", "Ngoại tệ"],
  ["auto_loan", "Vay mua xe"],
  ["consumer_loan", "Vay tiêu dùng"],
  ["payroll", "Tài khoản lương"],
];

export const PHAM_VI: Record<string, string> = {
  find_prospects: "Toàn kho khách hàng",
  portfolio: "Chỉ khách anh/chị đang phụ trách",
  whitespace: "Khách chưa ai phụ trách",
  analyze: "Tổng hợp toàn kho",
  count: "Đếm trong kho",
  compare: "So sánh khách đã nêu",
  followup: "Nhóm khách ở lượt trước",
};

export function PlanChips({ plan }: { plan?: ProspectAnswerPlan }) {
  const chips: Array<{ icon: string; text: string }> = [];
  if (!plan) {
    return <div className="chips"><span className="chip">Đang phân tích câu hỏi…</span></div>;
  }
  if (plan.shape && PHAM_VI[plan.shape]) chips.push({ icon: "🧭", text: `Phạm vi: ${PHAM_VI[plan.shape]}` });
  (plan.must_have ?? []).forEach((text) => chips.push({ icon: "✅", text: `Bắt buộc: ${text}` }));
  (plan.should_have ?? []).forEach((text) => chips.push({ icon: "➕", text: `Ưu tiên: ${text}` }));
  if (plan.products?.length) chips.push({ icon: "💼", text: `Sản phẩm: ${plan.products.join(", ")}` });
  const filters = plan.filters ?? {};
  if (filters.tinh_thanh) chips.push({ icon: "📍", text: `Khu vực: ${filters.tinh_thanh}` });
  if (filters.phan_khuc) chips.push({ icon: "🎯", text: `Phân khúc: ${filters.phan_khuc}` });
  if (filters.phai_co_lien_he) chips.push({ icon: "📞", text: "Phải có liên hệ" });
  if (filters.loai_co_hoi_dang_mo) chips.push({ icon: "🛡️", text: "Loại người đã có cơ hội mở" });
  if (filters.tin_hieu_trong_ngay) chips.push({ icon: "⏱️", text: `Tín hiệu trong ${filters.tin_hieu_trong_ngay} ngày` });

  return (
    <div className="chips">
      {chips.map(({ icon, text }) => (
        <span className="chip" key={text}>
          <span style={{ fontSize: "12px" }}>{icon}</span> {text}
        </span>
      ))}
    </div>
  );
}

export function ProspectCriteriaSection({ plan }: { plan?: ProspectAnswerPlan }) {
  const [open, setOpen] = useState(true);
  return (
    <section className="prospect-criteria-card" style={{ marginBottom: "12px" }}>
      <div
        className="prospect-criteria-head"
        style={{
          display: "flex",
          flexWrap: "wrap",
          alignItems: "center",
          justifyContent: "space-between",
          gap: "8px",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: "8px", flexWrap: "wrap" }}>
          <h4 className="prospect-criteria-title" style={{ margin: 0, fontSize: "12.5px" }}>
            <span>🎯</span> Hệ thống hiểu câu hỏi của bạn là
          </h4>
          <span
            className={`badge ${plan?.fallback ? "warn" : "ok"}`}
            title={
              plan?.fallback
                ? "Mô hình không hiểu được câu hỏi lúc này; hệ thống đang đoán theo từ khoá."
                : "Đọc bằng chứng thật: bài đăng, tín hiệu, lịch sử tiếp cận."
            }
          >
            {plan?.fallback ? "Dự phòng (đoán theo từ khoá)" : "AI suy luận bằng chứng"}
          </span>
        </div>
        <button
          type="button"
          className="btn btn-secondary btn-sm"
          style={{ fontSize: "11px", padding: "2px 8px", background: "none", border: "1px solid var(--border)" }}
          onClick={() => setOpen((prev) => !prev)}
        >
          {open ? "Thu gọn ▴" : "Chi tiết ▾"}
        </button>
      </div>
      {open ? (
        <div style={{ marginTop: "8px" }}>
          <PlanChips plan={plan} />
        </div>
      ) : null}
    </section>
  );
}

export function getProspectFollowUps(turn: AnswerTurn<ProspectAnswerPerson>, question?: string): string[] {
  return inferFollowUpQuestions(turn, { domain: "rb", question });
}

export default function ProspectAiSearch() {
  const qc = useQueryClient();
  const chatState = useProspectChatState();
  const [creatingFor, setCreatingFor] = useState<number | null>(null);
  const [createdMsg, setCreatedMsg] = useState<string | null>(null);
  const [createError, setCreateError] = useState<string | null>(null);
  const [aiViewMode, setAiViewMode] = useState<"cards" | "table">("cards");

  const createOpportunity = useMutation({
    mutationFn: ({ personId, product, need }: { personId: number; product: string; need: string }) =>
      api.rbOpportunityCreate({ person_id: personId, product, need }),
    onMutate: () => setCreateError(null),
    // 409 = khách đã có cơ hội mở cho sản phẩm này, hoặc đã yêu cầu không liên
    // hệ. Trước đây lỗi trôi mất: ô chọn vẫn mở, người dùng không biết vì sao.
    onError: (err) => setCreateError(err instanceof Error ? err.message : String(err)),
    onSuccess: () => {
      setCreatedMsg("✓ Đã tạo cơ hội mới vào Growth Radar thành công!");
      qc.invalidateQueries({ queryKey: ["rb-customer-tasks"] });
      qc.invalidateQueries({ queryKey: ["rb-opportunities"] });
      setTimeout(() => setCreatedMsg(null), 4000);
      setCreatingFor(null);
    },
  });

  return (
    <>
      {createdMsg && (
        <div className="talent-success-banner" style={{ marginBottom: "16px" }}>
          <span>{createdMsg}</span>
        </div>
      )}
      {createError && (
        <div className="err-box" role="alert" style={{ marginBottom: "16px" }}>
          ⚠ Không tạo được cơ hội: {createError}
        </div>
      )}

      <CopilotChat<ProspectAnswerPerson>
        chatState={chatState}
        ask={api.rbAsk}
        askTurn={api.rbAskTurn}
        supportsFiles={false}
        heroTitle={
          <>
            Trợ lý Tìm Kiếm &amp; Bán Chéo <span className="hero-gradient-text">Growth Radar</span>
          </>
        }
        heroSubtitle="Hỗ trợ RM &amp; Sales tìm kiếm khách hàng tiềm năng, cơ hội tài chính và bán chéo sản phẩm qua mô tả tự nhiên."
        heroPlaceholder="Mô tả chân dung khách hàng hoặc nhu cầu tài chính…"
        barPlaceholder="Mô tả chân dung khách hàng hoặc nhu cầu tài chính…"
        submitLabel="Tìm khách hàng"
        barSubmitAriaLabel="Gửi câu hỏi"
        quickPrompts={GOI_Y_RB}
        quickPromptIconStyle={{ background: "rgba(5, 150, 105, 0.12)", color: "#059669" }}
        renderAnswerBody={(msg, mi, messages, elapsedSeconds, sendFollowUp) => {
          const ans = msg.answer;
          const question = messages[mi - 1]?.sender === "user" ? messages[mi - 1].text : undefined;
          const plan = ans?.trace?.plan as ProspectAnswerPlan | undefined;
          const traceMeta = ans?.trace as { keeps_last_result?: boolean; count?: { exact?: boolean } } | undefined;
          const textOnly = Boolean(traceMeta?.keeps_last_result) || Boolean(traceMeta?.count?.exact);
          const showPayload = Boolean(plan) && !textOnly;
          const rows = (ans?.people ?? []).map(prospectRowFromAnswer);

          return (
            <>
              {(msg.isPending || (ans?.steps?.length ?? 0) > 0 || (ans?.durationMs ?? Number(ans?.trace?.ms_total ?? 0)) > 0) ? (
                <StepTimeline
                  steps={ans?.steps}
                  stage={ans?.stage}
                  elapsedSeconds={elapsedSeconds}
                  hint={waitingHint(elapsedSeconds)}
                  isPending={msg.isPending}
                  compact={!!msg.text}
                  durationMs={ans?.durationMs ?? Number(ans?.trace?.ms_total ?? 0)}
                />
              ) : null}

              {ans ? (
                <AnswerView<ProspectAnswerPerson>
                  turn={ans}
                  isPending={msg.isPending}
                  question={question}
                  conversationId={chatState.threadId}
                  onFollowUp={sendFollowUp}
                  getFollowUps={getProspectFollowUps}
                  personLinkFrom={PERSON_FROM}
                  extraBeforePeople={
                    showPayload ? <ProspectCriteriaSection plan={plan} /> : null
                  }
                  renderPeople={() =>
                    !showPayload ? null : rows.length === 0 ? (
                      <div className="empty-results-box" style={{ width: "100%" }}>
                        <div className="empty-icon">🔍</div>
                        <h3>Chưa có khách hàng nào có đủ bằng chứng phù hợp.</h3>
                        <p>Thử điều chỉnh câu hỏi mô tả hoặc dùng Bộ lọc Đa chiều để tra cứu rộng hơn.</p>
                      </div>
                    ) : (
                      <>
                        <div className="results-header-toolbar" style={{ margin: "0" }}>
                          <div className="results-count-badge">
                            <span>
                              Tìm thấy <strong>{rows.length}</strong> khách hàng tiềm năng xếp theo mức đáng ưu tiên liên hệ
                            </span>
                          </div>
                          <div className="results-actions-right">
                            <div className="view-mode-toggle">
                              <button
                                type="button"
                                className={`view-btn ${aiViewMode === "cards" ? "active" : ""}`}
                                onClick={() => setAiViewMode("cards")}
                                title="Xem dạng thẻ phân tích thông minh"
                              >
                                ⊞ Thẻ thông minh
                              </button>
                              <button
                                type="button"
                                className={`view-btn ${aiViewMode === "table" ? "active" : ""}`}
                                onClick={() => setAiViewMode("table")}
                                title="Xem dạng bảng cô đọng"
                              >
                                ≡ Bảng dữ liệu
                              </button>
                            </div>
                          </div>
                        </div>

                        {aiViewMode === "cards" ? (
                          <div className="prospect-ai-grid">
                            {rows.map((row) => (
                              <div key={row.person_id} className="prospect-ai-card">
                                <div className="prospect-card-top">
                                  <div className="prospect-avatar-meta-group">
                                    <div className="prospect-avatar-circle">
                                      {(row.display_name || "K")[0]?.toUpperCase()}
                                    </div>
                                    <div className="prospect-meta-info">
                                      <Link
                                        to={`/person/${row.person_id}?from=${PERSON_FROM}`}
                                        className="prospect-name-link"
                                        target="_blank"
                                        rel="noopener noreferrer"
                                      >
                                        {row.display_name || `Person #${row.person_id}`}
                                      </Link>
                                      <div className="prospect-headline-text">
                                        {row.occupation || "Khách hàng cá nhân"}
                                      </div>
                                      {row.location && (
                                        <div className="prospect-location-tag">
                                          <span>📍</span> {row.location}
                                        </div>
                                      )}
                                      {row.action_label && (
                                        <span
                                          className="badge ok"
                                          title="Hành động tiếp theo do hệ thống chọn từ trạng thái liên hệ và lịch sử tiếp cận"
                                          style={{ alignSelf: "flex-start", marginTop: "4px", fontSize: "11px", fontWeight: 700 }}
                                        >
                                          → {row.action_label}
                                          {typeof row.freshest_days === "number" && (
                                            <span style={{ fontWeight: 500, marginLeft: 6, opacity: 0.8 }}>
                                              · tín hiệu {row.freshest_days === 0 ? "hôm nay" : `${row.freshest_days} ngày trước`}
                                            </span>
                                          )}
                                        </span>
                                      )}
                                      {row.has_open_opportunity && (
                                        <span
                                          className="badge"
                                          style={{
                                            alignSelf: "flex-start",
                                            marginTop: "4px",
                                            background: "rgba(245, 158, 11, 0.12)",
                                            color: "#b45309",
                                            border: "1px solid rgba(245, 158, 11, 0.3)",
                                            fontSize: "11px",
                                            fontWeight: 700,
                                          }}
                                        >
                                          Đã có cơ hội mở
                                        </span>
                                      )}
                                    </div>
                                  </div>

                                  <div className="prospect-score-box" title="Điểm ưu tiên tổng hợp">
                                    <span className="score-number-big">{Math.round(row.priority_score)}</span>
                                    <span className="score-label-small">Điểm AI</span>
                                  </div>
                                </div>

                                {/* 5 Radar Dimension Pills */}
                                <div className="radar-dimensions-bar">
                                  {(Object.keys(TEN_CHIEU) as Array<keyof ProspectRowScores>).map((key) => (
                                    <span key={key} className="radar-dimension-pill">
                                      {TEN_CHIEU[key]}: <strong>{Math.round(row.scores[key])}</strong>
                                    </span>
                                  ))}
                                </div>

                                {/* Why AI Recommended Bullets */}
                                <div className="prospect-why-box">
                                  {row.why.slice(0, 3).map((line, index) => (
                                    <div key={index} className="prospect-why-item">{line}</div>
                                  ))}
                                </div>

                                {/* Card Footer Actions */}
                                <div className="prospect-card-bottom">
                                  <Link
                                    className="btn btn-secondary btn-sm"
                                    to={`/person/${row.person_id}?from=${PERSON_FROM}`}
                                    target="_blank"
                                    rel="noopener noreferrer"
                                  >
                                    Hồ sơ 360° →
                                  </Link>
                                  {creatingFor === row.person_id ? (
                                    <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
                                      <select
                                        className="config-select"
                                        style={{ fontSize: "12px", padding: "4px 8px" }}
                                        defaultValue={row.product || "credit_card"}
                                        id={`prod-select-card-${row.person_id}`}
                                      >
                                        {PRODUCTS.filter(([p]) => Boolean(p)).map(([code, label]) => (
                                          <option key={code} value={code}>{label}</option>
                                        ))}
                                      </select>
                                      <button
                                        type="button"
                                        className="btn btn-primary btn-sm"
                                        disabled={createOpportunity.isPending}
                                        onClick={() => {
                                          const sel = document.getElementById(
                                            `prod-select-card-${row.person_id}`,
                                          ) as HTMLSelectElement;
                                          createOpportunity.mutate({
                                            personId: row.person_id,
                                            product: sel?.value || "credit_card",
                                            need: `Đề xuất từ Growth Radar: ${question ?? ""}`,
                                          });
                                        }}
                                      >
                                        Xác nhận
                                      </button>
                                      <button
                                        type="button"
                                        className="btn btn-ghost btn-sm"
                                        onClick={() => setCreatingFor(null)}
                                      >
                                        Huỷ
                                      </button>
                                    </div>
                                  ) : (
                                    <button
                                      type="button"
                                      className="btn btn-primary btn-sm"
                                      onClick={() => setCreatingFor(row.person_id)}
                                    >
                                      ⚡ Tạo cơ hội
                                    </button>
                                  )}
                                </div>
                              </div>
                            ))}
                          </div>
                        ) : (
                          <div
                            className="talent-table-wrapper prospect-table-wrapper"
                            style={{
                              background: "var(--surface)",
                              border: "1px solid var(--border)",
                              borderRadius: "14px",
                              overflowX: "auto",
                              overflowY: "hidden",
                              WebkitOverflowScrolling: "touch",
                              maxWidth: "100%",
                            }}
                          >
                            <table className="table prospect-table" style={{ margin: 0, minWidth: "980px", width: "100%" }}>
                              <thead>
                                <tr>
                                  <th style={{ minWidth: "220px", width: "240px" }}>Khách hàng</th>
                                  <th style={{ minWidth: "160px", width: "180px" }}>Nghề nghiệp / Chức danh</th>
                                  <th className="num" style={{ minWidth: "190px", width: "190px", textAlign: "center" }}>Điểm ưu tiên</th>
                                  <th style={{ minWidth: "260px" }}>Vì sao đề xuất</th>
                                  <th style={{ minWidth: "140px", width: "140px", textAlign: "right" }}>Thao tác</th>
                                </tr>
                              </thead>
                              <tbody>
                                {rows.map((row) => (
                                  <tr key={row.person_id}>
                                    <td>
                                      <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
                                        <div
                                          className="task-avatar"
                                          style={{
                                            width: "34px",
                                            height: "34px",
                                            fontSize: "13px",
                                            background: "var(--accent-gradient)",
                                          }}
                                        >
                                          {(row.display_name || "K")[0]?.toUpperCase()}
                                        </div>
                                        <div>
                                          <Link
                                            to={`/person/${row.person_id}?from=${PERSON_FROM}`}
                                            style={{ fontWeight: 700, color: "var(--text)", textDecoration: "none" }}
                                            target="_blank"
                                            rel="noopener noreferrer"
                                          >
                                            {row.display_name || `Person #${row.person_id}`}
                                          </Link>
                                          {row.location && (
                                            <div className="muted small" style={{ fontSize: "12px" }}>
                                              📍 {row.location}
                                            </div>
                                          )}
                                          {row.has_open_opportunity && (
                                            <span
                                              className="badge"
                                              style={{
                                                marginTop: "4px",
                                                display: "inline-block",
                                                background: "rgba(245, 158, 11, 0.1)",
                                                color: "#b45309",
                                                border: "1px solid rgba(245, 158, 11, 0.3)",
                                              }}
                                            >
                                              Đã có cơ hội mở
                                            </span>
                                          )}
                                        </div>
                                      </div>
                                    </td>
                                    <td>
                                      <span style={{ fontWeight: 500, color: "var(--text-secondary)" }}>
                                        {row.occupation || <span className="muted">Chưa rõ</span>}
                                      </span>
                                    </td>
                                    <td className="num" style={{ minWidth: "190px", width: "190px", textAlign: "center" }}>
                                      <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: "3px" }}>
                                        <span
                                          style={{
                                            fontSize: "18px",
                                            fontWeight: 800,
                                            color: "#059669",
                                            lineHeight: 1.2,
                                          }}
                                        >
                                          {Math.round(row.priority_score)}
                                        </span>
                                        <div className="muted small" style={{ fontSize: "11px", textAlign: "center", lineHeight: 1.45, maxWidth: "180px" }}>
                                          {(Object.keys(TEN_CHIEU) as Array<keyof ProspectRowScores>)
                                            .map((key) => `${TEN_CHIEU[key]} ${Math.round(row.scores[key])}`)
                                            .join(" · ")}
                                        </div>
                                      </div>
                                    </td>
                                    <td className="prospect-why" style={{ minWidth: "260px" }}>
                                      {row.why && row.why.length > 0 ? (
                                        row.why.slice(0, 3).map((line, index) => (
                                          <div key={index}>{line}</div>
                                        ))
                                      ) : (
                                        <span className="muted small" style={{ fontStyle: "italic", opacity: 0.7 }}>Chưa có ghi chú phân tích</span>
                                      )}
                                    </td>
                                    <td style={{ textAlign: "right" }}>
                                      {creatingFor === row.person_id ? (
                                        <div style={{ display: "flex", flexDirection: "column", gap: "4px" }}>
                                          <select
                                            className="config-select"
                                            style={{ fontSize: "11.5px" }}
                                            defaultValue={row.product || "credit_card"}
                                            id={`prod-select-table-${row.person_id}`}
                                          >
                                            {PRODUCTS.filter(([p]) => Boolean(p)).map(([code, label]) => (
                                              <option key={code} value={code}>{label}</option>
                                            ))}
                                          </select>
                                          <button
                                            type="button"
                                            className="btn btn-primary btn-sm"
                                            style={{ fontSize: "11px", padding: "3px 8px" }}
                                            disabled={createOpportunity.isPending}
                                            onClick={() => {
                                              const sel = document.getElementById(
                                                `prod-select-table-${row.person_id}`,
                                              ) as HTMLSelectElement;
                                              createOpportunity.mutate({
                                                personId: row.person_id,
                                                product: sel?.value || "credit_card",
                                                need: `Đề xuất từ Growth Radar: ${question ?? ""}`,
                                              });
                                            }}
                                          >
                                            Xác nhận
                                          </button>
                                        </div>
                                      ) : (
                                        <button
                                          type="button"
                                          className="btn btn-secondary btn-sm"
                                          style={{ fontSize: "11.5px", padding: "4px 10px", whiteSpace: "nowrap" }}
                                          onClick={() => setCreatingFor(row.person_id)}
                                        >
                                          ⚡ Tạo cơ hội
                                        </button>
                                      )}
                                    </td>
                                  </tr>
                                ))}
                              </tbody>
                            </table>
                          </div>
                        )}
                      </>
                    )
                  }
                />
              ) : (
                msg.text && <p className="chat-paragraph">{msg.text}</p>
              )}
            </>
          );
        }}
      />
    </>
  );
}
