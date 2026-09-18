import { createContext, Dispatch, ReactNode, SetStateAction, useCallback, useContext, useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, AssistantConversation, ProspectAnswerPerson, SearchFilters } from "./api";
import { AnswerTurn } from "./AnswerView";

// SearchStateProvider được mount NGOÀI <App/> (xem main.tsx) nên không bị
// unmount khi App chuyển qua lại giữa màn hình Login và giao diện chính —
// state (hội thoại, danh sách lịch sử) sống sót qua một lượt đăng xuất/đăng
// nhập trên CÙNG tab. Trên máy dùng chung (nhiều chuyên viên tuyển dụng dùng
// chung máy), nếu không dọn state này thì người đăng nhập sau sẽ thấy ngay
// lịch sử chat của người trước. Hook này theo dõi danh tính đang đăng nhập
// (dùng chung cache react-query với session query trong App.tsx qua cùng
// queryKey ['me']) để các provider bên dưới tự xoá state khi danh tính đổi.
function useAuthUsername(): string | null | undefined {
  const { data, isSuccess } = useQuery({ queryKey: ["me"], queryFn: api.me, retry: false });
  // undefined = session query chưa có kết quả lần nào (đang tải/lỗi mạng) —
  // KHÔNG được coi là "đăng xuất", nếu không mọi lần tải lại trang sẽ bị
  // hiểu nhầm thành đổi danh tính và xoá nhầm hội thoại đang có.
  if (!isSuccess) return undefined;
  return data.authenticated ? data.username : null;
}

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
      scrollY: 0,
      history: Array.isArray(parsed.history) ? parsed.history.slice(0, 12) : [],
    };
  } catch {
    return { draft: EMPTY_FILTER, applied: EMPTY_FILTER, hasSearched: false,
      showAdvanced: false, viewMode: "cards" as const, page: 0, scrollY: 0,
      history: [] as TalentFilterHistoryEntry[] };
  }
}

function TalentFilterProvider({ children }: { children: ReactNode }) {
  const username = useAuthUsername();
  const initial = useState(readFilterState)[0];
  const [draft, setDraft] = useState<SearchFilters>(initial.draft);
  const [applied, setApplied] = useState<SearchFilters>(initial.applied);
  const [hasSearched, setHasSearched] = useState(initial.hasSearched);
  const [showAdvanced, setShowAdvanced] = useState(initial.showAdvanced);
  const [viewMode, setViewMode] = useState<"cards" | "table">(initial.viewMode);
  const [page, setPage] = useState(initial.page);
  const [scrollY, setScrollY] = useState(initial.scrollY);
  const [history, setHistory] = useState<TalentFilterHistoryEntry[]>(initial.history);

  const prevUsernameRef = useRef<string | null | undefined>(undefined);
  useEffect(() => {
    const prev = prevUsernameRef.current;
    prevUsernameRef.current = username;
    // Bỏ qua lần đầu (session query còn đang tải) — không phải đổi danh tính thật.
    if (prev === undefined || prev === username) return;
    // Đổi danh tính (đăng xuất/đăng nhập tài khoản khác) trên cùng máy —
    // xoá bộ lọc/lịch sử tìm kiếm của người trước, tránh lộ sang người sau.
    setDraft(EMPTY_FILTER);
    setApplied(EMPTY_FILTER);
    setHasSearched(false);
    setShowAdvanced(false);
    setPage(0);
    setScrollY(0);
    setHistory([]);
    try {
      localStorage.removeItem(FILTER_STATE_KEY);
    } catch {
      // ignore
    }
  }, [username]);

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

/**
 * Bộ lọc dùng chung cho phân hệ Tìm kiếm (/search). Một bucket duy nhất cho cả hai
 * góc nhìn: đổi góc nhìn Tuyển dụng ↔ Khách hàng vẫn giữ nguyên tiêu chí đang lọc,
 * chỉ đổi phân hệ đích của các thao tác (đợt tuyển vs cơ hội bán chéo).
 */
export function useSearchFilterState(): TalentFilterState {
  const ctx = useContext(TalentFilterContext);
  if (!ctx) throw new Error("useSearchFilterState phải nằm trong SearchStateProvider");
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
  const username = useAuthUsername();
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
  const prevUsernameRef = useRef<string | null | undefined>(undefined);
  useEffect(() => {
    const prev = prevUsernameRef.current;
    prevUsernameRef.current = username;
    // Bỏ qua lần đầu (session query còn đang tải) — không phải đổi danh tính thật.
    if (prev === undefined || prev === username) return;
    setMessages([]);
    setConversations([]);
    setActiveTurn(null);
    setThreadId(resetThreadId("talent"));
    if (username) refreshConversations().catch(() => undefined);
  }, [username, refreshConversations, setActiveTurn]);
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

// RB "Hỏi & Tìm khách hàng với AI" giờ dùng CHUNG một "cỗ máy" Answer Engine
// với Talent AiSearch (`rbAsk`/`rbAskTurn` cùng khuôn sự kiện SSE với
// `talentAsk`/`talentAskTurn`) — nên giữ y hệt hình dạng `AiChatMessage`/
// `AiChatState`, chỉ khác kiểu "người" trong kết quả (khách hàng có điểm ưu
// tiên thay vì ứng viên có trích dẫn CV).
export interface ProspectChatMessage {
  id: string;
  sender: "user" | "ai";
  text: string;
  timestamp: string;
  /** Một lượt của Growth Answer Engine — câu trả lời, kế hoạch, khách hàng. */
  answer?: AnswerTurn<ProspectAnswerPerson>;
  isPending?: boolean;
  /** Khoá lượt — để lấy lại kết quả nếu mobile rớt kết nối giữa chừng. */
  clientTurnId?: string;
  /** Mốc bắt đầu để thẻ chờ hiển thị thời gian thật. */
  startedAt?: number;
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
  activeTurn: ActiveTalentTurn | null;
  setActiveTurn: (turn: ActiveTalentTurn | null) => void;
}

const ProspectChatContext = createContext<ProspectChatState | null>(null);

function ProspectChatProvider({ children }: { children: ReactNode }) {
  const username = useAuthUsername();
  const [messages, setMessages] = useState<ProspectChatMessage[]>([]);
  const [threadId, setThreadId] = useState(() => makeThreadId("prospect"));
  const [conversations, setConversations] = useState<AssistantConversation[]>([]);
  const [activeTurnState, setActiveTurnState] = useState<ActiveTalentTurn | null>(() => {
    try {
      const raw = sessionStorage.getItem("msb-radar-prospect-active-turn");
      return raw ? JSON.parse(raw) as ActiveTalentTurn : null;
    } catch {
      return null;
    }
  });
  const setActiveTurn = useCallback((turn: ActiveTalentTurn | null) => {
    setActiveTurnState(turn);
    if (turn) sessionStorage.setItem("msb-radar-prospect-active-turn", JSON.stringify(turn));
    else sessionStorage.removeItem("msb-radar-prospect-active-turn");
  }, []);
  const refreshConversations = useCallback(async () => {
    const data = await api.conversations("prospect");
    setConversations(data.results);
  }, []);
  useEffect(() => { refreshConversations().catch(() => undefined); }, [refreshConversations]);
  const prevUsernameRef = useRef<string | null | undefined>(undefined);
  useEffect(() => {
    const prev = prevUsernameRef.current;
    prevUsernameRef.current = username;
    if (prev === undefined || prev === username) return;
    setMessages([]);
    setConversations([]);
    setActiveTurn(null);
    setThreadId(resetThreadId("prospect"));
    if (username) refreshConversations().catch(() => undefined);
  }, [username, refreshConversations, setActiveTurn]);
  const selectConversation = async (id: string) => {
    try {
      const row = await api.conversation(id, "prospect");
      setThreadId(storeThreadId("prospect", id));
      setMessages((row.messages ?? []).filter((m) => m.role !== "system").map((m) => ({
        id: `saved-${m.id}`, sender: m.role === "user" ? "user" : "ai", text: m.content,
        timestamp: new Date(m.created_at).toLocaleTimeString("vi-VN", { hour: "2-digit", minute: "2-digit" }),
        // Lượt do AI/Answer Engine ghi: dựng lại kế hoạch/khách hàng để hội
        // thoại cũ vẫn hiện đúng, không chỉ còn trơ mỗi đoạn văn.
        answer: (m.role === "assistant" || m.metadata?.answer_engine) ? {
          text: m.content,
          sources: [],
          people: (m.metadata?.people as ProspectAnswerPerson[]) ?? [],
          reasoning: (m.metadata?.reasoning_trace as string) || (m.metadata?.thinking_trace as string) || undefined,
          provider: m.provider,
          model: m.model,
          trace: m.metadata?.plan ? { plan: m.metadata.plan } : undefined,
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
    setActiveTurn(null);
    setThreadId(resetThreadId("prospect"));
  };
  return (
    <ProspectChatContext.Provider value={{ messages, setMessages, threadId, resetConversation,
      conversations, selectConversation, archiveConversation, renameConversation, refreshConversations,
      activeTurn: activeTurnState, setActiveTurn }}>
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
