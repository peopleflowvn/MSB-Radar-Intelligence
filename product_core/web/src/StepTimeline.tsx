import type { AnswerStep } from "./AnswerView";

/**
 * Danh sách BƯỚC Radar đang/đã làm, tick dần.
 *
 * Thay cho khối "Quá trình suy nghĩ & lập luận" tự bung: người dùng nói không
 * cần thấy token suy nghĩ của model, chỉ cần biết đang ở bước nào để đỡ sốt
 * ruột khi chờ.
 *
 * - `compact`: khi câu trả lời đã bắt đầu chảy — thu lại còn một dòng gọn.
 */
export default function StepTimeline({
  steps,
  compact = false,
}: {
  steps: AnswerStep[];
  compact?: boolean;
}) {
  if (!steps.length) return null;

  if (compact) {
    const done = steps.filter((s) => s.state === "done").length;
    return (
      <div className="radar-steps radar-steps-compact">
        <span className="radar-steps-check">✓</span>
        <span className="radar-steps-summary">
          Đã qua {done}/{steps.length} bước
        </span>
      </div>
    );
  }

  return (
    <ol className="radar-steps">
      {steps.map((step, i) => (
        <li key={`${step.label}-${i}`} className={`radar-step radar-step-${step.state}`}>
          <span className="radar-step-marker" aria-hidden="true">
            {step.state === "done" ? "✓" : <span className="radar-step-spinner" />}
          </span>
          <span className="radar-step-label">{step.label}</span>
        </li>
      ))}
    </ol>
  );
}
