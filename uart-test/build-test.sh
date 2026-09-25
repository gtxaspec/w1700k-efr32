#!/bin/bash
set -euo pipefail
SDK=/simplicity_sdk_2025.6.1; DEV=EFR32MG21A010F512IM32; BAUD=${BAUD:-460800}
TC=$(ls -d /opt/arm-gnu-toolchain-*arm-none-eabi)
W=/work/src; OUT=/work/build-$BAUD
rm -rf "$W" "$OUT"; cp -r $SDK/app/common/example/iostream_usart_baremetal "$W"
cp /work/app_iostream_usart.c "$W/app_iostream_usart.c"
sed -i 's/^  - id: iostream_retarget_stdio$/  - id: iostream_retarget_stdio\n  - id: sleeptimer\n  - id: bootloader_interface/' "$W/iostream_usart_baremetal.slcp"
slc signature trust --sdk $SDK >/dev/null
slc generate --with $DEV --project-file "$W/iostream_usart_baremetal.slcp" --export-destination "$OUT" \
  --copy-proj-sources --new-project --toolchain toolchain_gcc --sdk $SDK --output-type makefile >/work/slc.log 2>&1 || { tail -20 /work/slc.log; exit 1; }
setdef() { local f="$OUT/config/$1"; grep -qE "^\s*(//\s*)?#define\s+$2\b" "$f" || { echo "!! $2 not in $1"; return 1; }; sed -i -E "s|^\s*(//\s*)?#define\s+$2\b.*|#define $2 $3|" "$f"; }
V=sl_iostream_usart_vcom_config.h
setdef $V SL_IOSTREAM_USART_VCOM_BAUDRATE $BAUD
setdef $V SL_IOSTREAM_USART_VCOM_FLOW_CONTROL_TYPE usartHwFlowControlNone
setdef $V SL_IOSTREAM_USART_VCOM_PERIPHERAL USART0
setdef $V SL_IOSTREAM_USART_VCOM_PERIPHERAL_NO 0
setdef $V SL_IOSTREAM_USART_VCOM_TX_PORT gpioPortA
setdef $V SL_IOSTREAM_USART_VCOM_TX_PIN 5
setdef $V SL_IOSTREAM_USART_VCOM_RX_PORT gpioPortA
setdef $V SL_IOSTREAM_USART_VCOM_RX_PIN 6
sed -i -E '/#define SL_IOSTREAM_USART_VCOM_(CTS|RTS)_(PORT|PIN)\b/d' "$OUT/config/$V"
[ -f "$OUT/config/sl_board_control_config.h" ] && setdef sl_board_control_config.h SL_BOARD_ENABLE_VCOM 0 || true
C=sl_clock_manager_oscillator_config.h; [ -f "$OUT/config/$C" ] && { setdef $C SL_CLOCK_MANAGER_HFXO_EN 1; setdef $C SL_CLOCK_MANAGER_HFXO_CTUNE 128 || true; }
C2=sl_clock_manager_tree_config.h; [ -f "$OUT/config/$C2" ] && setdef $C2 SL_CLOCK_MANAGER_DEFAULT_HF_CLOCK_SOURCE SL_CLOCK_MANAGER_DEFAULT_HF_CLOCK_SOURCE_HFXO || true
grep -nE "#define SL_IOSTREAM_USART_VCOM_(BAUD|FLOW|PERIPH|TX_|RX_|CTS|RTS)" "$OUT/config/$V"
make -C "$OUT" -f iostream_usart_baremetal.Makefile -j"$(nproc)" ARM_GCC_DIR="$TC" >/work/make.log 2>&1 || { grep -E "error" /work/make.log | head; exit 1; }
ELF=$(ls "$OUT"/build/debug/*.out); "$TC"/bin/arm-none-eabi-size "$ELF"
"$TC"/bin/arm-none-eabi-nm "$ELF" | grep -E " bootloader_rebootAndInstall$| app_iostream_usart_process_action$"
commander gbl create /work/w1700k_uarttest_$BAUD.gbl --app "$ELF" >/dev/null && ls -l /work/w1700k_uarttest_$BAUD.gbl
