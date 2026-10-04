/* SPDX-License-Identifier: GPL-3.0-only */
#ifndef FX_INPUT_PREPARE_H
#define FX_INPUT_PREPARE_H
#include "../platform/fx_platform.h"

/* 11072: mode-dependent evaluator input workspace, or zero when disabled. */
uint16_t fx_input_workspace(fx_platform *platform);
/* E7EA: ordinary input has an exported workspace only in an eligible
 * high-bit calculation mode, outside the special result views. */
uint8_t fx_input_needs_export(fx_platform *platform);
/* E7B8: append the single-variable recall suffix in the ordinary screen.
 * Zero on success; -1 bounds an unterminated 64KiB source. */
int fx_input_append_variable_suffix(fx_platform *platform, uint16_t source);
/* 7FCA: equation mode appends '=0' when no comparison operator is present.
 * This uses the ordinary editor, including its capacity/cursor behavior. */
int fx_input_normalize_equation(fx_platform *platform, uint16_t source);
/* E802/E852/E8F0: prepare direct, exported, or saved-solve input. The source
 * address is a named host local; no CPU frame is materialized in RAM.
 * Return1 when ready,0 on a natural-field boundary error,-1 on malformed
 * bounded input. All persistent original RAM writes are retained. */
int fx_input_prepare_direct(fx_platform *platform, uint16_t *source);
int fx_input_prepare_exported(fx_platform *platform, uint16_t *source);
int fx_input_prepare_saved_solve(fx_platform *platform, uint16_t *source);
#endif
