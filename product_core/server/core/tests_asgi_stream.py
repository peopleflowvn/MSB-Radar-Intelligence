# -*- coding: utf-8 -*-
"""`to_async_iter` phải khiến StreamingHttpResponse stream THẬT qua ASGI.

Bug đã xảy ra: mọi view SSE trong repo viết generator bằng `def` (đồng bộ) vì
thân hàm đọc hàng đợi/gọi ORM đồng bộ. Đưa thẳng generator đó vào
`StreamingHttpResponse` khiến Django rơi vào nhánh dự phòng của chính nó
(`await sync_to_async(list)(self.streaming_content)`) — gom hết generator
thành một list rồi mới gửi một cục, dù code gọi `yield` đều đặn suốt quá
trình. Xác nhận bằng đo trực tiếp trên production: một câu hỏi mất 38 giây để
trả lời, nhưng toàn bộ byte tới client trong đúng MỘT đợt ở giây thứ 38.

Bài test dưới xác nhận `to_async_iter` khiến `StreamingHttpResponse.__aiter__`
lấy nhánh nhanh (`async for part in self.streaming_content`) chứ không rơi vào
nhánh dự phòng đó — nhánh dự phòng luôn tự phát `Warning`, nên "không có
Warning nào" chính là bằng chứng trực tiếp, không phải suy luận gián tiếp.
"""
import time
import warnings
from unittest import IsolatedAsyncioTestCase

from django.http import StreamingHttpResponse

from core.asgi_stream import to_async_iter


def _plain_sync_generator(items):
    """Generator đồng bộ thường — giống hệt các view SSE thật trong repo."""
    for item in items:
        yield item


class ToAsyncIterTest(IsolatedAsyncioTestCase):
    async def test_yields_items_in_order(self):
        items = [b"a", b"b", b"c"]
        collected = [chunk async for chunk in to_async_iter(_plain_sync_generator(items))]
        self.assertEqual(collected, items)

    async def test_empty_generator_yields_nothing(self):
        collected = [chunk async for chunk in to_async_iter(_plain_sync_generator([]))]
        self.assertEqual(collected, [])

    async def test_streaming_http_response_takes_the_real_async_branch(self):
        """Không Warning nào ⇒ Django KHÔNG rơi vào nhánh gom-hết-rồi-gửi."""
        response = StreamingHttpResponse(to_async_iter(_plain_sync_generator([b"x", b"y"])))
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            collected = [chunk async for chunk in response]
        self.assertEqual(collected, [b"x", b"y"])
        self.assertEqual(caught, [], "StreamingHttpResponse rơi vào nhánh sync_to_async(list) — "
                                    "không còn stream thật, xem docstring module này.")

    async def test_plain_sync_generator_without_the_wrapper_hits_the_fallback(self):
        """Đối chứng: KHÔNG bọc `to_async_iter` thì đúng là rơi vào nhánh cũ —
        chứng minh test trên thật sự phân biệt được hai nhánh, không phải lúc
        nào cũng "không có Warning"."""
        response = StreamingHttpResponse(_plain_sync_generator([b"x", b"y"]))
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            collected = [chunk async for chunk in response]
        self.assertEqual(collected, [b"x", b"y"])
        self.assertTrue(caught, "Nhánh dự phòng của Django lẽ ra phải cảnh báo ở đây")

    async def test_items_are_delivered_as_they_become_ready_not_all_at_the_end(self):
        """Bằng chứng THỜI GIAN: item thứ N phải tới sau khi generator gốc sinh
        ra nó, không phải dồn hết đợi generator xong xuôi mới có item đầu."""
        released_at = {}

        def slow_generator():
            for i in range(3):
                time.sleep(0.05)
                released_at[i] = time.perf_counter()
                yield i

        started = time.perf_counter()
        received_at = []
        async for _item in to_async_iter(slow_generator()):
            received_at.append(time.perf_counter())

        for i in range(3):
            # Mỗi item phải tới ngay sau khi được sinh ra (dung sai lịch trình
            # luồng), không phải dồn lại tới cuối (sẽ làm received_at[0] gần
            # bằng received_at[2], cách xa released_at[0]).
            self.assertLess(received_at[i] - released_at[i], 0.2,
                           f"item {i} tới quá trễ so với lúc được sinh ra — có vẻ lại bị gom")
        self.assertGreater(received_at[-1] - started, 0.1)
