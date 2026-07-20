"""LW-700 physical print specs.

The LW-700 print head is 180 dpi, monochrome thermal-transfer. The tape moves
lengthwise; the head is a vertical column of `printable_dots` pixels across the
tape. A label bitmap is therefore (length_dots wide) x (printable_dots tall).

NOTE: printable_dots per tape width were provisional (typical Epson LW values) until
measured on hardware. 12 mm is now calibrated; the rest are still estimates.

Calibration method (see LW700Bridge/tools/calibrate_tape.py): print a stepped wedge
whose step length encodes its row number, then measure which steps survive. Sending
more rows than the head prints does not widen the output - the printer silently drops
the extra ones off the top, which shifts the whole label sideways on the tape.
"""
from dataclasses import dataclass

DPI = 180
MM_PER_INCH = 25.4


def mm_to_dots(mm: float) -> int:
    return round(mm / MM_PER_INCH * DPI)


@dataclass(frozen=True)
class TapeSpec:
    width_mm: int
    printable_dots: int  # usable head height for this tape (provisional)


# Supported tapes (from LW-700 PPD: 6/9/12/18/24 mm).
# 12 mm measured 2026-07-20: 72 dots (10.16 mm), sitting 0.7 mm from one tape edge and
# 1.2 mm from the other. The others are still provisional - recalibrate when a reel of
# that width is at hand.
TAPES: dict[int, TapeSpec] = {
    6: TapeSpec(6, 32),
    9: TapeSpec(9, 48),
    12: TapeSpec(12, 72),
    18: TapeSpec(18, 112),
    24: TapeSpec(24, 128),
}

DEFAULT_TAPE_MM = 18
MIN_LINES = 1
MAX_LINES = 8


def tape(width_mm: int) -> TapeSpec:
    return TAPES.get(width_mm, TAPES[DEFAULT_TAPE_MM])
