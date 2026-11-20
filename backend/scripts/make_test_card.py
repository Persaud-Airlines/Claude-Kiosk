#!/usr/bin/env python3
"""Generate a synthetic student ID card photo (as a kiosk webcam would see it) for bench testing.

  python scripts/make_test_card.py --first Jordan --last Taylor --number 300123456 -o card.jpg
  python scripts/make_test_card.py --size 640x480 -o ../firmware/main/assets/mock_card.jpg

The output is used by backend tests and embedded in the firmware's MockCameraProvider.
"""
from __future__ import annotations

import argparse
import os

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/Library/Fonts/Arial Bold.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
]
FONT_REG_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/Library/Fonts/Arial.ttf",
    "C:/Windows/Fonts/arial.ttf",
]


def _font(cands: list[str], size: int):
    for path in cands:
        if os.path.exists(path):
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def render_card(first: str, last: str, number: str, school: str, layout: str = "plain") -> np.ndarray:
    w, h = 856, 540
    img = Image.new("RGB", (w, h), (250, 250, 247))
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, w, 110], fill=(18, 52, 110))
    d.text((30, 28), school.upper(), font=_font(FONT_CANDIDATES, 40), fill=(255, 255, 255))
    d.text((30, 120), "STUDENT IDENTIFICATION CARD", font=_font(FONT_REG_CANDIDATES, 24), fill=(80, 80, 80))
    d.rectangle([30, 170, 230, 430], fill=(200, 206, 214), outline=(120, 120, 120), width=3)
    d.ellipse([85, 200, 175, 290], fill=(150, 156, 166))
    d.rectangle([70, 300, 190, 420], fill=(150, 156, 166))
    big = _font(FONT_CANDIDATES, 58)
    small = _font(FONT_REG_CANDIDATES, 30)
    if layout == "labels":
        d.text((260, 180), "Last Name:", font=small, fill=(90, 90, 90))
        d.text((260, 215), last.upper(), font=big, fill=(10, 10, 10))
        d.text((260, 295), "First Name:", font=small, fill=(90, 90, 90))
        d.text((260, 330), first, font=big, fill=(10, 10, 10))
    else:
        d.text((260, 200), first, font=big, fill=(10, 10, 10))
        d.text((260, 270), last, font=big, fill=(10, 10, 10))
    d.text((260, 420), f"Student No: {number}", font=small, fill=(30, 30, 30))
    d.text((260, 465), "Grade 11   Valid 2026-2027", font=small, fill=(30, 30, 30))
    return cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)


def place_in_scene(card: np.ndarray, out_w: int, out_h: int, seed: int = 7) -> np.ndarray:
    rng = np.random.default_rng(seed)
    scene = np.full((out_h, out_w, 3), (52, 60, 70), np.uint8)
    noise = rng.normal(0, 6, scene.shape).astype(np.int16)
    scene = np.clip(scene.astype(np.int16) + noise, 0, 255).astype(np.uint8)
    ch, cw = card.shape[:2]
    margin_x, margin_y = out_w * 0.12, out_h * 0.14
    dst = np.float32([
        [margin_x + 8, margin_y],
        [out_w - margin_x, margin_y + 10],
        [out_w - margin_x - 6, out_h - margin_y],
        [margin_x, out_h - margin_y - 8],
    ])
    m = cv2.getPerspectiveTransform(np.float32([[0, 0], [cw, 0], [cw, ch], [0, ch]]), dst)
    warped = cv2.warpPerspective(card, m, (out_w, out_h))
    mask = cv2.warpPerspective(np.full((ch, cw), 255, np.uint8), m, (out_w, out_h))
    scene[mask > 0] = warped[mask > 0]
    return cv2.GaussianBlur(scene, (3, 3), 0)


def make_card_jpeg(first="Jordan", last="Taylor", number="300123456", school="Lakeview Secondary School",
                   size=(1280, 960), layout="plain", quality=88) -> bytes:
    scene = place_in_scene(render_card(first, last, number, school, layout), *size)
    ok, buf = cv2.imencode(".jpg", scene, [cv2.IMWRITE_JPEG_QUALITY, quality])
    assert ok
    return buf.tobytes()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--first", default="Jordan")
    ap.add_argument("--last", default="Taylor")
    ap.add_argument("--number", default="300123456")
    ap.add_argument("--school", default="Lakeview Secondary School")
    ap.add_argument("--layout", choices=["plain", "labels"], default="plain")
    ap.add_argument("--size", default="1280x960")
    ap.add_argument("--quality", type=int, default=88)
    ap.add_argument("-o", "--output", default="test_card.jpg")
    a = ap.parse_args()
    w, h = (int(x) for x in a.size.lower().split("x"))
    data = make_card_jpeg(a.first, a.last, a.number, a.school, (w, h), a.layout, a.quality)
    with open(a.output, "wb") as fh:
        fh.write(data)
    print(f"wrote {a.output} ({len(data)} bytes)")
