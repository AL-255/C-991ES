/* SPDX-License-Identifier: GPL-3.0-only */
#ifndef FX_ANNUNCIATOR_H
#define FX_ANNUNCIATOR_H
#include "../platform/fx_platform.h"

/* Draw the emulator's003D62 twelve-byte annunciator row at87D0, then copy
 * the entire row toF800. Scalar records8226 and, in modeC4,8408 are immutable.
 * Returns0 on success, -1 for an invalid platform, or the negative scalar
 * classifier status. A classifier failure retains the already cleared row
 * and preceding indicator writes, and does not copy the row to the LCD.
 * Native scalar workspaces 8000..805F and 8640..867B are preserved by the
 * address classifier. CPU stack effects and device timing are outside this API. */
int fx_annunciator_draw(fx_platform *platform);
#endif
