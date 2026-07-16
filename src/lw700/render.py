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

import math

Align = Literal["left", "center", "right"]
LabelType = Literal["text", "qr", "barcode", "text_qr",
                    "cable_flag", "cable_wrap", "patch_panel"]

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
    margin_mm: float = 0.0
    # barcode / qr
    code_data: str = ""
    barcode_type: str = "code128"
    show_code_text: bool = True
    invert: bool = False  # white on black
    line_spacing: float = 0.0   # inter-line gap as fraction of each line's band (0 = tight)
    # professional / cable labelling
    cable_diameter_mm: float = 5.0   # for cable_flag/wrap: wrap length = pi * diameter
    wrap_mm: float = 0.0             # explicit middle wrap length (overrides diameter if > 0)
    flag_mirror: bool = True         # cable_flag: rotate the 2nd face 180 so both read upright
    repeat: int = 4                 # cable_wrap: number of text repeats along the length
    ports: int = 12                 # patch_panel: number of ports
    port_pitch_mm: float = 0.0      # patch_panel: centre-to-centre pitch (0 => auto by length)

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
            margin_mm=float(d.get("margin_mm", 0.0)),
            code_data=str(d.get("code_data", "")),
            barcode_type=d.get("barcode_type", "code128"),
            show_code_text=bool(d.get("show_code_text", True)),
            invert=bool(d.get("invert", False)),
            line_spacing=float(d.get("line_spacing", 0.0)),
            cable_diameter_mm=float(d.get("cable_diameter_mm", 5.0)),
            wrap_mm=float(d.get("wrap_mm", 0.0)),
            flag_mirror=bool(d.get("flag_mirror", True)),
            repeat=int(d.get("repeat", 4)),
            ports=int(d.get("ports", 12)),
            port_pitch_mm=float(d.get("port_pitch_mm", 0.0)),
        )


def _auto_font(line: Line, band_h: int, pad: float = LINE_PAD_FRAC) -> "fonts.ImageFont.FreeTypeFont":
    if line.size_pt > 0:
        px = mm_to_dots(line.size_pt * 25.4 / 72.0)  # pt -> dots at 180dpi
        return fonts.load_font(line.font, max(6, px), line.bold)
    # auto-fit: binary search a size whose ascent+descent ~= usable band height
    target = int(band_h * (1 - 2 * pad))
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


def _text_block(lines: list[Line], height: int, margin: int, fixed_len: int | None,
                pad: float = LINE_PAD_FRAC) -> Image.Image:
    n = max(1, len(lines))
    band_h = height // n
    fitted = [(ln, _auto_font(ln, band_h, pad)) for ln in lines]

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
        img = _text_block(spec.lines, height, margin, fixed_len, spec.line_spacing / 2)

    elif spec.label_type == "qr":
        qr = _qr_img(spec.code_data or (spec.lines[0].text if spec.lines else " "), height)
        length = fixed_len or (qr.width + 2 * margin)
        img = Image.new("1", (max(length, qr.width + 2 * margin), height), 1)
        img.paste(qr, (margin, 0))
        if spec.show_code_text and spec.lines and spec.lines[0].text:
            # caption to the right of the QR
            cap = _text_block(spec.lines, height, margin, None, spec.line_spacing / 2)
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
        cap = _text_block(spec.lines, height, margin, None, spec.line_spacing / 2)
        length = fixed_len or (qr.width + 3 * margin + cap.width)
        img = Image.new("1", (max(length, qr.width + 3 * margin + cap.width), height), 1)
        img.paste(qr, (margin, 0))
        img.paste(cap, (qr.width + 2 * margin, 0))

    elif spec.label_type == "cable_flag":
        img = _cable_flag(spec, height, margin)
    elif spec.label_type == "cable_wrap":
        img = _cable_wrap(spec, height, margin)
    elif spec.label_type == "patch_panel":
        img = _patch_panel(spec, height, margin)
    else:
        img = _text_block(spec.lines, height, margin, fixed_len, spec.line_spacing / 2)

    if spec.invert:
        from PIL import ImageOps
        img = ImageOps.invert(img.convert("L")).convert("1")
    return img


def _wrap_dots(spec: "LabelSpec") -> int:
    """Middle wrap length in dots = explicit wrap_mm, else cable circumference."""
    mm = spec.wrap_mm if spec.wrap_mm > 0 else math.pi * spec.cable_diameter_mm
    return mm_to_dots(mm)


def _cable_flag(spec: "LabelSpec", height: int, margin: int) -> Image.Image:
    """Cable flag: text near BOTH ends, blank middle wraps the cable; when the two
    ends fold together they form a two-sided flag. The 2nd face is rotated 180 deg
    (flag_mirror) so both faces read upright once folded."""
    text = _text_block(spec.lines, height, margin, None, spec.line_spacing / 2)
    wrap = _wrap_dots(spec)
    total = text.width * 2 + wrap
    img = Image.new("1", (total, height), 1)
    img.paste(text, (0, 0))                                  # left flag (near left end)
    right = text.rotate(180) if spec.flag_mirror else text
    img.paste(right, (total - right.width, 0))               # right flag (near right end)
    # centering stripe: dashed vertical line at the fold centre (cable axis)
    draw = ImageDraw.Draw(img)
    cx = total // 2
    for y in range(0, height, 6):
        draw.line([(cx, y), (cx, min(y + 3, height - 1))], fill=0, width=2)
    return img


def _cable_wrap(spec: "LabelSpec", height: int, margin: int) -> Image.Image:
    """Self-laminating cable wrap: the text is repeated along the length so at least
    one copy is readable after the label is wound around the cable."""
    block = _text_block(spec.lines, height, margin, None, spec.line_spacing / 2)
    n = max(1, spec.repeat)
    gap = margin
    total = block.width * n + gap * (n - 1)
    img = Image.new("1", (total, height), 1)
    for i in range(n):
        img.paste(block, (i * (block.width + gap), 0))
    return img


def _patch_panel(spec: "LabelSpec", height: int, margin: int) -> Image.Image:
    """Patch-panel strip: one cell per port at a fixed pitch, each cell labelled from
    the corresponding line (or auto-numbered 1..ports if a single line is given)."""
    ports = max(1, spec.ports)
    if spec.port_pitch_mm > 0:
        pitch = mm_to_dots(spec.port_pitch_mm)
    elif spec.length_mode == "fixed":
        pitch = max(1, mm_to_dots(spec.length_mm) // ports)
    else:
        pitch = mm_to_dots(12.0)  # sensible default cell width
    # per-port text: explicit lines, else auto-number
    texts = [ln.text for ln in spec.lines if ln.text]
    base = spec.lines[0] if spec.lines else Line()
    img = Image.new("1", (pitch * ports, height), 1)
    draw = ImageDraw.Draw(img)
    for i in range(ports):
        label = texts[i] if i < len(texts) else str(i + 1)
        cell = _text_block([Line(text=label, font=base.font, bold=base.bold,
                                 align="center")], height, margin, pitch)
        img.paste(cell, (i * pitch, 0))
        if i:  # divider line between ports
            draw.line([(i * pitch, 0), (i * pitch, height - 1)], fill=0)
    return img


MARGIN_DOTS = 64  # ~9 mm head-to-cutter dead zone (per end)


def to_png_bytes(img: Image.Image, scale: int = 3, show_margins: bool = True) -> bytes:
    """Upscaled PNG for on-screen preview (nearest-neighbour keeps dots crisp).

    When show_margins is set, the ~9 mm unprintable dead zones the printer adds on
    both ends are drawn as grey bands so the physical label is represented truthfully.
    """
    big = img.resize((img.width * scale, img.height * scale), Image.NEAREST).convert("L")
    if show_margins:
        m = MARGIN_DOTS * scale
        canvas = Image.new("L", (big.width + 2 * m, big.height), 255)
        canvas.paste(big, (m, 0))
        band = Image.new("L", (m, big.height), 0xCC)  # light grey dead-zone band
        canvas.paste(band, (0, 0))
        canvas.paste(band, (big.width + m, 0))
        big = canvas
    buf = io.BytesIO()
    big.save(buf, format="PNG")
    return buf.getvalue()
