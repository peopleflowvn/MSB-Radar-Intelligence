# -*- coding: utf-8 -*-
"""Ghi lại một lượt chạy agent, từng bước một.

Dùng như một context manager:

    with runtime.run(AGENT_TALENT, goal=question, user=request.user) as run:
        with run.step("search_person", "Tìm trong kho ứng viên") as step:
            people = search.search(...)
            step.detail = f"tìm thấy {len(people)} hồ sơ"
        ...
        run.finish({"count": len(results)})

Cố ý KHÔNG có một "planner" nào ở đây quyết định bước nào chạy trước, chạy sau,
hay có chạy hay không — người viết domain code (`talent/ai_search.py`,
`rb/agent.py`) quyết định trình tự đó bằng chính cấu trúc hàm Python của họ,
giống hệt như trước khi có runtime này. `run.step()` chỉ BỌC quanh một đoạn code
đã có sẵn để đo thời gian và ghi lại — nó không thay code đó làm việc.

Không ghi được vào CSDL (chưa migrate, chạy ngoài Django, v.v.) thì im lặng bỏ
qua: quan sát hỏng không được phép làm hỏng nghiệp vụ đang chạy.
"""
import logging
import time
from contextlib import contextmanager

from django.utils import timezone

log = logging.getLogger(__name__)


class _StepHandle:
    """Trả về từ `run.step()`. Domain code có thể gán `detail`, `provider`,
    `model_name` trước khi khối `with` kết thúc."""

    def __init__(self, tool, label):
        self.tool = tool
        self.label = label
        self.detail = ""
        self.provider = ""
        self.model_name = ""
        self.ok = True


class _RunHandle:
    def __init__(self, agent_run):
        self._run = agent_run
        self._order = 0

    def record(self, label, tool="", detail="", ok=True, provider="", model_name=""):
        """Ghi một bước đã XONG RỒI — dùng khi domain code đã có sẵn một danh
        sách `trace` kiểu `{"label": ..., "detail": ...}` (như
        `talent/ai_search.py` có từ trước) và chỉ cần lưu lại, không cần đo
        thời gian bao quanh. `step()` (context manager) đo thời gian; `record()`
        thì không — dùng cho những bước mà domain code tự thấy phù hợp hơn khi
        không phải bọc lại toàn bộ hàm.
        """
        handle = _StepHandle(tool, label)
        handle.detail = detail
        handle.ok = ok
        handle.provider = provider
        handle.model_name = model_name
        self._record(handle, time.monotonic())

    @contextmanager
    def step(self, tool, label):
        handle = _StepHandle(tool, label)
        started = time.monotonic()
        try:
            yield handle
        except Exception:
            handle.ok = False
            self._record(handle, started)
            raise
        else:
            self._record(handle, started)

    def _record(self, handle, started):
        if self._run is None:
            return
        self._order += 1
        duration_ms = int((time.monotonic() - started) * 1000)
        try:
            from accounts.privacy import redact_contacts
            from .models import AgentStep
            # `detail` là chỗ domain code nhét văn bản tự do vào — trích dẫn bài
            # đăng, lý do model tự viết, mẩu CV. `AgentStep` thì nằm lại CSDL
            # VĨNH VIỄN và về sau còn được đọc lại ở màn hình quan sát. Một bản
            # sao liên hệ nằm ở đây là một bản sao ngoài tầm hạn mức mở khoá,
            # không ai nghĩ tới mà đi kiểm.
            #
            # Che ở ĐÂY vì đây là điểm ghi duy nhất của MỌI agent. Vá ở từng
            # agent thì agent tiếp theo lại phải nhớ vá lại — và
            # `docs/AI_AGENT_ACCEPTANCE_CRITERIA.md` §4 ghi hai lần đã quên
            # đúng như thế (#2 ở Talent, #3 ở RB) như hai lớp lỗi riêng biệt.
            AgentStep.objects.create(
                run=self._run, order=self._order, tool=handle.tool,
                label=redact_contacts(handle.label)[:200],
                detail=redact_contacts(str(handle.detail))[:500],
                ok=handle.ok, provider=handle.provider[:40],
                model_name=handle.model_name[:100], duration_ms=duration_ms)
        except Exception:                       # noqa: BLE001 — xem docstring
            log.exception("Không ghi được AgentStep")

    def finish(self, result_summary=None, error=""):
        if self._run is None:
            return
        try:
            from .models import AgentRun
            self._run.status = AgentRun.STATUS_ERROR if error else AgentRun.STATUS_OK
            self._run.error = str(error)[:500]
            self._run.result_summary = result_summary or {}
            self._run.finished_at = timezone.now()
            self._run.save(update_fields=["status", "error", "result_summary",
                                          "finished_at"])
        except Exception:                       # noqa: BLE001
            log.exception("Không đóng được AgentRun")


@contextmanager
def run(agent, goal="", user=None):
    """Mở một lượt chạy. Tự động đóng lại (status=ok) khi khối `with` xong xuôi;
    nếu bên trong ném lỗi thì đóng lại với status=error rồi để lỗi tiếp tục nổ —
    quan sát không được nuốt lỗi thật.
    """
    agent_run = None
    try:
        from accounts.privacy import redact_contacts
        from .models import AgentRun
        # `goal` là câu hỏi hoặc nguyên văn bài đăng đang xét — `rb/agent.py`
        # truyền thẳng `text[:200]` vào đây. Cùng lý do với `_record`: đây là
        # bản ghi nằm lại CSDL vĩnh viễn, ngoài tầm hạn mức mở khoá liên hệ.
        #
        # Bỏ sót đúng chỗ này ở lần vá đầu: che `AgentStep.detail` rồi tưởng
        # xong, trong khi `AgentRun.goal` ngay bên cạnh vẫn nguyên văn. Đúng
        # hình dạng lỗi mà tiêu chí §2.I dòng 1 mô tả — "che đúng ở API chính,
        # quên endpoint phụ".
        agent_run = AgentRun.objects.create(
            agent=agent, goal=redact_contacts(str(goal or ""))[:500],
            started_by=user if user is not None and getattr(user, "is_authenticated", False)
            else None)
    except Exception:                           # noqa: BLE001 — xem docstring
        log.exception("Không mở được AgentRun")

    handle = _RunHandle(agent_run)
    try:
        yield handle
    except Exception as exc:
        handle.finish(error=str(exc)[:500])
        raise
    else:
        from .models import AgentRun
        if agent_run is not None and agent_run.status == AgentRun.STATUS_RUNNING:
            # Domain code quên gọi finish() — vẫn đóng lại để không có bản ghi
            # "đang chạy" mãi mãi trong CSDL.
            handle.finish()
