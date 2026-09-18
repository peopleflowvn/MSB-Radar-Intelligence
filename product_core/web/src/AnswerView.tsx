import { ReactNode, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { AnswerPerson, AnswerSource, api } from "./api";
import { inferFollowUpQuestions } from "./followUpInference";
import FormattedMarkdown, { LinkablePerson } from "./FormattedMarkdown";
import SourcePreview, { SourceRef } from "./SourcePreview";

/**
 * Hiển thị MỘT lượt trả lời của Answer Engine.
 *
 * Thay cho danh sách thẻ ứng viên cũ. Thẻ vừa chiếm gần hết màn hình, vừa lặp
 * lại y nguyên nội dung đã có trong câu trả lời, mà phần đánh giá trên thẻ lại
 * do một bộ chấm điểm khác sinh ra nên hay mâu thuẫn với chính câu trả lời.
 *
 * Ở đây câu trả lời là trung tâm; người chỉ còn là một dòng chip bấm được, và
 * trích dẫn [n] bấm ngay trong câu chữ để xem nguyên văn đoạn CV gốc.
 */

export interface AnswerStep {
  label: string;
  state: "active" | "done";
}

/** `TPerson` mặc định là người Talent (trích dẫn CV). Growth Radar dùng
 *  `AnswerTurn<ProspectAnswerPerson>` — cùng khuôn sự kiện SSE, chỉ khác hình
 *  dạng "người" trong kết quả (điểm ưu tiên thay vì trích dẫn CV). */
export interface AnswerTurn<TPerson = AnswerPerson> {
  text: string;
  stage?: string;
  /** "Đã nhận yêu cầu — đây là cách mình định làm", hiện ngay sau khi hiểu câu
   *  hỏi, trước khi các bước tốn thời gian chạy. */
  preamble?: string;
  /** Các bước đang/đã làm — để giao diện tick dần thay vì đổ token suy nghĩ. */
  steps?: AnswerStep[];
  sources: AnswerSource[];
  people: TPerson[];
  /** Radar tự phát hiện lỗi trong câu trả lời và viết lại. */
  revised?: boolean;
  /** Nguồn ngoài internet khi Radar tra web để trả lời. */
  webSources?: Array<{ title?: string; url: string }>;
  reasoning?: string;
  provider?: string;
  model?: string;
  trace?: Record<string, unknown>;
  /** Thời gian từ khi server nhận câu hỏi đến khi có câu trả lời hoàn chỉnh. */
  durationMs?: number;
}

function sourceRef(source: AnswerSource): SourceRef {
  return {
    documentId: source.document_id,
    snippet: source.snippet,
    personName: source.name,
    personId: source.person_id,
    label: `[${source.n}]`,
  };
}

/** Thẻ ứng viên thông minh gọn gàng cho Talent Radar, thay thế dạng chip tối giản. */
function TalentSmartCards({
  people,
  personLinkFrom = "talent-ai",
}: {
  people: AnswerPerson[];
  personLinkFrom?: string;
}) {
  const [viewMode, setViewMode] = useState<"compact" | "chips">("compact");

  if (!people || people.length === 0) return null;

  return (
    <div className="talent-smart-section">
      <div className="talent-smart-header">
        <span className="talent-smart-title">
          <span>Hồ sơ được nhắc tới</span> <span className="talent-smart-count">({people.length})</span>
        </span>
        <div className="talent-view-toggle">
          <button
            type="button"
            className={`talent-toggle-btn ${viewMode === "compact" ? "active" : ""}`}
            onClick={() => setViewMode("compact")}
            title="Dạng thẻ thông minh gọn gàng"
          >
            ⊞ Thẻ gọn
          </button>
          <button
            type="button"
            className={`talent-toggle-btn ${viewMode === "chips" ? "active" : ""}`}
            onClick={() => setViewMode("chips")}
            title="Dạng nhãn tối giản"
          >
            ≡ Dạng nhãn
          </button>
        </div>
      </div>

      {viewMode === "chips" ? (
        <div className="answer-people-chips">
          {people.map((person) => {
            const attributes = Object.entries(person.attributes ?? {});
            return (
              <Link
                key={person.person_id}
                to={`/person/${person.person_id}?from=${personLinkFrom}`}
                className="answer-person-chip"
                title={person.why || undefined}
              >
                <strong>{person.name}</strong>
                {attributes.length > 0 && (
                  <span className="muted small">
                    {attributes.slice(0, 2).map(([key, value]) => `${key}: ${value}`).join(" · ")}
                  </span>
                )}
              </Link>
            );
          })}
        </div>
      ) : (
        <div className="talent-smart-grid">
          {people.map((person) => {
            const attributes = Object.entries(person.attributes ?? {});
            const role =
              person.attributes?.["Chức danh"] ||
              person.attributes?.["Vị trí"] ||
              person.attributes?.["role"] ||
              person.attributes?.["title"] ||
              person.attributes?.["Nghề nghiệp"];
            const company =
              person.attributes?.["Công ty"] ||
              person.attributes?.["Đơn vị"] ||
              person.attributes?.["company"];
            const headline = [role, company].filter(Boolean).join(" · ");

            return (
              <Link
                key={person.person_id}
                to={`/person/${person.person_id}?from=${personLinkFrom}`}
                className="talent-compact-card"
                title={`Mở hồ sơ 360° của ${person.name}`}
              >
                <div className="talent-card-header">
                  <div className="talent-card-avatar">
                    {(person.name || "U")[0]?.toUpperCase()}
                  </div>
                  <div className="talent-card-title-wrap">
                    <div className="talent-card-name-row">
                      <span className="talent-card-name">{person.name}</span>
                      {person.citations && person.citations.length > 0 && (
                        <span className="talent-card-citations" title="Trích dẫn bằng chứng">
                          {person.citations.map((c) => `[${c}]`).join(" ")}
                        </span>
                      )}
                    </div>
                    {headline ? (
                      <div className="talent-card-headline" title={headline}>
                        {headline}
                      </div>
                    ) : null}
                  </div>
                </div>

                {person.why && (
                  <div className="talent-card-why" title={person.why}>
                    <span className="talent-why-icon">💡</span>
                    <span className="talent-why-text">{person.why}</span>
                  </div>
                )}

                    {attributes.length > 0 && (
                      <div className="talent-card-attributes">
                        {attributes.slice(0, 3).map(([key, value]) => (
                          <span key={key} className="talent-attr-pill" title={`${key}: ${value}`}>
                            {`${key}: ${value}`}
                          </span>
                        ))}
                      </div>
                    )}
              </Link>
            );
          })}
        </div>
      )}
    </div>
  );
}

/** 👍/👎 trên một câu trả lời. Gửi một lần, không cho đổi ý loạn xạ. */
function Rating({ turn, question, conversationId }: {
  turn: AnswerTurn<any>; question?: string; conversationId?: string;
}) {
  const [sent, setSent] = useState<"up" | "down" | null>(null);
  const [failed, setFailed] = useState(false);

  const send = (rating: "up" | "down") => {
    setSent(rating);
    api.aiFeedback({ rating, conversation_id: conversationId,
                     question, answer: turn.text })
      .catch(() => { setFailed(true); setSent(null); });
  };

  if (sent) {
    return <span className="answer-rating-done muted small">Cảm ơn phản hồi của bạn.</span>;
  }
  return (
    <div className="answer-rating">
      <span className="muted small">Câu trả lời này có dùng được không?</span>
      <button type="button" className="answer-rating-btn" title="Dùng được"
              onClick={() => send("up")}>👍</button>
      <button type="button" className="answer-rating-btn" title="Chưa dùng được"
              onClick={() => send("down")}>👎</button>
      {failed && <span className="muted small">Không gửi được, thử lại sau.</span>}
    </div>
  );
}

/** Mặc định dùng cho Talent (`turn.people` là `AnswerPerson[]`). Growth Radar
 *  truyền `getFollowUps` riêng vì "ứng viên" ở đây là "khách hàng". */
function getFollowUpSuggestions(turn: AnswerTurn<any>, question?: string): string[] {
  return inferFollowUpQuestions(turn, { domain: "talent", question });
}

export interface WorkflowModelItem {
  role: string;
  provider?: string;
  model?: string;
  icon?: string;
}

export function extractWorkflowModels<TPerson>(turn: AnswerTurn<TPerson>): WorkflowModelItem[] {
  const trace = turn.trace as any;
  if (Array.isArray(trace?.workflow_models) && trace.workflow_models.length > 0) {
    return trace.workflow_models
      .map((item: any) => ({
        role: item.role || item.stage || "Mô hình",
        provider: item.provider,
        model: item.model,
        icon:
          item.icon ||
          (item.stage === "plan"
            ? "🎯"
            : item.stage === "judge"
            ? "⚖️"
            : item.stage === "compose"
            ? "✍️"
            : item.stage === "action"
            ? "⚡"
            : item.stage === "chat"
            ? "💬"
            : item.stage === "assess_doc"
            ? "📄"
            : "🤖"),
      }))
      .filter((m: WorkflowModelItem) => Boolean(m.model || m.provider));
  }

  const items: WorkflowModelItem[] = [];

  // Lập kế hoạch (Plan)
  const plan = trace?.plan;
  if (plan && (plan.model || plan.provider)) {
    items.push({
      role: "Lập kế hoạch",
      provider: plan.provider,
      model: plan.model,
      icon: "🎯",
    });
  }

  // Sàng lọc & Đánh giá (Judge)
  const pass1 = trace?.pass1;
  const pass2 = trace?.pass2;
  const judge = trace?.judge;
  const judgeModel = judge?.model || pass1?.model || pass2?.model;
  const judgeProvider = judge?.provider || pass1?.provider || pass2?.provider;
  if (judgeModel || judgeProvider) {
    items.push({
      role: "Sàng lọc & Đánh giá",
      provider: judgeProvider,
      model: judgeModel,
      icon: "⚖️",
    });
  }

  // Tổng hợp & Trả lời (Compose)
  const compose = trace?.compose;
  const composeModel = compose?.model || turn.model;
  const composeProvider = compose?.provider || turn.provider;
  const isFallback = Boolean((compose as { fallback?: boolean } | undefined)?.fallback);

  if (!isFallback && (composeModel || composeProvider)) {
    const isChat = trace?.mode === "chat";
    const isAction = trace?.mode === "action";
    const isAssessDoc = trace?.mode === "assess_doc";
    const role = isChat
      ? "Hội thoại"
      : isAction
      ? "Thực thi tác vụ"
      : isAssessDoc
      ? "Đọc & Phân tích tệp"
      : "Tổng hợp & Trả lời";
    const icon = isChat ? "💬" : isAction ? "⚡" : isAssessDoc ? "📄" : "✍️";
    items.push({
      role,
      provider: composeProvider,
      model: composeModel,
      icon,
    });
  }

  if (items.length === 0 && !isFallback && (turn.model || turn.provider)) {
    items.push({
      role: "Mô hình xử lý",
      provider: turn.provider,
      model: turn.model,
      icon: "🤖",
    });
  }

  return items;
}

export default function AnswerView<TPerson = AnswerPerson>({
  turn,
  isPending,
  question,
  conversationId,
  onFollowUp,
  renderPeople,
  extraBeforePeople,
  getFollowUps,
  personLinkFrom = "talent-ai",
}: {
  turn: AnswerTurn<TPerson>;
  isPending?: boolean;
  question?: string;
  conversationId?: string;
  onFollowUp?: (query: string) => void;
  /** Ghi đè cách hiện "người" trong kết quả — mặc định là chip trích dẫn CV
   *  (`PeopleStrip`); Growth Radar truyền lưới/bảng thẻ khách hàng có điểm
   *  ưu tiên + nút "Tạo cơ hội". */
  renderPeople?: (people: TPerson[]) => ReactNode;
  /** Chỗ chèn nội dung riêng theo domain (VD: khối "Hệ thống hiểu câu hỏi của
   *  bạn là…" của Growth Radar) — hiện ngay sau văn bản trả lời, trước phần
   *  người/khách hàng. */
  extraBeforePeople?: ReactNode;
  /** Ghi đè gợi ý câu hỏi tiếp theo — mặc định dùng ngôn ngữ "ứng viên". */
  getFollowUps?: (turn: AnswerTurn<TPerson>, question?: string) => string[];
  /** `from` gắn vào link hồ sơ khi TÊN người được nhắc trong câu chữ tự thành
   *  liên kết (không phải chip cuối bài) — quyết định "← Quay lại" đúng trang
   *  trên Hồ sơ 360°. Growth Radar truyền `"rb"`. */
  personLinkFrom?: string;
}) {
  const [preview, setPreview] = useState<SourceRef | null>(null);
  const [showSources, setShowSources] = useState(false);
  const [copied, setCopied] = useState(false);
  const byNumber = new Map(turn.sources.map((source) => [source.n, source]));

  const handleCopy = () => {
    if (!turn.text) return;
    navigator.clipboard.writeText(turn.text).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }).catch(() => undefined);
  };

  // Tên người trong câu chữ thành liên kết mở hồ sơ. Gom từ CẢ `people` lẫn
  // `sources`: ⑤ hay nhắc tên một người nó vừa trích CV mà không đưa vào danh
  // sách `people`, và đúng cái tên đó mới là chỗ người đọc muốn bấm.
  const linkablePeople = useMemo<LinkablePerson[]>(() => {
    const byId = new Map<number, LinkablePerson>();
    // `person_id`/`name` tồn tại trên cả AnswerPerson (Talent) lẫn
    // ProspectAnswerPerson (RB) — ép kiểu để dùng chung logic gắn liên kết.
    for (const person of turn.people as unknown as Array<{ person_id: number; name: string }>) {
      if (person?.name) byId.set(person.person_id, { personId: person.person_id, name: person.name });
    }
    for (const source of turn.sources) {
      if (source.name && !byId.has(source.person_id)) {
        byId.set(source.person_id, { personId: source.person_id, name: source.name });
      }
    }
    return [...byId.values()];
  }, [turn.people, turn.sources]);

  const openCitation = (n: number) => {
    const source = byNumber.get(n);
    if (source) setPreview(sourceRef(source));
  };

  return (
    <div className="answer-turn">
      {preview && <SourcePreview source={preview} onClose={() => setPreview(null)} />}

      {turn.revised && (
        // Nói rõ đã sửa. Âm thầm thay bài dưới mắt người đang đọc còn khó chịu
        // hơn là để nguyên câu sai.
        <div className="answer-revised muted small">
          ✎ Radar tự kiểm lại và đã viết lại câu trả lời cho đúng.
        </div>
      )}

      {turn.text && (
        <FormattedMarkdown content={turn.text} onCitation={openCitation}
                           people={linkablePeople} peopleLinkFrom={personLinkFrom} />
      )}

      {extraBeforePeople}

      {renderPeople
        ? renderPeople(turn.people)
        : <TalentSmartCards people={turn.people as unknown as AnswerPerson[]} personLinkFrom={personLinkFrom} />}

      {(turn.webSources?.length ?? 0) > 0 && (
        <div className="answer-sources">
          <span className="answer-people-label">🌐 Nguồn trên internet</span>
          <ol className="answer-sources-list">
            {turn.webSources!.map((source, index) => (
              <li key={`${source.url}-${index}`}>
                <a href={source.url} target="_blank" rel="noopener noreferrer">
                  {source.title || source.url}
                </a>
              </li>
            ))}
          </ol>
        </div>
      )}

      {turn.sources.length > 0 && (
        <div className="answer-sources">
          <button
            type="button"
            className="answer-sources-toggle"
            onClick={() => setShowSources((open) => !open)}
          >
            {showSources ? "▾" : "▸"} {turn.sources.length} nguồn trích dẫn
          </button>
          {showSources && (
            <ol className="answer-sources-list">
              {turn.sources.map((source) => (
                <li key={`${source.n}-${source.document_id}-${source.ordinal}`}>
                  <button
                    type="button"
                    className="citation-link"
                    onClick={() => setPreview(sourceRef(source))}
                  >
                    <b>[{source.n}] {source.name}</b>{" "}
                    <span className="muted small">“{source.snippet}”</span>
                  </button>
                </li>
              ))}
            </ol>
          )}
        </div>
      )}

      {/* Gợi ý các câu hỏi tiếp theo (Smart Follow-ups) khi đã có câu trả lời */}
      {!isPending && turn.text && onFollowUp && (
        <div className="answer-followup-section">
          <span className="answer-followup-title">💡 GỢI Ý CÂU HỎI TIẾP THEO:</span>
          <div className="answer-followup-chips">
            {(getFollowUps ? getFollowUps(turn, question) : getFollowUpSuggestions(turn, question)).map((suggestion) => (
              <button
                key={suggestion}
                type="button"
                className="answer-followup-chip"
                onClick={() => onFollowUp(suggestion)}
              >
                <span className="followup-icon">💬</span>
                <span className="followup-text">{suggestion}</span>
              </button>
            ))}
          </div>
        </div>
      )}

      {!isPending && turn.text && (
        <div className="answer-footer-row">
          {(() => {
            const workflowModels = extractWorkflowModels(turn);
            if (!workflowModels.length) return null;
            return (
              <div className="answer-workflow-models" title="Các mô hình AI tham gia trong quy trình xử lý">
                <span className="workflow-models-title">🤖 Mô hình quy trình ({workflowModels.length}):</span>
                <div className="workflow-models-badges">
                  {workflowModels.map((item, idx) => (
                    <span
                      key={idx}
                      className="workflow-model-pill"
                      title={`${item.role}: ${item.provider ? `${item.provider}/` : ""}${item.model || "mặc định"}`}
                    >
                      <span className="workflow-model-icon">{item.icon}</span>
                      <span className="workflow-model-role">{item.role}:</span>
                      <code className="workflow-model-name">
                        {item.provider ? `${item.provider}/${item.model || "mặc định"}` : item.model}
                      </code>
                    </span>
                  ))}
                </div>
              </div>
            );
          })()}
          <div className="answer-footer-meta">
            {(() => {
              const dur = turn.durationMs || Number((turn.trace as any)?.ms_total || 0);
              if (!dur) return null;
              return (
                <span className="answer-duration muted small" title="Thời gian xử lý câu trả lời">
                  ⏱️ {(dur / 1000).toFixed(1)}s
                </span>
              );
            })()}
            <button
              type="button"
              className="answer-copy-btn"
              onClick={handleCopy}
              title="Sao chép nội dung câu trả lời"
            >
              {copied ? "✓ Đã chép" : "📋 Sao chép"}
            </button>
          </div>
          <Rating turn={turn} question={question} conversationId={conversationId} />
        </div>
      )}
    </div>
  );
}
