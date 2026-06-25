# -*- coding: utf-8 -*-
"""
Điền form Microsoft Access bằng COM (Access có API → Bậc 1, ổn định hơn UIA).
Khác desktop_filler (UIA cho app KHÔNG có API như OH): Access tự động hoá tốt nhất qua COM.

Yêu cầu: Access đang mở sẵn file + form (chạy make_access_demo.py trước).
"""
from __future__ import annotations
import _bootstrap  # .env, temp->D:, sys.path
import re

AMOUNT_KEYS = {"tien_truoc_thue", "tong_thanh_toan"}


def _coerce(key: str, value, amount_keys: set):
    s = str(value)
    if key in amount_keys:                       # bỏ dấu phân cách -> số
        digits = re.sub(r"[^\d]", "", s)
        return int(digits) if digits else None
    return s                                     # text/ngày để Access tự parse


def fill_access(values_by_key: dict, *, form_name: "str | None" = None,
                submit: bool = True, profile: "dict | None" = None) -> dict:
    import os
    import win32com.client as win32

    # cấu hình: từ profile (đa-app) hoặc desktop_filler (mặc định)
    if profile:
        fields = profile["fields"]
        amount_keys = set(profile.get("amount_keys", []))
        exe = profile.get("exe", "")
        DB_PATH = exe if os.path.isabs(exe) else os.path.join(os.path.dirname(os.path.abspath(__file__)), exe)
    else:
        from .desktop_filler import FIELDS, APP_EXE
        fields, amount_keys, DB_PATH = FIELDS, AMOUNT_KEYS, APP_EXE

    acc = win32.Dispatch("Access.Application")       # tự mở/ tái dùng Access
    acc.Visible = True

    # mở CSDL của ta nếu chưa có db nào trong instance này
    has_db = False
    try:
        has_db = acc.CurrentDb() is not None
    except Exception:
        has_db = False
    if not has_db:
        if not os.path.exists(DB_PATH):
            raise RuntimeError(f"Không thấy file {DB_PATH}. Chạy make_access_demo.py trước.")
        acc.OpenCurrentDatabase(DB_PATH)

    # mở form (lấy tên form đầu tiên trong CSDL nếu không chỉ định)
    if not form_name:
        try:
            form_name = acc.CurrentProject.AllForms.Item(0).Name
        except Exception:
            form_name = "Form1"
    try:
        acc.DoCmd.OpenForm(form_name)
    except Exception:
        pass
    if acc.Forms.Count == 0:
        raise RuntimeError(f"Không mở được form '{form_name}'.")
    frm = acc.Forms(form_name)
    print(f"  📋 Form: {frm.Name}")

    # NHẢY SANG BẢN GHI MỚI (trống) để THÊM mới, không sửa bản ghi cũ
    try:
        acc.DoCmd.SelectObject(2, frm.Name, False)   # acForm: đưa form thành active
    except Exception:
        pass
    try:
        acc.DoCmd.GoToRecord(-1, "", 5)              # acActiveDataObject, acNewRec=5 -> dòng mới
    except Exception as e:
        print(f"  (không nhảy được sang bản ghi mới: {e})")

    out = {}
    for f in fields:
        v = values_by_key.get(f["key"])
        if v in (None, "", []):
            continue
        try:
            frm.Controls(f["name"]).Value = _coerce(f["key"], v, amount_keys)
            rb = frm.Controls(f["name"]).Value
            out[f["key"]] = rb
            print(f"  • {f['label']:<22} = {rb!r}  [✓]")
        except Exception as e:
            print(f"  • {f['label']:<22} ⛔ {e}")

    if submit:
        try:
            acc.DoCmd.RunCommand(97)             # acCmdSaveRecord
            print("✅ Đã lưu bản ghi vào bảng HoaDon.")
        except Exception as e:
            print(f"⚠️  Lưu bản ghi lỗi: {e}")
    return out


if __name__ == "__main__":
    print(f"Cấu hình {len(FIELDS)} ô (điền form Access đang mở qua COM).")
