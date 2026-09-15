# -*- coding: utf-8 -*-
"""Cấu hình MSB Radar Hub.

Một file settings, điều khiển bằng biến môi trường. Không tách base/dev/prod:
với dự án ở quy mô này, ba file settings kế thừa nhau chỉ tạo thêm chỗ để hai
môi trường lệch nhau một cách âm thầm.

CSDL chọn theo DATABASE_URL:
    chưa đặt  -> SQLite cạnh manage.py   (dev trên máy, chạy được ngay)
    đã đặt    -> PostgreSQL              (Docker Compose, máy chủ thật)

Nhờ vậy lập trình viên chạy và chạy test được mà không cần cài Postgres, còn
triển khai thật vẫn đúng PostgreSQL như Master Plan mục 7.
"""
import os
import sys
from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env(
    DEBUG=(bool, False),
    ALLOWED_HOSTS=(list, ["localhost", "127.0.0.1"]),
    CORS_ALLOWED_ORIGINS=(list, ["http://localhost:5173"]),
)
# Đọc `server/.env` trước, rồi tới `.env` ở gốc repo.
#
# Docker Compose vốn chỉ đọc file ở gốc repo, còn Django thì mặc định đọc cạnh
# manage.py. Chỉ hỗ trợ một trong hai nghĩa là có người sẽ sửa đúng biến ở sai
# file rồi mất một buổi tìm hiểu vì sao không ăn. Đọc cả hai, file gần hơn thắng.
for _env_file in (BASE_DIR / ".env", BASE_DIR.parent / ".env"):
    if _env_file.is_file():
        environ.Env.read_env(_env_file, overwrite=False)

# SECRET_KEY chỉ được phép có mặc định khi DEBUG. Ở chế độ thật mà thiếu thì
# phải nổ ngay lúc khởi động, không được âm thầm chạy bằng khoá ai cũng biết.
DEBUG = env("DEBUG")
if DEBUG:
    SECRET_KEY = env("SECRET_KEY", default="dev-only-khong-dung-cho-that")
else:
    SECRET_KEY = env("SECRET_KEY")

ALLOWED_HOSTS = env("ALLOWED_HOSTS")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "drf_spectacular",
    "corsheaders",
    "accounts",
    "core",
    "people",
    "ai",
    "intel",
    "knowledge",
    "talent",
    "intake",
    "hiring",
    "social",
    "rb",
    "agents",
    "reports",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    # Sau AuthenticationMiddleware vì nó cần request.user.
    "accounts.middleware.AccessLogMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
# Chạy thật bằng ASGI (Master Plan §3.2): SSE cho luồng Thinking cần async.
# WSGI_APPLICATION vẫn giữ để `manage.py runserver` và test đồng bộ chạy như cũ.
ASGI_APPLICATION = "config.asgi.application"

TEMPLATES = [{
    "BACKEND": "django.template.backends.django.DjangoTemplates",
    "DIRS": [],
    "APP_DIRS": True,
    "OPTIONS": {"context_processors": [
        "django.template.context_processors.debug",
        "django.template.context_processors.request",
        "django.contrib.auth.context_processors.auth",
        "django.contrib.messages.context_processors.messages",
    ]},
}]

_database_url = env("DATABASE_URL", default="")
if _database_url:
    DATABASES = {"default": env.db_url_config(_database_url)}
    DATABASES["default"].setdefault("CONN_MAX_AGE", 60)
else:
    DATABASES = {"default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "hub_dev.sqlite3",
    }}

# Thư mục chứa `index.html` đã build của giao diện.
#
# Django phải đọc được tệp này để chèn thẻ meta từ CSDL (xem
# `accounts/spa_views.py`). Trên container, `web/dist` được mount vào `/srv/web`;
# ở máy dev thì nằm cạnh `server/`.
WEB_DIST_DIR = env.str("WEB_DIST_DIR", default=str(BASE_DIR.parent / "web" / "dist"))

# URL gốc công khai — dùng để biến `og:image` thành URL tuyệt đối. Crawler mạng
# xã hội bỏ qua đường dẫn tương đối mà không báo lỗi gì.
PUBLIC_BASE_URL = env.str("PUBLIC_BASE_URL", default="")

# Cache nằm trên chính PostgreSQL, không phải trong bộ nhớ tiến trình.
#
# Hub chạy gunicorn `--workers 3`: cache locmem (mặc định của Django) là RIÊNG
# cho từng worker, nên cùng một câu hỏi lặp lại chỉ trúng 1/3 số lần — đúng chỗ
# đắt nhất mà lại hay trượt. Bảng CSDL thì cả ba worker dùng chung.
#
# Cố ý KHÔNG thêm Redis: VPS 1 vCPU / 5.8GB, thêm một dịch vụ nữa để cache vài
# chục mục là đổi lấy một thứ phải vận hành.
CACHES = {"default": {
    "BACKEND": "django.core.cache.backends.db.DatabaseCache",
    "LOCATION": "radar_cache",
    "TIMEOUT": 6 * 3600,
    "OPTIONS": {"MAX_ENTRIES": 5000, "CULL_FREQUENCY": 4},
}}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "vi"
TIME_ZONE = "Asia/Ho_Chi_Minh"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

REST_FRAMEWORK = {
    # Mặc định KHÔNG cho ai vào. Từng view phải mở quyền một cách tường minh —
    # quên khai quyền thì bị chặn, chứ không phải bị lộ.
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "core.auth.EdgeApiKeyAuthentication",
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "UNAUTHENTICATED_USER": None,
    "DEFAULT_THROTTLE_RATES": {"login": "10/minute", "email_otp_request": "10/minute",
                                "email_otp_verify": "20/minute"},
    # Sinh schema OpenAPI thẳng từ serializer/view đã có — không phải viết tay
    # một tài liệu thứ hai rồi để nó lệch dần với code thật.
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
}
if DEBUG:
    REST_FRAMEWORK["DEFAULT_RENDERER_CLASSES"].append(
        "rest_framework.renderers.BrowsableAPIRenderer")

# Tài liệu API tương tác, dùng cho hai nhóm đọc rất khác nhau:
#   - đội IT của một doanh nghiệp khác muốn tích hợp Edge/hệ thống của họ,
#     không có quyền đọc mã nguồn;
#   - chính đội mình, khi quay lại sau vài tháng và quên hình dạng payload.
SPECTACULAR_SETTINGS = {
    "TITLE": "MSB Radar Hub API",
    "DESCRIPTION": (
        "API của Hub — nơi Edge (ứng dụng thu thập chạy trên máy nhân viên) "
        "đồng bộ dữ liệu lên, và nơi giao diện quản trị đọc/ghi nghiệp vụ.\n\n"
        "Xác thực: `Authorization: Bearer <api_key>` kèm `X-Edge-Id: <mã edge>` "
        "cho các endpoint `/api/v1/edge/...` (dành cho Edge); phiên đăng nhập "
        "(cookie) cho các endpoint còn lại (dành cho giao diện quản trị/nghiệp vụ)."
    ),
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
    # Không tự sinh view cho những app chưa có serializer ổn định — schema rác
    # còn tệ hơn không có schema, vì người đọc tin nó là hợp đồng thật.
    "SCHEMA_PATH_PREFIX": "/api/v1",
}

CORS_ALLOWED_ORIGINS = env("CORS_ALLOWED_ORIGINS")

if DEBUG:
    # Django kiểm tra header Origin cho mọi yêu cầu POST. Lúc dev, giao diện chạy
    # ở cổng Vite (5173) và proxy sang đây, nên Origin không khớp và MỌI thao tác
    # ghi đều trả "CSRF Failed: Origin checking failed".
    #
    # Đăng nhập vẫn chạy nên lỗi này rất dễ bỏ sót: DRF chỉ bắt CSRF khi đã có
    # phiên, mà lúc đăng nhập thì chưa có. Nó chỉ nổ ở thao tác ghi TIẾP THEO.
    CSRF_TRUSTED_ORIGINS = ["http://localhost:5173", "http://127.0.0.1:5173",
                            "http://localhost:8000", "http://127.0.0.1:8000"]

# Edge gửi cả lô bản ghi trong một yêu cầu; mặc định 2,5 MB của Django là chật.
DATA_UPLOAD_MAX_MEMORY_SIZE = 20 * 1024 * 1024

# URL icon ứng dụng công khai phục vụ nhúng vào Email OTP HTML
PUBLIC_APP_ICON_URL = env("PUBLIC_APP_ICON_URL", default="https://dev-radar.tunghr.io.vn/apple-touch-icon.png")

# Số bản ghi tối đa Hub nhận trong một lô. Edge mặc định gửi 50.
EDGE_SYNC_MAX_BATCH = env.int("EDGE_SYNC_MAX_BATCH", default=500)

# --- Lưu trữ file (CV, ảnh, tài liệu) ---
# Mặc định 'local' = ổ đĩa VPS Oracle. Đổi sang 'r2' bằng biến môi trường khi
# cần nhân bản hoặc phục vụ file không tốn băng thông VPS. Xem core/storage.py.
FILE_STORAGE = {
    "backend": env("FILE_STORAGE_BACKEND", default="local"),
    "root": env("FILE_STORAGE_ROOT", default=str(BASE_DIR / "filestore")),
    "bucket": env("R2_BUCKET", default=""),
    "account_id": env("R2_ACCOUNT_ID", default=""),
    "access_key": env("R2_ACCESS_KEY", default=""),
    "secret_key": env("R2_SECRET_KEY", default=""),
    "endpoint": env("R2_ENDPOINT", default=""),
}

# LibreOffice headless chuyển DOC/DOCX/XLSX/PPTX sang PDF preview. Có thể ghi đè đường
# dẫn đầy đủ trên Windows/production bằng OFFICE_PREVIEW_COMMAND.
OFFICE_PREVIEW_COMMAND = env("OFFICE_PREVIEW_COMMAND", default="soffice")

# Phiên đăng nhập tồn tại đúng một tuần kể từ lúc xác thực, kể cả khi đóng/mở trình duyệt.
SESSION_COOKIE_AGE = env.int("SESSION_COOKIE_AGE_SECONDS", default=60 * 60 * 24 * 7)
SESSION_SAVE_EVERY_REQUEST = False
SESSION_EXPIRE_AT_BROWSER_CLOSE = False

# --- Nhà cung cấp LLM ---
# Cấu hình đọc thẳng từ os.environ trong ai/router.py chứ không qua đây, để lớp
# đó dùng được cả ngoài Django (script, worker). Xem docs/AI_PROVIDERS.md.

# --- Trợ lý Radar (Master Plan §10.3, §10.4.5, §21.5) ---
# Số lượt hội thoại gần nhất đưa thẳng vào context. Phần cũ hơn được nén thành
# summary có cấu trúc, nên tăng cửa sổ này không đồng nghĩa gửi toàn bộ lịch sử.
ASSISTANT_RECENT_TURNS = env.int("ASSISTANT_RECENT_TURNS", default=16)
# reasoning_trace giữ ngắn hơn message; lệnh prune_reasoning_traces dùng ngưỡng này.
ASSISTANT_REASONING_RETENTION_DAYS = env.int(
    "ASSISTANT_REASONING_RETENTION_DAYS", default=60)
# Hội thoại archive không hoạt động quá hạn này sẽ bị prune_conversations xoá.
ASSISTANT_CONVERSATION_RETENTION_DAYS = env.int(
    "ASSISTANT_CONVERSATION_RETENTION_DAYS", default=365)

# Intent router: một lượt gọi model nhỏ phân loại câu hỏi (search / hội thoại /
# web) thay cho heuristic. Tắt -> lùi hoàn toàn về heuristic cũ.
ASSISTANT_INTENT_ROUTER = env.bool("ASSISTANT_INTENT_ROUTER", default=True)
# Web search: cho Radar tra web khi câu hỏi cần dữ kiện ngoài kho. Độc lập với
# nhà cung cấp LLM — backend generic (Tavily/Brave/Google CSE) trả kết quả thô,
# bộ não đang dùng tự tổng hợp; Gemini grounding là fallback tự tìm + tự trả lời.
# MẶC ĐỊNH TẮT — bật tường minh sau khi chấp nhận việc gửi câu hỏi người dùng ra
# ngoài. Câu hỏi có PII (email/điện thoại/số định danh) luôn bị chặn khỏi nhánh này.
ASSISTANT_WEB_SEARCH = env.bool("ASSISTANT_WEB_SEARCH", default=False)
# Thứ tự thử backend web (phân tách bằng dấu phẩy). Rỗng → tavily,brave,
# google_cse,gemini_grounding. Đặt tên backend không hợp lệ sẽ bị bỏ qua.
ASSISTANT_WEBSEARCH_BACKENDS = env.str("ASSISTANT_WEBSEARCH_BACKENDS", default="")
# Tri thức nội bộ: chèn trích đoạn tài liệu nội bộ (knowledge/models.py) liên
# quan vào prompt hội thoại, để Radar trả lời quy trình/chính sách công ty theo
# ĐÚNG tài liệu thay vì theo kiến thức chung của model. Chỉ chạy cho người có
# module `knowledge` và chỉ tìm trong tài liệu nội bộ (không kéo CV vào ngữ
# cảnh). Bật sẵn vì không có tài liệu nào thì nó tự là no-op.
ASSISTANT_KNOWLEDGE_CONTEXT = env.bool("ASSISTANT_KNOWLEDGE_CONTEXT", default=True)

# Tool-calling (kỹ năng): cho phép model tự gọi tool server-owned trong lượt hội
# thoại (ai/toolset.py + ai/tool_handlers.py). Tool đều chỉ-đọc / chỉ-đề-xuất,
# lọc theo RBAC trước khi model thấy. MẶC ĐỊNH TẮT — bật tường minh sau khi soát.
ASSISTANT_TOOLS = env.bool("ASSISTANT_TOOLS", default=False)
# Per-process Talent worker cap. Timed-out provider calls retain their slot until exit.
ANSWER_RUNNER_MAX_WORKERS = max(1, env.int("ANSWER_RUNNER_MAX_WORKERS", default=8))
# Trần số vòng gọi tool trong một lượt (chống lặp vô hạn / chi phí).
ASSISTANT_TOOL_MAX_STEPS = env.int("ASSISTANT_TOOL_MAX_STEPS", default=4)
# Tool tier 3 (sinh nội dung / tra ngoài: draft_outreach, enrich_company_from_web).
# Tách cờ riêng — §19: mỗi kỹ năng hướng ngoại phê duyệt riêng. Không gửi/đăng gì.
ASSISTANT_TOOLS_TIER3 = env.bool("ASSISTANT_TOOLS_TIER3", default=False)

# Agent core dạng đồ thị (ai/graph_agent.py, engine ai/graph.py — tự viết, 0 dep)
# thay vòng lặp tay ai/agent.py. MẶC ĐỊNH TẮT — bật để đối chiếu rồi chuyển hẳn.
ASSISTANT_GRAPH = env.bool("ASSISTANT_GRAPH", default=False)

# --- People Intelligence: fact/provenance + canonical (Master Plan §5–7, §21) ---
# Ingest tự xếp hàng extraction cho mỗi Person có dữ liệu mới. Trước đây mặc
# định TẮT (cổng phê duyệt §19) và không có worker nào chạy nền, nên trên thực
# tế Hub KHÔNG hề dùng AI với dữ liệu mới: đo trên CSDL thật được 1 ExtractionRun
# và 0 fact `source_kind=ai`. Enqueue vẫn chỉ là xếp hàng — worker mới là chỗ gọi AI.
INTEL_AUTO_ENQUEUE_EXTRACTION = env.bool("INTEL_AUTO_ENQUEUE_EXTRACTION", default=True)
# Worker nền trong tiến trình web (core/worker.py) — thứ thực sự gọi AI. Tắt cờ
# này khi muốn tách ra chạy riêng bằng `run_extraction_worker`/`parse_missing_cvs`.
HUB_BACKGROUND_WORKER = env.bool("HUB_BACKGROUND_WORKER", default=True)
# Search đọc bộ lọc canonical; tắt để quay lại hành vi cũ hoàn toàn.
INTEL_CANONICAL_SEARCH = env.bool("INTEL_CANONICAL_SEARCH", default=True)

# Tìm người bằng AI: truy hồi MỀM — tiêu chí chuỗi (địa điểm, số năm, công ty,
# từ khoá) chỉ dùng để MỞ RỘNG pool, KHÔNG loại cứng ở SQL. scoring.py chấm điểm
# và AI xếp hạng + giải thích vì sao mỗi hồ sơ có trong danh sách / còn lệch gì.
# =0 để quay lại lọc cứng như cũ.
TALENT_SOFT_RETRIEVAL = env.bool("TALENT_SOFT_RETRIEVAL", default=True)

# AI-native: ở lượt "sâu", KHÔNG chấm điểm tất định — đưa toàn bộ dữ liệu có thật
# (profile + ExtractedFact + trích đoạn CV) của tập hồ sơ truy hồi rộng cho MỘT
# lượt LLM để tự phân tích, khoanh vùng, chọn, xếp hạng, giải thích. LLM lỗi →
# tự lùi về scoring.py. Đánh đổi §23 (thứ tự không còn tất định) — chủ dự án chọn.
TALENT_AI_NATIVE_SEARCH = env.bool("TALENT_AI_NATIVE_SEARCH", default=True)

# Ngưỡng điểm tất định tối thiểu để một hồ sơ "đáng xem" ở nhánh chấm điểm (không
# áp cho nhánh AI-native). Kho thật để trống nhiều trường cấu trúc nên bộ chấm
# điểm hay floor cả danh sách về 0 — hạ 0.25 → 0.15, cấu hình được.
TALENT_SCORE_FLOOR = env.float("TALENT_SCORE_FLOOR", default=0.15)

# Ngân sách dossier cho một lượt rerank AI-native (§18 mục 8 — sẽ thay bằng
# token-budget động ở GĐ4). Kẹp trong code: pool 10..80, cv_chars 300..3000.
TALENT_AI_RERANK_POOL = env.int("TALENT_AI_RERANK_POOL", default=60)
TALENT_AI_RERANK_CV_CHARS = env.int("TALENT_AI_RERANK_CV_CHARS", default=1500)

# Số chiều YÊU CẦU cho API embedding cần nêu rõ (Gemini output_dimensionality).
# Cột vector để biến chiều nên đổi số này không cần migrate.
TALENT_EMBEDDING_DIMENSIONS = env.int("TALENT_EMBEDDING_DIMENSIONS", default=1536)

# Endpoint embedding TỰ HOST (OpenAI-compatible /embeddings) — ưu tiên hơn route
# DB. Không quota, không phí/lượt, CV không rời máy chủ. Trỏ vào container nội bộ
# (vd Ollama: http://ollama:11434/v1 model bge-m3; hoặc HF TEI). Trống = dùng
# route `talent_embedding` trong /settings.
TALENT_EMBEDDING_BASE_URL = env("TALENT_EMBEDDING_BASE_URL", default="")
TALENT_EMBEDDING_MODEL = env("TALENT_EMBEDDING_MODEL", default="")
TALENT_EMBEDDING_API_KEY = env("TALENT_EMBEDDING_API_KEY", default="")
INTAKE_STAGING_ROOT = env("INTAKE_STAGING_ROOT", default=str(BASE_DIR / "var" / "intake-staging"))

# Lập chỉ mục tìm kiếm ngay khi lưu hồ sơ/tài liệu. Đúng cho luồng thường (dữ
# liệu mới tìm được ngay). TẮT khi nạp hàng loạt (import triệu bản ghi) rồi chạy
# `rebuild_talent_vector_index` một lượt — nếu không, mỗi bản ghi bị ghi nhiều lần.
TALENT_INDEX_ON_SAVE = env.bool("TALENT_INDEX_ON_SAVE", default=True)

# Private bridge used by MSB Radar Intelligence V2. These credentials are
# intentionally independent from user sessions and third-party AI provider keys.
INTELLIGENCE_SERVICE_TOKEN = env("INTELLIGENCE_SERVICE_TOKEN", default="")
INTELLIGENCE_INDEX_SCOPE_TOKEN = env("INTELLIGENCE_INDEX_SCOPE_TOKEN", default="")
INTELLIGENCE_SCOPE_MAX_AGE_SECONDS = env.int(
    "INTELLIGENCE_SCOPE_MAX_AGE_SECONDS", default=300)
INTELLIGENCE_BASE_URL = env("INTELLIGENCE_BASE_URL", default="http://intelligence:8081")
INTELLIGENCE_REQUEST_TIMEOUT_SECONDS = env.float(
    "INTELLIGENCE_REQUEST_TIMEOUT_SECONDS", default=90.0)
INTELLIGENCE_V2_PRIMARY = env.bool("INTELLIGENCE_V2_PRIMARY", default=False)

if not DEBUG:
    SECURE_SSL_REDIRECT = env.bool("SECURE_SSL_REDIRECT", default=True)
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = 60 * 60 * 24 * 30
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = env.bool("SECURE_HSTS_PRELOAD", default=True)
    # Caddy kết thúc TLS rồi chuyển tiếp; không có dòng này Django tưởng
    # mọi yêu cầu đều là HTTP và rơi vào vòng lặp chuyển hướng.
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    CSRF_TRUSTED_ORIGINS = env.list("CSRF_TRUSTED_ORIGINS", default=[])

# Test client gọi URL nội bộ bằng HTTP. Không để biến môi trường production làm
# toàn bộ assertion API biến thành redirect 301.
if "test" in sys.argv:
    SECURE_SSL_REDIRECT = False

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"simple": {"format": "[{asctime}] {levelname} {name}: {message}",
                              "style": "{"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "simple"}},
    "root": {"handlers": ["console"], "level": os.environ.get("LOG_LEVEL", "INFO")},
}
