import { useState } from "react";
import type { AnswerStep } from "./AnswerView";

interface Props {
  steps?: AnswerStep[];
  stage?: string;
  elapsedSeconds?: number;
  hint?: string;
  isPending?: boolean;
  compact?: boolean;
}

/**
 * Khối hiển thị Tiến trình & Các bước thực thi của Radar AI:
 * - Hợp nhất toàn bộ Bước (Steps), Đếm giây (Timer), và Trạng thái (Stage) vào một thẻ duy nhất.
 * - Tránh lặp lại tên bước nhiều lần trên cùng một khung chat.
 * - Khi đang xử lý: Hiển thị danh sách bước kèm đếm giây và gợi ý thông minh.
 * - Khi đã hoàn tất: Tự động thu gọn thành một thanh tóm tắt tinh tế (có thể mở rộng xem lại).
 */
export default function StepTimeline({
  steps = [],
  stage,
  elapsedSeconds = 0,
  hint,
  isPending = false,
  compact = false,
}: Props) {
  const [expanded, setExpanded] = useState(!compact);
  const totalCount = steps.length;
  // Lượt đã kết thúc thì không còn bước nào "đang chạy" — kể cả khi máy chủ
  // chưa kịp gửi chunk đóng cho bước cuối. Không chốt ở đây thì thẻ hiện
  // "2/3 bước" kèm một vòng xoay vĩnh viễn bên cạnh câu trả lời đã xong.
  const doneCount = isPending
    ? steps.filter((s) => s.state === "done").length
    : totalCount;

  // Nếu không có bước nào và không pending thì không hiển thị
  if (!totalCount && !isPending && !stage) return null;

  // Trạng thái thu gọn (khi câu trả lời đã bắt đầu xuất hiện hoặc người dùng thu gọn)
  if (compact && !expanded && totalCount > 0) {
    return (
      <div className="radar-steps-compact-bar">
        <button
          type="button"
          className="radar-steps-compact-btn"
          onClick={() => setExpanded(true)}
          title="Xem chi tiết các bước xử lý của AI"
        >
          <span className="radar-steps-compact-icon">✓</span>
          <span className="radar-steps-compact-text">
            Đã hoàn thành {doneCount}/{totalCount} bước
            {elapsedSeconds > 0 && <span className="radar-steps-time"> · {elapsedSeconds}s</span>}
          </span>
          <span className="radar-steps-compact-chevron">Chi tiết ▾</span>
        </button>
      </div>
    );
  }

  return (
    <div className={`radar-steps-card ${isPending ? "is-pending" : "is-done"}`}>
      {/* Header thanh lịch khi đã có các bước hoặc đang thu gọn */}
      {compact && totalCount > 0 && (
        <div className="radar-steps-card-header">
          <div className="radar-steps-header-left">
            <span className="radar-steps-done-badge">✓</span>
            <span className="radar-steps-card-title">
              Quá trình xử lý ({doneCount}/{totalCount} bước)
            </span>
          </div>
          <button
            type="button"
            className="radar-steps-toggle-btn"
            onClick={() => setExpanded(false)}
            title="Thu gọn danh sách bước"
          >
            Thu gọn ▲
          </button>
        </div>
      )}

      {/* Danh sách các bước chi tiết */}
      {totalCount > 0 ? (
        <ol className="radar-steps-list">
          {steps.map((step, i) => {
            const isStepActive = step.state === "active" && isPending;
            const isStepDone = step.state === "done" || (step.state === "active" && !isPending);

            return (
              <li
                key={`${step.label}-${i}`}
                className={`radar-step-item ${isStepDone ? "step-done" : isStepActive ? "step-active" : "step-waiting"}`}
              >
                <div className="radar-step-icon-wrap" aria-hidden="true">
                  {isStepDone ? (
                    <span className="step-check-icon">✓</span>
                  ) : isStepActive ? (
                    <span className="step-spinner-icon" />
                  ) : (
                    <span className="step-bullet" />
                  )}
                </div>

                <div className="radar-step-content">
                  <span className="radar-step-name">{step.label}</span>
                  {isStepActive && (
                    <span className="radar-step-active-meta">
                      {elapsedSeconds > 0 && <span className="step-timer-badge">{elapsedSeconds}s</span>}
                      <span className="step-typing-pulse">
                        <span className="pulse-dot" />
                        <span className="pulse-dot" />
                        <span className="pulse-dot" />
                      </span>
                    </span>
                  )}
                </div>
              </li>
            );
          })}
        </ol>
      ) : (
        /* Khi chưa kịp sinh danh sách bước, hiển thị thanh chờ đơn giản */
        <div className="radar-step-single-pending">
          <div className="step-spinner-icon" />
          <div className="radar-step-content">
            <span className="radar-step-name">{stage || "Radar đang suy nghĩ & phân tích..."}</span>
            {elapsedSeconds > 0 && <span className="step-timer-badge">{elapsedSeconds}s</span>}
          </div>
        </div>
      )}

      {/* Gợi ý thông minh (Smart Hint) khi đang chờ xử lý */}
      {isPending && hint && (
        <div className="radar-steps-hint-row">
          <span className="hint-icon">💡</span>
          <span className="hint-text">{hint}</span>
        </div>
      )}
    </div>
  );
}
