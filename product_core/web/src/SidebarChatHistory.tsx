import React, { useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { useAiChatState, useProspectChatState } from "./searchPersistence";

interface Props {
  collapsed: boolean;
  onExpand: () => void;
  onNavigate?: () => void;
  allowedModules?: Set<string>;
}

export default function SidebarChatHistory({ collapsed, onExpand, onNavigate, allowedModules }: Props) {
  const location = useLocation();
  const navigate = useNavigate();

  const aiChat = useAiChatState();
  const prospectChat = useProspectChatState();

  const isRbRoute = location.pathname.startsWith("/rb");
  const canAccessTalent = !allowedModules || allowedModules.has("talent");
  const canAccessRb = !allowedModules || allowedModules.has("rb");

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
      navigate("/talent?tab=talent");
      await aiChat.selectConversation(id);
    } else {
      navigate("/rb?tab=prospects");
      await prospectChat.selectConversation(id);
    }
  };

  const handleNew = () => {
    onNavigate?.();
    if (activeTab === "talent") {
      aiChat.resetConversation();
      navigate("/talent?tab=talent");
    } else {
      prospectChat.resetConversation();
      navigate("/rb?tab=prospects");
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
          title={`Lịch sử trò chuyện (${totalCount} cuộc hội thoại) — Bấm để mở`}
        >
          <span className="nav-item-icon">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
            </svg>
          </span>
          <span className="sidebar-chat-count-pill">{totalCount}</span>
        </button>
      </div>
    );
  }

  // Trạng thái Mở rộng (Expanded Sidebar)
  return (
    <div className="nav-group sidebar-chat-history-group">
      {/* Tiêu đề & Nút Tạo mới */}
      <div className="sidebar-chat-header-row">
        <div className="sidebar-chat-title-wrap">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
          </svg>
          <span className="sidebar-chat-header-label">Lịch sử trò chuyện</span>
          <span className="sidebar-chat-badge">{conversations.length}</span>
        </div>

        <button
          type="button"
          className="sidebar-chat-new-action-btn"
          onClick={handleNew}
          title="Tạo cuộc trò chuyện mới"
        >
          ＋ Mới
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
            Talent ({aiChat.conversations?.length || 0})
          </button>
          <button
            type="button"
            className={`sidebar-chat-tab-pill ${activeTab === "prospect" ? "active" : ""}`}
            onClick={() => setActiveTab("prospect")}
          >
            Growth ({prospectChat.conversations?.length || 0})
          </button>
        </div>
      )}

      {/* Ô tìm kiếm nhanh khi có từ 3 hội thoại trở lên */}
      {conversations.length >= 3 && (
        <div className="sidebar-chat-search-wrap">
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
              ×
            </button>
          )}
        </div>
      )}

      {/* Danh sách các cuộc trò chuyện */}
      <div className="sidebar-chat-list">
        {filtered.length === 0 ? (
          <div className="sidebar-chat-empty">
            {search ? "Không khớp tên hội thoại" : "Chưa có cuộc trò chuyện nào"}
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
                <span className="sidebar-chat-item-icon">
                  {activeTab === "talent" ? "🎯" : "💼"}
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
                    className="sidebar-chat-action-btn"
                    onClick={(e) => handleStartRename(cid, c.title || "", e)}
                    title="Đổi tên"
                  >
                    ✏️
                  </button>
                  <button
                    type="button"
                    className="sidebar-chat-action-btn delete"
                    onClick={(e) => void handleArchive(cid, e)}
                    title="Lưu trữ cuộc trò chuyện"
                  >
                    🗑️
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
