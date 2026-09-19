/**
 * Góc nhìn của phân hệ Tìm kiếm (/search): cùng một kho hồ sơ, hai mục đích.
 *
 *   recruiter → tìm ứng viên, kết quả đẩy sang Talent Radar (đợt tuyển, pipeline tuyển dụng)
 *   prospect  → tìm khách hàng, kết quả đẩy sang Growth Radar (cơ hội bán chéo)
 *
 * Quyền mở góc nhìn nào bám theo `modules` của phiên đăng nhập chứ không bám theo
 * `roles`: Admin có thể cấp/thu hồi module cho từng vai trò trong trang Quản trị
 * (`accounts.models.RoleModuleAccess`), nên chỉ `modules` mới phản ánh đúng quyền
 * thực tế. Bám theo roles sẽ bỏ qua các cấp phát đó.
 */
export type SearchPerspective = "recruiter" | "prospect";

export const PERSPECTIVE_STORAGE_KEY = "radar_active_perspective";

export interface PerspectiveAccess {
  canRecruiter: boolean;
  canProspect: boolean;
  canSwitch: boolean;
}

/**
 * Dự phòng cho `talent.corpus_qa.can_read_cv` khi phiên chưa mang cờ
 * `can_read_cv` (máy chủ bản cũ): RM thuần (`rb_sales` mà không kiêm vai trò
 * tuyển dụng nào) không được đọc nội dung CV. Có cờ từ `/auth/me/` thì luôn
 * dùng cờ đó — luật chỉ nên sống ở một chỗ.
 *
 * Không thể suy ra điều này từ `modules`: RB Sales VẪN có module `talent` (quyết
 * định 19/08 — đọc chéo hồ sơ, có ghi log `cross_domain`), nhưng backend chặn
 * riêng phần CV vì câu trả lời của engine Tuyển dụng luôn kèm trích dẫn CV.
 * Đây là chép lại luật của backend, không phải đặt thêm luật mới — lệch nhau thì
 * người dùng bấm vào một nút chắc chắn trả 403.
 */
function canReadCv(roles: Set<string>): boolean {
  if (!roles.has("rb_sales")) return true;
  return roles.has("recruiter") || roles.has("hiring_manager")
    || roles.has("manager") || roles.has("admin");
}

export function perspectiveAccess(
  modules: Set<string>,
  roles: Set<string>,
  serverCanReadCv?: boolean,
): PerspectiveAccess {
  const readCv = serverCanReadCv ?? canReadCv(roles);
  const canRecruiter = modules.has("talent") && readCv;
  const canProspect = modules.has("rb");
  return { canRecruiter, canProspect, canSwitch: canRecruiter && canProspect };
}

function readSaved(): SearchPerspective | null {
  try {
    const saved = localStorage.getItem(PERSPECTIVE_STORAGE_KEY);
    return saved === "recruiter" || saved === "prospect" ? saved : null;
  } catch {
    return null;
  }
}

export function rememberPerspective(perspective: SearchPerspective) {
  try {
    localStorage.setItem(PERSPECTIVE_STORAGE_KEY, perspective);
  } catch {
    // Chế độ riêng tư chặn localStorage — bỏ qua, chỉ mất ghi nhớ giữa các phiên.
  }
}

export function parsePerspective(value: string | null): SearchPerspective | null {
  return value === "recruiter" || value === "prospect" ? value : null;
}

/**
 * Góc nhìn khi mở phân hệ: tham số URL > chỉ có một quyền > lựa chọn gần nhất >
 * nghiệp vụ gốc của vai trò.
 */
export function resolvePerspective({
  modules,
  roles,
  param,
  canReadCv: serverCanReadCv,
}: {
  modules: Set<string>;
  roles: Set<string>;
  param?: string | null;
  canReadCv?: boolean;
}): SearchPerspective {
  const { canRecruiter, canProspect } = perspectiveAccess(modules, roles, serverCanReadCv);

  const requested = parsePerspective(param ?? null);
  if (requested === "prospect" && canProspect) return "prospect";
  if (requested === "recruiter" && canRecruiter) return "recruiter";

  if (canProspect && !canRecruiter) return "prospect";
  if (canRecruiter && !canProspect) return "recruiter";

  const saved = readSaved();
  if (saved === "prospect" && canProspect) return "prospect";
  if (saved === "recruiter" && canRecruiter) return "recruiter";

  const rmHome = roles.has("rb_sales") && !roles.has("recruiter") && !roles.has("hiring_manager");
  if (rmHome && canProspect) return "prospect";
  return canRecruiter ? "recruiter" : "prospect";
}

/** Phân hệ đích mà kết quả tìm kiếm được đẩy sang (đợt tuyển vs cơ hội bán chéo). */
export function perspectiveDomain(perspective: SearchPerspective): "talent" | "rb" {
  return perspective === "prospect" ? "rb" : "talent";
}

/**
 * Giá trị `?from=` gắn vào link Hồ sơ 360° để nút quay lại đưa người dùng về đúng
 * chỗ họ vừa đứng (xem `Person360.tsx`).
 */
export function personLinkFrom(perspective: SearchPerspective, tab: "ai" | "filter"): string {
  return `search-${tab}-${perspective}`;
}
