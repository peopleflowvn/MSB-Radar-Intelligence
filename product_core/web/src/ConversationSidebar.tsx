import { useState } from "react";
import { AssistantConversation } from "./api";

interface Props {
  activeId: string;
  conversations: AssistantConversation[];
  onNew: () => void;
  onSelect: (id: string) => void;
  onArchive: (id: string) => void;
  onRename: (id: string, title: string) => void;
  collapsed?: boolean;
  onToggleCollapse?: () => void;
}

export default function ConversationSidebar({
  activeId,
  conversations,
  onNew,
  onSelect,
  onArchive,
  onRename,
  collapsed = false,
  onToggleCollapse,
}: Props) {
  const [search, setSearch] = useState("");

  const filtered = conversations.filter((c) => {
    if (!search.trim()) return true;
    return (c.title || "").toLowerCase().includes(search.toLowerCase().trim());
  });

  const formatTime = (iso?: string) => {
    if (!iso) return "";
    const date = new Date(iso);
    const now = new Date();
    const isToday =
      date.getDate() === now.getDate() &&
      date.getMonth() === now.getMonth() &&
      date.getFullYear() === now.getFullYear();

    if (isToday) {
      return `Hôm nay, ${date.toLocaleTimeString("vi-VN", { hour: "2-digit", minute: "2-digit" })}`;
    }
    return date.toLocaleDateString("vi-VN", { day: "2-digit", month: "2-digit" });
  };

  // Trạng thái thu gọn (Collapsed View)
  if (collapsed) {
    return (
      <aside className="radar-conversation-sidebar collapsed" aria-label="Lịch sử trò chuyện">
        <button
          type="button"
          className="radar-sidebar-collapse-btn"
          onClick={onToggleCollapse}
          title="Mở rộng lịch sử trò chuyện"
          aria-label="Mở rộng lịch sử trò chuyện"
        >
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <rect x="3" y="3" width="18" height="18" rx="2" ry="2" />
            <line x1="9" y1="3" x2="9" y2="21" />
            <path d="m14 9 3 3-3 3" />
          </svg>
        </button>

        <button
          type="button"
          className="radar-conversation-new-mini"
          onClick={onNew}
          title="Cuộc trò chuyện mới"
          aria-label="Cuộc trò chuyện mới"
        >
          <span>＋</span>
        </button>

        <div className="radar-collapsed-history-count" title={`${conversations.length} cuộc hội thoại`}>
          <span>💬</span>
          <span className="count-badge">{conversations.length}</span>
        </div>
      </aside>
    );
  }

  // Trạng thái mở rộng (Expanded View)
  return (
    <aside className="radar-conversation-sidebar" aria-label="Lịch sử trò chuyện">
      {/* Header với nút thu gọn */}
      <div className="radar-sidebar-header">
        <div className="radar-sidebar-title-wrap">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
          </svg>
          <span className="radar-sidebar-title">Lịch sử trò chuyện</span>
          <span className="radar-history-badge">{conversations.length}</span>
        </div>

        {onToggleCollapse && (
          <button
            type="button"
            className="radar-sidebar-collapse-btn"
            onClick={onToggleCollapse}
            title="Thu gọn menu lịch sử"
            aria-label="Thu gọn menu lịch sử"
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <rect x="3" y="3" width="18" height="18" rx="2" ry="2" />
              <line x1="9" y1="3" x2="9" y2="21" />
              <path d="m16 15-3-3 3-3" />
            </svg>
          </button>
        )}
      </div>

      {/* Nút tạo cuộc trò chuyện mới */}
      <button type="button" className="radar-conversation-new" onClick={onNew}>
        <span className="plus-icon">＋</span>
        <span>Cuộc trò chuyện mới</span>
      </button>

      {/* Ô tìm kiếm nhanh nếu có từ 3 hội thoại trở lên */}
      {conversations.length >= 3 && (
        <div className="radar-sidebar-search-box">
          <input
            type="text"
            className="radar-sidebar-search-input"
            placeholder="Tìm cuộc hội thoại..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
          {search && (
            <button
              type="button"
              className="radar-sidebar-search-clear"
              onClick={() => setSearch("")}
              aria-label="Xóa tìm kiếm"
            >
              ×
            </button>
          )}
        </div>
      )}

      <div className="radar-conversation-heading">
        <span>GẦN ĐÂY</span>
      </div>

      {/* Danh sách các cuộc trò chuyện */}
      <div className="radar-conversation-list">
        {filtered.length === 0 && (
          <div className="radar-conversation-empty">
            {search.trim() ? "Không tìm thấy hội thoại phù hợp." : "Chưa có cuộc trò chuyện đã lưu."}
          </div>
        )}
        {filtered.map((row) => {
          const isActive = row.conversation_id === activeId;
          return (
            <div
              className={`radar-conversation-row ${isActive ? "active" : ""}`}
              key={row.conversation_id}
            >
              <button
                type="button"
                className="radar-conversation-title"
                onClick={() => onSelect(row.conversation_id)}
                title={row.title || "Cuộc trò chuyện mới"}
              >
                <span className="title-text">{row.title || "Cuộc trò chuyện mới"}</span>
                <small className="time-text">
                  {formatTime(row.last_message_at || row.updated_at)}
                </small>
              </button>

              <div className="radar-conversation-actions">
                <button
                  type="button"
                  className="radar-conv-action-btn edit"
                  title="Đổi tên"
                  aria-label={`Đổi tên ${row.title}`}
                  onClick={(e) => {
                    e.stopPropagation();
                    const title = window.prompt("Nhập tên mới cho cuộc trò chuyện:", row.title);
                    if (title?.trim()) onRename(row.conversation_id, title.trim());
                  }}
                >
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M17 3a2.828 2.828 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5L17 3z" />
                  </svg>
                </button>
                <button
                  type="button"
                  className="radar-conv-action-btn delete"
                  title="Lưu trữ / Xoá"
                  aria-label={`Lưu trữ ${row.title}`}
                  onClick={(e) => {
                    e.stopPropagation();
                    onArchive(row.conversation_id);
                  }}
                >
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <polyline points="3 6 5 6 21 6" />
                    <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
                  </svg>
                </button>
              </div>
            </div>
          );
        })}
      </div>
    </aside>
  );
}
