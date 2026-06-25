# -*- coding: utf-8 -*-
"""
Backend EXCEL "có thể NHÌN" — dùng win32com (COM) mở Excel THẬT lên,
điền từng ô (con trỏ nhảy, giá trị hiện dần) rồi lưu. Giống --headed của form.

Chậm hơn openpyxl và cần Excel cài sẵn, nhưng xem được quá trình điền.
Chỉ chạy trên Windows có Microsoft Excel.
"""
from __future__ import annotations
import os
import time
from datetime import date, datetime

from .excel_target import _coerce

XL_UP = -4162  # hằng số xlUp của Excel (tìm dòng cuối có dữ liệu)


def append_row_visible(path: str, sheet: "str | None", header_row: int,
                       fields: "list[dict]", values_by_id: dict,
                       *, delay: float = 0.6, keep_open: bool = True) -> int:
    """Mở Excel hiển thị, điền 1 dòng mới — thấy được từng ô. Trả số dòng đã ghi."""
    import win32com.client as win32

    abspath = os.path.abspath(path)
    excel = win32.Dispatch("Excel.Application")
    excel.Visible = True                # <-- cho thấy cửa sổ Excel
    excel.DisplayAlerts = False
    wb = excel.Workbooks.Open(abspath)
    try:
        ws = wb.Worksheets(sheet) if sheet else wb.Worksheets(1)
        ws.Activate()

        last = ws.Cells(ws.Rows.Count, 1).End(XL_UP).Row   # dòng cuối có dữ liệu (cột 1)
        row = max(last + 1, header_row + 1)

        for f in fields:
            val = _coerce(values_by_id.get(f["id"]), f["type"])
            if val is None:
                continue
            cell = ws.Cells(row, f["col"])
            excel.Goto(cell, True)       # cuộn tới + chọn ô cho dễ nhìn
            cell.Select()
            if isinstance(val, date) and not isinstance(val, datetime):
                # ghi NGÀY bằng SỐ SÊ-RI Excel (tránh pywin32 lệch múi giờ -7h)
                cell.NumberFormat = "dd/mm/yyyy"
                cell.Value = (val - date(1899, 12, 30)).days
            elif isinstance(val, str):
                cell.NumberFormat = "@"  # giữ dạng text (số 0 đầu, '10%'...)
                cell.Value = val
            else:
                cell.Value = val         # số tiền (int)
            time.sleep(delay)            # <-- chậm lại để xem

        wb.Save()
        print(f"✅ Đã điền dòng {row} (Excel đang mở để bạn xem).")
        return row
    finally:
        excel.DisplayAlerts = True
        if not keep_open:
            wb.Close(SaveChanges=True)
            excel.Quit()
