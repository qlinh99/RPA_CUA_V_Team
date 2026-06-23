# DECISIONS — quyết định kỹ thuật

> Ghi lý do các lựa chọn quan trọng. Cập nhật: 2026-06-23.

## D1. Kiến trúc 4 mảnh + "đích" cắm-rút
Tách soi-đích / OCR / trích-xuất / điền. Mảnh OCR+trích-xuất dùng chung mọi đích.
→ Đổi đích chỉ thay mảnh soi + điền. Cho phép 1 tool điền Form/Excel/Access/desktop/Zalo.

## D2. "Thang 5 bậc" — có API thì dùng API, đừng cố UI
- Excel/Access **có API** (openpyxl/COM) → Bậc 1, ổn định nhất.
- Web form không "API" công khai → Playwright (Bậc 3) hoặc POST tới `formResponse` (thực ra là Bậc 1 ẩn).
- App desktop không API (OH/Zalo) → pywinauto-UIA (Bậc 3).
- Chỉ pixel (Electron/Citrix/UI đổi) → CUA (Bậc 4, fallback).

## D3. Access dùng COM, KHÔNG dùng UIA
Access UIA: `set value` báo "Member not found"; datasheet `Ctrl+A`/`Del` suýt xoá sạch bản ghi.
→ Chuyển sang COM (`Dispatch("Access.Application")` + `Forms.Controls(name).Value`). Ổn định, an toàn.
Đây là minh hoạ D2: Access có API → đừng đánh nhau với UIA.

## D4. Zalo (Electron) — clipboard + đọc Name để verify
Electron phơi UIA nghèo: `SetValue` không ăn → dùng **clipboard + Ctrl+V** (chuẩn tiếng Việt).
Nút "MỞ" là Hyperlink không phải Button → **đa chiến thuật** (Enter/invoke/click/toạ độ), kiểm sau mỗi cách.
Ô soạn tin `richInput` không cho đọc value → **đọc thuộc tính Name** để xác minh đã dán/đã gửi.

## D5. CUA = fallback, KHÔNG thay Playwright cho form
Đo thực: CUA ~48s/bản ghi, định vị ~1/9 ô đúng (toạ độ Gemini lệch) vs Playwright 7.2s điền đúng cả 9.
→ CUA chỉ dùng khi bậc tất định gãy (UI không selector/đổi layout). Tự fallback khi Playwright fail; ép `--cua`.
CUA tái dùng adapter Gemini OCR (không cần browser-use/pyautogui).

## D6. Verification bắt buộc — "submit ≠ đúng"
Mọi bước điền đều **đọc lại để kiểm** (maker-checker). `verify.py` đối soát responses ↔ nguồn.
Bằng chứng: CUA tạo 1 dòng chỉ có 1 ô → "đã submit" nhưng sai → verify chấm mismatch.

## D7. Form nhiều trang
- **POST**: tất cả entry id nằm chung dữ liệu → gửi hết 1 lần + `pageHistory=0,1,...,N-1`. Không quan tâm số trang.
- **Playwright**: vòng lặp "điền ô trang hiện tại (tìm theo nhãn trong listitem) → bấm Tiếp → ... → Gửi".
  Chờ `[role='button']` (không chờ `listitem`) để qua được **trang bìa không có ô**.
- Hạn chế: form **rẽ nhánh** thì pageHistory tuyến tính chưa đúng.

## D8. Hệ profile đa-app (JSON)
Mỗi app desktop = 1 file `profiles/<tên>.json` (window_title, exe, method uia|com, fields, submit).
`--profile <tên>` tự route COM/UIA theo `method`. Thêm app = thêm 1 JSON, không sửa code.

## D9. Môi trường
- `py -3.11` (không `python` — trỏ venv thiếu lib).
- Temp→D: (ổ C đầy) qua `_bootstrap`.
- Playwright dùng Chrome sẵn có (`channel="chrome"`) — không tải Chromium (ổ đầy + tránh phụ thuộc).
- `.env` ở thư mục cha, KHÔNG commit; bí mật thật dùng vault cho production.

## D10. Model Gemini
`gemini-1.5-flash` bị Google gỡ (HTTP 404) → đổi fallback sang `gemini-2.5-flash-lite` (quota free cao nhất)
→ `gemini-2.0-flash`. Model chính `gemini-2.5-flash`.

## D11. Ghi ngày vào Excel qua COM
pywin32 đẩy `datetime` qua COM bị lệch múi giờ (-7h VN → ngày lùi 1 + 17:00).
→ Ghi ngày bằng **số sê-ri Excel** (`(d - 1899-12-30).days`) + NumberFormat `dd/mm/yyyy`. (openpyxl không bị.)

## D12. Di động Zalo
`ZALO_EXE` tự dò theo `%LOCALAPPDATA%` + glob (không gắn cứng tên user); cho `.env` ghi đè.
auto_id Zalo là ID nội bộ app → ổn định mọi máy cùng phiên bản; mã khoá/tài khoản là per-người.
