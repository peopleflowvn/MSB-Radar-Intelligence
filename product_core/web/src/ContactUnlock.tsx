import { useMutation } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "./api";

/**
 * Nút mở khoá thông tin liên hệ (Master Plan mục 27).
 *
 * Mọi danh sách trong hệ thống đều trả về email/SĐT **đã che**, không có tham
 * số nào để xin dữ liệu chưa che. Component này gọi đúng một cửa duy nhất trả
 * về liên hệ đầy đủ — nơi máy chủ đếm hạn mức và ghi vết.
 *
 * Giá trị đầy đủ chỉ sống trong bộ nhớ của phiên làm việc này: tải lại trang
 * thì lại che. Đó là chủ đích — người dùng cần số để gọi ngay lúc đó, không
 * cần một bản sao nằm sẵn trong trình duyệt.
 */
export default function ContactUnlock({
  personId,
  domain,
  maskedEmail,
  maskedPhone,
  onUnlocked,
}: {
  personId: number;
  domain?: "talent" | "rb";
  maskedEmail: string;
  maskedPhone: string;
  onUnlocked?: (unlocked: { email: string; phone: string }) => void;
}) {
  const [full, setFull] = useState<{ email: string; phone: string } | null>(null);
  const [error, setError] = useState("");
  const [remaining, setRemaining] = useState<number | null>(null);

  const unlock = useMutation({
    mutationFn: () => api.contactUnlock(personId, domain),
    onSuccess: (result) => {
      setError("");
      setRemaining(result.remaining);
      const unlocked = { email: result.primary_email, phone: result.primary_phone };
      setFull(unlocked);
      onUnlocked?.(unlocked);
    },
    onError: (err: Error) => setError(err.message),
  });

  if (!maskedEmail && !maskedPhone) {
    return <span className="muted">Chưa có thông tin liên hệ</span>;
  }

  return (
    <div className="contact-unlock">
      <div className="contact-unlock-values">
        {(full?.email || maskedEmail) && (
          <span className="contact-pill">
            <span className="c-icon">✉️</span>
            <span>{full?.email || maskedEmail}</span>
          </span>
        )}
        {(full?.phone || maskedPhone) && (
          <span className="contact-pill">
            <span className="c-icon">📞</span>
            <span>{full?.phone || maskedPhone}</span>
          </span>
        )}
      </div>

      {!full && (
        <button
          type="button"
          className="btn btn-secondary btn-sm"
          disabled={unlock.isPending}
          onClick={() => unlock.mutate()}
        >
          {unlock.isPending ? "Đang mở…" : "🔓 Mở khoá liên hệ"}
        </button>
      )}

      {full && remaining !== null && (
        <span className="muted small">Còn {remaining} lượt hôm nay</span>
      )}
      {full && remaining === null && (
        <span className="muted small">Không giới hạn</span>
      )}
      {error && <span className="contact-unlock-error">{error}</span>}
    </div>
  );
}
