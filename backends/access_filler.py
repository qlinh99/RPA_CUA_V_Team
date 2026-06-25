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

    # [A2] NHẢY SANG BẢN GHI MỚI — abort nếu thất bại để tránh ghi đè bản ghi cũ
    try:
        acc.DoCmd.SelectObject(2, frm.Name, False)   # acForm: đưa form thành active
    except Exception:
        pass
    try:
        acc.DoCmd.GoToRecord(-1, "", 5)              # acActiveDataObject, acNewRec=5 -> dòng mới
    except Exception as e:
        print(f"  ⛔ Không nhảy được sang bản ghi mới: {e} — DỪNG để tránh ghi đè.")
        return {}

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
            # [A1] Xác nhận bản ghi đã INSERT vào bảng bằng cách query COUNT(*)
            _verify_access_record(acc, values_by_key)
        except Exception as e:
            print(f"⚠️  Lưu bản ghi lỗi: {e}")
    return out


def _verify_access_record(acc, values_by_key: dict) -> None:
    """Query bảng để xác nhận bản ghi vừa lưu có thực sự tồn tại."""
    so_hd = str(values_by_key.get("so_hoa_don") or "").strip()
    if not so_hd:
        return                                   # không có số hoá đơn → không query được
    try:
        db = acc.CurrentDb()
        # Tìm tên bảng đầu tiên trong CSDL (thường là HoaDon)
        tables = [db.TableDefs.Item(i).Name for i in range(db.TableDefs.Count)
                  if not db.TableDefs.Item(i).Name.startswith("MSys")]
        if not tables:
            return
        table = tables[0]
        # Tìm cột chứa số hoá đơn (cột text đầu tiên)
        td = db.TableDefs(table)
        inv_col = None
        for i in range(td.Fields.Count):
            fn = td.Fields.Item(i).Name
            if any(k in fn.lower() for k in ("sohoadon", "so_hoa_don", "invoice")):
                inv_col = fn
                break
        if not inv_col:
            return
        rs = db.OpenRecordset(
            f"SELECT COUNT(*) AS cnt FROM [{table}] WHERE [{inv_col}]='{so_hd}'"
        )
        cnt = rs.Fields("cnt").Value
        rs.Close()
        if cnt > 0:
            print(f"   ✅ Xác nhận: tìm thấy {cnt} bản ghi trong [{table}]"
                  f" ({inv_col}={so_hd!r}).")
        else:
            print(f"   ⚠️  acCmdSaveRecord OK nhưng KHÔNG thấy bản ghi trong [{table}]!")
    except Exception as e:
        print(f"   (không query bảng được để xác nhận: {e})")


if __name__ == "__main__":
    print(f"Cấu hình {len(FIELDS)} ô (điền form Access đang mở qua COM).")
