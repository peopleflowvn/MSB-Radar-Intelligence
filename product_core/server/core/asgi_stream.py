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
`sync_to_async` (`thread_sensitive=False` — không có gì ở đây đụng ORM nên
không cần ràng buộc một luồng riêng, và ràng buộc đó sẽ nghẽn CẢ TIẾN TRÌNH
khi nhiều người dùng stream cùng lúc), nên Django lấy nhánh `async for part in
self.streaming_content` — gửi ngay mỗi phần tử ra socket khi nó vừa sẵn sàng.
"""
from asgiref.sync import sync_to_async

_SENTINEL = object()


async def to_async_iter(sync_iterable):
    iterator = iter(sync_iterable)
    while True:
        item = await sync_to_async(next, thread_sensitive=False)(iterator, _SENTINEL)
        if item is _SENTINEL:
            return
        yield item
