# W1700K EFR32

Flash and build firmware for the Silicon Labs EFR32MG21 radio inside the Gemtek W1700K running
OpenWrt, through the factory bootloader and ser2net, with no case opening or debugger.

## The radio

- EFR32MG21A010F512 (512 KB flash, 64 KB RAM) on the SoC's second UART, `/dev/ttyS1`
- EFR32 side: USART0, TX PA5, RX PA6, no hardware flow control
- Factory application (HW 2.1): a Silicon Labs BGAPI Bluetooth NCP (stack 6.2.0) that the stock
  firmware does not use
- Factory Gecko bootloader `0x02030002`: BGAPI UART DFU at 115200 (no XMODEM); it boots unsigned
  applications
- 460800 works on OpenWrt builds that carry the Airoha UART divider fix; without it the UART runs
  at half the configured rate (configure 230400 to get 115200)

ser2net on the router (`/etc/config/ser2net`):

```
config proxy 'zigbee'
	option enabled '1'
	option port '6638'
	option protocol 'raw'
	option timeout '0'
	option device '/dev/ttyS1'
	option baudrate '115200'
	option databits '8'
	option parity 'none'
	option stopbits '1'
	option rtscts '0'
	option xonxoff '0'
	option local '1'
	option kickolduser '1'
```

## Flashing

`bgapi_dfu.py HOST 6638 flash FIRMWARE.gbl` uploads a GBL through the factory bootloader. From the
factory Bluetooth NCP it enters DFU with `user_reset_to_dfu`; a bootloader that is already waiting
(for instance after refusing an image) is detected and used. Python standard library only.

`bgapi_dfu.py HOST 6638 probe` resets the factory application and prints its boot event.

Once the radio runs other firmware, return to the bootloader first with
`enter_bl.py HOST 6638 ezsp|cpc|spinel [BAUD]` (needs `universal-silabs-flasher`). It sends the
running application's reboot-to-bootloader command; its closing check looks for an XMODEM
bootloader, so the failure it reports is expected. The bootloader only talks at 115200: set
ser2net back to 115200 before flashing, and to the new firmware's rate afterwards.

Bootloader behaviour worth knowing:

- it restarts only on `system_reset` (class 0x01, id 0x01; mode 0 = application, 1 = DFU);
  `dfu_reset` is silently ignored
- a refused application brings it straight back, announcing `dfu_boot_failure` then `dfu_boot`
- HW 2.1 does not install an unsigned bootloader upgrade (the GBL verifies, then nothing
  changes), so keep the factory one

## Firmware

Builds run in the [silabs-w1700k](https://github.com/hurrian/silabs-w1700k) builder image
(Simplicity SDK 2025.6.1), with the script's directory mounted at `/work`:

```sh
docker run --rm --user root -v "$PWD/rcp:/work" \
    ghcr.io/hurrian/silabs-w1700k:27b92fe64f4a6d22 /work/build-rcp.sh
```

- **Zigbee NCP** (EmberZNet, EZSP for ZHA or zigbee2mqtt): the manifests in silabs-w1700k.
- **Multiprotocol RCP** (`rcp/build-rcp.sh`): Zigbee through zigbeed, Thread through OTBR and
  Bluetooth LE through HCI, all over CPC with CPC security disabled. `BAUD=460800` builds it for
  the faster link. The host side is
  [silabs-multipan-ha-addon](https://github.com/gtxaspec/silabs-multipan-ha-addon).
- **UART test** (`uart-test/`): prints `TICK` lines at `BAUD` and echoes input, then returns to the
  bootloader on `B` or after 90 s, so trying a rate the host cannot reach costs nothing.

With the multiprotocol RCP, cap Bluetooth LE scanning: BlueZ scans at 100 % duty (an 11.25 ms
window every 11.25 ms), which leaves the radio no time to receive 802.15.4. At 25 % both Thread
and Bluetooth scans see their devices; the add-on applies that cap by default.
