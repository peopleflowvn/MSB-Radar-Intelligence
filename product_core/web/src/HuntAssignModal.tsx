import React, { useEffect, useState } from "react";
import { HuntRequestRow } from "./api";

export interface HuntAssignPerson {
  person_id: number;
  name: string;
}

export interface HuntAssignModalProps {
  isOpen: boolean;
  title: string;
  people: HuntAssignPerson[];
  openHunts: HuntRequestRow[];
  onClose: () => void;
  onAssign: (opts: { huntId?: number; newTitle?: string }) => Promise<void>;
}

/** Modal đưa ứng viên (đơn lẻ hoặc hàng loạt) vào Đợt tuyển / Nhiệm vụ săn. */
export function HuntAssignModal({
  isOpen,
  title,
  people,
  openHunts,
  onClose,
  onAssign,
}: HuntAssignModalProps) {
  const [mode, setMode] = useState<"existing" | "new">(
    openHunts.length > 0 ? "existing" : "new"
  );
  const [selectedHuntId, setSelectedHuntId] = useState<number>(
    openHunts[0]?.id || 0
  );
  const [newTitle, setNewTitle] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (openHunts.length > 0 && !selectedHuntId) {
      setSelectedHuntId(openHunts[0].id);
    }
    if (openHunts.length === 0) {
      setMode("new");
    }
  }, [openHunts, selectedHuntId]);

  if (!isOpen) return null;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    if (mode === "existing") {
      if (!selectedHuntId) {
        setError("Vui lòng chọn một đợt tuyển hoặc nhiệm vụ săn.");
        return;
      }
      setSubmitting(true);
      try {
        await onAssign({ huntId: selectedHuntId });
        onClose();
      } catch (err: any) {
        setError(err?.message || "Lỗi khi đưa ứng viên vào đợt tuyển.");
      } finally {
        setSubmitting(false);
      }
    } else {
      const trimmed = newTitle.trim();
      if (!trimmed) {
        setError("Vui lòng nhập tên đợt tuyển hoặc nhiệm vụ săn mới.");
        return;
      }
      setSubmitting(true);
      try {
        await onAssign({ newTitle: trimmed });
        onClose();
      } catch (err: any) {
        setError(err?.message || "Lỗi khi tạo đợt tuyển mới.");
      } finally {
        setSubmitting(false);
      }
    }
  };

  return (
    <div className="hunt-modal-backdrop" onClick={onClose}>
      <div
        className="hunt-modal-box"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
      >
        <div className="hunt-modal-header">
          <div className="hunt-modal-title">
            <span className="hunt-modal-icon">🎯</span>
            <h3>{title}</h3>
          </div>
          <button
            type="button"
            className="hunt-modal-close-btn"
            onClick={onClose}
            aria-label="Đóng"
          >
            ✕
          </button>
        </div>

        <form onSubmit={handleSubmit} className="hunt-modal-body">
          <div className="hunt-modal-candidates-summary">
            {people.length === 1 ? (
              <p>
                Ứng viên: <strong>{people[0].name}</strong>
              </p>
            ) : (
              <p>
                Đã chọn <strong>{people.length}</strong> ứng viên:{" "}
                <span className="hunt-modal-candidate-names">
                  {people.map((p) => p.name).join(", ")}
                </span>
              </p>
            )}
          </div>

          {openHunts.length > 0 && (
            <div className="hunt-modal-tabs">
              <button
                type="button"
                className={`hunt-modal-tab${mode === "existing" ? " active" : ""}`}
                onClick={() => setMode("existing")}
              >
                Đợt tuyển có sẵn ({openHunts.length})
              </button>
              <button
                type="button"
                className={`hunt-modal-tab${mode === "new" ? " active" : ""}`}
                onClick={() => setMode("new")}
              >
                + Tạo đợt tuyển mới
              </button>
            </div>
          )}

          {mode === "existing" ? (
            <div className="hunt-modal-field">
              <label htmlFor="hunt-select">Chọn đợt tuyển / nhiệm vụ săn đang mở:</label>
              {openHunts.length === 0 ? (
                <div className="hunt-modal-empty-hint">
                  Hiện chưa có đợt tuyển nào đang mở. Vui lòng chuyển sang tab "+ Tạo đợt tuyển mới".
                </div>
              ) : (
                <select
                  id="hunt-select"
                  className="hunt-modal-select"
                  value={selectedHuntId}
                  onChange={(e) => setSelectedHuntId(Number(e.target.value))}
                >
                  {openHunts.map((hunt) => (
                    <option key={hunt.id} value={hunt.id}>
                      {hunt.title} ({hunt.progress?.total ?? hunt.people?.length ?? 0} ứng viên · {hunt.assigned_to_name || "Chưa gán"})
                    </option>
                  ))}
                </select>
              )}
            </div>
          ) : (
            <div className="hunt-modal-field">
              <label htmlFor="new-hunt-title">Tên đợt tuyển / nhiệm vụ săn mới:</label>
              <input
                id="new-hunt-title"
                type="text"
                className="hunt-modal-input"
                placeholder="VD: Tuyển dụng Senior Java Developer Q4/2026"
                value={newTitle}
                onChange={(e) => setNewTitle(e.target.value)}
                autoFocus
              />
            </div>
          )}

          {error && <div className="hunt-modal-error">{error}</div>}

          <div className="hunt-modal-footer">
            <button
              type="button"
              className="hunt-modal-btn btn-cancel"
              onClick={onClose}
              disabled={submitting}
            >
              Hủy
            </button>
            <button
              type="submit"
              className="hunt-modal-btn btn-submit"
              disabled={submitting || (mode === "existing" && openHunts.length === 0)}
            >
              {submitting ? "Đang xử lý…" : mode === "existing" ? "Đưa vào đợt tuyển" : "Tạo & Đưa vào"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
