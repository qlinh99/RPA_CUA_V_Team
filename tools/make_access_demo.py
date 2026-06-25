# -*- coding: utf-8 -*-
"""
Tạo "OH giả" bằng Microsoft Access: 1 CSDL + bảng HoaDon + form nhập liệu FormHoaDon.
Dùng để test backend --app (desktop) khi chưa truy cập được OH thật.

Chạy:  py -3.11 make_access_demo.py
=> tạo file hoadon_demo.accdb, mở Access hiển thị form FormHoaDon (chế độ nhập liệu).
Sau đó soi form:  py -3.11 inspect_uia.py "FormHoaDon" --all   (hoặc "hoadon_demo")
"""
import os
import sys
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "hoadon_demo.accdb")

# (cột trong bảng, kiểu Access, nhãn tiếng Việt trên form)
COLS = [
    ("SoHoaDon",      "TEXT(50)",  "Số hoá đơn"),
    ("KyHieu",        "TEXT(50)",  "Ký hiệu hoá đơn"),
    ("NgayLap",       "DATETIME",  "Ngày lập"),
    ("TenNCC",        "TEXT(255)", "Tên nhà cung cấp"),
    ("MST",           "TEXT(50)",  "MST nhà cung cấp"),
    ("DienGiai",      "TEXT(255)", "Diễn giải"),
    ("TienTruocThue", "DOUBLE",    "Tiền trước thuế"),
    ("ThueSuat",      "TEXT(10)",  "Thuế suất GTGT"),
    ("TongThanhToan", "DOUBLE",    "Tổng tiền thanh toán"),
]

# hằng số Access
acTextBox, acLabel, acForm, acSaveYes = 109, 100, 2, 1


def main():
    import win32com.client as win32

    if os.path.exists(DB):
        os.remove(DB)

    acc = win32.Dispatch("Access.Application")
    acc.Visible = True
    acc.NewCurrentDatabase(DB)
    db = acc.CurrentDb()

    # 1) bảng
    cols_sql = ", ".join(f"{c} {t}" for c, t, _ in COLS)
    db.Execute(f"CREATE TABLE HoaDon ({cols_sql})")
    print("✅ Đã tạo bảng HoaDon")

    # 2) form bound vào bảng + textbox cho từng cột
    try:
        acc.DoCmd.SetWarnings(False)
        frm = acc.CreateForm()
        form_name = frm.Name             # LƯU tên ngay (đừng gọi frm.* sau khi Close)
        frm.RecordSource = "HoaDon"
        top = 200
        for c, _t, caption in COLS:
            lbl = acc.CreateControl(form_name, acLabel, 0, "", "", 200, top, 2600, 300)
            lbl.Caption = caption
            txt = acc.CreateControl(form_name, acTextBox, 0, "", c, 2900, top, 4200, 300)
            txt.ControlSource = c
            txt.Name = "txt" + c          # Name để nhắm bằng UIA
            top += 420
        acc.DoCmd.Save(acForm, form_name)
        acc.DoCmd.Close(acForm, form_name, acSaveYes)

        # đặt form này tự mở khi mở file (để --app tự bật được form)
        try:
            db.Properties("StartUpForm").Value = form_name
        except Exception:
            prop = db.CreateProperty("StartUpForm", 10, form_name)   # 10 = dbText
            db.Properties.Append(prop)

        acc.DoCmd.OpenForm(form_name)     # mở chế độ nhập liệu
        print(f"✅ Đã tạo & mở form '{form_name}' (các ô tên 'txt<Cột>')")
    except Exception as e:
        print(f"⚠️  Tạo form tự động lỗi: {e}")
        print("   → Làm tay: trong Access chọn bảng HoaDon → Ribbon Create → Form → Save tên 'FormHoaDon'.")

    print(f"\n📄 File: {DB}")
    print('➜ Soi form:  py -3.11 inspect_uia.py "FormHoaDon" --all')


if __name__ == "__main__":
    try:
        import win32com.client  # noqa
    except ImportError:
        print("❌ Cần pywin32: py -3.11 -m pip install pywin32")
        raise SystemExit(1)
    main()
