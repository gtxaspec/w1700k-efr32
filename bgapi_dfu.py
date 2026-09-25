#!/usr/bin/env python3
"""Talk to the W1700K's EFR32MG21 (stock Silabs BGAPI Bluetooth NCP) through ser2net.

  bgapi_dfu.py HOST PORT probe          reset the NCP and print its boot event
  bgapi_dfu.py HOST PORT flash FILE.gbl reboot into the Gecko bootloader's BGAPI UART DFU
                                        mode and upload FILE.gbl (what bt_host_uart_dfu does)

BGAPI frame: byte0 = type(bit7: 1=event) | tech<<3 (Bluetooth = 4 -> 0x20) | len[10:8],
byte1 = len[7:0], byte2 = class, byte3 = command id, then the payload.
"""
import socket
import struct
import sys
import time

BT = 0x20
EVT = 0x80

# class/id pairs
SYSTEM_RESET = (0x01, 0x01)      # cmd: u8 boot mode (0 normal, 1 UART DFU; ignored by newer stacks)
USER_RESET_TO_DFU = (0xFF, 0x02)  # cmd: none; NCP calls bootloader_rebootAndInstall() (BT SDK >= 3.x host tools)
SYSTEM_BOOT_EVT = (0x01, 0x00)
DFU_RESET = (0x00, 0x00)         # cmd: u8 dfu
DFU_BOOT_EVT = (0x00, 0x00)      # evt: u32 bootloader version
DFU_BOOT_FAIL_EVT = (0x00, 0x01)  # evt: u16 reason
DFU_SET_ADDR = (0x00, 0x01)      # cmd: u32 address
DFU_UPLOAD = (0x00, 0x02)        # cmd: uint8array
DFU_FINISH = (0x00, 0x03)        # cmd: none

CHUNK = 48  # bt_host_uart_dfu's packet size; the bootloader's receive buffer is small


class Link:
    def __init__(self, host, port):
        self.s = socket.create_connection((host, port), timeout=5)
        self.buf = b""
        self.skipped = b""

    def drain(self, t=0.3):
        self.s.settimeout(t)
        try:
            while self.s.recv(4096):
                pass
        except socket.timeout:
            pass
        self.buf = b""

    def send(self, cls_id, payload=b""):
        cls, cid = cls_id
        n = len(payload)
        self.s.sendall(bytes([BT | (n >> 8), n & 0xFF, cls, cid]) + payload)

    def recv_msg(self, timeout):
        """Return (is_event, class, id, payload) or None on timeout; skips garbage bytes."""
        end = time.monotonic() + timeout
        while True:
            while len(self.buf) >= 4:
                b0 = self.buf[0]
                if (b0 & 0x78) != BT:  # not a Bluetooth-tech header: resync
                    self.skipped += self.buf[:1]
                    self.buf = self.buf[1:]
                    continue
                n = ((b0 & 0x07) << 8) | self.buf[1]
                if len(self.buf) < 4 + n:
                    break
                msg = (bool(b0 & EVT), self.buf[2], self.buf[3], self.buf[4:4 + n])
                self.buf = self.buf[4 + n:]
                return msg
            left = end - time.monotonic()
            if left <= 0:
                return None
            self.s.settimeout(left)
            try:
                chunk = self.s.recv(4096)
            except socket.timeout:
                return None
            if not chunk:
                raise ConnectionError("ser2net closed the connection")
            self.buf += chunk

    def wait_for(self, want_event, cls_id, timeout):
        end = time.monotonic() + timeout
        while True:
            m = self.recv_msg(max(0.0, end - time.monotonic()))
            if m is None:
                return None
            ev, cls, cid, pl = m
            if (ev, (cls, cid)) == (want_event, cls_id):
                return pl
            if ev and (cls, cid) == DFU_BOOT_FAIL_EVT:
                raise RuntimeError(f"dfu_boot_failure reason=0x{struct.unpack('<H', pl[:2])[0]:04x}")
            print(f"  (ignored {'evt' if ev else 'rsp'} class={cls:#04x} id={cid:#04x} {pl.hex()})")


def show_boot(pl):
    if len(pl) >= 18:
        major, minor, patch, build, btl, hw, h = struct.unpack("<HHHHIHI", pl[:18])
        print(f"system_boot: stack {major}.{minor}.{patch} build {build}, bootloader {btl:#010x}, hw {hw:#06x}, hash {h:#010x}")
    else:
        print(f"system_boot (short): {pl.hex()}")


def probe(link):
    link.drain()
    link.send(SYSTEM_RESET, b"\x00")
    pl = link.wait_for(True, SYSTEM_BOOT_EVT, 3)
    if pl is None:
        print("no BGAPI boot event: wrong baud, wrong firmware, or no link")
        return 1
    show_boot(pl)
    return 0


def flash(link, path):
    img = open(path, "rb").read()
    if img[:4] != b"\xeb\x17\xa6\x03":
        sys.exit(f"{path}: not a GBL file (header tag {img[:4].hex()})")
    link.drain()
    print("rebooting the NCP into its bootloader (user_reset_to_dfu) ...")
    link.skipped = b""
    link.send(USER_RESET_TO_DFU)
    pl = link.wait_for(True, DFU_BOOT_EVT, 5)
    if pl is None:
        # No app answered: the bootloader may already be running (e.g. it refused the last app).
        print("no dfu_boot; asking a running bootloader to re-enter DFU (system_reset 1) ...")
        link.send(SYSTEM_RESET, b"\x01")
        pl = link.wait_for(True, DFU_BOOT_EVT, 5)
    if pl is None:
        # A bootloader that refused the previous app sits in DFU without announcing itself;
        # it still answers DFU commands (flash_set_address below doubles as the probe).
        print("no dfu_boot event; checking whether a bootloader answers DFU commands ...")
    else:
        print(f"dfu_boot: bootloader version {struct.unpack('<I', pl[:4])[0]:#010x}")

    link.send(DFU_SET_ADDR, struct.pack("<I", 0))
    rsp = link.wait_for(False, DFU_SET_ADDR, 3)
    if rsp is None or struct.unpack("<H", rsp[:2])[0]:
        tail = link.skipped + link.buf
        sys.exit(f"flash_set_address failed: {rsp and rsp.hex()}; nothing was written. non-BGAPI bytes: {tail[:200]!r}")

    t0, sent = time.monotonic(), 0
    while sent < len(img):
        part = img[sent:sent + CHUNK]
        link.send(DFU_UPLOAD, bytes([len(part)]) + part)
        rsp = link.wait_for(False, DFU_UPLOAD, 3)
        if rsp is None or struct.unpack("<H", rsp[:2])[0]:
            sys.exit(f"upload failed at offset {sent}: {rsp and rsp.hex()} (bootloader stays in DFU; rerun)")
        sent += len(part)
        if sent % (CHUNK * 256) < CHUNK or sent == len(img):
            print(f"  {sent}/{len(img)} bytes, {sent / (time.monotonic() - t0) / 1024:.1f} KiB/s")

    link.send(DFU_FINISH)
    rsp = link.wait_for(False, DFU_FINISH, 15)
    if rsp is None or struct.unpack("<H", rsp[:2])[0]:
        sys.exit(f"upload_finish rejected the image: {rsp and rsp.hex()} (old app may be gone; bootloader stays in DFU)")
    print("image verified by the bootloader; rebooting into it (system_reset 0)")
    link.skipped = b""
    link.send(SYSTEM_RESET, b"\x00")
    # A refused app brings the bootloader straight back: it announces dfu_boot_failure, then dfu_boot.
    end = time.monotonic() + 4
    while True:
        m = link.recv_msg(max(0.0, end - time.monotonic()))
        if m is None:
            break
        ev, cls, cid, pl = m
        if ev and (cls, cid) == DFU_BOOT_FAIL_EVT:
            sys.exit(f"bootloader REFUSED the app: dfu_boot_failure status {struct.unpack('<H', pl[:2])[0]:#06x}")
        if ev and (cls, cid) == DFU_BOOT_EVT:
            sys.exit(f"bootloader came back (version {struct.unpack('<I', pl[:4])[0]:#010x}) instead of the app")
    print("no bootloader chatter after the reset: the app is running (or silent)")
    return 0


def main():
    host, port, cmd = sys.argv[1], int(sys.argv[2]), sys.argv[3]
    link = Link(host, port)
    if cmd == "probe":
        return probe(link)
    if cmd == "flash":
        return flash(link, sys.argv[4])
    sys.exit(__doc__)


if __name__ == "__main__":
    sys.exit(main())
