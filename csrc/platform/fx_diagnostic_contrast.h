/* SPDX-License-Identifier: GPL-3.0-only */
#ifndef FX_DIAGNOSTIC_CONTRAST_H
#define FX_DIAGNOSTIC_CONTRAST_H
#include "fx_platform.h"

typedef enum {
    FX_DIAGNOSTIC_CONTRAST_WAIT = 0,
    FX_DIAGNOSTIC_CONTRAST_DONE = 1,
    FX_DIAGNOSTIC_CONTRAST_INVALID = -1
} fx_diagnostic_contrast_status;

/* Semantic locals of CCF4. The host owns keyboard-event scheduling; this
 * object has no CPU register, instruction address, stack or RAM local. */
typedef struct {
    uint8_t value;
    uint8_t minimum;
    uint8_t maximum;
    uint8_t expanded;
    uint8_t active;
} fx_diagnostic_contrast_state;

/* CCF4..CD1E: paint the four-line CONTRAST menu and retain contrast8112.
 * Expanded/nonzero selects limits0..31 and displays the hexadecimal value;
 * normal/zero selects4..29. Existing values are not clamped. Returns WAIT
 * before the caller starts its ordinary key controller. */
fx_diagnostic_contrast_status fx_diagnostic_contrast_begin(
    fx_platform *platform, fx_diagnostic_contrast_state *state, uint8_t expanded);
/* CD24..CD1E/CD44: consume an already delivered semantic key token.
 * E3 decreases, E2 increases, E6 finishes. All other tokens retain the value
 * and repeat the native contrast writes. The result stays in host state even
 * if RAM8112 changes while waiting. WAIT means start another key controller;
 * DONE means the caller may continue the diagnostic lifecycle. */
fx_diagnostic_contrast_status fx_diagnostic_contrast_step(
    fx_platform *platform, fx_diagnostic_contrast_state *state, uint8_t token);
/* 739E: paint '<two hexadecimal positions>h' at LCD y8 with font7.
 * Preserve the native unadjusted high nibble, unmasked low position and its
 * signed ASCII comparison for values outside the admitted0..31 range.
 * This sets8121=0 while drawing and leaves8121=1; it does not allocate a
 * temporary text string in calculator RAM. All256 input values are valid. */
fx_diagnostic_contrast_status fx_diagnostic_contrast_draw_value(
    fx_platform *platform, uint8_t value);
#endif
