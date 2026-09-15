# -*- coding: utf-8 -*-
"""Bọc một generator đồng bộ thành generator bất đồng bộ, để SSE stream thật.

`StreamingHttpResponse.__aiter__()` (django/http/response.py) chỉ thật sự gửi
từng phần khi `streaming_content` có `__aiter__`. Với một generator đồng bộ
thường (mọi view SSE trong repo này viết bằng `def`, không phải `async def`,
vì thân hàm gọi ORM/hàng đợi/HTTP đồng bộ), `async for` trên nó ném
`TypeError`, và Django tự rơi vào nhánh dự phòng nó tự cảnh báo:

    await sync_to_async(list)(self.streaming_content)

— GOM TOÀN BỘ generator vào một list rồi mới gửi một cục duy nhất, dù code
gọi `yield` đều đặn suốt quá trình xử lý. Đây là hành vi tài liệu hoá của
chính Django, không phải lỗi ở gunicorn hay Caddy — xác nhận bằng đo trực
tiếp: một câu hỏi mất 38s tạo câu trả lời, nhưng toàn bộ byte tới client
trong đúng MỘT đợt tại giây 38 (workflow `diagnose-sse-streaming.yml`).

`to_async_iter` gọi `next()` của generator gốc TỪNG PHẦN TỬ MỘT qua
`sync_to_async`, nên Django lấy nhánh `async for part in self.streaming_content`
— gửi ngay mỗi phần tử ra socket khi nó vừa sẵn sàng.

`thread_sensitive=True` (mặc định của Django/asgiref) sẽ dồn MỌI stream đang
chạy cùng lúc trong cả tiến trình qua một luồng chờ duy nhất — một người dùng
hỏi lâu là mọi người khác bị nghẽn theo. `thread_sensitive=False` với executor
riêng tránh được nghẽn đó, nhưng có HAI cái bẫy khác, cả hai đã bắt được bằng
test thật (không phải suy luận):

1. Không cố định executor ⇒ đổi luồng OS GIỮA CÁC LẦN gọi `next()`. Sinh câu
   trả lời (`talent/answer/`) đọc/ghi CSDL giữa các `yield`; CSDL test SQLite
   là chia sẻ nhưng vẫn khoá theo luồng — đổi luồng giữa chừng làm generator
   vỡ giữa chừng ("database table is locked"). Fix: một `ThreadPoolExecutor`
   MỘT LUỒNG DUY NHẤT, RIÊNG cho từng generator/response (không chia sẻ giữa
   các response khác nhau — vậy mới không nghẽn nhau).

2. Fix (1) chưa đủ: `sync_to_async(...).__call__` mặc định COPY một
   `contextvars.Context` MỚI cho MỖI lần gọi (`contextvars.copy_context()`),
   dù luồng OS có cố định hay không. `ai/telemetry.py::capture()` làm
   `token = _active.set(...)` ở một lần gọi `next()`, rồi `token.reset()` ở
   MỘT LẦN GỌI KHÁC (khi generator resume ở yield tiếp theo) — hai lần gọi đó
   nếu chạy trên hai Context copy KHÁC NHAU, `reset()` ném thẳng
   `ValueError: ... was created in a different Context` (contextvars buộc
   token phải reset đúng Context đã tạo ra nó, không liên quan gì tới luồng
   OS). Generator vỡ giữa chừng vì lỗi này, và giá trị ContextVar bị "kẹt"
   trong context cũ còn rò sang cả những lần gọi/test SAU đó không liên quan.
   Fix: tự capture MỘT `contextvars.Context` khi bắt đầu, rồi truyền `context=`
   tường minh cho MỌI lần gọi `sync_to_async` của generator này — để chúng
   cùng chạy (và cùng sửa) một Context duy nhất suốt vòng đời generator.
"""
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context

from asgiref.sync import sync_to_async

_SENTINEL = object()


async def to_async_iter(sync_iterable):
    iterator = iter(sync_iterable)
    executor = ThreadPoolExecutor(max_workers=1)
    context = copy_context()
    try:
        while True:
            item = await sync_to_async(
                next, thread_sensitive=False, executor=executor, context=context,
            )(iterator, _SENTINEL)
            if item is _SENTINEL:
                return
            yield item
    finally:
        executor.shutdown(wait=False)


def drain_to_bytes(async_iterable):
    """Chỉ dùng trong test: gom `streaming_content` đã bọc `to_async_iter`
    thành bytes, thay cho `b"".join(...)` cũ (vỡ vì giờ đó là async generator,
    không phải iterable đồng bộ nữa)."""
    from asgiref.sync import async_to_sync

    async def _collect():
        return b"".join([chunk async for chunk in async_iterable])

    return async_to_sync(_collect)()
