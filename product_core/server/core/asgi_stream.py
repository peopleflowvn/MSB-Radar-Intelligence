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
hỏi lâu là mọi người khác bị nghẽn theo. Nhưng `thread_sensitive=False` với
executor mặc định (dùng chung của asyncio) lại đổi luồng thực thi GIỮA CÁC LẦN
gọi `next()` — bắt được bằng test thật: sinh câu trả lời (`talent/answer/`) đọc
ghi CSDL giữa các `yield`, và CSDL test SQLite `:memory:` là RIÊNG CHO TỪNG
LUỒNG — đổi luồng giữa chừng là sinh generator "mất" luôn dữ liệu nó vừa ghi ở
lần `next()` trước, generator hỏng giữa chừng và cả bộ test sau đó nhiễu chéo
(một luồng threadpool bị bỏ dở vẫn chạy nền, ghi telemetry vào scope của test
khác). Test ở `test_dedicated_thread_...` dưới xác nhận CHÍNH XÁC luồng OS
được giữ nguyên suốt vòng đời một generator.

Cách đúng: MỘT executor một-luồng RIÊNG cho từng generator (từng response) —
luồng cố định suốt vòng đời của nó (an toàn với mọi thứ gắn luồng bên trong),
nhưng KHÔNG chia sẻ giữa các response khác nhau (không nghẽn nhau).
"""
from concurrent.futures import ThreadPoolExecutor

from asgiref.sync import sync_to_async

_SENTINEL = object()


async def to_async_iter(sync_iterable):
    iterator = iter(sync_iterable)
    executor = ThreadPoolExecutor(max_workers=1)
    try:
        while True:
            item = await sync_to_async(next, thread_sensitive=False, executor=executor)(
                iterator, _SENTINEL)
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
