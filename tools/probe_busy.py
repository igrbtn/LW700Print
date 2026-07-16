#!/usr/bin/env python3
"""Print one medium label, then poll GetLWStatus to find the BUSY indicator.

The batch printer sends the next label's INIT while the previous is still printing,
which resets the head mid-print. To gate that, we need to know which status bit
means "busy printing". This prints a ~70mm label and logs status every 150ms.
Costs one label of tape.
"""
import sys
import os
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import usb.core
import usb.util

from lw700 import render
from lw700.escpl2 import encode

VID, PID = 0x04B8, 0x0705


def read_status(dev):
    try:
        st = bytes(dev.ctrl_transfer(0xC1, 0x01, 0, 0, 64, timeout=800))
        return st.hex()
    except Exception as e:  # noqa: BLE001
        return f"ERR:{e}"


def main():
    dev = usb.core.find(idVendor=VID, idProduct=PID)
    if dev is None:
        print("printer not found"); return
    try:
        dev.set_configuration()
    except usb.core.USBError:
        pass
    print("idle:", read_status(dev))

    spec = render.LabelSpec.from_dict({
        "tape_mm": 18, "label_type": "text", "length_mode": "auto",
        "lines": [{"text": "BUSY-PROBE-1234567890", "size_pt": 0}],
    })
    img = render.render(spec)
    data = encode(img)

    cfg = dev.get_active_configuration()
    intf = next((i for i in cfg if i.bInterfaceClass == 7), cfg[(0, 0)])
    ep = next(e for e in intf
              if usb.util.endpoint_direction(e.bEndpointAddress) == usb.util.ENDPOINT_OUT)
    try:
        usb.util.claim_interface(dev, intf.bInterfaceNumber)
    except usb.core.USBError:
        pass
    t0 = time.time()
    for i in range(0, len(data), 4096):
        ep.write(data[i:i + 4096], timeout=8000)
    print(f"sent {len(data)} bytes at t=0")
    usb.util.release_interface(dev, intf.bInterfaceNumber)

    for _ in range(140):  # ~21s
        t = time.time() - t0
        print(f"t={t:5.2f}  {read_status(dev)}")
        time.sleep(0.15)


if __name__ == "__main__":
    main()
