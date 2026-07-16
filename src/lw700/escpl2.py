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


# 180 dpi: ~7 dots per mm. The thermal head has a leading dead zone, so blank feed
# is printed before the content or the first millimetres clip. ~7 mm (50 dots) is
# the smallest lead that reliably clears it; the auto-cut trims this leader.
# NOTE: extra cuts (an EachPage mid-job cut, or a separate leading-cut job) reliably
# power the LW-700 off, so this uses a single end-cut (EachJob). The 'D' density fix
# alone clears the cold-head leading gaps, so no warm-up strip is needed by default
# (set warmup > 0 to add one). A ~7 mm blank lead clears the head-to-cutter gap.
def encode(img: Image.Image, *, minimal: bool = False, cut: bytes = CUT_EACH_JOB,
           rotate: int = 270, lead: int = 50, trail: int = 24,
           density: int = 4, warmup: int = 0, warmup_page: bool = False) -> bytes:
    """Encode a 1-bit PIL image to ESCPL2 for the LW-700.

    Renderer image is (width=length along tape, height=dots across tape). Each ESC.
    raster line must be one across-tape strip (<=head dots), so the image is rotated
    90 deg and one line is emitted per length position: nL = across-tape dots ('T'),
    number of lines = length ('L').

    The thermal head is cold at the start, so a solid warm-up strip is printed first.
    With warmup_page + EachPage cut it becomes a sacrificial first page that is cut
    off (feed -> cut -> print -> cut), so the visible label starts clean.
    """
    img = img.convert("1")
    if rotate:
        img = img.transpose(Image.ROTATE_90 if rotate == 90 else Image.ROTATE_270)
    width, height = img.size            # width = across-tape dots, height = length
    dots = width                        # 'T' across-tape (nL per line)
    length = height                     # 'L' along-tape (number of lines)
    line_bytes = (dots + 7) // 8
    px = img.load()
    blank = bytes(line_bytes)
    # warm-up uses a checkerboard (0xAA / 0x55 alternating per line) instead of full
    # solid: it heats every head element over two lines but draws ~half the peak
    # current, which avoids the brown-out that a full-solid strip triggers.
    warm_a = bytes([0xAA]) * line_bytes
    warm_b = bytes([0x55]) * line_bytes

    def start_page(page_len: int) -> bytes:
        b = _cmd(0x4C, (page_len & 0xFFFFFFFF).to_bytes(4, "little"))  # 'L' length
        b += _cmd(0x54, (dots & 0xFFFF).to_bytes(2, "little"))        # 'T' width
        if not minimal:
            b += _cmd(0x4F, b"\x00\x00") + _cmd(0x57, b"\x00\x00") + _cmd(0x74, b"\x00\x00\x00")
        return b

    def rline(bs: bytes) -> bytes:
        return _raster_line(bs, dots)

    out = bytearray()
    # --- StartDoc ---
    out += INIT
    if not minimal:
        out += _cmd(0x43, cut)                            # 'C' config (tape-cut mode)
        out += _cmd(0x44, bytes([(density + 5) & 0xFF]))  # 'D' density (param = density+5)
        out += _cmd(0x47)                                 # 'G'
        out += _cmd(0x73, b"\x00")                        # 's'

    inline_warm = 0
    if warmup > 0 and warmup_page:
        # sacrificial warm-up page: prints, then EachPage cut removes it
        out += start_page(warmup)
        for i in range(warmup):
            out += rline(warm_a if i % 2 == 0 else warm_b)
        out += bytes([0x0C])          # EndPage -> cut
    elif warmup > 0:
        inline_warm = warmup          # keep warm-up attached, right before content

    # --- content page ---
    out += start_page(length + lead + trail + inline_warm)
    for _ in range(lead):
        out += rline(blank)
    for i in range(inline_warm):
        out += rline(warm_a if i % 2 == 0 else warm_b)
    for y in range(length):
        line = bytearray(line_bytes)
        for x in range(dots):
            if px[x, y] == 0:  # black pixel -> print
                line[x >> 3] |= 0x80 >> (x & 7)
        out += rline(bytes(line))
    for _ in range(trail):
        out += rline(blank)
    out += bytes([0x0C])          # EndPage -> cut
    out += _cmd(0x40)             # '@' EndDoc
    return bytes(out)
