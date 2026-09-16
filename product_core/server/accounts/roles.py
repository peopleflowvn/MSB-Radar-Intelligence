# -*- coding: utf-8 -*-
"""Vai trò và phân quyền theo module (Master Plan mục 38, PHASE 5B).

Vai trò lưu bằng **Django Group** trùng tên khoá vai trò, không phải một trường
`role` riêng. Ba lý do:

  • Một người có thể kiêm nhiều vai trò (Recruiter kiêm Manager) — Group cho
    quan hệ nhiều-nhiều sẵn, còn trường `role` thì phải tự dựng lại.
  • Giao diện gán vai trò trong trang quản trị Django có sẵn, không phải viết.
  • Không đẻ ra một hệ thống phân quyền song song bên cạnh hệ thống Django đã có.

Phân quyền ở đây là **tầng module** (vào được Talent Radar hay không). Phân quyền
tầng bản ghi (Hiring Manager chỉ thấy ứng viên liên quan nhu cầu của mình) là
phần hoãn sau hackathon — xem docs/ACCESS_CONTROL.md mục 5.
"""
from django.contrib.auth.models import Group

# --- Vai trò ---
ADMIN = "admin"
EDGE_OPERATOR = "edge_operator"
RECRUITER = "recruiter"
HIRING_MANAGER = "hiring_manager"
RB_SALES = "rb_sales"
MANAGER = "manager"

ROLE_LABELS = {
    ADMIN: "Quản trị hệ thống",
    EDGE_OPERATOR: "Vận hành Edge",
    RECRUITER: "Chuyên viên Tuyển dụng",
    HIRING_MANAGER: "Trưởng bộ phận tuyển người",
    RB_SALES: "Sales/RM Khách hàng cá nhân",
    MANAGER: "Quản lý",
}
ALL_ROLES = tuple(ROLE_LABELS)

# --- Module ---
MODULE_TALENT = "talent"
MODULE_RB = "rb"
MODULE_SOCIAL = "social"
MODULE_EDGE = "edge_ops"
MODULE_INTAKE = "people_intake"
MODULE_AI_SETTINGS = "ai_settings"
MODULE_REPORTS = "reports"
MODULE_ADMIN = "admin_console"
MODULE_KNOWLEDGE = "knowledge"

MODULE_LABELS = {
    MODULE_TALENT: "Talent Radar",
    MODULE_RB: "RB Radar",
    MODULE_SOCIAL: "Social Radar",
    MODULE_EDGE: "Vận hành Edge",
    MODULE_INTAKE: "Nhập liệu ứng viên",
    MODULE_AI_SETTINGS: "Cài đặt AI",
    MODULE_REPORTS: "Vận hành & Báo cáo",
    MODULE_ADMIN: "Quản trị hệ thống",
    MODULE_KNOWLEDGE: "Tri thức nội bộ",
}
ALL_MODULES = tuple(MODULE_LABELS)

# Ô (vai trò, module) KHÔNG cho Admin console sửa qua giao diện — để không ai tự
# khoá mình ra khỏi trang quản trị.
LOCKED_GRANTS = frozenset({(ADMIN, MODULE_ADMIN)})

# Ma trận vai trò -> module vào được.
#
# RB Sales CÓ quyền đọc Talent theo quyết định ngày 19/08/2026 (xem
# docs/ACCESS_CONTROL.md mục 4.3). Truy cập liên nghiệp vụ này được `AccessLog`
# đánh dấu riêng bằng cờ `cross_domain` — chính vì nó là thứ kiểm toán soi đầu tiên.
#
# `reports` (trang vận hành) chỉ cấp cho Admin và Manager — hai vai trò duy
# nhất mà lý do tồn tại là nhìn xuyên suốt nhiều nghiệp vụ. Trang đó gộp cả số
# Talent lẫn số RB trên cùng một màn hình; cấp cho Recruiter hay RB Sales sẽ
# cho họ thấy số của nghiệp vụ kia theo một đường vòng mà quyết định 19/08
# (RB Sales đọc Talent) không hề tính tới.
# Đây là ma trận MẶC ĐỊNH, đóng vai trò sàn an toàn. Admin có thể phủ lên nó
# (cấp thêm / thu hồi) qua bảng `accounts.models.RoleModuleAccess`; xem `modules_of`.
#
# `people_intake` mặc định chỉ cấp cho Admin và Vận hành Edge — giữ đúng hành vi
# trước khi có tính năng. Muốn cho Recruiter/Manager nhập liệu thì Admin tự bật
# trong trang Quản trị → Phân quyền Module theo Vai trò.
#
# `knowledge` (tài liệu tri thức nội bộ — quy trình/quyết định/hướng dẫn):
# Recruiter được cấp mặc định vì đây chính là người hỏi Radar các câu chính
# sách/quy trình tuyển dụng (vd "thể lệ giới thiệu nội bộ ứng viên") — thiếu
# quyền này khiến `knowledge_sources()` luôn trả rỗng và Radar rơi thẳng vào
# nhánh tra web, dù tài liệu nội bộ đã có sẵn (đo trên production 16/09). Nội
# dung thật sự nhạy cảm (lương thưởng, quyết định nhân sự) là chuyện phân loại
# ở TỪNG tài liệu trong `/knowledge`, không phải lý do chặn cả module với vai
# trò dùng nó nhiều nhất. Vai trò khác vẫn mặc định không có — cấp thêm qua
# trang Quản trị → Phân quyền Module theo Vai trò khi cần.
ROLE_MODULES = {
    ADMIN: {MODULE_TALENT, MODULE_RB, MODULE_SOCIAL, MODULE_EDGE, MODULE_INTAKE,
           MODULE_AI_SETTINGS, MODULE_REPORTS, MODULE_ADMIN, MODULE_KNOWLEDGE},
    EDGE_OPERATOR: {MODULE_EDGE, MODULE_INTAKE},
    RECRUITER: {MODULE_TALENT, MODULE_SOCIAL, MODULE_KNOWLEDGE},
    HIRING_MANAGER: {MODULE_TALENT},
    RB_SALES: {MODULE_RB, MODULE_TALENT, MODULE_SOCIAL},
    MANAGER: {MODULE_TALENT, MODULE_RB, MODULE_REPORTS},
}

# Nghiệp vụ "gốc" của mỗi vai trò, dùng để phát hiện truy cập liên nghiệp vụ.
ROLE_HOME_DOMAIN = {
    RECRUITER: MODULE_TALENT,
    HIRING_MANAGER: MODULE_TALENT,
    RB_SALES: MODULE_RB,
    EDGE_OPERATOR: MODULE_EDGE,
}


def ensure_groups():
    """Tạo đủ Group cho các vai trò. Idempotent, gọi lúc nào cũng được."""
    for name in ALL_ROLES:
        Group.objects.get_or_create(name=name)


def roles_of(user):
    """Các vai trò của một người. Superuser luôn là admin."""
    if user is None or not getattr(user, "is_authenticated", False):
        return set()
    names = set(user.groups.values_list("name", flat=True)) & set(ALL_ROLES)
    if user.is_superuser:
        names.add(ADMIN)
    return names


def default_modules_for_role(role):
    return set(ROLE_MODULES.get(role, set()))


def role_module_overrides():
    """{(role, module): allowed} — các Ô Admin đã đổi so với mặc định.

    Truy vấn nhẹ (bảng chỉ chứa các Ô đã đổi). Import trong hàm để không tạo vòng
    phụ thuộc lúc nạp app.
    """
    try:
        from .models import RoleModuleAccess
    except Exception:                       # noqa: BLE001 - lúc migrate lần đầu
        return {}
    return {(row.role, row.module): row.allowed
            for row in RoleModuleAccess.objects.all()}


def modules_for_role(role, overrides=None):
    """Module một vai trò vào được = mặc định + phủ của Admin."""
    if overrides is None:
        overrides = role_module_overrides()
    allowed = default_modules_for_role(role)
    for module in ALL_MODULES:
        state = overrides.get((role, module))
        if state is True:
            allowed.add(module)
        elif state is False:
            allowed.discard(module)
    # Admin không bao giờ mất trang quản trị, dù bảng override có gì.
    if role == ADMIN:
        allowed.add(MODULE_ADMIN)
    return allowed


def modules_of(user):
    """Tập module người này vào được (đã tính phủ quyền của Admin)."""
    user_roles = roles_of(user)
    if not user_roles:
        return set()
    overrides = role_module_overrides()
    allowed = set()
    for role in user_roles:
        allowed |= modules_for_role(role, overrides)
    return allowed


def can_access(user, module):
    return module in modules_of(user)


def home_domains(user):
    """Nghiệp vụ gốc của người này — để biết đâu là truy cập liên nghiệp vụ."""
    return {ROLE_HOME_DOMAIN[role] for role in roles_of(user)
            if role in ROLE_HOME_DOMAIN}


def is_cross_domain(user, module):
    """Người này đọc dữ liệu của nghiệp vụ khác nghiệp vụ gốc của mình?

    Ví dụ điển hình sau quyết định 19/08: RB Sales đọc hồ sơ ứng viên. Được phép,
    nhưng phải để lại dấu vết phân biệt được với truy cập thông thường.

    Không có nghiệp vụ gốc nào (Admin, Manager) thì không tính là liên nghiệp vụ —
    họ vốn được thiết kế để nhìn xuyên suốt.
    """
    homes = home_domains(user)
    if not homes or module not in MODULE_LABELS:
        return False
    if module in (MODULE_SOCIAL, MODULE_EDGE, MODULE_AI_SETTINGS):
        return False
    return module not in homes
