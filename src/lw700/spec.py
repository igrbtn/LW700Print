"""LW-700 physical print specs.

The LW-700 print head is 180 dpi, monochrome thermal-transfer. The tape moves
lengthwise; the head is a vertical column of `printable_dots` pixels across the
tape. A label bitmap is therefore (length_dots wide) x (printable_dots tall).

NOTE: printable_dots per tape width are provisional (typical Epson LW values) and
will be locked to the exact hardware values once the reference USB capture is
decoded (the printer reports usable dot count in its status). Layout/preview are
correct in proportion regardless.
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


# Supported tapes (from LW-700 PPD: 6/9/12/18/24 mm) with provisional printable heights.
TAPES: dict[int, TapeSpec] = {
    6: TapeSpec(6, 32),
    9: TapeSpec(9, 48),
    12: TapeSpec(12, 76),
    18: TapeSpec(18, 112),
    24: TapeSpec(24, 128),
}

DEFAULT_TAPE_MM = 18
MIN_LINES = 1
MAX_LINES = 8


def tape(width_mm: int) -> TapeSpec:
    return TAPES.get(width_mm, TAPES[DEFAULT_TAPE_MM])
