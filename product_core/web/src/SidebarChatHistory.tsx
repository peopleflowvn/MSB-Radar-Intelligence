import React, { useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { useAiChatState, useProspectChatState } from "./searchPersistence";

interface Props {
  collapsed: boolean;
  onExpand: () => void;
  onNavigate?: () => void;
  allowedModules?: Set<string>;
}

// Micro SVG Icons for Sidebar Chat History
function IconChatBubble() {
  return (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
    </svg>
  );
}

function IconPlus() {
  return (
    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
      <line x1="12" y1="5" x2="12" y2="19" />
      <line x1="5" y1="12" x2="19" y2="12" />
    </svg>
  );
}

function IconSearchMini() {
  return (
    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="11" cy="11" r="8" />
      <line x1="21" y1="21" x2="16.65" y2="16.65" />
    </svg>
  );
}

function IconXMini() {
  return (
    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
      <line x1="18" y1="6" x2="6" y2="18" />
      <line x1="6" y1="6" x2="18" y2="18" />
    </svg>
  );
}

function IconPencilMini() {
  return (
    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M17 3a2.828 2.828 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5L17 3z" />
    </svg>
  );
}

function IconTrashMini() {
  return (
    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <polyline points="3 6 5 6 21 6" />
      <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
    </svg>
  );
}

function IconTalentChat() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2" />
      <circle cx="9" cy="7" r="4" />
      <path d="M22 21v-2a4 4 0 0 0-3-3.87" />
      <path d="M16 3.13a4 4 0 0 1 0 7.75" />
    </svg>
  );
}

function IconGrowthChat() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <polyline points="23 6 13.5 15.5 8.5 10.5 1 18" />
      <polyline points="17 6 23 6 23 12" />
    </svg>
  );
}

export default function SidebarChatHistory({ collapsed, onExpand, onNavigate, allowedModules }: Props) {
  const location = useLocation();
  const navigate = useNavigate();

  const aiChat = useAiChatState();
  const prospectChat = useProspectChatState();

  // Đang ở luồng Khách hàng nếu đứng trong Growth Radar, hoặc đang mở góc nhìn
  // Khách hàng của phân hệ Tìm kiếm — nếu chỉ dò "/rb" thì người dùng ở
  // /search?perspective=prospect sẽ bị kéo nhầm sang lịch sử chat Tuyển dụng.
  const isRbRoute = location.pathname.startsWith("/rb")
    || location.search.includes("perspective=prospect");
  const canAccessTalent = !allowedModules || allowedModules.has("talent");
  const canAccessRb = !allowedModules || allowedModules.has("rb");
  const chatRoute = (perspective: "recruiter" | "prospect") =>
    `/search?tab=ai&perspective=${perspective}`;

  // Tab mặc định theo route hiện tại
  const [activeTab, setActiveTab] = useState<"talent" | "prospect">(() => {
    if (isRbRoute && canAccessRb) return "prospect";
    return canAccessTalent ? "talent" : "prospect";
  });

  // Tự động chuyển tab hiển thị tương ứng khi người dùng đổi route
  React.useEffect(() => {
    if (isRbRoute && canAccessRb) {
      setActiveTab("prospect");
    } else if (canAccessTalent) {
      setActiveTab("talent");
    }
  }, [isRbRoute, canAccessRb, canAccessTalent]);

  const [search, setSearch] = useState("");
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editTitle, setEditTitle] = useState("");

  const currentChat = activeTab === "talent" ? aiChat : prospectChat;
  const conversations = currentChat.conversations || [];
  const activeId = currentChat.threadId;

  const filtered = conversations.filter((c) => {
    if (!search.trim()) return true;
    return (c.title || "").toLowerCase().includes(search.toLowerCase().trim());
  });

  const handleSelect = async (id: string) => {
    onNavigate?.();
    if (activeTab === "talent") {
      navigate(chatRoute("recruiter"));
      await aiChat.selectConversation(id);
    } else {
      navigate(chatRoute("prospect"));
      await prospectChat.selectConversation(id);
    }
  };

  const handleNew = () => {
    onNavigate?.();
    if (activeTab === "talent") {
      aiChat.resetConversation();
      navigate(chatRoute("recruiter"));
    } else {
      prospectChat.resetConversation();
      navigate(chatRoute("prospect"));
    }
  };

  const handleStartRename = (id: string, currentTitle: string, e: React.MouseEvent) => {
    e.stopPropagation();
    setEditingId(id);
    setEditTitle(currentTitle || "");
  };

  const handleConfirmRename = async (id: string, e: React.FormEvent | React.FocusEvent) => {
    e.preventDefault();
    if (editTitle.trim()) {
      await currentChat.renameConversation(id, editTitle.trim());
    }
    setEditingId(null);
  };

  const handleArchive = async (id: string, e: React.MouseEvent) => {
    e.stopPropagation();
    if (window.confirm("Bạn có chắc muốn lưu trữ cuộc trò chuyện này?")) {
      await currentChat.archiveConversation(id);
    }
  };

  const formatTime = (iso?: string) => {
    if (!iso) return "";
    const date = new Date(iso);
    const now = new Date();
    const isToday =
      date.getDate() === now.getDate() &&
      date.getMonth() === now.getMonth() &&
      date.getFullYear() === now.getFullYear();

    if (isToday) {
      return date.toLocaleTimeString("vi-VN", { hour: "2-digit", minute: "2-digit" });
    }
    return date.toLocaleDateString("vi-VN", { day: "2-digit", month: "2-digit" });
  };

  // Trạng thái Thu gọn (Collapsed Sidebar)
  if (collapsed) {
    const totalCount = (aiChat.conversations?.length || 0) + (prospectChat.conversations?.length || 0);
    return (
      <div className="nav-group sidebar-chat-history-group collapsed">
        <button
          type="button"
          className="sidebar-nav-item sidebar-chat-collapsed-trigger"
          onClick={onExpand}
          title={`Lịch sử AI Chat (${totalCount} phiên) — Nhấn để mở`}
          data-tooltip={`Lịch sử AI (${totalCount})`}
        >
          <span className="nav-item-icon">
            <IconChatBubble />
          </span>
          {totalCount > 0 && <span className="sidebar-chat-count-pill">{totalCount}</span>}
        </button>
      </div>
    );
  }

  // Trạng thái Mở rộng (Expanded Sidebar)
  return (
    <div className="sidebar-chat-history-group">
      {/* Tiêu đề & Nút Tạo mới */}
      <div className="sidebar-chat-header-row">
        <div className="sidebar-chat-title-wrap">
          <span className="sidebar-chat-icon-badge">
            <IconChatBubble />
          </span>
          <span className="sidebar-chat-header-label">Lịch sử AI</span>
          <span className="sidebar-chat-badge">{conversations.length}</span>
        </div>

        <button
          type="button"
          className="sidebar-chat-new-action-btn"
          onClick={handleNew}
          title="Tạo phiên trò chuyện mới"
        >
          <IconPlus />
          <span>Mới</span>
        </button>
      </div>

      {/* Tabs chuyển đổi giữa Talent & Growth (khi người dùng có quyền cả 2) */}
      {canAccessTalent && canAccessRb && (
        <div className="sidebar-chat-subtabs">
          <button
            type="button"
            className={`sidebar-chat-tab-pill ${activeTab === "talent" ? "active" : ""}`}
            onClick={() => setActiveTab("talent")}
          >
            <span>Talent</span>
            <span className="sidebar-chat-tab-count">{aiChat.conversations?.length || 0}</span>
          </button>
          <button
            type="button"
            className={`sidebar-chat-tab-pill ${activeTab === "prospect" ? "active" : ""}`}
            onClick={() => setActiveTab("prospect")}
          >
            <span>Growth</span>
            <span className="sidebar-chat-tab-count">{prospectChat.conversations?.length || 0}</span>
          </button>
        </div>
      )}

      {/* Ô tìm kiếm nhanh khi có từ 3 hội thoại trở lên */}
      {conversations.length >= 3 && (
        <div className="sidebar-chat-search-wrap">
          <span className="sidebar-chat-search-icon">
            <IconSearchMini />
          </span>
          <input
            type="text"
            className="sidebar-chat-search-input"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Tìm cuộc trò chuyện…"
          />
          {search && (
            <button
              type="button"
              className="sidebar-chat-search-clear"
              onClick={() => setSearch("")}
              title="Xóa tìm kiếm"
            >
              <IconXMini />
            </button>
          )}
        </div>
      )}

      {/* Danh sách các cuộc trò chuyện */}
      <div className="sidebar-chat-list">
        {filtered.length === 0 ? (
          <div className="sidebar-chat-empty">
            {search ? "Không tìm thấy hội thoại" : "Chưa có cuộc trò chuyện"}
          </div>
        ) : (
          filtered.map((c) => {
            const cid = c.conversation_id || String(c.id);
            const isActive = activeId === cid || activeId === String(c.id);
            const isEditing = editingId === cid;

            return (
              <div
                key={c.id}
                className={`sidebar-chat-item ${isActive ? "active" : ""}`}
                onClick={() => handleSelect(cid)}
                title={c.title || "Cuộc trò chuyện"}
              >
                <span className={`sidebar-chat-item-icon ${activeTab}`}>
                  {activeTab === "talent" ? <IconTalentChat /> : <IconGrowthChat />}
                </span>

                <div className="sidebar-chat-item-info">
                  {isEditing ? (
                    <form onSubmit={(e) => void handleConfirmRename(cid, e)} onClick={(e) => e.stopPropagation()}>
                      <input
                        type="text"
                        className="sidebar-chat-rename-input"
                        value={editTitle}
                        onChange={(e) => setEditTitle(e.target.value)}
                        onBlur={(e) => void handleConfirmRename(cid, e)}
                        autoFocus
                      />
                    </form>
                  ) : (
                    <>
                      <span className="sidebar-chat-item-title">{c.title || "Cuộc trò chuyện mới"}</span>
                      <span className="sidebar-chat-item-time">{formatTime(c.updated_at || c.created_at)}</span>
                    </>
                  )}
                </div>

                {/* Các nút thao tác nhanh (Đổi tên, Lưu trữ) */}
                <div className="sidebar-chat-item-actions">
                  <button
                    type="button"
                    className="sidebar-chat-action-btn edit"
                    onClick={(e) => handleStartRename(cid, c.title || "", e)}
                    title="Đổi tên"
                    aria-label="Đổi tên"
                  >
                    <IconPencilMini />
                  </button>
                  <button
                    type="button"
                    className="sidebar-chat-action-btn delete"
                    onClick={(e) => void handleArchive(cid, e)}
                    title="Lưu trữ"
                    aria-label="Lưu trữ"
                  >
                    <IconTrashMini />
                  </button>
                </div>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}
