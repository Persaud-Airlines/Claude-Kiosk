#!/usr/bin/env python3
"""Write a 320x240 RGB565 preview frame (little-endian) from the mock card, for the simulator."""
import sys
from pathlib import Path

import cv2
import numpy as np

HERE = Path(__file__).resolve().parent
card = HERE.parent / "main" / "assets" / "mock_card.jpg"
out = Path(sys.argv[1] if len(sys.argv) > 1 else "frame.rgb565")

img = cv2.resize(cv2.imread(str(card)), (320, 240), interpolation=cv2.INTER_AREA)
rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB).astype(np.uint16)
rgb565 = ((rgb[..., 0] >> 3) << 11) | ((rgb[..., 1] >> 2) << 5) | (rgb[..., 2] >> 3)
rgb565.astype("<u2").tofile(out)
print(f"wrote {out}")
