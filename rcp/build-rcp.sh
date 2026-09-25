#!/bin/bash
# Build the SiSDK multiprotocol RCP (OpenThread + Zigbee + BLE HCI over CPC) for the W1700K's EFR32MG21A010F512.
set -euo pipefail
SDK=/simplicity_sdk_2025.6.1
SAMPLE=${SAMPLE:-rcp-uart-802154-blehci}
DEV=EFR32MG21A010F512IM32
TC=$(ls -d /opt/arm-gnu-toolchain-*arm-none-eabi)
W=/work/src-$SAMPLE; OUT=/work/build-$SAMPLE
rm -rf "$W" "$OUT"; cp -r $SDK/protocol/openthread/sample-apps/ot-ncp "$W"
# CPC link encryption off: the HA add-on's cpcd runs with disable_encryption, and ser2net carries plain bytes anyway
sed -i 's/^  - id: ot_ncp_cpc$/  - id: ot_ncp_cpc\n  - id: cpc_security_secondary_none/' "$W/$SAMPLE.slcp"
grep -q "cpc_security_secondary_none" "$W/$SAMPLE.slcp" || { echo "!! could not add cpc_security_secondary_none"; exit 1; }
slc signature trust --sdk $SDK >/dev/null
slc generate --with $DEV --project-file "$W/$SAMPLE.slcp" --export-destination "$OUT" \
  --copy-proj-sources --new-project --toolchain toolchain_gcc --sdk $SDK --output-type makefile >/work/slc-$SAMPLE.log 2>&1 \
  || { tail -30 /work/slc-$SAMPLE.log; exit 1; }

setdef() {  # setdef FILE NAME VALUE : rewrite "#define NAME ..." (commented or not) in a generated config header
  local f="$OUT/config/$1"
  grep -qE "^\s*(//\s*)?#define\s+$2\b" "$f" || { echo "!! $2 not in $1"; return 1; }
  sed -i -E "s|^\s*(//\s*)?#define\s+$2\b.*|#define $2 $3|" "$f"
}
V=sl_cpc_drv_uart_usart_vcom_config.h
setdef $V SL_CPC_DRV_UART_VCOM_BAUDRATE ${BAUD:-115200}
setdef $V SL_CPC_DRV_UART_VCOM_FLOW_CONTROL_TYPE usartHwFlowControlNone
setdef $V SL_CPC_DRV_UART_VCOM_PERIPHERAL USART0
setdef $V SL_CPC_DRV_UART_VCOM_PERIPHERAL_NO 0
setdef $V SL_CPC_DRV_UART_VCOM_TX_PORT gpioPortA
setdef $V SL_CPC_DRV_UART_VCOM_TX_PIN 5
setdef $V SL_CPC_DRV_UART_VCOM_RX_PORT gpioPortA
setdef $V SL_CPC_DRV_UART_VCOM_RX_PIN 6
# no CTS/RTS on the W1700K link
sed -i -E '/#define SL_CPC_DRV_UART_VCOM_(CTS|RTS)_(PORT|PIN)\b/d' "$OUT/config/$V"
[ -f "$OUT/config/sl_board_control_config.h" ] && setdef sl_board_control_config.h SL_BOARD_ENABLE_VCOM 0 || true
[ -f "$OUT/config/sl_rail_util_pti_config.h" ] && setdef sl_rail_util_pti_config.h SL_RAIL_UTIL_PTI_MODE RAIL_PTI_MODE_DISABLED || true
C=sl_clock_manager_oscillator_config.h
[ -f "$OUT/config/$C" ] && { setdef $C SL_CLOCK_MANAGER_HFXO_EN 1; setdef $C SL_CLOCK_MANAGER_HFXO_CTUNE 128 || true; }
C2=sl_clock_manager_tree_config.h
[ -f "$OUT/config/$C2" ] && setdef $C2 SL_CLOCK_MANAGER_DEFAULT_HF_CLOCK_SOURCE SL_CLOCK_MANAGER_DEFAULT_HF_CLOCK_SOURCE_HFXO || true
echo "=== UART config now:"; grep -nE "#define SL_CPC_DRV_UART_VCOM_(BAUD|FLOW|PERIPH|TX_|RX_|CTS|RTS)" "$OUT/config/$V"
echo "=== security:"; grep -hn "#define SL_CPC_SECURITY_ENABLED" "$OUT"/config/*.h || echo "  (no security config = security component absent)"
echo "=== PTI/VCOM/clock:"; grep -hnE "#define (SL_RAIL_UTIL_PTI_MODE|SL_BOARD_ENABLE_VCOM|SL_CLOCK_MANAGER_HFXO_EN|SL_CLOCK_MANAGER_HFXO_CTUNE|SL_CLOCK_MANAGER_DEFAULT_HF_CLOCK_SOURCE) " "$OUT"/config/*.h || true

make -C "$OUT" -f $SAMPLE.Makefile -j"$(nproc)" ARM_GCC_DIR="$TC" >/work/make-$SAMPLE.log 2>&1 || { grep -E "error|overflow|region" /work/make-$SAMPLE.log | head -20; exit 1; }
ELF=$(ls "$OUT"/build/debug/*.out)
"$TC"/bin/arm-none-eabi-size "$ELF"
grep -E "^\s*(FLASH|RAM)\s" "$OUT"/build/debug/*.map | head -4 || true
commander gbl create /work/w1700k_${SAMPLE}_${BAUD:-115200}.gbl --app "$ELF" >/dev/null && ls -l /work/w1700k_${SAMPLE}_${BAUD:-115200}.gbl
