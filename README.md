# rpa_hoadon — Trích xuất hoá đơn (OCR) → điền tự động vào nhiều "đích"

Đọc chứng từ (ảnh/PDF) bằng OCR, rồi điền vào **5 loại đích** qua **một lệnh `autofill.py`**.
Kiến trúc tách 4 mảnh — đổi đích chỉ thay mảnh "soi" + "điền".

```
① soi đích → schema trường   ②/③ OCR + trích xuất (dùng chung)   ④ điền
```

## Cấu trúc thư mục

```
rpa_hoadon/
├─ *.py              ← TẤT CẢ code phẳng ở root (import nhau như module top-level;
│                      mọi script chạy trực tiếp `py -3.11 <file>.py`). KHÔNG tách thư mục con.
├─ README.md         ← tài liệu chính (file này)
├─ requirements.txt
├─ profiles/         ← profile đa-app (access.json, _template.json)
├─ docs/             ← PROJECT_STATE.md · TODO.md · DECISIONS.md · DEMO.md
├─ reports/          ← bao_cao_3_bac.html · tool_flowchart.html
├─ screenshots/      ← bằng chứng chạy (gitignore)
└─ _tmp/, form_cache/, *.xlsx, *.accdb  ← file tạm/sinh ra (gitignore)
```

> **Vì sao code không tách thư mục con?** Các `.py` import nhau phẳng và `_bootstrap`
> tính đường dẫn `.env`/engine OCR theo `HERE.parent`. Tách ra sẽ phá mọi import +
> lệnh README. Layout phẳng là đúng cho bộ "script chạy trực tiếp dùng chung module".

## 1 lệnh — 5 đích (`autofill.py`)

| Đích | Cờ | Cơ chế | Bậc |
|------|-----|--------|-----|
| Google Form | `--form <URL>` | Playwright / HTTP POST | 1–3 |
| Excel | `--excel <file>` | openpyxl / COM (`--watch`) | 1 |
| Microsoft Access | `--access` | COM | 1 |
| App desktop (OH) | `--app` | pywinauto-UIA | 3 |
| Zalo | `--zalo --to <tên>` | pywinauto-UIA | 3 |

Mặc định **chỉ trích xuất xem trước**; thêm **`--submit`** mới thực sự ghi/gửi.
Xem đầy đủ: `py -3.11 autofill.py -h`.

**Fallback CUA Gemini (Bậc 4):** nhánh Form tự rơi xuống CUA khi Playwright gãy; ép bằng `--cua`.
**Đa-app:** `--profile <tên>` đọc `profiles/<tên>.json` (thêm app khác = thêm 1 JSON).
**Verification:** `verify.py` đối soát responses với nguồn (xem mục dưới).

## Yêu cầu

- Chạy bằng **Python 3.11**: `py -3.11` (bản có cv2, playwright, fitz, pdfplumber, openpyxl, pywin32, pywinauto).
- `.env` ở `D:\python\ocr_vsf\.env`: `OCR_PROVIDER=gemini` + `GEMINI_API_KEY=...` (và `ZALO_PASSWORD=...` nếu dùng demo Zalo).
- Luôn `cd` vào thư mục này trước khi chạy.

```powershell
cd D:\python\ocr_vsf\rpa_hoadon
```

## 1) Đích = Google Form

```powershell
# xem trước (không gửi)
py -3.11 autofill.py --form "https://forms.gle/XXXX" --doc "..\...\hoadon.pdf"
# gửi (thêm --headed để xem trình duyệt; --post để gửi bằng HTTP)
py -3.11 autofill.py --form "https://forms.gle/XXXX" --doc "..\...\hoadon.pdf" --submit --headed
# đợt sau cùng form → bỏ trống --form (tự dùng form cũ); --refresh nếu form bị sửa
py -3.11 autofill.py --doc "..\...\hoadon2.pdf" --submit
```

## 2) Đích = Excel

```powershell
py -3.11 excel_target.py bao_cao.xlsx        # tạo báo cáo mẫu (1 lần)
py -3.11 autofill.py --excel bao_cao.xlsx --doc "..\...\hoadon.pdf"            # xem trước
py -3.11 autofill.py --excel bao_cao.xlsx --doc "..\...\hoadon.pdf" --submit   # ghi 1 dòng
py -3.11 autofill.py --excel bao_cao.xlsx --doc "..\...\hoadon.pdf" --submit --watch  # mở Excel nhìn điền
```

## 3) Đích = Microsoft Access (qua COM — ổn định)

```powershell
py -3.11 make_access_demo.py     # tạo hoadon_demo.accdb + form (1 lần)
# ĐÓNG Access, rồi:
py -3.11 autofill.py --access --doc "..\...\hoadon.pdf" --submit
```
Access có API (COM) → điền thẳng `Forms.Controls.Value`, không dùng UIA (Access chống UIA).

## 4) Đích = App desktop (UIA — cho app KHÔNG có API như OH)

```powershell
# B1: soi app lấy auto_id từng ô  →  điền vào FIELDS trong desktop_filler.py
py -3.11 inspect_uia.py "<tên app>" --all
# B2: chạy
py -3.11 autofill.py --app --doc "..\...\hoadon.pdf"            # xem trước
py -3.11 autofill.py --app --doc "..\...\hoadon.pdf" --submit   # điền + Lưu
```

## 5) Đa-app qua profile (thêm app khác = thêm 1 file JSON)

```powershell
py -3.11 inspect_uia.py "<tên app>" --all          # soi lấy auto_id/name
copy profiles\_template.json profiles\<ten>.json   # điền window_title, fields, method (uia|com)
py -3.11 autofill.py --profile <ten> --doc "..\...\hoadon.pdf" --submit
```
`method:"com"` cho app có API (Access); `method:"uia"` cho app không API (OH). Có sẵn `profiles/access.json`.

## 6) Fallback CUA Gemini (Bậc 4 — khi Bậc 3 gãy)

```powershell
py -3.11 autofill.py --form "<URL>" --doc "..\...\hoadon.pdf" --submit --cua --headed
```
Gemini Vision nhìn ảnh form → trả toạ độ từng ô → Playwright click/gõ (pixel, không selector).
Nhánh Form **tự** gọi CUA khi Playwright thất bại. (Cần `GEMINI_API_KEY`.)

## 7) Verification — maker-checker (R4)

```powershell
# Tải responses: Form -> Responses -> ⋮ -> Download .csv
py -3.11 verify.py --responses "Downloads\... (Responses).csv"
# hoặc URL sheet đã publish:
py -3.11 verify.py --responses "https://docs.google.com/spreadsheets/d/<ID>/export?format=csv"
```
Đối soát từng dòng nộp với nguồn đúng (`ground_truth.csv`) theo số hoá đơn → báo cáo
`verified / mismatch (kèm trường lệch) / missing` + cảnh báo trùng. Tự chuẩn hoá ngày/số/thuế/tên.

## Demo desktop có sẵn (Zalo) — chứng minh toàn bộ kỹ thuật

```powershell
# mở Zalo → (tự) mở khoá → tìm người → mở chat
py -3.11 zalo_demo.py "Tên người"
# + OCR hoá đơn rồi GỬI vào chat người đó (mặc định chỉ dán; --send mới gửi)
py -3.11 zalo_send_invoice.py "Tên người" --doc "..\...\hoadon.pdf"
py -3.11 zalo_send_invoice.py "Tên người" --doc "..\...\hoadon.pdf" --send
```

## Các file

| Nhóm | File | Vai trò |
|------|------|---------|
| Nhạc trưởng | `autofill.py` | tool hợp nhất: `--form` / `--excel` / `--app` + `--doc` |
| Khởi tạo | `_bootstrap.py` | temp→D:, nạp .env, nối pipeline OCR ở thư mục cha |
| Đọc tài liệu | `doc_reader.py` | ảnh/PDF → trang (PDF điện tử đọc text, scan thì OCR ảnh) |
| Chuẩn hoá | `ocr_to_form.py` | ngày `DD/MM/YYYY`, thuế `0/5/8/10%`, số tiền |
| Soi đích | `inspect_form.py` / `inspect_uia.py` | soi Google Form / soi cây UIA app desktop |
| Điền — Form | `form_filler.py`, `fill_invoice_form*.py` | Playwright / HTTP POST |
| Điền — Excel | `excel_target.py` (openpyxl), `excel_com.py` (Excel thật) | mỗi chứng từ = 1 dòng |
| Điền — Desktop | `desktop_filler.py` (UIA), `access_filler.py` (Access COM) | điền app desktop |
| Đa-app | `desktop_profiles.py`, `profiles/*.json` | mỗi app = 1 profile |
| Fallback | `cua_fallback.py` | CUA Gemini (Bậc 4) cho web form |
| Verification | `verify.py` | đối soát responses ↔ nguồn (R4) |
| Demo desktop | `zalo_demo.py`, `zalo_send_invoice.py` | mở app→mở khoá→điều hướng→điền→gửi |
| Chuyên hoá đơn | `hoadon_to_form.py`, `form_config.py` | bản cố định 9 trường (tiền thân autofill) |

## Bộ "đồ nghề" desktop (trong zalo_demo.py — tái dùng cho mọi app)

`connect/launch`, `wait_ready` (nhận trạng thái), `force_front` (ép cửa sổ lên trước),
mở khoá đa-chiến-thuật, định vị theo `auto_id`, dán clipboard, **xác minh từng bước**
(đọc lại / state đổi), screenshot bằng chứng.

## Áp cho OH (Orion Health HIS) sau này

OH là .NET WinForms → UIA tốt hơn Zalo (dùng được Họ A `SetValue`/`Invoke`, verify không cần OCR).
Khi có máy trong mạng Vingroup: `inspect_uia.py "OrionHealth" --all` → điền `WINDOW_TITLE` + `FIELDS`
+ `SUBMIT` trong `desktop_filler.py`, thêm bước đăng nhập/điều hướng. Lưu ý: mật khẩu dùng vault
(không để .env), chỉ chạy UAT, audit log, người duyệt ở bước lâm sàng.
(OH có SOAP middle-tier → nếu xin được API thì đó là Bậc 1, tốt hơn UI automation.)

## Deliverables bài tập (R1–R4)

| | Yêu cầu | Trong repo |
|--|---------|-----------|
| R1 | Bậc 1–2: submit không trình duyệt | `--form --post` (HTTP POST) |
| R2 | Bậc 3: Playwright + screenshot + retry | `--form` (mặc định) |
| R3 | Bậc 4: CUA | `--cua` (Gemini Vision + Playwright) |
| R4 | Verification maker-checker | `verify.py` |

## Cài đặt (máy mới)

```powershell
py -3.11 -m pip install -r requirements.txt
# KHÔNG cần tải Chromium — Playwright dùng Chrome sẵn có (channel="chrome").
```

Cần `.env` ở thư mục cha (`..\.env`): `OCR_PROVIDER=gemini`, `GEMINI_API_KEY=...`
(và `ZALO_PASSWORD=...` nếu dùng demo Zalo). Engine OCR (`test_image_processing.py`) nằm ở thư mục cha.
#
