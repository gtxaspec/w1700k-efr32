#!/usr/bin/env python3
"""Put the W1700K's EFR32 into its Gecko bootloader from whatever app runs (EZSP, CPC, Spinel).

  enter_bl.py HOST PORT [ezsp|cpc|spinel] [baud]

Uses universal-silabs-flasher's app-specific entry commands. Its final check looks for an
XMODEM bootloader, which Gemtek's BGAPI-DFU bootloader is not, so that failure is expected;
bgapi_dfu.py then talks to the waiting bootloader.
"""
import asyncio
import sys

from universal_silabs_flasher.const import ApplicationType
from universal_silabs_flasher.flasher import FailedToEnterBootloaderError, Flasher

TYPES = {"ezsp": ApplicationType.EZSP, "cpc": ApplicationType.CPC, "spinel": ApplicationType.SPINEL}


async def main():
    host, port = sys.argv[1], sys.argv[2]
    kind = sys.argv[3] if len(sys.argv) > 3 else "ezsp"
    baud = int(sys.argv[4]) if len(sys.argv) > 4 else 115200
    flasher = Flasher(device=f"socket://{host}:{port}", probe_methods=[(TYPES[kind], baud)])
    await flasher.probe_app_type()
    print(f"running app: {flasher.app_type} {flasher.app_version}")
    try:
        await flasher.enter_bootloader()
    except FailedToEnterBootloaderError:
        print("entry command sent; no XMODEM bootloader answered (expected with the BGAPI bootloader)")


asyncio.run(main())
