/* BASE-N numeric result tokens. GPL-3.0-or-later. */
#ifndef FX_FORMAT_BASE_H
#define FX_FORMAT_BASE_H
#include "fx_format.h"

/* Original158B8. base_mask is the full80FA byte:1 binary,7 octal,9
 * decimal,15 hexadecimal. Nondecimal records produce an empty result;
 * unsupported base settings return FX_FORMAT_UNIMPLEMENTED. kind is0.
 * Input is immutable; required length and bounded NUL termination follow
 * the ordinary formatter API. */
fx_format_status fx_format_base(const fx_number *number, uint8_t base_mask,
                                uint8_t *tokens, size_t capacity,
                                fx_format_result *result);

#endif
