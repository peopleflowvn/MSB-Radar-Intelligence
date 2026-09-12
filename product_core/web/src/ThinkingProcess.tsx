import { useState, useEffect } from "react";
import FormattedMarkdown from "./FormattedMarkdown";

interface Props {
  isPending?: boolean;
  reasoning?: string;
  trace?: Array<{ label: string; detail: string }>;
  defaultExpanded?: boolean;
}

/**
 * Component hiển thị Quá trình suy nghĩ & Lập luận thật của AI.
 * - Khi đang suy nghĩ và có reasoning stream: Hiển thị luồng suy nghĩ thật của mô hình đang sinh ra.
 * - Khi chưa có reasoning / đang chờ: Hiển thị trạng thái chờ tinh gọn (không dùng các bước giả lập).
 * - Khi đã hoàn tất: Accordion cho phép xem toàn bộ chuỗi lập luận thật (DeepSeek / Gemini / OpenAI / Agent Trace).
 */
export default function ThinkingProcess({
  isPending = false,
  reasoning,
  trace,
  defaultExpanded = false,
}: Props) {
  const hasReasoning = Boolean(reasoning && reasoning.trim());
  const hasTrace = Boolean(trace && trace.length > 0);

  // Khi đang stream suy nghĩ thật, tự động mở để người dùng theo dõi
  const [expanded, setExpanded] = useState(defaultExpanded || (isPending && hasReasoning));

  useEffect(() => {
    if (isPending && hasReasoning) {
      setExpanded(true);
    }
  }, [isPending, hasReasoning]);

  // Nếu không có luồng suy nghĩ thật và không có trace thì ẩn
  if (!hasReasoning && !hasTrace) {
    if (!isPending) return null;
    // Khi đang pending mà chưa có reasoning text từ model:
    return (
      <div className="radar-thinking-pending-bar">
        <span className="radar-thinking-pulse-dot" />
        <span className="radar-thinking-pending-text">Radar đang suy nghĩ &amp; phân tích...</span>
      </div>
    );
  }

  return (
    <div className={`radar-thinking-box ${isPending ? "thinking-active" : "thinking-done"}`}>
      <button
        type="button"
        className="radar-thinking-header"
        onClick={() => setExpanded((prev) => !prev)}
        aria-expanded={expanded}
        title={expanded ? "Thu gọn luồng suy nghĩ" : "Xem luồng suy nghĩ thật của AI"}
      >
        <div className="radar-thinking-title">
          {isPending ? (
            <>
              <span className="radar-thinking-pulse" aria-hidden="true" />
              <span className="radar-thinking-label">Radar đang suy nghĩ...</span>
            </>
          ) : (
            <>
              <span className="radar-thinking-icon" aria-hidden="true">💡</span>
              <span className="radar-thinking-label">Quá trình suy nghĩ &amp; lập luận</span>
              {hasReasoning && (
                <span className="radar-thinking-token-badge">
                  {Math.round(reasoning!.length / 4)} tokens
                </span>
              )}
            </>
          )}
        </div>
        <span className="radar-thinking-toggle">{expanded ? "Thu gọn ▲" : "Xem chi tiết ▼"}</span>
      </button>

      {expanded && (
        <div className="radar-thinking-body">
          {hasReasoning && (
            <div className="radar-thinking-content">
              <FormattedMarkdown content={reasoning!} />
              {isPending && <span className="radar-thinking-cursor" />}
            </div>
          )}

          {hasTrace && (
            <div className="radar-thinking-trace-section">
              <span className="trace-section-heading">Công cụ &amp; Bằng chứng đã xác minh:</span>
              <ol className="agent-trace radar-thinking-trace">
                {trace!.map((step, idx) => (
                  <li key={idx}>
                    <span className="tick">✓</span>
                    <span className="step-label">{step.label}</span>
                    {step.detail && <span className="step-detail">{step.detail}</span>}
                  </li>
                ))}
              </ol>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
