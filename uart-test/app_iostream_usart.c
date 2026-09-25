// W1700K EFR32 UART speed test: talks at SL_IOSTREAM_USART_VCOM_BAUDRATE, then returns to the
// bootloader on 'B' or unconditionally after 90 s, so a host that cannot hit this rate still gets
// the chip back at the bootloader's 115200.
#include <stdio.h>
#include <string.h>
#include "sl_iostream.h"
#include "sl_iostream_init_instances.h"
#include "sl_iostream_handles.h"
#include "sl_sleeptimer.h"
#include "btl_interface.h"
#include "sl_iostream_usart_vcom_config.h"

#define TEST_WINDOW_MS 90000u

static uint32_t boot_tick;
static uint32_t next_tick_ms = 1000u;
static uint32_t ticks;

static uint32_t elapsed_ms(void)
{
  return sl_sleeptimer_tick_to_ms(sl_sleeptimer_get_tick_count() - boot_tick);
}

static void to_bootloader(const char *why)
{
  printf("\r\n%s -> BOOTLOADER\r\n", why);
  sl_sleeptimer_delay_millisecond(50);
  bootloader_rebootAndInstall();
}

void app_iostream_usart_init(void)
{
  setvbuf(stdout, NULL, _IONBF, 0);
  setvbuf(stdin, NULL, _IONBF, 0);
  sl_iostream_set_default(sl_iostream_vcom_handle);
  boot_tick = sl_sleeptimer_get_tick_count();
  printf("\r\nW1700K-EFR32 UART TEST baud=%lu window=%lus\r\n",
         (unsigned long)SL_IOSTREAM_USART_VCOM_BAUDRATE, (unsigned long)(TEST_WINDOW_MS / 1000u));
}

void app_iostream_usart_process_action(void)
{
  uint32_t ms = elapsed_ms();
  if (ms >= TEST_WINDOW_MS) {
    to_bootloader("TIMEOUT");
  }
  if (ms >= next_tick_ms) {
    printf("TICK %lu\r\n", (unsigned long)++ticks);
    next_tick_ms += 1000u;
  }
  int c = getchar();
  if (c > 0) {
    if (c == 'B') {
      to_bootloader("REQUESTED");
    }
    putchar(c);
  }
}
