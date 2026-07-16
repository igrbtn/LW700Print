"""Font resolution. Prefer fonts with Cyrillic coverage (project language is RU)."""
import os
from functools import lru_cache

from PIL import ImageFont

# Curated candidates: (friendly name, [regular path candidates], [bold path candidates]).
# DejaVu is bundled with the project (assets/fonts) so the Cyrillic default is
# deterministic on any machine, regardless of Pillow build or system fonts.
_BUNDLED = os.path.join(os.path.dirname(__file__), "..", "..", "assets", "fonts")
_BUNDLED = os.path.abspath(_BUNDLED)

_SYS = "/System/Library/Fonts"
_SYS_SUP = "/System/Library/Fonts/Supplemental"
_USER = os.path.expanduser("~/Library/Fonts")

FONT_TABLE = {
    "DejaVu Sans": {
        "regular": [os.path.join(_BUNDLED, "DejaVuSans.ttf")],
        "bold": [os.path.join(_BUNDLED, "DejaVuSans-Bold.ttf")],
    },
    "DejaVu Sans Mono": {
        "regular": [os.path.join(_BUNDLED, "DejaVuSansMono.ttf")],
        "bold": [os.path.join(_BUNDLED, "DejaVuSansMono-Bold.ttf")],
    },
    "Helvetica": {
        "regular": [f"{_SYS}/Helvetica.ttc", f"{_SYS_SUP}/Helvetica.ttc"],
        "bold": [f"{_SYS}/Helvetica.ttc"],
    },
    "Arial": {
        "regular": [f"{_SYS_SUP}/Arial.ttf"],
        "bold": [f"{_SYS_SUP}/Arial Bold.ttf"],
    },
    "Arial Narrow": {
        "regular": [f"{_SYS_SUP}/Arial Narrow.ttf"],
        "bold": [f"{_SYS_SUP}/Arial Narrow Bold.ttf"],
    },
    "Times New Roman": {
        "regular": [f"{_SYS_SUP}/Times New Roman.ttf"],
        "bold": [f"{_SYS_SUP}/Times New Roman Bold.ttf"],
    },
    "Courier New": {
        "regular": [f"{_SYS_SUP}/Courier New.ttf"],
        "bold": [f"{_SYS_SUP}/Courier New Bold.ttf"],
    },
    "Menlo": {
        "regular": [f"{_SYS}/Menlo.ttc"],
        "bold": [f"{_SYS}/Menlo.ttc"],
    },
    "PT Sans": {
        "regular": [f"{_SYS_SUP}/PTSans.ttc"],
        "bold": [f"{_SYS_SUP}/PTSans.ttc"],
    },
}

DEFAULT_FONT = "DejaVu Sans"


def _first_existing(paths):
    for p in paths:
        if os.path.exists(p):
            return p
    return None


@lru_cache(maxsize=1)
def available_fonts() -> list[str]:
    """Friendly names whose regular file exists on this machine."""
    names = [n for n, v in FONT_TABLE.items() if _first_existing(v["regular"])]
    # keep DejaVu first as the safe Cyrillic default
    names = sorted(names, key=lambda n: (n != DEFAULT_FONT, n))
    return names


@lru_cache(maxsize=256)
def load_font(name: str, size_px: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    entry = FONT_TABLE.get(name, FONT_TABLE[DEFAULT_FONT])
    dejavu = os.path.join(_BUNDLED, "DejaVuSans.ttf")
    path = _first_existing(entry["bold" if bold else "regular"]) \
        or _first_existing(entry["regular"]) \
        or dejavu
    try:
        return ImageFont.truetype(path, size_px)
    except OSError:
        return ImageFont.truetype(dejavu, size_px)
