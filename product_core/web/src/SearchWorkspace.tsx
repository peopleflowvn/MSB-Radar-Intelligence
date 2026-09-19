import { useQuery } from "@tanstack/react-query";
import { useEffect } from "react";
import { useSearchParams } from "react-router-dom";
import AiSearch from "./AiSearch";
import ProspectAiSearch from "./ProspectAiSearch";
import SearchFilterWorkspace from "./SearchFilterWorkspace";
import { api } from "./api";
import {
  SearchPerspective,
  parsePerspective,
  perspectiveAccess,
  rememberPerspective,
  resolvePerspective,
} from "./searchPerspective";

type SearchTab = "ai" | "filter";

function parseTab(value: string | null): SearchTab {
  return value === "filter" ? "filter" : "ai";
}

/**
 * Phân hệ Tìm kiếm (/search) — một cửa duy nhất để tra cứu kho hồ sơ.
 *
 * Cùng một kho dữ liệu người, hai góc nhìn khai thác: Tuyển dụng (đẩy sang Talent
 * Radar) và Khách hàng tiềm năng (đẩy sang Growth Radar). Góc nhìn nào mở được là
 * do `modules` của phiên quyết định, nên Admin cấp/thu hồi quyền trong trang Quản
 * trị là có hiệu lực ngay, không cần sửa code.
 */
export default function SearchWorkspace() {
  const [searchParams, setSearchParams] = useSearchParams();
  const session = useQuery({ queryKey: ["me"], queryFn: api.me, retry: false });

  const identity = session.data?.authenticated ? session.data : null;
  const modules = new Set(identity?.modules ?? []);
  const roles = new Set(identity?.roles ?? []);
  const canReadCv = identity?.can_read_cv;
  const { canRecruiter, canProspect, canSwitch } = perspectiveAccess(modules, roles, canReadCv);

  // Bộ lọc đa chiều chạy trên `/talent/search/` + `/talent/facets/`, hai endpoint
  // đòi MODULE_TALENT (xem `talent/views.py`). Người chỉ được cấp `rb` vẫn dùng
  // được Tìm kiếm AI (engine RB riêng) nhưng sẽ ăn 403 ở bộ lọc — nên ẩn hẳn tab
  // đó thay vì để họ bấm vào một màn hình luôn báo lỗi.
  //
  // Điều kiện ở đây là module, KHÔNG phải `canRecruiter`: RM thuần không mở được
  // góc nhìn Tuyển dụng (chặn đọc CV) nhưng vẫn có module `talent` và lọc khách
  // hàng đa chiều chính là việc thường ngày của họ.
  const canUseFilter = modules.has("talent");
  const tab = canUseFilter ? parseTab(searchParams.get("tab")) : "ai";
  const perspective = resolvePerspective({
    modules,
    roles,
    param: searchParams.get("perspective"),
    canReadCv,
  });

  // Ghim góc nhìn đã giải quyết vào URL để link chia sẻ / nút quay lại từ Hồ sơ
  // 360° mở đúng chỗ, và để lần sau vào thẳng góc nhìn quen dùng.
  useEffect(() => {
    if (!identity) return;
    if (parsePerspective(searchParams.get("perspective")) === perspective) return;
    setSearchParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        next.set("perspective", perspective);
        return next;
      },
      { replace: true },
    );
  }, [identity, perspective, searchParams, setSearchParams]);

  const switchPerspective = (next: SearchPerspective) => {
    rememberPerspective(next);
    setSearchParams((prev) => {
      const params = new URLSearchParams(prev);
      params.set("perspective", next);
      return params;
    });
  };

  if (session.isLoading) return null;

  if (!canRecruiter && !canProspect) {
    return (
      <div className="empty-box" style={{ margin: "32px" }}>
        Vai trò của bạn chưa được cấp quyền tra cứu kho hồ sơ.
      </div>
    );
  }

  const isProspect = perspective === "prospect";

  return (
    <div className="search-workspace full-page-ai-glow">
      {/* Dynamic Animated AI Glow Spheres */}
      <div className="ai-ambient-glow" aria-hidden="true">
        <div className="glow-orb orb-1" />
        <div className="glow-orb orb-2" />
        <div className="glow-orb orb-3" />
        <div className="glow-orb orb-4" />
      </div>

      {/* Sleek Centered Perspective Switch */}
      {canSwitch && (
        <div className="search-control-toolbar">
          <div className="perspective-segmented-switch" role="tablist" aria-label="Góc nhìn tìm kiếm">
            <button
              type="button"
              role="tab"
              aria-selected={perspective === "recruiter"}
              className={`switch-btn ${perspective === "recruiter" ? "active" : ""}`}
              onClick={() => switchPerspective("recruiter")}
            >
              <span className="switch-icon talent-icon" aria-hidden="true">
                <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2" />
                  <circle cx="9" cy="7" r="4" />
                  <path d="M22 21v-2a4 4 0 0 0-3-3.87" />
                  <path d="M16 3.13a4 4 0 0 1 0 7.75" />
                </svg>
              </span>
              <span className="switch-text">Góc nhìn Tuyển dụng</span>
              <span className="switch-badge badge-recruiter">Recruiter</span>
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={perspective === "prospect"}
              className={`switch-btn ${perspective === "prospect" ? "active" : ""}`}
              onClick={() => switchPerspective("prospect")}
            >
              <span className="switch-icon prospect-icon" aria-hidden="true">
                <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <rect width="20" height="14" x="2" y="7" rx="2" />
                  <path d="M16 7V5a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v2" />
                </svg>
              </span>
              <span className="switch-text">Góc nhìn Khách hàng</span>
              <span className="switch-badge badge-prospect">RM &amp; Sales</span>
            </button>
          </div>
        </div>
      )}

      {tab === "ai"
        ? (isProspect ? <ProspectAiSearch /> : <AiSearch />)
        : <SearchFilterWorkspace perspective={perspective} />}
    </div>
  );
}
