# -*- coding: utf-8 -*-
"""
Backend ĐÍCH = APP DESKTOP (pywinauto-UIA). Điền dữ liệu OCR vào một app Windows.
Tái dùng bộ đồ nghề đã kiểm chứng trên Zalo: force_front, clipboard, read-back verify.

Định vị ô theo 'auto_id' HOẶC 'name' (một số app như Access để định danh ở Name,
auto_id rỗng). Lấy chúng bằng:  py -3.11 inspect_uia.py "<tên app>" --all

ĐANG CẤU HÌNH CHO: Microsoft Access (form FormHoaDon trong hoadon_demo.accdb).
"""
from __future__ import annotations
import _bootstrap  # .env, temp->D:, sys.path
import os
import re
import time

def force_front(dlg) -> None:
    try:
        dlg.set_focus()
    except Exception:
        pass


def set_clipboard(text: str) -> None:
    import win32clipboard  # type: ignore
    win32clipboard.OpenClipboard()
    win32clipboard.EmptyClipboard()
    win32clipboard.SetClipboardText(str(text), win32clipboard.CF_UNICODETEXT)
    win32clipboard.CloseClipboard()


def read_value(ctrl) -> str:
    try:
        return ctrl.window_text() or ""
    except Exception:
        return ""


# ====================== CẤU HÌNH APP ĐÍCH (SỬA Ở ĐÂY) ======================
# Trỏ tới file .accdb → tự mở Access + form (FormHoaDon là StartUpForm).
APP_EXE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "hoadon_demo.accdb")
WINDOW_TITLE = "Access"       # regex 1 phần tiêu đề cửa sổ đích

# key | label (cho OCR) | name (UIA Name của ô) | type
FIELDS: list[dict] = [
    {"key": "so_hoa_don",      "label": "Số hoá đơn",          "name": "txtSoHoaDon",      "type": "text"},
    {"key": "ky_hieu",         "label": "Ký hiệu hoá đơn",     "name": "txtKyHieu",        "type": "text"},
    {"key": "ngay_lap",        "label": "Ngày lập",            "name": "txtNgayLap",       "type": "date"},
    {"key": "ten_ncc",         "label": "Tên nhà cung cấp",    "name": "txtTenNCC",        "type": "text"},
    {"key": "mst_ncc",         "label": "MST nhà cung cấp",    "name": "txtMST",           "type": "text"},
    {"key": "dien_giai",       "label": "Diễn giải",           "name": "txtDienGiai",      "type": "text"},
    {"key": "tien_truoc_thue", "label": "Tiền trước thuế",     "name": "txtTienTruocThue", "type": "text"},
    {"key": "thue_suat",       "label": "Thuế suất GTGT",      "name": "txtThueSuat",      "type": "text"},
    {"key": "tong_thanh_toan", "label": "Tổng tiền thanh toán","name": "txtTongThanhToan", "type": "text"},
]
# Access lưu record khi gõ Shift+Enter; form không có nút Lưu riêng.
SUBMIT = {"keys": "+{ENTER}"}   # hoặc {"auto_id": "..."} / {"name": "..."} với app có nút Lưu
# ===========================================================================


def connect_or_launch(title: str = WINDOW_TITLE, exe: str = APP_EXE, timeout: int = 40):
    from pywinauto import Desktop

    def _find():
        wins = Desktop(backend="uia").windows(title_re=f"(?i).*{title}.*")
        vis = [w for w in wins if w.is_visible()] or wins
        if not vis:
            raise RuntimeError("no window")
        best = max(vis, key=lambda w: w.rectangle().width() * w.rectangle().height())
        return Desktop(backend="uia").window(handle=best.handle)

    try:
        return _find()
    except Exception:
        if exe and os.path.exists(exe):
            print(f"🚀 Khởi chạy: {exe}")
            os.startfile(exe)
            end = time.time() + timeout
            while time.time() < end:
                try:
                    return _find()
                except Exception:
                    time.sleep(1)
        raise RuntimeError(f"Không thấy cửa sổ '{title}' (app đã mở chưa? đúng tiêu đề chưa?)")


def _locate(dlg, field: dict):
    """Tìm control theo auto_id hoặc theo Name (khớp 1 phần — Access có tiền tố 'Detail Section, ')."""
    if field.get("auto_id"):
        return dlg.child_window(auto_id=field["auto_id"], control_type="Edit").wrapper_object()
    nm = field["name"]
    return dlg.child_window(title_re=f"(?i).*{re.escape(nm)}.*", control_type="Edit").wrapper_object()


def fill_one(dlg, field: dict, value) -> str:
    from pywinauto.keyboard import send_keys
    print("       [locate]", end="", flush=True)
    ctrl = _locate(dlg, field)
    print(" [click]", end="", flush=True)
    try:
        ctrl.click_input()
    except Exception as e:
        print(f"(click lỗi {e})", end="", flush=True)
        try:
            ctrl.set_focus()
        except Exception:
            pass
    time.sleep(0.15)

    # Họ A: ValuePattern.SetValue
    done = False
    print(" [setvalue]", end="", flush=True)
    try:
        ctrl.iface_value.SetValue(str(value))
        done = True
    except Exception as e:
        print(f"(setvalue lỗi {e})", end="", flush=True)
    # Họ B: clipboard
    if not done:
        print(" [paste]", end="", flush=True)
        send_keys("^a"); send_keys("{DEL}")
        set_clipboard(str(value))
        send_keys("^v")
    time.sleep(0.2)
    print(" [read]", flush=True)
    return read_value(ctrl)


def do_submit(dlg, submit_cfg: "dict | None" = None) -> None:
    from pywinauto.keyboard import send_keys
    sub = submit_cfg if submit_cfg is not None else SUBMIT
    if sub.get("auto_id") or sub.get("name"):
        kw = {k: v for k, v in sub.items() if k in ("auto_id", "name") and v}
        try:
            btn = dlg.child_window(**kw).wrapper_object()
            try:
                btn.invoke()
            except Exception:
                btn.click_input()
            print("✅ Đã bấm nút Lưu.")
            return
        except Exception as e:
            print(f"⛔ Không bấm được nút Lưu: {e}")
    if sub.get("keys"):
        send_keys(sub["keys"])
        print(f"✅ Đã gửi phím lưu record ({sub['keys']}).")


def fill_desktop(values_by_id: dict, *, submit: bool = False, profile: "dict | None" = None) -> dict:
    # cấu hình: từ profile (đa-app) hoặc module (mặc định)
    if profile:
        fields = profile["fields"]
        title = profile["window_title"]
        exe = profile.get("exe", "")
        if exe and not os.path.isabs(exe):
            exe = os.path.join(os.path.dirname(os.path.abspath(__file__)), exe)
        submit_cfg = profile.get("submit", {})
    else:
        fields, title, exe, submit_cfg = FIELDS, WINDOW_TITLE, APP_EXE, SUBMIT

    dlg = connect_or_launch(title, exe)
    # chờ form tải xong (ô đầu tiên xuất hiện) — mở file mất vài giây
    if fields:
        end = time.time() + 20
        while time.time() < end:
            try:
                _locate(dlg, fields[0])
                break
            except Exception:
                time.sleep(1)
                try:
                    dlg = connect_or_launch(title, exe)
                except Exception:
                    pass
    force_front(dlg)
    print(f"  🪟 Đã bám cửa sổ: {dlg.window_text()!r}")
    out = {}
    for f in fields:
        v = values_by_id.get(f["key"])
        if v in (None, "", []):
            continue
        print(f"  → đang điền: {f['label']}")
        try:
            rb = fill_one(dlg, f, v)
        except Exception as e:
            print(f"  • {f['label']:<22} ⛔ KHÔNG tìm thấy ô (name={f.get('name')!r}): {e}")
            continue
        out[f["key"]] = rb
        flag = "✓" if str(rb).strip() == str(v).strip() else "≠"
        print(f"  • {f['label']:<22} điền {v!r} → đọc lại {rb!r}  [{flag}]")
    if submit:
        do_submit(dlg, submit_cfg)
    return out


def schema() -> list[dict]:
    """Schema cho autofill: id=key (Access định danh bằng Name nên không dùng auto_id làm id)."""
    return [{"id": f["key"], "label": f["label"], "type": f.get("type", "text")} for f in FIELDS]


if __name__ == "__main__":
    print(f"Cấu hình {len(FIELDS)} ô cho cửa sổ ~ '{WINDOW_TITLE}'.")
