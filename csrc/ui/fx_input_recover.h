/* SPDX-License-Identifier: GPL-3.0-only */
#ifndef FX_INPUT_RECOVER_H
#define FX_INPUT_RECOVER_H
#include "../platform/fx_platform.h"

/* Named persistent/local policies from the outer input handler. The display
 * and result are original bus addresses; this context is a host C object. */
typedef struct {
    uint16_t display_address;
    uint16_t result_address;
    uint8_t calculation_mode;
    uint8_t saved_math_result;
    uint8_t return_value;
} fx_input_recovery_context;

/* E67C: after cursor recovery declines, initialize the ordinary editor and
 * restore the saved result, reset mode12, or prepare fresh input. Return0/1
 * matches the native retry choice. -1 propagates malformed/unsupported
 * shared editor/rendering contexts; CPU registers and frames are not used. */
int fx_input_recover_after_error(fx_platform *platform,
                                 fx_input_recovery_context *context);
/* E71E: initialize input, reset result/layout flags and select the context's
 * initial screen. Mutates context.return_value to0. Return0 success,-1 when
 * the shared initializer cannot handle the prepared context. */
int fx_input_reset_context(fx_platform *platform,
                            fx_input_recovery_context *context);
#endif
