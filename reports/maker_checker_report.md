# Báo cáo Maker–Checker: Hệ thống RPA Thu Ngân

**Ngày:** 2026-06-25  
**Phạm vi:** Google Forms · Excel · Microsoft Access  
**Tác giả:** Claude Sonnet 4.6 — phân tích tĩnh từ source code

---

## 1. Tổng quan kiến trúc Maker–Checker

```
CHỨNG TỪ (ảnh/PDF/CSV)
       │
       ▼
  [MAKER — OCR + LLM]
       │  extract_values()  →  _normalize_record()
       │  • OCR trang ảnh hoặc đọc text
       │  • LLM trích xuất JSON {id: giá_trị}
       │  • normalize_value(): chuẩn hoá kiểu (ngày, option, số)
       │  • Sinh issues[] — lỗi bắt buộc chặn gửi, tùy chọn để qua
       ▼
  [CHECKER — xác nhận trước ghi/gửi]
       │
       ├── Gform  : _labels_on_page + on_page_fail + _confirm_submitted
       ├── Excel  : _coerce + append_row / append_row_visible
       └── Access : fill_access → read-back frm.Controls().Value [✓/⛔]
```

---

## 2. Chi tiết từng hệ thống đích

### 2.1 Google Forms (Gform)

#### Luồng Maker
| Bước | Hàm | Mô tả |
|------|-----|--------|
| 1 | `resolve_schema()` | Soi form qua `FB_PUBLIC_LOAD_DATA_`, lưu cache JSON |
| 2 | `extract_values()` | OCR chứng từ, cache trong phiên tránh OCR lần 2 |
| 3 | `_normalize_record()` | Chuẩn hoá từng trường, in preview, sinh `issues[]` |
| 4 | `_submit_form_record()` | Gọi Playwright điền + gửi |

#### Luồng Checker
| Bước | Hàm | Cơ chế kiểm tra |
|------|-----|-----------------|
| C1 | `_normalize_record()` | Kiểm tra `required` + kiểu → sinh `issues[]` |
| C2 | `_labels_on_page()` | 1 JS roundtrip xác nhận nhãn nào hiển thị trang hiện tại |
| C3 | `on_page_fail` tracking | Đếm trường điền thất bại mỗi trang, in cảnh báo ⚠️ |
| C4 | `_confirm_submitted()` | Chờ URL chuyển sang `formResponse`, hoặc text "đã ghi câu trả lời" |
| C5 | Screenshot | Chụp màn hình lưu `screenshots/` — có hậu tố `_FAIL` nếu lỗi |
| C6 | `retries=2` | Retry tự động khi gặp lỗi Timeout |

#### Lỗ hổng phát hiện

| # | Vị trí | Mô tả lỗ hổng | Mức độ |
|---|--------|---------------|--------|
| G1 | `_attempt()` L.263–264 | Không có pre-submit check DOM trước khi bấm "Gửi": nếu `_try_fill_field` trả `True` nhưng DOM thực tế không thay đổi (JS click không có hiệu lực), form vẫn bị nộp thiếu | **Cao** |
| G2 | `fill_and_submit_browser()` | `debug=False` theo mặc định → chi tiết trường nào thất bại bị ẩn; chỉ in số lượng | **Trung** |
| G3 | `_submit_form_record()` L.324–333 | CUA fallback bị vô hiệu khi dùng shared browser → bản ghi 2–3 trong batch thất bại không có fallback | **Cao** |
| G4 | `inspect_form.py` L.51 | Đếm trang = `1 + count(page-break)` — tĩnh; form có logic điều kiện (conditional section) sẽ đếm sai số trang | **Thấp** |
| G5 | `_find_nav()` | Nếu cả Submit và Next đều có trên trang, Submit được ưu tiên → có thể submit sớm khi còn trang sau | **Trung** |
| G6 | `_labels_on_page()` | Với trường grid, `item["label"]` là nhãn dòng con (e.g. "Tôi xác nhận..."). Nếu chuỗi này xuất hiện trong nhiều listitem khác nhau, có thể false-positive → nhảy qua điền nhưng trang chưa thực sự có trường đó | **Thấp** |
| G7 | `_confirm_submitted()` L.185 | Timeout 12 giây — mạng chậm hoặc server GForm bận → false-negative (báo thất bại dù đã gửi) | **Thấp** |

---

### 2.2 Microsoft Excel

#### Luồng Maker
| Bước | Hàm | Mô tả |
|------|-----|--------|
| 1 | `inspect_excel()` | Đọc dòng header → `[{id, label, type, col}]` |
| 2 | `extract_values()` | OCR → JSON |
| 3 | `_normalize_record()` | Chuẩn hoá, in preview |
| 4 | `append_row()` / `append_row_visible()` | Thêm dòng vào sheet |

#### Luồng Checker
| Bước | Hàm | Cơ chế kiểm tra |
|------|-----|-----------------|
| C1 | `_coerce()` | Chuyển kiểu: ngày → `date`, số nguyên → `int`, text → `str` |
| C2 | `append_row()` | Trả số dòng đã ghi |
| C3 | `append_row_visible()` | Mở Excel thật, con trỏ nhảy từng ô → người giám sát có thể nhìn |

#### Lỗ hổng phát hiện

| # | Vị trí | Mô tả lỗ hổng | Mức độ |
|---|--------|---------------|--------|
| E1 | `append_row()` L.80–83 | Không có **read-back**: sau khi `ws.cell().value = val` và `wb.save()`, không đọc lại ô để xác nhận giá trị đúng | **Cao** |
| E2 | `inspect_excel()` L.34 | `ws.max_row` đếm theo openpyxl — nếu sheet có ô trống xen kẽ hoặc merged cells, `max_row` có thể cao hơn thực tế → ghi đè dữ liệu hoặc bỏ trống dòng | **Trung** |
| E3 | `inspect_excel()` L.30 | `_guess_type()` chỉ kiểm tra "ngày/ngay/date" trong nhãn; các cột số tiền không được nhận dạng → `_coerce()` không chuyển thành `int` → Excel lưu text thay vì số | **Trung** |
| E4 | `append_row()` | Không kiểm tra trùng lặp: cùng 1 hóa đơn nộp 2 lần sẽ tạo 2 dòng giống hệt nhau | **Cao** |
| E5 | `excel_com.py` L.34 | `ws.Cells(ws.Rows.Count, 1).End(XL_UP).Row` — tìm dòng cuối theo cột 1; nếu cột 1 trống nhưng cột khác có dữ liệu → tính sai dòng ghi | **Trung** |
| E6 | `run_invoice()` L.443 | `_issues` bị bỏ qua với `_` → dù trường bắt buộc thiếu, vẫn ghi vào Excel | **Cao** |

---

### 2.3 Microsoft Access

#### Luồng Maker
| Bước | Hàm | Mô tả |
|------|-----|--------|
| 1 | `desktop_filler.schema()` | Đọc `FIELDS` hằng số → `[{id, label, type}]` |
| 2 | `extract_values()` | OCR → JSON |
| 3 | `_normalize_record()` | Chuẩn hoá, in preview |
| 4 | `fill_access()` | Ghi qua COM API |

#### Luồng Checker
| Bước | Hàm | Cơ chế kiểm tra |
|------|-----|-----------------|
| C1 | `fill_access()` L.84–85 | **Read-back**: `rb = frm.Controls(f["name"]).Value` → in `[✓]` nếu khớp, `[⛔]` nếu lỗi COM |
| C2 | `acc.DoCmd.RunCommand(97)` | Lệnh `acCmdSaveRecord` lưu bản ghi |
| C3 | `GoToRecord(acNewRec=5)` | Nhảy sang bản ghi mới để tránh ghi đè |

#### Lỗ hổng phát hiện

| # | Vị trí | Mô tả lỗ hổng | Mức độ |
|---|--------|---------------|--------|
| A1 | `fill_access()` L.90–95 | Không query bảng `HoaDon` sau khi `acCmdSaveRecord` → không biết bản ghi có thực sự được INSERT vào bảng hay chỉ nằm trong buffer | **Cao** |
| A2 | `fill_access()` L.73–75 | `GoToRecord(acNewRec=5)` nếu thất bại → tiếp tục điền vào bản ghi hiện tại → **ghi đè** bản ghi cũ mà không có cảnh báo | **Cao** |
| A3 | `access_filler.py` L.12 | `AMOUNT_KEYS` chỉ có `{"tien_truoc_thue", "tong_thanh_toan"}` — `_coerce()` dùng `re.sub(r"[^\d]", "")` → mất phần thập phân (e.g. "1,250.50" → 125050) | **Trung** |
| A4 | `fill_access()` L.83 | Read-back so sánh `Value` sau khi SET — nhưng Access có thể tự format lại (e.g. ngày "15/06/2026" → "#6/15/2026#"); so sánh chuỗi có thể false-negative | **Thấp** |
| A5 | `run_access()` L.400–406 | `_issues` từ `_normalize_record()` được kiểm tra → ✅ có chặn bản ghi lỗi | — |

---

## 3. Lỗ hổng chéo (ảnh hưởng cả 3 hệ thống)

| # | Vị trí | Mô tả | Mức độ |
|---|--------|--------|--------|
| X1 | `run_invoice()` L.443 | `_issues` bị bỏ qua hoàn toàn khi dùng `run_invoice` (Excel + Access chạy cùng) → trường bắt buộc thiếu vẫn được ghi | **Nghiêm trọng** |
| X2 | `extract_values()` | Không có fallback khi LLM trả về JSON không đầy đủ (vài trường thừa, vài trường thiếu hoặc key sai) — `raw.get(_fid(f))` trả `None` im lặng | **Cao** |
| X3 | Toàn bộ | Không có **audit log file** — mọi output chỉ in stdout; khi lỗi không thể tra lại | **Trung** |
| X4 | `_normalize_record()` | `optional_empty` chỉ in tên trường, không in giá trị gốc LLM trả về → không biết LLM có trả về gì không | **Thấp** |
| X5 | `build_prompt()` | Không có ràng buộc schema độ dài giá trị → LLM có thể hallucinate chuỗi dài cho trường text | **Thấp** |

---

## 4. Đề xuất cải tiến ưu tiên

### 4.1 Ưu tiên Cao — sửa ngay

#### [FIX-X1] `run_invoice()`: không bỏ qua `_issues`

```python
# autofill.py — run_invoice(), vòng lặp ghi
for i, (merged_items, issues) in enumerate(all_records, 1):   # bỏ _
    if n > 1:
        print(f"\n  ══ Bản ghi {i}/{n} ══")
    if issues:
        print(f"⛔ Bản ghi {i}: còn trường không hợp lệ — bỏ qua.")
        for iss in issues:
            print(f"   - {iss}")
        codes.append(2)
        continue
```

#### [FIX-G1] Pre-submit DOM check trước khi bấm Gửi

Thêm vào `_attempt()` ngay trước `submit_b.click()`:

```python
# Kiểm tra DOM xem trường required nào chưa có giá trị
empty_required = page.evaluate("""() => {
    return [...document.querySelectorAll('div[role="listitem"]')]
        .filter(li => {
            const hasRequired = li.querySelector('[aria-required="true"], [required]');
            if (!hasRequired) return false;
            // Radio/checkbox: không có [aria-checked="true"] nào
            const radios = [...li.querySelectorAll('[role="radio"]')];
            if (radios.length) return !radios.some(r => r.getAttribute('aria-checked') === 'true');
            // Text: textbox trống
            const tb = li.querySelector('[role="textbox"], input, textarea');
            return tb && !tb.value;
        })
        .map(li => li.textContent.trim().slice(0, 60));
}""")
if empty_required:
    print(f"   ⛔ PRE-SUBMIT: {len(empty_required)} trường BẮT BUỘC chưa điền:")
    for t in empty_required:
        print(f"      • {t!r}")
```

#### [FIX-G3] CUA fallback trong shared browser — dùng browser mới tách biệt

```python
# autofill.py — _submit_form_record()
if not res["ok"]:
    if browser is not None:
        print(f"\n⚠️  Playwright thất bại — thử lại với browser riêng...")
        # Tạo browser mới tách biệt để tránh xung đột sync_playwright
        retry_res = form_filler.fill_and_submit_browser(
            schema["view_url"], items,
            headless=not args.headed,
            slow_mo=200 if args.headed else 0,
            shot_name=shot + "_retry",
            browser=None,   # browser=None → tự tạo sync_playwright riêng
        )
        if retry_res["ok"]:
            res = retry_res
    else:
        # CUA fallback chỉ khi không có shared browser
        ...
```

#### [FIX-A2] Kiểm tra GoToRecord thành công trước khi điền

```python
# access_filler.py — fill_access()
try:
    acc.DoCmd.GoToRecord(-1, "", 5)
    # Xác nhận đang ở bản ghi mới (ID = None / 0)
    try:
        pk_ctrl = frm.Controls("ID")
        if pk_ctrl.Value not in (None, 0, ""):
            raise RuntimeError("GoToRecord không tạo được bản ghi mới")
    except Exception:
        pass   # form không có ô ID — chấp nhận
except Exception as e:
    print(f"  ⛔ Không nhảy sang bản ghi mới: {e} — DỪNG để tránh ghi đè.")
    return {}
```

#### [FIX-A1] Verify bản ghi sau khi lưu Access

```python
# access_filler.py — sau acc.DoCmd.RunCommand(97)
try:
    db = acc.CurrentDb()
    so_hd = values_by_key.get("so_hoa_don", "")
    if so_hd:
        rs = db.OpenRecordset(
            f"SELECT COUNT(*) FROM HoaDon WHERE SoHoaDon='{so_hd}'"
        )
        cnt = rs.Fields(0).Value
        rs.Close()
        if cnt > 0:
            print(f"✅ Đã xác nhận bản ghi trong bảng HoaDon (SoHoaDon={so_hd!r}).")
        else:
            print(f"⚠️  Lưu RunCommand thành công nhưng không thấy bản ghi trong bảng!")
except Exception as e:
    print(f"  (không query được bảng để xác nhận: {e})")
```

---

### 4.2 Ưu tiên Trung — cải tiến chất lượng

#### [IMP-E1] Read-back sau openpyxl write

```python
# excel_target.py — append_row()
wb.save(path)
# Read-back verify
wb2 = load_workbook(path, read_only=True, data_only=True)
ws2 = wb2.active if not sheet else wb2[sheet]
mismatches = []
for f in fields:
    written = values_by_id.get(f["id"])
    read_back = ws2.cell(row=row, column=f["col"]).value
    if written is not None and str(read_back) != str(_coerce(written, f["type"])):
        mismatches.append(f"{f['label']}: ghi {written!r} đọc lại {read_back!r}")
wb2.close()
if mismatches:
    print(f"   ⚠️  Read-back không khớp: {'; '.join(mismatches)}")
```

#### [IMP-E4] Kiểm tra trùng lặp hóa đơn

```python
# excel_target.py — append_row(), trước khi ghi
inv_label_col = next((f["col"] for f in fields
                      if "số hoá đơn" in f["label"].lower()), None)
if inv_label_col:
    inv_val = values_by_id.get(
        next((f["id"] for f in fields if f["col"] == inv_label_col), ""))
    if inv_val:
        for r in range(header_row + 1, row):
            if ws.cell(row=r, column=inv_label_col).value == inv_val:
                print(f"   ⚠️  TRÙNG: Số hoá đơn {inv_val!r} đã có ở dòng {r}!")
                break
```

#### [IMP-X3] Audit log file

```python
# autofill.py — thêm hàm _audit_log()
import datetime
AUDIT_LOG = Path(__file__).parent / "reports" / "audit.log"

def _audit_log(target: str, doc: str, record: dict, ok: bool, detail: str = ""):
    AUDIT_LOG.parent.mkdir(exist_ok=True)
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    status = "OK" if ok else "FAIL"
    line = f"{ts} | {status} | {target} | {os.path.basename(doc)} | {detail[:80]}\n"
    with open(AUDIT_LOG, "a", encoding="utf-8") as f:
        f.write(line)
```

#### [IMP-E3] Nhận dạng kiểu cột tốt hơn

```python
# excel_target.py — _guess_type()
def _guess_type(label: str) -> str:
    l = (label or "").lower()
    if any(k in l for k in ("ngày", "ngay", "date")):
        return "date"
    if any(k in l for k in ("tiền", "tien", "thuế", "thue", "giá", "gia",
                             "phí", "phi", "amount", "price", "tax")):
        return "number"
    return "text"
```

---

### 4.3 Ưu tiên Thấp — cải tiến dài hạn

| # | Đề xuất |
|---|---------|
| L1 | Lưu kết quả OCR raw (trước `normalize_value`) vào file `.json` tạm để debug khi LLM trả sai |
| L2 | Thêm `--dry-run` flag in report đầy đủ (giá trị sẽ điền, trường sẽ bỏ qua) mà không mở browser |
| L3 | Thêm `max_length` cho trường text trong `build_prompt()` để LLM không hallucinate |
| L4 | Form cache hiện soi lại mỗi phiên — thêm TTL (24h) để giảm request, nhưng `--refresh` vẫn ép soi lại |
| L5 | Với form nhiều trang có logic điều kiện: sau mỗi `next_b.click()`, so sánh `remaining` với `on_page` để phát hiện trang ẩn/hiện động |

---

## 5. Bảng tổng hợp mức độ rủi ro

| Hệ thống | Checker hiện tại | Lỗ hổng nghiêm trọng | Lỗ hổng trung | Lỗ hổng thấp |
|----------|-----------------|---------------------|---------------|--------------|
| **Gform** | Trung (có on_page_fail, screenshot, confirm_submitted) | G1, G3 | G2, G5 | G4, G6, G7 |
| **Excel** | Yếu (không có read-back, không phát hiện trùng) | E1, E4, X1 | E2, E3, E5 | — |
| **Access** | Khá (có read-back từng ô qua COM) | A1, A2, X1 | A3 | A4 |
| **Chéo** | — | X1, X2 | X3 | X4, X5 |

**Tổng điểm rủi ro:** Excel < Access < Gform (theo mức độ khó khắc phục lỗi khi đã xảy ra)

---

## 6. Checklist đảm bảo "không bỏ sót trường" trước Submit

```
□ [OCR]     LLM trả đủ tất cả key trong fields? (không có key null không rõ lý do)
□ [NORM]    issues[] rỗng? (bao gồm cả run_invoice — hiện đang bỏ qua)
□ [GFORM]   _labels_on_page() trả đủ nhãn bắt buộc ở mỗi trang?
□ [GFORM]   on_page_fail == [] trước khi bấm Tiếp/Gửi?
□ [GFORM]   DOM pre-submit check: không có [aria-required] nào còn trống?
□ [GFORM]   _confirm_submitted() trả True (URL = formResponse)?
□ [EXCEL]   append_row() trả số dòng > header_row?
□ [EXCEL]   Read-back xác nhận giá trị ô khớp giá trị ghi?
□ [EXCEL]   Không có số hoá đơn trùng trong sheet?
□ [ACCESS]  GoToRecord(acNewRec) không lỗi?
□ [ACCESS]  fill_access() trả dict không rỗng?
□ [ACCESS]  acCmdSaveRecord không exception?
□ [ACCESS]  Query COUNT(*) bảng HoaDon > 0 sau khi lưu?
□ [ALL]     audit.log ghi nhận OK cho bản ghi này?
```

---

*Báo cáo dựa trên phân tích tĩnh source code tại commit `d4db5af` (2026-06-25).*  
*Để kiểm tra động, cần chạy thực tế với chứng từ mẫu và bật `debug=True` trong `fill_and_submit_browser`.*
