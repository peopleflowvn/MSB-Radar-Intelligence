import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { AnswerPerson, AnswerSource, api } from "./api";
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

export interface AnswerTurn {
  text: string;
  stage?: string;
  /** "Đã nhận yêu cầu — đây là cách mình định làm", hiện ngay sau khi hiểu câu
   *  hỏi, trước khi các bước tốn thời gian chạy. */
  preamble?: string;
  /** Các bước đang/đã làm — để giao diện tick dần thay vì đổ token suy nghĩ. */
  steps?: AnswerStep[];
  sources: AnswerSource[];
  people: AnswerPerson[];
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

/** Dòng người được nhắc — đủ để mở hồ sơ, không phải một thẻ hồ sơ thu nhỏ. */
function PeopleStrip({ people }: { people: AnswerPerson[] }) {
  if (people.length === 0) return null;
  return (
    <div className="answer-people">
      <span className="answer-people-label">Hồ sơ được nhắc tới</span>
      <div className="answer-people-chips">
        {people.map((person) => {
          const attributes = Object.entries(person.attributes ?? {});
          return (
            <Link
              key={person.person_id}
              to={`/person/${person.person_id}?from=talent-ai`}
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
    </div>
  );
}

/** 👍/👎 trên một câu trả lời. Gửi một lần, không cho đổi ý loạn xạ. */
function Rating({ turn, question, conversationId }: {
  turn: AnswerTurn; question?: string; conversationId?: string;
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

function getFollowUpSuggestions(turn: AnswerTurn): string[] {
  if (turn.people && turn.people.length > 1) {
    return [
      `So sánh chi tiết các ứng viên vừa tìm được`,
      `Ai trong số đó có nhiều năm kinh nghiệm nhất?`,
      `Soạn thư mời phỏng vấn cho ${turn.people[0].name}`,
    ];
  }
  if (turn.people && turn.people.length === 1) {
    return [
      `Tóm tắt điểm mạnh nổi bật của ${turn.people[0].name}`,
      `Tìm thêm các ứng viên tương tự ${turn.people[0].name}`,
      `Soạn email liên hệ hẹn phỏng vấn`,
    ];
  }
  if (turn.webSources && turn.webSources.length > 0) {
    return [
      "Tóm tắt các ý chính quan trọng",
      "Chính sách này áp dụng thế nào tại MSB?",
    ];
  }
  return [
    "Gợi ý thêm tiêu chí tìm kiếm mở rộng trong kho",
    "Có hồ sơ ứng viên nào khác liên quan không?",
  ];
}

export default function AnswerView({
  turn,
  isPending,
  question,
  conversationId,
  onFollowUp,
}: {
  turn: AnswerTurn;
  isPending?: boolean;
  question?: string;
  conversationId?: string;
  onFollowUp?: (query: string) => void;
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
    for (const person of turn.people) {
      if (person.name) byId.set(person.person_id, { personId: person.person_id, name: person.name });
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
                           people={linkablePeople} />
      )}

      <PeopleStrip people={turn.people} />

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
            {getFollowUpSuggestions(turn).map((suggestion) => (
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
          <div className="answer-footer-meta">
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
