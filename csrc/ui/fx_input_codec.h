/* SPDX-License-Identifier: GPL-3.0-only */
#ifndef FX_INPUT_CODEC_H
#define FX_INPUT_CODEC_H
#include "fx_editor.h"

/* Convert recursive DISPLAY tokens into evaluator INPUT tokens (9ff2).
 * Full export uses full_expression!=0. With full_expression==0, conversion
 * stops at the requested input-token index and maps it to editor cursor8114;
 * the produced prefix retains the native termination behavior.
 * Addresses use the platform's original wrapping bus. Return0 on completion,
 * -1 for a bounded malformed stream rather than a native infinite scan. */
int fx_editor_export_input(fx_platform *platform, uint16_t source,
                           uint16_t destination, uint8_t input_cursor,
                           uint8_t full_expression);
/* 9ee4: explicit parentheses and argument commas must remain within their
 * natural-editor fields. Return1 when allowed,0 and set cursor8114 on a
 * boundary violation, or -1 after a bounded unterminated scan. This is the
 * editor's boundary check; evaluator syntax checking is separate. */
int fx_editor_input_boundaries(fx_platform *platform, uint16_t source);
#endif
