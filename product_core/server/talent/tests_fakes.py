# -*- coding: utf-8 -*-
"""LLM giả dùng chung cho các bài kiểm thử của Talent.

Trước đây nằm trong `tests_ai.py` — file kiểm thử của đường trả lời cũ. Đường đó
đã bị gỡ, nhưng tiện ích này thì không thuộc về nó: `tests_person_qa`,
`tests_corpus_qa`… đều cần.
"""


class FakeLLM:
    """LLM giả. Trả lần lượt các câu đã đặt trước, ghi lại prompt nhận được."""

    def __init__(self, *replies, raises=None):
        self.replies = list(replies)
        self.raises = raises
        self.calls = []

    def __call__(self, messages, task="", **kwargs):
        self.calls.append({"messages": messages, "task": task, "kwargs": kwargs})
        if self.raises:
            raise self.raises
        text = self.replies.pop(0) if self.replies else "{}"

        class Reply:
            def __init__(self, text):
                self.text = text
                self.provider = "fake"
                self.model = "fake-1"
        return Reply(text)
