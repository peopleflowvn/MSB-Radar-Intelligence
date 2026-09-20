# -*- coding: utf-8 -*-
"""Chọn nhà cung cấp LLM và chuyển sang dự phòng khi cần (Master Plan mục 7.1).

Nghiệp vụ gọi `complete(messages, task="talent_search")` và không biết phía sau
là GreenNode, GPT, Gemini hay DeepSeek.

Thứ tự ưu tiên:
    1. Provider chỉ định riêng cho tác vụ đó   MSB_AI_PROVIDER_TALENT_SEARCH
    2. Provider mặc định                        MSB_AI_PROVIDER_DEFAULT
    3. Chuỗi dự phòng                           MSB_AI_PROVIDER_FALLBACK

GreenNode đứng đầu mặc định — vừa là hạ tầng của ban tổ chức, vừa là điều kiện
tranh giải "Best Use of Green Node AI Platform". Nhưng nếu chưa có khoá thì nó
tự bị bỏ qua, nên phát triển ngay bây giờ với GPT/Gemini/DeepSeek vẫn chạy được.

Chỉ chuyển provider khi lỗi là TẠM THỜI. Khoá sai hay tên model sai mà cũng
chuyển sang provider khác thì lỗi cấu hình sẽ bị giấu đi, và hoá đơn nhảy sang
một nhà cung cấp mà không ai biết.
"""
import logging
import os
import time

from . import tasks as tasks_registry
from .providers import (LLMAuthError, LLMError, LLMUnavailable,
                        OpenAICompatibleProvider, PROVIDER_DEFAULTS, build_provider)

log = logging.getLogger(__name__)

# agentbase = đường tới GreenNode MaaS đi qua Prospect Agent trên AgentBase
# (nằm trong datacenter GreenNode → nhanh/ổn hơn Hub gọi ra internet). Đứng ngay
# sau greennode-trực-tiếp: greennode chậm/treo thì rơi sang đây thay vì OpenAI.
# Không có endpoint (MSB_AGENT_ENDPOINT) thì `build_provider` trả None, tự bỏ qua.
DEFAULT_ORDER = ["greennode", "agentbase", "openai", "gemini", "deepseek"]


def _dedupe(names):
    seen, out = set(), []
    for name in names:
        if name and name not in seen:
            seen.add(name)
            out.append(name)
    return out


def _provider_from_config(config, transport=None):
    """Dựng nhà cung cấp từ một hàng ProviderConfig. None nếu thiếu khoá."""
    api_keys = config.get_api_keys()
    if not api_keys:
        # Có thể là chưa nhập khoá, hoặc khoá không giải mã được sau khi
        # SECRET_KEY đổi. Cả hai đều nghĩa là chưa dùng được.
        return None
    defaults = PROVIDER_DEFAULTS.get(config.provider, {})
    return OpenAICompatibleProvider(
        name=config.provider,
        base_url=config.base_url or defaults.get("base_url", ""),
        api_key=api_keys,
        model=config.model or defaults.get("model", ""),
        timeout=config.timeout or 60,
        transport=transport)


class NoProviderConfigured(LLMError):
    """Chưa khai báo khoá cho bất kỳ nhà cung cấp nào."""


# Circuit breaker: một provider treo/timeout liên tiếp thì tạm bỏ qua để không
# bắt mọi lượt gọi sau đó cùng chờ hết giờ vì nó. Reset khi gọi lại thành công.
_BREAKER_TRIPS = 2          # số lần timeout liên tiếp trước khi ngắt
_BREAKER_COOLDOWN = 90.0    # giây tạm bỏ qua sau khi ngắt

# Router là singleton THEO TIẾN TRÌNH. Với gunicorn nhiều worker, lưu cấu hình ở
# `/settings` chỉ gọi `reset_router()` trong đúng worker phục vụ request đó — các
# worker khác giữ provider/model cũ tới lần restart. Để mọi worker tự bắt kịp,
# router soi `max(updated_at)` của ProviderConfig + TaskModelRoute mỗi TTL giây;
# dấu đổi ⇒ xoá cache provider đã dựng.
_CONFIG_TTL_DEFAULT = 5.0


class Router:
    def __init__(self, env=None, transport=None, sink=None):
        self.env = env if env is not None else os.environ
        self.transport = transport
        # sink nhận mỗi lượt gọi để ghi nhật ký/tính chi phí. Tách ra thay vì
        # ghi thẳng vào CSDL ở đây, để test không cần CSDL và để sau này đổi
        # sang hàng đợi mà không phải sửa router.
        self.sink = sink
        self._cache = {}
        self._breaker = {}          # name -> {"fails": int, "until": monotonic ts}
        self._config_checked_at = 0.0
        self._config_stamp = None

    # ---------------- làm mới cấu hình xuyên worker ----------------

    def _config_ttl(self):
        try:
            return float(self.env.get("MSB_AI_CONFIG_TTL_SECONDS") or _CONFIG_TTL_DEFAULT)
        except (TypeError, ValueError):
            return _CONFIG_TTL_DEFAULT

    def _current_config_stamp(self):
        """Dấu thời gian cấu hình model trong CSDL. None khi chạy ngoài Django."""
        try:
            from django.db.models import Max

            from .models import ProviderConfig, TaskModelRoute
            provider_ts = ProviderConfig.objects.aggregate(m=Max("updated_at"))["m"]
            route_ts = TaskModelRoute.objects.aggregate(m=Max("updated_at"))["m"]
            route_n = TaskModelRoute.objects.count()
        except Exception:                      # noqa: BLE001 - chưa migrate / ngoài Django
            return None
        return (provider_ts.isoformat() if provider_ts else "",
                route_ts.isoformat() if route_ts else "", route_n)

    def maybe_refresh(self):
        """Xoá cache provider nếu cấu hình DB đã đổi ở worker/tiến trình khác."""
        now = time.monotonic()
        if now - self._config_checked_at < self._config_ttl():
            return
        self._config_checked_at = now
        stamp = self._current_config_stamp()
        if stamp is None:
            return
        if self._config_stamp is not None and stamp != self._config_stamp:
            log.info("Cấu hình model DB đã đổi — dựng lại provider cache")
            self._cache.clear()
        self._config_stamp = stamp

    # ---------------- circuit breaker ----------------

    def _breaker_open(self, name):
        state = self._breaker.get(name)
        return bool(state and state.get("until", 0) > time.monotonic())

    def _breaker_record(self, name, *, timed_out):
        if not timed_out:
            self._breaker.pop(name, None)
            return
        state = self._breaker.setdefault(name, {"fails": 0, "until": 0.0})
        state["fails"] += 1
        if state["fails"] >= _BREAKER_TRIPS:
            state["until"] = time.monotonic() + _BREAKER_COOLDOWN
            log.warning("Ngắt tạm nhà cung cấp %s trong %.0fs (timeout %d lần liên tiếp)",
                        name, _BREAKER_COOLDOWN, state["fails"])

    # ---------------- chọn nhà cung cấp ----------------

    def provider_order(self, task=""):
        """Danh sách tên nhà cung cấp sẽ thử, theo thứ tự.

        Ưu tiên (cụ thể thắng chung chung):
          1. emergency override ENV có tên rõ ràng;
          2. TaskModelRoute trong CSDL (`/settings`);
          3. Mặc định của sổ đăng ký (`ai/tasks.py::DEFAULT_ROUTE`);
          4. Thứ tự ProviderConfig trong CSDL;
          5. ENV bootstrap/default/fallback khi CSDL chưa cấu hình.

        Bậc 3 là bậc mới, và nó tồn tại vì một lỗ cụ thể: thêm tác vụ mới vào
        `ai/tasks.py` mà quên viết migration gieo route thì tác vụ ấy lại im
        lặng rơi xuống model mặc định của nhà cung cấp — đúng cái vừa dọn xong,
        và đúng cái đã chôn ba quả mìn (glm-5.2 nhận `cv_ocr` dù không có thị
        giác). Nay mặc định của sổ đăng ký đỡ ngay, không chờ ai nhớ.
        """
        emergency = self.env.get(f"MSB_AI_EMERGENCY_PROVIDER_{task.upper()}", "").strip() if task else ""
        pinned = [p.strip().lower() for p in emergency.split(",") if p.strip()]
        route = self._task_route(task)
        if route is not None:
            routed = [route.provider]
        else:
            mac_dinh, _ = tasks_registry.default_route(task) if task else ("", "")
            routed = [mac_dinh] if mac_dinh else []
        # Hệ cũ chưa hề có cấu hình DB vẫn chạy được với task pin ENV. Ngay khi
        # DB đã được cấu hình hoặc có TaskModelRoute, pin cũ không được override
        # màn hình Settings nữa.
        db_order = self._db_order()
        if not pinned and route is None and db_order is None and task:
            legacy = self.env.get(f"MSB_AI_PROVIDER_{task.upper()}", "").strip()
            pinned = [p.strip().lower() for p in legacy.split(",") if p.strip()]

        # Thứ tự nền: CSDL nếu người vận hành đã cấu hình, ngược lại DEFAULT/FALLBACK.
        from_db = db_order
        if from_db is not None:
            base = list(from_db)
        else:
            base = []
            default = self.env.get("MSB_AI_PROVIDER_DEFAULT", "").strip()
            base.append(default.lower() if default else DEFAULT_ORDER[0])
            fallback = self.env.get("MSB_AI_PROVIDER_FALLBACK", "").strip()
            if fallback:
                base += [p.strip().lower() for p in fallback.split(",") if p.strip()]
            else:
                # Mọi nhà cung cấp còn lại, KHÔNG phải DEFAULT_ORDER[1:]. Đặt
                # PROVIDER_DEFAULT=gemini không được âm thầm loại GreenNode khỏi
                # chuỗi — nó là điều kiện tranh giải Best Use of GreenNode.
                base += [p for p in DEFAULT_ORDER if p not in base]

        order = _dedupe(pinned + routed + base)
        # Operational kill switch for providers known to be unusable (for
        # example billing HTTP 402).  Keeping them in a fallback chain wastes
        # latency and makes a failed compose look as though it was retried
        # meaningfully.  Task-specific config wins over the global list.
        disabled_raw = self.env.get(
            f"MSB_AI_DISABLED_PROVIDERS_{task.upper()}", "") if task else ""
        disabled_raw = disabled_raw or self.env.get("MSB_AI_DISABLED_PROVIDERS", "")
        disabled = {name.strip().lower() for name in disabled_raw.split(",")
                    if name.strip()}
        return [name for name in order if name not in disabled]

    def _task_route(self, task):
        if not task:
            return None
        try:
            from .models import TaskModelRoute
            return TaskModelRoute.objects.filter(task=task, enabled=True).first()
        except Exception:  # noqa: BLE001 - migration chưa áp dụng / ngoài Django
            return None

    def effective_config(self, task=""):
        """Cấu hình thực sự có hiệu lực, an toàn để hiển thị trên Settings/trace."""
        self.maybe_refresh()
        order = self.provider_order(task)
        provider = order[0] if order else ""
        route = self._task_route(task)
        emergency_key = f"MSB_AI_EMERGENCY_PROVIDER_{task.upper()}" if task else ""
        model_key = f"MSB_AI_EMERGENCY_MODEL_{task.upper()}" if task else ""
        if task and self.env.get(emergency_key, "").strip():
            source = "env_emergency"
        elif route is not None:
            source = "db_task_route"
        elif task and tasks_registry.default_route(task)[1]:
            # Chưa có hàng trong CSDL nhưng sổ đăng ký có mặc định. Nói đúng tên
            # nguồn để `/settings` gợi được "bấm Lưu để chốt vào CSDL", thay vì
            # hiện `db_provider_default` làm người ta tưởng đã cấu hình rồi.
            source = "registry_default"
        elif self._db_order() is not None:
            source = "db_provider_default"
        else:
            source = "env_bootstrap"
        picked_model = self._model_for(provider, task) if provider else ""
        if not picked_model and provider:
            built = self.get_provider(provider)
            picked_model = getattr(built, "model", "") if built is not None else ""
        return {"task": task, "provider": provider,
                "capability": tasks_registry.capability_for(task),
                "model": picked_model,
                "config_source": source,
                "emergency_key": emergency_key if source == "env_emergency" else "",
                "emergency_model_key": model_key if self.env.get(model_key, "").strip() else "",
                # Tên biến env đang thực sự chi phối model của task này (nếu có) —
                # để `/settings` chỉ rõ "env vô hình" thay vì để người vận hành đoán.
                "model_env_override": self._model_env_override(provider, task, route)}

    def _model_env_override(self, provider, task, route):
        if not task or not provider:
            return ""
        task_up, name_up = task.upper(), provider.upper()
        candidates = [f"MSB_AI_EMERGENCY_{name_up}_MODEL_{task_up}",
                      f"MSB_AI_EMERGENCY_MODEL_{task_up}"]
        if route is None:
            candidates += [f"MSB_AI_{name_up}_MODEL_{task_up}", f"MSB_AI_MODEL_{task_up}"]
        for key in candidates:
            if self.env.get(key, "").strip():
                return key
        return ""

    def _db_order(self):
        """Thứ tự từ bảng ProviderConfig.

        Trả `None` nghĩa là "CSDL không có ý kiến, dùng biến môi trường".
        Trả `[]` nghĩa là "người vận hành đã cấu hình và tắt hết" — khác hẳn nhau.

        Phân biệt hai thứ đó là bắt buộc: mở trang cài đặt sẽ tạo sẵn một hàng
        cho mỗi nhà cung cấp (đều tắt). Nếu coi đó là "đã cấu hình" thì chỉ cần
        mở trang một lần là toàn bộ cấu hình qua biến môi trường ngừng hoạt
        động. Ngược lại, nếu luôn lùi về biến môi trường khi không có gì được
        bật thì thao tác tắt hết của người vận hành bị bỏ qua.
        """
        try:
            from .models import ProviderConfig
            rows = list(ProviderConfig.objects
                        .order_by("priority", "provider")
                        .values_list("provider", "enabled", "api_key_encrypted"))
        except Exception:                      # noqa: BLE001
            # Chưa migrate, hoặc đang chạy ngoài Django. Lùi về biến môi trường
            # thay vì làm hỏng mọi lời gọi AI.
            return None

        # "Đã cấu hình" = có ít nhất một hàng được bật hoặc đã nhập khoá.
        if not any(enabled or key for _name, enabled, key in rows):
            return None
        return [name for name, enabled, _key in rows if enabled]

    def get_provider(self, name):
        if name not in self._cache:
            self._cache[name] = self._build(name)
        return self._cache[name]

    def _build(self, name):
        """Dựng nhà cung cấp: ưu tiên CSDL, thiếu gì thì lấy từ biến môi trường."""
        # agentbase không phải OpenAI-compat -> không đi qua ProviderConfig (khuôn
        # đó giả định chat/completions). Chỉ dựng từ MSB_AGENT_ENDPOINT.
        if str(name).strip().lower() == "agentbase":
            try:
                return build_provider("agentbase", transport=self.transport, env=self.env)
            except LLMError:
                return None
        config = self._db_config(name)
        if config is not None:
            provider = _provider_from_config(config, transport=self.transport)
            if provider is not None:
                return provider
        try:
            return build_provider(name, transport=self.transport, env=self.env)
        except LLMError:
            return None

    @staticmethod
    def _db_config(name):
        try:
            from .models import ProviderConfig
            return ProviderConfig.objects.filter(provider=name, enabled=True).first()
        except Exception:                      # noqa: BLE001
            return None

    def available(self):
        """Các nhà cung cấp đã có khoá — hiển thị trên trang trạng thái."""
        return [name for name in self.provider_order()
                if (self.get_provider(name) or None) is not None]

    # ---------------- gọi ----------------

    # Khi MỌI nhà cung cấp đều lỗi tạm thời, đợi rồi thử lại một vòng nữa.
    #
    # Ca thường gặp nhất: chỉ cấu hình một nhà cung cấp và bị giới hạn tốc độ
    # (HTTP 429). Chuyển provider không cứu được vì không có chỗ để chuyển, mà
    # giới hạn tốc độ thì chỉ cần đợi vài giây. Đo thực tế với khoá Gemini miễn
    # phí: 15 lượt gọi trong một phút là đã bị chặn — đúng nhịp một buổi demo.
    RETRY_ROUNDS = 2
    RETRY_DELAY_SECONDS = 3.0

    # Trần thời gian cho TOÀN BỘ một lượt `complete()`, tính cả chuyển nhà cung
    # cấp và thử lại.
    #
    # Không có trần này, trường hợp xấu nhất là 4 nhà cung cấp × 60 giây × 2
    # vòng ≈ 8 phút màn hình đứng — mà một lượt tìm bằng AI gọi hai lần, thành
    # 16 phút. Trước ban giám khảo, treo 16 phút tệ hơn hẳn báo lỗi sau 25 giây
    # rồi lùi về dò từ khoá. Mạng hội trường chập chờn là chuyện thường.
    #
    # 25 giây: một lượt gọi Gemini đo được 4–7 giây, nên vẫn đủ cho nhà cung cấp
    # chính cộng một lần dự phòng.
    BUDGET_SECONDS = 25.0

    def complete(self, messages, task="", **kwargs):
        """Gọi nhà cung cấp đầu tiên dùng được, chuyển tiếp khi lỗi tạm thời."""
        self.maybe_refresh()
        budget = float(kwargs.pop("budget_seconds", None) or self._budget())
        deadline = time.monotonic() + budget

        for attempt in range(self.RETRY_ROUNDS):
            try:
                return self._complete_once(messages, task=task,
                                           deadline=deadline, **kwargs)
            except LLMUnavailable:
                remaining = deadline - time.monotonic()
                if attempt == self.RETRY_ROUNDS - 1:
                    raise
                # Đợi rồi thử lại chỉ có nghĩa nếu còn đủ thời gian để lượt sau
                # thật sự chạy xong, chứ không phải để hết giờ giữa chừng.
                if remaining <= self.RETRY_DELAY_SECONDS + 1.0:
                    log.info("Hết thời gian chờ (%.0fs), không thử lại nữa", budget)
                    raise
                log.info("Mọi nhà cung cấp đều bận; đợi %.1fs rồi thử lại",
                         self.RETRY_DELAY_SECONDS)
                time.sleep(self.RETRY_DELAY_SECONDS)

    def _budget(self):
        try:
            return float(self.env.get("MSB_AI_BUDGET_SECONDS") or self.BUDGET_SECONDS)
        except (TypeError, ValueError):
            return self.BUDGET_SECONDS

    def _model_for(self, name, task):
        """Mã model ghi đè cho (nhà cung cấp, tác vụ), hoặc None → model mặc định.

        Ưu tiên route trong DB. ENV chỉ là emergency override có tiền tố rõ;
        các biến task cũ chỉ là fallback bootstrap để không làm hỏng triển khai
        chưa migrate, không được ghi đè cấu hình DB.
        """
        if not task:
            return None
        task_up = task.upper()
        for key in (f"MSB_AI_EMERGENCY_{name.upper()}_MODEL_{task_up}",
                    f"MSB_AI_EMERGENCY_MODEL_{task_up}"):
            value = self.env.get(key, "").strip()
            if value:
                return value
        route = self._task_route(task)
        if route is not None and route.provider == name and route.model:
            return route.model
        # Compatibility bootstrap only when no DB task route exists.
        if route is None:
            for key in (f"MSB_AI_{name.upper()}_MODEL_{task_up}",
                        f"MSB_AI_MODEL_{task_up}"):
                value = self.env.get(key, "").strip()
                if value:
                    return value
            # Chưa ai cấu hình gì cho tác vụ này. Thà lấy mặc định đã đo được
            # còn hơn để rơi xuống model mặc định của nhà cung cấp — đó là cách
            # `cv_ocr` từng nhận một model không đọc nổi ảnh mà không ai hay.
            mac_dinh_provider, mac_dinh_model = tasks_registry.default_route(task)
            if mac_dinh_model and mac_dinh_provider == name:
                return mac_dinh_model
        return None

    def stream(self, messages, task="", **kwargs):
        """Stream lượt gọi qua nhà cung cấp đầu tiên dùng được.

        Chỉ chuyển provider khi provider hiện tại lỗi TRƯỚC khi có nội dung
        (mở kết nối hỏng). Có nội dung rồi thì không đổi giữa chừng — xem
        `OpenAICompatibleProvider.stream`.
        """
        self.maybe_refresh()
        budget = float(kwargs.pop("budget_seconds", None) or self._budget())
        deadline = time.monotonic() + budget
        full_order = self.provider_order(task)
        order = [n for n in full_order if not self._breaker_open(n)] or full_order
        attempted, last_error = [], None
        for name in order:
            provider = self.get_provider(name)
            if provider is None or not hasattr(provider, "stream"):
                continue
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            attempted.append(name)
            call_kwargs = dict(kwargs)
            call_kwargs["timeout"] = min(provider.timeout, remaining)
            picked_model = call_kwargs.get("model") or self._model_for(name, task)
            if picked_model:
                call_kwargs["model"] = picked_model
            attempt_started = time.monotonic()
            try:
                gen = provider.stream(messages, **call_kwargs)
                first = next(gen)
            except LLMAuthError as exc:
                self._record(name, picked_model or provider.model, task, error=str(exc), started=attempt_started)
                raise
            except LLMUnavailable as exc:
                last_error = exc
                self._breaker_record(
                    name, timed_out="timeout" in str(exc).lower()
                    or "timed out" in str(exc).lower())
                self._record(name, picked_model or provider.model, task, error=str(exc), started=attempt_started)
                continue
            except StopIteration:
                continue

            done = None

            def _relay(first_chunk, generator):
                nonlocal done
                current = first_chunk
                while True:
                    if current.get("type") == "done":
                        done = current.get("completion")
                        yield current
                        return
                    yield current
                    try:
                        current = next(generator)
                    except StopIteration:
                        return

            try:
                yield from _relay(first, gen)
            except LLMError as exc:
                self._record(name, picked_model or provider.model, task,
                             error=str(exc), started=attempt_started)
                raise
            self._breaker_record(name, timed_out=False)
            self._record(name, (done.model if done else provider.model), task,
                         result=done, started=attempt_started)
            return

        if not attempted:
            raise NoProviderConfigured(
                "Chưa cấu hình nhà cung cấp AI nào cho stream.")
        raise LLMUnavailable(
            f"Đã thử {', '.join(attempted)} nhưng đều không stream được. "
            f"Lỗi cuối: {last_error}")

    def _complete_once(self, messages, task="", deadline=None, **kwargs):
        full_order = [n for n in self.provider_order(task)
                      if self.get_provider(n) is not None]
        # Bỏ qua provider đang bị ngắt — trừ khi nó là lựa chọn duy nhất.
        order = [n for n in full_order if not self._breaker_open(n)] or full_order
        attempted, last_error = [], None

        for position, name in enumerate(order):
            provider = self.get_provider(name)
            if provider is None:
                continue                      # chưa có khoá; im lặng bỏ qua

            remaining = None if deadline is None else deadline - time.monotonic()
            if remaining is not None and remaining <= 1.0:
                log.warning("Hết thời gian chờ trước khi thử %s", name)
                break
            attempted.append(name)
            call_kwargs = dict(kwargs)
            # Model theo tác vụ (nếu người gọi chưa chỉ định rõ).
            picked_model = call_kwargs.get("model") or self._model_for(name, task)
            if picked_model:
                call_kwargs["model"] = picked_model
            attempt_started = time.monotonic()
            try:
                # Ép thời gian chờ của lượt này nằm trong phần ngân sách còn
                # lại — VÀ chừa phần cho dự phòng: một provider treo không được
                # ăn hết ngân sách rồi để provider sau không có giây nào chạy.
                if remaining is not None:
                    left = len(order) - position
                    per_call = remaining if left <= 1 else remaining * 0.6
                    call_kwargs["timeout"] = min(provider.timeout, per_call)
                result = provider.complete(messages, **call_kwargs)
            except LLMUnavailable as exc:
                last_error = exc
                timed_out = "timed out" in str(exc).lower() or "timeout" in str(exc).lower()
                self._breaker_record(name, timed_out=timed_out)
                log.warning("Nhà cung cấp %s tạm thời không dùng được: %s", name, exc)
                self._record(name, picked_model or provider.model, task, error=str(exc), started=attempt_started)
                continue
            except LLMAuthError as exc:
                # Khoá sai KHÔNG được âm thầm đẩy sang nhà cung cấp khác: lỗi
                # cấu hình sẽ bị giấu và hoá đơn nhảy sang chỗ khác.
                self._record(name, picked_model or provider.model, task, error=str(exc), started=attempt_started)
                raise
            except LLMError as exc:
                self._record(name, picked_model or provider.model, task, error=str(exc), started=attempt_started)
                raise

            self._breaker_record(name, timed_out=False)     # gọi được -> reset
            self._record(name, result.model, task, result=result)
            return result

        if not attempted:
            raise NoProviderConfigured(
                "Chưa cấu hình nhà cung cấp AI nào. Đặt một trong các biến: "
                + ", ".join(f"MSB_AI_{n.upper()}_API_KEY" for n in DEFAULT_ORDER))
        raise LLMUnavailable(
            f"Đã thử {', '.join(attempted)} nhưng đều không dùng được. "
            f"Lỗi cuối: {last_error}")

    def _record(self, provider, model, task, result=None, error="", started=None):
        try:
            from . import telemetry
            entry = {
                "provider": provider, "model": model, "task": task,
                "prompt_tokens": result.prompt_tokens if result else 0,
                "completion_tokens": result.completion_tokens if result else 0,
                "latency_ms": result.latency_ms if result else (
                    int((time.monotonic() - started) * 1000) if started is not None else 0),
                "ok": bool(result), "error": error,
                "at": time.time(),
            }
            # Safe configuration provenance only; never attach request content.
            config = self.effective_config(task)
            entry["route_reason"] = (config["config_source"] if config["provider"] == provider
                                     else "fallback")
            entry["capability"] = tasks_registry.capability_for(task)
            telemetry.record({**entry, **(telemetry.reported_usage(result) if result else {})})
            if self.sink is not None:
                self.sink(entry)
        except Exception:                      # noqa: BLE001
            # Ghi nhật ký hỏng không được làm hỏng lời gọi AI.
            log.exception("Không ghi được nhật ký lượt gọi AI")


_router = None


def get_router():
    global _router
    if _router is None:
        _router = Router(sink=_django_sink)
    return _router


def reset_router():
    """Dùng trong test."""
    global _router
    _router = None


def _django_sink(entry):
    """Ghi mỗi lượt gọi vào CSDL để theo dõi và tính chi phí.

    Import trong hàm để module providers/router dùng được ở ngoài Django.
    """
    from .models import LLMCall
    LLMCall.objects.create(
        provider=entry["provider"], model=entry["model"] or "", task=entry["task"] or "",
        prompt_tokens=entry["prompt_tokens"], completion_tokens=entry["completion_tokens"],
        latency_ms=entry["latency_ms"], ok=entry["ok"], error=entry["error"][:500])


def complete(messages, task="", **kwargs):
    """Điểm vào duy nhất cho toàn bộ nghiệp vụ."""
    return get_router().complete(messages, task=task, **kwargs)


def stream(messages, task="", **kwargs):
    """Stream — điểm vào duy nhất. Yield dict chunk, kết thúc bằng type 'done'."""
    yield from get_router().stream(messages, task=task, **kwargs)
