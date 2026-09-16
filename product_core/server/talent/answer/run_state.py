# -*- coding: utf-8 -*-
"""Claim một-lần của Talent — thân nằm ở `core/answer/run_state.py`.

Bảng chỉ lưu (người dùng, mã lượt, trạng thái, hạn chót), không có gì thuộc về
kho CV, nên Growth dùng đúng bảng ấy. Giữ tên module ở đây vì `talent.answer`
và test gọi qua nó.
"""
from core.answer.run_state import claim, finish, status   # noqa: F401
