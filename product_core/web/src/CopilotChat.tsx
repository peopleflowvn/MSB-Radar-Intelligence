import React, { Dispatch, ReactNode, SetStateAction, useEffect, useRef, useState } from "react";
import { AnswerStreamEvent, ApiError, HistoryTurn, TalentTurnResult } from "./api";
import { useCustomTheme } from "./CustomThemeContext";
import { ActiveTalentTurn } from "./searchPersistence";
import { AnswerTurn } from "./AnswerView";

const ACCEPTED_FILES = ".pdf,.docx,.xlsx,.pptx,.txt,.md,.csv,.json,.png,.jpg,.jpeg,.webp";
const MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024;

/**
 * "Cỗ máy" chat AI dùng CHUNG cho Talent Radar (`AiSearch`) và Growth Radar
 * (`ProspectSearch`, chế độ "Hỏi bằng lời"): khung chào mừng, gợi ý mẫu, dòng
 * hội thoại, thanh nhập liệu, dừng/tiếp tục, phục hồi lượt khi rớt mạng.
 *
 * Hai trang chỉ khác nhau ở NỘI DUNG theo domain — được tiêm vào qua props
 * (`ask`/`askTurn` gọi engine nào, có đính kèm tệp hay không, và
 * `renderAnswerBody` vẽ phần thân câu trả lời: Talent hiện trích dẫn CV,
 * Growth Radar hiện thẻ khách hàng + điểm ưu tiên).
 */

export interface CopilotMessage<TPerson> {
  id: string;
  sender: "user" | "ai";
  text: string;
  timestamp: string;
  answer?: AnswerTurn<TPerson>;
  isPending?: boolean;
  attachments?: Array<Pick<File, "name" | "size">>;
  clientTurnId?: string;
  startedAt?: number;
}

export interface CopilotChatState<TPerson> {
  messages: CopilotMessage<TPerson>[];
  setMessages: Dispatch<SetStateAction<CopilotMessage<TPerson>[]>>;
  threadId: string;
  resetConversation: () => void;
  refreshConversations: () => Promise<void>;
  activeTurn: ActiveTalentTurn | null;
  setActiveTurn: (turn: ActiveTalentTurn | null) => void;
}

export interface QuickPrompt {
  icon: string;
  title: string;
  text: string;
}

function waitingHint(seconds: number) {
  if (seconds >= 20) return "Yêu cầu này cần đọc nhiều bằng chứng hơn bình thường. Radar vẫn đang làm.";
  if (seconds >= 8) return "Radar vẫn đang xử lý và sẽ tự cập nhật khi có kết quả.";
  return "Bạn có thể chuyển tab, Radar vẫn tiếp tục xử lý.";
}

export { waitingHint };

interface CopilotChatProps<TPerson> {
  chatState: CopilotChatState<TPerson>;
  ask: (
    body: { q: string; conversation_id?: string; client_turn_id?: string; history?: HistoryTurn[]; files?: File[] },
    signal?: AbortSignal,
  ) => AsyncGenerator<AnswerStreamEvent>;
  askTurn: (clientTurnId: string) => Promise<TalentTurnResult>;
  supportsFiles?: boolean;
  heroTitle: ReactNode;
  heroSubtitle: string;
  heroPlaceholder: string;
  barPlaceholder: string;
  submitLabel: string;
  /** title/aria-label của nút gửi trong khung chào mừng — mặc định dùng `submitLabel`. */
  heroSubmitAriaLabel?: string;
  /** title/aria-label của nút gửi (chỉ icon) trong thanh nhập liệu dưới cùng. */
  barSubmitAriaLabel: string;
  quickPrompts: QuickPrompt[];
  quickPromptIconStyle?: React.CSSProperties;
  /** Vẽ phần thân câu trả lời của MỘT tin nhắn AI (StepTimeline + AnswerView
   *  + phần riêng theo domain). Nhận `elapsedSeconds` đã tính sẵn cho thẻ chờ
   *  và `sendFollowUp` để gắn vào `AnswerView`'s `onFollowUp` (gợi ý câu hỏi
   *  tiếp theo). */
  renderAnswerBody: (
    msg: CopilotMessage<TPerson>,
    index: number,
    messages: CopilotMessage<TPerson>[],
    elapsedSeconds: number,
    sendFollowUp: (query: string) => void,
  ) => ReactNode;
}

/** Lấy lại kết quả một lượt khi stream đứt (mobile treo tab, mất mạng chớp
 *  nhoáng). Máy chủ vẫn chạy engine tới hết và lưu bản đầy đủ — ta thăm dò tới
 *  hết deadline máy chủ. Trả kết quả nếu lấy được, `null` nếu lượt đã lỗi/hết hạn. */
async function recoverTurn<TPerson>(
  askTurn: (clientTurnId: string) => Promise<TalentTurnResult>,
  clientTurnId: string,
  startedAt = Date.now(),
): Promise<AnswerTurn<TPerson> & { durationMs: number } | null> {
  // Máy chủ cho một lượt tối đa 150 giây. Poll tới sau deadline đó để việc đổi
  // tab/app không biến thành lỗi giả chỉ vì cơ chế nối lại cũ dừng sau ~60 giây.
  const now = Date.now();
  const deadline = Math.max(now + 10_000, Math.min(startedAt + 170_000, now + 170_000));
  let unknown = 0;
  while (Date.now() < deadline) {
    try {
      const r = await askTurn(clientTurnId);
      if (r.state === "done" && r.answer) {
        return {
          text: r.answer,
          sources: r.citations ?? [],
          people: (r.people as unknown as TPerson[]) ?? [],
          provider: r.provider,
          model: r.model,
          trace: r.trace,
          durationMs: Number(r.duration_ms ?? r.trace?.ms_total ?? 0),
        };
      }
    } catch (err) {
      // Một khoảng đệm ngắn cho race lúc runner vừa khởi động. Nếu server đã
      // xác nhận không biết lượt này thì không bắt người dùng chờ cả phút.
      const missing = (err instanceof ApiError && err.status === 404)
        || String((err as Error)?.message || "").includes("404");
      if (missing && ++unknown >= 5) return null;
      if (err instanceof ApiError && [401, 403, 500, 504].includes(err.status)) return null;
    }
    await new Promise((res) => setTimeout(res, 2_000));
  }
  return null;
}

export default function CopilotChat<TPerson>({
  chatState, ask, askTurn, supportsFiles = false,
  heroTitle, heroSubtitle, heroPlaceholder, barPlaceholder, submitLabel,
  heroSubmitAriaLabel, barSubmitAriaLabel,
  quickPrompts, quickPromptIconStyle, renderAnswerBody,
}: CopilotChatProps<TPerson>) {
  const { appName, radarAvatarUrl, radarAvatarEmoji } = useCustomTheme();
  const { messages, setMessages, threadId, resetConversation, refreshConversations, activeTurn, setActiveTurn } = chatState;
  const [inputText, setInputText] = useState("");
  const [attachedFiles, setAttachedFiles] = useState<File[]>([]);
  const [attachmentError, setAttachmentError] = useState("");
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const streamAbortRef = useRef<AbortController | null>(null);
  const messagesRef = useRef(messages);
  const recoveringRef = useRef(new Set<string>());

  const lastMsgRef = useRef<HTMLDivElement>(null);
  const [asking, setAsking] = useState(false);
  const [now, setNow] = useState(Date.now());
  const [showScrollBottom, setShowScrollBottom] = useState(false);
  const [isDraggingOver, setIsDraggingOver] = useState(false);

  const handleDragOver = (e: React.DragEvent) => {
    if (!supportsFiles) return;
    e.preventDefault();
    e.stopPropagation();
    if (!isDraggingOver) setIsDraggingOver(true);
  };

  const handleDragLeave = (e: React.DragEvent) => {
    if (!supportsFiles) return;
    e.preventDefault();
    e.stopPropagation();
    if (!e.currentTarget.contains(e.relatedTarget as Node)) {
      setIsDraggingOver(false);
    }
  };

  const handleDrop = (e: React.DragEvent) => {
    if (!supportsFiles) return;
    e.preventDefault();
    e.stopPropagation();
    setIsDraggingOver(false);
    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      handleFiles(e.dataTransfer.files);
    }
  };

  useEffect(() => { messagesRef.current = messages; }, [messages]);

  const handleStopGenerating = () => {
    if (streamAbortRef.current) {
      streamAbortRef.current.abort();
    }
    setAsking(false);
    setActiveTurn(null);
    setMessages((prev) =>
      prev.map((m) => (m.isPending ? { ...m, isPending: false } : m))
    );
  };

  useEffect(() => {
    const handleScroll = () => {
      const scrollHeight = document.documentElement.scrollHeight || document.body.scrollHeight;
      const scrollTop = window.scrollY || document.documentElement.scrollTop;
      const clientHeight = window.innerHeight;
      const distanceFromBottom = scrollHeight - (scrollTop + clientHeight);
      setShowScrollBottom(distanceFromBottom > 140);
    };
    window.addEventListener("scroll", handleScroll, { passive: true });
    return () => window.removeEventListener("scroll", handleScroll);
  }, []);

  useEffect(() => {
    const onNewChat = () => resetConversation();
    window.addEventListener("radar:new-chat", onNewChat);
    return () => window.removeEventListener("radar:new-chat", onNewChat);
  }, [resetConversation]);

  // Chuyển tab chỉ làm mất kênh hiển thị, không phải lệnh hủy tác vụ. Khi tab
  // hiện lại, hỏi snapshot máy chủ; tuyệt đối không abort stream vì visibility.
  useEffect(() => {
    const onVisibility = () => {
      if (document.visibilityState === "visible") {
        const stuck = messagesRef.current.find(
          (m) => m.sender === "ai" && m.isPending && m.clientTurnId,
        );
        if (!stuck || recoveringRef.current.has(stuck.clientTurnId!)) return;
        recoveringRef.current.add(stuck.clientTurnId!);
        void recoverTurn<TPerson>(askTurn, stuck.clientTurnId!, stuck.startedAt)
          .then((recovered) => {
            if (!recovered) return;
            setMessages((cur) =>
              cur.map((m) =>
                m.id === stuck.id
                  ? { ...m, isPending: false, text: recovered.text, answer: recovered }
                  : m,
              ),
            );
            setActiveTurn(null);
            setAsking(false);
            void refreshConversations();
          })
          .finally(() => recoveringRef.current.delete(stuck.clientTurnId!));
      }
    };
    document.addEventListener("visibilitychange", onVisibility);
    return () => document.removeEventListener("visibilitychange", onVisibility);
  }, [setMessages, setActiveTurn, askTurn, refreshConversations]);

  // Dựng lại lượt đang chạy sau reload hoặc khi quay lại route. Mã lượt nằm
  // trong sessionStorage qua provider, còn kết quả là nguồn sự thật ở server.
  useEffect(() => {
    if (!activeTurn || activeTurn.threadId !== threadId
        || messages.some((m) => m.clientTurnId === activeTurn.clientTurnId)) return;
    const timestamp = new Date(activeTurn.startedAt).toLocaleTimeString("vi-VN", {
      hour: "2-digit", minute: "2-digit",
    });
    const pendingId = `recovered-${activeTurn.clientTurnId}`;
    setMessages((prev) => [...prev,
      { id: `recovered-user-${activeTurn.clientTurnId}`, sender: "user",
        text: activeTurn.query, timestamp },
      { id: pendingId, sender: "ai", text: "", timestamp, isPending: true,
        clientTurnId: activeTurn.clientTurnId, startedAt: activeTurn.startedAt,
        answer: { text: "", sources: [], people: [],
          stage: "Đang nối lại với lượt đang xử lý…" } },
    ]);
    setAsking(true);
    void recoverTurn<TPerson>(askTurn, activeTurn.clientTurnId, activeTurn.startedAt).then((result) => {
      if (result) {
        setMessages((prev) => prev.map((m) => m.id === pendingId
          ? { ...m, isPending: false, text: result.text, answer: result } : m));
        setActiveTurn(null);
        void refreshConversations();
      } else {
        setMessages((prev) => prev.map((m) => m.id === pendingId
          ? { ...m, isPending: false, text: "Không thể nối lại lượt xử lý. Bạn có thể thử lại.",
              answer: { ...(m.answer ?? { sources: [], people: [] }), text: "Không thể nối lại lượt xử lý. Bạn có thể thử lại.", stage: undefined } }
          : m));
        setActiveTurn(null);
      }
      setAsking(false);
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeTurn, threadId]);

  useEffect(() => {
    if (!messages.some((m) => m.isPending)) return;
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [messages]);

  // Auto-cuộn: chỉ neo ĐẦU lượt trả lời lên đầu khung, MỘT lần khi lượt bắt đầu.
  const anchoredId = useRef("");
  useEffect(() => {
    const last = messages[messages.length - 1];
    if (!last || anchoredId.current === last.id) return;
    anchoredId.current = last.id;
    lastMsgRef.current?.scrollIntoView?.({ behavior: "smooth", block: "start" });
  }, [messages]);

  const handleSendMessage = (textToSend?: string, filesOverride?: File[]) => {
    const files = supportsFiles ? (filesOverride ?? attachedFiles) : [];
    const enteredText = (textToSend ?? inputText).trim();
    const query = enteredText || (files.length ? "Phân tích tài liệu đính kèm để tìm người phù hợp" : "");
    if (!query || asking) return;
    setAsking(true);

    // Lịch sử để hỏi tiếp bám được ngữ cảnh ("2 người đầu", "so sánh họ").
    const history: HistoryTurn[] = messages.reduce<HistoryTurn[]>((turns, message, index) => {
      if (message.sender !== "ai" || message.isPending || !message.text) return turns;
      const previous = messages[index - 1];
      turns.push({
        criteria: {},
        question: previous?.sender === "user" ? previous.text : "",
        answer: message.text,
      });
      return turns;
    }, []).slice(-12);

    // Một khoá cho cả lượt (kể cả lượt sâu nối tiếp) — retry không tạo message trùng.
    const clientTurnId = globalThis.crypto?.randomUUID?.() ?? `turn-${Date.now()}`;
    const userMsgId = `user-${Date.now()}`;
    const aiMsgId = `ai-${Date.now() + 1}`;
    const timeStr = new Date().toLocaleTimeString("vi-VN", {
      hour: "2-digit",
      minute: "2-digit",
    });
    const startedAt = Date.now();

    const userMsg: CopilotMessage<TPerson> = {
      id: userMsgId,
      sender: "user",
      text: query,
      timestamp: timeStr,
      attachments: files,
    };

    const aiPendingMsg: CopilotMessage<TPerson> = {
      id: aiMsgId,
      sender: "ai",
      text: "",
      timestamp: timeStr,
      isPending: true,
      attachments: files,
      clientTurnId,
      startedAt,
      answer: { text: "", sources: [], people: [], stage: "Đang tiếp nhận yêu cầu…" },
    };

    setMessages((prev) => [...prev, userMsg, aiPendingMsg]);
    setInputText("");
    setAttachedFiles([]);
    setAttachmentError("");
    setActiveTurn({ threadId, clientTurnId, query, startedAt });
    if (fileInputRef.current) fileInputRef.current.value = "";

    const patchMsg = (patch: Partial<CopilotMessage<TPerson>>) =>
      setMessages((prev) => prev.map((m) => (m.id === aiMsgId ? { ...m, ...patch } : m)));

    // Đường trả lời DUY NHẤT. Máy chủ tự hiểu câu hỏi và trả lời có dẫn chứng —
    // không còn nhánh rẽ engine khác khi lỗi (giống hệt Talent): lỗi giữa/trước
    // khi có chữ đều thử `askTurn` trước khi báo lỗi.
    const runAsk = async () => {
      const controller = new AbortController();
      streamAbortRef.current = controller;
      const turn: AnswerTurn<TPerson> = { text: "", sources: [], people: [] };
      const push = (patch: Partial<AnswerTurn<TPerson>>) => {
        Object.assign(turn, patch);
        patchMsg({ text: turn.text || aiPendingMsg.text, answer: { ...turn } });
      };
      const closedSteps = () =>
        (turn.steps ?? []).map((s) => (s.state === "done" ? s : { ...s, state: "done" as const }));
      try {
        for await (const ev of ask(
          { q: query, conversation_id: threadId, client_turn_id: clientTurnId, history, files },
          controller.signal,
        )) {
          if (ev.event === "preamble") {
            // Ngoài `text` (hiện trong khối "Kế hoạch tìm kiếm & xử lý"), một số
            // domain (Growth Radar) gửi kèm dữ liệu riêng (VD: `plan`) — chuyển
            // tiếp NGUYÊN VẸN vào `trace` để phần vẽ theo domain đọc được ngay,
            // trước cả khi có `done`. Vô hại với domain không dùng tới.
            const { text, ...extra } = ev.data;
            push({
              preamble: String(text ?? ""),
              trace: Object.keys(extra).length ? { ...(turn.trace ?? {}), ...extra } : turn.trace,
            });
          } else if (ev.event === "step") {
            const label = String(ev.data.label ?? "");
            const state = (ev.data.state === "done" ? "done" : "active") as "active" | "done";
            const steps = [...(turn.steps ?? [])];
            const at = steps.findIndex((s) => s.label === label);
            if (at >= 0) steps[at] = { label, state };
            else {
              steps.forEach((s, i) => { if (s.state === "active") steps[i] = { ...s, state: "done" }; });
              steps.push({ label, state });
            }
            push({ steps, stage: label });
          } else if (ev.event === "stage") {
            push({ stage: String(ev.data.text ?? "") });
          } else if (ev.event === "thinking") {
            // Máy chủ không còn gửi 'thinking' cho luồng này; giữ nhánh để tương
            // thích ngược, nhưng KHÔNG hiện ra người dùng.
          } else if (ev.event === "answer") {
            push({ text: turn.text + String(ev.data.text ?? "") });
          } else if (ev.event === "revision") {
            // `ok: false` là máy chủ đã BỎ CUỘC (câu xin lỗi/văn bản tất định),
            // không phải bản đã sửa đúng — không gắn banner "đã tự sửa" cho nó,
            // kẻo người đọc hiểu ngược thành "Radar vừa sửa xong, đúng rồi".
            push({ text: String(ev.data.text ?? ""), revised: ev.data.ok !== false });
          } else if (ev.event === "citations") {
            push({ sources: (ev.data.items as AnswerTurn<TPerson>["sources"]) ?? [] });
          } else if (ev.event === "error") {
            throw new ApiError(0, String(ev.data.text ?? "Lỗi khi stream câu trả lời."));
          } else if (ev.event === "done") {
            const finalText = String(ev.data.answer ?? turn.text) || turn.text;
            Object.assign(turn, {
              text: finalText,
              stage: undefined,
              steps: closedSteps(),
              sources: (ev.data.citations as AnswerTurn<TPerson>["sources"]) ?? turn.sources,
              webSources: (ev.data.web_sources as AnswerTurn<TPerson>["webSources"]) ?? [],
              people: (ev.data.people as TPerson[]) ?? [],
              provider: String(ev.data.provider ?? ""),
              model: String(ev.data.model ?? ""),
              // Hợp nhất chứ không THAY: nếu `done` không nhắc lại một khoá đã
              // có từ `preamble` (VD: `plan` khi vòng nới không đổi kế hoạch),
              // giữ nguyên giá trị cũ thay vì để mất.
              trace: { ...(turn.trace ?? {}), ...(ev.data.trace as Record<string, unknown> ?? {}) },
              durationMs: Number(ev.data.duration_ms ??
                (ev.data.trace as Record<string, unknown> | undefined)?.ms_total ?? 0),
            });
            patchMsg({ isPending: false, text: finalText, answer: { ...turn } });
            setActiveTurn(null);
            void refreshConversations();
          }
        }
      } catch (err: any) {
        const userStopped = err?.name === "AbortError" || streamAbortRef.current?.signal?.aborted;
        if (userStopped) {
          turn.text = turn.text ? `${turn.text}\n\n*(Đã dừng trả lời)*` : `*(Đã dừng)*`;
          turn.stage = undefined;
          turn.steps = closedSteps();
          patchMsg({ isPending: false, text: turn.text, answer: { ...turn } });
          setActiveTurn(null);
        } else {
          // Stream đứt/treo — nhưng máy chủ vẫn chạy engine tới hết. Thử lấy
          // lại kết quả trước khi kết luận hỏng. GIỮ phần chữ đã nhận trên màn hình.
          turn.stage = "Kết nối gián đoạn — đang lấy lại kết quả…";
          patchMsg({ answer: { ...turn } });
          const recovered = await recoverTurn<TPerson>(askTurn, clientTurnId, startedAt);
          if (recovered) {
            Object.assign(turn, recovered, { stage: undefined, steps: closedSteps() });
            patchMsg({ isPending: false, text: recovered.text, answer: { ...turn } });
            setActiveTurn(null);
            void refreshConversations();
          } else {
            const detail = err instanceof ApiError ? err.message : "Mất kết nối khi đang trả lời.";
            turn.text = turn.text ? `${turn.text}\n\n⚠️ ${detail}` : `⚠️ Đã có lỗi xảy ra: ${detail}`;
            turn.stage = undefined;
            turn.steps = closedSteps();
            patchMsg({ isPending: false, text: turn.text, answer: { ...turn } });
            setActiveTurn(null);
          }
        }
      } finally {
        streamAbortRef.current = null;
        setAsking(false);
      }
    };

    void runAsk();
  };

  const sendFollowUp = (query: string) => handleSendMessage(query);

  const handleFiles = (selected: FileList | File[] | null) => {
    if (!supportsFiles || !selected) return;
    const incoming = Array.from(selected);
    const tooLarge = incoming.find((file) => file.size > MAX_ATTACHMENT_BYTES);
    if (tooLarge) {
      setAttachmentError(`${tooLarge.name} vượt quá giới hạn 10 MB.`);
      return;
    }
    setAttachedFiles((current) => {
      const unique = [...current];
      incoming.forEach((file) => {
        if (!unique.some((item) => item.name === file.name && item.size === file.size)) unique.push(file);
      });
      if (unique.length > 5) {
        setAttachmentError("Chỉ được đính kèm tối đa 5 tệp.");
        return unique.slice(0, 5);
      }
      setAttachmentError("");
      return unique;
    });
  };

  const handlePaste = (e: React.ClipboardEvent) => {
    if (!supportsFiles) return;
    const clipboardData = e.clipboardData;
    if (!clipboardData) return;

    const filesToAttach: File[] = [];
    const items = clipboardData.items;
    if (items) {
      for (let i = 0; i < items.length; i++) {
        const item = items[i];
        if (item.type.startsWith("image/")) {
          const blob = item.getAsFile();
          if (blob) {
            const ext = item.type === "image/jpeg" ? "jpg" : item.type.split("/")[1] || "png";
            const nowStr = new Date().toISOString().replace(/[-:T]/g, "").slice(0, 14);
            const filename = blob.name && blob.name !== "image.png"
              ? blob.name
              : `anh-chup-${nowStr}.${ext}`;
            const file = new File([blob], filename, { type: item.type });
            filesToAttach.push(file);
          }
        }
      }
    }

    if (filesToAttach.length === 0 && clipboardData.files && clipboardData.files.length > 0) {
      for (let i = 0; i < clipboardData.files.length; i++) {
        filesToAttach.push(clipboardData.files[i]);
      }
    }

    if (filesToAttach.length > 0) {
      const hasText = Array.from(items || []).some((it) => it.type === "text/plain");
      if (!hasText) {
        e.preventDefault();
      }
      handleFiles(filesToAttach);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSendMessage();
    }
  };

  return (
    <div
      className={`copilot-chat-container ${isDraggingOver ? "is-dragover" : ""}`}
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
      onPaste={handlePaste}
    >
      {isDraggingOver && (
        <div className="copilot-drag-overlay" aria-hidden="true">
          <div className="copilot-drag-box">
            <span className="drag-icon">📄</span>
            <strong className="drag-title">Thả tệp JD hoặc CV vào đây</strong>
            <span className="drag-desc">Radar sẽ tự động đọc nội dung để phân tích và tìm kiếm ứng viên</span>
          </div>
        </div>
      )}

      <div className="radar-conversation-content full-width">
      {messages.length === 0 ? (
        <div className="copilot-welcome-hero">
          <div className="copilot-hero-heading-block">
            <h2 className="copilot-hero-title">{heroTitle}</h2>
            <p className="copilot-hero-subtitle">{heroSubtitle}</p>
          </div>

          <div className="hero-command-card">
            {supportsFiles && attachedFiles.length > 0 && (
              <div className="copilot-attachment-tray" style={{ marginBottom: "10px" }}>
                {attachedFiles.map((file, index) => (
                  <span className="copilot-file-chip" key={`${file.name}-${file.size}`}>
                    📄 {file.name}
                    <button type="button" aria-label={`Bỏ tệp ${file.name}`} onClick={() => setAttachedFiles((files) => files.filter((_, i) => i !== index))}>×</button>
                  </span>
                ))}
              </div>
            )}

            <div className="hero-input-main-row">
              <textarea
                rows={2}
                className="hero-command-textarea"
                placeholder={heroPlaceholder}
                value={inputText}
                onChange={(e) => setInputText(e.target.value)}
                onKeyDown={handleKeyDown}
                onPaste={handlePaste}
                disabled={asking}
              />
            </div>

            <div className="hero-command-actions-row">
              <div className="hero-actions-left">
                {supportsFiles && (
                  <>
                    <input
                      ref={fileInputRef}
                      type="file"
                      multiple
                      accept={ACCEPTED_FILES}
                      className="visually-hidden"
                      onChange={(event) => handleFiles(event.target.files)}
                    />
                    <button
                      type="button"
                      className="hero-attach-pill-btn"
                      onClick={() => fileInputRef.current?.click()}
                      disabled={asking}
                      title="Đính kèm tài liệu"
                      aria-label="Đính kèm tài liệu"
                    >
                      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                        <path d="m21.4 11.6-8.9 8.9a6 6 0 0 1-8.5-8.5l9.6-9.6a4 4 0 0 1 5.7 5.7l-9.6 9.6a2 2 0 1 1-2.8-2.8l8.9-8.9" />
                      </svg>
                      <span>Đính kèm JD / CV</span>
                    </button>
                    <span className="hero-shortcut-hint">
                      💡 <strong>Enter</strong> để gửi · <strong>Shift+Enter</strong> xuống dòng · Có thể dán ảnh (<strong>Ctrl+V</strong>) hoặc kéo thả tệp
                    </span>
                  </>
                )}
                {!supportsFiles && (
                  <span className="hero-shortcut-hint">
                    💡 <strong>Enter</strong> để gửi · <strong>Shift+Enter</strong> xuống dòng
                  </span>
                )}
              </div>

              <div className="hero-actions-right">
                {asking ? (
                  <button
                    type="button"
                    className="copilot-stop-btn"
                    onClick={handleStopGenerating}
                    title="Dừng câu trả lời của AI"
                    aria-label="Dừng câu trả lời"
                  >
                    <span className="stop-icon">⏹</span>
                    <span>Dừng trả lời</span>
                  </button>
                ) : (
                  <button
                    type="button"
                    className="hero-submit-btn"
                    onClick={() => handleSendMessage()}
                    disabled={!inputText.trim() && attachedFiles.length === 0}
                    title={heroSubmitAriaLabel ?? submitLabel}
                    aria-label={heroSubmitAriaLabel ?? submitLabel}
                  >
                    <span>✨</span>
                    <span>{submitLabel}</span>
                  </button>
                )}
              </div>
            </div>

            {attachmentError && <div className="copilot-attachment-error" style={{ marginTop: "8px" }}>{attachmentError}</div>}
          </div>

          <div className="hero-quick-prompts-section">
            <div className="quick-prompts-label-bar">
              <span>💡 GỢI Ý TÌM NHANH THEO MẪU:</span>
            </div>
            <div className="hero-quick-prompts-grid">
              {quickPrompts.map((item) => (
                <button
                  key={item.text}
                  type="button"
                  className="hero-quick-prompt-card"
                  onClick={() => handleSendMessage(item.text)}
                >
                  <div className="prompt-card-icon-box" style={quickPromptIconStyle}>
                    <span>{item.icon}</span>
                  </div>
                  <div className="prompt-card-text-col">
                    <strong className="prompt-card-heading">{item.title}</strong>
                    <span className="prompt-card-desc">{item.text}</span>
                  </div>
                </button>
              ))}
            </div>
          </div>
        </div>
      ) : (
        <>
          <div className="copilot-stream-header">
            <div className="stream-header-left">
              <span className="stream-header-title">💬 Hội thoại với Radar AI</span>
              <span className="stream-header-badge">
                {messages.filter((m) => m.sender === "user").length} câu hỏi
              </span>
            </div>
            <button
              type="button"
              className="copilot-new-chat-top-btn"
              onClick={resetConversation}
              title="Bắt đầu đoạn chat mới"
            >
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                <line x1="12" y1="5" x2="12" y2="19" />
                <line x1="5" y1="12" x2="19" y2="12" />
              </svg>
              <span>Bắt đầu chat mới</span>
            </button>
          </div>

          <div className="copilot-chat-stream">
            {messages.map((msg, mi) => {
              const elapsedSeconds = Math.max(0, Math.floor((now - (msg.startedAt ?? now)) / 1000));
              const fallbackTag = (msg.answer?.trace?.compose as { fallback?: boolean } | undefined)?.fallback;
              return (
                <div key={msg.id}
                  ref={mi === messages.length - 1 ? lastMsgRef : undefined}
                  className={`chat-message-row ${msg.sender}`}
                  style={{ scrollMarginTop: "12px" }}>
                  <div className={`chat-avatar ${msg.sender === "ai" ? "radar-bot-avatar" : ""}`}>
                    {msg.sender === "user" ? (
                      "👤"
                    ) : radarAvatarUrl ? (
                      <img src={radarAvatarUrl} alt={appName} className="bot-avatar-img" />
                    ) : (
                      <span>{radarAvatarEmoji || "⚡"}</span>
                    )}
                  </div>

                  <div className="chat-bubble-wrapper">
                    <div className="chat-bubble-meta">
                      <span className="chat-author">
                        {msg.sender === "user" ? "Bạn" : `${appName} AI`}
                      </span>
                      {msg.sender === "ai" && fallbackTag && (
                        <span className="ai-model-tag">
                          <>⚠️ <code>AI chưa hoàn tất đầy đủ</code></>
                        </span>
                      )}
                      {msg.sender === "ai" && !msg.isPending && !fallbackTag && (msg.answer?.model || msg.answer?.provider) && (
                        <span className="ai-model-tag">
                          🤖 Mô hình: <code>{msg.answer.provider ? `${msg.answer.provider}/${msg.answer.model || "mặc định"}` : msg.answer.model}</code>
                        </span>
                      )}
                      <span className="chat-time">{msg.timestamp}</span>
                    </div>

                    <div className={`chat-bubble ${msg.sender}`}>
                      {msg.sender === "ai" && msg.answer?.preamble ? (
                        <div className="radar-preamble">
                          <div className="radar-preamble-header">
                            <span className="radar-preamble-icon">🎯</span>
                            <span className="radar-preamble-title">Kế hoạch tìm kiếm &amp; xử lý</span>
                          </div>
                          <div className="radar-preamble-text">{msg.answer.preamble}</div>
                        </div>
                      ) : null}

                      {msg.sender === "ai"
                        ? renderAnswerBody(msg, mi, messages, elapsedSeconds, sendFollowUp)
                        : msg.text && <p className="chat-paragraph">{msg.text}</p>}

                      {msg.sender === "user" && msg.attachments && msg.attachments.length > 0 && (
                        <div className="chat-attachment-list">
                          {msg.attachments.map((file) => <span key={`${file.name}-${file.size}`}>📎 {file.name}</span>)}
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              );
            })}
            <div ref={messagesEndRef} />
          </div>

          <div className="copilot-input-bar-wrapper">
            {supportsFiles && attachedFiles.length > 0 && (
              <div className="copilot-attachment-tray">
                {attachedFiles.map((file, index) => (
                  <span className="copilot-file-chip" key={`${file.name}-${file.size}`}>
                    📄 {file.name}
                    <button type="button" aria-label={`Bỏ tệp ${file.name}`} onClick={() => setAttachedFiles((files) => files.filter((_, i) => i !== index))}>×</button>
                  </span>
                ))}
              </div>
            )}
            <div className="copilot-input-box">
              {supportsFiles && (
                <>
                  <input
                    ref={fileInputRef}
                    type="file"
                    multiple
                    accept={ACCEPTED_FILES}
                    className="visually-hidden"
                    onChange={(event) => handleFiles(event.target.files)}
                  />
                  <button
                    type="button"
                    className="copilot-attach-btn"
                    onClick={() => fileInputRef.current?.click()}
                    disabled={asking}
                    title="Đính kèm tài liệu"
                    aria-label="Đính kèm tài liệu"
                  >
                    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                      <path d="m21.4 11.6-8.9 8.9a6 6 0 0 1-8.5-8.5l9.6-9.6a4 4 0 0 1 5.7 5.7l-9.6 9.6a2 2 0 1 1-2.8-2.8l8.9-8.9" />
                    </svg>
                  </button>
                </>
              )}
              <textarea
                rows={1}
                className="copilot-textarea"
                placeholder={barPlaceholder}
                value={inputText}
                onChange={(e) => {
                  setInputText(e.target.value);
                  e.target.style.height = "auto";
                  e.target.style.height = `${Math.min(e.target.scrollHeight, 120)}px`;
                }}
                onKeyDown={handleKeyDown}
                onPaste={handlePaste}
                disabled={asking}
              />
              {asking ? (
                <button
                  type="button"
                  className="copilot-stop-btn"
                  onClick={handleStopGenerating}
                  title="Dừng câu trả lời của AI"
                  aria-label="Dừng câu trả lời"
                >
                  <span className="stop-icon">⏹</span>
                  <span>Dừng</span>
                </button>
              ) : (
                <button
                  type="button"
                  className="copilot-send-btn"
                  onClick={() => handleSendMessage()}
                  disabled={(!inputText.trim() && attachedFiles.length === 0) || asking}
                  title={barSubmitAriaLabel}
                  aria-label={barSubmitAriaLabel}
                >
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                    <line x1="12" y1="19" x2="12" y2="5" />
                    <polyline points="5 12 12 5 19 12" />
                  </svg>
                </button>
              )}
            </div>
            {showScrollBottom && (
              <button
                type="button"
                className="copilot-scroll-bottom-btn"
                onClick={() => messagesEndRef.current?.scrollIntoView({ behavior: "smooth" })}
                title="Cuộn xuống tin nhắn mới nhất"
                aria-label="Cuộn xuống dưới cùng"
              >
                <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M12 5v14M5 12l7 7 7-7" />
                </svg>
                <span>Xuống dưới cùng</span>
              </button>
            )}
            {attachmentError && <div className="copilot-attachment-error">{attachmentError}</div>}
            <div className="copilot-footer-hint">
              <span>
                Radar AI có thể đưa ra thông tin chưa chính xác. Vui lòng kiểm tra lại các nội dung quan trọng.
              </span>
              <button
                type="button"
                className="link small"
                onClick={resetConversation}
                style={{ marginLeft: "10px", whiteSpace: "nowrap" }}
              >
                🔄 Bắt đầu đoạn chat mới
              </button>
            </div>
          </div>
        </>
      )}
      </div>
    </div>
  );
}
