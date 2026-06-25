# -*- coding: utf-8 -*-
"""
Backend ĐÍCH = EXCEL: coi 1 sheet báo cáo như "form", dòng header = các trường,
mỗi chứng từ = 1 dòng thêm mới. Ghi thẳng bằng openpyxl (Bậc 1 — không mở Excel).

  inspect_excel(path, sheet, header_row) -> (sheet_name, fields)
  append_row(path, sheet, header_row, fields, values_by_id) -> số dòng vừa ghi
  make_template(path) -> tạo file báo cáo mẫu để test
"""
from __future__ import annotations
import re
from datetime import datetime
from pathlib import Path

HEADERS_MAU = [
    "Số hoá đơn", "Ký hiệu hoá đơn", "Ngày lập", "Tên nhà cung cấp",
    "MST nhà cung cấp", "Diễn giải", "Tiền trước thuế", "Thuế suất GTGT",
    "Tổng tiền thanh toán",
]


def _guess_type(label: str) -> str:
    l = (label or "").lower()
    if any(k in l for k in ("ngày", "ngay", "date")):
        return "date"
    return "text"


def inspect_excel(path: str, sheet: "str | None" = None, header_row: int = 1):
    """Đọc dòng header -> danh sách trường [{id, label, type, col}]."""
    from openpyxl import load_workbook
    wb = load_workbook(path, read_only=True, data_only=True)
    ws = wb[sheet] if sheet else wb.active
    fields = []
    for col, cell in enumerate(ws[header_row], 1):
        label = "" if cell.value is None else str(cell.value).strip()
        if not label:
            continue
        fields.append({
            "id": f"col{col}",        # khoá dùng cho prompt/kết quả OCR
            "label": label,
            "type": _guess_type(label),
            "col": col,
        })
    name = ws.title
    wb.close()
    return name, fields


def _coerce(value, ftype: str):
    """Chuyển chuỗi OCR thành kiểu phù hợp để Excel hiểu (số/ngày)."""
    if value in (None, ""):
        return None
    if ftype == "date":
        for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
            try:
                return datetime.strptime(str(value), fmt).date()
            except ValueError:
                pass
        return value
    s = str(value)
    if re.fullmatch(r"\d{1,15}", s):
        # GIỮ text nếu có số 0 đứng đầu (số hoá đơn/MST) — tránh mất '0'
        if len(s) > 1 and s.startswith("0"):
            return s
        return int(s)               # số tiền -> int để Excel cộng được
    return value


def append_row(path: str, sheet: "str | None", header_row: int,
               fields: "list[dict]", values_by_id: dict) -> int:
    """Thêm 1 dòng mới ngay sau dữ liệu hiện có, ghi từng giá trị vào đúng cột."""
    from openpyxl import load_workbook
    wb = load_workbook(path)
    ws = wb[sheet] if sheet else wb.active
    row = ws.max_row + 1
    if row <= header_row:               # sheet mới chỉ có header
        row = header_row + 1
    for f in fields:
        val = _coerce(values_by_id.get(f["id"]), f["type"])
        if val is not None:
            ws.cell(row=row, column=f["col"], value=val)
    wb.save(path)
    return row


def make_template(path: str) -> None:
    """Tạo file báo cáo tài chính mẫu (chỉ có dòng header)."""
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill
    wb = Workbook()
    ws = wb.active
    ws.title = "BaoCao"
    for col, h in enumerate(HEADERS_MAU, 1):
        c = ws.cell(row=1, column=col, value=h)
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="5645D4")
        ws.column_dimensions[c.column_letter].width = max(14, len(h) + 2)
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)
    print(f"✅ Đã tạo báo cáo mẫu: {path}")


if __name__ == "__main__":
    import sys
    out = sys.argv[1] if len(sys.argv) > 1 else "bao_cao_tai_chinh.xlsx"
    make_template(out)
