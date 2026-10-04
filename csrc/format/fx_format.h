/* Readable, high-level result-token formatting. GPL-3.0-or-later. */
#ifndef FX_FORMAT_H
#define FX_FORMAT_H
#include <stddef.h>
#include <stdint.h>
#include "../numeric/fx_numeric.h"

typedef enum {
    FX_FORMAT_OK = 0, FX_FORMAT_INVALID = -1,
    FX_FORMAT_BUFFER_TOO_SMALL = -2, FX_FORMAT_UNIMPLEMENTED = -3
} fx_format_status;
typedef struct {
    uint8_t selection;       /* full8100: low=current0..15, high=previous0..15 */
    uint8_t math_output;     /* resolved permission from C35E */
    uint8_t mixed_fraction;  /* 8107 */
    uint8_t display_mode;    /* 8102: 0 Norm1, 4 Norm2, 8 Fix, 9 Sci */
    uint8_t digits;          /* 8103: Fix places or Sci significant digits */
    uint8_t decimal_dot;     /* 8104: zero is comma, nonzero is dot */
    uint8_t format_context;  /* C060 stack argument0..6; grouping/decimal width */
    uint8_t recurring_style; /* 0 means the firmware default */
} fx_format_options;
typedef struct {
    size_t length;           /* excludes NUL, including on overflow */
    uint8_t kind;            /* native C060 return: DMS1, ENG2..9, decimal10..15 */
    uint8_t recognized;      /* 0 none, 1 rational, 2 pi */
} fx_format_result;

fx_format_options fx_format_default_options(void);
/* The input record is never modified. Output is always NUL-terminated when
 * capacity is nonzero. Overflow is reported and length gives the required
 * output length; no embedded NUL is emitted. */
fx_format_status fx_format_number(const fx_number *number,
                                  const fx_format_options *options,
                                  uint8_t *tokens, size_t capacity,
                                  fx_format_result *result);
/* Decimal-only counterpart of B99C/BA9A/BC4A, bypassing recognition. */
fx_format_status fx_format_decimal(const fx_number *number,
                                   const fx_format_options *options,
                                   uint8_t *tokens, size_t capacity,
                                   fx_format_result *result);
#endif
