"""Print backends behind one interface.

PreviewBackend works today (renders PNG to output/). USBBackend is wired for the
moment the ESCPL2 protocol is decoded from the reference capture - until then its
`print_label` raises NotReady, and the app falls back to preview.

Tape auto-detection: presence of the printer is detectable now via pyusb; the
actual loaded tape WIDTH is only readable once the enter-remote/status handshake
is decoded. `detect_status()` returns what we can know today.
"""
from __future__ import annotations

import itertools
import os
import time
from dataclasses import dataclass

from PIL import Image

VID, PID = 0x04B8, 0x0705


class NotReady(RuntimeError):
    pass


@dataclass
class PrinterStatus:
    connected: bool
    tape_mm: int | None  # None until the status handshake is decoded
    detail: str
    media_ok: bool | None = None   # tentative: tape present / no error
    raw: str = ""                  # raw status bytes for debugging


# GetLWStatus (0xC1,0x01) byte[3] encodes the loaded tape width.
# Confirmed on hardware: 0x03 -> 12mm, 0x04 -> 18mm. Others assumed sequential;
# refine as more tapes are tested.
TAPE_CODE_MM = {0x01: 6, 0x02: 9, 0x03: 12, 0x04: 18, 0x05: 24}


def detect_status() -> PrinterStatus:
    try:
        import usb.core
    except ImportError:
        return PrinterStatus(False, None, "pyusb not installed")
    try:
        dev = usb.core.find(idVendor=VID, idProduct=PID)
    except Exception as e:  # noqa: BLE001 - libusb backend issues surface here
        return PrinterStatus(False, None, f"usb error: {e}")
    if dev is None:
        return PrinterStatus(False, None, "LW-700 not found on USB")
    tape_mm = None
    media_ok = None
    detail = "LW-700 connected"
    raw = ""
    try:
        st = bytes(dev.ctrl_transfer(0xC1, 0x01, 0, 0, 64, timeout=1500))
        raw = st.hex()
        if len(st) > 3:
            code = st[3]
            tape_mm = TAPE_CODE_MM.get(code)
            # tape code 0 => no cassette / no tape (tentative)
            media_ok = code != 0
            if tape_mm:
                detail = f"LW-700 connected, tape {tape_mm}mm"
            elif code == 0:
                detail = "LW-700 connected, NO TAPE / cover open"
            else:
                detail = f"LW-700 connected, tape code 0x{code:02x}"
    except Exception:  # noqa: BLE001 - status read is best-effort
        pass
    return PrinterStatus(True, tape_mm, detail, media_ok, raw)


class PrinterBackend:
    name = "base"

    def print_label(self, img: Image.Image, *, tape_mm: int, cut: bool = True) -> str:
        raise NotImplementedError


class PreviewBackend(PrinterBackend):
    """Saves the exact print bitmap to output/ as PNG. Always available."""
    name = "preview"

    _counter = itertools.count(1)

    def __init__(self, out_dir: str):
        self.out_dir = out_dir
        os.makedirs(out_dir, exist_ok=True)

    def print_label(self, img: Image.Image, *, tape_mm: int, cut: bool = True) -> str:
        ts = time.strftime("%Y%m%d-%H%M%S")
        seq = next(PreviewBackend._counter)
        path = os.path.join(self.out_dir, f"label_{tape_mm}mm_{ts}_{seq:03d}.png")
        scale = 4
        big = img.resize((img.width * scale, img.height * scale), Image.NEAREST)
        big.convert("L").save(path)
        return f"preview saved: {path}"


class USBBackend(PrinterBackend):
    """Direct USB print via the reverse-engineered ESCPL2 protocol (no Epson stack).

    Sequence: claim interface 0 -> bulk-write ESCPL2 to EP 0x02. The printer must be
    powered on and in PC-connection mode. LW-700 auto-powers-off when idle, so we
    retry finding the device briefly.
    """
    name = "usb"

    def print_label(self, img: Image.Image, *, tape_mm: int, cut: bool = True) -> str:
        import time

        import usb.core
        import usb.util

        from .escpl2 import CUT_EACH_JOB, CUT_NONE, encode

        data = encode(img, cut=CUT_EACH_JOB if cut else CUT_NONE)

        dev = None
        for _ in range(10):
            dev = usb.core.find(idVendor=VID, idProduct=PID)
            if dev is not None:
                break
            time.sleep(0.5)
        if dev is None:
            raise NotReady("LW-700 not found on USB (powered off / disconnected?)")
        try:
            dev.set_configuration()
        except usb.core.USBError:
            pass
        cfg = dev.get_active_configuration()
        intf = next((i for i in cfg if i.bInterfaceClass == 7), cfg[(0, 0)])
        ep_out = next(e for e in intf
                      if usb.util.endpoint_direction(e.bEndpointAddress) == usb.util.ENDPOINT_OUT)
        try:
            usb.util.claim_interface(dev, intf.bInterfaceNumber)
        except usb.core.USBError:
            pass
        written = 0
        try:
            for i in range(0, len(data), 4096):
                written += ep_out.write(data[i:i + 4096], timeout=8000)
        finally:
            usb.util.release_interface(dev, intf.bInterfaceNumber)
            usb.util.dispose_resources(dev)
        return f"printed {tape_mm}mm label ({written} bytes ESCPL2)"


def cut_tape() -> str:
    """Manual cut: print a tiny real label with the normal job structure, then cut.

    Bare/short jobs power the printer off; only a full-structure print (standard lead,
    density, single end-cut) is safe, so encode a tiny mark image the normal way.
    """
    import time

    from PIL import Image

    import usb.core
    import usb.util

    from .escpl2 import encode

    # image is (width = length along tape, height = tape dots); keep it short
    img = Image.new("1", (10, 76), 1)
    for y in range(30, 46):
        img.putpixel((4, y), 0)           # a short mark so the print is a valid job
    out = encode(img)                     # normal structure: lead/trail + single cut

    dev = None
    for _ in range(6):
        dev = usb.core.find(idVendor=VID, idProduct=PID)
        if dev is not None:
            break
        time.sleep(0.5)
    if dev is None:
        raise NotReady("LW-700 not found")
    try:
        dev.set_configuration()
    except usb.core.USBError:
        pass
    cfg = dev.get_active_configuration()
    intf = next((i for i in cfg if i.bInterfaceClass == 7), cfg[(0, 0)])
    ep = next(e for e in intf
              if usb.util.endpoint_direction(e.bEndpointAddress) == usb.util.ENDPOINT_OUT)
    try:
        usb.util.claim_interface(dev, intf.bInterfaceNumber)
    except usb.core.USBError:
        pass
    try:
        ep.write(bytes(out), timeout=8000)
    finally:
        usb.util.release_interface(dev, intf.bInterfaceNumber)
        usb.util.dispose_resources(dev)
    return "cut sent"


# LW-700 prints/feeds at roughly this speed; used to wait out one label before the
# next INIT is sent in a batch (a mid-print INIT resets the head -> feed jump + tail clip).
# Deliberately conservative (under-estimating speed = waiting a little longer) because
# a mid-print INIT corrupts the label, while a few extra idle seconds are harmless
# (auto-power-off is minutes away). Calibrate with tools/probe_busy.py.
PRINT_SPEED_MM_S = 8.0
CUT_SECONDS = 2.0
LEAD_TRAIL_DOTS = 128  # lead+trail blank feed added by the encoder (~18 mm)


def feed_seconds(length_dots: int) -> float:
    """Estimated seconds to print+feed+cut one label of the given along-tape length."""
    mm = (length_dots + LEAD_TRAIL_DOTS) / 180 * 25.4
    return mm / PRINT_SPEED_MM_S + CUT_SECONDS


def print_labels_usb(jobs, *, should_stop=None, on_result=None, wait: bool = True):
    """Print several labels over ONE USB connection (claim the interface once).

    Per-label claim/release/dispose churn leaves the bulk pipe in a dirty state on
    macOS - the first label prints clean, later (long) labels drop columns. Holding a
    single persistent pipe for the whole batch and waiting for each label to finish
    before the next INIT fixes the corruption seen on cable-flag batches.

    jobs: list of (PIL.Image, tape_mm). Returns a list of per-label result strings.
    Raises NotReady if the printer can't be opened (caller falls back to preview).
    """
    import time

    import usb.core
    import usb.util

    from .escpl2 import CUT_EACH_JOB, encode

    dev = None
    for _ in range(10):
        dev = usb.core.find(idVendor=VID, idProduct=PID)
        if dev is not None:
            break
        time.sleep(0.5)
    if dev is None:
        raise NotReady("LW-700 not found on USB (powered off / disconnected?)")
    try:
        dev.set_configuration()
    except usb.core.USBError:
        pass
    cfg = dev.get_active_configuration()
    intf = next((i for i in cfg if i.bInterfaceClass == 7), cfg[(0, 0)])
    ep = next(e for e in intf
              if usb.util.endpoint_direction(e.bEndpointAddress) == usb.util.ENDPOINT_OUT)
    try:
        usb.util.claim_interface(dev, intf.bInterfaceNumber)
    except usb.core.USBError:
        pass

    results = []
    n = len(jobs)
    try:
        for i, (img, tape_mm) in enumerate(jobs):
            if should_stop and should_stop():
                results.append(f"STOPPED after {i}")
                break
            data = encode(img, cut=CUT_EACH_JOB)
            written = 0
            for k in range(0, len(data), 4096):
                written += ep.write(data[k:k + 4096], timeout=15000)
            msg = f"printed {tape_mm}mm label ({written} bytes ESCPL2)"
            results.append(msg)
            if on_result:
                on_result(i, msg)
            if wait and i < n - 1:
                time.sleep(feed_seconds(img.width))  # let this label finish before next INIT
    finally:
        usb.util.release_interface(dev, intf.bInterfaceNumber)
        usb.util.dispose_resources(dev)
    return results


def get_backend(prefer_usb: bool, out_dir: str) -> PrinterBackend:
    if prefer_usb and detect_status().connected:
        return USBBackend()
    return PreviewBackend(out_dir)
