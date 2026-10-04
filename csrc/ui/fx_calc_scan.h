/* SPDX-License-Identifier: GPL-3.0-only */
#ifndef FX_CALC_SCAN_H
#define FX_CALC_SCAN_H
#include "../platform/fx_platform.h"

/* CALC branch of 172F6. Scan the prepared input at 8398 into the physical
 * FF-terminated variable list at 83FE. A variable assigned at the beginning
 * of a colon-separated statement is excluded from later prompts only after
 * that statement ends. This is dependency discovery, not syntax checking.
 * Requires screen80FC.bit6 clear. Returns native0, or negative host errors:
 * -1 invalid platform, -2 SOLVE screen, -3 unterminated input. */
int fx_calc_scan_variables(fx_platform *platform);
#endif
