# -*- coding: utf-8 -*-
"""Nhớ lại kết quả ②③④ cho câu hỏi đã gặp. Khung dùng chung mọi domain.

Đo trên kho Talent thật: mỗi lượt hỏi tốn ~38.700 token nạp vào + 6 lượt gọi
model, và **③ chiếm 75%** trong đó. Hỏi lại đúng một câu là trả lại toàn bộ số
đó. Growth có cùng hình dạng chi phí vì chạy cùng dây chuyền.

Cắt ở ranh giới ②③④ chứ không phải cả lượt:

* ② tất định với cùng bộ truy vấn; ③ chạy ở nhiệt độ thấp nên gần như tất định;
  ④ là CODE thuần.
* ⑤ thì **không** cache: nó phụ thuộc lịch sử hội thoại và những điều người dùng
  đã dặn, nên cùng một danh sách người vẫn phải viết lại cho đúng ngữ cảnh lượt
  này. Chỉ cache ⑤ mới là chỗ người dùng nhận ra câu trả lời "bị lặp".

## Bốn vân tay, và vì sao thiếu cái nào cũng hỏng

    corpus      dữ liệu đổi ⇒ mục cũ tự hết hiệu lực, không ai phải nhớ đi xoá
    execution   prompt / tuyến model đổi ⇒ không phục vụ câu trả lời sinh ra
                dưới một hợp đồng cũ suốt sáu tiếng
    permission  quyền của người hỏi đổi ⇒ không dùng lại kết quả của phạm vi cũ
    context     "so sánh hai người đầu" nghĩa khác nhau tuỳ danh sách lượt trước

Ba cái đầu là **hàm của hệ thống**, cái cuối là hàm của cuộc trò chuyện.

**Phần phụ thuộc nghiệp vụ** nằm gọn trong `TurnCache.__init__`: vân tay kho lấy
ở đâu, prompt nào của domain phải nằm trong vân tay thực thi, tác vụ định tuyến
nào có ảnh hưởng, và một dòng đã lưu dựng lại thành đối tượng phán đoán gì. Mọi
thứ còn lại trong file này đúng cho cả hai domain.
"""
from __future__ import annotations

import hashlib
import json
import logging
import threading

from django.core.cache import cache

log = logging.getLogger(__name__)

#: 6 giờ. Vân tay kho đã lo phần dữ liệu đổi; TTL chỉ để dọn rác và để một lần
#: ③ phán đoán lệch không đóng đinh vĩnh viễn.
TTL_SECONDS = 6 * 3600


def digest(value):
    return hashlib.sha256(json.dumps(
        value, ensure_ascii=False, sort_keys=True, default=str,
        separators=(",", ":")).encode("utf-8")).hexdigest()[:24]


def permission_fingerprint(user):
    """Định danh/vai trò/phạm vi module hiện tại của người dùng — không bao giờ PII."""
    if user is None:
        return digest({"user": None})
    try:
        from accounts import roles
        user_roles = roles.roles_of(user)
        overrides = roles.role_module_overrides()
        modules = set()
        for role in user_roles:
            modules |= roles.modules_for_role(role, overrides)
        return digest({
            "authenticated": bool(getattr(user, "is_authenticated", False)),
            "active": bool(getattr(user, "is_active", False)),
            "superuser": bool(getattr(user, "is_superuser", False)),
            "roles": sorted(user_roles),
            "modules": sorted(modules),
        })
    except Exception:                              # noqa: BLE001
        log.warning("answer.cache: không lấy được dấu quyền, bỏ qua cache",
                    exc_info=True)
        return ""


def context_marker(envelope):
    """Dấu ngữ cảnh: danh sách người của lượt trước và những gì đã dặn.

    Cùng một câu chữ ("so sánh hai người đầu") nghĩa khác nhau tuỳ danh sách
    đang nói tới, nên nó phải nằm trong khoá.
    """
    projection = getattr(envelope, "projection", None)
    last = dict(getattr(projection, "last_result", None) or {}) if projection else {}
    ids = [item.get("id") or item.get("person_id")
           for item in (last.get("items") or [])]
    # Thứ tự là một phần của định danh: [A, B] và [B, A] hiểu "người thứ hai"
    # khác nhau.
    return {"people": [str(i) for i in ids if i],
            "criteria": getattr(projection, "active_criteria", {}) or {},
            "patches": getattr(projection, "constraint_patches", []) or [],
            "mentioned": getattr(projection, "mentioned_ids", []) or [],
            "memories": getattr(projection, "memories", []) or [],
            "summary": getattr(projection, "summary", "") or "",
            "recent": getattr(projection, "recent_turns", []) or []}


def plan_marker(query_plan):
    """Đầu vào đã chuẩn hoá có thể đổi kết quả truy hồi hoặc phán đoán.

    Đọc bằng `getattr` chứ không ép một lớp kế hoạch cụ thể: kế hoạch của Talent
    và của Growth không cùng tập trường, và trường riêng của mỗi bên được domain
    tự thêm qua `TurnCache(extra_plan_marker=...)`.
    """
    if query_plan is None:
        return {}

    def text(value):
        return " ".join(str(value or "").split()).casefold()

    def items(values):
        return sorted(set(filter(None, (text(v) for v in (values or [])))))

    sort_by = getattr(query_plan, "sort_by", None) or {}
    return {
        "shape": text(getattr(query_plan, "shape", "")),
        "need": text(getattr(query_plan, "information_need", "")),
        "must": items(getattr(query_plan, "must_have", [])),
        "should": items(getattr(query_plan, "should_have", [])),
        "extract": items(getattr(query_plan, "extract", [])),
        "queries": items(getattr(query_plan, "search_queries", [])),
        # limit đổi kích thước pool truy hồi, nên nó không chỉ là trình bày.
        "limit": int(getattr(query_plan, "limit", 0) or 0),
        "sort": {"key": text(sort_by.get("key")), "dir": text(sort_by.get("dir"))}
                if sort_by else None,
    }


class TurnCache:
    """Cache một lượt hỏi, buộc vào đúng domain qua các tham số khởi tạo.

    `prefix`             tiền tố khoá; đổi khi khuôn dữ liệu lưu đổi, để mục cũ
                         không bị đọc bằng khuôn mới.
    `prompts`            `{tên: chuỗi prompt}`, HOẶC một hàm không tham số trả về
                         dict đó. Đổi prompt là đổi hợp đồng, mục cũ phải hết
                         hiệu lực ngay chứ không đợi hết TTL.

                         Dùng hàm khi prompt nằm ở module import ngược lên gói
                         này (vòng import), và khi test thay prompt bằng
                         `mock.patch.object` để kiểm đúng việc đổi prompt phải
                         làm cache hết hiệu lực — chốt giá trị lúc khởi tạo thì
                         phép kiểm ấy luôn xanh một cách giả tạo.
    `tasks`              tên các tác vụ định tuyến có ảnh hưởng tới kết quả.
    `corpus_fingerprint` hàm không tham số, trả vân tay dữ liệu của domain.
    `row_to_judgement`   dựng lại một phán đoán từ dòng đã lưu.
    `extra_plan_marker`  (tuỳ chọn) trường riêng của kế hoạch domain này.
    """

    def __init__(self, *, prefix, prompts, tasks, corpus_fingerprint,
                 row_to_judgement, extra_plan_marker=None, ttl=TTL_SECONDS):
        self.prefix = prefix
        self._prompts = prompts
        self.tasks = tuple(tasks)
        self.corpus_fingerprint = corpus_fingerprint
        self.row_to_judgement = row_to_judgement
        self.extra_plan_marker = extra_plan_marker
        self.ttl = ttl
        self._execution_cache = {"marker": None, "value": ""}
        self._execution_lock = threading.Lock()

    @property
    def prompts(self):
        """Prompt hiện tại của domain — gọi lại mỗi lần, xem `__init__`."""
        return dict(self._prompts() if callable(self._prompts) else self._prompts)

    # -------------------------------------------------------------- vân tay

    def execution_fingerprint(self):
        """Đầu vào ngữ nghĩa của phần được cache, KHÔNG kèm bí mật.

        Mục cache sống qua cả restart lẫn deploy. Chỉ mình vân tay kho là không
        đủ: đổi prompt của ①/③ hay đổi tuyến model hiệu lực mà không đổi vân tay
        thì một câu trả lời sinh ra dưới hợp đồng CŨ vẫn được phục vụ thêm sáu
        tiếng nữa.
        """
        try:
            from ai.models import ProviderConfig
            from ai.router import get_router

            router = get_router()
            router.maybe_refresh()
            prompt_hashes = {
                name: hashlib.sha256(str(text or "").encode("utf-8")).hexdigest()
                for name, text in self.prompts.items()
            }
            # Môi trường là tĩnh theo tiến trình khi triển khai. Chỉ băm các
            # trường ĐỊNH TUYẾN; không bao giờ giữ API key, token, secret hay
            # mật khẩu trong dấu này.
            env_routes = {key: value for key, value in router.env.items()
                          if key.startswith("MSB_AI_")
                          and any(part in key for part in ("PROVIDER", "MODEL", "BASE_URL"))
                          and not any(secret in key for secret in
                                      ("KEY", "TOKEN", "SECRET", "PASSWORD"))}
            marker = (id(router), getattr(router, "_config_stamp", None),
                      digest(prompt_hashes), digest(env_routes))
            with self._execution_lock:
                if self._execution_cache["marker"] == marker:
                    return self._execution_cache["value"]
            routes = []
            providers = set()
            for task in self.tasks:
                config = router.effective_config(task)
                order = router.provider_order(task)
                providers.update(order)
                routes.append({
                    "task": task,
                    "provider": config.get("provider", ""),
                    "model": config.get("model", ""),
                    "source": config.get("config_source", ""),
                    "order": order,
                })
            # Model của nhà cung cấp dự phòng cũng đổi kết quả khi tuyến đầu
            # không dùng được. Không bao giờ đưa khoá đã mã hoá hay gợi ý khoá.
            fallback_models = list(ProviderConfig.objects.filter(provider__in=providers)
                                   .order_by("provider")
                                   .values("provider", "enabled", "priority",
                                           "base_url", "model"))
            value = digest({"prompts": prompt_hashes, "routes": routes,
                            "fallback_models": fallback_models})
            with self._execution_lock:
                self._execution_cache.update(marker=marker, value=value)
            return value
        except Exception:                          # noqa: BLE001 - migration/startup edge
            log.warning("answer.cache: không lấy được dấu thực thi, bỏ qua cache",
                        exc_info=True)
            return ""

    # ----------------------------------------------------------------- khoá

    def key_for(self, question, *, envelope=None, user=None, query_plan=None):
        """Khoá cache, hoặc None nếu lượt này không nên cache.

        Câu người dùng ổn định là neo chính. Kế hoạch đã chuẩn hoá cũng nằm
        trong khoá vì ②③ thực thi chính các điều kiện/truy vấn đó.

        Khoá gồm cả **người hỏi**. Nói cho đúng với Talent: hôm nay ② KHÔNG lọc
        theo từng dòng dữ liệu — phân quyền ở đó là cấp module, tức "vào được
        phòng nào", không phải "thấy được dòng nào". Nên chiều theo-người-dùng ở
        Talent là lưới đỡ phòng xa, không phải hệ quả của một bộ lọc đang có.
        Ghi rõ vì một bản trước từng viết "② lọc theo quyền" — khẳng định không
        có mã nào đỡ, khiến người đọc sau tin là đã có lọc rồi không đi kiểm.
        """
        fingerprint = self.corpus_fingerprint()
        execution = self.execution_fingerprint()
        permission = permission_fingerprint(user)
        if not fingerprint or not execution or not permission:
            return None
        normalized = " ".join(str(question or "").split()).lower()
        if not normalized:
            return None
        marker = plan_marker(query_plan)
        if self.extra_plan_marker is not None and query_plan is not None:
            marker = {**marker, "domain": self.extra_plan_marker(query_plan)}
        payload = {
            "q": normalized,
            "plan": marker,
            "corpus": fingerprint,
            "execution": execution,
            "permission": permission,
            "user": getattr(user, "pk", None),
            "context": context_marker(envelope),
        }
        value = hashlib.sha256(
            json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()[:40]
        return f"{self.prefix}:{value}"

    # ----------------------------------------------------------- đọc / ghi

    def load(self, key):
        """Trả `(judgements, retrieved)` đã lưu, hoặc None.

        Lưu ở mức ③ (phán đoán từng người) chứ không phải sau ④. ④ là CODE thuần
        và chạy tức thì, nên chạy lại nó với `limit`/`sort_by` của LƯỢT NÀY vừa
        đúng hơn vừa cho tỉ lệ trúng cao hơn: cùng một câu hỏi mà lần này xin 5
        người, lần trước xin 10, vẫn dùng chung được phần đắt tiền.
        """
        if not key:
            return None
        try:
            blob = cache.get(key)
        except Exception as exc:                   # noqa: BLE001
            log.warning("answer.cache: đọc hỏng: %s", exc)
            return None
        if not blob:
            return None
        try:
            return ([self.row_to_judgement(row) for row in blob["judgements"]],
                    int(blob.get("retrieved") or 0))
        except Exception:                          # noqa: BLE001
            log.warning("answer.cache: mục hỏng khuôn, bỏ qua")
            return None

    def save(self, key, judgements, retrieved):
        if not key:
            return
        try:
            cache.set(key, {
                "judgements": [j.as_dict() for j in judgements],
                "retrieved": int(retrieved),
            }, self.ttl)
        except Exception as exc:                   # noqa: BLE001
            # Cache hỏng không được làm hỏng lượt trả lời.
            log.warning("answer.cache: ghi hỏng: %s", exc)
