# -*- coding: utf-8 -*-
"""Đọc tệp Excel/CSV người dùng tải lên thành các dòng dạng dict.

Chỉ `openpyxl` và thư viện chuẩn — dự án không có `pandas`. Kết quả là danh sách
`{tiêu_đề_gốc: giá_trị_ô}`; việc ánh xạ sang khoá payload là của `fields.py`.
"""
import csv
import io

from openpyxl import load_workbook

MAX_ROWS = 5000
MAX_BYTES = 10 * 1024 * 1024


class ImportFileError(ValueError):
    pass


def read_table(django_file):
    """`UploadedFile` → `(headers, rows)`.

    `headers`: list tiêu đề cột theo đúng thứ tự trong tệp.
    `rows`: list dict; mỗi dict là một dòng dữ liệu (đã bỏ dòng trống hoàn toàn).
    """
    name = str(getattr(django_file, "name", "") or "").lower()
    size = getattr(django_file, "size", 0) or 0
    if size > MAX_BYTES:
        raise ImportFileError(f"Tệp vượt quá {MAX_BYTES // (1024 * 1024)} MB.")

    django_file.seek(0)
    data = django_file.read()
    if not data:
        raise ImportFileError("Tệp rỗng.")

    if name.endswith(".csv") or name.endswith(".txt"):
        return _read_csv(data)
    if name.endswith((".xlsx", ".xlsm")):
        return _read_xlsx(data)
    raise ImportFileError("Chỉ nhận tệp .xlsx hoặc .csv.")


def _read_csv(data):
    text = data.decode("utf-8-sig", errors="replace")
    reader = csv.reader(io.StringIO(text))
    matrix = [row for row in reader]
    return _from_matrix(matrix)


def _read_xlsx(data):
    try:
        wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception as exc:  # noqa: BLE001 - openpyxl ném nhiều loại lỗi cho file hỏng
        raise ImportFileError("Không đọc được tệp Excel: tệp có thể hỏng.") from exc
    ws = wb.active
    matrix = []
    for row in ws.iter_rows(values_only=True):
        matrix.append(list(row))
    wb.close()
    return _from_matrix(matrix)


def _from_matrix(matrix):
    # Bỏ các dòng trống ở đầu, lấy dòng không trống đầu tiên làm tiêu đề.
    rows_iter = iter(enumerate(matrix))
    headers = None
    for _idx, row in rows_iter:
        if any(_cell(v) for v in row):
            headers = [_cell(v) for v in row]
            break
    if not headers:
        raise ImportFileError("Không tìm thấy hàng tiêu đề.")

    # Cắt đuôi các cột tiêu đề rỗng.
    while headers and not headers[-1]:
        headers.pop()
    if not headers:
        raise ImportFileError("Hàng tiêu đề rỗng.")

    rows = []
    for _idx, row in rows_iter:
        values = [_cell(v) for v in row]
        if not any(values):
            continue
        record = {}
        for col_i, header in enumerate(headers):
            if not header:
                continue
            record[header] = values[col_i] if col_i < len(values) else ""
        rows.append(record)
        if len(rows) >= MAX_ROWS:
            raise ImportFileError(f"Tệp quá lớn: tối đa {MAX_ROWS} dòng mỗi lần nhập.")

    if not rows:
        raise ImportFileError("Tệp không có dòng dữ liệu nào.")
    return headers, rows


def _cell(value):
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()
