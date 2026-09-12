#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Cổng chạy các lệnh quản trị Django của MSB Radar Hub."""
import os
import sys


def main():
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Không import được Django. Đã cài requirements.txt và kích hoạt "
            "virtualenv chưa?") from exc
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
