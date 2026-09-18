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
  const { canRecruiter, canProspect, canSwitch } = perspectiveAccess(modules, roles);

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

  const setTab = (next: SearchTab) => {
    setSearchParams((prev) => {
      const params = new URLSearchParams(prev);
      params.set("tab", next);
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
    <div className="search-workspace">
      <div className="search-workspace-head">
        <div className="search-workspace-title">
          <span className="search-workspace-icon">{isProspect ? "💳" : "🎯"}</span>
          <div>
            <h1 className="workspace-main-title">
              {isProspect ? "Tìm Khách Hàng Tiềm Năng" : "Tìm Kiếm Nhân Tài"}
            </h1>
            <p className="workspace-subtitle">
              {isProspect
                ? "Trợ lý AI và bộ lọc đa chiều trên toàn kho hồ sơ — chấm điểm tiềm năng, đề xuất sản phẩm và đẩy cơ hội sang Growth Radar."
                : "Trợ lý AI và bộ lọc đa chiều trên toàn kho hồ sơ — bóc tách JD, đối sánh năng lực và đẩy ứng viên sang đợt tuyển của Talent Radar."}
            </p>
          </div>
        </div>

        {canSwitch && (
          <div className="perspective-segmented-switch">
            <button
              type="button"
              className={`switch-btn ${perspective === "recruiter" ? "active" : ""}`}
              onClick={() => switchPerspective("recruiter")}
            >
              <span className="switch-icon">🎯</span>
              <span className="switch-text">Góc nhìn Tuyển dụng</span>
              <span className="switch-badge">Recruiter</span>
            </button>
            <button
              type="button"
              className={`switch-btn ${perspective === "prospect" ? "active" : ""}`}
              onClick={() => switchPerspective("prospect")}
            >
              <span className="switch-icon">💳</span>
              <span className="switch-text">Góc nhìn Khách hàng</span>
              <span className="switch-badge">RM &amp; Sales</span>
            </button>
          </div>
        )}
      </div>

      <div className="search-mode-tabs">
        <button
          type="button"
          className={`search-mode-tab ${tab === "ai" ? "active" : ""}`}
          onClick={() => setTab("ai")}
        >
          ✨ Tìm kiếm AI
        </button>
        {canUseFilter && (
          <button
            type="button"
            className={`search-mode-tab ${tab === "filter" ? "active" : ""}`}
            onClick={() => setTab("filter")}
          >
            ⚙️ Bộ lọc đa chiều
          </button>
        )}
      </div>

      {tab === "ai"
        ? (isProspect ? <ProspectAiSearch /> : <AiSearch />)
        : <SearchFilterWorkspace perspective={perspective} />}
    </div>
  );
}
