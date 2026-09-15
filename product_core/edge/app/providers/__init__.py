# -*- coding: utf-8 -*-
"""Danh mục các nguồn tuyển dụng mà phần mềm hỗ trợ."""
from .base import Provider, LoginError, NotImplementedProvider
from .topcv import TopCVProvider
from .vietnamworks import VietnamWorksProvider
from .careerviet import CareerVietProvider
from .vieclam24h import Vieclam24hProvider
from .itviec import ITViecProvider
from .joboko import JobokoProvider
from .jobsgo import JobsGoProvider

# Thứ tự ở đây quyết định thứ tự tab trên giao diện
ALL_PROVIDERS = [
    TopCVProvider,
    VietnamWorksProvider,
    CareerVietProvider,
    Vieclam24hProvider,
    ITViecProvider,
    JobokoProvider,
    JobsGoProvider,
]

PROVIDERS_BY_KEY = {p.key: p for p in ALL_PROVIDERS}


def get_provider(key, cfg, log=print):
    cls = PROVIDERS_BY_KEY.get(key, TopCVProvider)
    return cls(cfg, log)


__all__ = ["Provider", "LoginError", "ALL_PROVIDERS", "PROVIDERS_BY_KEY", "get_provider"]
__all__ = ["Provider", "LoginError", "NotImplementedProvider", "ALL_PROVIDERS"]
