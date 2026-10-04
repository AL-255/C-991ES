/* SPDX-License-Identifier: GPL-3.0-only */
#ifndef FX_INPUT_DISPLAY_H
#define FX_INPUT_DISPLAY_H
#include "../platform/fx_platform.h"
/*8282 ordinary linear expression row, including expanded token labels,
 * byte-valued horizontal admission, cursor geometry and end/scroll markers.
 * Host character buffers replace the original temporary CPU stack strings.
 * Return0 success,-1 bounded malformed/unsupported token representation.
 * TABLE range prefixes C674/10FE2 are outside this ordinary entry. */
int fx_input_draw_linear_expression(fx_platform *platform);
#endif
