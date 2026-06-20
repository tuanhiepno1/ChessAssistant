from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class CaptureRegion:
    left: int
    top: int
    width: int
    height: int


class ScreenCapture:
    def monitors(self) -> list[CaptureRegion]:
        import mss

        with mss.mss() as sct:
            return [
                CaptureRegion(
                    left=int(monitor["left"]),
                    top=int(monitor["top"]),
                    width=int(monitor["width"]),
                    height=int(monitor["height"]),
                )
                for monitor in sct.monitors[1:]
            ]

    def capture(self, region: CaptureRegion | None = None) -> np.ndarray:
        import mss

        with mss.mss() as sct:
            monitor = region.__dict__ if region else sct.monitors[1]
            image = np.array(sct.grab(monitor))
        return image[:, :, 2::-1]
