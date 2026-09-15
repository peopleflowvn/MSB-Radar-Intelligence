"""Thông tin phiên bản dùng chung cho giao diện và quy trình đóng gói."""

# APP_VERSION phải là chuỗi số thuần (x.y.z) vì build_exe.py chuyển nó thành
# filevers/prodvers cho VSVersionInfo của Windows. Không thêm hậu tố -alpha/-rc.
APP_VERSION = "3.0.0"
APP_NAME = "MSB Radar Edge"
APP_DISPLAY_NAME = f"{APP_NAME} v{APP_VERSION}"
