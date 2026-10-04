/* SPDX-License-Identifier: GPL-3.0-only */
#ifndef FX_KEY_WAIT_H
#define FX_KEY_WAIT_H
#include "fx_keys.h"

/* Semantic state for the emulator's1D802 wait. The two cursor bitmaps and
 * blink fields belong to the host; no CPU registers or stack frame are
 * represented. Framebuffer addresses retain original16-bit wrapping. */
typedef struct {
    uint8_t shown[20];
    uint8_t hidden[20];
    uint16_t framebuffer;
    uint16_t pair_destination;
    uint16_t remaining_transitions;
    uint16_t last_idle_counter;
    uint8_t phase;
    uint8_t cursor_enabled;
    uint8_t period;
    uint8_t countdown;
    uint8_t captured_height;
    uint8_t active;
    uint8_t ready;
} fx_key_wait;

/* Begin a wait and set the emulator host flag8E00=1. Returns0 on success,
 * -1 for invalid arguments, or -2 for a cursor font/height outside the
 * bounded native bitmap domain. Visible cursor fonts6/7/10 are supported;
 * suppressed cursors accept heights0..10. */
int fx_key_wait_begin(fx_platform *platform, fx_key_wait *state,
                       uint16_t pair_destination);
/* One native iteration: blink, timer129A, host-pair test, then increment
 * idle counter8224 only when no key is ready. Returns0 waiting or1 ready.
 * Every new wait consumes this iteration even for a preloaded host key.
 * A ready state is retained until finish; subsequent ticks return1 without
 * repeating the iteration. -1 means inactive; -2 means the height grew
 * into native uncaptured stack bytes, outside this host-state API. */
int fx_key_wait_tick(fx_platform *platform, fx_key_wait *state);
/* Clear8E00, copy the current raw8E01/8E02 pair to the requested data-bus
 * destination, and restore the hidden cursor bitmap even when suppressed.
 * The host pair is not cleared. key may be NULL. Returns0 on completion,
 * -1 without a ready wait, or -2 for unsupported height growth. */
int fx_key_wait_finish(fx_platform *platform, fx_key_wait *state,
                        fx_key_state *key);
#endif
