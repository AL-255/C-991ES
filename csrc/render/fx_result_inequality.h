#ifndef FX_RESULT_INEQUALITY_H
#define FX_RESULT_INEQUALITY_H
#include "fx_render.h"

/* B60E appends the relation surrounding one root. The address is returned
 * unchanged. Tokens are read/written with firmware 16-bit wrapping; a
 * nonterminating destination is bounded at one address-space traversal. */
uint16_t fx_append_inequality_relation(fx_render *render, uint16_t destination,
                                      uint8_t part, uint8_t solution_class);
/* B4B0: equation caption selected by 8135 and the startup pointer table at
 * 8DFA. Write its padded text to destination, clear the frame and draw the
 * last row. Numeric evaluation and B070's enclosing history are separate. */
int fx_display_equation_caption(fx_render *render, uint16_t destination,
                                fx_box *final_box);
/* B754: inequality class 8406, up to three real root records at 8410, 841A,
 * 8424 and the original startup caption table 8DF6. Supports mode75/context1
 * with both result display styles and cached natural viewport reuse.
 * Return1 success,0 formatting/layout failure,-1 unsupported context.
 * Native numeric scratch and inactive metric pool slots are outside the
 * record-format API. CPU stack aliases/oversized stack text are not modeled. */
int fx_display_inequality_result(fx_render *render, fx_box *final_box);
/* 10E34: combine component format kinds for the complete result. */
uint8_t fx_combine_result_kinds(uint8_t first, uint8_t second);
#endif
