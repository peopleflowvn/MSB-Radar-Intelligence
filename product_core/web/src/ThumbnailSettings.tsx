import React, { useEffect, useState } from "react";
import { api, PublicSettings } from "./api";

/**
 * Cấu hình thumbnail — ảnh và chữ hiện ra khi dán liên kết Radar vào Zalo,
 * Messenger, Slack, Teams…
 *
 * Mọi giá trị lưu xuống CSDL nên tất cả người truy cập thấy như nhau; không có
 * gì ở localStorage. Máy chủ chèn thẻ meta vào HTML trước khi trả về, vì trình
 * thu thập của các nền tảng đó KHÔNG chạy JavaScript — đổi bằng JS phía trình
 * duyệt thì người dùng thấy, còn liên kết chia sẻ vẫn ảnh cũ.
 */

interface Props {
  settings: PublicSettings | null;
  onSaved: (next: PublicSettings) => void;
}

type Draft = {
  og_image_url: string;
  og_image_alt: string;
  og_image_width: number;
  og_image_height: number;
  og_title: string;
  og_description: string;
  og_site_name: string;
  meta_keywords: string;
  meta_robots: string;
  pwa_short_name: string;
  pwa_background_color: string;
};

const EMPTY: Draft = {
  og_image_url: "", og_image_alt: "", og_image_width: 1200, og_image_height: 630,
  og_title: "", og_description: "", og_site_name: "", meta_keywords: "",
  meta_robots: "index, follow", pwa_short_name: "", pwa_background_color: "#0F172A",
};

function fromSettings(settings: PublicSettings | null): Draft {
  if (!settings) return { ...EMPTY };
  return {
    og_image_url: settings.og_image_url ?? "",
    og_image_alt: settings.og_image_alt ?? "",
    og_image_width: settings.og_image_width ?? 1200,
    og_image_height: settings.og_image_height ?? 630,
    og_title: settings.og_title ?? "",
    og_description: settings.og_description ?? "",
    og_site_name: settings.og_site_name ?? "",
    meta_keywords: settings.meta_keywords ?? "",
    meta_robots: settings.meta_robots || "index, follow",
    pwa_short_name: settings.pwa_short_name ?? "",
    pwa_background_color: settings.pwa_background_color || "#0F172A",
  };
}

export default function ThumbnailSettings({ settings, onSaved }: Props) {
  const [draft, setDraft] = useState<Draft>(() => fromSettings(settings));
  const [message, setMessage] = useState("");
  const [saving, setSaving] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState("");
  const [isDragOver, setIsDragOver] = useState(false);
  const [showManualUrl, setShowManualUrl] = useState(false);
  const fileInputRef = React.useRef<HTMLInputElement>(null);

  useEffect(() => { setDraft(fromSettings(settings)); }, [settings]);

  const set = <K extends keyof Draft>(key: K, value: Draft[K]) =>
    setDraft((current) => ({ ...current, [key]: value }));

  const handleProcessFile = async (file: File) => {
    if (!file) return;
    const validTypes = ["image/png", "image/jpeg", "image/webp", "image/gif"];
    if (!validTypes.includes(file.type)) {
      setUploadError("Chỉ hỗ trợ các tệp ảnh định dạng PNG, JPG, WebP hoặc GIF.");
      return;
    }
    if (file.size > 5 * 1024 * 1024) {
      setUploadError("Dung lượng tệp vượt quá 5MB. Vui lòng chọn tệp nhỏ hơn.");
      return;
    }
    setUploadError("");
    setUploading(true);
    try {
      const res = await api.uploadOgImage(file);
      setDraft((current) => ({
        ...current,
        og_image_url: res.url,
        og_image_width: res.width || current.og_image_width,
        og_image_height: res.height || current.og_image_height,
      }));
      setMessage("✓ Đã tải ảnh thumbnail lên máy chủ thành công.");
    } catch (err: unknown) {
      const detail = err instanceof Error ? err.message : "Tải ảnh thất bại";
      setUploadError(`⚠️ ${detail}`);
    } finally {
      setUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  };

  const handleFileUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) handleProcessFile(file);
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragOver(false);
    const file = e.dataTransfer.files?.[0];
    if (file) handleProcessFile(file);
  };

  const handleRemoveImage = () => {
    setDraft((current) => ({
      ...current,
      og_image_url: "",
      og_image_width: 1200,
      og_image_height: 630,
    }));
    setUploadError("");
    if (fileInputRef.current) fileInputRef.current.value = "";
  };

  // Ô xem trước dùng bản ĐÃ SUY RA từ máy chủ khi người dùng chưa gõ gì, để cái
  // họ thấy đúng bằng cái crawler sẽ nhận — không phải một phỏng đoán của giao diện.
  const derived = settings?.link_preview;
  const shownTitle = draft.og_title || derived?.title || settings?.app_name || "MSB Radar";
  const shownDesc = draft.og_description || derived?.description || settings?.app_tagline || "";
  const shownSite = draft.og_site_name || derived?.site_name || "";
  const shownImage = draft.og_image_url || derived?.image || "/og-image.png";

  const save = async (event: React.FormEvent) => {
    event.preventDefault();
    setSaving(true);
    try {
      const next = await api.publicSettingsSave(draft);
      onSaved(next);
      setMessage("✓ Đã lưu. Mọi người truy cập sẽ thấy thumbnail mới ngay.");
    } catch {
      setMessage("⚠️ Lưu không thành công. Cần quyền quản trị.");
    } finally {
      setSaving(false);
      setTimeout(() => setMessage(""), 5000);
    }
  };

  return (
    <form className="card thumbnail-settings" onSubmit={save}>
      <h3>Thumbnail &amp; xem trước liên kết</h3>
      <p className="muted small">
        Ảnh và chữ hiện ra khi dán liên kết Radar vào Zalo, Messenger, Slack, Teams…
        Lưu xuống máy chủ nên <strong>mọi người truy cập đều thấy như nhau</strong>.
        Để trống một ô nghĩa là lấy theo tên hệ thống và câu mô tả bên trên.
      </p>

      <div className="thumbnail-grid">
        <div className="thumbnail-fields">
          {/* Tải tệp Thumbnail lên trực tiếp */}
          <div style={{ marginBottom: "6px" }}>
            <label style={{ display: "block", marginBottom: "6px", fontWeight: 600 }}>
              Ảnh thumbnail chia sẻ mạng xã hội (Open Graph Image)
            </label>
            <p className="muted small" style={{ margin: "0 0 10px" }}>
              Tải trực tiếp tệp ảnh từ máy tính (PNG, JPG, WebP, GIF). Khuyến nghị tỷ lệ 1.91:1 (chuẩn 1200×630px).
            </p>

            <input
              ref={fileInputRef}
              type="file"
              accept="image/png, image/jpeg, image/webp, image/gif"
              style={{ display: "none" }}
              onChange={handleFileUpload}
            />

            {draft.og_image_url ? (
              <div className="icon-preview-active-card">
                <div className="icon-preview-left">
                  <div className="icon-preview-thumb-box" style={{ width: "80px", height: "46px", borderRadius: "8px" }}>
                    <img
                      src={draft.og_image_url}
                      alt="Thumbnail Preview"
                      className="icon-preview-thumb-img"
                      style={{ objectFit: "cover" }}
                    />
                  </div>
                  <div className="icon-preview-meta">
                    <h4 className="icon-preview-title">✓ Đã áp dụng ảnh thumbnail tùy chỉnh</h4>
                    <p className="icon-preview-desc">
                      Kích thước: {draft.og_image_width}×{draft.og_image_height}px
                      {draft.og_image_url.startsWith("/media/") ? " (Lưu trong kho media máy chủ)" : " (Liên kết ảnh)"}
                    </p>
                  </div>
                </div>
                <div style={{ display: "flex", gap: "8px", alignItems: "center" }}>
                  <button
                    type="button"
                    className="btn btn-secondary btn-sm"
                    disabled={uploading}
                    onClick={() => fileInputRef.current?.click()}
                  >
                    📁 Chọn tệp khác
                  </button>
                  <button
                    type="button"
                    className="btn btn-secondary btn-sm"
                    disabled={uploading}
                    onClick={handleRemoveImage}
                  >
                    🗑️ Gỡ bỏ ảnh
                  </button>
                </div>
              </div>
            ) : (
              <div
                className={`icon-upload-dropzone ${isDragOver ? "dragover" : ""}`}
                style={{ minHeight: "110px" }}
                onClick={() => !uploading && fileInputRef.current?.click()}
                onDragOver={(e) => { e.preventDefault(); setIsDragOver(true); }}
                onDragLeave={() => setIsDragOver(false)}
                onDrop={handleDrop}
              >
                <div className="icon-upload-icon-svg">{uploading ? "⏳" : "🖼️"}</div>
                <span className="icon-upload-main-text">
                  {uploading
                    ? "Đang tải ảnh lên máy chủ…"
                    : "Bấm để tải ảnh thumbnail lên hoặc kéo & thả vào đây"}
                </span>
                <span className="icon-upload-sub-text">
                  Hỗ trợ PNG, JPG, WebP, GIF (Tối đa 5MB, khuyến nghị 1200×630px)
                </span>
              </div>
            )}

            {uploadError && <p className="error-text" style={{ marginTop: "8px" }}>{uploadError}</p>}

            <div style={{ marginTop: "8px" }}>
              <button
                type="button"
                className="btn btn-link btn-sm"
                style={{ padding: 0, fontSize: "12px", color: "var(--accent)" }}
                onClick={() => setShowManualUrl((v) => !v)}
              >
                {showManualUrl ? "▲ Thu gọn nhập URL thủ công" : "▼ Hoặc nhập liên kết URL ảnh ngoài"}
              </button>
            </div>

            {showManualUrl && (
              <div style={{ marginTop: "8px", padding: "10px", background: "var(--surface-raised, rgba(0,0,0,0.03))", borderRadius: "8px" }}>
                <label>
                  Đường dẫn ảnh trực tiếp (URL)
                  <input
                    type="text"
                    value={draft.og_image_url}
                    placeholder="/og-image.png hoặc https://..."
                    onChange={(e) => set("og_image_url", e.target.value)}
                  />
                </label>
                <span className="muted small" style={{ display: "block", marginTop: "4px" }}>
                  Dán URL đầy đủ (https://...) hoặc đường dẫn bắt đầu bằng “/”.
                </span>
              </div>
            )}
          </div>

          <div className="thumbnail-row">
            <label>
              Rộng (px)
              <input type="number" min={200} max={4000} value={draft.og_image_width}
                     onChange={(e) => set("og_image_width", Number(e.target.value))} />
            </label>
            <label>
              Cao (px)
              <input type="number" min={200} max={4000} value={draft.og_image_height}
                     onChange={(e) => set("og_image_height", Number(e.target.value))} />
            </label>
          </div>

          <label>
            Mô tả ảnh (cho trình đọc màn hình)
            <input value={draft.og_image_alt} placeholder={derived?.image_alt || ""}
                   onChange={(e) => set("og_image_alt", e.target.value)} />
          </label>

          <label>
            Tiêu đề khi chia sẻ
            <input value={draft.og_title} placeholder={derived?.title || ""}
                   onChange={(e) => set("og_title", e.target.value)} />
          </label>

          <label>
            Mô tả khi chia sẻ
            <textarea rows={3} value={draft.og_description}
                      placeholder={derived?.description || ""}
                      onChange={(e) => set("og_description", e.target.value)} />
          </label>

          <label>
            Tên trang (og:site_name)
            <input value={draft.og_site_name} placeholder={derived?.site_name || ""}
                   onChange={(e) => set("og_site_name", e.target.value)} />
          </label>

          <label>
            Từ khoá SEO
            <input value={draft.meta_keywords} placeholder="cách nhau bằng dấu phẩy"
                   onChange={(e) => set("meta_keywords", e.target.value)} />
          </label>

          <label>
            Cho phép công cụ tìm kiếm lập chỉ mục
            <select value={draft.meta_robots}
                    onChange={(e) => set("meta_robots", e.target.value)}>
              <option value="index, follow">Có — cho lập chỉ mục</option>
              <option value="noindex, nofollow">Không — hệ thống nội bộ</option>
            </select>
          </label>

          <div className="thumbnail-row">
            <label>
              Tên ngắn khi cài lên điện thoại
              <input value={draft.pwa_short_name} placeholder={settings?.app_name || ""}
                     onChange={(e) => set("pwa_short_name", e.target.value)} />
            </label>
            <label>
              Màu nền khi mở app
              <input type="color" value={draft.pwa_background_color}
                     onChange={(e) => set("pwa_background_color", e.target.value)} />
            </label>
          </div>
        </div>

        <div className="thumbnail-preview-col">
          <span className="muted small">Xem trước khi chia sẻ liên kết</span>
          <div className="thumbnail-preview">
            <div className="thumbnail-preview-image"
                 style={{ aspectRatio: `${draft.og_image_width} / ${draft.og_image_height}` }}>
              {shownImage
                ? <img src={shownImage} alt={draft.og_image_alt || shownTitle} />
                : <span className="muted small">Chưa có ảnh</span>}
            </div>
            <div className="thumbnail-preview-text">
              {shownSite && <span className="thumbnail-preview-site">{shownSite}</span>}
              <strong>{shownTitle}</strong>
              <span className="muted small">{shownDesc}</span>
            </div>
          </div>
          <span className="muted small">
            Nền tảng nhớ ảnh cũ khá lâu. Đổi xong mà Zalo/Facebook còn hiện ảnh cũ
            thì đó là bộ nhớ đệm của họ, không phải Radar chưa lưu.
          </span>
        </div>
      </div>

      <div className="thumbnail-actions">
        <button type="submit" className="btn" disabled={saving}>
          {saving ? "Đang lưu…" : "Lưu thumbnail"}
        </button>
        {message && <span className="muted small">{message}</span>}
      </div>
    </form>
  );
}
