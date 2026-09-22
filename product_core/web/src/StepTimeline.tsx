import { useState } from "react";
import type { AnswerStep, AnswerTurn } from "./AnswerView";

interface Props {
  steps?: AnswerStep[];
  stage?: string;
  elapsedSeconds?: number;
  hint?: string;
  isPending?: boolean;
  compact?: boolean;
  durationMs?: number;
  turn?: AnswerTurn<any>;
}

/**
 * Khôi phục danh sách các bước thực hiện một cách đầy đủ và logic:
 * - Nếu đã có danh sách steps (>1 bước) từ luồng stream hoặc DB: giữ nguyên.
 * - Nếu tin nhắn cũ trong DB chưa lưu steps hoặc chỉ có 1 bước: tự động tái tạo
 *   chuỗi các bước thực tế (Hiểu yêu cầu -> Quét kho theo tiêu chí -> Chọn lọc hồ sơ -> Viết câu trả lời)
 *   dựa trên trace và plan của lượt hỏi, không bao giờ để hiển thị cụt 1/1 bước.
 */
function resolveDisplaySteps(
  rawSteps: AnswerStep[] | undefined,
  turn: AnswerTurn<any> | undefined,
  isPending: boolean,
  durationMs: number
): AnswerStep[] {
  if (rawSteps && rawSteps.length > 1) {
    return rawSteps;
  }
  if (rawSteps && rawSteps.length === 1 && isPending) {
    return rawSteps;
  }
  if (!isPending && (durationMs > 0 || turn?.text || turn?.trace)) {
    const trace = (turn?.trace as Record<string, any>) || {};
    const plan = (trace.plan as Record<string, any>) || {};
    const coverage = (trace.answer_coverage as Record<string, any>) || {};
    const generated: AnswerStep[] = [
      { label: "Hiểu yêu cầu", state: "done" },
    ];

    const isProspect = Boolean(
      plan.shape && ["find_prospects", "portfolio", "whitespace"].includes(plan.shape)
    ) || Boolean(
      turn?.people?.[0] && ("priority_score" in turn.people[0] || "action" in turn.people[0])
    );
    const unit = isProspect ? "khách hàng" : "hồ sơ";
    const readStep = isProspect ? "Đọc sâu & đối chiếu hồ sơ khách hàng" : "Đọc hồ sơ";
    const searchPrefix = isProspect ? "Tìm trong kho khách hàng" : "Tìm trong kho";

    const mustHave = Array.isArray(plan.must_have) ? plan.must_have.filter(Boolean) : [];
    const queries = Array.isArray(plan.search_queries) ? plan.search_queries.filter(Boolean) : [];
    const criteria = mustHave.slice(0, 3).join(", ") || queries.slice(0, 2).join(", ");
    generated.push({
      label: criteria ? `${searchPrefix} (tiêu chí: ${criteria})` : searchPrefix,
      state: "done",
    });

    const judged = Number(coverage.judged || (turn?.people?.length ?? 0) || 0);
    const candidateTotal = Number(coverage.candidate_total || 0);
    if (judged > 0 && candidateTotal > judged) {
      generated.push({
        label: `Đã chọn lọc ${judged} ${unit} tối ưu từ ${candidateTotal} ${unit} đã quét để đọc sâu`,
        state: "done",
      });
      generated.push({ label: readStep, state: "done" });
    } else if (judged > 0) {
      generated.push({
        label: `Đã chọn lọc ${judged} ${unit} phù hợp nhất để đọc sâu`,
        state: "done",
      });
      generated.push({ label: readStep, state: "done" });
    }

    generated.push({ label: "Viết câu trả lời", state: "done" });
    return generated;
  }
  return rawSteps || [];
}

/**
 * Khối hiển thị Tiến trình & Các bước thực thi của Radar AI:
 * - Hợp nhất toàn bộ Bước (Steps), Đếm giây (Timer), và Trạng thái (Stage) vào một thẻ duy nhất.
 * - Tránh lặp lại tên bước nhiều lần trên cùng một khung chat.
 * - Khi đang xử lý: Hiển thị danh sách bước kèm đếm giây chạy liên tục và gợi ý thông minh.
 * - Khi bước trước xong mà bước sau đang chuẩn bị (hoặc chạy ngầm): Tự động hiển thị bước chuyển tiếp kèm spinner và đếm giây, không bao giờ để đơ.
 * - Khi hoàn tất: Hiển thị "Hoàn tất trong xx giây" ngay dưới bước "✓ Viết câu trả lời".
 */
function formatStepLabel(label: string, isDone: boolean): string {
  if (!isDone) return label;
  if (label.startsWith("Đang thực hiện ")) {
    return "Đã thực hiện " + label.slice("Đang thực hiện ".length);
  }
  if (label === "Đang thực hiện yêu cầu") {
    return "Đã thực hiện yêu cầu";
  }
  if (label.startsWith("Đang ")) {
    return "Đã " + label.slice("Đang ".length);
  }
  return label;
}

export default function StepTimeline({
  steps: rawSteps = [],
  stage,
  elapsedSeconds = 0,
  hint,
  isPending = false,
  compact: _compact = false,
  durationMs = 0,
  turn,
}: Props) {
  // Người dùng có thể chủ động bấm "Chi tiết ▾" hoặc "Thu gọn ▲"
  // Mặc định: khi đang xử lý (isPending) -> mở rộng; sau khi có câu trả lời (!isPending) -> tự động thu gọn
  const [userExpanded, setUserExpanded] = useState<boolean | null>(null);

  const isExpanded = userExpanded !== null ? userExpanded : isPending;

  const steps = resolveDisplaySteps(rawSteps, turn, isPending, durationMs);
  const totalCount = steps.length;
  const effectiveTotal = totalCount || (!isPending && durationMs > 0 ? 1 : 0);
  const doneCount = isPending
    ? steps.filter((s) => s.state === "done").length
    : (totalCount || (!isPending && durationMs > 0 ? 1 : 0));
  const hasActiveStep = steps.some((s) => s.state === "active");

  // Nếu không có bước nào và không pending và không có duration thì không hiển thị
  if (!totalCount && !isPending && !stage && !durationMs) return null;

  // Trạng thái thu gọn (sau khi có câu trả lời hoặc khi người dùng bấm thu gọn)
  if (!isExpanded && (totalCount > 0 || durationMs > 0)) {
    return (
      <div className="radar-steps-compact-bar">
        <button
          type="button"
          className="radar-steps-compact-btn"
          onClick={() => setUserExpanded(true)}
          title="Xem chi tiết các bước xử lý của AI"
        >
          {isPending ? (
            <span className="step-spinner-icon" />
          ) : (
            <span className="radar-steps-compact-icon">✓</span>
          )}
          <span className="radar-steps-compact-text">
            {isPending ? "Đang xử lý" : "Quá trình xử lý"} ({doneCount}/{effectiveTotal || 1} bước)
            {!isPending && durationMs > 0 ? (
              <> · <span className="radar-steps-time">Hoàn tất trong {(durationMs / 1000).toFixed(1)} giây</span></>
            ) : isPending && elapsedSeconds > 0 ? (
              <> · <span className="radar-steps-time">{elapsedSeconds}s</span></>
            ) : null}
          </span>
          <span className="radar-steps-compact-chevron">Chi tiết ▾</span>
        </button>
      </div>
    );
  }

  return (
    <div className={`radar-steps-card ${isPending ? "is-pending" : "is-done"}`}>
      {/* Header thanh lịch với tổng số bước, bộ đếm giây luôn chạy, và nút thu gọn */}
      <div className="radar-steps-card-header">
        <div className="radar-steps-header-left">
          {isPending ? (
            <span className="step-spinner-icon" />
          ) : (
            <span className="radar-steps-done-badge">✓</span>
          )}
          <span className="radar-steps-card-title">
            {isPending ? "Đang xử lý yêu cầu" : "Quá trình xử lý"} ({doneCount}/{effectiveTotal || 1} bước)
          </span>
        </div>
        <div className="radar-steps-header-right">
          {isPending && elapsedSeconds > 0 ? (
            <span className="step-timer-badge timer-ticking">
              ⏱ {elapsedSeconds}s
            </span>
          ) : !isPending && durationMs > 0 ? (
            <span className="step-timer-badge timer-static">
              ⏱ {(durationMs / 1000).toFixed(1)}s
            </span>
          ) : null}
          {(totalCount > 0 || durationMs > 0) && (
            <button
              type="button"
              className="radar-steps-toggle-btn"
              onClick={() => setUserExpanded(false)}
              title="Thu gọn danh sách bước"
            >
              Thu gọn ▲
            </button>
          )}
        </div>
      </div>

      {/* Danh sách các bước chi tiết */}
      {totalCount > 0 ? (
        <ol className="radar-steps-list">
          {steps.map((step, i) => {
            const isStepActive = step.state === "active" && isPending;
            const isStepDone = step.state === "done" || (step.state === "active" && !isPending);
            const hasVietCauTraLoi = steps.some((s) => s.label === "Viết câu trả lời");
            const isTargetStep =
              step.label === "Viết câu trả lời" || (!hasVietCauTraLoi && i === steps.length - 1);

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
                  <div className="radar-step-title-row">
                    <span className="radar-step-name">{formatStepLabel(step.label, isStepDone)}</span>
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
                  {isTargetStep && !isPending && durationMs > 0 && (
                    <div className="radar-step-finish-duration">
                      Hoàn tất trong {(durationMs / 1000).toFixed(1)} giây
                    </div>
                  )}
                </div>
              </li>
            );
          })}

          {/* Khi server đang xử lý giữa các bước (chưa có step active mới): hiển thị bước chuyển tiếp với spinner và timer liên tục */}
          {isPending && !hasActiveStep && (
            <li className="radar-step-item step-active step-transitioning">
              <div className="radar-step-icon-wrap" aria-hidden="true">
                <span className="step-spinner-icon" />
              </div>
              <div className="radar-step-content">
                <div className="radar-step-title-row">
                  <span className="radar-step-name">
                    {stage && !steps.some((s) => s.label === stage)
                      ? stage
                      : "Đang phân tích & xử lý tiếp..."}
                  </span>
                  <span className="radar-step-active-meta">
                    {elapsedSeconds > 0 && <span className="step-timer-badge">{elapsedSeconds}s</span>}
                    <span className="step-typing-pulse">
                      <span className="pulse-dot" />
                      <span className="pulse-dot" />
                      <span className="pulse-dot" />
                    </span>
                  </span>
                </div>
              </div>
            </li>
          )}
        </ol>
      ) : (
        !isPending && durationMs > 0 ? (
          <ol className="radar-steps-list">
            <li className="radar-step-item step-done">
              <div className="radar-step-icon-wrap" aria-hidden="true">
                <span className="step-check-icon">✓</span>
              </div>
              <div className="radar-step-content">
                <div className="radar-step-title-row">
                  <span className="radar-step-name">Viết câu trả lời</span>
                </div>
                <div className="radar-step-finish-duration">
                  Hoàn tất trong {(durationMs / 1000).toFixed(1)} giây
                </div>
              </div>
            </li>
          </ol>
        ) : (
          /* Khi chưa kịp sinh danh sách bước, hiển thị thanh chờ đơn giản kèm spinner & đếm giây */
          <div className="radar-step-single-pending">
            <div className="step-spinner-icon" />
            <div className="radar-step-content">
              <span className="radar-step-name">{stage || "Radar đang suy nghĩ & phân tích..."}</span>
              {elapsedSeconds > 0 && <span className="step-timer-badge">{elapsedSeconds}s</span>}
            </div>
          </div>
        )
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

