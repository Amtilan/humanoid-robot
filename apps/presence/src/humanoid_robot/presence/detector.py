"""Motion-based visitor detector.

The presenter scene is static (a hall, the wall, the stand) until a visitor
walks up to the robot — so grayscale frame differencing is a robust,
dependency-light "someone is here" signal. The score is the fraction of
pixels that changed appreciably against the previous frame.
"""

from __future__ import annotations

import io

import numpy as np
from PIL import Image

# Downscale before diffing: kills JPEG noise and makes the diff O(small).
_ANALYSIS_SIZE = (160, 120)
# A pixel counts as "changed" when its gray level moved by more than this
# (0..255); below is sensor/JPEG noise.
_PIXEL_DELTA = 25


class MotionDetector:
    """Stateful frame-differencing scorer; feed frames, read scores."""

    def __init__(self) -> None:
        self._previous: np.ndarray | None = None

    def score(self, jpeg: bytes) -> float:
        """0..1 — fraction of the frame that moved since the last call."""
        with Image.open(io.BytesIO(jpeg)) as img:
            gray = np.asarray(
                img.convert("L").resize(_ANALYSIS_SIZE, Image.BILINEAR),
                dtype=np.int16,
            )
        previous, self._previous = self._previous, gray
        if previous is None:
            return 0.0
        changed = np.abs(gray - previous) > _PIXEL_DELTA
        return float(changed.mean())

    def reset(self) -> None:
        self._previous = None
