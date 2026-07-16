"""ESCPL2 encoder for LW-700, reconstructed from the macOS rastertolw ESCPCommand class.

Command format (ESC {):  1b 7b <N> <cmd> <params...> <cksum> 7d
  N     = len(cmd+params) + 2   (bytes from cmd through '}' inclusive)
  cksum = (cmd + sum(params)) & 0xff
Raster line (ESC .):     1b 2e 00 00 00 01 <nL> <nH> <data>
  nL,nH = dot count (LE) per line = tape-width dots; data = (dots+7)//8 bytes.

Print sequence (from doStartDoc/doStartPage/doSendRasterData/doEndPage/doEndDoc):
  StartDoc: '{'(ST) 'C' 'D' 'G' 's'
  StartPage: 'L'(length) 'T'(width) 'O' 'W' 't'
  raster lines x N
  EndPage: 0x0c
  EndDoc: '@'
Config params ('C','D','s','O','W','t') come from CUPS EPLW* options; v0 uses
conservative defaults and can be tuned against the live printer.
"""
from __future__ import annotations

from PIL import Image


def _cmd(c: int, params: bytes = b"") -> bytes:
    body = bytes([c]) + params
    n = len(body) + 2  # + cksum + '}'
    cksum = (c + sum(params)) & 0xFF
    return bytes([0x1B, 0x7B, n]) + body + bytes([cksum, 0x7D])


# '{' init/signature command is special: 1b 7b 07 7b 00 00 53 54 22 7d
INIT = bytes([0x1B, 0x7B, 0x07, 0x7B, 0x00, 0x00, 0x53, 0x54, 0x22, 0x7D])


def _raster_line(col_bits: bytes, dots: int) -> bytes:
    return bytes([0x1B, 0x2E, 0x00, 0x00, 0x00, 0x01, dots & 0xFF, (dots >> 8) & 0xFF]) + col_bits


# 'C' config param (UIParam[3..6]) tape-cut modes, from the option parser:
CUT_NONE = b"\x00\x00\x00\x00"
CUT_EACH_JOB = b"\x02\x00\x01\x01"   # dword 0x1010002
CUT_EACH_PAGE = b"\x02\x02\x01\x01"  # dword 0x1010202


# 180 dpi: ~21 dots = 3 mm. Small lead so the head's dead zone clears; the auto-cut
# trims the leading feed, leaving a clean ~2-3 mm margin.
def encode(img: Image.Image, *, minimal: bool = False, cut: bytes = CUT_EACH_JOB,
           rotate: int = 270, lead: int = 18, trail: int = 18) -> bytes:
    """Encode a 1-bit PIL image to ESCPL2 for the LW-700.

    Renderer image is (width=length along tape, height=dots across tape). Each ESC.
    raster line must be one across-tape strip (<=head dots), so the image is rotated
    90 deg and one line is emitted per length position: nL = across-tape dots ('T'),
    number of lines = length ('L').
    """
    img = img.convert("1")
    if rotate:
        img = img.transpose(Image.ROTATE_90 if rotate == 90 else Image.ROTATE_270)
    width, height = img.size            # width = across-tape dots, height = length
    dots = width                        # 'T' across-tape (nL per line)
    length = height                     # 'L' along-tape (number of lines)
    line_bytes = (dots + 7) // 8
    px = img.load()

    out = bytearray()
    # --- StartDoc ---
    out += INIT
    if not minimal:
        out += _cmd(0x43, cut)                   # 'C' config (tape-cut mode)
        out += _cmd(0x44, b"\x00")               # 'D' density
        out += _cmd(0x47)                        # 'G'
        out += _cmd(0x73, b"\x00")               # 's'
    total_len = length + lead + trail
    blank = bytes(line_bytes)
    # --- StartPage ---
    out += _cmd(0x4C, (total_len & 0xFFFFFFFF).to_bytes(4, "little"))  # 'L' length
    out += _cmd(0x54, (dots & 0xFFFF).to_bytes(2, "little"))           # 'T' width
    if not minimal:
        out += _cmd(0x4F, b"\x00\x00")           # 'O' tape kind
        out += _cmd(0x57, b"\x00\x00")           # 'W'
        out += _cmd(0x74, b"\x00\x00\x00")       # 't' tape color
    # --- raster: leading blank feed, content, trailing blank feed ---
    for _ in range(lead):
        out += _raster_line(blank, dots)
    for y in range(length):
        line = bytearray(line_bytes)
        for x in range(dots):
            if px[x, y] == 0:  # black pixel -> print
                line[x >> 3] |= 0x80 >> (x & 7)
        out += _raster_line(bytes(line), dots)
    for _ in range(trail):
        out += _raster_line(blank, dots)
    # --- EndPage / EndDoc ---
    out += bytes([0x0C])          # form feed
    out += _cmd(0x40)             # '@' end
    return bytes(out)
