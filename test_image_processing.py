"""
Image Processing Pipeline
Dự án: AI Grading Assistant — chấm bài viết tay

Gồm các mode:
  - test_pipeline()        : xem ảnh từng bước qua cv2.imshow + gửi OCR
  - process_image()        : xử lý + encode base64 để gửi Vision API
  - ocr_multiple_images()  : batch OCR nhiều file ảnh

Providers được hỗ trợ (đổi qua .env):
  OCR_PROVIDER=gemini   → Gemini 1.5/2.0 Flash / Pro  (mặc định)
  OCR_PROVIDER=openai   → GPT-4o / GPT-4o-mini
  OCR_PROVIDER=claude   → Claude 3.5 Sonnet / Haiku
  OCR_PROVIDER=ollama   → LLaVA / llama3.2-vision (local, miễn phí)

API keys (chỉ cần key của provider đang dùng):
  GEMINI_API_KEY=...
  OPENAI_API_KEY=...
  ANTHROPIC_API_KEY=...
  OLLAMA_BASE_URL=http://localhost:11434   (optional, default là localhost)

Model cụ thể (optional — đã có default tốt):
  MODEL_GEMINI=flashlite      # flashlite | flash | pro
  MODEL_OPENAI=gpt-4o-mini    # gpt-4o | gpt-4o-mini
  MODEL_CLAUDE=haiku          # haiku | sonnet
  MODEL_OLLAMA=llava          # llava | llama3.2-vision
"""

import cv2
import math
import time
import hashlib
import json
import base64
import os
import sys
import urllib.request
import urllib.error
import numpy as np
from abc import ABC, abstractmethod
from PIL import Image, ImageEnhance
from dotenv import load_dotenv

load_dotenv(override=True)


# ============================================================
# CONSTANTS
# ============================================================

BLUR_THRESHOLD         = 100
BRIGHTNESS_TOO_DARK    = 50
BRIGHTNESS_TOO_BRIGHT  = 220
BRIGHTNESS_DARK_EDGE   = 80
BRIGHTNESS_BRIGHT_EDGE = 180
MIN_WIDTH              = 800
MIN_HEIGHT             = 600
QUALITY_PASS_SCORE     = 40
QUALITY_HIGH_CONF      = 60
MAX_API_RETRIES        = 3
MAX_RETRY_WAIT         = 10
CACHE_TTL              = 3600
TILE_SIZE              = 768
TOKENS_PER_TILE        = 258
RESIZE_MAX             = 1536
JPEG_QUALITY           = 90
MAX_OUTPUT_TOKENS      = 8192
USD_TO_VND             = 25_000

RETRYABLE_HTTP_CODES = {429, 500, 503}


# ============================================================
# CACHE
# ============================================================

_ocr_cache: dict[str, tuple[float, dict]] = {}


def _get_cache(key: str) -> "dict | None":
    if key not in _ocr_cache:
        return None
    ts, data = _ocr_cache[key]
    if time.time() - ts < CACHE_TTL:
        return data
    del _ocr_cache[key]
    return None


def _set_cache(key: str, result: dict) -> None:
    _ocr_cache[key] = (time.time(), result)


# ============================================================
# BƯỚC 1: LOAD ẢNH
# ============================================================

def load_image(image_path: str) -> np.ndarray:
    img = cv2.imread(image_path)
    if img is None:
        raise ValueError(f"Không đọc được ảnh: {image_path}")
    print(f"✅ Load ảnh thành công: {img.shape[1]}x{img.shape[0]}px")
    return img


# ============================================================
# BƯỚC 2: QUALITY CHECK
# ============================================================

def check_image_quality(img: np.ndarray) -> dict:
    gray       = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if len(img.shape) == 3 else img
    brightness = float(np.mean(gray))
    lap_var    = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    h, w       = gray.shape
    score      = 100
    warnings: list[str] = []

    if brightness < BRIGHTNESS_TOO_DARK:
        warnings.append("⚠️  Ảnh quá tối — cần chụp lại với ánh sáng tốt hơn")
        score -= 30
    elif brightness > BRIGHTNESS_TOO_BRIGHT:
        warnings.append("⚠️  Ảnh quá sáng — có thể mất chi tiết chữ")
        score -= 20

    if lap_var < BLUR_THRESHOLD:
        warnings.append("⚠️  Ảnh bị mờ — cần chụp lại rõ hơn")
        score -= 40

    if w < MIN_WIDTH or h < MIN_HEIGHT:
        warnings.append(f"⚠️  Độ phân giải thấp ({w}x{h}) — khó đọc chữ nhỏ")
        score -= 20

    score      = max(0, score)
    passed     = score >= QUALITY_PASS_SCORE
    confidence = "high" if score >= QUALITY_HIGH_CONF else "low"

    icon = "🟢" if confidence == "high" else "🟡"
    print(f"📊 Quality Score: {score}/100  {icon} {confidence.upper()}"
          f"  |  Brightness: {brightness:.0f}  |  Blur: {lap_var:.0f}")
    for msg in warnings:
        print(msg)
    if confidence == "low" and passed:
        print("   → Chất lượng thấp nhưng vẫn thử OCR; kết quả có thể kém.")

    return {
        "passed":     passed,
        "score":      score,
        "confidence": confidence,
        "brightness": brightness,
        "warnings":   warnings,
    }


# ============================================================
# BƯỚC 3: PERSPECTIVE CORRECTION
# ============================================================

def correct_perspective(img: np.ndarray) -> np.ndarray:
    gray    = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (7, 7), 0)
    edged   = cv2.Canny(blurred, 30, 100)

    contours, _ = cv2.findContours(edged, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    contours     = sorted(contours, key=cv2.contourArea, reverse=True)

    img_h, img_w = gray.shape
    min_doc_area = float(img_h * img_w) * 0.10
    doc_pts      = None

    for c in contours:
        if cv2.contourArea(c) < min_doc_area:
            continue
        peri   = cv2.arcLength(c, True)
        approx = cv2.approxPolyDP(c, 0.02 * peri, True)
        if len(approx) == 4 and cv2.isContourConvex(approx):
            doc_pts = approx.reshape(4, 2).astype(np.float32)
            break

    if doc_pts is None:
        for c in contours:
            if cv2.contourArea(c) < min_doc_area:
                continue
            rect   = cv2.minAreaRect(c)
            box    = cv2.boxPoints(rect).astype(np.float32)
            rw, rh = rect[1]
            if rw > 0 and rh > 0 and max(rw, rh) / min(rw, rh) < 3.0:
                doc_pts = box
                print("⚠️  Dùng fallback minAreaRect cho perspective")
                break

    if doc_pts is None:
        print("⚠️  Không detect được góc giấy — bỏ qua perspective transform")
        return img

    rect = _order_points(doc_pts)
    tl, tr, br, bl = rect

    max_w = int(max(np.linalg.norm(br - bl), np.linalg.norm(tr - tl)))
    max_h = int(max(np.linalg.norm(tr - br), np.linalg.norm(tl - bl)))

    if max_w < img_w * 0.30 or max_h < img_h * 0.30:
        print(f"⚠️  Contour không hợp lệ ({max_w}x{max_h}) — bỏ qua perspective transform")
        return img

    dst    = np.array([[0,0],[max_w-1,0],[max_w-1,max_h-1],[0,max_h-1]], dtype=np.float32)
    warped = cv2.warpPerspective(img, cv2.getPerspectiveTransform(rect, dst), (max_w, max_h))
    print(f"✅ Perspective correction: {img.shape[1]}x{img.shape[0]} → {max_w}x{max_h}")
    return warped


def _order_points(pts: np.ndarray) -> np.ndarray:
    rect = np.zeros((4, 2), dtype=np.float32)
    s    = pts.sum(axis=1)
    diff = np.diff(pts, axis=1)
    rect[0] = pts[np.argmin(s)]
    rect[2] = pts[np.argmax(s)]
    rect[1] = pts[np.argmin(diff)]
    rect[3] = pts[np.argmax(diff)]
    return rect


# ============================================================
# BƯỚC 4: ENHANCE
# ============================================================

def enhance_image(img: np.ndarray, brightness: float = -1.0) -> np.ndarray:
    if brightness < 0:
        brightness = float(np.mean(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)))

    if brightness < BRIGHTNESS_DARK_EDGE:
        contrast, sharpness = 2.0, 2.2
    elif brightness > BRIGHTNESS_BRIGHT_EDGE:
        contrast, sharpness = 1.2, 1.5
    else:
        contrast, sharpness = 1.6, 2.0

    pil = Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
    pil = ImageEnhance.Contrast(pil).enhance(contrast)
    pil = ImageEnhance.Sharpness(pil).enhance(sharpness)
    img = cv2.cvtColor(np.array(pil), cv2.COLOR_RGB2BGR)
    img = cv2.fastNlMeansDenoisingColored(img, None, 10, 10, 7, 21)
    print(f"✅ Enhance: contrast×{contrast}, sharpness×{sharpness}, denoise"
          f"  (brightness={brightness:.0f})")
    return img


# ============================================================
# BƯỚC 5: BINARIZATION (dự phòng — không dùng với LLM)
# ============================================================

def binarize_image(img: np.ndarray) -> np.ndarray:
    """Chỉ dùng cho traditional OCR (Tesseract). Không dùng với LLM."""
    gray   = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    binary = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                   cv2.THRESH_BINARY, 11, 2)
    binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, np.ones((2, 2), np.uint8))
    print("✅ Binarization hoàn tất")
    return binary


# ============================================================
# BƯỚC 6: RESIZE + ENCODE BASE64
# ============================================================

def prepare_for_api(img: np.ndarray,
                    max_size: int = RESIZE_MAX) -> "tuple[str, tuple[int,int]]":
    h, w = img.shape[:2]
    if max(h, w) > max_size:
        scale        = max_size / max(h, w)
        new_w, new_h = int(w * scale), int(h * scale)
        img          = cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_AREA)
        print(f"✅ Resize: {w}x{h} → {new_w}x{new_h}")
    else:
        new_w, new_h = w, h
        print(f"✅ Kích thước OK: {w}x{h}")

    if len(img.shape) == 2:
        img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)

    _, buf = cv2.imencode('.jpg', img, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
    b64    = base64.standard_b64encode(buf).decode('utf-8')
    print(f"✅ Encode base64: {len(b64)//1024} KB  ({new_w}×{new_h}px)")
    return b64, (new_w, new_h)


# ============================================================
# FULL PIPELINE
# ============================================================

def process_image(image_path: str) -> "tuple[str, dict, tuple[int,int]]":
    """
    Full pipeline: load → quality check → perspective → enhance → encode.

    Returns:
        b64     : ảnh đã xử lý, sẵn sàng gửi Vision API
        quality : dict (score, confidence, brightness, passed, warnings)
        size    : (width, height) thực tế sau resize
    """
    print(f"\n{'='*60}\n🔄 PROCESSING: {os.path.basename(image_path)}\n{'='*60}")

    img     = load_image(image_path)
    quality = check_image_quality(img)

    if not quality["passed"]:
        raise ValueError(
            f"Ảnh không đạt chất lượng (score={quality['score']}/100). "
            "Vui lòng chụp lại ảnh sáng hơn / rõ hơn."
        )

    img       = correct_perspective(img)
    img       = enhance_image(img, brightness=quality["brightness"])
    b64, size = prepare_for_api(img)
    print("✅ Pipeline hoàn tất!\n")
    return b64, quality, size


# ============================================================
# OCR PROMPTS
# ============================================================
# OCR_PROMPTS = {
#     "raw": """Đây là ảnh bài viết tay của học sinh trên giấy kẻ dòng.
 
# Hãy thực hiện OCR — nhận dạng và chép lại TOÀN BỘ CHỮ VIẾT TAY trong ảnh.
 
# Yêu cầu:
# - HOÀN TOÀN BỎ QUA các đường kẻ ngang của giấy — đó là đường in sẵn, KHÔNG phải chữ hay dấu chấm
# - Chỉ đọc phần chữ viết tay của học sinh, KHÔNG đọc đường kẻ
# - Giữ nguyên cấu trúc dòng / đoạn văn của bài viết
# - Giữ nguyên dấu câu, dấu tiếng Việt
# - Nếu chữ quá mờ / không đọc được → ghi [không rõ]
# - KHÔNG thêm nhận xét, KHÔNG sửa lỗi chính tả
# - Chỉ trả về nội dung OCR thuần túy, KHÔNG có markdown""",
 
#     "structured": """Đây là ảnh bài viết tay của học sinh trên giấy kẻ dòng.
 
# Thực hiện OCR và trả về JSON (không kèm markdown):
# {
#   "paragraphs": ["đoạn 1", "đoạn 2", ...],
#   "unclear_count": <số chỗ không rõ>,
#   "estimated_words": <số từ ước lượng>
# }
# Yêu cầu:
# - HOÀN TOÀN BỎ QUA các đường kẻ ngang của giấy (đường in sẵn, không phải chữ)
# - Chỉ đọc chữ viết tay
# - Giữ nguyên dấu câu, dấu tiếng Việt
# - KHÔNG sửa lỗi chính tả""",
# }
OCR_PROMPTS = {
    "raw": """Đây là ảnh một hóa đơn (có thể là hóa đơn GTGT/VAT, hóa đơn bán lẻ, hoặc phiếu thu).

Hãy thực hiện OCR — nhận dạng và chép lại TOÀN BỘ NỘI DUNG VĂN BẢN trong ảnh.

Yêu cầu:
- Giữ nguyên bố cục đọc từ trên xuống, trái sang phải
- Với phần bảng kê hàng hóa/dịch vụ: giữ nguyên cấu trúc cột (mặt hàng | đơn vị | số lượng | đơn giá | thành tiền), mỗi dòng hàng trên một dòng riêng
- Chép CHÍNH XÁC mọi con số: mã số thuế, số hóa đơn, ký hiệu, ngày tháng, số lượng, đơn giá, thành tiền, thuế suất, tiền thuế, tổng cộng — TUYỆT ĐỐI KHÔNG làm tròn, không suy đoán, không tự "sửa" cho hợp lý
- Giữ nguyên định dạng số gốc (dấu phân cách hàng nghìn, dấu thập phân) đúng như trong ảnh
- Giữ nguyên dấu tiếng Việt
- Nếu ký tự/con số quá mờ hoặc bị che (dấu mộc, chữ ký đè lên) → ghi [không rõ], KHÔNG đoán giá trị
- KHÔNG thêm nhận xét, KHÔNG sửa lỗi chính tả, KHÔNG diễn giải
- Chỉ trả về nội dung OCR thuần túy, KHÔNG có markdown""",

    "structured": """Đây là ảnh một hóa đơn (ưu tiên hóa đơn GTGT/VAT Việt Nam).

Thực hiện OCR và trích xuất thành JSON (CHỈ trả về JSON, không kèm markdown, không giải thích):
{
  "invoice_type": "<GTGT | ban_le | phieu_thu | khac>",
  "serial": "<ký hiệu hóa đơn, vd 1C24TAA>",
  "invoice_no": "<số hóa đơn>",
  "issue_date": "<ngày lập, định dạng YYYY-MM-DD nếu đọc được, nếu không thì để nguyên chuỗi gốc>",
  "seller": {
    "name": "<tên người bán>",
    "tax_code": "<MST người bán>",
    "address": "<địa chỉ>"
  },
  "buyer": {
    "name": "<tên người mua>",
    "tax_code": "<MST người mua, null nếu không có>",
    "address": "<địa chỉ, null nếu không có>"
  },
  "line_items": [
    {
      "description": "<tên hàng hóa/dịch vụ>",
      "unit": "<đơn vị tính, null nếu không có>",
      "quantity": <số lượng dạng number, null nếu không có>,
      "unit_price": <đơn giá dạng number, null nếu không có>,
      "amount": <thành tiền dạng number, null nếu không có>
    }
  ],
  "subtotal": <tiền hàng trước thuế, number>,
  "vat_rate": "<thuế suất, vd '8%', '10%', 'KCT', null nếu không có>",
  "vat_amount": <tiền thuế GTGT, number>,
  "total": <tổng tiền thanh toán, number>,
  "currency": "<VND | USD | ...>",
  "unclear_fields": ["<tên các trường đọc không rõ>"]
}

Yêu cầu:
- Mọi giá trị số trong JSON là KIỂU SỐ thuần (đã bỏ dấu phân cách hàng nghìn), KHÔNG để dạng chuỗi
- Chép chính xác con số gốc — KHÔNG làm tròn, KHÔNG tự tính lại, KHÔNG suy đoán
- KHÔNG tự ý "khớp" total = subtotal + vat_amount; điền đúng con số đọc được trên hóa đơn, kể cả khi cộng không khớp
- Trường nào không có hoặc không đọc được → để null và thêm tên trường đó vào "unclear_fields"
- Giữ nguyên dấu tiếng Việt trong các trường text
- KHÔNG sửa chính tả, KHÔNG bịa dữ liệu""",
}
DEFAULT_OCR_PROMPT = OCR_PROMPTS["raw"]


# ============================================================
# OCR ADAPTER — abstract base
# ============================================================

class OCRAdapter(ABC):
    """
    Interface chung cho mọi OCR provider.
    Mỗi provider implement _do_ocr() với API riêng của mình.
    """

    @abstractmethod
    def _do_ocr(self, images: list[str], prompt: str,
                image_sizes: "list[tuple[int,int]] | None") -> dict:
        """
        Gọi API thực tế. Trả về dict chuẩn:
          success, text, model, error, usage, images, image_sizes, cached
        """
        ...

    def ocr(self, images: "str | list[str]",
            prompt: str = DEFAULT_OCR_PROMPT,
            image_sizes: "list[tuple[int,int]] | None" = None) -> dict:
        """Entry point chung — xử lý cache trước khi gọi provider."""
        imgs = [images] if isinstance(images, str) else list(images)

        # Cache key độc lập với provider (bao gồm tên class)
        raw_key   = self.__class__.__name__ + "|".join(imgs) + prompt
        cache_key = hashlib.md5(raw_key.encode()).hexdigest()

        cached = _get_cache(cache_key)
        if cached is not None:
            result           = dict(cached)
            result["cached"] = True
            print("⚡ Cache hit — bỏ qua API call")
            return result

        result = self._do_ocr(imgs, prompt, image_sizes)
        result.setdefault("cached", False)
        result.setdefault("images", len(imgs))
        result.setdefault("image_sizes", image_sizes or [])

        if result.get("success"):
            _set_cache(cache_key, result)

        return result

    # ── helper dùng chung ──────────────────────────────────────

    @staticmethod
    def _http_post(url: str, payload: dict,
                   headers: "dict | None" = None,
                   max_retries: int = MAX_API_RETRIES) -> "tuple[dict | None, str, int]":
        """
        POST JSON với exponential backoff retry.

        429 được xử lý thông minh:
          - Nếu message chứa "quota" / "limit: 0"  → QUOTA_EXCEEDED, không retry
          - Nếu là rate-limit thông thường          → retry sau retryDelay (hoặc backoff)

        Returns: (data, error_msg, http_code).
          data=None nếu thất bại.
          http_code=0 nếu lỗi network.
          http_code=429 giúp caller phân biệt quota vs lỗi khác.
        """
        body = json.dumps(payload).encode("utf-8")
        hdrs = {"Content-Type": "application/json"}
        if headers:
            hdrs.update(headers)
        last_error = ""
        last_code  = 0

        for attempt in range(max_retries):
            if attempt > 0:
                wait = min(2 ** attempt, MAX_RETRY_WAIT)
                print(f"   ⏳ Retry {attempt}/{MAX_API_RETRIES-1} sau {wait}s...")
                time.sleep(wait)

            req = urllib.request.Request(url, data=body, headers=hdrs, method="POST")
            try:
                with urllib.request.urlopen(req, timeout=60) as resp:
                    return json.loads(resp.read().decode("utf-8")), "", 200

            except urllib.error.HTTPError as e:
                last_code = e.code
                err_body  = e.read().decode("utf-8", errors="replace")
                try:
                    err_obj = json.loads(err_body).get("error", {})
                    err_msg = err_obj.get("message", err_body) if isinstance(err_obj, dict) else err_body
                except Exception:
                    err_msg = err_body
                last_error = f"HTTP {e.code}: {err_msg}"

                if e.code == 429:
                    # Quota exceeded (limit: 0) → retry sẽ không giúp được gì
                    is_quota = "limit: 0" in err_msg or "quota" in err_msg.lower()
                    if is_quota:
                        print(f"   ⛔ Quota exceeded — không retry")
                        break

                    # Rate-limit thông thường → thử parse retryDelay từ response
                    retry_secs = None
                    try:
                        details = json.loads(err_body).get("error", {}).get("details", [])
                        for d in details:
                            if d.get("@type", "").endswith("RetryInfo"):
                                delay_str  = d.get("retryDelay", "")   # e.g. "22.954894387s"
                                retry_secs = float(delay_str.rstrip("s")) if delay_str else None
                    except Exception:
                        pass

                    wait = min(retry_secs or (2 ** (attempt + 1)), MAX_RETRY_WAIT)
                    print(f"   ⏳ Rate-limited — chờ {wait:.1f}s trước retry...")
                    time.sleep(wait)
                    continue   # không tính vào attempt thông thường

                if e.code not in RETRYABLE_HTTP_CODES:
                    break      # lỗi client 4xx khác → dừng ngay

            except Exception as e:
                last_error = str(e)
                continue

        return None, last_error, last_code

    @staticmethod
    def _err(msg: str, model: str = "", n_images: int = 0,
             image_sizes: "list | None" = None) -> dict:
        return {
            "success":     False,
            "text":        "",
            "model":       model,
            "error":       msg,
            "usage":       {},
            "images":      n_images,
            "image_sizes": image_sizes or [],
            "cached":      False,
        }


# ============================================================
# GEMINI ADAPTER
# ============================================================

GEMINI_MODELS = {
    "flash":     "gemini-2.5-flash",
    "flashlite": "gemini-2.5-flash-lite",   # quota free cao nhất -> fallback tốt khi 429
    "flash20":   "gemini-2.0-flash",
    "flash15":   "gemini-2.0-flash",         # alias cũ (1.5 đã bị Google gỡ -> 404)
    "pro":       "gemini-2.5-pro",
}
GEMINI_MODEL_FALLBACK: "list[str]" = []   # không thử model Gemini khác; cross-provider fallback qua ChainOCRAdapter
GEMINI_API_BASE       = "https://generativelanguage.googleapis.com/v1beta/models"


class GeminiOCRAdapter(OCRAdapter):
    """
    OCR qua Google Gemini Vision.
    Model mặc định: MODEL_GEMINI env var, hoặc flash15.
    """

    def __init__(self, api_key: str, model: "str | None" = None,
                 retries: int = MAX_API_RETRIES):
        self.api_key  = api_key.strip()
        self.model    = model or os.environ.get("MODEL_GEMINI", "flashlite")
        self.retries  = retries

    def _build_payload(self, images: list[str], prompt: str, n: int) -> dict:
        multi_note = (
            f"\n\nLưu ý: có {n} ảnh. Hãy OCR từng ảnh và đánh số [Ảnh 1], [Ảnh 2], ..."
            if n > 1 else ""
        )
        parts: list = [{"text": prompt + multi_note}]
        for idx, b64 in enumerate(images, 1):
            if n > 1:
                parts.append({"text": f"--- Ảnh {idx} ---"})
            parts.append({"inline_data": {"mime_type": "image/jpeg", "data": b64}})
        return {
            "contents":       [{"parts": parts}],
            "generationConfig": {"temperature": 0.1, "maxOutputTokens": MAX_OUTPUT_TOKENS},
        }

    def _do_ocr(self, images: list[str], prompt: str,
                image_sizes: "list[tuple[int,int]] | None") -> dict:
        n = len(images)

        # Danh sách model thử: chỉ định trước → fallback
        models_to_try = [self.model]
        for fb in GEMINI_MODEL_FALLBACK:
            if fb != self.model and fb not in models_to_try:
                models_to_try.append(fb)

        last_err  = ""
        quota_hit = False   # True khi account hết quota — skip mọi fallback

        for try_model in models_to_try:
            if quota_hit:
                break

            mn      = GEMINI_MODELS.get(try_model, try_model)
            url     = f"{GEMINI_API_BASE}/{mn}:generateContent?key={self.api_key}"
            payload = self._build_payload(images, prompt, n)

            if try_model != self.model:
                print(f"🔄 Fallback → {mn}")

            data, last_err, http_code = self._http_post(url, payload, max_retries=self.retries)

            # Quota exceeded → fallback model cùng account cũng vô ích
            if data is None and http_code == 429 and (
                "limit: 0" in last_err or "quota" in last_err.lower()
            ):
                quota_hit = True
                last_err += (
                    "\n\n💡 Gợi ý: Gemini free quota đã hết.\n"
                    "   → Đổi OCR_PROVIDER=ollama  (local, miễn phí)\n"
                    "   → Hoặc OCR_PROVIDER=mock   (demo không cần API)\n"
                    "   → Hoặc nâng lên paid Gemini key"
                )
                break

            if data is None:
                print(f"  ❌ {mn} lỗi HTTP {http_code}: {last_err[:120]}")
                continue

            try:
                candidates = data.get("candidates", [])
                if not candidates:
                    block    = data.get("promptFeedback", {}).get("blockReason", "UNKNOWN")
                    last_err = f"Bị block: {block}"
                    continue

                parts_out = candidates[0].get("content", {}).get("parts", [])
                ocr_text  = "".join(p.get("text", "") for p in parts_out).strip()
                finish    = candidates[0].get("finishReason", "")

                if finish not in ("STOP", "MAX_TOKENS", ""):
                    last_err = f"finishReason bất thường: {finish}"
                    continue

                usage = data.get("usageMetadata", {})
                return {
                    "success": True,
                    "text":    ocr_text,
                    "model":   mn,
                    "error":   "",
                    "usage": {
                        "prompt_tokens":   usage.get("promptTokenCount", 0),
                        "response_tokens": usage.get("candidatesTokenCount", 0),
                        "total_tokens":    usage.get("totalTokenCount", 0),
                    },
                    "images":      n,
                    "image_sizes": image_sizes or [],
                    "cached":      False,
                }
            except (KeyError, IndexError) as e:
                last_err = f"Parse lỗi: {e} | Raw: {str(data)[:300]}"
                continue

        return self._err(last_err, model=self.model, n_images=n, image_sizes=image_sizes)


# ============================================================
# OPENAI ADAPTER (GPT-4o / GPT-4o-mini)
# ============================================================

OPENAI_MODELS = {
    "gpt-4o":      "gpt-4o",
    "gpt-4o-mini": "gpt-4o-mini",
}
OPENAI_API_URL = "https://api.openai.com/v1/chat/completions"


class OpenAIOCRAdapter(OCRAdapter):
    """
    OCR qua OpenAI GPT-4o Vision.
    Model mặc định: MODEL_OPENAI env var, hoặc gpt-4o-mini (tiết kiệm hơn cho demo).
    """

    def __init__(self, api_key: str, model: "str | None" = None):
        self.api_key = api_key.strip()
        self.model   = model or os.environ.get("MODEL_OPENAI", "gpt-4o-mini")

    def _do_ocr(self, images: list[str], prompt: str,
                image_sizes: "list[tuple[int,int]] | None") -> dict:
        n            = len(images)
        model_name   = OPENAI_MODELS.get(self.model, self.model)

        # Build content: text prompt + image(s)
        content: list = [{"type": "text", "text": prompt}]
        if n > 1:
            content[0]["text"] += f"\n\nLưu ý: có {n} ảnh. OCR từng ảnh, đánh số [Ảnh 1], [Ảnh 2], ..."
        for idx, b64 in enumerate(images, 1):
            if n > 1:
                content.append({"type": "text", "text": f"--- Ảnh {idx} ---"})
            content.append({
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{b64}", "detail": "high"},
            })

        payload = {
            "model":      model_name,
            "messages":   [{"role": "user", "content": content}],
            "max_tokens": MAX_OUTPUT_TOKENS,
            "temperature": 0.1,
        }
        headers = {"Authorization": f"Bearer {self.api_key}"}

        data, err, _ = self._http_post(OPENAI_API_URL, payload, headers)
        if data is None:
            return self._err(err, model=model_name, n_images=n, image_sizes=image_sizes)

        try:
            ocr_text = data["choices"][0]["message"]["content"].strip()
            usage    = data.get("usage", {})
            return {
                "success": True,
                "text":    ocr_text,
                "model":   model_name,
                "error":   "",
                "usage": {
                    "prompt_tokens":   usage.get("prompt_tokens", 0),
                    "response_tokens": usage.get("completion_tokens", 0),
                    "total_tokens":    usage.get("total_tokens", 0),
                },
                "images":      n,
                "image_sizes": image_sizes or [],
                "cached":      False,
            }
        except (KeyError, IndexError) as e:
            return self._err(f"Parse lỗi: {e} | Raw: {str(data)[:300]}",
                             model=model_name, n_images=n, image_sizes=image_sizes)


# ============================================================
# CLAUDE ADAPTER (Anthropic)
# ============================================================

CLAUDE_MODELS = {
    "haiku":  "claude-haiku-4-5-20251001",
    "sonnet": "claude-sonnet-4-6",
}
ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"


class ClaudeOCRAdapter(OCRAdapter):
    """
    OCR qua Anthropic Claude Vision.
    Model mặc định: MODEL_CLAUDE env var, hoặc haiku (nhanh + rẻ cho demo).
    """

    def __init__(self, api_key: str, model: "str | None" = None):
        self.api_key = api_key.strip()
        self.model   = model or os.environ.get("MODEL_CLAUDE", "haiku")

    def _do_ocr(self, images: list[str], prompt: str,
                image_sizes: "list[tuple[int,int]] | None") -> dict:
        n          = len(images)
        model_name = CLAUDE_MODELS.get(self.model, self.model)

        content: list = []
        if n > 1:
            content.append({
                "type": "text",
                "text": f"Lưu ý: có {n} ảnh. OCR từng ảnh, đánh số [Ảnh 1], [Ảnh 2], ..."
            })
        for idx, b64 in enumerate(images, 1):
            if n > 1:
                content.append({"type": "text", "text": f"--- Ảnh {idx} ---"})
            content.append({
                "type": "image",
                "source": {"type": "base64", "media_type": "image/jpeg", "data": b64},
            })
        content.append({"type": "text", "text": prompt})

        payload = {
            "model":       model_name,
            "max_tokens":  MAX_OUTPUT_TOKENS,
            "temperature": 0.1,
            "messages":    [{"role": "user", "content": content}],
        }
        headers = {
            "x-api-key":         self.api_key,
            "anthropic-version": ANTHROPIC_VERSION,
        }

        data, err, _ = self._http_post(ANTHROPIC_API_URL, payload, headers)
        if data is None:
            return self._err(err, model=model_name, n_images=n, image_sizes=image_sizes)

        try:
            ocr_text = "".join(
                b.get("text", "") for b in data.get("content", [])
                if b.get("type") == "text"
            ).strip()
            usage = data.get("usage", {})
            return {
                "success": True,
                "text":    ocr_text,
                "model":   model_name,
                "error":   "",
                "usage": {
                    "prompt_tokens":   usage.get("input_tokens", 0),
                    "response_tokens": usage.get("output_tokens", 0),
                    "total_tokens":    usage.get("input_tokens", 0) + usage.get("output_tokens", 0),
                },
                "images":      n,
                "image_sizes": image_sizes or [],
                "cached":      False,
            }
        except (KeyError, IndexError) as e:
            return self._err(f"Parse lỗi: {e} | Raw: {str(data)[:300]}",
                             model=model_name, n_images=n, image_sizes=image_sizes)


# ============================================================
# OLLAMA ADAPTER (local — LLaVA / llama3.2-vision)
# ============================================================

OLLAMA_MODELS = {
    "llava":              "llava",
    "llama3.2-vision":    "llama3.2-vision",
    "llava-llama3":       "llava-llama3",
}


class OllamaOCRAdapter(OCRAdapter):
    """
    OCR qua Ollama local (không cần internet, miễn phí hoàn toàn).
    Yêu cầu: `ollama serve` đang chạy + đã pull model.

    Quick start:
        ollama pull llava
        ollama serve
    """

    def __init__(self, base_url: "str | None" = None, model: "str | None" = None):
        base = base_url or os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
        self.api_url = f"{base.rstrip('/')}/api/chat"
        self.model   = model or os.environ.get("MODEL_OLLAMA", "llava")

    def _do_ocr(self, images: list[str], prompt: str,
                image_sizes: "list[tuple[int,int]] | None") -> dict:
        n          = len(images)
        model_name = OLLAMA_MODELS.get(self.model, self.model)

        # Ollama: images là list base64, gắn vào message cuối cùng
        full_prompt = prompt
        if n > 1:
            full_prompt += f"\n\nLưu ý: có {n} ảnh. OCR từng ảnh, đánh số [Ảnh 1], [Ảnh 2], ..."

        payload = {
            "model":  model_name,
            "stream": False,
            "messages": [{
                "role":    "user",
                "content": full_prompt,
                "images":  images,        # Ollama nhận list base64 trực tiếp
            }],
            "options": {"temperature": 0.1},
        }

        data, err, _ = self._http_post(self.api_url, payload)
        if data is None:
            hint = " (Đã chạy 'ollama serve' chưa?)" if "Connection" in err else ""
            return self._err(err + hint, model=model_name, n_images=n, image_sizes=image_sizes)

        try:
            ocr_text = data["message"]["content"].strip()
            usage    = data.get("prompt_eval_count", 0)
            return {
                "success": True,
                "text":    ocr_text,
                "model":   f"ollama/{model_name}",
                "error":   "",
                "usage": {
                    "prompt_tokens":   data.get("prompt_eval_count", 0),
                    "response_tokens": data.get("eval_count", 0),
                    "total_tokens":    data.get("prompt_eval_count", 0) + data.get("eval_count", 0),
                },
                "images":      n,
                "image_sizes": image_sizes or [],
                "cached":      False,
            }
        except (KeyError, IndexError) as e:
            return self._err(f"Parse lỗi: {e} | Raw: {str(data)[:300]}",
                             model=model_name, n_images=n, image_sizes=image_sizes)


# ============================================================
# MOCK ADAPTER (testing — không cần API key)
# ============================================================

class MockOCRAdapter(OCRAdapter):
    def __init__(self, response: str = ""):
        self.response = response or "[MOCK] Đây là kết quả OCR giả lập.\nDòng 2: Học sinh viết bình thường."

    def _do_ocr(self, images: list[str], prompt: str,
                image_sizes: "list[tuple[int,int]] | None") -> dict:
        print("🧪 MockOCRAdapter — trả về response giả")
        return {
            "success":     True,
            "text":        self.response,
            "model":       "mock",
            "error":       "",
            "usage":       {"prompt_tokens": 0, "response_tokens": 0, "total_tokens": 0},
            "images":      len(images),
            "image_sizes": image_sizes or [],
            "cached":      False,
        }


# ============================================================
# GOOGLE CLOUD VISION ADAPTER (service account)
# ============================================================

def _load_google_vision_credentials_from_env():
    """
    Load Google Cloud Vision service account credentials from env.

    Supported env:
      - GOOGLE_VISION_CREDENTIALS_BASE64: base64-encoded service account JSON
      - (optional) GOOGLE_VISION_CREDENTIALS_JSON: raw JSON string (fallback)
    """
    b64 = os.environ.get("GOOGLE_VISION_CREDENTIALS_BASE64", "").strip()
    raw = os.environ.get("GOOGLE_VISION_CREDENTIALS_JSON", "").strip()

    if not b64 and not raw:
        raise ValueError(
            "Thiếu credential cho Google Vision. "
            "Set GOOGLE_VISION_CREDENTIALS_BASE64 (khuyến nghị) "
            "hoặc GOOGLE_VISION_CREDENTIALS_JSON."
        )

    if b64:
        # allow both standard and urlsafe base64; tolerate missing padding
        padded = b64 + "=" * (-len(b64) % 4)
        try:
            decoded = base64.b64decode(padded, validate=False)
        except Exception:
            decoded = base64.urlsafe_b64decode(padded)
        try:
            info = json.loads(decoded.decode("utf-8"))
        except Exception as e:
            raise ValueError(f"GOOGLE_VISION_CREDENTIALS_BASE64 không phải JSON hợp lệ: {e}") from e
    else:
        try:
            info = json.loads(raw)
        except Exception as e:
            raise ValueError(f"GOOGLE_VISION_CREDENTIALS_JSON không phải JSON hợp lệ: {e}") from e

    try:
        from google.oauth2 import service_account
        return service_account.Credentials.from_service_account_info(info)
    except Exception as e:
        raise ValueError(f"Không tạo được Google service account credentials: {e}") from e


class GoogleVisionOCRAdapter(OCRAdapter):
    """
    OCR qua Google Cloud Vision API (document_text_detection).

    Env:
      OCR_PROVIDER=gcv
      GOOGLE_VISION_CREDENTIALS_BASE64=...   (service account JSON, base64)
    """

    def __init__(self):
        creds = _load_google_vision_credentials_from_env()
        try:
            from google.cloud import vision
        except Exception as e:
            raise ValueError(
                "Chưa cài dependency cho Google Vision. "
                "Hãy `pip install google-cloud-vision`."
            ) from e
        self._vision = vision
        # self._client = vision.ImageAnnotatorClient(credentials=creds) #

    def _do_ocr(self, images: list[str], prompt: str,
                image_sizes: "list[tuple[int,int]] | None") -> dict:
        # prompt không dùng cho Vision API (traditional OCR), nhưng giữ signature cho thống nhất
        n = len(images)
        texts: list[str] = []
        last_err = ""

        for idx, b64 in enumerate(images, 1):
            try:
                content = base64.b64decode(b64)
                image = self._vision.Image(content=content)
                # Hint language for better Vietnamese handwriting OCR.
                # Vision API may still be weaker than LLM-Vision for handwriting,
                # but language hints can reduce diacritic/word-splitting errors.
                image_context = None
                try:
                    image_context = self._vision.ImageContext(language_hints=["vi"])
                except Exception:
                    image_context = None

                resp = (
                    self._client.document_text_detection(image=image, image_context=image_context)
                    if image_context is not None
                    else self._client.document_text_detection(image=image)
                )

                if resp.error and getattr(resp.error, "message", ""):
                    raise RuntimeError(resp.error.message)

                full_text = ""
                if resp.full_text_annotation and resp.full_text_annotation.text:
                    full_text = resp.full_text_annotation.text
                elif resp.text_annotations:
                    # fallback: first annotation contains the whole text for text_detection;
                    # for document_text_detection it may be empty, but keep safe
                    full_text = resp.text_annotations[0].description or ""

                if n > 1:
                    texts.append(f"[Ảnh {idx}]\n{full_text}".strip())
                else:
                    texts.append(full_text.strip())

            except Exception as e:
                last_err = f"Lỗi Google Vision (ảnh {idx}/{n}): {e}"
                return self._err(last_err, model="gcv/document_text_detection", n_images=n, image_sizes=image_sizes)

        return {
            "success": True,
            "text":    "\n\n".join(t for t in texts if t).strip(),
            "model":   "gcv/document_text_detection",
            "error":   "",
            "usage":   {},  # Vision API không trả token usage
            "images":  n,
            "image_sizes": image_sizes or [],
            "cached":  False,
        }


# ============================================================
# CHAIN ADAPTER — thử provider theo thứ tự, fallback khi thất bại
# ============================================================

class ChainOCRAdapter(OCRAdapter):
    """Thử adapter theo thứ tự; chuyển sang adapter tiếp khi thất bại hoàn toàn."""

    def __init__(self, *adapters: OCRAdapter):
        self.adapters = list(adapters)

    def _do_ocr(self, images: list, prompt: str,
                image_sizes: "list[tuple[int,int]] | None") -> dict:
        last: dict = {}
        for adapter in self.adapters:
            result = adapter._do_ocr(images, prompt, image_sizes)
            if result.get("success"):
                return result
            last = result
            name = adapter.__class__.__name__.replace("OCRAdapter", "")
            print(f"⚠️  {name} thất bại ({result.get('error', '')[:80]}) — thử provider tiếp theo...")
        return last or self._err("Tất cả provider thất bại", n_images=len(images),
                                 image_sizes=image_sizes)


# ============================================================
# FACTORY — tạo adapter từ .env
# ============================================================

def create_ocr_adapter() -> OCRAdapter:
    """
    Đọc OCR_PROVIDER từ .env và trả về adapter tương ứng.
    Không cần sửa code khi đổi provider — chỉ đổi .env.

    OCR_PROVIDER=gemini   → GeminiOCRAdapter   (cần GEMINI_API_KEY)
    OCR_PROVIDER=openai   → OpenAIOCRAdapter   (cần OPENAI_API_KEY)
    OCR_PROVIDER=claude   → ClaudeOCRAdapter   (cần ANTHROPIC_API_KEY)
    OCR_PROVIDER=ollama   → OllamaOCRAdapter   (local, không cần key)
    OCR_PROVIDER=gcv      → GoogleVisionOCRAdapter (cần GOOGLE_VISION_CREDENTIALS_BASE64)
    OCR_PROVIDER=mock     → MockOCRAdapter      (testing)
    """
    provider = os.environ.get("OCR_PROVIDER", "gemini").lower().strip()
    print(f"🔌 OCR Provider: {provider.upper()}")

    if provider == "gemini":
        key = os.environ.get("GEMINI_API_KEY", "")
        if not key:
            raise ValueError("Thiếu GEMINI_API_KEY trong .env")
        openai_key = os.environ.get("OPENAI_API_KEY", "")
        if openai_key:
            print("   ↩️  Fallback provider: OpenAI GPT-4o-mini")
            gemini = GeminiOCRAdapter(api_key=key, retries=1)   # fail nhanh, OpenAI lo fallback
            return ChainOCRAdapter(gemini, OpenAIOCRAdapter(api_key=openai_key, model="gpt-4o-mini"))
        return GeminiOCRAdapter(api_key=key)

    elif provider == "openai":
        key = os.environ.get("OPENAI_API_KEY", "")
        if not key:
            raise ValueError("Thiếu OPENAI_API_KEY trong .env")
        return OpenAIOCRAdapter(api_key=key)

    elif provider == "claude":
        key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not key:
            raise ValueError("Thiếu ANTHROPIC_API_KEY trong .env")
        return ClaudeOCRAdapter(api_key=key)

    elif provider == "ollama":
        return OllamaOCRAdapter()  # không cần key

    elif provider in ("gcv", "google_vision", "google-vision", "googlevision"):
        return GoogleVisionOCRAdapter()

    elif provider == "mock":
        return MockOCRAdapter()

    else:
        raise ValueError(
            f"OCR_PROVIDER không hợp lệ: '{provider}'. "
            "Chọn một trong: gemini | openai | claude | ollama | gcv | mock"
        )


# ============================================================
# TOKEN UTILITIES
# ============================================================

def calculate_image_tokens(width: int, height: int) -> int:
    """
    Công thức Gemini (dùng làm ước lượng chung):
      ≤ 384×384px → 258 tokens  |  lớn hơn → ceil(w/768) × ceil(h/768) × 258
    """
    if width <= 384 and height <= 384:
        return TOKENS_PER_TILE
    return math.ceil(width / TILE_SIZE) * math.ceil(height / TILE_SIZE) * TOKENS_PER_TILE


def estimate_cost(usage: dict, model: str = "flash") -> float:
    """
    Tính cost paid tier (tham khảo).
    Flash/Haiku/Mini: ~$0.075/$0.30 per 1M.  Pro/Sonnet/4o: ~$1.25/$5.00 per 1M.
    """
    inp, out = usage.get("prompt_tokens", 0), usage.get("response_tokens", 0)
    is_large = any(k in model for k in ("pro", "sonnet", "gpt-4o", "opus"))
    p_in, p_out = (1.25, 5.00) if is_large else (0.075, 0.30)
    return (inp * p_in + out * p_out) / 1_000_000


def _ocr_confidence_score(result: dict) -> dict:
    """Thêm ocr_confidence (0.0–1.0) và unclear_count vào result."""
    text    = result.get("text", "")
    unclear = text.count("[không rõ]")
    words   = len(text.split()) if text else 0

    if words == 0:
        score = 0.0
    else:
        # FIX: penalty ngắn chỉ áp dụng khi unclear > 0 để tránh phạt oan
        unclear_penalty = (unclear / max(words, 1)) * 5
        short_penalty   = 0.2 if (words < 20 and unclear > 0) else 0.0
        score = max(0.0, 1.0 - unclear_penalty - short_penalty)

    result["ocr_confidence"] = round(score, 2)
    result["unclear_count"]  = unclear
    return result


# ============================================================
# PRINT RESULT
# ============================================================

def _print_ocr_result(result: dict) -> None:
    n_images  = result.get("images", 1)
    img_sizes = result.get("image_sizes", [])
    cached    = result.get("cached", False)
    label     = f"{n_images} ảnh" + (" ⚡ CACHED" if cached else "")

    print(f"\n{'='*60}")
    print(f"🤖 OCR — model: {result.get('model','?')}  |  {label}")
    print('='*60)

    if not result["success"]:
        print(f"❌ OCR thất bại: {result['error']}")
        if result.get("text"):
            print(f"   (partial: {result['text'][:200]})")
        return

    usage = result.get("usage", {})
    if usage and not cached:
        inp   = usage.get("prompt_tokens",   0)
        out   = usage.get("response_tokens", 0)
        total = usage.get("total_tokens",    0)

        model_str = result.get("model", "")
        est_img   = sum(calculate_image_tokens(w, h) for w, h in img_sizes) if img_sizes else None
        est_text  = max(0, inp - est_img) if est_img is not None else "?"
        size_str  = ", ".join(f"{w}×{h}" for w, h in img_sizes) if img_sizes else "?"

        cost_usd = estimate_cost(usage, model_str)
        print(f"📊 Tokens: in={inp}  out={out}  total={total}")
        if est_img is not None:
            print(f"   ├─ Ước lượng text: {est_text}  |  Ảnh: {est_img} ({size_str})")
        print(f"💰 Ước tính: ${cost_usd:.6f}  ≈  {cost_usd * USD_TO_VND:.2f} VNĐ")
        print(f"   (Free tier: không tính tiền)")

    result = _ocr_confidence_score(result)
    icon   = "🟢" if result["ocr_confidence"] >= 0.8 else ("🟡" if result["ocr_confidence"] >= 0.5 else "🔴")
    print(f"\n📝 Kết quả OCR:\n{'-'*40}")
    print(result["text"])
    print('-'*40)
    print(f"✅ {len(result['text'])} ký tự  |  {icon} confidence: {result['ocr_confidence']:.0%}"
          f"  |  [không rõ]: {result['unclear_count']} chỗ")


# ============================================================
# BATCH OCR
# ============================================================

def ocr_multiple_images(
    image_paths: "list[str]",
    adapter: "OCRAdapter | None" = None,
    prompt: str = DEFAULT_OCR_PROMPT,
    batch_size: int = 4,
    save_results: bool = True,         # FIX: caller quyết định có ghi file không
) -> "list[dict]":
    """
    Xử lý pipeline + OCR nhiều file ảnh, tự động chia batch.
    Mỗi batch = 1 request duy nhất.

    adapter: nếu None → tạo từ .env qua create_ocr_adapter()
    save_results: True → tự động ghi .txt; False → chỉ trả về kết quả
    """
    if not image_paths:
        return []

    ocr = adapter or create_ocr_adapter()

    print(f"\n{'='*60}")
    print(f"📚 BATCH OCR: {len(image_paths)} ảnh  |  batch_size={batch_size}")
    print('='*60)

    b64_list:    list[str]            = []
    size_list:   list[tuple[int,int]] = []
    valid_paths: list[str]            = []

    for path in image_paths:
        try:
            b64, _q, size = process_image(path)
            b64_list.append(b64)
            size_list.append(size)
            valid_paths.append(path)
        except Exception as e:
            print(f"⚠️  Bỏ qua {os.path.basename(path)}: {e}")

    if not b64_list:
        print("❌ Không có ảnh hợp lệ.")
        return []

    results: list[dict] = []
    total_batches = math.ceil(len(b64_list) / batch_size)

    for i in range(0, len(b64_list), batch_size):
        sl        = slice(i, i + batch_size)
        batch_num = i // batch_size + 1
        bpaths    = valid_paths[sl]

        print(f"\n⏳ Batch {batch_num}/{total_batches} "
              f"({len(b64_list[sl])} ảnh: {[os.path.basename(p) for p in bpaths]})...")

        result = ocr.ocr(b64_list[sl], prompt=prompt, image_sizes=size_list[sl])
        result["batch"] = batch_num
        result["paths"] = bpaths
        _print_ocr_result(result)

        # FIX: ghi file chỉ khi caller opt-in
        if save_results and result["success"] and result["text"]:
            suffix   = f"_batch{batch_num}" if total_batches > 1 else ""
            out_path = os.path.splitext(bpaths[0])[0] + f"{suffix}_ocr.txt"
            with open(out_path, "w", encoding="utf-8") as f:
                f.write(result["text"])
            print(f"💾 Lưu: {out_path}")

        results.append(result)

    ok = sum(1 for r in results if r["success"])
    print(f"\n✅ Hoàn tất: {ok}/{len(results)} batch thành công.")
    return results


# ============================================================
# TEST PIPELINE
# ============================================================

def _display_comparison(img_l: np.ndarray, img_r: np.ndarray,
                         title: str, max_h: int = 500) -> None:
    def bgr(x: np.ndarray) -> np.ndarray:
        return cv2.cvtColor(x, cv2.COLOR_GRAY2BGR) if len(x.shape) == 2 else x.copy()
    L = cv2.resize(bgr(img_l), (int(img_l.shape[1] * max_h / img_l.shape[0]), max_h))
    R = cv2.resize(bgr(img_r), (int(img_r.shape[1] * max_h / img_r.shape[0]), max_h))
    cv2.putText(L, "TRUOC", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 120, 255), 2)
    cv2.putText(R, "SAU",   (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 180, 0),   2)
    cv2.imshow(title, np.hstack([L, np.ones((max_h, 4, 3), np.uint8) * 180, R]))


def test_pipeline(image_path: "str | list[str]",
                  adapter: "OCRAdapter | None" = None) -> None:
    """
    Test pipeline với hiển thị từng bước (cv2.imshow).
    adapter: nếu None → tạo từ .env qua create_ocr_adapter()
    Nhấn phím bất kỳ để qua bước, ESC để thoát.
    """
    paths = [image_path] if isinstance(image_path, str) else list(image_path)
    for p in paths:
        if not os.path.exists(p):
            print(f"❌ File không tìm thấy: {p}")
            return

    print(f"\n{'='*60}\n🧪 TEST PIPELINE: {len(paths)} ảnh\n{'='*60}")
    print("→ Nhấn phím bất kỳ để qua bước, ESC để thoát\n")

    b64_list:  list[str]            = []
    size_list: list[tuple[int,int]] = []

    for idx, path in enumerate(paths, 1):
        print(f"\n{'─'*40}\n🖼️  Ảnh {idx}/{len(paths)}: {os.path.basename(path)}\n{'─'*40}")

        os.makedirs("debug_output", exist_ok=True)
        orig = load_image(path)
        cv2.imwrite("debug_output/01-original.jpg", orig)

        print("\n--- Quality Check ---")
        quality = check_image_quality(orig)
        if not quality["passed"]:
            print("❌ Ảnh không đạt — bỏ qua")
            continue

        print("\n--- Perspective Correction ---")
        persp = correct_perspective(orig)
        cv2.imwrite("debug_output/02-perspective.jpg", persp)

        print("\n--- Enhance (adaptive) ---")
        enh = enhance_image(persp, brightness=quality["brightness"])
        cv2.imwrite("debug_output/03-enhanced.jpg", enh)
        
        print("\n💾 Đã lưu các bước xử lý vào thư mục 'debug_output'. Bạn hãy mở xem nhé.")

        print("\n--- ⚠️  Binarization SKIPPED (LLM mode) ---")

        print("\n--- Prepare for API ---")
        b64, size = prepare_for_api(enh)
        print(f"📦 {len(b64)//1024} KB  |  ~{calculate_image_tokens(*size)} image tokens")
        b64_list.append(b64)
        size_list.append(size)

    if not b64_list:
        print("\n❌ Không có ảnh hợp lệ.")
        cv2.destroyAllWindows()
        return

    ocr = adapter or create_ocr_adapter()
    n   = len(b64_list)
    print(f"\n--- OCR ({n} ảnh, 1 request) ---")
    result = ocr.ocr(b64_list, image_sizes=size_list)
    _print_ocr_result(result)

    if result["success"] and result["text"]:
        suffix   = f"_{n}imgs" if n > 1 else ""
        out_path = os.path.splitext(paths[0])[0] + f"{suffix}_ocr.txt"
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(result["text"])
        print(f"💾 Đã lưu: {out_path}")

    print("\n✅ Xong!")


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":
    """
    Cách dùng:
      python image_processing.py anh.jpg
      python image_processing.py t1.jpg t2.jpg t3.jpg

    Đổi provider trong .env (không cần sửa code):
      OCR_PROVIDER=gemini      GEMINI_API_KEY=AIza...
      OCR_PROVIDER=openai      OPENAI_API_KEY=sk-...
      OCR_PROVIDER=claude      ANTHROPIC_API_KEY=sk-ant-...
      OCR_PROVIDER=ollama      (không cần key, cần ollama serve)
      OCR_PROVIDER=mock        (test không cần API)
    """
    args = sys.argv[1:]
    image_paths = args if args else ["demo3.jpg"]

    # Adapter tạo từ .env — không cần truyền key qua CLI nữa
    try:
        adapter = create_ocr_adapter()
    except ValueError as e:
        print(f"❌ {e}")
        sys.exit(1)

    test_pipeline(
        image_paths[0] if len(image_paths) == 1 else image_paths,
        adapter=adapter,
    )