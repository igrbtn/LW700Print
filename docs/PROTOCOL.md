# Epson LabelWorks LW-700 USB protocol notes

Reverse-engineered notes on how to drive the Epson LabelWorks **LW-700** directly
over USB, so it can be used without Epson's driver stack. Reconstructed from the
publicly shipped macOS filter/plugin behaviour and validated against real hardware.
No proprietary Epson binaries are included in this repository.

## Device

- USB `VID 0x04B8` (Seiko Epson) / `PID 0x0705`, printer-class interface 0.
- Bulk **OUT `0x02`**, bulk **IN `0x81`**.
- IEEE-1284 device ID: `MFG:EPSON;CMD:ESCPL2;MDL:LW-700;CLS:PRINTER;` -> language **ESCPL2**.
- The printer auto-powers-off when idle (drops off the USB bus). Turn it on and set
  "PC connection" mode on the device before printing.

## Printing is just a bulk write

The LW-700 does **not** need any vendor "engage / enter remote" handshake (those
vendor requests exist for sibling models and STALL on the LW-700). To print:

```
claim interface 0  ->  bulk-write the ESCPL2 stream to endpoint 0x02
```

### Control requests the LW-700 does implement (optional, for status)

| bmRequestType | bRequest | meaning | example reply |
|---------------|----------|---------|---------------|
| `0xC1` (IN, vendor, interface) | `0x01` | GetLWStatus | `08 00 00 04 00 00 00 00` (idle) |
| `0xA1` (IN, printer class)     | `0x01` | Get port status | `0x38` (ready) |
| `0xA1` (IN, printer class)     | `0x00` | Get IEEE-1284 device ID | see above |

The GetLWStatus reply byte 1 goes non-zero (`0x02`/`0x05`) while the printer is busy
and returns to `0x00` when idle. Vendor requests `0x02`/`0x03`/`0x04`
(EngageConnect/Disconnect/Status) STALL on the LW-700 and are not needed.

## ESCPL2 stream format

Two command families plus the print job envelope.

### Control command (`ESC {`)

```
1B 7B <N> <cmd> <params...> <cksum> 7D
```
- `N`     = number of bytes from `<cmd>` through the closing `}` inclusive
          = `len(cmd) + len(params) + 1 (cksum) + 1 ('}')`.
- `cksum` = `(cmd + sum(params)) & 0xFF`.

### Raster line (`ESC .`)

```
1B 2E 00 00 00 01 <nL> <nH> <data...>
```
- `nL,nH` = number of dots on this line (little-endian) = tape width in dots.
- `data`  = `(dots + 7) // 8` bytes, MSB = first dot. **Each raster line is one
  across-the-tape strip**; you emit one line per position along the tape length.
- Keep `dots` within the print head width (LW-700 ~112-128 dots at 180 dpi).

### Job sequence

```
StartDoc : '{'(init sig)  'C'(config)  'D'(density)  'G'  's'
StartPage: 'L'(length)    'T'(width)   'O'  'W'  't'
raster   : ESC . line  x  (number of dots along the tape length)
EndPage  : 0x0C   (form feed)
EndDoc   : '@'
```

Notable commands:

| cmd | byte | params | meaning |
|-----|------|--------|---------|
| init | `{` 0x7B | fixed `1B 7B 07 7B 00 00 53 54 22 7D` | job signature ("ST") |
| length | `L` 0x4C | u32 LE | tape length in dots (along feed) |
| width  | `T` 0x54 | u16 LE | tape width in dots (across, = raster `dots`) |
| config | `C` 0x43 | 4 bytes | cut mode etc. (see below) |
| end    | `@` 0x40 | none    | end of document |

### Tape cut (`C` command params)

The 4 `C` params encode the cut mode:

| mode | bytes |
|------|-------|
| no cut | `00 00 00 00` |
| cut each job | `02 00 01 01` |
| cut each page | `02 02 01 01` |

## Practical notes

- The physical head starts a few mm in; emit a short run of blank raster lines
  (leading feed, ~40-50 lines at 180 dpi) before the content so the first column is
  not clipped, and a few trailing blank lines. Epson's own driver feeds ~1 cm, cuts,
  prints, then cuts again.
- Rotate the rendered bitmap 90 deg so that image rows become across-the-tape strips
  (the raster `dots` axis must be the tape width, <= head width).

This documentation is an independent interoperability description of an observed
protocol. It contains no Epson source code or binaries.
