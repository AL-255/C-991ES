/* SPDX-License-Identifier: GPL-3.0-only */
#ifndef FX_RESULT_VERIFY_H
#define FX_RESULT_VERIFY_H
#include "fx_render.h"
#include "../format/fx_format.h"

/* 8000, selected by C060 for a nonerror record in mode137/0x89.
 * Native class1 selects the live pointer at8DF2; every other class selects
 * 8DF4. The default startup pointers spell FALSE and TRUE. Label bytes are
 * copied verbatim, including a null pointer's empty spelling. Selection,
 * recognition, numeric workspaces and display MMIO are not changed here.
 * This record API models the classification's Boolean projection; compact
 * opposite-sign conversion has numeric scratch effects outside this API.
 * Result kind and recognition are0; length excludes the final terminator.
 * A NULL ROM requires rom_size0; RAM labels remain available in that
 * descriptor. Output/capacity conventions match fx_format_number. Finite labels can
 * wrap through the sixteen-bit data map; a nonterminated full-map scan
 * returns UNIMPLEMENTED. Input and output must not overlap. */
fx_format_status fx_format_verify_result(const fx_render *render,
    const fx_number *value, uint8_t *tokens, size_t capacity,
    fx_format_result *result);
#endif
