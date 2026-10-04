/* SPDX-License-Identifier: GPL-3.0-only */
#ifndef FX_BOOT_H
#define FX_BOOT_H
#include "fx_platform.h"

typedef enum {
    FX_BOOT_READY = 0,
    FX_BOOT_DIAGNOSTIC = 1,
    FX_BOOT_WELCOME = 2,
    FX_BOOT_RESTART = 3,
    FX_BOOT_UNIMPLEMENTED = -1,
    FX_BOOT_MALFORMED = -2
} fx_boot_status;

/* 52e2/52f0: retained-state signature and the original validity checks.
 * This checks ten numeric tags and contrast4..29, not full numeric values. */
void fx_boot_write_signature(fx_platform *platform);
uint8_t fx_boot_retained_state_invalid(fx_platform *platform);
/* 1d77e/1d78a/1d796: clear display input and mode-dependent workspaces. */
void fx_boot_clear_expression(fx_platform *platform);
void fx_boot_clear_exported_input(fx_platform *platform);
void fx_boot_clear_result_workspaces(fx_platform *platform);
/* 1e55e: reset editor/display fields and optionally paint its initial line.
 * action bit7 retains the display expression; low nibble2 paints the default
 * result/title line. Unsupported mode-specific rendering is explicit. */
fx_boot_status fx_boot_initialize_editor(fx_platform *platform, uint8_t action);
/* 1d71c/1d6ec: reset to ROM settings and cold retained-state initialization. */
fx_boot_status fx_boot_reset_settings(fx_platform *platform);
fx_boot_status fx_boot_cold_reset(fx_platform *platform);
/* 40a2: reset transient flags, contrast, editor and workspaces, then flush. */
fx_boot_status fx_boot_default_screen(fx_platform *platform);
/* 6fe6: five-read boot-key probe; zero denotes the 0x7b combination. */
uint8_t fx_boot_probe_welcome_key(fx_platform *platform);
/* D6FE..D730: stack guard data, peripheral setup, retained-state validation
 * and conditional cold reset. Physical CPU registers and delays are omitted. */
fx_boot_status fx_boot_initialize(fx_platform *platform);
/* D730..D7AE: default display and boot-key gates. A diagnostic/welcome
 * response transfers control to the corresponding host event controller;
 * this API does not block while waiting for an external key event. */
fx_boot_status fx_boot_resume(fx_platform *platform);
/* 5338: paint the power-off bitmap and configure the sleep/restart ports.
 * Suppression80DD leaves the state untouched and returns READY. Otherwise
 * RESTART exposes the native6F82 transfer to the host scheduler. */
fx_boot_status fx_boot_prepare_power_off(fx_platform *platform);
/* Reset-entry6F82 startup data copy, F000 initialization and ordinary boot.
 * Diagnostic/welcome branches retain the same explicit event boundaries. */
fx_boot_status fx_boot_reset(fx_platform *platform);
#endif
