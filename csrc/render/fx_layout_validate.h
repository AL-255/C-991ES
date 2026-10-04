#ifndef FX_LAYOUT_VALIDATE_H
#define FX_LAYOUT_VALIDATE_H
#include "fx_render.h"

/* Display-token spans retain original byte-count wrap. Malformed token
 * streams that would never terminate natively are bounded to one address
 * space traversal here. These functions read ROM/RAM and mutate no state. */
uint8_t fx_parameter_length(const fx_render *render, uint16_t expression,
                             uint8_t parameter_index);                 /* 8B14 */
uint8_t fx_construct_length(const fx_render *render, uint16_t expression); /* 8B9E */
uint8_t fx_parenthesis_length(const fx_render *render, uint16_t expression); /* 8BF8 */
uint8_t fx_field_length(const fx_render *render, uint16_t expression);     /* 8AE0 */
/* A1FE: stop_after_atom is original R2, allow_signed_number is R3. */
uint8_t fx_atom_length(const fx_render *render, uint16_t expression,
                        uint8_t stop_after_atom, uint8_t allow_signed_number);
/* A14E and8A6C return the owning construct/open-parenthesis address.
 * The output byte identifies the parameter or a matched parenthesis. */
uint16_t fx_owning_construct(const fx_render *render, uint16_t position,
                              uint8_t *parameter);
uint16_t fx_parenthesis_start(const fx_render *render, uint16_t position,
                               uint8_t *matched);
/* A2DA reads the expression root from0x812c. */
uint16_t fx_previous_atom_start(const fx_render *render, uint16_t position);
int fx_mixed_whole_valid(const fx_render *render, uint16_t expression);
#endif
