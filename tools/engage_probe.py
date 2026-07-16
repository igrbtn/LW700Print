#!/usr/bin/env python3
"""Validate the reverse-engineered LW-700 vendor control protocol on the live printer.

Control requests decoded from macOS LWUSBPrintClass plugin (USBClassPluginSub):
  bmRequestType 0xC1 (IN|vendor|interface):
    bRequest 0x01 = GetLWStatus
    bRequest 0x02 = EngageConnect  (enter PC/remote mode)
    bRequest 0x03 = EngageDisconnect
    bRequest 0x04 = EngageStatus
  bmRequestType 0x21 (printer-class) bRequest 0x02 = SoftReset
Read-only probes first; EngageConnect only sets PC mode (what the driver does anyway).
"""
import sys
import usb.core
import usb.util

VID, PID = 0x04B8, 0x0705
dev = usb.core.find(idVendor=VID, idProduct=PID)
if dev is None:
    sys.exit("LW-700 not found on USB")
try:
    dev.set_configuration()
except usb.core.USBError:
    pass
cfg = dev.get_active_configuration()
intf = next((i for i in cfg if i.bInterfaceClass == 7), cfg[(0, 0)])
ifnum = intf.bInterfaceNumber
try:
    usb.util.claim_interface(dev, ifnum)
except usb.core.USBError as e:
    print(f"claim warn: {e}")


def ctrl_in(bReq, wValue, wIndex, length, tag):
    try:
        data = dev.ctrl_transfer(0xC1, bReq, wValue, wIndex, length, timeout=3000)
        print(f"  [{tag}] IN  bReq=0x{bReq:02x} wVal={wValue} wIdx={wIndex} -> {len(data)}B: {bytes(data).hex()}")
        return bytes(data)
    except usb.core.USBError as e:
        print(f"  [{tag}] IN  bReq=0x{bReq:02x} wVal={wValue} wIdx={wIndex} -> ERR {e}")
        return None


print(f"interface={ifnum}")
print("== read-only probes ==")
# try wIndex = 0 and wIndex = interface number, a few lengths
for wIdx in (0, ifnum):
    ctrl_in(0x01, 0, wIdx, 64, f"GetLWStatus wIdx={wIdx}")
    ctrl_in(0x04, 0, wIdx, 8, f"EngageStatus wIdx={wIdx}")

print("== EngageConnect (enter PC/remote mode) ==")
for wIdx in (0, ifnum):
    r = ctrl_in(0x02, 0, wIdx, 3, f"EngageConnect wIdx={wIdx}")
    if r is not None:
        # re-read status to see if state changed
        ctrl_in(0x04, 0, wIdx, 8, f"EngageStatus after wIdx={wIdx}")
        break

usb.util.release_interface(dev, ifnum)
usb.util.dispose_resources(dev)
print("done")
