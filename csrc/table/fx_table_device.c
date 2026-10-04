/* SPDX-License-Identifier: GPL-3.0-only */
#include "fx_table_presentation.h"
#include "../platform/fx_platform.h"
/* A synchronous prepared5550 device boundary. The host supplies only the
 * external readiness byte; timer/configuration/status writes execute in C. */
int fx_table_poll_device(fx_platform *p, uint8_t readiness)
{
    if (!p || !p->ram) return -3;
    fx_data_write(p, 0, 0x8e00, 2);
    fx_timer_start(p, 0x129a);
    /* Explicit external input, equivalent to device response at5564. */
    p->ram[0x8e00] = readiness;
    int cancelled = fx_data_read(p, 0, 0x8e00) != 0;
    if (cancelled) {
        fx_data_write(p, 0, 0x80f2, 4);
        fx_data_write(p, 0, 0x80f3, 16);
    }
    fx_data_write(p, 0, 0x8e00, 0);
    return cancelled;
}
