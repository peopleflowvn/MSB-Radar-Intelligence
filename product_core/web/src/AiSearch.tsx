import { api, AnswerPerson } from "./api";
import { useAiChatState } from "./searchPersistence";
import AnswerView from "./AnswerView";
import StepTimeline from "./StepTimeline";
import CopilotChat, { waitingHint } from "./CopilotChat";

const GOI_Y = [
  {
    icon: "🎯",
    title: "Senior Data Analyst HN",
    text: "Tìm Senior Data Analyst ở Hà Nội biết SQL và Python, trên 3 năm kinh nghiệm",
  },
  {
    icon: "👔",
    title: "Sourcing Specialist IT",
    text: "Tìm chuyên viên tuyển dụng IT / Sourcing Specialist có kinh nghiệm trên 2 năm",
  },
  {
    icon: "🏦",
    title: "Chuyên viên Ngân hàng",
    text: "Tìm chuyên viên Khách hàng ưu tiên (Priority Banking) hoặc Quản lý Tín dụng có kinh nghiệm",
  },
  {
    icon: "💻",
    title: "Tech Lead & Kỹ sư Phần mềm",
    text: "Tìm Tech Lead hoặc Senior Backend Java / Golang có kinh nghiệm phát triển hệ thống tài chính",
  },
];

/**
 * Trợ lý Tuyển Dụng &amp; Săn Nhân Tài (Talent Radar) — lớp mỏng bọc
 * `CopilotChat` (cỗ máy chat AI dùng chung với Growth Radar), chỉ khai báo
 * phần riêng của Talent: đính kèm JD/CV, gợi ý mẫu, và cách vẽ câu trả lời
 * (trích dẫn CV + chip người qua `AnswerView`).
 */
export default function AiSearch() {
  const chatState = useAiChatState();

  return (
    <CopilotChat<AnswerPerson>
      chatState={chatState}
      ask={api.talentAsk}
      askTurn={api.talentAskTurn}
      supportsFiles
      heroTitle={
        <>
          Trợ lý Tuyển Dụng &amp; Săn Nhân Tài{" "}
          <span className="hero-gradient-text">Talent Radar</span>
        </>
      }
      heroSubtitle="Hỗ trợ Recruiter &amp; Talent Acquisition tìm kiếm ứng viên mục tiêu qua mô tả tự nhiên hoặc tải lên bản mô tả công việc (JD)."
      heroPlaceholder="Mô tả người cần tìm, dán ảnh chụp (Ctrl+V) hoặc kéo thả JD/CV vào đây…"
      barPlaceholder="Mô tả người cần tìm, dán ảnh chụp (Ctrl+V) hoặc tải lên JD…"
      submitLabel="Tìm kiếm với AI"
      heroSubmitAriaLabel="Gửi yêu cầu phân tích"
      barSubmitAriaLabel="Gửi yêu cầu phân tích"
      quickPrompts={GOI_Y}
      renderAnswerBody={(msg, mi, messages, elapsedSeconds, sendFollowUp) => (
        <>
          {(msg.isPending || (msg.answer?.steps?.length ?? 0) > 0 || (msg.answer?.durationMs ?? Number(msg.answer?.trace?.ms_total ?? 0)) > 0) ? (
            <StepTimeline
              steps={msg.answer?.steps}
              stage={msg.answer?.stage}
              elapsedSeconds={elapsedSeconds}
              hint={waitingHint(elapsedSeconds)}
              isPending={msg.isPending}
              compact={!!msg.text}
              durationMs={msg.answer?.durationMs ?? Number(msg.answer?.trace?.ms_total ?? 0)}
            />
          ) : null}

          {msg.answer ? (
            <AnswerView
              turn={msg.answer}
              isPending={msg.isPending}
              question={messages[mi - 1]?.sender === "user" ? messages[mi - 1].text : undefined}
              conversationId={chatState.threadId}
              onFollowUp={sendFollowUp}
            />
          ) : (
            msg.text && <p className="chat-paragraph">{msg.text}</p>
          )}
        </>
      )}
    />
  );
}
