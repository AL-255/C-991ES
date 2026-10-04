/* SPDX-License-Identifier: GPL-3.0-only */
#ifndef FX_CURSOR_H
#define FX_CURSOR_H
#include "fx_keys.h"

/* Capture/restore the two framebuffer bytes touched by a cursor on each
 * row. Font height811B is read on each iteration, as in1DA46/1DA88;
 * framebuffer rows have a16-byte stride and packed rows a2-byte stride.
 * Addresses use the original wrapping data bus and may alias. */
void fx_cursor_capture(fx_platform *platform, uint16_t packed, uint16_t framebuffer);
void fx_cursor_restore(fx_platform *platform, uint16_t framebuffer, uint16_t packed);
/* 1D902: advance a prepared blink state. Offset0 is the shown bitmap,
 * offset20 the hidden bitmap,40 the phase,41 the visible gate,42 the
 * framebuffer address,44 the period,45 the countdown and46 a16-bit
 * remaining-transition counter. This advances one native tick; it does
 * not schedule physical time or wait for a key. */
void fx_cursor_tick(fx_platform *platform, uint16_t state);
/* 1DAC2: cursor eligibility from suppression80DD, editor80FB and80FE. */
uint8_t fx_cursor_is_visible(fx_platform *platform);

#endif
