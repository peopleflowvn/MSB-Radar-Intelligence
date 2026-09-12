import { createContext, Dispatch, ReactNode, SetStateAction, useCallback, useContext, useEffect, useState } from "react";
import { api, AssistantConversation, ProspectResponse, SearchFilters } from "./api";
import { AnswerTurn } from "./AnswerView";

// Giữ nguyên kết quả tìm kiếm AI (Talent lẫn RB "tìm khách bằng AI") khi
// điều hướng sang trang khác trong ứng dụng rồi quay lại.
//
// Trước đây state nằm trong chính component (AiSearch.tsx, ProspectSearch.tsx),
// mà hai component đó chỉ được render có điều kiện bên trong route /talent và
// /rb — bấm vào một hồ sơ tìm được (điều hướng sang /person/:id) làm React
// Router gỡ bỏ toàn bộ cây route cũ, xoá sạch state cục bộ; bấm "quay lại"
// thì component dựng lại từ đầu, mất trắng kết quả vừa tìm.
//
// Sửa bằng cách đặt state ở NGOÀI <Routes> (xem main.tsx) — sống suốt phiên
// làm việc, không theo route. Cố ý KHÔNG lưu xuống sessionStorage: tệp đính
// kèm (File) trong tin nhắn Talent AI Search không tuần tự hoá được, và giữ
// trong bộ nhớ JS là đủ cho đúng nhu cầu — mất khi tải lại cả trang là điều
// người dùng đã quen với mọi ứng dụng web, khác hẳn với mất khi chỉ bấm
// "quay lại" trong cùng một phiên.

export interface AiChatMessage {
  id: string;
  sender: "user" | "ai";
  text: string;
  timestamp: string;
  /** Một lượt của Answer Engine — câu trả lời, trích dẫn, người được nhắc. */
  answer?: AnswerTurn;
  isPending?: boolean;
  attachments?: Array<Pick<File, "name" | "size">>;
  /** Khoá lượt — để lấy lại kết quả nếu mobile rớt kết nối giữa chừng. */
  clientTurnId?: string;
  /** Mốc bắt đầu để thẻ chờ hiển thị thời gian thật. */
  startedAt?: number;
}

export interface ActiveTalentTurn {
  threadId: string;
  clientTurnId: string;
  query: string;
  startedAt: number;
}

export interface TalentFilterHistoryEntry {
  id: string;
  filters: SearchFilters;
  createdAt: number;
}

interface TalentFilterState {
  draft: SearchFilters;
  setDraft: Dispatch<SetStateAction<SearchFilters>>;
  applied: SearchFilters;
  setApplied: Dispatch<SetStateAction<SearchFilters>>;
  hasSearched: boolean;
  setHasSearched: Dispatch<SetStateAction<boolean>>;
  showAdvanced: boolean;
  setShowAdvanced: Dispatch<SetStateAction<boolean>>;
  viewMode: "cards" | "table";
  setViewMode: Dispatch<SetStateAction<"cards" | "table">>;
  page: number;
  setPage: Dispatch<SetStateAction<number>>;
  scrollY: number;
  setScrollY: Dispatch<SetStateAction<number>>;
  history: TalentFilterHistoryEntry[];
  rememberFilter: (filters: SearchFilters) => void;
  clearHistory: () => void;
}

const EMPTY_FILTER: SearchFilters = { order: "relevance" };
const FILTER_STATE_KEY = "msb-radar-talent-filter-state-v1";
const TalentFilterContext = createContext<TalentFilterState | null>(null);

function readFilterState() {
  try {
    const parsed = JSON.parse(localStorage.getItem(FILTER_STATE_KEY) || "{}") as Partial<{
      draft: SearchFilters; applied: SearchFilters; hasSearched: boolean;
      showAdvanced: boolean; viewMode: "cards" | "table"; page: number;
      scrollY: number; history: TalentFilterHistoryEntry[];
    }>;
    return {
      draft: parsed.draft ?? EMPTY_FILTER,
      applied: parsed.applied ?? EMPTY_FILTER,
      hasSearched: Boolean(parsed.hasSearched),
      showAdvanced: Boolean(parsed.showAdvanced),
      viewMode: parsed.viewMode === "table" ? "table" as const : "cards" as const,
      page: Math.max(0, Number(parsed.page) || 0),
      scrollY: Math.max(0, Number(parsed.scrollY) || 0),
      history: Array.isArray(parsed.history) ? parsed.history.slice(0, 12) : [],
    };
  } catch {
    return { draft: EMPTY_FILTER, applied: EMPTY_FILTER, hasSearched: false,
      showAdvanced: false, viewMode: "cards" as const, page: 0, scrollY: 0,
      history: [] as TalentFilterHistoryEntry[] };
  }
}

function TalentFilterProvider({ children }: { children: ReactNode }) {
  const initial = useState(readFilterState)[0];
  const [draft, setDraft] = useState<SearchFilters>(initial.draft);
  const [applied, setApplied] = useState<SearchFilters>(initial.applied);
  const [hasSearched, setHasSearched] = useState(initial.hasSearched);
  const [showAdvanced, setShowAdvanced] = useState(initial.showAdvanced);
  const [viewMode, setViewMode] = useState<"cards" | "table">(initial.viewMode);
  const [page, setPage] = useState(initial.page);
  const [scrollY, setScrollY] = useState(initial.scrollY);
  const [history, setHistory] = useState<TalentFilterHistoryEntry[]>(initial.history);

  useEffect(() => {
    try {
      localStorage.setItem(FILTER_STATE_KEY, JSON.stringify({ draft, applied,
        hasSearched, showAdvanced, viewMode, page, scrollY, history }));
    } catch {
      // Trình duyệt có thể chặn storage; state trong provider vẫn hoạt động.
    }
  }, [draft, applied, hasSearched, showAdvanced, viewMode, page, scrollY, history]);

  const rememberFilter = useCallback((filters: SearchFilters) => {
    const normalized = Object.fromEntries(Object.entries(filters).filter(([, value]) =>
      value !== "" && value !== false && value !== undefined && value !== null,
    )) as SearchFilters;
    if (Object.keys(normalized).every((key) => key === "order")) return;
    const signature = JSON.stringify(normalized);
    setHistory((current) => [{ id: `${Date.now()}`, filters: normalized, createdAt: Date.now() },
      ...current.filter((row) => JSON.stringify(row.filters) !== signature)].slice(0, 12));
  }, []);
  const clearHistory = useCallback(() => setHistory([]), []);

  return <TalentFilterContext.Provider value={{ draft, setDraft, applied, setApplied,
    hasSearched, setHasSearched, showAdvanced, setShowAdvanced, viewMode, setViewMode,
    page, setPage, scrollY, setScrollY, history, rememberFilter, clearHistory }}>
    {children}
  </TalentFilterContext.Provider>;
}

export function useTalentFilterState(): TalentFilterState {
  const ctx = useContext(TalentFilterContext);
  if (!ctx) throw new Error("useTalentFilterState phải nằm trong SearchStateProvider");
  return ctx;
}

interface AiChatState {
  messages: AiChatMessage[];
  setMessages: Dispatch<SetStateAction<AiChatMessage[]>>;
  threadId: string;
  resetConversation: () => void;
  conversations: AssistantConversation[];
  selectConversation: (id: string) => Promise<void>;
  archiveConversation: (id: string) => Promise<void>;
  renameConversation: (id: string, title: string) => Promise<void>;
  refreshConversations: () => Promise<void>;
  activeTurn: ActiveTalentTurn | null;
  setActiveTurn: (turn: ActiveTalentTurn | null) => void;
}

const AiChatContext = createContext<AiChatState | null>(null);

function AiChatProvider({ children }: { children: ReactNode }) {
  const [messages, setMessages] = useState<AiChatMessage[]>([]);
  const [threadId, setThreadId] = useState(() => makeThreadId("talent"));
  const [conversations, setConversations] = useState<AssistantConversation[]>([]);
  const [activeTurnState, setActiveTurnState] = useState<ActiveTalentTurn | null>(() => {
    try {
      const raw = sessionStorage.getItem("msb-radar-talent-active-turn");
      return raw ? JSON.parse(raw) as ActiveTalentTurn : null;
    } catch {
      return null;
    }
  });
  const setActiveTurn = useCallback((turn: ActiveTalentTurn | null) => {
    setActiveTurnState(turn);
    if (turn) sessionStorage.setItem("msb-radar-talent-active-turn", JSON.stringify(turn));
    else sessionStorage.removeItem("msb-radar-talent-active-turn");
  }, []);
  const refreshConversations = useCallback(async () => {
    const data = await api.conversations("talent");
    setConversations(data.results);
  }, []);
  useEffect(() => { refreshConversations().catch(() => undefined); }, [refreshConversations]);
  const selectConversation = async (id: string) => {
    try {
      const row = await api.conversation(id, "talent");
      setThreadId(storeThreadId("talent", id));
      setMessages((row.messages ?? []).filter((m) => m.role !== "system").map((m) => ({
        id: `saved-${m.id}`, sender: m.role === "user" ? "user" : "ai", text: m.content,
        timestamp: new Date(m.created_at).toLocaleTimeString("vi-VN", { hour: "2-digit", minute: "2-digit" }),
        attachments: (m.metadata?.attachments as Array<Pick<File, "name" | "size">>) ?? [],
        // Lượt do AI/Answer Engine ghi: dựng lại trích dẫn để mở hội thoại cũ vẫn
        // bấm được vào nguồn, không chỉ còn trơ mỗi đoạn văn.
        answer: (m.role === "assistant" || m.metadata?.answer_engine) ? {
          text: m.content,
          sources: (m.metadata?.cv_citations as AnswerTurn["sources"]) ?? [],
          people: (m.metadata?.people as any) ?? [],
          reasoning: (m.metadata?.reasoning_trace as string) || (m.metadata?.thinking_trace as string) || undefined,
          provider: m.provider,
          model: m.model,
        } : undefined,
      })));
    } catch {
      // Fallback khi không tải được
    }
  };
  const archiveConversation = async (id: string) => {
    await api.conversationUpdate(id, { archived: true, surface: "talent" });
    if (id === threadId) resetConversation();
    await refreshConversations();
  };
  const renameConversation = async (id: string, title: string) => {
    await api.conversationUpdate(id, { title, surface: "talent" });
    await refreshConversations();
  };
  const resetConversation = () => {
    setMessages([]);
    setActiveTurn(null);
    setThreadId(resetThreadId("talent"));
  };
  return <AiChatContext.Provider value={{ messages, setMessages, threadId, resetConversation,
    conversations, selectConversation, archiveConversation, renameConversation, refreshConversations,
    activeTurn: activeTurnState, setActiveTurn }}>{children}</AiChatContext.Provider>;
}

export function useAiChatState(): AiChatState {
  const ctx = useContext(AiChatContext);
  if (!ctx) throw new Error("useAiChatState phải nằm trong SearchStateProvider (xem main.tsx)");
  return ctx;
}

// RB "Hỏi & Tìm khách hàng với AI" từng chỉ giữ MỘT câu hỏi/MỘT câu trả lời
// (ghi đè mỗi lần hỏi), không có hội thoại tích luỹ như Talent AiSearch —
// khác hẳn cách mọi chatbot AI khác hoạt động. Đổi sang danh sách tin nhắn
// giống hệt AiChatMessage để: (1) nhiều lượt hỏi/đáp cùng hiện trong một luồng
// chat, (2) mỗi lượt AI trả lời giữ `data.criteria` — dùng làm "lịch sử" gửi
// kèm câu hỏi tiếp theo để AI hỏi tiếp (refine) thay vì hỏi độc lập.
export interface ProspectChatMessage {
  id: string;
  sender: "user" | "ai";
  text: string;
  timestamp: string;
  data?: ProspectResponse;
  isPending?: boolean;
}

interface ProspectChatState {
  messages: ProspectChatMessage[];
  setMessages: Dispatch<SetStateAction<ProspectChatMessage[]>>;
  threadId: string;
  resetConversation: () => void;
  conversations: AssistantConversation[];
  selectConversation: (id: string) => Promise<void>;
  archiveConversation: (id: string) => Promise<void>;
  renameConversation: (id: string, title: string) => Promise<void>;
  refreshConversations: () => Promise<void>;
}

const ProspectChatContext = createContext<ProspectChatState | null>(null);

function ProspectChatProvider({ children }: { children: ReactNode }) {
  const [messages, setMessages] = useState<ProspectChatMessage[]>([]);
  const [threadId, setThreadId] = useState(() => makeThreadId("prospect"));
  const [conversations, setConversations] = useState<AssistantConversation[]>([]);
  const refreshConversations = useCallback(async () => {
    const data = await api.conversations("prospect");
    setConversations(data.results);
  }, []);
  useEffect(() => { refreshConversations().catch(() => undefined); }, [refreshConversations]);
  const selectConversation = async (id: string) => {
    try {
      const row = await api.conversation(id, "prospect");
      setThreadId(storeThreadId("prospect", id));
      setMessages((row.messages ?? []).filter((m) => m.role !== "system").map((m) => ({
        id: `saved-${m.id}`, sender: m.role === "user" ? "user" : "ai", text: m.content,
        timestamp: new Date(m.created_at).toLocaleTimeString("vi-VN", { hour: "2-digit", minute: "2-digit" }),
        data: m.metadata ? {
          mode: (m.metadata.mode as "search" | "conversation") || "conversation",
          criteria: (m.metadata.criteria as any) || {},
          criteria_from: "keyword" as const,
          question: "",
          error: "",
          count: typeof m.metadata.count === "number" ? m.metadata.count : 0,
          results: [],
          provider: m.provider,
          model: m.model,
          reasoning_content: (m.metadata.reasoning_content as string) || (m.metadata.thinking_trace as string) || undefined,
        } : undefined,
      })));
    } catch {
      // Fallback khi không tải được
    }
  };
  const archiveConversation = async (id: string) => {
    await api.conversationUpdate(id, { archived: true, surface: "prospect" });
    if (id === threadId) resetConversation();
    await refreshConversations();
  };
  const renameConversation = async (id: string, title: string) => {
    await api.conversationUpdate(id, { title, surface: "prospect" });
    await refreshConversations();
  };
  const resetConversation = () => {
    setMessages([]);
    setThreadId(resetThreadId("prospect"));
  };
  return (
    <ProspectChatContext.Provider value={{ messages, setMessages, threadId, resetConversation,
      conversations, selectConversation, archiveConversation, renameConversation, refreshConversations }}>
      {children}
    </ProspectChatContext.Provider>
  );
}

function newThreadId() {
  return globalThis.crypto?.randomUUID?.() ?? `thread-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

function makeThreadId(surface: string) {
  const key = `msb-radar-${surface}-thread`;
  const existing = sessionStorage.getItem(key);
  if (existing) return existing;
  const created = newThreadId();
  sessionStorage.setItem(key, created);
  return created;
}

function resetThreadId(surface: string) {
  const key = `msb-radar-${surface}-thread`;
  const created = newThreadId();
  sessionStorage.setItem(key, created);
  return created;
}

function storeThreadId(surface: string, id: string) {
  sessionStorage.setItem(`msb-radar-${surface}-thread`, id);
  return id;
}

export function useProspectChatState(): ProspectChatState {
  const ctx = useContext(ProspectChatContext);
  if (!ctx) throw new Error("useProspectChatState phải nằm trong SearchStateProvider (xem main.tsx)");
  return ctx;
}

export function SearchStateProvider({ children }: { children: ReactNode }) {
  return (
    <AiChatProvider>
      <ProspectChatProvider>
        <TalentFilterProvider>{children}</TalentFilterProvider>
      </ProspectChatProvider>
    </AiChatProvider>
  );
}
