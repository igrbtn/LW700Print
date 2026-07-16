"""Render a label description into a 1-bit bitmap sized for the LW-700 head.

Coordinate model: image is (length_dots wide) x (printable_dots tall) at 180 dpi,
black pixels = printed. This bitmap is both the on-screen preview and the source
for the (future) ESCPL2 raster encoder - one source of truth.
"""
from __future__ import annotations

import io
from dataclasses import dataclass, field
from typing import Literal

import barcode as barcode_lib
import qrcode
from barcode.writer import ImageWriter
from PIL import Image, ImageDraw

from . import fonts
from .spec import DEFAULT_TAPE_MM, MAX_LINES, mm_to_dots, tape

Align = Literal["left", "center", "right"]
LabelType = Literal["text", "qr", "barcode", "text_qr"]

MAX_LENGTH_MM = 500  # safety cap
LINE_PAD_FRAC = 0.15  # vertical padding inside each text band


@dataclass
class Line:
    text: str = ""
    font: str = fonts.DEFAULT_FONT
    size_pt: int = 0  # 0 => auto-fit the line band
    bold: bool = False
    align: Align = "center"


@dataclass
class LabelSpec:
    tape_mm: int = DEFAULT_TAPE_MM
    label_type: LabelType = "text"
    lines: list[Line] = field(default_factory=lambda: [Line(text="LW-700")])
    length_mode: Literal["auto", "fixed"] = "auto"
    length_mm: float = 40.0
    margin_mm: float = 3.0
    # barcode / qr
    code_data: str = ""
    barcode_type: str = "code128"
    show_code_text: bool = True
    invert: bool = False  # white on black

    @staticmethod
    def from_dict(d: dict) -> "LabelSpec":
        lines = [
            Line(
                text=str(ln.get("text", "")),
                font=ln.get("font", fonts.DEFAULT_FONT),
                size_pt=int(ln.get("size_pt", 0) or 0),
                bold=bool(ln.get("bold", False)),
                align=ln.get("align", "center"),
            )
            for ln in (d.get("lines") or [])
        ][:MAX_LINES]
        if not lines:
            lines = [Line()]
        return LabelSpec(
            tape_mm=int(d.get("tape_mm", DEFAULT_TAPE_MM)),
            label_type=d.get("label_type", "text"),
            lines=lines,
            length_mode=d.get("length_mode", "auto"),
            length_mm=float(d.get("length_mm", 40.0)),
            margin_mm=float(d.get("margin_mm", 3.0)),
            code_data=str(d.get("code_data", "")),
            barcode_type=d.get("barcode_type", "code128"),
            show_code_text=bool(d.get("show_code_text", True)),
            invert=bool(d.get("invert", False)),
        )


def _auto_font(line: Line, band_h: int) -> "fonts.ImageFont.FreeTypeFont":
    if line.size_pt > 0:
        px = mm_to_dots(line.size_pt * 25.4 / 72.0)  # pt -> dots at 180dpi
        return fonts.load_font(line.font, max(6, px), line.bold)
    # auto-fit: binary search a size whose ascent+descent ~= usable band height
    target = int(band_h * (1 - 2 * LINE_PAD_FRAC))
    lo, hi, best = 6, 400, 6
    while lo <= hi:
        mid = (lo + hi) // 2
        f = fonts.load_font(line.font, mid, line.bold)
        asc, desc = f.getmetrics()
        if asc + desc <= target:
            best, lo = mid, mid + 1
        else:
            hi = mid - 1
    return fonts.load_font(line.font, best, line.bold)


def _text_block(lines: list[Line], height: int, margin: int, fixed_len: int | None) -> Image.Image:
    n = max(1, len(lines))
    band_h = height // n
    fitted = [(ln, _auto_font(ln, band_h)) for ln in lines]

    # measure widest line to size the block length (auto)
    tmp = Image.new("1", (1, 1), 1)
    d = ImageDraw.Draw(tmp)
    max_w = 1
    for ln, f in fitted:
        if ln.text:
            w = d.textlength(ln.text, font=f)
            max_w = max(max_w, int(w))
    length = fixed_len if fixed_len else max_w + 2 * margin
    length = max(length, 2 * margin + 1)

    img = Image.new("1", (length, height), 1)  # 1 = white
    draw = ImageDraw.Draw(img)
    for i, (ln, f) in enumerate(fitted):
        if not ln.text:
            continue
        band_top = i * band_h
        asc, desc = f.getmetrics()
        y = band_top + (band_h - (asc + desc)) // 2
        w = draw.textlength(ln.text, font=f)
        if ln.align == "left":
            x = margin
        elif ln.align == "right":
            x = length - margin - int(w)
        else:
            x = (length - int(w)) // 2
        draw.text((x, y), ln.text, font=f, fill=0)  # 0 = black
    return img


def _qr_img(data: str, size: int) -> Image.Image:
    qr = qrcode.QRCode(border=1, error_correction=qrcode.constants.ERROR_CORRECT_M)
    qr.add_data(data or " ")
    qr.make(fit=True)
    im = qr.make_image(fill_color="black", back_color="white").convert("1")
    return im.resize((size, size), Image.NEAREST)


def _barcode_img(data: str, symbology: str, height: int, show_text: bool) -> Image.Image:
    try:
        cls = barcode_lib.get_barcode_class(symbology)
    except barcode_lib.errors.BarcodeNotFoundError:
        cls = barcode_lib.get_barcode_class("code128")
    writer = ImageWriter()
    opts = {
        "module_height": max(3.0, height / 180 * 25.4 * 0.7),
        "module_width": 0.25,
        "quiet_zone": 2.0,
        "font_size": 8,
        "text_distance": 3.0,
        "write_text": show_text,
        "dpi": 180,
    }
    try:
        obj = cls(data or "000000000000", writer=writer)
    except Exception:
        obj = barcode_lib.get_barcode_class("code128")(data or "0", writer=writer)
    buf = io.BytesIO()
    obj.write(buf, options=opts)
    buf.seek(0)
    im = Image.open(buf).convert("1")
    # scale to fit tape height, keep aspect
    ratio = height / im.height
    return im.resize((max(1, int(im.width * ratio)), height), Image.NEAREST)


def render(spec: LabelSpec) -> Image.Image:
    t = tape(spec.tape_mm)
    height = t.printable_dots
    margin = mm_to_dots(spec.margin_mm)
    fixed_len = mm_to_dots(min(spec.length_mm, MAX_LENGTH_MM)) if spec.length_mode == "fixed" else None

    if spec.label_type == "text":
        img = _text_block(spec.lines, height, margin, fixed_len)

    elif spec.label_type == "qr":
        qr = _qr_img(spec.code_data or (spec.lines[0].text if spec.lines else " "), height)
        length = fixed_len or (qr.width + 2 * margin)
        img = Image.new("1", (max(length, qr.width + 2 * margin), height), 1)
        img.paste(qr, (margin, 0))
        if spec.show_code_text and spec.lines and spec.lines[0].text:
            # caption to the right of the QR
            cap = _text_block(spec.lines, height, margin, None)
            need = qr.width + 2 * margin + cap.width
            if need > img.width:
                new = Image.new("1", (need, height), 1)
                new.paste(qr, (margin, 0))
                img = new
            img.paste(cap, (qr.width + 2 * margin, 0))

    elif spec.label_type == "barcode":
        bc = _barcode_img(spec.code_data, spec.barcode_type, height, spec.show_code_text)
        length = fixed_len or (bc.width + 2 * margin)
        img = Image.new("1", (max(length, bc.width + 2 * margin), height), 1)
        x = (img.width - bc.width) // 2
        img.paste(bc, (x, 0))

    elif spec.label_type == "text_qr":
        qr = _qr_img(spec.code_data or " ", height)
        cap = _text_block(spec.lines, height, margin, None)
        length = fixed_len or (qr.width + 3 * margin + cap.width)
        img = Image.new("1", (max(length, qr.width + 3 * margin + cap.width), height), 1)
        img.paste(qr, (margin, 0))
        img.paste(cap, (qr.width + 2 * margin, 0))
    else:
        img = _text_block(spec.lines, height, margin, fixed_len)

    if spec.invert:
        from PIL import ImageOps
        img = ImageOps.invert(img.convert("L")).convert("1")
    return img


def to_png_bytes(img: Image.Image, scale: int = 3) -> bytes:
    """Upscaled PNG for on-screen preview (nearest-neighbour keeps dots crisp)."""
    big = img.resize((img.width * scale, img.height * scale), Image.NEAREST)
    buf = io.BytesIO()
    big.convert("L").save(buf, format="PNG")
    return buf.getvalue()
