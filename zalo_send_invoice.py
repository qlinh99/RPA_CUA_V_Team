# -*- coding: utf-8 -*-
"""
Gửi thông tin chứng từ (OCR từ ảnh/PDF) vào khung chat Zalo của người chỉ định.
Nội dung tin nhắn TỰ ĐỔI theo tài liệu (hoá đơn / phiếu bệnh nhân / phiếu thu...),
không khoá vào 9 trường hoá đơn — dùng trích xuất động (doc_extract.extract_dynamic).

Luồng: OCR động → mở Zalo → mở khoá → tìm người → mở chat → DÁN nội dung → (tuỳ chọn) GỬI.

Chạy:
  # DÁN vào ô chat để xem trước, KHÔNG gửi:
  py -3.11 zalo_send_invoice.py "Tên người" --doc "..\\...\\HD03.pdf" --unlock

  # DÁN rồi GỬI luôn:
  py -3.11 zalo_send_invoice.py "Tên người" --doc "..\\...\\HD03.pdf" --unlock --send

An toàn: gửi tin là hành động ra ngoài → mặc định chỉ dán; chỉ gửi khi có --send.
"""
import _bootstrap  # .env, temp->D:, sys.path
import re
import sys
import time

from zalo_demo import enter_zalo, open_chat, read_value
from doc_extract import extract_dynamic, format_message


def set_clipboard(text: str) -> None:
    """Đưa text (Unicode, nhiều dòng) vào clipboard — paste chuẩn tiếng Việt."""
    import win32clipboard
    win32clipboard.OpenClipboard()
    win32clipboard.EmptyClipboard()
    win32clipboard.SetClipboardData(win32clipboard.CF_UNICODETEXT, text)
    win32clipboard.CloseClipboard()


def find_composer(dlg):
    """Ô soạn tin Zalo = Group 'richInput'. Fallback: Edit khác ô tìm kiếm."""
    for ct in ("Group", "Edit", "Document", "Pane"):
        try:
            return dlg.child_window(auto_id="richInput", control_type=ct).wrapper_object()
        except Exception:
            continue
    try:
        for w in dlg.descendants(control_type="Edit"):
            if w.element_info.automation_id != "contact-search-input":
                return w
    except Exception:
        pass
    return None


def composer_text(dlg) -> str:
    """Đọc nội dung ô soạn tin: tên của Group richInput (Zalo để text ở Name)."""
    c = find_composer(dlg)
    if c is None:
        return ""
    try:
        nm = c.element_info.name
        if nm and nm.strip():
            return nm
    except Exception:
        pass
    return read_value(c)


def focus_composer(dlg, composer) -> bool:
    """Focus ô soạn tin: click vào placeholder 'tin nhắn tới ...' (đang hiển thị)."""
    # 1) tìm ĐÚNG placeholder 'tin nhắn tới' (loại 'Tin nhắn thoại'), click nó
    try:
        for w in dlg.descendants(control_type="Text"):
            nm = w.element_info.name or ""
            if re.search(r"(?i)tin nh.n t.i", nm):   # 'tin nhắn tới'
                try:
                    if w.is_visible():
                        w.click_input()
                        return True
                except Exception:
                    pass
    except Exception:
        pass
    # 2) fallback: click ô Edit nếu có toạ độ hợp lệ
    if composer is not None:
        try:
            r = composer.rectangle()
            if r.width() > 0 and r.height() > 0:
                composer.click_input()
                return True
        except Exception:
            pass
    return False


def run(name: str, doc: str, do_send: bool = False) -> int:
    """OCR hoá đơn -> mở Zalo -> mở chat 'name' -> dán nội dung -> (tuỳ chọn) gửi."""
    from pywinauto.keyboard import send_keys

    # 1) OCR ĐỘNG: tin nhắn tự đổi theo nội dung ảnh/PDF (hoá đơn, phiếu BN, phiếu thu...)
    print(f"🧾 OCR (động) chứng từ: {doc}")
    data = extract_dynamic(doc)
    msg = format_message(data)
    print(f"\n--- TIN NHẮN ({data.get('loai_tai_lieu') or 'chứng từ'}) ---\n"
          + msg + "\n----------------")

    # 2) mở Zalo (tự chờ trạng thái + tự mở khoá nếu cần) -> mở chat đúng người
    dlg = enter_zalo()
    if dlg is None:
        return 2
    if not open_chat(dlg, name):
        return 2
    time.sleep(1.0)

    # 3) ô soạn tin (Edit khác search) + focus bằng click placeholder
    composer = find_composer(dlg)
    if not focus_composer(dlg, composer):
        print("⛔ Không focus được ô soạn tin (chat có thể CHƯA mở thật).")
        return 2
    time.sleep(0.4)

    # 4) dán nội dung, rồi ĐỌC LẠI ô soạn tin để xác minh dán đúng
    send_keys("^a"); send_keys("{BACKSPACE}")
    set_clipboard(msg)
    send_keys("^v")
    time.sleep(0.6)
    val = composer_text(dlg)                       # đọc tên richInput
    if not val.strip():
        print("⛔ Đã dán nhưng ô soạn tin vẫn trống → chưa focus/dán đúng chỗ.")
        print("   Gửi tôi:  py -3.11 inspect_uia.py \"Zalo\" --all   (khi đang mở chat).")
        return 2
    print(f"📋 Đã dán & xác minh nội dung ô soạn tin (đọc lại: {val[:40]!r}...)")

    # 5) gửi: Enter rồi XÁC MINH ô đã trống (Zalo xoá ô sau khi gửi)
    if not do_send:
        print("💡 Chưa gửi (xem trước). Tự bấm Enter trong Zalo, hoặc chạy lại với --send.")
        return 0

    send_keys("{ENTER}")
    time.sleep(1.2)
    after = composer_text(dlg)
    if val.strip() and not after.strip():
        print(f"✅ Đã GỬI tin nhắn cho '{name}' (ô soạn tin đã trống sau khi gửi).")
        return 0
    print(f"⛔ CHƯA chắc gửi được — ô soạn tin sau Enter vẫn còn: {after[:40]!r}. Kiểm tra Zalo.")
    return 2


def main() -> int:
    pos = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not pos or "--doc" not in sys.argv:
        print(__doc__)
        return 1
    name = pos[0]
    try:
        doc = sys.argv[sys.argv.index("--doc") + 1]
    except IndexError:
        print("❌ Thiếu đường dẫn sau --doc")
        return 1
    return run(name, doc, do_send="--send" in sys.argv)


if __name__ == "__main__":
    try:
        import pywinauto  # noqa
        import win32clipboard  # noqa
    except ImportError as e:
        print(f"❌ Thiếu thư viện: {e}. Cần: py -3.11 -m pip install pywinauto pywin32")
        raise SystemExit(1)
    raise SystemExit(main())
