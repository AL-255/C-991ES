/* SPDX-License-Identifier: GPL-3.0-only */
#ifndef FX_RESULT_STATUS_WORKFLOW_H
#define FX_RESULT_STATUS_WORKFLOW_H
#include "fx_render.h"
#include "../format/fx_format.h"

/*Prepared C2AA and382E queries. No renderer writes; answer must be separate from renderer. Native byte preferences remain
 *byte-valued. Replay parsing rejects malformed/out-of-store histories. */
int fx_result_equation_is_vertex(const fx_render *render, uint8_t *answer);
int fx_result_equation_rectangular(const fx_render *render, uint8_t *answer);
/*C060 component formatting: errors, BASE, VERIFY, then paired fixed budget.
 *Ordinary compact SURD formatter preparation commits the existing six
 *ordered components and DMS/exact-SURD spelling stages; selection15
 *bypasses ordinary decimal preparation. Input is copied before pool writes.
 *other numeric scratch remains separate.
 *Output512-byte field and result must be separate from input and renderer. */
int fx_format_status_component(fx_render *render, const fx_number *value,
                              uint8_t context, uint8_t output[512],
                              fx_format_result *result);
/*B070 priority and composition for equation69 and additional paired modes.
 *Already supported ordinary modes delegate existing controllers. Source is
 *read companion-first, with a word then even-aligned eight-byte tail.
 *Keep source, replay, framebuffer, settings, history and result buffers
 *disjoint. Numeric scratch and original CPU local/frame aliases are not
 *represented. Natural modes without persistent output return-1.
 *Legacy paired text<=16 (including BASE BIN), caption text<=16 and
 *numeric special text<26 keep native private fields
 *bounded; wider forms return-1, preserving preceding documented writes.
 *Return1 completion,0 format/layout failure,-1 untranslated/invalid host. */
int fx_display_status_workflow(fx_render *render, uint16_t source, fx_box *box);
#endif
