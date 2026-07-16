#!/usr/bin/env python3
"""Map which vendor/class control requests the LW-700 actually supports (live)."""
import sys
import usb.core, usb.util

VID, PID = 0x04B8, 0x0705
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
try:
    usb.util.claim_interface(dev, ifnum)
except usb.core.USBError:
    pass


def tin(bmRT, bReq, wV, wI, ln, tag):
    try:
        d = bytes(dev.ctrl_transfer(bmRT, bReq, wV, wI, ln, timeout=2000))
        print(f"  OK  {tag:24s} bmRT=0x{bmRT:02x} bReq=0x{bReq:02x} -> {len(d)}B {d.hex()}")
    except usb.core.USBError as e:
        print(f"  --  {tag:24s} bmRT=0x{bmRT:02x} bReq=0x{bReq:02x} -> {e}")


print(f"interface={ifnum}, endpoints:",
      [hex(e.bEndpointAddress) for e in intf])
# vendor IN 0xC1
tin(0xC1, 0x01, 0, 0, 64, "GetLWStatus")
tin(0xC1, 0x02, 0, 0, 3, "EngageConnect")
tin(0xC1, 0x03, 0, 0, 3, "EngageDisconnect")
tin(0xC1, 0x04, 0, 0, 8, "EngageStatus")
# printer class IN: GET_PORT_STATUS (bmRT 0xA1, bReq 1)
tin(0xA1, 0x01, 0, ifnum, 1, "PClass GetPortStatus")
# printer class: GET_DEVICE_ID (bmRT 0xA1, bReq 0)
tin(0xA1, 0x00, 0, ifnum << 8, 255, "PClass GetDeviceID")
# vendor: try a few other bRequests to see what's implemented
for br in (0x00, 0x05, 0x06, 0x10, 0x20):
    tin(0xC1, br, 0, 0, 8, f"vendorIN bReq0x{br:02x}")

usb.util.release_interface(dev, ifnum)
usb.util.dispose_resources(dev)
print("done")
