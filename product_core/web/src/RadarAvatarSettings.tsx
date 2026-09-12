import React, { useRef, useState, useEffect } from "react";
import { api, PublicSettings } from "./api";
import { useCustomTheme } from "./CustomThemeContext";

const PRESET_RADAR_AVATARS = ["🤖", "⚡", "🧠", "🎯", "🔮", "🚀", "🦊", "🌐", "✨", "💼", "💡", "🛡️"];

interface Props {
  settings: PublicSettings | null;
  onSaved?: (next: PublicSettings) => void;
}

export default function RadarAvatarSettings({ settings, onSaved }: Props) {
  const {
    appName,
    radarAvatarUrl,
    radarAvatarEmoji,
    setRadarAvatarUrl,
    setRadarAvatarEmoji,
    saveSystemSettings,
  } = useCustomTheme();

  const [localUrl, setLocalUrl] = useState(radarAvatarUrl || settings?.radar_avatar_url || "");
  const [localEmoji, setLocalEmoji] = useState(radarAvatarEmoji || settings?.radar_avatar_emoji || "⚡");
  const [isDragOver, setIsDragOver] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState("");
  const [message, setMessage] = useState("");
  const [saving, setSaving] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (radarAvatarUrl !== undefined) setLocalUrl(radarAvatarUrl);
  }, [radarAvatarUrl]);

  useEffect(() => {
    if (radarAvatarEmoji !== undefined) setLocalEmoji(radarAvatarEmoji);
  }, [radarAvatarEmoji]);

  const handleProcessFile = async (file: File) => {
    if (!file) return;
    const valid = ["image/png", "image/jpeg", "image/webp", "image/svg+xml"];
    if (!valid.includes(file.type)) {
      setUploadError("Chỉ hỗ trợ ảnh định dạng PNG, JPG, WebP hoặc SVG.");
      return;
    }
    if (file.size > 3 * 1024 * 1024) {
      setUploadError("Dung lượng tệp vượt quá 3MB. Vui lòng chọn ảnh nhỏ hơn.");
      return;
    }
    setUploadError("");
    setUploading(true);
    try {
      const res = await api.uploadRadarAvatar(file);
      setLocalUrl(res.url);
      setMessage("✓ Đã tải ảnh avatar lên máy chủ thành công.");
    } catch (err: unknown) {
      const detail = err instanceof Error ? err.message : "Tải ảnh avatar thất bại";
      setUploadError(`⚠️ ${detail}`);
    } finally {
      setUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  };

  const handleFileUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) void handleProcessFile(file);
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragOver(false);
    const file = e.dataTransfer.files?.[0];
    if (file) void handleProcessFile(file);
  };

  const handleClearImage = () => {
    setLocalUrl("");
    setUploadError("");
    if (fileInputRef.current) fileInputRef.current.value = "";
  };

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);
    try {
      const patch = {
        radar_avatar_url: localUrl.trim(),
        radar_avatar_emoji: localEmoji.trim() || "⚡",
      };
      setRadarAvatarUrl(patch.radar_avatar_url);
      setRadarAvatarEmoji(patch.radar_avatar_emoji);
      const next = await saveSystemSettings(patch);
      onSaved?.(next);
      setMessage("✓ Đã lưu cài đặt Avatar của Radar AI. Áp dụng đồng bộ cho mọi người dùng.");
      setTimeout(() => setMessage(""), 4000);
    } catch {
      setUploadError("Không thể lưu cài đặt. Vui lòng thử lại.");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="radar-avatar-settings-container">
      <div className="section-title-wrap">
        <h3>🤖 Avatar &amp; Trợ Diện Radar AI</h3>
        <p className="section-desc">
          Tùy chỉnh biểu tượng đại diện của trợ lý ảo Radar AI khi trò chuyện, trả lời tìm kiếm nhân tài và phân tích khách hàng tiềm năng.
        </p>
      </div>

      <form onSubmit={handleSave}>
        <div className="form-row-2">
          {/* Cột 1: Tải ảnh hoặc chọn Emoji */}
          <div>
            <label style={{ fontWeight: 600, display: "block", marginBottom: 6 }}>
              Ảnh Avatar Đại Diện (Tải lên)
            </label>
            <div
              className={`brand-dropzone ${isDragOver ? "dragover" : ""}`}
              onDragOver={(e) => {
                e.preventDefault();
                setIsDragOver(true);
              }}
              onDragLeave={() => setIsDragOver(false)}
              onDrop={handleDrop}
              onClick={() => fileInputRef.current?.click()}
              style={{ padding: "18px 16px", minHeight: "130px", display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center" }}
            >
              <input
                type="file"
                ref={fileInputRef}
                onChange={handleFileUpload}
                accept=".png,.jpg,.jpeg,.webp,.svg"
                style={{ display: "none" }}
              />
              <div className="dropzone-icon" style={{ fontSize: "28px", marginBottom: "6px" }}>
                {uploading ? "⏳" : localUrl ? "🖼️" : "📤"}
              </div>
              <p className="dropzone-text" style={{ fontSize: "13px", margin: 0, textAlign: "center" }}>
                {uploading ? (
                  "Đang tải ảnh lên máy chủ…"
                ) : localUrl ? (
                  <span>
                    Đang dùng ảnh đại diện tùy chỉnh.{" "}
                    <strong style={{ color: "var(--accent)" }}>Bấm để đổi ảnh khác</strong>
                  </span>
                ) : (
                  <span>
                    Kéo thả hoặc <strong>Bấm để tải ảnh lên</strong> (PNG, JPG, WebP, SVG)
                  </span>
                )}
              </p>
              <span className="dropzone-hint" style={{ fontSize: "11px", color: "var(--muted)", marginTop: "4px" }}>
                Khuyên dùng ảnh vuông tối thiểu 128×128px, dung lượng dưới 3MB
              </span>
            </div>

            {localUrl && (
              <div style={{ marginTop: "8px", display: "flex", gap: "8px", alignItems: "center" }}>
                <span style={{ fontSize: "12px", color: "var(--muted)" }}>Ảnh hiện tại:</span>
                <button
                  type="button"
                  className="btn btn-secondary"
                  onClick={handleClearImage}
                  style={{ padding: "3px 10px", fontSize: "12px", borderRadius: "6px" }}
                >
                  ✕ Gỡ ảnh (chuyển sang dùng Emoji)
                </button>
              </div>
            )}

            {/* Chọn Emoji Preset */}
            <div style={{ marginTop: "16px" }}>
              <label style={{ fontWeight: 600, display: "block", marginBottom: 6 }}>
                Hoặc chọn Biểu tượng Emoji thay thế (khi không dùng ảnh)
              </label>
              <div className="icon-selector-wrapper">
                <input
                  type="text"
                  value={localEmoji}
                  onChange={(e) => setLocalEmoji(e.target.value)}
                  placeholder="⚡"
                  className="input-text icon-input-text"
                  maxLength={4}
                  style={{ width: "60px", textAlign: "center", fontSize: "18px" }}
                />
                <div className="icon-preset-list">
                  {PRESET_RADAR_AVATARS.map((em) => (
                    <button
                      key={em}
                      type="button"
                      className={`icon-preset-btn ${localEmoji === em && !localUrl ? "selected" : ""}`}
                      onClick={() => {
                        setLocalEmoji(em);
                        setLocalUrl("");
                      }}
                      title={`Chọn ${em}`}
                    >
                      {em}
                    </button>
                  ))}
                </div>
              </div>
            </div>
          </div>

          {/* Cột 2: Khung Xem Trước Trực Tiếp (Live Chat Turn Simulation) */}
          <div>
            <label style={{ fontWeight: 600, display: "block", marginBottom: 6 }}>
              👁️ Xem trước giao diện trả lời của Radar AI
            </label>
            <div
              className="radar-avatar-live-preview-box"
              style={{
                background: "var(--surface-raised)",
                border: "1px solid var(--border)",
                borderRadius: "14px",
                padding: "16px",
                minHeight: "180px",
                display: "flex",
                flexDirection: "column",
                justifyContent: "center",
                gap: "12px",
              }}
            >
              <div className="chat-message-row ai" style={{ display: "flex", gap: "12px", alignItems: "flex-start" }}>
                <div
                  className="chat-avatar radar-bot-avatar"
                  style={{
                    width: "38px",
                    height: "38px",
                    borderRadius: "10px",
                    background: "var(--accent-gradient)",
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    overflow: "hidden",
                    flexShrink: 0,
                    boxShadow: "0 4px 12px var(--accent-soft)",
                  }}
                >
                  {localUrl ? (
                    <img
                      src={localUrl}
                      alt="Radar Avatar"
                      style={{ width: "100%", height: "100%", objectFit: "cover" }}
                    />
                  ) : (
                    <span style={{ fontSize: "20px" }}>{localEmoji || "⚡"}</span>
                  )}
                </div>

                <div className="chat-bubble-wrapper" style={{ flex: 1 }}>
                  <div className="chat-bubble-meta" style={{ display: "flex", alignItems: "center", gap: "8px", marginBottom: "4px" }}>
                    <span className="chat-author" style={{ fontWeight: 700, fontSize: "13px", color: "var(--text)" }}>
                      {appName || "MSB Radar"} AI
                    </span>
                    <span className="ai-model-tag" style={{ fontSize: "11px", background: "var(--surface)", border: "1px solid var(--border)", borderRadius: "4px", padding: "1px 6px" }}>
                      🤖 <code>Radar Engine</code>
                    </span>
                    <span className="chat-time" style={{ fontSize: "11px", color: "var(--muted)" }}>Vừa xong</span>
                  </div>

                  <div
                    className="chat-bubble ai"
                    style={{
                      background: "var(--surface)",
                      border: "1px solid var(--border)",
                      borderRadius: "4px 14px 14px 14px",
                      padding: "12px 14px",
                      fontSize: "13.5px",
                      lineHeight: "1.5",
                      color: "var(--text)",
                      boxShadow: "0 2px 8px rgba(0,0,0,0.05)",
                    }}
                  >
                    Xin chào! Tôi là trợ lý ảo <strong>{appName || "MSB Radar"}</strong>. Tôi đã sẵn sàng hỗ trợ bạn săn tìm ứng viên mục tiêu và phát hiện cơ hội bán chéo sản phẩm tài chính!
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>

        {uploadError && (
          <p className="error-text" style={{ marginTop: "12px", color: "#ef4444", fontSize: "13px" }}>
            {uploadError}
          </p>
        )}
        {message && (
          <p className="success-text" style={{ marginTop: "12px", color: "#10b981", fontSize: "13px", fontWeight: 600 }}>
            {message}
          </p>
        )}

        <div style={{ marginTop: "16px", display: "flex", justifyContent: "flex-end" }}>
          <button
            type="submit"
            className="btn btn-primary radar-gradient-btn"
            disabled={saving || uploading}
            style={{ display: "inline-flex", alignItems: "center", gap: "8px", padding: "9px 22px", fontWeight: 600 }}
          >
            {saving ? "Đang lưu cấu hình…" : "Lưu Avatar Radar"}
          </button>
        </div>
      </form>
    </div>
  );
}
