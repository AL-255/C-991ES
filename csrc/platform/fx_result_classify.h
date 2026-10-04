/* SPDX-License-Identifier: GPL-3.0-only */
#ifndef FX_RESULT_CLASSIFY_H
#define FX_RESULT_CLASSIFY_H
#include "fx_platform.h"
#include "../numeric/fx_numeric.h"

typedef struct {
    uint16_t continuation;
    uint8_t classification;
} fx_result_classification;

/* Address-based 1CCF6 classification and its finite numeric workspaces.
 * companion is the incoming secondary operand address saved at 805E.
 * Classes: 1 zero, 2 negative, 4 positive, F0 inadmissible tag. The continuation
 * remains companion on the direct branches; the decimal conversion returns
 * its final low mantissa word. It is needed by consecutive header calls.
 * This interface contains no CPU state and never executes firmware.
 * Sources intersecting the native CPU stack are rejected before mutation.
 * Opposite-sign surds admit canonical BCD components outside the numeric
 * workspaces, with no address wrap; unsupported conversion inputs return
 * UNIMPLEMENTED after only the native argument/load prefix effects. */
fx_numeric_status fx_result_classify_address(fx_platform *platform,
    uint16_t source, uint16_t companion, fx_result_classification *result);
#endif
