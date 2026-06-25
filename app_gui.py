# -*- coding: utf-8 -*-
"""
GIAO DIỆN bấm-nút cho RPA hoá đơn (Tkinter — không cần cài thêm).
Chọn file chứng từ → chọn tab đích → Xem trước / Điền & Nộp.

Chạy:  py -3.11 app_gui.py
"""
import _bootstrap  # .env, temp->D:, sys.path
import os
import queue as _queue
import sys
import threading
import types
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

import autofill

HERE = os.path.dirname(os.path.abspath(__file__))


def build_args(target, doc, extra, submit, headed, watch=True) -> types.SimpleNamespace:
    a = types.SimpleNamespace(
        doc=doc, submit=submit, headed=headed,
        form=None, refresh=False, cua=False,
        excel=None, sheet=None, header_row=1, watch=watch,
        access=False,
    )
    if target == "form":
        a.form = extra or None
    elif target == "excel":
        a.excel = extra or os.path.join(HERE, "data", "bao_cao.xlsx")
    elif target == "access":
        a.access = True
    return a


def dispatch(a) -> int:
    if a.access and getattr(a, "excel", None):
        return autofill.run_invoice(a)   # cả hai đích → OCR 1 lần
    if a.access:
        return autofill.run_access(a)
    if a.excel:
        return autofill.run_excel(a)
    return autofill.run_form(a)


class TkWriter:
    """Chuyển print() của engine vào ô log (an toàn từ thread khác)."""
    def __init__(self, widget):
        self.w = widget

    def write(self, s):
        self.w.after(0, self._ins, s)

    def _ins(self, s):
        self.w.configure(state="normal")
        self.w.insert("end", s)
        self.w.see("end")
        self.w.configure(state="disabled")

    def flush(self):
        pass


class ReviewDialog:
    """Bảng tham chiếu thủ công — hiện khi OCR thiếu trường bắt buộc.

    Worker thread block tại review_fn(); main thread hiện dialog này;
    sau khi user xác nhận / bỏ qua, done_event được set để unblock worker.
    """

    def __init__(self, master, doc_name: str, items: list, issues: list,
                 result_queue: "_queue.Queue", done_event: "threading.Event"):
        self._rq = result_queue
        self._ev = done_event
        self._items = items
        self._vars: "dict[str, tk.StringVar]" = {}

        top = tk.Toplevel(master)
        self._top = top
        top.title(f"Xem xét thủ công — {doc_name}")
        top.geometry("700x480")
        top.grab_set()          # modal: khoá cửa sổ chính khi dialog mở
        top.resizable(True, True)

        # Nhãn lỗi từ issues (so sánh với item label)
        issue_labels: "set[str]" = {iss.split(":")[0].strip() for iss in issues}

        # ── Tiêu đề ──────────────────────────────────────────────────
        ttk.Label(top,
                  text=f"⚠️  {len(issues)} trường cần bổ sung — điền vào ô trống rồi bấm Xác nhận",
                  foreground="#c0392b",
                  font=("Segoe UI", 10, "bold")).pack(padx=14, pady=(10, 2), anchor="w")
        ttk.Label(top,
                  text="Trường có * là bắt buộc  •  ⛔ = lỗi cần sửa  •  ✓ = trích xuất OK",
                  foreground="#555").pack(padx=14, pady=(0, 6), anchor="w")

        # ── Bảng cuộn ─────────────────────────────────────────────────
        outer = ttk.Frame(top)
        outer.pack(fill="both", expand=True, padx=14, pady=0)

        canvas = tk.Canvas(outer, highlightthickness=0, background="#fafafa")
        sb = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        inner = ttk.Frame(canvas)
        _win = canvas.create_window((0, 0), window=inner, anchor="nw")

        canvas.bind("<Configure>", lambda e: canvas.itemconfig(_win, width=e.width))
        inner.bind("<Configure>",  lambda e: canvas.configure(
            scrollregion=canvas.bbox("all")))
        _mw_id = canvas.bind_all("<MouseWheel>",
                                  lambda e: canvas.yview_scroll(-1 * (e.delta // 120), "units"))

        # ── Header hàng ──────────────────────────────────────────────
        _HDR = [("Trường", 24), ("Giá trị trích xuất", 0), ("", 4)]
        for c, (txt, w) in enumerate(_HDR):
            kw = {"width": w} if w else {}
            ttk.Label(inner, text=txt, font=("Segoe UI", 9, "bold"),
                      background="#dde3f0", anchor="w",
                      **kw).grid(row=0, column=c, padx=2, pady=2, sticky="ew")

        first_empty_entry = None
        for r, item in enumerate(items, 1):
            lbl   = item["label"]
            req   = item.get("required", False)
            err   = lbl in issue_labels
            color = "#c0392b" if err else "#1a1a1a"

            # Cột 0 — nhãn trường
            ttk.Label(inner, text=lbl + (" *" if req else ""),
                      foreground=color, anchor="w",
                      width=24).grid(row=r, column=0, padx=(4, 2), pady=2, sticky="w")

            # Cột 1 — Entry (lỗi) hoặc Label (OK)
            var = tk.StringVar(value="" if item["value"] is None else str(item["value"]))
            self._vars[item["id"]] = var
            if err:
                ent = ttk.Entry(inner, textvariable=var)
                ent.grid(row=r, column=1, padx=2, pady=2, sticky="ew")
                if first_empty_entry is None and not var.get():
                    first_empty_entry = ent
            else:
                ttk.Label(inner, textvariable=var,
                          background="#f4f4f4", anchor="w",
                          relief="flat").grid(row=r, column=1, padx=2, pady=2, sticky="ew")

            # Cột 2 — trạng thái
            st, fg = ("⛔", "#c0392b") if err else ("✓", "#27ae60")
            ttk.Label(inner, text=st, foreground=fg,
                      anchor="center").grid(row=r, column=2, padx=4, pady=2)

        inner.columnconfigure(1, weight=1)

        # Focus ô lỗi đầu tiên còn trống
        if first_empty_entry:
            top.after(150, first_empty_entry.focus_set)

        # ── Nút ──────────────────────────────────────────────────────
        bf = ttk.Frame(top)
        bf.pack(fill="x", padx=14, pady=10)
        ttk.Button(bf, text="Xác nhận & Tiếp tục",
                   command=self._confirm).pack(side="left", expand=True, fill="x", padx=(0, 6))
        ttk.Button(bf, text="Bỏ qua bản ghi này",
                   command=self._skip).pack(side="left", expand=True, fill="x")

        top.protocol("WM_DELETE_WINDOW", self._skip)
        top.bind("<Destroy>", lambda _: canvas.unbind_all("<MouseWheel>"))

    def _confirm(self):
        new_items = []
        for item in self._items:
            raw = self._vars[item["id"]].get().strip()
            new_items.append({**item, "value": raw if raw else None})
        self._rq.put(new_items)
        self._top.destroy()
        self._ev.set()

    def _skip(self):
        self._rq.put(None)
        self._top.destroy()
        self._ev.set()


class App:
    def __init__(self, root):
        self.root = root
        root.title("RPA hoá đơn")
        root.geometry("560x520")
        root.attributes("-topmost", True)
        pad = {"padx": 10, "pady": 6}

        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TNotebook.Tab", padding=[14, 6], background="#d0d0d0", foreground="#333")
        style.map("TNotebook.Tab",
                  background=[("selected", "#1a6fc4")],
                  foreground=[("selected", "white")])

        # ── 1) Chọn chứng từ ────────────────────────────────────────────
        self.docs = []
        self._set_display = False
        f1 = ttk.Frame(root); f1.pack(fill="x", **pad)
        ttk.Label(f1, text="Chứng từ (ảnh/PDF/Excel/CSV/Word — chọn nhiều):").pack(side="left")
        self.doc_var = tk.StringVar()
        self.doc_var.trace_add("write", self._on_doc_edit)
        ttk.Entry(f1, textvariable=self.doc_var).pack(side="left", fill="x", expand=True, padx=6)
        ttk.Button(f1, text="Chọn…", command=self.pick_doc).pack(side="left")

        # ── 2) Tab đích ─────────────────────────────────────────────────
        self.nb = ttk.Notebook(root)
        self.nb.pack(fill="x", **pad)

        # Tab 0 — Hồ sơ bệnh nhân / Gform
        t0 = ttk.Frame(self.nb, padding=(8, 8, 8, 10))
        self.nb.add(t0, text="  Hồ sơ bệnh nhân — Gform  ")
        ttk.Label(t0, text="Form URL (bỏ trống = dùng form cũ):").pack(anchor="w")
        self.form_url = tk.StringVar()
        ttk.Entry(t0, textvariable=self.form_url).pack(fill="x", pady=(3, 0))

        # Tab 1 — Hóa đơn (Excel & Access)
        t1 = ttk.Frame(self.nb, padding=(8, 8, 8, 10))
        self.nb.add(t1, text="  Hóa đơn (Excel & Access)  ")

        row_xl = ttk.Frame(t1); row_xl.pack(fill="x", pady=(0, 4))
        self.use_excel = tk.BooleanVar(value=True)
        ttk.Checkbutton(row_xl, text="Ghi vào Excel:", variable=self.use_excel).pack(side="left")
        self.excel_path = tk.StringVar(value=os.path.join(HERE, "data", "bao_cao.xlsx"))
        ttk.Entry(row_xl, textvariable=self.excel_path).pack(
            side="left", fill="x", expand=True, padx=4)
        ttk.Button(row_xl, text="…", width=3, command=self._pick_excel).pack(side="left")

        self.use_access = tk.BooleanVar(value=True)
        ttk.Checkbutton(t1, text="Ghi vào Access (CSDL mặc định)",
                        variable=self.use_access).pack(anchor="w")

        # Trạng thái ẩn — mặc định True, không hiện lên GUI
        self.headed = tk.BooleanVar(value=True)  # luôn hiện trình duyệt Form
        self.watch  = tk.BooleanVar(value=True)  # luôn mở Excel/Access xem điền

        # ── 3) Nút hành động ────────────────────────────────────────────
        f4 = ttk.Frame(root); f4.pack(fill="x", **pad)
        self.btn_prev = ttk.Button(f4, text="Xem trước nội dung",
                                   command=lambda: self.run(False))
        self.btn_prev.pack(side="left", expand=True, fill="x", padx=4)
        self.btn_go = ttk.Button(f4, text="Điền & Nộp ▶",
                                 command=lambda: self.run(True))
        self.btn_go.pack(side="left", expand=True, fill="x", padx=4)

        # ── 4) Log ──────────────────────────────────────────────────────
        self.log = tk.Text(root, height=16, state="disabled", wrap="word",
                           font=("Consolas", 9))
        self.log.pack(fill="both", expand=True, **pad)

    # ── file picker ─────────────────────────────────────────────────────
    def pick_doc(self):
        ps = filedialog.askopenfilenames(
            title="Chọn chứng từ (giữ Ctrl/Shift để chọn nhiều)",
            filetypes=[
                ("Chứng từ", "*.pdf *.jpg *.jpeg *.png *.bmp *.webp *.tif *.tiff "
                             "*.xlsx *.xlsm *.xls *.csv *.tsv *.docx *.doc *.txt *.md *.json"),
                ("Ảnh/PDF",  "*.pdf *.jpg *.jpeg *.png"),
                ("Dữ liệu",  "*.xlsx *.xlsm *.xls *.csv *.tsv *.docx *.doc"),
                ("Tất cả",   "*.*")])
        if not ps:
            return
        self.docs = list(ps)
        self._set_display = True
        if len(self.docs) == 1:
            self.doc_var.set(self.docs[0])
        else:
            names = ", ".join(os.path.basename(p) for p in self.docs)
            self.doc_var.set(f"{len(self.docs)} file: {names}")
        self._set_display = False

    def _pick_excel(self):
        p = filedialog.askopenfilename(
            title="Chọn file Excel báo cáo",
            filetypes=[("Excel", "*.xlsx *.xlsm"), ("Tất cả", "*.*")])
        if p:
            self.excel_path.set(p)

    def _on_doc_edit(self, *_):
        if not self._set_display:
            self.docs = []

    def _resolve_docs(self):
        if self.docs:
            return list(self.docs)
        p = self.doc_var.get().strip()
        return [p] if p else []

    # ── chạy ────────────────────────────────────────────────────────────
    def run(self, submit):
        docs = self._resolve_docs()
        bad  = [d for d in docs if not os.path.exists(d)]
        if not docs or bad:
            msg = "Hãy chọn file chứng từ hợp lệ." if not docs \
                else "Không tìm thấy file:\n" + "\n".join(bad)
            messagebox.showwarning("Thiếu file", msg)
            return

        tab = self.nb.index("current")  # 0 = Gform, 1 = Hóa đơn

        if tab == 1 and not self.use_excel.get() and not self.use_access.get():
            messagebox.showwarning("Chưa chọn đích",
                                   "Hãy tích chọn ít nhất Excel hoặc Access.")
            return

        if submit and not messagebox.askyesno(
                "Xác nhận",
                f"ĐIỀN & NỘP thật {len(docs)} chứng từ?\n(Xem trước thì bấm Hủy.)"):
            return

        # đóng gói params — đọc widget ở luồng chính trước khi spawn thread
        if tab == 0:
            params = ("form",
                      self.form_url.get().strip(),
                      submit, self.headed.get(), self.watch.get())
        else:
            params = ("invoice",
                      {"excel":  (self.use_excel.get(),  self.excel_path.get().strip()),
                       "access": self.use_access.get()},
                      submit, self.headed.get(), self.watch.get())

        self.btn_prev.configure(state="disabled")
        self.btn_go.configure(state="disabled")
        self.log.configure(state="normal"); self.log.delete("1.0", "end")
        self.log.configure(state="disabled")
        threading.Thread(target=self._worker, args=(docs, params), daemon=True).start()

    def _worker(self, docs, params):
        target, extra, submit, headed, watch = params
        old = sys.stdout
        sys.stdout = TkWriter(self.log)
        codes = []
        try:
            for i, doc in enumerate(docs, 1):
                print(f"\n{'='*48}\n[{i}/{len(docs)}] {os.path.basename(doc)}\n{'='*48}")

                review_fn = self._make_review_fn(os.path.basename(doc))
                if target == "invoice":
                    use_xl, xl_path = extra["excel"]
                    use_ac = extra["access"]
                    try:
                        if use_xl and use_ac:
                            a = build_args("excel", doc, xl_path, submit, headed, watch)
                            a.access = True
                            a.review_fn = review_fn
                            rc = dispatch(a)
                        elif use_xl:
                            a = build_args("excel", doc, xl_path, submit, headed, watch)
                            a.review_fn = review_fn
                            rc = dispatch(a)
                        elif use_ac:
                            a = build_args("access", doc, "", submit, headed, watch)
                            a.review_fn = review_fn
                            rc = dispatch(a)
                        else:
                            rc = 0
                    except Exception as e:
                        import traceback
                        print("\n⛔ LỖI:", e, "\n", traceback.format_exc())
                        rc = 1
                else:
                    a = build_args(target, doc, extra, submit, headed, watch)
                    a.review_fn = review_fn
                    try:
                        rc = dispatch(a)
                    except Exception as e:
                        import traceback
                        print("\n⛔ LỖI:", e, "\n", traceback.format_exc())
                        rc = 1

                codes.append(rc)
                print(f"--- xong [{i}/{len(docs)}] (mã {rc}) ---")

            ok = sum(1 for c in codes if c == 0)
            print(f"\n=== TỔNG KẾT: {ok}/{len(docs)} thành công "
                  f"(mã != 0: {[c for c in codes if c != 0] or 'không'}) ===")
        finally:
            sys.stdout = old
            self.root.after(0, self._done)

    def _done(self):
        self.btn_prev.configure(state="normal")
        self.btn_go.configure(state="normal")

    def _make_review_fn(self, doc_name: str):
        """Trả về callback truyền vào args.review_fn.

        Được gọi từ worker thread khi có issues → block worker, hiện
        ReviewDialog trên main thread, rồi trả lại items đã sửa (hoặc None).
        """
        q  = _queue.Queue()
        ev = threading.Event()

        def _callback(items, issues):
            self.root.after(0, lambda: ReviewDialog(
                self.root, doc_name, items, issues, q, ev))
            ev.wait()   # block worker thread cho đến khi user xác nhận/bỏ qua
            ev.clear()
            return q.get()  # None = bỏ qua; list = items đã chỉnh

        return _callback


if __name__ == "__main__":
    root = tk.Tk()
    App(root)
    root.mainloop()
