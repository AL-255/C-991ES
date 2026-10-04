/* High-level numeric records for the fx-991ES PLUS C firmware.
 * GPL-3.0-or-later. No firmware execution is used by this implementation. */
#ifndef FX_NUMERIC_H
#define FX_NUMERIC_H
#include <stddef.h>
#include <stdint.h>

typedef struct { uint8_t bytes[10]; } fx_number;
typedef enum {
    FX_NUMBER_DECIMAL = 0, FX_NUMBER_RATIONAL = 2, FX_NUMBER_SURD = 8,
    FX_NUMBER_ERROR = 15, FX_NUMBER_UNSUPPORTED = 16
} fx_number_type;
typedef enum {
    FX_NUMERIC_OK = 0, FX_NUMERIC_INVALID = -1,
    FX_NUMERIC_UNREPRESENTABLE = -2, FX_NUMERIC_UNIMPLEMENTED = -3
} fx_numeric_status;

/* sign * mantissa * 10^(exponent-14); nonzero mantissas have 15 digits.
 * flags stores the optional 0x40 metadata marker in record byte 0. */
typedef struct {
    int sign;
    int exponent;
    uint64_t mantissa;
    uint8_t flags;
} fx_decimal;
typedef struct { int64_t numerator; uint64_t denominator; uint8_t flags; } fx_rational;
typedef enum { FX_ADD, FX_SUBTRACT, FX_MULTIPLY, FX_DIVIDE } fx_binary_op;

fx_number_type fx_number_kind(const fx_number *number);
/* Exact counterpart of 0x1d1a2: invalid first digit or marked sign field. */
int fx_number_has_special_marker(const fx_number *number);
void fx_number_zero(fx_number *out);
void fx_number_error(fx_number *out, unsigned code);
void fx_number_copy(fx_number *out, const fx_number *in);
void fx_number_copy_complex(fx_number out[2], const fx_number in[2]);
fx_numeric_status fx_decimal_decode(fx_decimal *out, const fx_number *in);
fx_numeric_status fx_decimal_encode(fx_number *out, const fx_decimal *in);
/* Decimal literal parsing truncates to the original 15 stored digits. */
fx_numeric_status fx_decimal_parse(fx_number *out, const char *text);
fx_numeric_status fx_decimal_from_integer(fx_number *out, int64_t value);
fx_numeric_status fx_decimal_to_integer(int64_t *out, const fx_number *in);
/* Counterpart of 0x1d08c (R2 is an unsigned byte). */
void fx_decimal_from_u8(fx_number *out, uint8_t value);
/* Returns 0x5000 for error records, matching 0x1cfde. */
int fx_number_exponent(const fx_number *in);
fx_numeric_status fx_decimal_binary(fx_number *out, const fx_number *a,
                                   const fx_number *b, fx_binary_op op);
fx_numeric_status fx_decimal_sqrt(fx_number *out, const fx_number *in);
fx_numeric_status fx_number_to_decimal(fx_number *out, const fx_number *in);
/* 0x1cef0 removes tiny low-mantissa residue; this is not nearest-integer rounding. */
fx_numeric_status fx_decimal_integer_cleanup(fx_number *number);
/* Counterpart of 0x1cabe: zero for integral, 0xf0 for fractional/unsupported. */
int fx_number_fractional_status(const fx_number *number);
/* 0x11110 surd-operand preprocessor: one when a plain decimal admits a
 * short rational in the original continued-fraction recognition interval. */
int fx_number_recognize_rational(fx_rational *out, const fx_number *number);
fx_numeric_status fx_rational_decode(fx_rational *out, const fx_number *in);
fx_numeric_status fx_rational_encode(fx_number *out, const fx_rational *in);
/* Components are coefficient, radicand, denominator for each of two terms. */
fx_numeric_status fx_surd_unpack(fx_number out[6], const fx_number *in);
fx_numeric_status fx_surd_pack(fx_number *out, const fx_number components[6]);
/* Evaluator arithmetic: preserves rational/surd operands in Math context. */
fx_numeric_status fx_number_binary(fx_number *out, const fx_number *a,
                                  const fx_number *b, fx_binary_op op);
fx_numeric_status fx_number_sqrt(fx_number *out, const fx_number *in, int exact_math);
fx_numeric_status fx_number_negate(fx_number *out, const fx_number *in);
fx_numeric_status fx_number_integer_power(fx_number *out, const fx_number *in,
                                        int exponent);
/* 0x1c3fa writes the remainder to operand0 and integral quotient to operand2.
 * The finite decimal workspace may stop before all quotient digits are found. */
fx_numeric_status fx_number_divmod(fx_number *remainder, fx_number *quotient,
                                  const fx_number *dividend, const fx_number *divisor);

#endif
