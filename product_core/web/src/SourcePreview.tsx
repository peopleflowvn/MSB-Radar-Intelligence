import { useQuery } from "@tanstack/react-query";
import React, { useEffect, useMemo, useRef } from "react";
import { api } from "./api";

/**
 * Xem nguyên văn đoạn CV được trích dẫn — kiểu NotebookLM: bấm vào một trích dẫn,
 * mở panel văn bản nguồn, cuộn tới và tô sáng đúng đoạn.
 */
export interface SourceRef {
  documentId: number;
  snippet: string;
  personName?: string;
  personId?: number;
  label?: string;
}

function norm(s: string): string {
  return s.replace(/\s+/g, " ").trim().toLowerCase();
}

/** Tìm vị trí đoạn snippet trong text nguồn (khoan dung khoảng trắng/xuống dòng). */
function locate(text: string, snippet: string): [number, number] | null {
  const nSnip = norm(snippet).slice(0, 120);
  if (!nSnip) return null;
  const nText = norm(text);
  let i = nText.indexOf(nSnip);
  if (i < 0) {
    // thử với 8 từ đầu của snippet
    const head = nSnip.split(" ").slice(0, 8).join(" ");
    i = head ? nText.indexOf(head) : -1;
    if (i < 0) return null;
  }
  // ánh xạ vị trí trong bản normalized về text gốc (xấp xỉ theo tỉ lệ từ)
  const wordsBefore = nText.slice(0, i).split(" ").length - 1;
  const parts = text.split(/(\s+)/);
  let count = 0;
  let start = 0;
  for (let p = 0; p < parts.length; p++) {
    if (parts[p].trim()) {
      if (count === wordsBefore) { start = text.indexOf(parts[p], start); break; }
      count++;
    }
    start += parts[p].length;
  }
  const end = Math.min(text.length, start + snippet.length + 40);
  return [Math.max(0, start), end];
}

export default function SourcePreview({
  source,
  onClose,
  personLinkFrom = "talent-ai",
}: {
  source: SourceRef;
  onClose: () => void;
  /** Ngữ cảnh quay lại cho Hồ sơ 360°, do màn hình chứa nó truyền xuống. */
  personLinkFrom?: string;
}) {
  // documentId = 0 nghĩa là đoạn lấy từ dữ liệu hồ sơ (trường CSDL + payload
  // Edge), không phải trích từ một file CV — không có văn bản gốc để mở.
  const fromProfile = !source.documentId;
  const q = useQuery({
    queryKey: ["doc-text", source.documentId],
    queryFn: () => api.documentText(source.documentId),
    staleTime: 5 * 60_000,
    enabled: !fromProfile,
  });
  const markRef = useRef<HTMLElement | null>(null);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  useEffect(() => {
    markRef.current?.scrollIntoView?.({ block: "center", behavior: "smooth" });
  }, [q.data]);

  const body = useMemo(() => {
    const text = q.data?.text ?? "";
    if (!text) return null;
    const span = locate(text, source.snippet);
    if (!span) {
      return <pre className="source-preview-text">{text}</pre>;
    }
    const [s, e] = span;
    return (
      <pre className="source-preview-text">
        {text.slice(0, s)}
        <mark ref={markRef as React.RefObject<HTMLElement>} className="source-preview-hl">
          {text.slice(s, e)}
        </mark>
        {text.slice(e)}
      </pre>
    );
  }, [q.data, source.snippet]);

  return (
    <div className="source-preview-backdrop" onClick={onClose}>
      <div className="source-preview-panel" onClick={(e) => e.stopPropagation()}>
        <div className="source-preview-head">
          <div>
            <strong>📄 Nguồn: {source.personName || `Tài liệu #${source.documentId}`}</strong>
            <span className="muted small">
              {" · "}{fromProfile ? "Dữ liệu hồ sơ" : `CV #${source.documentId}`}
              {source.label ? ` · ${source.label}` : ""}
            </span>
          </div>
          <div style={{ display: "flex", gap: 8 }}>
            {!fromProfile && (
              <a className="btn ghost small" href={api.documentPreviewUrl(source.documentId)} target="_blank" rel="noopener noreferrer">
                Mở bản gốc ↗
              </a>
            )}
            {source.personId ? (
              <a className="btn ghost small" href={`/person/${source.personId}?from=${personLinkFrom}`}>
                Mở hồ sơ ↗
              </a>
            ) : null}
            <button className="btn ghost small" type="button" onClick={onClose}>✕</button>
          </div>
        </div>
        <div className="source-preview-cited">
          <span className="muted small">Đoạn được trích:</span> “{source.snippet}”
        </div>
        {q.data?.contacts_masked && (
          // Nói rõ là ĐANG CHE, kẻo người đọc tưởng CV thiếu dữ liệu và đi tìm
          // ở chỗ khác — hoặc tệ hơn, tưởng hệ thống bóc tách hỏng.
          <div className="source-preview-note muted small">
            🔒 Email và số điện thoại đã được che. Mở khoá liên hệ trong hồ sơ để xem.
          </div>
        )}
        <div className="source-preview-scroll">
          {fromProfile && (
            <p className="muted">
              Đoạn này lấy từ dữ liệu hồ sơ (trường trong hệ thống và dữ liệu Edge
              gửi lên), không phải trích từ một tệp CV nên không có văn bản gốc để mở.
            </p>
          )}
          {q.isLoading && <p className="muted">Đang tải văn bản nguồn…</p>}
          {q.isError && <p className="error-text">Không đọc được văn bản tài liệu này.</p>}
          {body}
        </div>
      </div>
    </div>
  );
}
