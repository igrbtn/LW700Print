#!/usr/bin/env python3
"""v0 direct USB print test: render -> ESCPL2 -> bulk-write to the live LW-700."""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import usb.core
import usb.util
from lw700 import render
from lw700.escpl2 import encode

VID, PID = 0x04B8, 0x0705

# short test label on 18mm tape
spec = render.LabelSpec.from_dict({
    "tape_mm": 18, "label_type": "text",
    "lines": [{"text": "Ok", "align": "center"}],
    "length_mode": "fixed", "length_mm": 25, "margin_mm": 2,
})
img = render.render(spec)
print(f"image {img.size} (WxH)")
minimal = "--full" not in sys.argv
data = encode(img, minimal=minimal)
print(f"ESCPL2 {len(data)} bytes, minimal={minimal}")
print("head:", data[:40].hex())

dev = usb.core.find(idVendor=VID, idProduct=PID)
if dev is None:
    sys.exit("LW-700 not found")
try:
    dev.set_configuration()
except usb.core.USBError:
    pass
cfg = dev.get_active_configuration()
intf = next((i for i in cfg if i.bInterfaceClass == 7), cfg[(0, 0)])
ifnum = intf.bInterfaceNumber
ep_out = next(e for e in intf if usb.util.endpoint_direction(e.bEndpointAddress) == usb.util.ENDPOINT_OUT)
try:
    usb.util.claim_interface(dev, ifnum)
except usb.core.USBError:
    pass


def status():
    try:
        return bytes(dev.ctrl_transfer(0xC1, 0x01, 0, 0, 64, timeout=2000)).hex()
    except usb.core.USBError as e:
        return f"ERR {e}"


print("status before:", status())
if "--dry" in sys.argv:
    print("(dry run, not writing)")
    sys.exit(0)

total = 0
try:
    for i in range(0, len(data), 4096):
        total += ep_out.write(data[i:i + 4096], timeout=8000)
    print(f"wrote {total} bytes to EP 0x{ep_out.bEndpointAddress:02x}")
except usb.core.USBError as e:
    print(f"bulk write error after {total}B: {e}")

time.sleep(1.5)
print("status after:", status())
usb.util.release_interface(dev, ifnum)
usb.util.dispose_resources(dev)
print("done - check if tape ejected")
