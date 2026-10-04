/* SPDX-License-Identifier: GPL-3.0-only */
#ifndef FX_PLATFORM_H
#define FX_PLATFORM_H
#include <stddef.h>
#include <stdint.h>

typedef enum {
    FX_MEMORY_OK = 0,
    FX_MEMORY_UNMAPPED = 1,
    FX_MEMORY_READ_ONLY = 2
} fx_memory_status;

/* Data bus for the emulator image. Timing and physical devices are separate.
 * The C implementation has no instruction-fetch or CPU-execution interface. */
typedef struct {
    const uint8_t *rom;
    size_t rom_size;
    uint8_t *ram;                    /* 65536 bytes */
    uint8_t callback_pending;
    fx_memory_status status;
} fx_platform;

uint8_t fx_data_read(fx_platform *platform, uint8_t segment, uint16_t address);
void fx_data_write(fx_platform *platform, uint8_t segment, uint16_t address, uint8_t value);
uint8_t fx_take_callback(fx_platform *platform);
/* Startup data records at 1:f8d0. This is only data initialization, not boot. */
int fx_copy_startup_data(fx_platform *platform);
void fx_timer_start(fx_platform *platform, uint16_t period);
void fx_timer_restart(fx_platform *platform);
uint8_t fx_timer_flags(fx_platform *platform);
uint8_t fx_acquire_busy(fx_platform *platform);
void fx_mark_busy(fx_platform *platform);
void fx_clear_busy(fx_platform *platform);
uint8_t fx_is_busy(fx_platform *platform);
uint8_t fx_secondary_busy(fx_platform *platform);
void fx_configure_key_port(fx_platform *platform);
void fx_configure_interrupt_port(fx_platform *platform);
void fx_configure_display_port(fx_platform *platform);
void fx_display_port_restart(fx_platform *platform);
void fx_display_port_active(fx_platform *platform);
/* 0x542a: peripheral startup writes; CPU delay loops have no bus effects. */
void fx_configure_ports(fx_platform *platform);
void fx_display_port_sleep(fx_platform *platform);
void fx_set_lcd_flag(fx_platform *platform, uint8_t enabled);
void fx_disable_display(fx_platform *platform);
void fx_key_drive_enable(fx_platform *platform);
void fx_key_drive_disable(fx_platform *platform);
void fx_key_select_all(fx_platform *platform);
void fx_key_deselect_all(fx_platform *platform);
uint8_t fx_any_key(fx_platform *platform);
#endif
