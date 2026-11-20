"""Student ID card detection (OpenCV) + OCR name extraction.

Pipeline
  1. Decode JPEG -> BGR ndarray (size / format validated).
  2. Try QR / barcode payload (fast path, exact data).
  3. Detect the card's quadrilateral contour, four-point perspective warp to ID-1 aspect (85.6 x 54 mm).
  4. Enhance (CLAHE on luminance, denoise, adaptive threshold variant).
  5. OCR with the best available engine (PaddleOCR > EasyOCR > Tesseract).
  6. Parse First / Last name with label-aware heuristics (EN / FR / ES), then optionally snap to the
     school's enrolled roster with fuzzy matching to correct OCR noise.

No image is ever written to disk unless OCR_DEBUG_DIR is explicitly set (forbidden in production).
"""
from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Protocol

import cv2
import numpy as np

from ..core.config import get_settings

log = logging.getLogger("detechtive.ocr")

CARD_ASPECT = 85.6 / 54.0
WARP_W, WARP_H = 1000, int(1000 / CARD_ASPECT)

STOPWORDS = {
    "student", "students", "school", "secondary", "high", "elementary", "middle", "public", "catholic",
    "academy", "college", "collegiate", "institute", "district", "board", "card", "identification", "id",
    "grade", "valid", "until", "expires", "exp", "issued", "year", "number", "no", "dob", "birth", "date",
    "name", "first", "last", "surname", "given", "homeroom", "room", "teacher", "principal", "signature",
    "library", "barcode", "photo", "class", "of", "the", "and", "for", "est", "carte", "etudiant", "étudiant",
    "eleve", "élève", "ecole", "école", "secondaire", "nom", "prenom", "prénom", "tarjeta", "estudiante",
    "escuela", "nombre", "apellido", "apellidos", "alumno", "grado", "technologies", "inc", "detechtive",
    "de-tech-tive", "phone", "address", "emergency", "contact", "property", "if", "found", "return", "to",
    "please", "present", "this", "frame", "your", "school's", "schools", "tdsb", "district", "usd", "isd",
}
NAME_PARTICLES = {"de", "da", "del", "della", "der", "di", "du", "la", "le", "van", "von", "st", "st.", "mac", "bin", "al"}

_token_re = re.compile(r"^[A-Za-zÀ-ÖØ-öø-ÿ][A-Za-zÀ-ÖØ-öø-ÿ'\-]*[A-Za-zÀ-ÖØ-öø-ÿ]$")
_student_no_re = re.compile(r"(?<!\d)(\d{6,10})(?!\d)")

LABELS_FULL = re.compile(
    r"^(?:student\s+)?(?:full\s+)?(?:name|nom(?:\s+complet)?|nombre(?:\s+completo)?)\s*[:\-]?\s*(?P<v>.+)$", re.I
)
LABELS_FIRST = re.compile(r"^(?:first(?:\s+name)?|given\s+names?|pr[ée]nom|nombre)s?\s*[:\-]?\s*(?P<v>.*)$", re.I)
LABELS_LAST = re.compile(
    r"^(?:last(?:\s+name)?|surname|family\s+name|nom(?:\s+de\s+famille)?|apellidos?)\s*[:\-]?\s*(?P<v>.*)$", re.I
)


# ---------------------------------------------------------------------------------- data types
@dataclass
class OcrLine:
    text: str
    confidence: float  # 0..1
    height: float = 0.0  # pixel height of the text line (bigger usually == the name)
    y: float = 0.0


@dataclass
class NameCandidate:
    first: str
    last: str
    score: float
    source: str


@dataclass
class OcrResult:
    detected: bool
    first_name: str | None = None
    last_name: str | None = None
    student_number: str | None = None
    confidence: float = 0.0
    card_found: bool = False
    engine: str = "none"
    reason: str | None = None
    candidates: list[NameCandidate] = field(default_factory=list)
    elapsed_ms: int = 0


class OcrEngine(Protocol):
    name: str

    def read(self, image: np.ndarray) -> list[OcrLine]: ...


# ------------------------------------------------------------------------------------ engines
class TesseractEngine:
    name = "tesseract"

    def __init__(self) -> None:
        import pytesseract

        self._pt = pytesseract
        pytesseract.get_tesseract_version()  # raises if binary missing

    def read(self, image: np.ndarray) -> list[OcrLine]:
        data = self._pt.image_to_data(
            image, lang=os.environ.get("TESSERACT_LANG", "eng"), config="--oem 1 --psm 11",
            output_type=self._pt.Output.DICT,
        )
        # psm 11 returns sparse words; regroup into lines by block/par/line and vertical proximity
        groups: dict[tuple[int, int, int], list[int]] = {}
        for i, txt in enumerate(data["text"]):
            if not txt.strip() or float(data["conf"][i]) < 0:
                continue
            key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
            groups.setdefault(key, []).append(i)
        lines: list[OcrLine] = []
        for idxs in groups.values():
            idxs.sort(key=lambda j: data["left"][j])
            text = " ".join(data["text"][j] for j in idxs)
            conf = float(np.mean([float(data["conf"][j]) for j in idxs])) / 100.0
            h = float(np.median([data["height"][j] for j in idxs]))
            y = float(np.mean([data["top"][j] for j in idxs]))
            lines.append(OcrLine(text=text, confidence=conf, height=h, y=y))
        return _merge_same_row(lines)


class EasyOcrEngine:
    name = "easyocr"

    def __init__(self) -> None:
        import easyocr  # type: ignore

        self._reader = easyocr.Reader(["en", "fr", "es"], gpu=False, verbose=False)

    def read(self, image: np.ndarray) -> list[OcrLine]:
        out = []
        for box, text, conf in self._reader.readtext(image):
            ys = [p[1] for p in box]
            out.append(OcrLine(text=text, confidence=float(conf), height=max(ys) - min(ys), y=min(ys)))
        return _merge_same_row(out)


class PaddleOcrEngine:
    name = "paddle"

    def __init__(self) -> None:
        from paddleocr import PaddleOCR  # type: ignore

        self._ocr = PaddleOCR(use_angle_cls=True, lang="en", show_log=False)

    def read(self, image: np.ndarray) -> list[OcrLine]:
        result = self._ocr.ocr(image, cls=True) or []
        out = []
        for page in result:
            for box, (text, conf) in page or []:
                ys = [p[1] for p in box]
                out.append(OcrLine(text=text, confidence=float(conf), height=max(ys) - min(ys), y=min(ys)))
        return _merge_same_row(out)


def _merge_same_row(lines: list[OcrLine]) -> list[OcrLine]:
    """Combine word fragments that sit on the same visual row (e.g. 'Jordan' + 'Taylor')."""
    lines = sorted(lines, key=lambda l: (l.y, -l.height))
    merged: list[OcrLine] = []
    for ln in lines:
        if merged:
            prev = merged[-1]
            tol = max(prev.height, ln.height) * 0.5
            if abs(prev.y - ln.y) <= tol and abs(prev.height - ln.height) <= max(prev.height, ln.height) * 0.35:
                prev.text = f"{prev.text} {ln.text}"
                prev.confidence = min(prev.confidence, ln.confidence)
                continue
        merged.append(OcrLine(ln.text, ln.confidence, ln.height, ln.y))
    return merged


_engine_lock = threading.Lock()
_engine: OcrEngine | None = None
_engine_override: OcrEngine | None = None
_engine_failed = False


def set_engine_override(engine: OcrEngine | None) -> None:
    """Tests / bench mode can inject a deterministic engine."""
    global _engine_override
    _engine_override = engine


def get_engine() -> OcrEngine | None:
    global _engine, _engine_failed
    if _engine_override is not None:
        return _engine_override
    if _engine is not None or _engine_failed:
        return _engine
    with _engine_lock:
        if _engine is not None:
            return _engine
        choice = get_settings().ocr_engine
        order = {
            "auto": [PaddleOcrEngine, EasyOcrEngine, TesseractEngine],
            "paddle": [PaddleOcrEngine],
            "easyocr": [EasyOcrEngine],
            "tesseract": [TesseractEngine],
            "none": [],
        }[choice]
        for cls in order:
            try:
                _engine = cls()
                log.info("OCR engine initialised: %s", _engine.name)
                return _engine
            except Exception as exc:  # noqa: BLE001 - engine optional
                log.info("OCR engine %s unavailable: %s", cls.__name__, exc)
        _engine_failed = True
        log.warning("No OCR engine available; only QR-coded cards can be read")
        return None


# ------------------------------------------------------------------------------ image helpers
def decode_jpeg(data: bytes) -> np.ndarray:
    if len(data) < 64 or not (data[:3] == b"\xff\xd8\xff" or data[:8] == b"\x89PNG\r\n\x1a\n"):
        raise ValueError("Payload is not a JPEG/PNG image")
    img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("Image could not be decoded")
    h, w = img.shape[:2]
    if w < 160 or h < 120 or w > 4096 or h > 4096:
        raise ValueError("Image dimensions out of range")
    return img


def order_points(pts: np.ndarray) -> np.ndarray:
    rect = np.zeros((4, 2), dtype="float32")
    s = pts.sum(axis=1)
    rect[0] = pts[np.argmin(s)]  # top-left
    rect[2] = pts[np.argmax(s)]  # bottom-right
    d = np.diff(pts, axis=1)
    rect[1] = pts[np.argmin(d)]  # top-right
    rect[3] = pts[np.argmax(d)]  # bottom-left
    return rect


def four_point_transform(image: np.ndarray, pts: np.ndarray) -> np.ndarray:
    rect = order_points(pts.reshape(4, 2).astype("float32"))
    (tl, tr, br, bl) = rect
    width = max(np.linalg.norm(br - bl), np.linalg.norm(tr - tl))
    height = max(np.linalg.norm(tr - br), np.linalg.norm(tl - bl))
    portrait = height > width
    dst_w, dst_h = (WARP_H, WARP_W) if portrait else (WARP_W, WARP_H)
    dst = np.array([[0, 0], [dst_w - 1, 0], [dst_w - 1, dst_h - 1], [0, dst_h - 1]], dtype="float32")
    m = cv2.getPerspectiveTransform(rect, dst)
    return cv2.warpPerspective(image, m, (dst_w, dst_h), flags=cv2.INTER_CUBIC)


def detect_card(image: np.ndarray) -> np.ndarray | None:
    """Return the 4-point contour of the largest card-shaped quadrilateral, or None."""
    h, w = image.shape[:2]
    scale = 800.0 / max(h, w)
    small = cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA) if scale < 1 else image.copy()
    s = scale if scale < 1 else 1.0
    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
    gray = cv2.bilateralFilter(gray, 9, 60, 60)
    frame_area = small.shape[0] * small.shape[1]
    best, best_area = None, 0.0
    for lo, hi in ((30, 120), (50, 180), (15, 80)):
        edges = cv2.Canny(gray, lo, hi)
        edges = cv2.dilate(edges, cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5)), iterations=2)
        edges = cv2.erode(edges, cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3)), iterations=1)
        contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for c in sorted(contours, key=cv2.contourArea, reverse=True)[:8]:
            area = cv2.contourArea(c)
            if area < 0.12 * frame_area or area > 0.98 * frame_area:
                continue
            peri = cv2.arcLength(c, True)
            approx = cv2.approxPolyDP(c, 0.02 * peri, True)
            if len(approx) != 4:
                rect = cv2.minAreaRect(c)
                box = cv2.boxPoints(rect)
                if cv2.contourArea(box) <= 0 or area / cv2.contourArea(box) < 0.85:
                    continue
                approx = box.reshape(4, 1, 2)
            (rw, rh) = cv2.minAreaRect(approx.reshape(4, 2).astype("float32"))[1]
            if min(rw, rh) == 0:
                continue
            aspect = max(rw, rh) / min(rw, rh)
            if not 1.30 <= aspect <= 1.90:
                continue
            if area > best_area:
                best, best_area = approx.reshape(4, 2).astype("float32") / s, area
        if best is not None:
            break
    return best


def enhance(card: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    lab = cv2.cvtColor(card, cv2.COLOR_BGR2LAB)
    l_ch, a_ch, b_ch = cv2.split(lab)
    clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8))
    l_ch = clahe.apply(l_ch)
    enhanced = cv2.cvtColor(cv2.merge((l_ch, a_ch, b_ch)), cv2.COLOR_LAB2BGR)
    gray = cv2.cvtColor(enhanced, cv2.COLOR_BGR2GRAY)
    gray = cv2.fastNlMeansDenoising(gray, None, 7, 7, 21)
    thresh = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 12)
    return gray, thresh


def card_sharpness(gray: np.ndarray) -> float:
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


# ----------------------------------------------------------------------------- QR / barcodes
def decode_qr(image: np.ndarray) -> dict | None:
    try:
        payload, _, _ = cv2.QRCodeDetector().detectAndDecode(image)
    except cv2.error:
        return None
    if not payload:
        return None
    return parse_card_payload(payload)


def parse_card_payload(payload: str) -> dict | None:
    payload = payload.strip()
    try:
        obj = json.loads(payload)
        if isinstance(obj, dict):
            first = obj.get("first_name") or obj.get("firstName") or obj.get("first")
            last = obj.get("last_name") or obj.get("lastName") or obj.get("last")
            if first and last:
                num = obj.get("student_number") or obj.get("studentNumber") or obj.get("id")
                return {"first_name": str(first), "last_name": str(last), "student_number": str(num) if num else None}
    except (json.JSONDecodeError, TypeError):
        pass
    parts = [p.strip() for p in re.split(r"[,;|^]", payload) if p.strip()]
    if len(parts) >= 2 and all(_is_name_token(t) for t in parts[0].split() + parts[1].split()):
        num = next((p for p in parts[2:] if _student_no_re.fullmatch(p)), None)
        return {"last_name": parts[0], "first_name": parts[1], "student_number": num}
    return None


# --------------------------------------------------------------------------- name heuristics
def _clean(text: str) -> str:
    text = text.replace("|", " ").replace("_", " ").replace("’", "'")
    text = re.sub(r"[“”\"`~*•·]+", " ", text)
    return re.sub(r"\s+", " ", text).strip(" .:-")


def _is_name_token(tok: str) -> bool:
    t = tok.strip(".,")
    return bool(_token_re.match(t)) and t.lower() not in STOPWORDS and len(t) >= 2


def _split_full_name(value: str) -> tuple[str, str] | None:
    value = _clean(value)
    if "," in value:
        last, _, first = value.partition(",")
        first_toks = [t for t in first.split() if _is_name_token(t)]
        last_toks = [t for t in last.split() if _is_name_token(t) or t.lower() in NAME_PARTICLES]
        if first_toks and last_toks:
            return first_toks[0], " ".join(last_toks)
        return None
    toks = [t.strip(".,") for t in value.split()]
    toks = [t for t in toks if _is_name_token(t) or t.lower() in NAME_PARTICLES]
    if len(toks) < 2 or len(toks) > 4:
        return None
    first = toks[0]
    rest = toks[1:]
    # keep particles with the surname: "Jordan De Silva"; drop a single middle name: "Mary Ann Smith"
    for i, t in enumerate(rest):
        if t.lower() in NAME_PARTICLES:
            return first, " ".join(rest[i:])
    return first, rest[-1]


def extract_names(lines: list[OcrLine]) -> list[NameCandidate]:
    cands: list[NameCandidate] = []
    texts = [_clean(l.text) for l in lines]
    max_h = max((l.height for l in lines), default=1.0) or 1.0

    first_val = last_val = None
    first_conf = last_conf = 0.0
    for i, (ln, txt) in enumerate(zip(lines, texts)):
        nxt = texts[i + 1] if i + 1 < len(texts) else ""
        nxt_conf = lines[i + 1].confidence if i + 1 < len(lines) else 0.0
        if m := LABELS_LAST.match(txt):
            v = m.group("v").strip() or nxt
            if v and all(_is_name_token(t) or t.lower() in NAME_PARTICLES for t in v.split()):
                last_val, last_conf = v, ln.confidence if m.group("v").strip() else nxt_conf
                continue
        if m := LABELS_FIRST.match(txt):
            v = m.group("v").strip() or nxt
            toks = [t for t in v.split() if _is_name_token(t)]
            if toks:
                first_val, first_conf = toks[0], ln.confidence if m.group("v").strip() else nxt_conf
                continue
        if m := LABELS_FULL.match(txt):
            v = m.group("v").strip() or nxt
            split = _split_full_name(v)
            if split:
                cands.append(NameCandidate(split[0], split[1], min(1.0, ln.confidence * 0.95 + 0.08), "label:full"))
    if first_val and last_val:
        cands.append(NameCandidate(first_val, last_val, min(1.0, min(first_conf, last_conf) * 0.95 + 0.1), "label:split"))

    for ln, txt in zip(lines, texts):
        if ":" in txt:
            continue
        if "," in txt:
            split = _split_full_name(txt)
            if split:
                cands.append(NameCandidate(split[0], split[1], ln.confidence * 0.85, "comma"))
            continue
        raw = txt.split()
        if not 2 <= len(raw) <= 4:
            continue
        good = [t for t in raw if _is_name_token(t) or t.lower() in NAME_PARTICLES]
        if len(good) != len(raw):
            continue
        split = _split_full_name(txt)
        if not split:
            continue
        size_bonus = 0.15 * (ln.height / max_h)
        case_bonus = 0.05 if all(t[0].isupper() for t in raw if t.lower() not in NAME_PARTICLES) else 0.0
        cands.append(NameCandidate(split[0], split[1], min(1.0, ln.confidence * 0.8 + size_bonus + case_bonus), "line"))
    # Stacked layout: first name on one line, surname directly below in the same large type.
    for i in range(len(lines) - 1):
        a, b = lines[i], lines[i + 1]
        ta, tb = texts[i].split(), texts[i + 1].split()
        if not ta or not tb or len(ta) > 2 or len(tb) > 3 or ":" in texts[i] or ":" in texts[i + 1]:
            continue
        if not all(_is_name_token(t) for t in ta) or not all(_is_name_token(t) or t.lower() in NAME_PARTICLES for t in tb):
            continue
        if min(a.height, b.height) < 0.55 * max_h or abs(a.height - b.height) > 0.3 * max(a.height, b.height):
            continue
        size_bonus = 0.15 * (min(a.height, b.height) / max_h)
        cands.append(NameCandidate(ta[0], " ".join(tb), min(1.0, min(a.confidence, b.confidence) * 0.8 + size_bonus), "stacked"))
    cands.sort(key=lambda c: c.score, reverse=True)
    return cands


def extract_student_number(lines: list[OcrLine]) -> str | None:
    for ln in lines:
        if m := _student_no_re.search(ln.text.replace(" ", "")):
            return m.group(1)
    return None


# ------------------------------------------------------------------------------- entry point
def analyze_card_image(data: bytes) -> OcrResult:
    """Synchronous, CPU bound — call from a worker thread."""
    started = time.perf_counter()
    try:
        img = decode_jpeg(data)
    except ValueError as exc:
        return OcrResult(detected=False, reason=str(exc))

    def _done(r: OcrResult) -> OcrResult:
        r.elapsed_ms = int((time.perf_counter() - started) * 1000)
        return r

    qr = decode_qr(img)
    if qr:
        return _done(
            OcrResult(True, qr["first_name"], qr["last_name"], qr.get("student_number"), 0.99, True, "qr")
        )

    quad = detect_card(img)
    card_found = quad is not None
    card = four_point_transform(img, quad) if card_found else img
    if card.shape[0] > card.shape[1]:  # portrait card -> rotate to landscape for OCR
        card = cv2.rotate(card, cv2.ROTATE_90_CLOCKWISE)
    if not card_found:
        h, w = card.shape[:2]
        scale = 1000.0 / w
        card = cv2.resize(card, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    gray, thresh = enhance(card)

    debug_dir = get_settings().ocr_debug_dir
    if debug_dir:
        os.makedirs(debug_dir, exist_ok=True)
        cv2.imwrite(os.path.join(debug_dir, f"{uuid.uuid4().hex}_card.jpg"), card)

    if card_sharpness(gray) < 15.0:
        return _done(OcrResult(False, card_found=card_found, reason="image_too_blurry"))

    qr = decode_qr(card)
    if qr:
        return _done(OcrResult(True, qr["first_name"], qr["last_name"], qr.get("student_number"), 0.99, True, "qr"))

    engine = get_engine()
    if engine is None:
        return _done(OcrResult(False, card_found=card_found, reason="ocr_engine_unavailable"))

    lines = engine.read(gray)
    cands = extract_names(lines)
    if not cands or cands[0].score < 0.75:
        alt = engine.read(thresh)
        cands = sorted(cands + extract_names(alt), key=lambda c: c.score, reverse=True)
        lines = lines + alt
    number = extract_student_number(lines)
    if not cands:
        return _done(OcrResult(False, student_number=number, card_found=card_found, engine=engine.name,
                               reason="no_name_found" if card_found else "no_card_detected"))
    best = cands[0]
    conf = best.score if card_found else best.score * 0.85
    return _done(
        OcrResult(
            detected=True,
            first_name=best.first,
            last_name=best.last,
            student_number=number,
            confidence=round(float(conf), 3),
            card_found=card_found,
            engine=engine.name,
            candidates=cands[:5],
        )
    )
